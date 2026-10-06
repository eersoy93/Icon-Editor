"""Tkinter user interface of the icon editor."""

import base64
import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from . import __version__
from .formats import (
    DEFAULT_RATE, MAX_SIZE, Frame, IconDocument, IconImage, load_document,
    save_document, scale_rgba,
)
from .png import decode_png, encode_png

TOOLS = [
    ("pencil", "Pencil", "p"),
    ("eraser", "Eraser", "e"),
    ("fill", "Fill", "f"),
    ("line", "Line", "l"),
    ("rect", "Rectangle", "r"),
    ("ellipse", "Ellipse", "o"),
    ("picker", "Color picker", "i"),
    ("hotspot", "Hotspot", "h"),
]

PALETTE = [
    (0, 0, 0, 255), (128, 128, 128, 255), (128, 0, 0, 255), (128, 128, 0, 255),
    (0, 128, 0, 255), (0, 128, 128, 255), (0, 0, 128, 255), (128, 0, 128, 255),
    (255, 255, 255, 255), (192, 192, 192, 255), (255, 0, 0, 255), (255, 255, 0, 255),
    (0, 255, 0, 255), (0, 255, 255, 255), (0, 0, 255, 255), (255, 0, 255, 255),
    (255, 128, 0, 255), (128, 64, 0, 255), (255, 192, 203, 255), (0, 0, 0, 0),
]

STANDARD_SIZES = (16, 24, 32, 48, 64, 128, 256)
FILE_TYPES = {
    "ico": ("Icon files", "*.ico"),
    "cur": ("Cursor files", "*.cur"),
    "ani": ("Animated cursor files", "*.ani"),
}
UNDO_LIMIT = 100
CHECKER = 8  # size of the transparency checkerboard cells in screen pixels
MAX_CANVAS = 4096  # maximum zoomed image size in screen pixels
MAX_IMPORT_SIZE = 4096  # largest PNG accepted by "Import PNG" (scaled down)


def rgba_hex(rgba):
    return "#%02x%02x%02x" % tuple(rgba[:3])


def photo_from_rgba(width, height, rgba):
    """Create a Tk PhotoImage (with alpha channel) from an RGBA buffer."""
    data = base64.b64encode(encode_png(width, height, rgba, level=1))
    return tk.PhotoImage(data=data, format="png")


def parse_size(text):
    """Parse ``"32"`` or ``"32x48"`` into a ``(w, h)`` tuple."""
    text = text.lower().replace("\u00d7", "x").replace(" ", "")
    parts = text.split("x")
    if len(parts) == 1:
        parts = parts * 2
    if len(parts) != 2:
        raise ValueError("Invalid size")
    w, h = int(parts[0]), int(parts[1])
    if not (1 <= w <= MAX_SIZE and 1 <= h <= MAX_SIZE):
        raise ValueError("Size must be between 1 and %d" % MAX_SIZE)
    return w, h


# ---------------------------------------------------------------------------
# Raster helpers
# ---------------------------------------------------------------------------

def line_points(x0, y0, x1, y1):
    """Bresenham line between two points (inclusive)."""
    points = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return points
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def rect_points(x0, y0, x1, y1, filled):
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    pts = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if filled or x in (x0, x1) or y in (y0, y1):
                pts.append((x, y))
    return pts


def ellipse_points(x0, y0, x1, y1, filled):
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    rx, ry = (x1 - x0) / 2.0 + 0.5, (y1 - y0) / 2.0 + 0.5

    def inside(x, y):
        return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0

    pts = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if not inside(x, y):
                continue
            if filled or not (inside(x - 1, y) and inside(x + 1, y)
                              and inside(x, y - 1) and inside(x, y + 1)):
                pts.append((x, y))
    return pts


def flood_fill(img, x, y, rgba):
    """4-connected flood fill. Returns the list of changed pixels."""
    target = img.get_pixel(x, y)
    rgba = tuple(rgba)
    if target == rgba:
        return []
    changed = []
    stack = [(x, y)]
    seen = set()
    while stack:
        px, py = stack.pop()
        if (px, py) in seen or not (0 <= px < img.width and 0 <= py < img.height):
            continue
        seen.add((px, py))
        if img.get_pixel(px, py) != target:
            continue
        img.set_pixel(px, py, rgba)
        changed.append((px, py))
        stack.extend(((px + 1, py), (px - 1, py), (px, py + 1), (px, py - 1)))
    return changed


def flip_image(img, horizontal):
    out = IconImage(img.width, img.height)
    for y in range(img.height):
        for x in range(img.width):
            sx = img.width - 1 - x if horizontal else x
            sy = y if horizontal else img.height - 1 - y
            out.set_pixel(x, y, img.get_pixel(sx, sy))
    hx, hy = img.hotspot
    out.hotspot = (img.width - 1 - hx, hy) if horizontal else (hx, img.height - 1 - hy)
    return out


def rotate_image(img):
    """Rotate 90 degrees clockwise."""
    out = IconImage(img.height, img.width)
    for y in range(img.height):
        for x in range(img.width):
            out.set_pixel(img.height - 1 - y, x, img.get_pixel(x, y))
    hx, hy = img.hotspot
    out.hotspot = (img.height - 1 - hy, hx)
    return out


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------

