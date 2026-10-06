# Icon-Editor
An icon (.ico, .cur, .ani) editor in Python and Tkinter.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)

## Features

* Create and edit Windows **icons** (`.ico`), **cursors** (`.cur`) and
  **animated cursors** (`.ani`).
* Multiple image sizes per file (1–256 px, e.g. 16, 32, 48, 256). New sizes
  can be blank or resampled from an existing image.
* Full 32-bit RGBA colour with per-colour alpha (transparency).
* Drawing tools: pencil, eraser, flood fill, line, rectangle, ellipse
  (outlined or filled), colour picker and cursor **hotspot** tool.
* Left/right mouse buttons draw with primary/secondary colours.
* Undo/redo, clear, flip horizontally/vertically, rotate 90°.
* Animation frames for `.ani`: add, duplicate, delete, reorder, per-frame
  display rate (in jiffies, 1/60 s), title/author metadata and a live
  animated preview.
* Import PNG images into the current image and export images as PNG.
* Reads 1/4/8/16/24/32-bit BMP and PNG-compressed images inside icon files.
  Writes 32-bit BMP images (plus AND mask) and PNG for 256 px images.
* No third-party dependencies – only the Python standard library.

## Requirements

* Python 3.8 or newer with Tkinter (on Debian/Ubuntu: `sudo apt install python3-tk`).

## Usage

```sh
python3 main.py                 # start with a new 32×32 icon
python3 main.py path/to/file.ani  # open an existing file
python3 -m icon_editor          # alternative way to start
```

Keyboard shortcuts:

| Key | Action |
| --- | --- |
| Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Shift+S | New / Open / Save / Save As |
| Ctrl+Z / Ctrl+Y | Undo / Redo |
| Ctrl++ / Ctrl+- / Ctrl+mouse wheel | Zoom in / out |
| P, E, F, L, R, O, I, H | Pencil, Eraser, Fill, Line, Rectangle, Ellipse, Color picker, Hotspot |
| Del | Clear current image |

The file type is chosen by the extension used in *Save As*, so a document can
be converted between `.ico`, `.cur` and `.ani`. Adding a frame to an icon or
cursor converts it to an animated cursor.

## Running the tests

```sh
python3 -m unittest discover -s tests -v
```
