"""High-level loading and saving of documents and single images."""

import os

from . import ani, ico, png
from .model import IconDocument, IconFrame, IconImage, KIND_ANI, KIND_CUR, KIND_ICO

EXTENSIONS = {KIND_ICO: ".ico", KIND_CUR: ".cur", KIND_ANI: ".ani"}


def kind_from_path(path):
    ext = os.path.splitext(path)[1].lower()
    for kind, kind_ext in EXTENSIONS.items():
        if ext == kind_ext:
            return kind
    return None


def loads(data):
    """Parse the contents of an .ico, .cur or .ani file."""
    if ani.is_ani(data):
        return ani.read(data)
    rtype, images = ico.read(data)
    kind = KIND_CUR if rtype == ico.TYPE_CUR else KIND_ICO
    return IconDocument(kind, [IconFrame(images)])


def dumps(doc):
    """Serialise a document according to its kind."""
    if doc.kind == KIND_ANI:
        return ani.write(doc)
    rtype = ico.TYPE_CUR if doc.kind == KIND_CUR else ico.TYPE_ICO
    return ico.write(doc.images, rtype)


def load(path):
    with open(path, "rb") as fh:
        return loads(fh.read())


def save(doc, path):
    data = dumps(doc)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def import_png(path):
    with open(path, "rb") as fh:
        width, height, rgba = png.decode(fh.read())
    return IconImage(width, height, rgba)


def export_png(image, path):
    with open(path, "wb") as fh:
        fh.write(png.encode(image.width, image.height, image.pixels))