class NewDocumentDialog(simpledialog.Dialog):
    """Ask for the document type and the image sizes of a new document."""

    def body(self, master):
        self.kind = tk.StringVar(value="ico")
        ttk.Label(master, text="Type:").grid(row=0, column=0, sticky="w")
        for i, (kind, label) in enumerate((("ico", "Icon (.ico)"),
                                           ("cur", "Cursor (.cur)"),
                                           ("ani", "Animated cursor (.ani)"))):
            ttk.Radiobutton(master, text=label, value=kind, variable=self.kind).grid(
                row=i + 1, column=0, sticky="w", padx=8)
        ttk.Label(master, text="Sizes:").grid(row=0, column=1, sticky="w")
        self.size_vars = {}
        for i, size in enumerate(STANDARD_SIZES):
            var = tk.BooleanVar(value=size == 32)
            self.size_vars[size] = var
            ttk.Checkbutton(master, text="%d \u00d7 %d" % (size, size), variable=var).grid(
                row=i + 1, column=1, sticky="w", padx=8)
        ttk.Label(master, text="Custom (e.g. 20x20):").grid(
            row=len(STANDARD_SIZES) + 1, column=0, columnspan=2, sticky="w")
        self.custom = ttk.Entry(master)
        self.custom.grid(row=len(STANDARD_SIZES) + 2, column=0, columnspan=2, sticky="ew")
        return self.custom

    def validate(self):
        sizes = [(s, s) for s, v in self.size_vars.items() if v.get()]
        custom = self.custom.get().strip()
        if custom:
            try:
                for part in custom.replace(";", ",").split(","):
                    if part.strip():
                        sizes.append(parse_size(part))
            except ValueError as exc:
                messagebox.showerror("Invalid size", str(exc), parent=self)
                return False
        if not sizes:
            messagebox.showerror("No size", "Select at least one image size.", parent=self)
            return False
        self.sizes = list(dict.fromkeys(sizes))
        return True

    def apply(self):
        self.result = (self.kind.get(), self.sizes)


