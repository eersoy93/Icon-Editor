"""Reading and writing of Windows icon (.ico) and cursor (.cur) files.

Both formats share the same container: an ICONDIR header followed by
ICONDIRENTRY records and the image data. Each image is either a PNG stream
or a DIB (BITMAPINFOHEADER + colour table + XOR bitmap + AND mask) whose
header stores twice the real height.
"""

import struct

from . import png
from .model import IconImage, MAX_SIZE

TYPE_ICO = 1
TYPE_CUR = 2

_DIR = struct.Struct("<HHH")
_ENTRY = struct.Struct("<BBBBHHII")
_BIH = struct.Struct("<IiiHHIIiiII")

BI_RGB = 0
BI_BITFIELDS = 3


class IconFormatError(ValueError):
    pass


def _mask_shift(mask):
    """Return (shift, max value) for a BI_BITFIELDS colour mask."""
    if mask == 0:
        return 0, 0
    shift = 0
    while not (mask >> shift) & 1:
        shift += 1
    return shift, mask >> shift


def _decode_dib(data, hotspot):
    if len(data) < 16:
        raise IconFormatError("Truncated bitmap header")
    header_size = struct.unpack("<I", data[:4])[0]
    if header_size < 40 or len(data) < header_size:
        raise IconFormatError("Unsupported bitmap header (size %d)" % header_size)
    (_, width, height2, _planes, bpp, compression, _size_image, _xppm, _yppm,
     clr_used, _clr_important) = _BIH.unpack(data[:40])
    top_down = height2 < 0
    height = abs(height2) // 2
    if not (1 <= width <= MAX_SIZE and 1 <= height <= MAX_SIZE):
        raise IconFormatError("Unsupported bitmap size %dx%d" % (width, height))
    if bpp not in (1, 4, 8, 16, 24, 32):
        raise IconFormatError("Unsupported bit depth %d" % bpp)
    if compression not in (BI_RGB, BI_BITFIELDS):
        raise IconFormatError("Unsupported bitmap compression %d" % compression)

    pos = header_size
    masks = None
    if compression == BI_BITFIELDS:
        if bpp not in (16, 32):
            raise IconFormatError("BI_BITFIELDS requires 16 or 32 bits per pixel")
        if header_size >= 52:
            masks = struct.unpack("<III", data[40:52])
        else:
            if pos + 12 > len(data):
                raise IconFormatError("Truncated colour masks")
            masks = struct.unpack("<III", data[pos:pos + 12])
            pos += 12
    elif bpp == 16:
        masks = (0x7C00, 0x03E0, 0x001F)

    palette = []
    if bpp <= 8:
        count = clr_used or (1 << bpp)
        count = min(count, 1 << bpp)
        if pos + count * 4 > len(data):
            raise IconFormatError("Truncated colour table")
        for i in range(count):
            b, g, r = data[pos + i * 4:pos + i * 4 + 3]
            palette.append((r, g, b))
        pos += count * 4
        palette += [(0, 0, 0)] * ((1 << bpp) - len(palette))

    xor_stride = ((width * bpp + 31) // 32) * 4
    and_stride = ((width + 31) // 32) * 4
    xor_data = data[pos:pos + xor_stride * height]
    if len(xor_data) < xor_stride * height:
        raise IconFormatError("Truncated bitmap data")
    pos += xor_stride * height
    and_data = data[pos:pos + and_stride * height]
    has_and = len(and_data) >= and_stride * height

    if masks is not None:
        decoders = [_mask_shift(m) for m in masks]

    out = bytearray(width * height * 4)
    for row in range(height):
        y = row if top_down else height - 1 - row
        line = xor_data[row * xor_stride:(row + 1) * xor_stride]
        for x in range(width):
            if bpp <= 8:
                per_byte = 8 // bpp
                byte = line[x // per_byte]
                shift = 8 - bpp * (x % per_byte + 1)
                r, g, b = palette[(byte >> shift) & ((1 << bpp) - 1)]
                a = 255
            elif bpp == 24:
                b, g, r = line[x * 3:x * 3 + 3]
                a = 255
            else:
                if bpp == 16:
                    value = struct.unpack("<H", line[x * 2:x * 2 + 2])[0]
                else:
                    value = struct.unpack("<I", line[x * 4:x * 4 + 4])[0]
                if masks is not None:
                    channels = []
                    for shift, maxv in decoders:
                        v = (value >> shift) & maxv if maxv else 0
                        channels.append(v * 255 // maxv if maxv else 0)
                    r, g, b = channels
                    a = (value >> 24) & 0xFF if bpp == 32 else 255
                else:
                    b, g, r, a = line[x * 4:x * 4 + 4]
            i = (y * width + x) * 4
            out[i:i + 4] = bytes((r, g, b, a))

    alpha_used = bpp == 32 and any(out[3::4])
    if not alpha_used:
        for row in range(height):
            y = row if top_down else height - 1 - row
            line = and_data[row * and_stride:(row + 1) * and_stride] if has_and else b""
            for x in range(width):
                transparent = bool(line) and (line[x >> 3] >> (7 - (x & 7))) & 1
                i = (y * width + x) * 4 + 3
                out[i] = 0 if transparent else 255
                if transparent:
                    out[i - 3:i] = b"\0\0\0"
    return IconImage(width, height, out, hotspot)


def _decode_png(data, hotspot):
    try:
        width, height, rgba = png.decode(data)
    except png.PNGError as exc:
        raise IconFormatError(str(exc))
    if width > MAX_SIZE or height > MAX_SIZE:
        raise IconFormatError("Unsupported image size %dx%d" % (width, height))
    return IconImage(width, height, rgba, hotspot)


def detect_type(data):
    """Return TYPE_ICO, TYPE_CUR or None for the given file contents."""
    if len(data) < 6:
        return None
    reserved, rtype, count = _DIR.unpack(data[:6])
    if reserved != 0 or rtype not in (TYPE_ICO, TYPE_CUR) or count == 0:
        return None
    return rtype


def read(data):
    """Parse .ico/.cur file contents.

    Returns ``(type, images)`` where type is TYPE_ICO or TYPE_CUR.
    """
    data = bytes(data)
    rtype = detect_type(data)
    if rtype is None:
        raise IconFormatError("Not an icon or cursor file")
    count = _DIR.unpack(data[:6])[2]
    if len(data) < 6 + count * _ENTRY.size:
        raise IconFormatError("Truncated icon directory")
    images = []
    for n in range(count):
        (w, h, _colors, _res, planes_or_hx, bpp_or_hy, size,
         offset) = _ENTRY.unpack_from(data, 6 + n * _ENTRY.size)
        if offset + size > len(data) or size == 0:
            raise IconFormatError("Image %d lies outside the file" % n)
        blob = data[offset:offset + size]
        hotspot = (planes_or_hx, bpp_or_hy) if rtype == TYPE_CUR else (0, 0)
        if png.is_png(blob):
            img = _decode_png(blob, hotspot)
        else:
            img = _decode_dib(blob, hotspot)
        images.append(img)
    return rtype, images


def _encode_dib(img):
    w, h = img.width, img.height
    xor_stride = w * 4
    and_stride = ((w + 31) // 32) * 4
    xor = bytearray(xor_stride * h)
    and_mask = bytearray(and_stride * h)
    src = img.pixels
    for row in range(h):
        y = h - 1 - row  # bottom-up
        for x in range(w):
            s = (y * w + x) * 4
            r, g, b, a = src[s:s + 4]
            d = row * xor_stride + x * 4
            xor[d:d + 4] = bytes((b, g, r, a))
            if a == 0:
                and_mask[row * and_stride + (x >> 3)] |= 0x80 >> (x & 7)
    header = _BIH.pack(40, w, h * 2, 1, 32, BI_RGB, len(xor) + len(and_mask), 0, 0, 0, 0)
    return header + bytes(xor) + bytes(and_mask)


def write(images, rtype=TYPE_ICO, png_min_size=256):
    """Serialise images to .ico (TYPE_ICO) or .cur (TYPE_CUR) bytes.

    Images whose width or height is at least ``png_min_size`` are stored
    PNG-compressed (as Windows Vista+ does for 256x256 icons); all others
    are stored as 32-bit DIBs with an AND mask for compatibility.
    """
    if rtype not in (TYPE_ICO, TYPE_CUR):
        raise ValueError("Invalid resource type")
    if not images:
        raise ValueError("An icon must contain at least one image")
    if len(images) > 0xFFFF:
        raise ValueError("Too many images")
    blobs = []
    for img in images:
        if max(img.width, img.height) >= png_min_size:
            blobs.append(png.encode(img.width, img.height, img.pixels))
        else:
            blobs.append(_encode_dib(img))
    out = bytearray(_DIR.pack(0, rtype, len(images)))
    offset = 6 + _ENTRY.size * len(images)
    for img, blob in zip(images, blobs):
        if rtype == TYPE_CUR:
            field1, field2 = img.hotspot
        else:
            field1, field2 = 1, 32
        out += _ENTRY.pack(
            img.width & 0xFF, img.height & 0xFF, 0, 0, field1, field2, len(blob), offset
        )
        offset += len(blob)
    for blob in blobs:
        out += blob
    return bytes(out)
