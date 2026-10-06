"""Tkinter user interface of the icon editor."""

import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from . import fileio, png
from .model import (
    DEFAULT_RATE, IconDocument, IconFrame, IconImage, KIND_ANI, KIND_CUR,
    KIND_ICO, MAX_SIZE,
)

APP_NAME = "Icon Editor"

KIND_LABELS = {KIND_ICO: "Icon", KIND_CUR: "Cursor", KIND_ANI: "Animated cursor"}

FILE_TYPES = [
    ("All supported files", "*.ico *.cur *.ani"),
    ("Icons", "*.ico"),
    ("Cursors", "*.cur"),
    ("Animated cursors", "*.ani"),
    ("All files", "*.*"),
]
SAVE_TYPES = {
    KIND_ICO: [("Icon", "*.ico"), ("Cursor", "*.cur"), ("Animated cursor", "*.ani")],
    KIND_CUR: [("Cursor", "*.cur"), ("Icon", "*.ico"), ("Animated cursor", "*.ani")],
    KIND_ANI: [("Animated cursor", "*.ani"), ("Cursor", "*.cur"), ("Icon", "*.ico")],
}
PNG_TYPES = [("PNG image", "*.png"), ("All files", "*.*")]

STANDARD_SIZES = (16, 24, 32, 48, 64, 128, 256)

TOOLS = (
    ("pencil", "Pencil"),
    ("eraser", "Eraser"),
    ("fill", "Fill"),
    ("line", "Line"),
    ("rect", "Rectangle"),
    ("frect", "Filled rectangle"),
    ("ellipse", "Ellipse"),
    ("fellipse", "Filled ellipse"),
    ("picker", "Color picker"),
    ("hotspot", "Hotspot"),
)
SHAPE_TOOLS = ("line", "rect", "frect", "ellipse", "fellipse")

PALETTE = (
    "#000000", "#808080", "#800000", "#808000", "#008000", "#008080", "#000080", "#800080",
    "#ffffff", "#c0c0c0", "#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff",
    "#404040", "#a0a0a0", "#ff8000", "#80ff00", "#00ff80", "#0080ff", "#8000ff", "#ff0080",
    "#202020", "#e0e0e0", "#804000", "#ffc080", "#408000", "#c0ffc0", "#004080", "#c0c0ff",
)

CHECK_LIGHT = 0xFF
CHECK_DARK = 0xCC

MAX_UNDO = 50
MAX_ZOOM = 64


def hex_color(rgb):
    return "#%02x%02x%02x" % tuple(rgb[:3])