class PropertiesDialog(simpledialog.Dialog):
    def __init__(self, parent, doc):
        self.doc = doc
        super().__init__(parent, "Animation properties")

    def body(self, master):
        ttk.Label(master, text="Title:").grid(row=0, column=0, sticky="w")
        ttk.Label(master, text="Author:").grid(row=1, column=0, sticky="w")
        self.title_entry = ttk.Entry(master, width=32)
        self.author_entry = ttk.Entry(master, width=32)
        self.title_entry.insert(0, self.doc.title)
        self.author_entry.insert(0, self.doc.author)
        self.title_entry.grid(row=0, column=1, pady=2)
        self.author_entry.grid(row=1, column=1, pady=2)
        return self.title_entry

    def apply(self):
        self.result = (self.title_entry.get(), self.author_entry.get())


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class IconEditorApp:
    def __init__(self, root, path=None):
        self.root = root
        self.doc = IconDocument.new("ico", [(32, 32)])
        self.path = None
        self.dirty = False
        self.frame_index = 0
        self.image_index = 0
        self.zoom = 12
        self.show_grid = tk.BooleanVar(value=True)
        self.fill_shapes = tk.BooleanVar(value=False)
        self.tool = tk.StringVar(value="pencil")
        self.colors = [(0, 0, 0, 255), (255, 255, 255, 255)]
        self.undo_stack = []
        self.redo_stack = []
        self.photo = None
        self.preview_photo = None
        self._drag = None
        self._anim_job = None
        self._anim_step = 0

        self._build_ui()
        self._bind_keys()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        if path:
            self.open_file(path)
        else:
            self.refresh_all()

    # -- UI construction ---------------------------------------------------

    def _build_ui(self):
        root = self.root
        root.geometry("1000x680")
        root.minsize(760, 520)
        self._build_menu()

        left = ttk.Frame(root, padding=4)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Tools").pack(anchor="w")
        for value, label, key in TOOLS:
            ttk.Radiobutton(left, text="%s (%s)" % (label, key.upper()), value=value,
                            variable=self.tool, command=self._tool_changed).pack(anchor="w")
        ttk.Checkbutton(left, text="Filled shapes", variable=self.fill_shapes).pack(
            anchor="w", pady=(4, 8))

        ttk.Label(left, text="Colors (left / right button)").pack(anchor="w")
        sw = ttk.Frame(left)
        sw.pack(anchor="w", pady=2)
        self.swatches = []
        for i in range(2):
            c = tk.Canvas(sw, width=36, height=36, highlightthickness=1,
                          highlightbackground="#555", cursor="hand2")
            c.grid(row=0, column=i, padx=2)
            c.bind("<Button-1>", lambda e, i=i: self.choose_color(i))
            self.swatches.append(c)
        ttk.Button(sw, text="\u21c4", width=3, command=self.swap_colors).grid(row=0, column=2)

        self.alpha_vars = []
        for i, label in enumerate(("Primary alpha", "Secondary alpha")):
            ttk.Label(left, text=label).pack(anchor="w")
            var = tk.IntVar(value=self.colors[i][3])
            tk.Scale(left, from_=0, to=255, orient="horizontal", variable=var,
                     showvalue=True, length=150,
                     command=lambda v, i=i: self._alpha_changed(i)).pack(anchor="w")
            self.alpha_vars.append(var)

        pal = ttk.Frame(left)
        pal.pack(anchor="w", pady=6)
        for n, rgba in enumerate(PALETTE):
            c = tk.Canvas(pal, width=16, height=16, highlightthickness=1,
                          highlightbackground="#888", cursor="hand2")
            c.grid(row=n // 4, column=n % 4, padx=1, pady=1)
            self._paint_swatch(c, rgba, 16)
            c.bind("<Button-1>", lambda e, rgba=rgba: self.set_color(0, rgba))
            for btn in ("<Button-2>", "<Button-3>"):
                c.bind(btn, lambda e, rgba=rgba: self.set_color(1, rgba))

        right = ttk.Frame(root, padding=4)
        right.pack(side="right", fill="y")
        ttk.Label(right, text="Images").pack(anchor="w")
        self.image_list = tk.Listbox(right, height=8, exportselection=False, width=22)
        self.image_list.pack(fill="x")
        self.image_list.bind("<<ListboxSelect>>", self._image_selected)
        ib = ttk.Frame(right)
        ib.pack(fill="x", pady=2)
        ttk.Button(ib, text="Add\u2026", command=self.add_image).pack(side="left")
        ttk.Button(ib, text="Remove", command=self.remove_image).pack(side="left")

        ttk.Label(right, text="Frames (animation)").pack(anchor="w", pady=(8, 0))
        self.frame_list = tk.Listbox(right, height=8, exportselection=False, width=22)
        self.frame_list.pack(fill="x")
        self.frame_list.bind("<<ListboxSelect>>", self._frame_selected)
        fb = ttk.Frame(right)
        fb.pack(fill="x", pady=2)
        ttk.Button(fb, text="New", width=5, command=self.add_frame).pack(side="left")
        ttk.Button(fb, text="Copy", width=5, command=self.duplicate_frame).pack(side="left")
        ttk.Button(fb, text="Del", width=4, command=self.delete_frame).pack(side="left")
        fb2 = ttk.Frame(right)
        fb2.pack(fill="x")
        ttk.Button(fb2, text="\u2191", width=3, command=lambda: self.move_frame(-1)).pack(side="left")
        ttk.Button(fb2, text="\u2193", width=3, command=lambda: self.move_frame(1)).pack(side="left")
        ttk.Label(fb2, text=" Rate:").pack(side="left")
        self.rate_var = tk.IntVar(value=DEFAULT_RATE)
        rate = ttk.Spinbox(fb2, from_=1, to=600, width=5, textvariable=self.rate_var,
                           command=self._rate_changed)
        rate.pack(side="left")
        rate.bind("<Return>", lambda e: self._rate_changed())
        rate.bind("<FocusOut>", lambda e: self._rate_changed())
        ttk.Label(right, text="Rate is in jiffies (1/60 s).", foreground="#666").pack(anchor="w")

        ttk.Label(right, text="Preview").pack(anchor="w", pady=(8, 0))
        self.preview = tk.Label(right, relief="sunken", width=MAX_SIZE, height=MAX_SIZE,
                                background="#ffffff")
        self.preview.pack()
        self.play_button = ttk.Button(right, text="\u25b6 Play", command=self.toggle_play)
        self.play_button.pack(pady=2)

        self.status = ttk.Label(root, relief="sunken", anchor="w", padding=(4, 1))
        self.status.pack(side="bottom", fill="x")

        center = ttk.Frame(root)
        center.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(center, background="#808080", highlightthickness=0,
                                cursor="crosshair")
        hbar = ttk.Scrollbar(center, orient="horizontal", command=self.canvas.xview)
        vbar = ttk.Scrollbar(center, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        hbar.pack(side="bottom", fill="x")
        vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        for n in (1, 3):
            self.canvas.bind("<ButtonPress-%d>" % n, lambda e, b=n: self._press(e, 0 if b == 1 else 1))
            self.canvas.bind("<B%d-Motion>" % n, self._drag_motion)
            self.canvas.bind("<ButtonRelease-%d>" % n, self._release)
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<Control-MouseWheel>", self._wheel_zoom)
        self.canvas.bind("<Control-Button-4>", lambda e: self.set_zoom(self.zoom + 1))
        self.canvas.bind("<Control-Button-5>", lambda e: self.set_zoom(self.zoom - 1))

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        m = tk.Menu(menubar, tearoff=False)
        m.add_command(label="New\u2026", accelerator="Ctrl+N", command=self.new_document)
        m.add_command(label="Open\u2026", accelerator="Ctrl+O", command=self.open_dialog)
        m.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        m.add_command(label="Save As\u2026", accelerator="Ctrl+Shift+S", command=self.save_as)
        m.add_separator()
        m.add_command(label="Import PNG into Current Image\u2026", command=self.import_png)
        m.add_command(label="Export Current Image as PNG\u2026", command=self.export_png)
        m.add_separator()
        m.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=m)

        m = tk.Menu(menubar, tearoff=False)
        m.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        m.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        m.add_separator()
        m.add_command(label="Clear Image", accelerator="Del", command=self.clear_image)
        m.add_command(label="Flip Horizontally", command=lambda: self.transform("flip_h"))
        m.add_command(label="Flip Vertically", command=lambda: self.transform("flip_v"))
        m.add_command(label="Rotate 90\u00b0 Clockwise", command=lambda: self.transform("rotate"))
        menubar.add_cascade(label="Edit", menu=m)

        m = tk.Menu(menubar, tearoff=False)
        m.add_command(label="Add Image Size\u2026", command=self.add_image)
        m.add_command(label="Remove Image Size", command=self.remove_image)
        menubar.add_cascade(label="Image", menu=m)

        m = tk.Menu(menubar, tearoff=False)
        m.add_command(label="New Frame", command=self.add_frame)
        m.add_command(label="Duplicate Frame", command=self.duplicate_frame)
        m.add_command(label="Delete Frame", command=self.delete_frame)
        m.add_command(label="Move Frame Up", command=lambda: self.move_frame(-1))
        m.add_command(label="Move Frame Down", command=lambda: self.move_frame(1))
        m.add_command(label="Set Rate for All Frames\u2026", command=self.set_all_rates)
        m.add_separator()
        m.add_command(label="Play / Stop Preview", command=self.toggle_play)
        m.add_command(label="Title and Author\u2026", command=self.edit_properties)
        menubar.add_cascade(label="Animation", menu=m)

        m = tk.Menu(menubar, tearoff=False)
        m.add_command(label="Zoom In", accelerator="Ctrl++", command=lambda: self.set_zoom(self.zoom + 2))
        m.add_command(label="Zoom Out", accelerator="Ctrl+-", command=lambda: self.set_zoom(self.zoom - 2))
        m.add_checkbutton(label="Show Grid", variable=self.show_grid, command=self.render_canvas)
        menubar.add_cascade(label="View", menu=m)

        m = tk.Menu(menubar, tearoff=False)
        m.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", "Icon Editor %s\nEdits .ico, .cur and .ani files.\n"
            "Written in Python and Tkinter." % __version__))
        menubar.add_cascade(label="Help", menu=m)
        self.root.config(menu=menubar)

    def _bind_keys(self):
        r = self.root
        r.bind("<Control-n>", lambda e: self.new_document())
        r.bind("<Control-o>", lambda e: self.open_dialog())
        r.bind("<Control-s>", lambda e: self.save())
        r.bind("<Control-S>", lambda e: self.save_as())
        r.bind("<Control-z>", lambda e: self.undo())
        r.bind("<Control-y>", lambda e: self.redo())
        r.bind("<Control-plus>", lambda e: self.set_zoom(self.zoom + 2))
        r.bind("<Control-equal>", lambda e: self.set_zoom(self.zoom + 2))
        r.bind("<Control-minus>", lambda e: self.set_zoom(self.zoom - 2))
        r.bind("<Delete>", self._key_delete)
        for value, _label, key in TOOLS:
            r.bind("<Key-%s>" % key, lambda e, v=value: self._key_tool(e, v))

    def _typing(self, event):
        return isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Spinbox))

    def _key_tool(self, event, value):
        if not self._typing(event):
            self.tool.set(value)
            self._tool_changed()

    def _key_delete(self, event):
        if not self._typing(event):
            self.clear_image()

    # -- state helpers -----------------------------------------------------

    @property
    def frame(self):
        return self.doc.frames[self.frame_index]

    @property
    def image(self):
        return self.frame.images[self.image_index]

    def _clamp_indices(self):
        self.frame_index = max(0, min(self.frame_index, len(self.doc.frames) - 1))
        self.image_index = max(0, min(self.image_index, len(self.frame.images) - 1))

    def mark_dirty(self):
        self.dirty = True
        self.update_title()

    def update_title(self):
        name = os.path.basename(self.path) if self.path else "Untitled.%s" % self.doc.kind
        self.root.title("%s%s - Icon Editor" % ("*" if self.dirty else "", name))

    def _confirm_discard(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Unsaved changes", "Save changes before continuing?")
        if answer is None:
            return False
        if answer:
            return self.save()
        return True

    # -- undo / redo -------------------------------------------------------

    def push_undo(self, kind="image"):
        """Record state before a modification.

        ``kind`` is ``"image"`` for edits limited to the current image and
        ``"doc"`` for structural changes to the whole document.
        """
        self.undo_stack.append(self._snapshot(kind))
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()

    def _snapshot(self, kind):
        if kind == "image":
            return ("image", self.frame_index, self.image_index, self.image.copy())
        return ("doc", self.frame_index, self.image_index, self.doc.copy())

    def _restore(self, entry, target_stack):
        kind, fi, ii, data = entry
        if kind == "image":
            self.frame_index, self.image_index = fi, ii
            target_stack.append(self._snapshot("image"))
            self.doc.frames[fi].images[ii] = data
        else:
            target_stack.append(self._snapshot("doc"))
            self.doc = data
            self.frame_index, self.image_index = fi, ii
        self._clamp_indices()
        self.mark_dirty()
        self.refresh_all()

    def undo(self):
        if self.undo_stack:
            self._restore(self.undo_stack.pop(), self.redo_stack)

    def redo(self):
        if self.redo_stack:
            self._restore(self.redo_stack.pop(), self.undo_stack)

    # -- rendering ---------------------------------------------------------

    def refresh_all(self):
        self._clamp_indices()
        self.update_title()
        self.refresh_lists()
        self.render_canvas()
        self.render_preview()
        self.update_swatches()

    def refresh_lists(self):
        self.image_list.delete(0, "end")
        for img in self.frame.images:
            text = "%d \u00d7 %d" % (img.width, img.height)
            if self.doc.is_cursor:
                text += "  hotspot %d,%d" % img.hotspot
            self.image_list.insert("end", text)
        self.image_list.selection_set(self.image_index)
        self.image_list.see(self.image_index)

        self.frame_list.delete(0, "end")
        for n, frame in enumerate(self.doc.frames):
            self.frame_list.insert("end", "Frame %d  (%d jiffies)" % (n + 1, frame.rate))
        self.frame_list.selection_set(self.frame_index)
        self.frame_list.see(self.frame_index)
        self.rate_var.set(self.frame.rate)

    def _max_zoom(self):
        img = self.image
        return max(1, min(32, MAX_CANVAS // max(img.width, img.height)))

    def render_canvas(self):
        img = self.image
        self.zoom = min(self.zoom, self._max_zoom())
        z = self.zoom
        w, h = img.width, img.height
        # Checkerboard background showing through transparent pixels.
        tile = tk.PhotoImage(width=CHECKER * 2, height=CHECKER * 2)
        tile.put("#ffffff", to=(0, 0, CHECKER * 2, CHECKER * 2))
        tile.put("#cccccc", to=(CHECKER, 0, CHECKER * 2, CHECKER))
        tile.put("#cccccc", to=(0, CHECKER, CHECKER, CHECKER * 2))
        self.checker = tk.PhotoImage(width=w * z, height=h * z)
        self.tk_copy(self.checker, tile, 0, 0, w * z, h * z)
        small = photo_from_rgba(w, h, img.pixels)
        self.photo = small.zoom(z) if z > 1 else small

        c = self.canvas
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self.checker, tags="checker")
        c.create_image(0, 0, anchor="nw", image=self.photo, tags="image")
        if self.show_grid.get() and z >= 4:
            for x in range(w + 1):
                c.create_line(x * z, 0, x * z, h * z, fill="#909090", tags="grid")
            for y in range(h + 1):
                c.create_line(0, y * z, w * z, y * z, fill="#909090", tags="grid")
        c.configure(scrollregion=(0, 0, w * z, h * z))
        self.draw_hotspot()

    def tk_copy(self, dest, src, *to, rule=None):
        """Copy (tiling if needed) ``src`` into ``dest`` at region ``to``."""
        args = [dest, "copy", src, "-to"] + list(to)
        if rule:
            args += ["-compositingrule", rule]
        self.root.tk.call(*args)

    def draw_hotspot(self):
        c = self.canvas
        c.delete("hotspot")
        if not self.doc.is_cursor:
            return
        z = self.zoom
        hx, hy = self.image.hotspot
        x0, y0 = hx * z, hy * z
        c.create_rectangle(x0, y0, x0 + z, y0 + z, outline="#ff0000", width=2, tags="hotspot")
        mx, my = x0 + z / 2.0, y0 + z / 2.0
        c.create_line(mx - z, my, mx + z, my, fill="#ff0000", tags="hotspot")
        c.create_line(mx, my - z, mx, my + z, fill="#ff0000", tags="hotspot")

    def update_pixels(self, points):
        """Redraw only the region containing ``points`` on the canvas image."""
        img = self.image
        points = [(x, y) for x, y in points if 0 <= x < img.width and 0 <= y < img.height]
        if not points:
            return
        x0 = min(p[0] for p in points)
        x1 = max(p[0] for p in points) + 1
        y0 = min(p[1] for p in points)
        y1 = max(p[1] for p in points) + 1
        w = x1 - x0
        stride = img.width * 4
        region = bytearray()
        for y in range(y0, y1):
            region += img.pixels[y * stride + x0 * 4:y * stride + x1 * 4]
        z = self.zoom
        patch = photo_from_rgba(w, y1 - y0, region)
        if z > 1:
            patch = patch.zoom(z)
        self.tk_copy(self.photo, patch, x0 * z, y0 * z, rule="set")

    def _preview_image(self, frame):
        """Pick the image in ``frame`` matching the current size."""
        cur = self.image
        for img in frame.images:
            if (img.width, img.height) == (cur.width, cur.height):
                return img
        return frame.images[min(self.image_index, len(frame.images) - 1)]

    def render_preview(self, frame=None):
        img = self._preview_image(frame or self.frame)
        self.preview_photo = photo_from_rgba(img.width, img.height, img.pixels)
        self.preview.configure(image=self.preview_photo, width=MAX_SIZE, height=MAX_SIZE)

    def _paint_swatch(self, canvas, rgba, size):
        canvas.delete("all")
        half = size // 2
        for i in range(2):
            for j in range(2):
                canvas.create_rectangle(i * half, j * half, (i + 1) * half, (j + 1) * half,
                                        fill="#ffffff" if (i + j) % 2 == 0 else "#cccccc",
                                        width=0)
        canvas.create_rectangle(0, 0, size, size, fill=rgba_hex(rgba), width=0,
                                stipple="" if rgba[3] >= 192 else ("gray50" if rgba[3] >= 64 else "gray12"))
        if rgba[3] == 0:
            canvas.create_line(0, size, size, 0, fill="#ff0000")

    def update_swatches(self):
        for i, c in enumerate(self.swatches):
            self._paint_swatch(c, self.colors[i], 36)
            self.alpha_vars[i].set(self.colors[i][3])

    # -- colors ------------------------------------------------------------

    def set_color(self, index, rgba):
        self.colors[index] = tuple(rgba)
        self.update_swatches()

    def choose_color(self, index):
        current = self.colors[index]
        result = colorchooser.askcolor(color=rgba_hex(current), parent=self.root,
                                       title="Choose %s color" % ("primary", "secondary")[index])
        if result and result[0]:
            r, g, b = (int(v) for v in result[0])
            alpha = current[3] or 255
            self.set_color(index, (r, g, b, alpha))

    def swap_colors(self):
        self.colors.reverse()
        self.update_swatches()

    def _alpha_changed(self, index):
        r, g, b, _ = self.colors[index]
        self.colors[index] = (r, g, b, int(self.alpha_vars[index].get()))
        self._paint_swatch(self.swatches[index], self.colors[index], 36)

    # -- mouse handling ----------------------------------------------------

    def _tool_changed(self):
        if self.tool.get() == "hotspot" and not self.doc.is_cursor:
            self.status.configure(text="The hotspot tool only applies to cursors (.cur, .ani).")

    def _event_pixel(self, event):
        x = int(self.canvas.canvasx(event.x) // self.zoom)
        y = int(self.canvas.canvasy(event.y) // self.zoom)
        return x, y

    def _in_image(self, x, y):
        return 0 <= x < self.image.width and 0 <= y < self.image.height

    def _hover(self, event):
        x, y = self._event_pixel(event)
        img = self.image
        text = "%s  %d \u00d7 %d  zoom %d\u00d7" % (self.doc.kind.upper(), img.width,
                                                    img.height, self.zoom)
        if self._in_image(x, y):
            text += "   (%d, %d)  RGBA %d,%d,%d,%d" % ((x, y) + img.get_pixel(x, y))
        if self.doc.is_cursor:
            text += "   hotspot %d,%d" % img.hotspot
        self.status.configure(text=text)

    def _press(self, event, button):
        self.canvas.focus_set()
        x, y = self._event_pixel(event)
        tool = self.tool.get()
        color = (0, 0, 0, 0) if tool == "eraser" else self.colors[button]
        img = self.image
        if tool == "picker":
            if self._in_image(x, y):
                self.set_color(button, img.get_pixel(x, y))
            return
        if tool == "hotspot":
            if not self.doc.is_cursor:
                messagebox.showinfo("Hotspot", "Hotspots are only used by cursors. "
                                    "Save the file as .cur or .ani to use them.")
                return
            if self._in_image(x, y):
                self.push_undo()
                img.hotspot = (x, y)
                self.draw_hotspot()
                self.refresh_lists()
                self.mark_dirty()
            return
        if tool == "fill":
            if self._in_image(x, y):
                self.push_undo()
                if flood_fill(img, x, y, color):
                    self.render_canvas()
                    self.render_preview()
                    self.mark_dirty()
            return
        self.push_undo()
        self._drag = {"tool": tool, "color": color, "start": (x, y), "last": (x, y),
                      "backup": bytearray(img.pixels), "preview": []}
        if tool in ("pencil", "eraser"):
            self._plot([(x, y)], color)
        else:
            self._shape_preview(x, y)

    def _plot(self, points, color):
        img = self.image
        changed = []
        for x, y in points:
            if self._in_image(x, y):
                img.set_pixel(x, y, color)
                changed.append((x, y))
        if changed:
            self.update_pixels(changed)
            self.dirty = True

    def _shape_points(self, x, y):
        d = self._drag
        x0, y0 = d["start"]
        if d["tool"] == "line":
            return line_points(x0, y0, x, y)
        if d["tool"] == "rect":
            return rect_points(x0, y0, x, y, self.fill_shapes.get())
        return ellipse_points(x0, y0, x, y, self.fill_shapes.get())

    def _shape_preview(self, x, y):
        d = self._drag
        img = self.image
        backup = d["backup"]
        for px, py in d["preview"]:
            if self._in_image(px, py):
                i = (py * img.width + px) * 4
                img.pixels[i:i + 4] = backup[i:i + 4]
        old = d["preview"]
        new = [p for p in self._shape_points(x, y) if self._in_image(*p)]
        for px, py in new:
            img.set_pixel(px, py, d["color"])
        d["preview"] = new
        self.update_pixels(set(old) | set(new))

    def _drag_motion(self, event):
        self._hover(event)
        d = self._drag
        if not d:
            return
        x, y = self._event_pixel(event)
        if (x, y) == d["last"]:
            return
        if d["tool"] in ("pencil", "eraser"):
            self._plot(line_points(d["last"][0], d["last"][1], x, y), d["color"])
        else:
            self._shape_preview(x, y)
        d["last"] = (x, y)

    def _release(self, event):
        d = self._drag
        self._drag = None
        if not d:
            return
        if self.image.pixels == d["backup"]:
            # Nothing changed: drop the useless undo entry.
            if self.undo_stack and self.undo_stack[-1][0] == "image":
                self.undo_stack.pop()
            return
        self.mark_dirty()
        self.render_preview()

    def _wheel_zoom(self, event):
        self.set_zoom(self.zoom + (1 if event.delta > 0 else -1))

    def set_zoom(self, zoom):
        zoom = max(1, min(self._max_zoom(), zoom))
        if zoom != self.zoom:
            self.zoom = zoom
            self.render_canvas()

    def _fit_zoom(self):
        img = self.image
        self.zoom = max(1, min(24, 512 // max(img.width, img.height)))

    # -- list callbacks ----------------------------------------------------

    def _image_selected(self, _event=None):
        sel = self.image_list.curselection()
        if sel and sel[0] != self.image_index:
            self.image_index = sel[0]
            self._fit_zoom()
            self.render_canvas()
            self.render_preview()

    def _frame_selected(self, _event=None):
        sel = self.frame_list.curselection()
        if sel and sel[0] != self.frame_index:
            self.frame_index = sel[0]
            self._clamp_indices()
            self.refresh_lists()
            self.render_canvas()
            self.render_preview()

    def _rate_changed(self):
        try:
            rate = int(self.rate_var.get())
        except (tk.TclError, ValueError):
            self.rate_var.set(self.frame.rate)
            return
        rate = max(1, min(600, rate))
        if rate != self.frame.rate:
            self.push_undo("doc")
            self.frame.rate = rate
            self.mark_dirty()
            self.refresh_lists()

    # -- file operations ---------------------------------------------------

    def new_document(self):
        if not self._confirm_discard():
            return
        dlg = NewDocumentDialog(self.root, "New document")
        if not dlg.result:
            return
        kind, sizes = dlg.result
        self._set_document(IconDocument.new(kind, sizes), None)

    def _set_document(self, doc, path):
        self.stop_animation()
        self.doc = doc
        self.path = path
        self.dirty = False
        self.frame_index = self.image_index = 0
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._fit_zoom()
        self.refresh_all()

    def open_dialog(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="Open",
            filetypes=[("Icons and cursors", "*.ico *.cur *.ani"),
                       FILE_TYPES["ico"], FILE_TYPES["cur"], FILE_TYPES["ani"],
                       ("PNG images", "*.png"), ("All files", "*.*")])
        if path:
            self.open_file(path)

    def open_file(self, path):
        try:
            doc = load_document(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Open failed", "Could not open %s:\n%s" % (path, exc))
            self.refresh_all()
            return False
        is_icon_file = os.path.splitext(path)[1].lower() in (".ico", ".cur", ".ani")
        self._set_document(doc, path if is_icon_file else None)
        return True

    def save(self):
        if not self.path or os.path.splitext(self.path)[1].lower() != "." + self.doc.kind:
            return self.save_as()
        return self._write(self.path, self.doc.kind)

    def save_as(self):
        kinds = [self.doc.kind] + [k for k in ("ico", "cur", "ani") if k != self.doc.kind]
        initial = (os.path.splitext(os.path.basename(self.path))[0] if self.path else "untitled")
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save As", defaultextension="." + self.doc.kind,
            initialfile=initial + "." + self.doc.kind,
            filetypes=[FILE_TYPES[k] for k in kinds])
        if not path:
            return False
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        kind = ext if ext in FILE_TYPES else self.doc.kind
        if kind not in FILE_TYPES or ext != kind:
            path += "." + kind
        return self._write(path, kind)

    def _write(self, path, kind):
        if kind != "ani" and len(self.doc.frames) > 1:
            if not messagebox.askokcancel(
                    "Save", "%s files cannot store animations. Only the first frame "
                    "will be saved. Continue?" % kind.upper()):
                return False
        try:
            save_document(self.doc, path, kind)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Save failed", "Could not save %s:\n%s" % (path, exc))
            return False
        self.doc.kind = kind
        self.path = path
        self.dirty = False
        self.refresh_all()
        return True

    def import_png(self):
        path = filedialog.askopenfilename(parent=self.root, title="Import PNG",
                                          filetypes=[("PNG images", "*.png")])
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                w, h, rgba = decode_png(fh.read(), MAX_IMPORT_SIZE)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        cur = self.image
        if (w, h) != (cur.width, cur.height):
            rgba = scale_rgba(w, h, rgba, cur.width, cur.height)
        src = IconImage(cur.width, cur.height, rgba)
        src.hotspot = cur.hotspot
        self.push_undo()
        self.frame.images[self.image_index] = src
        self.mark_dirty()
        self.render_canvas()
        self.render_preview()

    def export_png(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Export PNG",
                                            defaultextension=".png",
                                            filetypes=[("PNG images", "*.png")])
        if not path:
            return
        img = self.image
        try:
            with open(path, "wb") as fh:
                fh.write(encode_png(img.width, img.height, img.pixels))
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def quit(self):
        if self._confirm_discard():
            self.stop_animation()
            self.root.destroy()

    # -- edit operations ---------------------------------------------------

    def clear_image(self):
        self.push_undo()
        img = self.image
        img.pixels = bytearray(len(img.pixels))
        self.mark_dirty()
        self.render_canvas()
        self.render_preview()

    def transform(self, op):
        img = self.image
        if op == "rotate" and img.width != img.height:
            messagebox.showinfo("Rotate", "Only square images can be rotated.")
            return
        self.push_undo()
        if op == "flip_h":
            new = flip_image(img, True)
        elif op == "flip_v":
            new = flip_image(img, False)
        else:
            new = rotate_image(img)
        self.frame.images[self.image_index] = new
        self.mark_dirty()
        self.refresh_lists()
        self.render_canvas()
        self.render_preview()

    # -- image sizes -------------------------------------------------------

    def add_image(self):
        text = simpledialog.askstring("Add image size",
                                      "Size (e.g. 48 or 32x48, max %d):" % MAX_SIZE,
                                      parent=self.root)
        if not text:
            return
        try:
            w, h = parse_size(text)
        except ValueError as exc:
            messagebox.showerror("Invalid size", str(exc))
            return
        if any((i.width, i.height) == (w, h) for i in self.frame.images):
            messagebox.showerror("Add image size", "This size already exists.")
            return
        resample = messagebox.askyesno(
            "Add image size", "Create the new image by resampling the current image?\n"
            "(Choose No for a blank image.)")
        self.push_undo("doc")
        # Keep all frames of an animation in sync: every frame gets the size.
        for frame in self.doc.frames:
            src = frame.images[min(self.image_index, len(frame.images) - 1)]
            frame.images.append(src.scaled(w, h) if resample else
                                IconImage(w, h, hotspot=(src.hotspot[0] * w // src.width,
                                                         src.hotspot[1] * h // src.height)))
        self.image_index = len(self.frame.images) - 1
        self._fit_zoom()
        self.mark_dirty()
        self.refresh_all()

    def remove_image(self):
        if len(self.frame.images) <= 1:
            messagebox.showinfo("Remove image size", "A document needs at least one image.")
            return
        self.push_undo("doc")
        for frame in self.doc.frames:
            if self.image_index < len(frame.images) and len(frame.images) > 1:
                del frame.images[self.image_index]
        self._clamp_indices()
        self._fit_zoom()
        self.mark_dirty()
        self.refresh_all()

    # -- animation frames --------------------------------------------------

    def _ensure_animation(self):
        if self.doc.kind == "ani":
            return True
        if not messagebox.askyesno(
                "Animation", "Multiple frames require an animated cursor (.ani). "
                "Convert this document to an animated cursor?"):
            return False
        self.doc.kind = "ani"
        return True

    def add_frame(self):
        if not self._ensure_animation():
            return
        self.push_undo("doc")
        cur = self.frame
        blank = Frame([IconImage(i.width, i.height, hotspot=i.hotspot) for i in cur.images],
                      cur.rate)
        self.doc.frames.insert(self.frame_index + 1, blank)
        self.frame_index += 1
        self.mark_dirty()
        self.refresh_all()

    def duplicate_frame(self):
        if not self._ensure_animation():
            return
        self.push_undo("doc")
        self.doc.frames.insert(self.frame_index + 1, self.frame.copy())
        self.frame_index += 1
        self.mark_dirty()
        self.refresh_all()

    def delete_frame(self):
        if len(self.doc.frames) <= 1:
            messagebox.showinfo("Delete frame", "A document needs at least one frame.")
            return
        self.push_undo("doc")
        del self.doc.frames[self.frame_index]
        self._clamp_indices()
        self.mark_dirty()
        self.refresh_all()

    def move_frame(self, delta):
        i, j = self.frame_index, self.frame_index + delta
        if not 0 <= j < len(self.doc.frames):
            return
        self.push_undo("doc")
        frames = self.doc.frames
        frames[i], frames[j] = frames[j], frames[i]
        self.frame_index = j
        self.mark_dirty()
        self.refresh_all()

    def set_all_rates(self):
        rate = simpledialog.askinteger("Frame rate", "Rate for all frames in jiffies "
                                       "(1/60 s):", parent=self.root, minvalue=1,
                                       maxvalue=600, initialvalue=self.frame.rate)
        if rate:
            self.push_undo("doc")
            for frame in self.doc.frames:
                frame.rate = rate
            self.mark_dirty()
            self.refresh_lists()

    def edit_properties(self):
        dlg = PropertiesDialog(self.root, self.doc)
        if dlg.result and dlg.result != (self.doc.title, self.doc.author):
            self.push_undo("doc")
            self.doc.title, self.doc.author = dlg.result
            self.mark_dirty()

    def toggle_play(self):
        if self._anim_job:
            self.stop_animation()
            self.render_preview()
        else:
            self._anim_step = self.frame_index
            self.play_button.configure(text="\u25a0 Stop")
            self._animate()

    def _animate(self):
        frames = self.doc.frames
        frame = frames[self._anim_step % len(frames)]
        self.render_preview(frame)
        self._anim_step = (self._anim_step + 1) % len(frames)
        self._anim_job = self.root.after(max(16, frame.rate * 1000 // 60), self._animate)

    def stop_animation(self):
        if self._anim_job:
            self.root.after_cancel(self._anim_job)
            self._anim_job = None
        self.play_button.configure(text="\u25b6 Play")


def main(argv=None):
    import sys
    argv = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    IconEditorApp(root, argv[0] if argv else None)
    root.mainloop()
