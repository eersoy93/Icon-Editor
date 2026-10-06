import io
import os
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from icon_editor import ani, fileio, ico, png  # noqa: E402
from icon_editor.model import (  # noqa: E402
    IconDocument, IconFrame, IconImage, KIND_ANI, KIND_CUR, KIND_ICO,
)

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional cross-check
    Image = None


def make_image(w, h, hotspot=(0, 0)):
    img = IconImage(w, h, hotspot=hotspot)
    for y in range(h):
        for x in range(w):
            a = 0 if (x + y) % 5 == 0 else (255 if x % 2 else 128)
            img.set_pixel(x, y, (x * 7 % 256, y * 11 % 256, (x + y) % 256, a))
    # Fully transparent pixels are normalised to black by the encoder mask.
    for i in range(0, len(img.pixels), 4):
        if img.pixels[i + 3] == 0:
            img.pixels[i:i + 3] = b"\0\0\0"
    return img


class PNGTests(unittest.TestCase):
    def test_roundtrip(self):
        img = make_image(13, 7)
        data = png.encode(13, 7, img.pixels)
        self.assertTrue(png.is_png(data))
        self.assertEqual(png.decode(data), (13, 7, img.pixels))

    def _png(self, w, h, depth, ctype, raw, extra=b"", interlace=0):
        def chunk(tag, payload):
            return (struct.pack(">I", len(payload)) + tag + payload
                    + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))
        ihdr = struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, interlace)
        return (png.SIGNATURE + chunk(b"IHDR", ihdr) + extra
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

    def test_palette_with_transparency(self):
        def chunk(tag, payload):
            return (struct.pack(">I", len(payload)) + tag + payload
                    + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))
        extra = chunk(b"PLTE", b"\xff\x00\x00\x00\xff\x00") + chunk(b"tRNS", b"\x00")
        # 2x2, 1-bit indices: row0 = [0, 1], row1 = [1, 0]
        raw = b"\x00\x40\x00\x80"
        w, h, px = png.decode(self._png(2, 2, 1, 3, raw, extra))
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(bytes(px), bytes([255, 0, 0, 0, 0, 255, 0, 255,
                                           0, 255, 0, 255, 255, 0, 0, 0]))

    def test_filters_rgb(self):
        # Sub filter on the first row, Up on the second, Paeth on the third.
        rows = [
            b"\x01" + bytes([10, 20, 30, 5, 5, 5]),
            b"\x02" + bytes([1, 1, 1, 1, 1, 1]),
            b"\x04" + bytes([0, 0, 0, 0, 0, 0]),
        ]
        w, h, px = png.decode(self._png(2, 3, 8, 2, b"".join(rows)))
        self.assertEqual(px[0:8], bytes([10, 20, 30, 255, 15, 25, 35, 255]))
        self.assertEqual(px[8:16], bytes([11, 21, 31, 255, 16, 26, 36, 255]))
        self.assertEqual(px[16:24], bytes([11, 21, 31, 255, 16, 26, 36, 255]))

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_decode_pillow_interlaced(self):
        im = Image.new("RGBA", (9, 9))
        for y in range(9):
            for x in range(9):
                im.putpixel((x, y), (x * 20, y * 20, 100, 255 - x * y))
        buf = io.BytesIO()
        im.save(buf, "PNG", interlace=1)
        w, h, px = png.decode(buf.getvalue())
        self.assertEqual(bytes(px), im.tobytes())

    def test_rejects_garbage(self):
        with self.assertRaises(png.PNGError):
            png.decode(b"not a png")


