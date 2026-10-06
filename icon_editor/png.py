"""Minimal pure-Python PNG encoder/decoder (RGBA in, RGBA out).

Used for PNG-compressed entries inside .ico/.cur files (common for 256x256
images) and for importing/exporting single images.
"""

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Adam7 passes: (x start, y start, x step, y step)
_ADAM7 = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)

_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PNGError(ValueError):
    pass


def is_png(data):
    return data[:8] == SIGNATURE


def _chunk(tag, payload):
    crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)


def encode(width, height, rgba):
    """Encode straight RGBA pixels as an 8-bit RGBA PNG."""
    if len(rgba) != width * height * 4:
        raise PNGError("Pixel buffer has wrong length")
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: None
        raw += rgba[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def _paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(data, offset, rows, row_bytes, bpp):
    """Undo PNG scanline filters; returns (list of rows, new offset)."""
    out = []
    prev = bytearray(row_bytes)
    for _ in range(rows):
        if offset + 1 + row_bytes > len(data):
            raise PNGError("Truncated image data")
        ftype = data[offset]
        line = bytearray(data[offset + 1:offset + 1 + row_bytes])
        offset += 1 + row_bytes
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(bpp, row_bytes):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(row_bytes):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(row_bytes):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(row_bytes):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        else:
            raise PNGError("Unknown filter type %d" % ftype)
        out.append(line)
        prev = line
    return out, offset


def _samples(line, width, channels, depth):
    """Yield integer samples from a scanline, scaled to 0..255 (or raw index)."""
    count = width * channels
    if depth == 8:
        return list(line[:count])
    if depth == 16:
        return [line[i * 2] for i in range(count)]
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    result = []
    for i in range(count):
        byte = line[i // per_byte]
        shift = 8 - depth * (i % per_byte + 1)
        result.append((byte >> shift) & mask)
    return result


def decode(data):
    """Decode a PNG file. Returns (width, height, rgba bytearray)."""
    if not is_png(data):
        raise PNGError("Not a PNG file")
    pos = 8
    width = height = None
    depth = ctype = interlace = None
    palette = b""
    trns = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length, tag = struct.unpack(">I4s", data[pos:pos + 8])
        payload = data[pos + 8:pos + 8 + length]
        if len(payload) != length:
            raise PNGError("Truncated chunk")
        pos += 12 + length
        if tag == b"IHDR":
            width, height, depth, ctype, comp, filt, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if comp != 0 or filt != 0:
                raise PNGError("Unsupported PNG compression/filter method")
            if ctype not in _CHANNELS:
                raise PNGError("Unsupported PNG colour type %d" % ctype)
        elif tag == b"PLTE":
            palette = bytes(payload)
        elif tag == b"tRNS":
            trns = bytes(payload)
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
    if width is None:
        raise PNGError("Missing IHDR chunk")
    if width <= 0 or height <= 0:
        raise PNGError("Invalid PNG dimensions")
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise PNGError("Corrupt PNG data: %s" % exc)

    channels = _CHANNELS[ctype]
    bits_pp = channels * depth
    bpp = max(1, bits_pp // 8)
    out = bytearray(width * height * 4)

    maxval = (1 << depth) - 1 if depth < 8 else 255
    scale = (lambda v: v * 255 // maxval) if depth < 8 and ctype != 3 else (lambda v: v)

    trns_key = None
    if trns is not None and ctype in (0, 2):
        if ctype == 0 and len(trns) >= 2:
            trns_key = (struct.unpack(">H", trns[:2])[0],)
        elif ctype == 2 and len(trns) >= 6:
            trns_key = struct.unpack(">HHH", trns[:6])
        if trns_key is not None and depth == 16:
            trns_key = None  # 16-bit samples are reduced to 8 bits; ignore key

    passes = _ADAM7 if interlace == 1 else ((0, 0, 1, 1),)
    offset = 0
    for xs, ys, dx, dy in passes:
        pw = (width - xs + dx - 1) // dx
        ph = (height - ys + dy - 1) // dy
        if pw <= 0 or ph <= 0:
            continue
        row_bytes = (pw * bits_pp + 7) // 8
        rows, offset = _unfilter(raw, offset, ph, row_bytes, bpp)
        for ry, line in enumerate(rows):
            y = ys + ry * dy
            s = _samples(line, pw, channels, depth)
            for rx in range(pw):
                x = xs + rx * dx
                v = s[rx * channels:(rx + 1) * channels]
                if ctype == 0:
                    g = scale(v[0])
                    a = 255
                    if trns_key is not None and v[0] == trns_key[0]:
                        a = 0
                    px = (g, g, g, a)
                elif ctype == 2:
                    a = 255
                    if trns_key is not None and tuple(v) == trns_key:
                        a = 0
                    px = (v[0], v[1], v[2], a)
                elif ctype == 3:
                    idx = v[0]
                    if idx * 3 + 3 > len(palette):
                        raise PNGError("Palette index out of range")
                    a = trns[idx] if trns is not None and idx < len(trns) else 255
                    px = (palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2], a)
                elif ctype == 4:
                    g = scale(v[0])
                    px = (g, g, g, scale(v[1]))
                else:
                    px = (v[0], v[1], v[2], v[3])
                i = (y * width + x) * 4
                out[i:i + 4] = bytes(px)
    return width, height, out