def parse_hex(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def composite(rgba, light):
    """Blend an RGBA colour over a grey checkerboard cell."""
    r, g, b, a = rgba
    bg = CHECK_LIGHT if light else CHECK_DARK
    if a == 255:
        return "#%02x%02x%02x" % (r, g, b)
    if a == 0:
        return "#%02x%02x%02x" % (bg, bg, bg)
    inv = 255 - a
    return "#%02x%02x%02x" % (
        (r * a + bg * inv) // 255,
        (g * a + bg * inv) // 255,
        (b * a + bg * inv) // 255,
    )


def line_points(x0, y0, x1, y1):
    """Bresenham line between two pixel positions (inclusive)."""
    points = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return points


def rect_points(x0, y0, x1, y1, filled):
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if filled:
        return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    points = set()
    for x in range(x0, x1 + 1):
        points.add((x, y0))
        points.add((x, y1))
    for y in range(y0, y1 + 1):
        points.add((x0, y))
        points.add((x1, y))
    return list(points)


def ellipse_points(x0, y0, x1, y1, filled):
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    rx = (x1 - x0 + 1) / 2.0
    ry = (y1 - y0 + 1) / 2.0

    def inside(x, y):
        return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0

    points = []
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if not inside(x, y):
                continue
            if filled or not (inside(x - 1, y) and inside(x + 1, y)
                              and inside(x, y - 1) and inside(x, y + 1)):
                points.append((x, y))
    return points


def shape_points(tool, x0, y0, x1, y1):
    if tool == "line":
        return line_points(x0, y0, x1, y1)
    if tool in ("rect", "frect"):
        return rect_points(x0, y0, x1, y1, tool == "frect")
    return ellipse_points(x0, y0, x1, y1, tool == "fellipse")


class NewDocumentDialog(simpledialog.Dialog):
    """Asks for the kind of document and the image sizes to create."""

    def __init__(self, parent, kind=KIND_ICO):
        self.initial_kind = kind
        self.result = None
        super().__init__(parent, "New")

    def body(self, master):
        self.kind_var = tk.StringVar(value=self.initial_kind)
        ttk.Label(master, text="Type:").grid(row=0, column=0, sticky="w")
        for i, kind in enumerate((KIND_ICO, KIND_CUR, KIND_ANI)):
            ttk.Radiobutton(master, text=KIND_LABELS[kind], value=kind,
                            variable=self.kind_var).grid(row=0, column=i + 1, sticky="w")
        ttk.Label(master, text="Sizes:").grid(row=1, column=0, sticky="nw", pady=(8, 0))
        self.size_vars = {}
        for i, size in enumerate(STANDARD_SIZES):
            var = tk.BooleanVar(value=size == 32)
            self.size_vars[size] = var
            ttk.Checkbutton(master, text="%d x %d" % (size, size), variable=var).grid(
                row=1 + i // 3, column=1 + i % 3, sticky="w", pady=(8 if i < 3 else 0, 0))
        row = 2 + len(STANDARD_SIZES) // 3
        ttk.Label(master, text="Custom:").grid(row=row, column=0, sticky="w", pady=(8, 0))
        custom = ttk.Frame(master)
        custom.grid(row=row, column=1, columnspan=3, sticky="w", pady=(8, 0))
        self.custom_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(custom, variable=self.custom_var).pack(side="left")
        self.width_var = tk.IntVar(value=40)
        self.height_var = tk.IntVar(value=40)
        ttk.Spinbox(custom, from_=1, to=MAX_SIZE, width=5,
                    textvariable=self.width_var).pack(side="left")
        ttk.Label(custom, text=" x ").pack(side="left")
        ttk.Spinbox(custom, from_=1, to=MAX_SIZE, width=5,
                    textvariable=self.height_var).pack(side="left")
        return None

    def validate(self):
        sizes = [(s, s) for s, var in self.size_vars.items() if var.get()]
        if self.custom_var.get():
            try:
                w, h = int(self.width_var.get()), int(self.height_var.get())
            except (tk.TclError, ValueError):
                messagebox.showerror(APP_NAME, "Invalid custom size.", parent=self)
                return False
            if not (1 <= w <= MAX_SIZE and 1 <= h <= MAX_SIZE):
                messagebox.showerror(
                    APP_NAME, "Sizes must be between 1 and %d." % MAX_SIZE, parent=self)
                return False
            if (w, h) not in sizes:
                sizes.append((w, h))
        if not sizes:
            messagebox.showerror(APP_NAME, "Select at least one size.", parent=self)
            return False
        self.result = (self.kind_var.get(), sizes)
        return True


class SizeDialog(simpledialog.Dialog):
    """Asks for an image size, optionally scaling the current image."""

    def __init__(self, parent, title, width, height, offer_scale=True):
        self.initial = (width, height)
        self.offer_scale = offer_scale
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text="Width:").grid(row=0, column=0, sticky="w")
        ttk.Label(master, text="Height:").grid(row=1, column=0, sticky="w")
        self.width_var = tk.IntVar(value=self.initial[0])
        self.height_var = tk.IntVar(value=self.initial[1])
        w = ttk.Spinbox(master, from_=1, to=MAX_SIZE, width=6, textvariable=self.width_var)
        w.grid(row=0, column=1, sticky="w")
        ttk.Spinbox(master, from_=1, to=MAX_SIZE, width=6,
                    textvariable=self.height_var).grid(row=1, column=1, sticky="w")
        self.scale_var = tk.BooleanVar(value=True)
        if self.offer_scale:
            ttk.Checkbutton(master, text="Scale current image",
                            variable=self.scale_var).grid(row=2, column=0, columnspan=2,
                                                          sticky="w", pady=(6, 0))
        return w

    def validate(self):
        try:
            w, h = int(self.width_var.get()), int(self.height_var.get())
        except (tk.TclError, ValueError):
            messagebox.showerror(APP_NAME, "Invalid size.", parent=self)
            return False
        if not (1 <= w <= MAX_SIZE and 1 <= h <= MAX_SIZE):
            messagebox.showerror(
                APP_NAME, "Sizes must be between 1 and %d." % MAX_SIZE, parent=self)
            return False
        self.result = (w, h, bool(self.scale_var.get()) and self.offer_scale)
        return True


class PropertiesDialog(simpledialog.Dialog):
    """Edits the title and author of an animated cursor."""

    def __init__(self, parent, title, author):
        self.initial = (title, author)
        self.result = None
        super().__init__(parent, "Properties")

    def body(self, master):
        ttk.Label(master, text="Title:").grid(row=0, column=0, sticky="w")
        ttk.Label(master, text="Author:").grid(row=1, column=0, sticky="w")
        self.title_var = tk.StringVar(value=self.initial[0])
        self.author_var = tk.StringVar(value=self.initial[1])
        e = ttk.Entry(master, width=36, textvariable=self.title_var)
        e.grid(row=0, column=1)
        ttk.Entry(master, width=36, textvariable=self.author_var).grid(row=1, column=1)
        return e

    def apply(self):
        self.result = (self.title_var.get(), self.author_var.get())


class IconEditorApp:
    def __init__(self, root, path=None):
        self.root = root
        self.doc = IconDocument.new(KIND_ICO, [(32, 32)])
        self.path = None
        self.dirty = False
        self.frame_index = 0
        self.image_index = 0
        self.zoom = 12
        self.undo_stack = []
        self.redo_stack = []
        self.clipboard = None
        self.primary = (0, 0, 0, 255)
        self.secondary = (255, 255, 255, 255)
        self.playing = False
        self._play_job = None
        self._play_step = 0
        self._stroke = None
        self._photo = None
        self._preview_photo = None

        self.tool_var = tk.StringVar(value="pencil")
        self.grid_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar()
        self.rate_var = tk.IntVar(value=DEFAULT_RATE)
        self.primary_alpha = tk.IntVar(value=255)
        self.secondary_alpha = tk.IntVar(value=255)

        root.title(APP_NAME)
        root.geometry("1100x720")
        root.minsize(800, 520)
        root.protocol("WM_DELETE_WINDOW", self.quit)

        self._build_menu()
        self._build_layout()
        self._bind_keys()

        if path:
            self.open_path(path)
        else:
            self._document_changed(reset_zoom=True)

    # ------------------------------------------------------------------ UI
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New...", accelerator="Ctrl+N", command=self.new_document)
        file_menu.add_command(label="Open...", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        file_menu.add_command(label="Save As...", accelerator="Ctrl+Shift+S",
                              command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Import PNG into Image...", command=self.import_png)
        file_menu.add_command(label="Export Image as PNG...", command=self.export_png)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Copy Image", accelerator="Ctrl+C", command=self.copy_image)
        edit_menu.add_command(label="Paste Image", accelerator="Ctrl+V",
                              command=self.paste_image)
        edit_menu.add_separator()
        edit_menu.add_command(label="Clear Image", accelerator="Delete",
                              command=self.clear_image)
        edit_menu.add_command(label="Flip Horizontally", command=self.flip_horizontal)
        edit_menu.add_command(label="Flip Vertically", command=self.flip_vertical)
        edit_menu.add_command(label="Rotate 90\u00b0 Clockwise", command=self.rotate)
        shift_menu = tk.Menu(edit_menu, tearoff=False)
        shift_menu.add_command(label="Left", command=lambda: self.shift(-1, 0))
        shift_menu.add_command(label="Right", command=lambda: self.shift(1, 0))
        shift_menu.add_command(label="Up", command=lambda: self.shift(0, -1))
        shift_menu.add_command(label="Down", command=lambda: self.shift(0, 1))
        edit_menu.add_cascade(label="Shift Image", menu=shift_menu)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        image_menu = tk.Menu(menubar, tearoff=False)
        image_menu.add_command(label="Add Image Size...", command=self.add_image)
        image_menu.add_command(label="Remove Image", command=self.remove_image)
        image_menu.add_command(label="Resize Image...", command=self.resize_image)
        image_menu.add_separator()
        image_menu.add_command(label="Set Hotspot...", command=self.ask_hotspot)
        menubar.add_cascade(label="Image", menu=image_menu)

        anim_menu = tk.Menu(menubar, tearoff=False)
        anim_menu.add_command(label="Add Frame", command=self.add_frame)
        anim_menu.add_command(label="Duplicate Frame", command=self.duplicate_frame)
        anim_menu.add_command(label="Delete Frame", command=self.delete_frame)
        anim_menu.add_command(label="Move Frame Up", command=lambda: self.move_frame(-1))
        anim_menu.add_command(label="Move Frame Down", command=lambda: self.move_frame(1))
        anim_menu.add_separator()
        anim_menu.add_command(label="Apply Rate to All Frames", command=self.rate_to_all)
        anim_menu.add_command(label="Play / Stop", command=self.toggle_play)
        anim_menu.add_separator()
        anim_menu.add_command(label="Properties...", command=self.edit_properties)
        menubar.add_cascade(label="Animation", menu=anim_menu)
        self.anim_menu = anim_menu

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Zoom In", accelerator="Ctrl++", command=self.zoom_in)
        view_menu.add_command(label="Zoom Out", accelerator="Ctrl+-", command=self.zoom_out)
        view_menu.add_command(label="Fit", command=self.zoom_fit)
        view_menu.add_checkbutton(label="Show Grid", variable=self.grid_var,
                                  command=self.render)
        menubar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="About", command=self.about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def _build_layout(self):
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        # Left: tools and colours.
        left = ttk.Frame(main, padding=6)
        left.pack(side="left", fill="y")
        tools_box = ttk.LabelFrame(left, text="Tools", padding=4)
        tools_box.pack(fill="x")
        self.tool_buttons = {}
        for name, label in TOOLS:
            btn = ttk.Radiobutton(tools_box, text=label, value=name, variable=self.tool_var)
            btn.pack(anchor="w")
            self.tool_buttons[name] = btn

        colors_box = ttk.LabelFrame(left, text="Colors", padding=4)
        colors_box.pack(fill="x", pady=(8, 0))
        swatches = ttk.Frame(colors_box)
        swatches.pack(fill="x")
        self.primary_swatch = tk.Canvas(swatches, width=36, height=36,
                                        highlightthickness=1, cursor="hand2")
        self.primary_swatch.grid(row=0, column=0, padx=(0, 4))
        self.secondary_swatch = tk.Canvas(swatches, width=36, height=36,
                                          highlightthickness=1, cursor="hand2")
        self.secondary_swatch.grid(row=0, column=1, padx=(0, 4))
        ttk.Button(swatches, text="\u21c4", width=3, command=self.swap_colors).grid(
            row=0, column=2)
        ttk.Label(swatches, text="Left").grid(row=1, column=0)
        ttk.Label(swatches, text="Right").grid(row=1, column=1)
        self.primary_swatch.bind("<Button-1>", lambda e: self.choose_color(True))
        self.secondary_swatch.bind("<Button-1>", lambda e: self.choose_color(False))

        ttk.Label(colors_box, text="Left alpha").pack(anchor="w", pady=(6, 0))
        ttk.Scale(colors_box, from_=0, to=255, variable=self.primary_alpha,
                  command=lambda v: self._alpha_changed(True)).pack(fill="x")
        ttk.Label(colors_box, text="Right alpha").pack(anchor="w")
        ttk.Scale(colors_box, from_=0, to=255, variable=self.secondary_alpha,
                  command=lambda v: self._alpha_changed(False)).pack(fill="x")

        palette = ttk.Frame(colors_box)
        palette.pack(pady=(6, 0))
        for i, color in enumerate(PALETTE):
            sw = tk.Canvas(palette, width=16, height=16, bg=color, highlightthickness=1,
                           highlightbackground="#808080", cursor="hand2")
            sw.grid(row=i // 4, column=i % 4, padx=1, pady=1)
            rgba = parse_hex(color) + (255,)
            sw.bind("<Button-1>", lambda e, c=rgba: self.set_color(c, True))
            for button in ("<Button-2>", "<Button-3>"):
                sw.bind(button, lambda e, c=rgba: self.set_color(c, False))
        clear = tk.Canvas(palette, width=70, height=16, highlightthickness=1,
                          highlightbackground="#808080", cursor="hand2")
        clear.grid(row=len(PALETTE) // 4, column=0, columnspan=4, pady=(2, 0))
        for i in range(0, 72, 6):
            for j in range(0, 18, 6):
                light = (i // 6 + j // 6) % 2 == 0
                clear.create_rectangle(i, j, i + 6, j + 6, outline="",
                                       fill=composite((0, 0, 0, 0), light))
        clear.create_text(36, 9, text="Transparent", font=("TkDefaultFont", 7))
        clear.bind("<Button-1>", lambda e: self.set_color((0, 0, 0, 0), True))
        for button in ("<Button-2>", "<Button-3>"):
            clear.bind(button, lambda e: self.set_color((0, 0, 0, 0), False))

        # Right: images, frames and preview.
        right = ttk.Frame(main, padding=6, width=230)
        right.pack(side="right", fill="y")

        images_box = ttk.LabelFrame(right, text="Images", padding=4)
        images_box.pack(fill="x")
        self.image_list = tk.Listbox(images_box, height=7, exportselection=False,
                                     activestyle="none")
        self.image_list.pack(fill="x")
        self.image_list.bind("<<ListboxSelect>>", self._image_selected)
        buttons = ttk.Frame(images_box)
        buttons.pack(fill="x", pady=(4, 0))
        ttk.Button(buttons, text="Add...", command=self.add_image).pack(side="left")
        ttk.Button(buttons, text="Remove", command=self.remove_image).pack(side="left")
        ttk.Button(buttons, text="Resize...", command=self.resize_image).pack(side="left")

        self.frames_box = ttk.LabelFrame(right, text="Frames", padding=4)
        self.frames_box.pack(fill="x", pady=(8, 0))
        self.frame_list = tk.Listbox(self.frames_box, height=7, exportselection=False,
                                     activestyle="none")
        self.frame_list.pack(fill="x")
        self.frame_list.bind("<<ListboxSelect>>", self._frame_selected)
        fb = ttk.Frame(self.frames_box)
        fb.pack(fill="x", pady=(4, 0))
        self.frame_buttons = [
            ttk.Button(fb, text="Add", width=5, command=self.add_frame),
            ttk.Button(fb, text="Dup", width=5, command=self.duplicate_frame),
            ttk.Button(fb, text="Del", width=5, command=self.delete_frame),
            ttk.Button(fb, text="\u2191", width=3, command=lambda: self.move_frame(-1)),
            ttk.Button(fb, text="\u2193", width=3, command=lambda: self.move_frame(1)),
        ]
        for b in self.frame_buttons:
            b.pack(side="left")
        rate_row = ttk.Frame(self.frames_box)
        rate_row.pack(fill="x", pady=(4, 0))
        ttk.Label(rate_row, text="Rate (1/60 s):").pack(side="left")
        self.rate_spin = ttk.Spinbox(rate_row, from_=1, to=6000, width=6,
                                     textvariable=self.rate_var,
                                     command=self._rate_changed)
        self.rate_spin.pack(side="left", padx=4)
        self.rate_spin.bind("<Return>", lambda e: self._rate_changed())
        self.rate_spin.bind("<FocusOut>", lambda e: self._rate_changed())
        self.frame_buttons.append(self.rate_spin)

        preview_box = ttk.LabelFrame(right, text="Preview", padding=4)
        preview_box.pack(fill="both", expand=True, pady=(8, 0))
        self.preview = tk.Canvas(preview_box, width=200, height=200, bg="#f0f0f0",
                                 highlightthickness=0)
        self.preview.pack(fill="both", expand=True)
        self.play_button = ttk.Button(preview_box, text="\u25b6 Play",
                                      command=self.toggle_play)
        self.play_button.pack(pady=(4, 0))
        self.hotspot_label = ttk.Label(preview_box, text="")
        self.hotspot_label.pack()

        # Centre: the drawing canvas.
        center = ttk.Frame(main)
        center.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(center, bg="#9a9a9a", highlightthickness=0, cursor="tcross")
        xscroll = ttk.Scrollbar(center, orient="horizontal", command=self.canvas.xview)
        yscroll = ttk.Scrollbar(center, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-1>", lambda e: self._on_press(e, True))
        self.canvas.bind("<B1-Motion>", lambda e: self._on_drag(e))
        self.canvas.bind("<ButtonRelease-1>", lambda e: self._on_release(e))
        for n in ("2", "3"):
            self.canvas.bind("<ButtonPress-%s>" % n, lambda e: self._on_press(e, False))
            self.canvas.bind("<B%s-Motion>" % n, lambda e: self._on_drag(e))
            self.canvas.bind("<ButtonRelease-%s>" % n, lambda e: self._on_release(e))
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self._update_status())
        self.canvas.bind("<Control-MouseWheel>", self._on_wheel_zoom)
        self.canvas.bind("<Control-Button-4>", lambda e: self.zoom_in())
        self.canvas.bind("<Control-Button-5>", lambda e: self.zoom_out())

        status = ttk.Label(self.root, textvariable=self.status_var, anchor="w",
                           relief="sunken", padding=(6, 2))
        status.pack(side="bottom", fill="x")

        self._draw_swatches()

    def _bind_keys(self):
        r = self.root
        r.bind_all("<Control-n>", lambda e: self.new_document())
        r.bind_all("<Control-o>", lambda e: self.open_file())
        r.bind_all("<Control-s>", lambda e: self.save())
        r.bind_all("<Control-S>", lambda e: self.save_as())
        r.bind_all("<Control-z>", lambda e: self.undo())
        r.bind_all("<Control-y>", lambda e: self.redo())
        r.bind_all("<Control-Z>", lambda e: self.redo())
        r.bind_all("<Control-c>", self._key_copy)
        r.bind_all("<Control-v>", self._key_paste)
        r.bind_all("<Control-plus>", lambda e: self.zoom_in())
        r.bind_all("<Control-equal>", lambda e: self.zoom_in())
        r.bind_all("<Control-minus>", lambda e: self.zoom_out())
        self.canvas.bind("<Delete>", lambda e: self.clear_image())
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())

    def _key_copy(self, event):
        if not isinstance(event.widget, (tk.Entry, ttk.Entry)):
            self.copy_image()

    def _key_paste(self, event):
        if not isinstance(event.widget, (tk.Entry, ttk.Entry)):
            self.paste_image()

    # ------------------------------------------------------------ helpers
    @property
    def frame(self):
        return self.doc.frames[self.frame_index]

    @property
    def image(self):
        return self.frame.images[self.image_index]

    def _set_dirty(self, dirty=True):
        self.dirty = dirty
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self.path) if self.path else "Untitled"
        self.root.title("%s%s - %s (%s)" % (
            name, "*" if self.dirty else "", APP_NAME, KIND_LABELS[self.doc.kind]))

    def _snapshot(self):
        return (self.doc.copy(), self.frame_index, self.image_index)

    def push_undo(self):
        self.undo_stack.append(self._snapshot())
        if len(self.undo_stack) > MAX_UNDO:
            del self.undo_stack[0]
        self.redo_stack.clear()

    def _restore(self, snapshot):
        self.doc, self.frame_index, self.image_index = snapshot
        self.doc = self.doc.copy()
        self._set_dirty(True)
        self._document_changed()

    def undo(self):
        if self._stroke or not self.undo_stack:
            return
        self.redo_stack.append(self._snapshot())
        self._restore(self.undo_stack.pop())

    def redo(self):
        if self._stroke or not self.redo_stack:
            return
        self.undo_stack.append(self._snapshot())
        self._restore(self.redo_stack.pop())

    def _clamp_selection(self):
        self.frame_index = max(0, min(self.frame_index, len(self.doc.frames) - 1))
        self.image_index = max(0, min(self.image_index, len(self.frame.images) - 1))

    def _document_changed(self, reset_zoom=False):
        """Refresh every view after the document structure changed."""
        self._clamp_selection()
        if reset_zoom:
            self.zoom_fit(render=False)
        self._refresh_lists()
        self.render()
        self._update_title()

    def _refresh_lists(self):
        self.image_list.delete(0, "end")
        for img in self.frame.images:
            label = "%d x %d" % (img.width, img.height)
            if self.doc.is_cursor:
                label += "   hotspot %d,%d" % img.hotspot
            self.image_list.insert("end", label)
        self.image_list.selection_clear(0, "end")
        self.image_list.selection_set(self.image_index)
        self.image_list.see(self.image_index)

        self.frame_list.delete(0, "end")
        is_ani = self.doc.kind == KIND_ANI
        if is_ani:
            for i, f in enumerate(self.doc.frames):
                self.frame_list.insert("end", "Frame %d   (%d jiffies)" % (i + 1, f.rate))
            self.frame_list.selection_set(self.frame_index)
            self.frame_list.see(self.frame_index)
            self.rate_var.set(self.frame.rate)
        state = "normal" if is_ani else "disabled"
        self.frame_list.configure(state=state)
        for b in self.frame_buttons:
            b.configure(state=state)
        self.play_button.configure(state=state)
        for i in range(self.anim_menu.index("end") + 1):
            if self.anim_menu.type(i) == "command":
                self.anim_menu.entryconfigure(i, state=state)
        self.tool_buttons["hotspot"].configure(
            state="normal" if self.doc.is_cursor else "disabled")
        if not self.doc.is_cursor and self.tool_var.get() == "hotspot":
            self.tool_var.set("pencil")

    # ------------------------------------------------------------ rendering
    def render(self):
        """Redraw the editing canvas and the preview."""
        img = self.image
        z = self.zoom
        w, h = img.width, img.height
        px = img.pixels
        rows = []
        for y in range(h):
            row = []
            base = y * w * 4
            for x in range(w):
                i = base + x * 4
                row.append(composite(px[i:i + 4], (x + y) & 1 == 0))
            rows.append("{" + " ".join(row) + "}")
        base_photo = tk.PhotoImage(width=w, height=h)
        base_photo.put(" ".join(rows))
        self._photo = base_photo.zoom(z) if z > 1 else base_photo

        c = self.canvas
        c.delete("all")
        c.create_image(0, 0, image=self._photo, anchor="nw", tags="image")
        if self.grid_var.get() and z >= 4:
            for x in range(1, w):
                c.create_line(x * z, 0, x * z, h * z, fill="#b0b0b0", tags="grid")
            for y in range(1, h):
                c.create_line(0, y * z, w * z, y * z, fill="#b0b0b0", tags="grid")
        c.create_rectangle(0, 0, w * z, h * z, outline="#404040", tags="border")
        self._draw_hotspot()
        c.configure(scrollregion=(0, 0, w * z, h * z))
        self.render_preview()
        self._update_status()

    def _draw_hotspot(self):
        self.canvas.delete("hotspot")
        if not self.doc.is_cursor:
            return
        z = self.zoom
        hx, hy = self.image.hotspot
        cx, cy = hx * z + z / 2.0, hy * z + z / 2.0
        r = max(z, 6)
        width = 2 if z >= 4 else 1
        for color, extra in (("#ffffff", 2), ("#ff2020", 0)):
            opts = dict(fill=color, width=width + extra, tags="hotspot")
            self.canvas.create_line(cx - r, cy, cx + r + 1, cy, **opts)
            self.canvas.create_line(cx, cy - r, cx, cy + r + 1, **opts)
        self.canvas.create_rectangle(hx * z, hy * z, (hx + 1) * z, (hy + 1) * z,
                                     outline="#000000", tags="hotspot")
        self.hotspot_label.configure(text="Hotspot: %d, %d" % (hx, hy))

    def _update_cells(self, points):
        """Fast partial redraw of changed pixels."""
        img = self.image
        z = self.zoom
        photo = self._photo
        for x, y in points:
            if img.in_bounds(x, y):
                photo.put(composite(img.get_pixel(x, y), (x + y) & 1 == 0),
                          to=(x * z, y * z, (x + 1) * z, (y + 1) * z))

    def _preview_image(self, img):
        w, h = img.width, img.height
        px = img.pixels
        rows = []
        for y in range(h):
            row = []
            for x in range(w):
                i = (y * w + x) * 4
                row.append(composite(px[i:i + 4], ((x >> 2) + (y >> 2)) & 1 == 0))
            rows.append("{" + " ".join(row) + "}")
        photo = tk.PhotoImage(width=w, height=h)
        photo.put(" ".join(rows))
        return photo

    def render_preview(self, img=None):
        if img is None:
            img = self.image
        self._preview_photo = self._preview_image(img)
        self.preview.delete("all")
        cw = max(self.preview.winfo_width(), 200)
        ch = max(self.preview.winfo_height(), 200)
        self.preview.create_image(cw // 2, ch // 2, image=self._preview_photo)
        if self.doc.is_cursor:
            hx, hy = img.hotspot
            self.hotspot_label.configure(text="Hotspot: %d, %d" % (hx, hy))
        else:
            self.hotspot_label.configure(text="")

    def _draw_swatches(self):
        for canvas, color in ((self.primary_swatch, self.primary),
                              (self.secondary_swatch, self.secondary)):
            canvas.delete("all")
            for i in range(4):
                for j in range(4):
                    light = (i + j) % 2 == 0
                    canvas.create_rectangle(i * 9 + 1, j * 9 + 1, i * 9 + 10, j * 9 + 10,
                                            outline="", fill=composite(color, light))

    def _update_status(self, pos=None):
        img = self.image
        parts = ["%s" % KIND_LABELS[self.doc.kind]]
        if self.doc.kind == KIND_ANI:
            parts.append("Frame %d/%d" % (self.frame_index + 1, len(self.doc.frames)))
        parts.append("Image %d x %d" % (img.width, img.height))
        parts.append("Zoom %d00%%" % self.zoom)
        if pos is not None and img.in_bounds(*pos):
            r, g, b, a = img.get_pixel(*pos)
            parts.append("Pos %d, %d" % pos)
            parts.append("RGBA %d, %d, %d, %d" % (r, g, b, a))
        self.status_var.set("    ".join(parts))

    # ------------------------------------------------------------- colours
    def set_color(self, rgba, primary=True):
        rgba = tuple(rgba)
        if primary:
            self.primary = rgba
            self.primary_alpha.set(rgba[3])
        else:
            self.secondary = rgba
            self.secondary_alpha.set(rgba[3])
        self._draw_swatches()

    def choose_color(self, primary=True):
        current = self.primary if primary else self.secondary
        result = colorchooser.askcolor(color=hex_color(current), parent=self.root,
                                       title="Choose %s color" % ("left" if primary else "right"))
        if result and result[1]:
            alpha = current[3] if current[3] else 255
            self.set_color(parse_hex(result[1]) + (alpha,), primary)

    def _alpha_changed(self, primary):
        if primary:
            self.primary = self.primary[:3] + (int(float(self.primary_alpha.get())),)
        else:
            self.secondary = self.secondary[:3] + (int(float(self.secondary_alpha.get())),)
        self._draw_swatches()

    def swap_colors(self):
        p, s = self.primary, self.secondary
        self.set_color(s, True)
        self.set_color(p, False)

    # --------------------------------------------------------------- tools
    def _event_pixel(self, event):
        x = int(self.canvas.canvasx(event.x)) // self.zoom
        y = int(self.canvas.canvasy(event.y)) // self.zoom
        return x, y

    def _on_press(self, event, primary):
        self.canvas.focus_set()
        self.begin_stroke(*self._event_pixel(event), primary=primary)

    def _on_drag(self, event):
        pos = self._event_pixel(event)
        self.continue_stroke(*pos)
        self._update_status(pos)

    def _on_release(self, event):
        self.end_stroke()

    def _on_motion(self, event):
        self._update_status(self._event_pixel(event))

    def _on_wheel_zoom(self, event):
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def begin_stroke(self, x, y, primary=True):
        """Start applying the current tool at pixel (x, y)."""
        if self._stroke is not None:
            return
        if self.playing:
            self.toggle_play()
        tool = self.tool_var.get()
        img = self.image
        color = self.primary if primary else self.secondary
        if tool == "picker":
            if img.in_bounds(x, y):
                self.set_color(img.get_pixel(x, y), primary)
            return
        if tool == "hotspot":
            if self.doc.is_cursor and img.in_bounds(x, y):
                self.set_hotspot(x, y)
            return
        if tool == "fill" and not img.in_bounds(x, y):
            return
        self.push_undo()
        self._set_dirty(True)
        if tool == "fill":
            img.flood_fill(x, y, color)
            self.render()
            return
        if tool == "eraser":
            color = (0, 0, 0, 0)
        self._stroke = {
            "tool": tool, "color": color, "start": (x, y), "last": (x, y),
            "backup": bytearray(img.pixels), "shape": [],
        }
        if tool in ("pencil", "eraser"):
            img.set_pixel(x, y, color)
            self._update_cells([(x, y)])
        else:
            self._draw_shape(x, y)

    def continue_stroke(self, x, y):
        s = self._stroke
        if s is None:
            return
        img = self.image
        if s["tool"] in ("pencil", "eraser"):
            points = line_points(s["last"][0], s["last"][1], x, y)
            for px, py in points:
                img.set_pixel(px, py, s["color"])
            self._update_cells(points)
        else:
            self._draw_shape(x, y)
        s["last"] = (x, y)

    def _draw_shape(self, x, y):
        s = self._stroke
        img = self.image
        backup = s["backup"]
        old = s["shape"]
        for px, py in old:
            if img.in_bounds(px, py):
                i = (py * img.width + px) * 4
                img.pixels[i:i + 4] = backup[i:i + 4]
        new = shape_points(s["tool"], s["start"][0], s["start"][1], x, y)
        for px, py in new:
            img.set_pixel(px, py, s["color"])
        s["shape"] = new
        self._update_cells(set(old) | set(new))

    def end_stroke(self):
        if self._stroke is None:
            return
        self._stroke = None
        self.render_preview()

    def set_hotspot(self, x, y):
        img = self.image
        if img.hotspot == (x, y):
            return
        self.push_undo()
        img.set_hotspot(x, y)
        self._set_dirty(True)
        self._refresh_lists()
        self._draw_hotspot()
        self.render_preview()

    def ask_hotspot(self):
        if not self.doc.is_cursor:
            messagebox.showinfo(APP_NAME, "Only cursors have a hotspot.", parent=self.root)
            return
        img = self.image
        value = simpledialog.askstring(
            "Hotspot", "Hotspot position as x,y:", parent=self.root,
            initialvalue="%d,%d" % img.hotspot)
        if not value:
            return
        try:
            x, y = (int(v) for v in value.replace(" ", "").split(","))
        except ValueError:
            messagebox.showerror(APP_NAME, "Enter the position as x,y.", parent=self.root)
            return
        if not img.in_bounds(x, y):
            messagebox.showerror(APP_NAME, "The hotspot must lie inside the image.",
                                 parent=self.root)
            return
        self.set_hotspot(x, y)

    # ------------------------------------------------------- image edits
    def _modify_image(self, func):
        if self._stroke is not None:
            return
        self.push_undo()
        func(self.image)
        self._set_dirty(True)
        self._document_changed()

    def clear_image(self):
        self._modify_image(lambda img: img.clear())

    def flip_horizontal(self):
        self._modify_image(lambda img: img.flip_horizontal())

    def flip_vertical(self):
        self._modify_image(lambda img: img.flip_vertical())

    def rotate(self):
        self._modify_image(lambda img: img.rotate_clockwise())

    def shift(self, dx, dy):
        self._modify_image(lambda img: img.shift(dx, dy))

    def copy_image(self):
        self.clipboard = self.image.copy()
        self.status_var.set("Image copied.")

    def paste_image(self):
        if self.clipboard is None or self._stroke is not None:
            return
        img = self.image
        src = self.clipboard
        if (src.width, src.height) != (img.width, img.height):
            src = src.resized(img.width, img.height)
        self.push_undo()
        img.pixels[:] = src.pixels
        self._set_dirty(True)
        self._document_changed()

    def add_image(self):
        img = self.image
        dlg = SizeDialog(self.root, "Add Image", img.width, img.height)
        if dlg.result:
            self.add_image_size(*dlg.result)

    def add_image_size(self, width, height, scale=True):
        """Add an image of the given size to every frame."""
        self.push_undo()
        index = len(self.frame.images)
        for frame in self.doc.frames:
            src = frame.images[min(self.image_index, len(frame.images) - 1)]
            if scale:
                new = src.resized(width, height)
            else:
                new = IconImage(width, height)
                new.set_hotspot(src.hotspot[0] * width // src.width,
                                src.hotspot[1] * height // src.height)
            frame.images.append(new)
        self.image_index = index
        self._set_dirty(True)
        self._document_changed(reset_zoom=True)

    def remove_image(self):
        if len(self.frame.images) <= 1:
            messagebox.showinfo(APP_NAME, "A file must contain at least one image.",
                                parent=self.root)
            return
        self.push_undo()
        img = self.image
        size = (img.width, img.height)
        for frame in self.doc.frames:
            if frame is self.frame:
                del frame.images[self.image_index]
            elif len(frame.images) > 1:
                # Remove the matching size from other frames as well.
                for i, other in enumerate(frame.images):
                    if (other.width, other.height) == size:
                        del frame.images[i]
                        break
        self._set_dirty(True)
        self._document_changed(reset_zoom=True)

    def resize_image(self):
        img = self.image
        dlg = SizeDialog(self.root, "Resize Image", img.width, img.height)
        if dlg.result:
            w, h, scale = dlg.result
            self.resize_current(w, h, scale)

    def resize_current(self, width, height, scale=True):
        img = self.image
        self.push_undo()
        if scale:
            new = img.resized(width, height)
        else:
            new = IconImage(width, height, hotspot=img.hotspot)
            for y in range(min(height, img.height)):
                for x in range(min(width, img.width)):
                    new.set_pixel(x, y, img.get_pixel(x, y))
        self.frame.images[self.image_index] = new
        self._set_dirty(True)
        self._document_changed(reset_zoom=True)

    # -------------------------------------------------------------- frames
    def _require_ani(self):
        return self.doc.kind == KIND_ANI and self._stroke is None

    def add_frame(self):
        if not self._require_ani():
            return
        self.push_undo()
        images = [IconImage(i.width, i.height, hotspot=i.hotspot) for i in self.frame.images]
        self.doc.frames.insert(self.frame_index + 1, IconFrame(images, self.frame.rate))
        self.frame_index += 1
        self._set_dirty(True)
        self._document_changed()

    def duplicate_frame(self):
        if not self._require_ani():
            return
        self.push_undo()
        self.doc.frames.insert(self.frame_index + 1, self.frame.copy())
        self.frame_index += 1
        self._set_dirty(True)
        self._document_changed()

    def delete_frame(self):
        if not self._require_ani():
            return
        if len(self.doc.frames) <= 1:
            messagebox.showinfo(APP_NAME, "An animation needs at least one frame.",
                                parent=self.root)
            return
        self.push_undo()
        del self.doc.frames[self.frame_index]
        self._set_dirty(True)
        self._document_changed()

    def move_frame(self, delta):
        if not self._require_ani():
            return
        new = self.frame_index + delta
        if not 0 <= new < len(self.doc.frames):
            return
        self.push_undo()
        frames = self.doc.frames
        frames[self.frame_index], frames[new] = frames[new], frames[self.frame_index]
        self.frame_index = new
        self._set_dirty(True)
        self._document_changed()

    def _read_rate(self):
        try:
            rate = int(self.rate_var.get())
        except (tk.TclError, ValueError):
            return None
        return rate if 1 <= rate <= 6000 else None

    def _rate_changed(self):
        if self.doc.kind != KIND_ANI:
            return
        rate = self._read_rate()
        if rate is None:
            self.rate_var.set(self.frame.rate)
            return
        if rate != self.frame.rate:
            self.push_undo()
            self.frame.rate = rate
            self._set_dirty(True)
            self._refresh_lists()

    def rate_to_all(self):
        if not self._require_ani():
            return
        rate = self._read_rate() or self.frame.rate
        self.push_undo()
        for f in self.doc.frames:
            f.rate = rate
        self._set_dirty(True)
        self._refresh_lists()

    def toggle_play(self):
        if self.playing:
            self.playing = False
            if self._play_job is not None:
                self.root.after_cancel(self._play_job)
                self._play_job = None
            self.play_button.configure(text="\u25b6 Play")
            self.render_preview()
            return
        if self.doc.kind != KIND_ANI:
            return
        self.playing = True
        self._play_step = self.frame_index
        self.play_button.configure(text="\u25a0 Stop")
        self._play_tick()

    def _play_tick(self):
        if not self.playing:
            return
        frames = self.doc.frames
        frame = frames[self._play_step % len(frames)]
        size = (self.image.width, self.image.height)
        img = next((i for i in frame.images if (i.width, i.height) == size), frame.images[0])
        self.render_preview(img)
        self._play_step = (self._play_step + 1) % len(frames)
        self._play_job = self.root.after(max(1, frame.rate * 1000 // 60), self._play_tick)

    def edit_properties(self):
        if self.doc.kind != KIND_ANI:
            return
        dlg = PropertiesDialog(self.root, self.doc.title, self.doc.author)
        if dlg.result and dlg.result != (self.doc.title, self.doc.author):
            self.push_undo()
            self.doc.title, self.doc.author = dlg.result
            self._set_dirty(True)

    # ----------------------------------------------------------- selection
    def _image_selected(self, event=None):
        sel = self.image_list.curselection()
        if sel and sel[0] != self.image_index:
            self.select(image_index=sel[0])

    def _frame_selected(self, event=None):
        sel = self.frame_list.curselection()
        if sel and sel[0] != self.frame_index:
            self.select(frame_index=sel[0])

    def select(self, frame_index=None, image_index=None):
        if self._stroke is not None:
            return
        old = self.image
        if frame_index is not None:
            self._rate_changed()
            self.frame_index = frame_index
            # Keep the same image size selected when switching frames.
            size = (old.width, old.height)
            for i, img in enumerate(self.frame.images):
                if (img.width, img.height) == size:
                    self.image_index = i
                    break
        if image_index is not None:
            self.image_index = image_index
        new = self.image
        self._document_changed(reset_zoom=(old.width, old.height) != (new.width, new.height))

    # ---------------------------------------------------------------- view
    def set_zoom(self, zoom):
        zoom = max(1, min(MAX_ZOOM, int(zoom)))
        if zoom != self.zoom:
            self.zoom = zoom
            self.render()

    def zoom_in(self):
        self.set_zoom(self.zoom + (1 if self.zoom < 4 else 2 if self.zoom < 16 else 4))

    def zoom_out(self):
        self.set_zoom(self.zoom - (1 if self.zoom <= 4 else 2 if self.zoom <= 16 else 4))

    def zoom_fit(self, render=True):
        img = self.image
        self.root.update_idletasks()
        avail = min(max(self.canvas.winfo_width(), 400), max(self.canvas.winfo_height(), 400))
        self.zoom = max(1, min(MAX_ZOOM, (avail - 20) // max(img.width, img.height)))
        if render:
            self.render()

    # ----------------------------------------------------------- file ops
    def confirm_discard(self):
        """Ask to save unsaved changes. Returns False if the user cancels."""
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            APP_NAME, "Save changes to %s?" % (
                os.path.basename(self.path) if self.path else "Untitled"),
            parent=self.root)
        if answer is None:
            return False
        if answer:
            return self.save()
        return True

    def _reset(self, doc, path):
        if self.playing:
            self.toggle_play()
        self.doc = doc
        self.path = path
        self.frame_index = 0
        self.image_index = 0
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._set_dirty(False)
        self._document_changed(reset_zoom=True)

    def new_document(self, kind=None, sizes=None):
        if not self.confirm_discard():
            return
        if sizes is None:
            dlg = NewDocumentDialog(self.root, self.doc.kind)
            if not dlg.result:
                return
            kind, sizes = dlg.result
        doc = IconDocument.new(kind or KIND_ICO, sizes)
        self._reset(doc, None)

    def open_file(self):
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(parent=self.root, filetypes=FILE_TYPES,
                                          title="Open")
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            doc = fileio.load(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, "Cannot open %s:\n%s" % (path, exc),
                                 parent=self.root)
            return False
        self._reset(doc, path)
        return True

    def save(self):
        if self.path is None:
            return self.save_as()
        return self.save_to_path(self.path)

    def save_as(self):
        kind = self.doc.kind
        initial = os.path.splitext(os.path.basename(self.path))[0] if self.path else "untitled"
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save As", filetypes=SAVE_TYPES[kind],
            defaultextension=fileio.EXTENSIONS[kind],
            initialfile=initial + fileio.EXTENSIONS[kind])
        if not path:
            return False
        return self.save_to_path(path)

    def save_to_path(self, path, confirm=True):
        """Save to a path; the file extension decides the format."""
        self._rate_changed()
        kind = fileio.kind_from_path(path)
        if kind is None:
            kind = self.doc.kind
            path += fileio.EXTENSIONS[kind]
        doc = self.doc
        if kind != doc.kind:
            if doc.kind == KIND_ANI and len(doc.frames) > 1 and confirm:
                if not messagebox.askokcancel(
                        APP_NAME, "%s files cannot be animated. Only the current frame "
                        "will be kept. Continue?" % KIND_LABELS[kind], parent=self.root):
                    return False
            self.push_undo()
            frame = self.frame if doc.kind == KIND_ANI else doc.frames[0]
            doc.frames = [frame]
            doc.kind = kind
        try:
            fileio.save(doc, path)
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, "Cannot save %s:\n%s" % (path, exc),
                                 parent=self.root)
            self._document_changed()
            return False
        self.path = path
        self._set_dirty(False)
        self._document_changed()
        self.status_var.set("Saved %s" % path)
        return True

    def import_png(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=PNG_TYPES,
                                          title="Import PNG")
        if path:
            self.import_png_path(path)

    def import_png_path(self, path):
        """Load a PNG and paste it, scaled, into the current image."""
        try:
            with open(path, "rb") as fh:
                width, height, rgba = png.decode(fh.read())
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, "Cannot import %s:\n%s" % (path, exc),
                                 parent=self.root)
            return False
        src = _fit_rgba(width, height, rgba)
        img = self.image
        if (src.width, src.height) != (img.width, img.height):
            src = src.resized(img.width, img.height)
        self.push_undo()
        img.pixels[:] = src.pixels
        self._set_dirty(True)
        self._document_changed()
        return True

    def export_png(self):
        img = self.image
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export PNG", filetypes=PNG_TYPES,
            defaultextension=".png", initialfile="image_%dx%d.png" % (img.width, img.height))
        if not path:
            return
        try:
            fileio.export_png(img, path)
        except OSError as exc:
            messagebox.showerror(APP_NAME, "Cannot export %s:\n%s" % (path, exc),
                                 parent=self.root)

    def about(self):
        from . import __version__
        messagebox.showinfo(
            "About", "%s %s\n\nCreate and edit Windows icons (.ico), cursors (.cur) "
            "and animated cursors (.ani).\n\nWritten in Python and Tkinter."
            % (APP_NAME, __version__), parent=self.root)

    def quit(self):
        if self.confirm_discard():
            if self.playing:
                self.toggle_play()
            self.root.destroy()


def _fit_rgba(width, height, rgba):
    """Make an IconImage from RGBA data of any size, shrinking it if needed."""
    if width <= MAX_SIZE and height <= MAX_SIZE:
        return IconImage(width, height, rgba)
    scale = max(width, height) / float(MAX_SIZE)
    nw = max(1, min(MAX_SIZE, int(round(width / scale))))
    nh = max(1, min(MAX_SIZE, int(round(height / scale))))
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        sy = y * height // nh
        for x in range(nw):
            sx = x * width // nw
            s = (sy * width + sx) * 4
            d = (y * nw + x) * 4
            out[d:d + 4] = rgba[s:s + 4]
    return IconImage(nw, nh, out)


def main(argv=None):
    import sys
    argv = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    IconEditorApp(root, argv[0] if argv else None)
    root.mainloop()
