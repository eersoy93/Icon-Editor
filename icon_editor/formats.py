"""Data model and codecs for Windows icon (.ico), cursor (.cur) and
animated cursor (.ani) files.

Everything is implemented with the Python standard library only.

Model overview
--------------
* :class:`IconImage` - a single RGBA bitmap (max. 256x256) with an optional
  cursor hotspot.
* :class:`Frame` - a set of images (usually the same picture in different
  sizes) plus a display rate used for animated cursors.
* :class:`IconDocument` - a list of frames together with the file kind
  (``"ico"``, ``"cur"`` or ``"ani"``) and optional ANI metadata.
"""

import os
import struct

from .png import decode_png, encode_png, is_png

MAX_SIZE = 256
DEFAULT_RATE = 10  # jiffies (1/60 s) per frame for animated cursors

ICO_TYPE = 1
CUR_TYPE = 2

AF_ICON = 0x1
AF_SEQUENCE = 0x2


class IconFormatError(ValueError):
    """Raised when a file cannot be parsed."""


def scale_rgba(width, height, rgba, new_width, new_height):
    """Nearest-neighbour scale an RGBA buffer. Returns a new bytearray."""
    out = bytearray(new_width * new_height * 4)
    for y in range(new_height):
        row = (y * height // new_height) * width
        for x in range(new_width):
            si = (row + x * width // new_width) * 4
            di = (y * new_width + x) * 4
            out[di:di + 4] = rgba[si:si + 4]
    return out


class IconImage:
    """A single RGBA bitmap."""

    def __init__(self, width, height, pixels=None, hotspot=(0, 0)):
        if not (1 <= width <= MAX_SIZE and 1 <= height <= MAX_SIZE):
            raise ValueError("Image size must be between 1 and %d" % MAX_SIZE)
        self.width = width
        self.height = height
        if pixels is None:
            pixels = bytearray(width * height * 4)
        elif len(pixels) != width * height * 4:
            raise ValueError("Pixel buffer size does not match dimensions")
        self.pixels = bytearray(pixels)
        self.hotspot = (min(max(0, hotspot[0]), width - 1),
                        min(max(0, hotspot[1]), height - 1))

    def copy(self):
        return IconImage(self.width, self.height, self.pixels, self.hotspot)

    def get_pixel(self, x, y):
        i = (y * self.width + x) * 4
        return tuple(self.pixels[i:i + 4])

    def set_pixel(self, x, y, rgba):
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 4
            self.pixels[i:i + 4] = bytes(rgba)

    def scaled(self, width, height):
        """Return a nearest-neighbour scaled copy of this image."""
        out = IconImage(width, height,
                        scale_rgba(self.width, self.height, self.pixels, width, height))
        out.hotspot = (self.hotspot[0] * width // self.width,
                       self.hotspot[1] * height // self.height)
        return out

    def __eq__(self, other):
        return (isinstance(other, IconImage) and self.width == other.width
                and self.height == other.height and self.pixels == other.pixels
                and self.hotspot == other.hotspot)

    def __repr__(self):
        return "IconImage(%dx%d, hotspot=%r)" % (self.width, self.height, self.hotspot)


class Frame:
    """One frame of a document: a list of images of different sizes."""

    def __init__(self, images=None, rate=DEFAULT_RATE):
        self.images = list(images or [])
        self.rate = rate

    def copy(self):
        return Frame([img.copy() for img in self.images], self.rate)

    def __eq__(self, other):
        return (isinstance(other, Frame) and self.images == other.images)


class IconDocument:
    """An editable icon, cursor or animated cursor."""

    def __init__(self, kind="ico", frames=None, title="", author=""):
        if kind not in ("ico", "cur", "ani"):
            raise ValueError("Unknown document kind %r" % kind)
        self.kind = kind
        self.frames = list(frames or [])
        self.title = title
        self.author = author

    @classmethod
    def new(cls, kind="ico", sizes=((32, 32),)):
        images = [IconImage(w, h) for w, h in sizes]
        return cls(kind, [Frame(images)])

    def copy(self):
        return IconDocument(self.kind, [f.copy() for f in self.frames],
                            self.title, self.author)

    @property
    def is_cursor(self):
        return self.kind in ("cur", "ani")


# ---------------------------------------------------------------------------
# DIB (BMP without file header) decoding / encoding
# ---------------------------------------------------------------------------

def _mask_shift(mask):
    if not mask:
        return 0, 0
    shift = 0
    while not (mask >> shift) & 1:
        shift += 1
    bits = 0
    while (mask >> (shift + bits)) & 1:
        bits += 1
    return shift, bits


def _extract(value, mask):
    shift, bits = _mask_shift(mask)
    if not bits:
        return 0
    v = (value & mask) >> shift
    return v * 255 // ((1 << bits) - 1)


def _decode_dib(data, cursor_hotspot=(0, 0)):
    if len(data) < 40:
        raise IconFormatError("Bitmap header too short")
    (hdr_size, width, height2, _planes, bpp, compression, _size_image,
     _xppm, _yppm, clr_used, _clr_imp) = struct.unpack("<IiiHHIIiiII", data[:40])
    if hdr_size < 40 or hdr_size > len(data):
        raise IconFormatError("Unsupported bitmap header")
    height = abs(height2) // 2
    if width <= 0 or height <= 0 or width > MAX_SIZE or height > MAX_SIZE:
        raise IconFormatError("Unsupported bitmap size %dx%d" % (width, height))
    if compression not in (0, 3):
        raise IconFormatError("Compressed bitmaps are not supported")
    if bpp not in (1, 4, 8, 16, 24, 32):
        raise IconFormatError("Unsupported bit depth %d" % bpp)

    pos = hdr_size
    masks = None
    if compression == 3:
        if hdr_size >= 52:
            masks = struct.unpack("<III", data[40:52])
        else:
            masks = struct.unpack("<III", data[pos:pos + 12])
            pos += 12
    elif bpp == 16:
        masks = (0x7C00, 0x03E0, 0x001F)

    palette = []
    if bpp <= 8:
        n = clr_used or (1 << bpp)
        for i in range(n):
            b, g, r, _ = data[pos + i * 4:pos + i * 4 + 4]
            palette.append((r, g, b))
        pos += n * 4

    xor_stride = ((width * bpp + 31) // 32) * 4
    and_stride = ((width + 31) // 32) * 4
    xor_data = data[pos:pos + xor_stride * height]
    and_data = data[pos + xor_stride * height:pos + xor_stride * height + and_stride * height]
    if len(xor_data) < xor_stride * height:
        raise IconFormatError("Truncated bitmap data")
    has_mask = len(and_data) >= and_stride * height
    bottom_up = height2 > 0

    img = IconImage(width, height, hotspot=cursor_hotspot)
    px = img.pixels
    any_alpha = False
    for row in range(height):
        y = height - 1 - row if bottom_up else row
        line = xor_data[row * xor_stride:(row + 1) * xor_stride]
        for x in range(width):
            a = 255
            if bpp == 32:
                b, g, r, a = line[x * 4:x * 4 + 4]
                if masks is not None:
                    v = struct.unpack("<I", line[x * 4:x * 4 + 4])[0]
                    r, g, b = (_extract(v, m) for m in masks)
                if a:
                    any_alpha = True
            elif bpp == 24:
                b, g, r = line[x * 3:x * 3 + 3]
            elif bpp == 16:
                v = line[x * 2] | (line[x * 2 + 1] << 8)
                r, g, b = (_extract(v, m) for m in masks)
            else:
                per_byte = 8 // bpp
                byte = line[x // per_byte]
                shift = 8 - bpp * (x % per_byte + 1)
                idx = (byte >> shift) & ((1 << bpp) - 1)
                r, g, b = palette[idx] if idx < len(palette) else (0, 0, 0)
            i = (y * width + x) * 4
            px[i:i + 4] = bytes((r, g, b, a))

    use_mask = has_mask and (bpp != 32 or not any_alpha)
    for row in range(height):
        y = height - 1 - row if bottom_up else row
        mline = and_data[row * and_stride:(row + 1) * and_stride] if has_mask else b""
        for x in range(width):
            i = (y * width + x) * 4 + 3
            if use_mask:
                transparent = (mline[x // 8] >> (7 - x % 8)) & 1
                px[i] = 0 if transparent else 255
            elif bpp == 32 and not any_alpha:
                px[i] = 255
    return img


def _encode_dib(img):
    w, h = img.width, img.height
    xor_stride = w * 4
    and_stride = ((w + 31) // 32) * 4
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                         (xor_stride + and_stride) * h, 0, 0, 0, 0)
    xor = bytearray()
    andm = bytearray()
    px = img.pixels
    for y in range(h - 1, -1, -1):
        mrow = bytearray(and_stride)
        for x in range(w):
            i = (y * w + x) * 4
            r, g, b, a = px[i:i + 4]
            xor += bytes((b, g, r, a))
            if a == 0:
                mrow[x // 8] |= 0x80 >> (x % 8)
        andm += mrow
    return header + bytes(xor) + bytes(andm)


# ---------------------------------------------------------------------------
# ICO / CUR
# ---------------------------------------------------------------------------

def read_ico(data):
    """Parse ICO or CUR bytes. Returns ``(kind, [IconImage, ...])``."""
    data = bytes(data)
    if len(data) < 6:
        raise IconFormatError("File too short")
    reserved, itype, count = struct.unpack("<HHH", data[:6])
    if reserved != 0 or itype not in (ICO_TYPE, CUR_TYPE):
        raise IconFormatError("Not an icon or cursor file")
    if count == 0:
        raise IconFormatError("File contains no images")
    images = []
    for n in range(count):
        entry = data[6 + n * 16:6 + (n + 1) * 16]
        if len(entry) < 16:
            raise IconFormatError("Truncated directory entry")
        _w, _h, _colors, _res, f1, f2, size, offset = struct.unpack("<BBBBHHII", entry)
        blob = data[offset:offset + size]
        if len(blob) < min(size, 8) or not blob:
            raise IconFormatError("Image %d points outside of the file" % n)
        hotspot = (f1, f2) if itype == CUR_TYPE else (0, 0)
        if is_png(blob):
            w, h, rgba = decode_png(blob, MAX_SIZE)
            images.append(IconImage(w, h, rgba, hotspot))
        else:
            images.append(_decode_dib(blob, hotspot))
    return ("cur" if itype == CUR_TYPE else "ico"), images


def write_ico(images, cursor=False):
    """Serialise images to ICO (or CUR when ``cursor`` is true) bytes.

    Images of 256 pixels in either dimension are stored as PNG, everything
    else as 32-bit BMP with an AND mask for maximum compatibility.
    """
    if not images:
        raise ValueError("At least one image is required")
    blobs = []
    for img in images:
        if img.width >= MAX_SIZE or img.height >= MAX_SIZE:
            blobs.append(encode_png(img.width, img.height, img.pixels))
        else:
            blobs.append(_encode_dib(img))
    out = bytearray(struct.pack("<HHH", 0, CUR_TYPE if cursor else ICO_TYPE, len(images)))
    offset = 6 + 16 * len(images)
    for img, blob in zip(images, blobs):
        if cursor:
            f1, f2 = img.hotspot
        else:
            f1, f2 = 1, 32
        out += struct.pack("<BBBBHHII", img.width % 256, img.height % 256, 0, 0,
                           f1, f2, len(blob), offset)
        offset += len(blob)
    for blob in blobs:
        out += blob
    return bytes(out)


# ---------------------------------------------------------------------------
# ANI (RIFF "ACON")
# ---------------------------------------------------------------------------

def _iter_chunks(data, start, end):
    pos = start
    while pos + 8 <= end:
        cid, size = struct.unpack("<4sI", data[pos:pos + 8])
        body_start = pos + 8
        body_end = min(body_start + size, end)
        yield cid, body_start, body_end
        pos = body_start + size + (size & 1)


def _cstr(raw):
    return raw.split(b"\0", 1)[0].decode("latin-1")


def read_ani(data):
    """Parse ANI bytes into an :class:`IconDocument`.

    Steps are expanded according to the optional ``seq`` chunk so that every
    frame of the returned document corresponds to one displayed step.
    """
    data = bytes(data)
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"ACON":
        raise IconFormatError("Not an animated cursor file")
    end = min(len(data), 8 + struct.unpack("<I", data[4:8])[0])
    header = None
    rates = None
    seq = None
    raw_frames = []
    title = author = ""
    for cid, s, e in _iter_chunks(data, 12, end):
        if cid == b"anih":
            if e - s < 36:
                raise IconFormatError("Invalid anih chunk")
            header = struct.unpack("<9I", data[s:s + 36])
        elif cid == b"rate":
            rates = list(struct.unpack("<%dI" % ((e - s) // 4), data[s:s + (e - s) // 4 * 4]))
        elif cid == b"seq ":
            seq = list(struct.unpack("<%dI" % ((e - s) // 4), data[s:s + (e - s) // 4 * 4]))
        elif cid == b"LIST" and e - s >= 4:
            ltype = data[s:s + 4]
            for sub, ss, se in _iter_chunks(data, s + 4, e):
                if ltype == b"fram" and sub == b"icon":
                    raw_frames.append(data[ss:se])
                elif ltype == b"INFO" and sub == b"INAM":
                    title = _cstr(data[ss:se])
                elif ltype == b"INFO" and sub == b"IART":
                    author = _cstr(data[ss:se])
    if header is None:
        raise IconFormatError("Missing anih chunk")
    _cb, n_frames, n_steps, _w, _h, _bits, _planes, disp_rate, flags = header
    if not flags & AF_ICON:
        raise IconFormatError("Raw-bitmap animated cursors are not supported")
    if not raw_frames:
        raise IconFormatError("Animated cursor contains no frames")
    frames = [read_ico(raw)[1] for raw in raw_frames]

    if seq is None:
        seq = list(range(len(frames)))
    if n_steps and n_steps < len(seq):
        seq = seq[:n_steps]
    out = []
    for step, idx in enumerate(seq):
        if idx >= len(frames):
            raise IconFormatError("Sequence refers to missing frame %d" % idx)
        rate = rates[step] if rates and step < len(rates) else disp_rate
        out.append(Frame([img.copy() for img in frames[idx]], rate or DEFAULT_RATE))
    return IconDocument("ani", out, title, author)


def _chunk(cid, payload):
    out = struct.pack("<4sI", cid, len(payload)) + payload
    if len(payload) & 1:
        out += b"\0"
    return out


def write_ani(doc):
    """Serialise an :class:`IconDocument` to ANI bytes.

    Identical frames are stored only once and referenced via a ``seq``
    chunk; per-step rates are written to a ``rate`` chunk when they differ.
    """
    if not doc.frames:
        raise ValueError("At least one frame is required")
    unique = []
    seq = []
    for frame in doc.frames:
        for i, u in enumerate(unique):
            if u == frame:
                seq.append(i)
                break
        else:
            unique.append(frame)
            seq.append(len(unique) - 1)
    rates = [f.rate for f in doc.frames]
    uniform = all(r == rates[0] for r in rates)
    use_seq = seq != list(range(len(seq)))
    flags = AF_ICON | (AF_SEQUENCE if use_seq else 0)

    body = bytearray(b"ACON")
    if doc.title or doc.author:
        info = bytearray(b"INFO")
        if doc.title:
            info += _chunk(b"INAM", doc.title.encode("latin-1", "replace") + b"\0")
        if doc.author:
            info += _chunk(b"IART", doc.author.encode("latin-1", "replace") + b"\0")
        body += _chunk(b"LIST", bytes(info))
    body += _chunk(b"anih", struct.pack("<9I", 36, len(unique), len(seq), 0, 0, 0, 0,
                                        rates[0], flags))
    if not uniform:
        body += _chunk(b"rate", struct.pack("<%dI" % len(rates), *rates))
    if use_seq:
        body += _chunk(b"seq ", struct.pack("<%dI" % len(seq), *seq))
    fram = bytearray(b"fram")
    for frame in unique:
        fram += _chunk(b"icon", write_ico(frame.images, cursor=True))
    body += _chunk(b"LIST", bytes(fram))
    return b"RIFF" + struct.pack("<I", len(body)) + bytes(body)


# ---------------------------------------------------------------------------
# High level helpers
# ---------------------------------------------------------------------------

def load_document(path):
    """Load an .ico, .cur, .ani or .png file into an :class:`IconDocument`."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] == b"RIFF":
        return read_ani(data)
    if is_png(data):
        w, h, rgba = decode_png(data, MAX_SIZE)
        return IconDocument("ico", [Frame([IconImage(w, h, rgba)])])
    kind, images = read_ico(data)
    return IconDocument(kind, [Frame(images)])


def document_to_bytes(doc, kind=None):
    kind = kind or doc.kind
    if kind == "ani":
        return write_ani(doc)
    if kind not in ("ico", "cur"):
        raise ValueError("Unknown kind %r" % kind)
    return write_ico(doc.frames[0].images, cursor=(kind == "cur"))


def save_document(doc, path, kind=None):
    """Save ``doc`` to ``path``. ``kind`` defaults to the file extension."""
    if kind is None:
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        kind = ext if ext in ("ico", "cur", "ani") else doc.kind
    data = document_to_bytes(doc, kind)
    with open(path, "wb") as fh:
        fh.write(data)
    return kind
