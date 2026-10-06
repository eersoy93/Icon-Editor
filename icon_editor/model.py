"""In-memory document model for icons, cursors and animated cursors.

Pixels are stored as a flat ``bytearray`` of straight (non-premultiplied)
RGBA values, row by row from the top-left corner.
"""

import copy

KIND_ICO = "ico"
KIND_CUR = "cur"
KIND_ANI = "ani"
KINDS = (KIND_ICO, KIND_CUR, KIND_ANI)

MIN_SIZE = 1
MAX_SIZE = 256

# Default display rate of animated cursors, in jiffies (1/60 second).
DEFAULT_RATE = 10


def _check_size(width, height):
    if not (MIN_SIZE <= width <= MAX_SIZE and MIN_SIZE <= height <= MAX_SIZE):
        raise ValueError(
            "Image size must be between %d and %d pixels, got %dx%d"
            % (MIN_SIZE, MAX_SIZE, width, height)
        )


class IconImage:
    """A single bitmap of an icon or cursor, with an optional hotspot."""

    def __init__(self, width, height, pixels=None, hotspot=(0, 0)):
        _check_size(width, height)
        self.width = width
        self.height = height
        if pixels is None:
            pixels = bytearray(width * height * 4)
        elif len(pixels) != width * height * 4:
            raise ValueError("Pixel buffer has wrong length")
        self.pixels = bytearray(pixels)
        self.hotspot = (0, 0)
        self.set_hotspot(*hotspot)

    def set_hotspot(self, x, y):
        self.hotspot = (
            max(0, min(self.width - 1, int(x))),
            max(0, min(self.height - 1, int(y))),
        )

    def get_pixel(self, x, y):
        i = (y * self.width + x) * 4
        return tuple(self.pixels[i:i + 4])

    def set_pixel(self, x, y, rgba):
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 4
            self.pixels[i:i + 4] = bytes(rgba)

    def in_bounds(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def copy(self):
        return IconImage(self.width, self.height, self.pixels, self.hotspot)

    def clear(self, rgba=(0, 0, 0, 0)):
        self.pixels[:] = bytes(rgba) * (self.width * self.height)

    def flood_fill(self, x, y, rgba):
        """Fill the 4-connected area of identical colour containing (x, y)."""
        if not self.in_bounds(x, y):
            return
        target = self.get_pixel(x, y)
        rgba = tuple(rgba)
        if target == rgba:
            return
        stack = [(x, y)]
        while stack:
            px, py = stack.pop()
            if self.get_pixel(px, py) != target:
                continue
            # Scan-line fill for speed.
            left = px
            while left > 0 and self.get_pixel(left - 1, py) == target:
                left -= 1
            right = px
            while right < self.width - 1 and self.get_pixel(right + 1, py) == target:
                right += 1
            for cx in range(left, right + 1):
                self.set_pixel(cx, py, rgba)
                if py > 0 and self.get_pixel(cx, py - 1) == target:
                    stack.append((cx, py - 1))
                if py < self.height - 1 and self.get_pixel(cx, py + 1) == target:
                    stack.append((cx, py + 1))

    def flip_horizontal(self):
        w, h = self.width, self.height
        out = bytearray(len(self.pixels))
        for y in range(h):
            for x in range(w):
                s = (y * w + x) * 4
                d = (y * w + (w - 1 - x)) * 4
                out[d:d + 4] = self.pixels[s:s + 4]
        self.pixels = out
        self.set_hotspot(w - 1 - self.hotspot[0], self.hotspot[1])

    def flip_vertical(self):
        w, h = self.width, self.height
        stride = w * 4
        out = bytearray(len(self.pixels))
        for y in range(h):
            d = (h - 1 - y) * stride
            out[d:d + stride] = self.pixels[y * stride:(y + 1) * stride]
        self.pixels = out
        self.set_hotspot(self.hotspot[0], h - 1 - self.hotspot[1])

    def rotate_clockwise(self):
        w, h = self.width, self.height
        out = bytearray(len(self.pixels))
        # New image is h wide and w tall; (x, y) -> (h - 1 - y, x)
        for y in range(h):
            for x in range(w):
                s = (y * w + x) * 4
                d = (x * h + (h - 1 - y)) * 4
                out[d:d + 4] = self.pixels[s:s + 4]
        hx, hy = self.hotspot
        self.width, self.height = h, w
        self.pixels = out
        self.set_hotspot(h - 1 - hy, hx)

    def shift(self, dx, dy):
        """Move the content by (dx, dy) pixels, wrapping around the edges."""
        w, h = self.width, self.height
        out = bytearray(len(self.pixels))
        for y in range(h):
            for x in range(w):
                s = (y * w + x) * 4
                d = (((y + dy) % h) * w + (x + dx) % w) * 4
                out[d:d + 4] = self.pixels[s:s + 4]
        self.pixels = out

    def resized(self, width, height):
        """Return a copy scaled to the given size.

        Down-scaling averages the covered source pixels (alpha weighted);
        up-scaling uses nearest neighbour to keep pixel art crisp.
        """
        _check_size(width, height)
        sw, sh = self.width, self.height
        src = self.pixels
        out = bytearray(width * height * 4)
        for y in range(height):
            y0 = y * sh // height
            y1 = max(y0 + 1, (y + 1) * sh // height)
            for x in range(width):
                x0 = x * sw // width
                x1 = max(x0 + 1, (x + 1) * sw // width)
                r = g = b = a = 0
                n = 0
                for sy in range(y0, y1):
                    base = sy * sw
                    for sx in range(x0, x1):
                        i = (base + sx) * 4
                        pa = src[i + 3]
                        r += src[i] * pa
                        g += src[i + 1] * pa
                        b += src[i + 2] * pa
                        a += pa
                        n += 1
                d = (y * width + x) * 4
                if a:
                    out[d] = (r + a // 2) // a
                    out[d + 1] = (g + a // 2) // a
                    out[d + 2] = (b + a // 2) // a
                    out[d + 3] = (a + n // 2) // n
        hx = self.hotspot[0] * width // sw
        hy = self.hotspot[1] * height // sh
        return IconImage(width, height, out, (hx, hy))

    def __eq__(self, other):
        return (
            isinstance(other, IconImage)
            and self.width == other.width
            and self.height == other.height
            and self.pixels == other.pixels
            and self.hotspot == other.hotspot
        )

    def __repr__(self):
        return "IconImage(%dx%d, hotspot=%r)" % (self.width, self.height, self.hotspot)


class IconFrame:
    """A set of images of different sizes (one .ico/.cur resource)."""

    def __init__(self, images=None, rate=DEFAULT_RATE):
        self.images = list(images or [])
        self.rate = int(rate)

    def copy(self):
        return IconFrame([img.copy() for img in self.images], self.rate)

    def __eq__(self, other):
        return (
            isinstance(other, IconFrame)
            and self.images == other.images
            and self.rate == other.rate
        )

    def __repr__(self):
        return "IconFrame(%r, rate=%d)" % (self.images, self.rate)


class IconDocument:
    """An icon (.ico), cursor (.cur) or animated cursor (.ani).

    ICO and CUR documents contain exactly one frame. ANI documents contain
    one or more frames, played back in order; each frame has its own display
    rate in jiffies (1/60 s).
    """

    def __init__(self, kind=KIND_ICO, frames=None, title="", author=""):
        if kind not in KINDS:
            raise ValueError("Unknown document kind: %r" % (kind,))
        self.kind = kind
        self.frames = list(frames) if frames else [IconFrame()]
        self.title = title
        self.author = author

    @classmethod
    def new(cls, kind=KIND_ICO, sizes=((32, 32),)):
        images = [IconImage(w, h) for (w, h) in sizes]
        return cls(kind, [IconFrame(images)])

    @property
    def is_cursor(self):
        return self.kind in (KIND_CUR, KIND_ANI)

    @property
    def images(self):
        """Images of the first frame (convenience for ICO/CUR)."""
        return self.frames[0].images

    def copy(self):
        return copy.deepcopy(self)

    def __eq__(self, other):
        return (
            isinstance(other, IconDocument)
            and self.kind == other.kind
            and self.frames == other.frames
            and self.title == other.title
            and self.author == other.author
        )