class ICOTests(unittest.TestCase):
    def test_roundtrip_ico_multiple_sizes(self):
        images = [make_image(16, 16), make_image(33, 20), make_image(256, 256)]
        data = ico.write(images, ico.TYPE_ICO)
        rtype, back = ico.read(data)
        self.assertEqual(rtype, ico.TYPE_ICO)
        self.assertEqual(back, images)
        # 256x256 is PNG-compressed, smaller ones are DIBs.
        offset = struct.unpack_from("<I", data, 6 + 16 * 2 + 12)[0]
        self.assertTrue(png.is_png(data[offset:]))

    def test_roundtrip_cur_hotspot(self):
        images = [make_image(32, 32, hotspot=(5, 9))]
        rtype, back = ico.read(ico.write(images, ico.TYPE_CUR))
        self.assertEqual(rtype, ico.TYPE_CUR)
        self.assertEqual(back[0].hotspot, (5, 9))
        self.assertEqual(back, images)

    def _dib_icon(self, bpp, w, h, palette, xor_rows, and_rows):
        header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, bpp, 0, 0, 0, 0, len(palette), 0)
        pal = b"".join(bytes((b, g, r, 0)) for (r, g, b) in palette)
        blob = header + pal + b"".join(reversed(xor_rows)) + b"".join(reversed(and_rows))
        return struct.pack("<HHH", 0, 1, 1) + struct.pack(
            "<BBBBHHII", w, h, len(palette), 0, 1, bpp, len(blob), 22) + blob

    def test_read_4bpp_with_and_mask(self):
        palette = [(0, 0, 0), (255, 0, 0), (0, 0, 255)] + [(0, 0, 0)] * 13
        xor_rows = [bytes([0x12, 0, 0, 0]), bytes([0x21, 0, 0, 0])]
        and_rows = [bytes([0x00, 0, 0, 0]), bytes([0x40, 0, 0, 0])]
        _, images = ico.read(self._dib_icon(4, 2, 2, palette, xor_rows, and_rows))
        img = images[0]
        self.assertEqual(img.get_pixel(0, 0), (255, 0, 0, 255))
        self.assertEqual(img.get_pixel(1, 0), (0, 0, 255, 255))
        self.assertEqual(img.get_pixel(0, 1), (0, 0, 255, 255))
        self.assertEqual(img.get_pixel(1, 1), (0, 0, 0, 0))

    def test_read_24bpp(self):
        xor_rows = [bytes([255, 0, 0, 0, 255, 0]) + b"\0\0", bytes([0, 0, 255, 9, 9, 9]) + b"\0\0"]
        and_rows = [b"\0\0\0\0", b"\x80\0\0\0"]
        _, images = ico.read(self._dib_icon(24, 2, 2, [], xor_rows, and_rows))
        img = images[0]
        self.assertEqual(img.get_pixel(0, 0), (0, 0, 255, 255))
        self.assertEqual(img.get_pixel(1, 0), (0, 255, 0, 255))
        self.assertEqual(img.get_pixel(0, 1), (0, 0, 0, 0))
        self.assertEqual(img.get_pixel(1, 1), (9, 9, 9, 255))

    def test_rejects_bad_offsets(self):
        bad = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 16, 16, 0, 0, 1, 32, 999, 22)
        with self.assertRaises(ico.IconFormatError):
            ico.read(bad)
        with self.assertRaises(ico.IconFormatError):
            ico.read(b"garbage")

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_pillow_reads_our_ico(self):
        img = make_image(32, 32)
        im = Image.open(io.BytesIO(ico.write([img], ico.TYPE_ICO)))
        self.assertEqual(im.size, (32, 32))
        self.assertEqual(im.convert("RGBA").tobytes(), bytes(img.pixels))

    @unittest.skipIf(Image is None, "Pillow not installed")
    def test_we_read_pillow_ico(self):
        im = Image.new("RGBA", (48, 48), (10, 200, 30, 255))
        im.putpixel((3, 4), (0, 0, 0, 0))
        buf = io.BytesIO()
        im.save(buf, "ICO", sizes=[(48, 48), (16, 16)])
        _, images = ico.read(buf.getvalue())
        sizes = sorted((i.width, i.height) for i in images)
        self.assertEqual(sizes, [(16, 16), (48, 48)])
        big = [i for i in images if i.width == 48][0]
        self.assertEqual(big.get_pixel(0, 0), (10, 200, 30, 255))
        self.assertEqual(big.get_pixel(3, 4)[3], 0)


class ANITests(unittest.TestCase):
    def test_roundtrip(self):
        frames = [
            IconFrame([make_image(32, 32, (1, 2))], rate=5),
            IconFrame([make_image(32, 32, (3, 4)), make_image(16, 16, (1, 1))], rate=12),
        ]
        doc = IconDocument(KIND_ANI, frames, title="Busy", author="Me")
        data = ani.write(doc)
        self.assertTrue(ani.is_ani(data))
        self.assertEqual(struct.unpack("<I", data[4:8])[0], len(data) - 8)
        self.assertEqual(ani.read(data), doc)

    def test_uniform_rate_has_no_rate_chunk(self):
        doc = IconDocument(KIND_ANI, [IconFrame([make_image(8, 8)], 7)] * 3)
        data = ani.write(doc)
        self.assertNotIn(b"rate", data)
        self.assertEqual([f.rate for f in ani.read(data).frames], [7, 7, 7])

    def test_sequence_is_expanded(self):
        cur_a = ico.write([make_image(4, 4)], ico.TYPE_CUR)
        cur_b = ico.write([IconImage(4, 4)], ico.TYPE_CUR)

        def chunk(tag, payload):
            return tag + struct.pack("<I", len(payload)) + payload + (b"\0" if len(payload) & 1 else b"")
        anih = struct.pack("<9I", 36, 2, 3, 0, 0, 0, 0, 6, ani.AF_ICON | ani.AF_SEQUENCE)
        body = (chunk(b"anih", anih) + chunk(b"seq ", struct.pack("<3I", 1, 0, 1))
                + chunk(b"rate", struct.pack("<3I", 1, 2, 3))
                + chunk(b"LIST", b"fram" + chunk(b"icon", cur_a) + chunk(b"icon", cur_b)))
        data = b"RIFF" + struct.pack("<I", len(body) + 4) + b"ACON" + body
        doc = ani.read(data)
        self.assertEqual(len(doc.frames), 3)
        self.assertEqual([f.rate for f in doc.frames], [1, 2, 3])
        self.assertEqual(doc.frames[0].images[0], IconImage(4, 4))
        self.assertEqual(doc.frames[1].images[0], make_image(4, 4))

    def test_rejects_garbage(self):
        with self.assertRaises(ani.AniFormatError):
            ani.read(b"RIFF\x04\0\0\0ACON")


class FileIOTests(unittest.TestCase):
    def test_save_and_load_all_kinds(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kind in (KIND_ICO, KIND_CUR, KIND_ANI):
                doc = IconDocument.new(kind, [(16, 16), (32, 32)])
                doc.images[0].set_pixel(1, 1, (1, 2, 3, 255))
                path = os.path.join(tmp, "test" + fileio.EXTENSIONS[kind])
                fileio.save(doc, path)
                self.assertEqual(fileio.kind_from_path(path), kind)
                self.assertEqual(fileio.load(path), doc)

    def test_png_import_export(self):
        img = make_image(20, 10)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.png")
            fileio.export_png(img, path)
            self.assertEqual(fileio.import_png(path).pixels, img.pixels)


if __name__ == "__main__":
    unittest.main()
