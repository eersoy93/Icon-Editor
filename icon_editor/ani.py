"""Reading and writing of Windows animated cursor (.ani) files.

An ANI file is a RIFF container of form type ``ACON``::

    RIFF 'ACON'
        [LIST 'INFO' [INAM <title>] [IART <author>]]
        anih <ANIHEADER>
        [rate <DWORD per step, in jiffies>]
        [seq  <DWORD frame index per step>]
        LIST 'fram'
            icon <complete .ico/.cur file>
            ...
"""

import struct

from . import ico
from .model import IconDocument, IconFrame, KIND_ANI, DEFAULT_RATE

AF_ICON = 0x1
AF_SEQUENCE = 0x2

_ANIH = struct.Struct("<9I")


class AniFormatError(ValueError):
    pass


def is_ani(data):
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"ACON"


def _iter_chunks(data, start, end):
    pos = start
    while pos + 8 <= end:
        tag = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body_start = pos + 8
        body_end = body_start + size
        if body_end > end:
            # Tolerate a truncated final chunk.
            body_end = end
        yield tag, body_start, body_end
        pos = body_end + (size & 1)


def _decode_string(raw):
    raw = raw.split(b"\0", 1)[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def read(data):
    """Parse .ani file contents into an IconDocument."""
    data = bytes(data)
    if not is_ani(data):
        raise AniFormatError("Not an animated cursor (RIFF/ACON) file")
    riff_end = min(len(data), 8 + struct.unpack("<I", data[4:8])[0])
    header = None
    rates = None
    seq = None
    icons = []
    title = author = ""
    for tag, s, e in _iter_chunks(data, 12, riff_end):
        if tag == b"anih":
            if e - s < _ANIH.size:
                raise AniFormatError("Truncated anih chunk")
            header = _ANIH.unpack(data[s:s + _ANIH.size])
        elif tag == b"rate":
            rates = list(struct.unpack("<%dI" % ((e - s) // 4), data[s:s + (e - s) // 4 * 4]))
        elif tag == b"seq ":
            seq = list(struct.unpack("<%dI" % ((e - s) // 4), data[s:s + (e - s) // 4 * 4]))
        elif tag == b"LIST" and e - s >= 4:
            list_type = data[s:s + 4]
            for sub, ss, se in _iter_chunks(data, s + 4, e):
                if list_type == b"fram" and sub == b"icon":
                    icons.append(data[ss:se])
                elif list_type == b"INFO" and sub == b"INAM":
                    title = _decode_string(data[ss:se])
                elif list_type == b"INFO" and sub == b"IART":
                    author = _decode_string(data[ss:se])
    if header is None:
        raise AniFormatError("Missing anih chunk")
    if not icons:
        raise AniFormatError("Animated cursor contains no frames")

    _cb, n_frames, n_steps, _w, _h, _bpp, _planes, disp_rate, flags = header
    if not flags & AF_ICON and not all(ico.detect_type(b) for b in icons):
        raise AniFormatError("Raw bitmap frames are not supported")

    decoded = []
    for blob in icons:
        try:
            _rtype, images = ico.read(blob)
        except ico.IconFormatError as exc:
            raise AniFormatError("Invalid frame: %s" % exc)
        decoded.append(images)

    if seq is None or not flags & AF_SEQUENCE:
        seq = list(range(len(decoded)))
    if n_steps and len(seq) > n_steps:
        seq = seq[:n_steps]
    frames = []
    for step, index in enumerate(seq):
        if index >= len(decoded):
            raise AniFormatError("Sequence refers to missing frame %d" % index)
        rate = rates[step] if rates and step < len(rates) else disp_rate
        frames.append(IconFrame([img.copy() for img in decoded[index]], rate or DEFAULT_RATE))
    return IconDocument(KIND_ANI, frames, title=title, author=author)


def _chunk(tag, payload):
    out = tag + struct.pack("<I", len(payload)) + payload
    if len(payload) & 1:
        out += b"\0"
    return out


def write(doc):
    """Serialise an IconDocument as .ani bytes (frames stored as cursors)."""
    frames = doc.frames
    if not frames:
        raise ValueError("An animated cursor needs at least one frame")
    for frame in frames:
        if not frame.images:
            raise ValueError("Every frame must contain at least one image")
        if frame.rate <= 0:
            raise ValueError("Frame rates must be positive")
    body = bytearray()
    info = b""
    if doc.title:
        info += _chunk(b"INAM", doc.title.encode("utf-8") + b"\0")
    if doc.author:
        info += _chunk(b"IART", doc.author.encode("utf-8") + b"\0")
    if info:
        body += _chunk(b"LIST", b"INFO" + info)
    n = len(frames)
    rates = [f.rate for f in frames]
    body += _chunk(b"anih", _ANIH.pack(_ANIH.size, n, n, 0, 0, 0, 0, rates[0], AF_ICON))
    if any(r != rates[0] for r in rates):
        body += _chunk(b"rate", struct.pack("<%dI" % n, *rates))
    fram = bytearray(b"fram")
    for frame in frames:
        fram += _chunk(b"icon", ico.write(frame.images, ico.TYPE_CUR))
    body += _chunk(b"LIST", bytes(fram))
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"ACON" + bytes(body)
