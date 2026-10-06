import os
import struct
import tempfile
import unittest
import zlib

from icon_editor.formats import (
    Frame, IconDocument, IconFormatError, IconImage, load_document, read_ani,
    read_ico, save_document, write_ani, write_ico,
)
from icon_editor.png import decode_png, encode_png


def sample_image(w, h, hotspot=(0, 0)):
    img = IconImage(w, h, hotspot=hotspot)
    for y in range(h):
        for x in range(w):
            a = 0 if (x + y) % 5 == 0 else (255 if x % 2 else 128)
            img.set_pixel(x, y, (x * 7 % 256, y * 11 % 256, (x ^ y) % 256, a))
    return img


class PNGTests(unittest.TestCase):
    def test_round_trip(self):
        img = sample_image(13, 7)
        data = encode_png(13, 7, img.pixels)
        w, h, px = decode_png(data)
        self.assertEqual((w, h), (13, 7))
        self.assertEqual(px, img.pixels)

    def _png(self, w, h, ctype, depth, raw_rows, extra=b""):
        def chunk(k, p):
            return (struct.pack(">I", len(p)) + k + p
                    + struct.pack(">I", zlib.crc32(k + p) & 0xFFFFFFFF))
        raw = b"".join(raw_rows)
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, 0))
                + extra + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    def test_filters_and_rgb(self):
        # Row 0 with Sub filter, row 1 with Up filter, row 2 with Paeth.
        rows = [b"\x01" + bytes([10, 20, 30, 5, 5, 5]),
                b"\x02" + bytes([1, 1, 1, 1, 1, 1]),
                b"\x04" + bytes([0, 0, 0, 0, 0, 0])]
        w, h, px = decode_png(self._png(2, 3, 2, 8, rows))
        self.assertEqual(tuple(px[0:4]), (10, 20, 30, 255))
        self.assertEqual(tuple(px[4:8]), (15, 25, 35, 255))
        self.assertEqual(tuple(px[8:12]), (11, 21, 31, 255))
        self.assertEqual(tuple(px[16:20]), (11, 21, 31, 255))

    def test_palette_with_transparency(self):
        def chunk(k, p):
            return (struct.pack(">I", len(p)) + k + p
                    + struct.pack(">I", zlib.crc32(k + p) & 0xFFFFFFFF))
        extra = chunk(b"PLTE", bytes([255, 0, 0, 0, 255, 0])) + chunk(b"tRNS", b"\x00")
        rows = [b"\x00" + bytes([0b01000000])]
        w, h, px = decode_png(self._png(2, 1, 3, 1, rows, extra))
        self.assertEqual(tuple(px), (255, 0, 0, 0, 0, 255, 0, 255))


class ICOTests(unittest.TestCase):
    def test_ico_round_trip(self):
        images = [sample_image(16, 16), sample_image(32, 32), sample_image(48, 48)]
        kind, out = read_ico(write_ico(images))
        self.assertEqual(kind, "ico")
        self.assertEqual(out, images)

    def test_256_uses_png(self):
        img = sample_image(256, 256)
        data = write_ico([img])
        offset = struct.unpack("<I", data[18:22])[0]
        self.assertEqual(data[offset:offset + 4], b"\x89PNG")
        self.assertEqual(data[6], 0)  # width 256 stored as 0
        self.assertEqual(read_ico(data)[1], [img])

    def test_cur_hotspot(self):
        img = sample_image(32, 32, hotspot=(5, 9))
        kind, out = read_ico(write_ico([img], cursor=True))
        self.assertEqual(kind, "cur")
        self.assertEqual(out[0].hotspot, (5, 9))

    def test_paletted_bmp_with_mask(self):
        w = h = 8
        header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 1, 0, 0, 0, 0, 2, 0)
        palette = bytes([0, 0, 0, 0, 255, 255, 255, 0])
        xor = b"".join(bytes([0b10101010, 0, 0, 0]) for _ in range(h))
        andm = b"".join(bytes([0b00000001, 0, 0, 0]) for _ in range(h))
        blob = header + palette + xor + andm
        data = struct.pack("<HHH", 0, 1, 1) + struct.pack(
            "<BBBBHHII", w, h, 2, 0, 1, 1, len(blob), 22) + blob
        _, imgs = read_ico(data)
        img = imgs[0]
        self.assertEqual(img.get_pixel(0, 0), (255, 255, 255, 255))
        self.assertEqual(img.get_pixel(1, 0), (0, 0, 0, 255))
        self.assertEqual(img.get_pixel(7, 3)[3], 0)

    def test_invalid(self):
        with self.assertRaises(IconFormatError):
            read_ico(b"garbage data")


class ANITests(unittest.TestCase):
    def test_round_trip_with_sequence_and_rates(self):
        a = Frame([sample_image(32, 32, (3, 4))], rate=5)
        b = Frame([sample_image(16, 16)], rate=8)
        doc = IconDocument("ani", [a, b, a.copy()], title="Title", author="Me")
        doc.frames[2].rate = 12
        data = write_ani(doc)
        self.assertIn(b"seq ", data)
        self.assertIn(b"rate", data)
        out = read_ani(data)
        self.assertEqual(len(out.frames), 3)
        self.assertEqual([f.rate for f in out.frames], [5, 8, 12])
        self.assertEqual(out.frames[0].images, a.images)
        self.assertEqual(out.frames[1].images, b.images)
        self.assertEqual(out.frames[0].images[0].hotspot, (3, 4))
        self.assertEqual((out.title, out.author), ("Title", "Me"))

    def test_simple_ani(self):
        doc = IconDocument("ani", [Frame([sample_image(32, 32)]),
                                   Frame([sample_image(32, 32).scaled(32, 32)])])
        doc.frames[1].images[0].set_pixel(0, 0, (1, 2, 3, 255))
        data = write_ani(doc)
        self.assertNotIn(b"seq ", data)
        out = read_ani(data)
        self.assertEqual([f.images for f in out.frames], [f.images for f in doc.frames])


class FileTests(unittest.TestCase):
    def test_save_and_load_by_extension(self):
        doc = IconDocument.new("ico", [(16, 16), (32, 32)])
        doc.frames[0].images[0].set_pixel(1, 1, (9, 8, 7, 255))
        with tempfile.TemporaryDirectory() as tmp:
            for ext in ("ico", "cur", "ani"):
                path = os.path.join(tmp, "test." + ext)
                self.assertEqual(save_document(doc, path), ext)
                loaded = load_document(path)
                self.assertEqual(loaded.kind, ext)
                self.assertEqual(loaded.frames[0].images, doc.frames[0].images)
            png = os.path.join(tmp, "x.png")
            with open(png, "wb") as fh:
                fh.write(encode_png(2, 2, bytes(16)))
            self.assertEqual(load_document(png).frames[0].images[0].width, 2)


if __name__ == "__main__":
    unittest.main()
