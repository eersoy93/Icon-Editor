"""Minimal pure-Python PNG encoder/decoder working on RGBA buffers.

Only the standard library (``zlib`` and ``struct``) is used so that the
editor has no third-party dependencies.
"""

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PNGError(ValueError):
    """Raised when PNG data cannot be decoded."""


def is_png(data):
    return bytes(data[:8]) == PNG_SIGNATURE


def _chunk(kind, payload):
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def encode_png(width, height, rgba, level=9):
    """Encode an RGBA ``bytes``/``bytearray`` buffer into PNG bytes.

    ``level`` is the zlib compression level (0-9).
    """
    if len(rgba) != width * height * 4:
        raise ValueError("RGBA buffer size does not match dimensions")
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type: None
        raw += rgba[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (PNG_SIGNATURE + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), level))
            + _chunk(b"IEND", b""))


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


def _unfilter(data, width, height, bits_per_pixel):
    """Reverse PNG scanline filters, returning a list of raw row bytearrays."""
    row_bytes = (width * bits_per_pixel + 7) // 8
    bpp = max(1, bits_per_pixel // 8)
    rows = []
    prev = bytearray(row_bytes)
    pos = 0
    for _ in range(height):
        if pos + 1 + row_bytes > len(data):
            raise PNGError("Truncated PNG image data")
        ftype = data[pos]
        line = bytearray(data[pos + 1:pos + 1 + row_bytes])
        pos += 1 + row_bytes
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
            raise PNGError("Unknown PNG filter type %d" % ftype)
        rows.append(line)
        prev = line
    return rows


def _samples(row, count, depth):
    """Return ``count`` integer samples (8-bit range for depth >= 8)."""
    if depth == 8:
        return list(row[:count])
    if depth == 16:
        return [row[i * 2] for i in range(count)]  # keep the high byte
    out = []
    mask = (1 << depth) - 1
    per_byte = 8 // depth
    for i in range(count):
        byte = row[i // per_byte]
        shift = 8 - depth * (i % per_byte + 1)
        out.append((byte >> shift) & mask)
    return out


def decode_png(data):
    """Decode PNG bytes. Returns ``(width, height, rgba_bytearray)``."""
    data = bytes(data)
    if not is_png(data):
        raise PNGError("Not a PNG file")
    pos = 8
    width = height = None
    depth = ctype = interlace = None
    palette = []
    trns = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, ctype, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", payload)
        elif kind == b"PLTE":
            palette = [tuple(payload[i:i + 3]) for i in range(0, len(payload) - 2, 3)]
        elif kind == b"tRNS":
            trns = payload
        elif kind == b"IDAT":
            idat += payload
        elif kind == b"IEND":
            break
    if width is None:
        raise PNGError("Missing IHDR chunk")
    if interlace:
        raise PNGError("Interlaced PNG images are not supported")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None or depth not in (1, 2, 4, 8, 16):
        raise PNGError("Unsupported PNG format")
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise PNGError("Corrupt PNG data: %s" % exc)
    rows = _unfilter(raw, width, height, depth * channels)

    # Colour key transparency for grey / truecolour images.
    key = None
    if trns is not None and ctype == 0 and len(trns) >= 2:
        key = struct.unpack(">H", trns[:2])
    elif trns is not None and ctype == 2 and len(trns) >= 6:
        key = struct.unpack(">HHH", trns[:6])

    gray_scale = 255 // ((1 << depth) - 1) if depth < 8 else 1
    out = bytearray(width * height * 4)
    o = 0
    count = width * channels
    for row in rows:
        s = _samples(row, count, depth)
        if key is not None:
            if depth == 16:
                full = [struct.unpack(">H", bytes(row[i * 2:i * 2 + 2]))[0]
                        for i in range(count)]
            else:
                full = s
        for x in range(width):
            a = 255
            if ctype == 6:
                r, g, b, a = s[x * 4:x * 4 + 4]
            elif ctype == 2:
                r, g, b = s[x * 3:x * 3 + 3]
                if key is not None and tuple(full[x * 3:x * 3 + 3]) == key:
                    a = 0
            elif ctype == 4:
                r = g = b = s[x * 2]
                a = s[x * 2 + 1]
            elif ctype == 0:
                r = g = b = s[x] * gray_scale
                if key is not None and (full[x],) == key:
                    a = 0
            else:  # indexed colour
                idx = s[x]
                r, g, b = palette[idx] if idx < len(palette) else (0, 0, 0)
                if trns is not None and idx < len(trns):
                    a = trns[idx]
            out[o:o + 4] = bytes((r, g, b, a))
            o += 4
    return width, height, out
