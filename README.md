# Icon-Editor

An icon editor written in Python and Tkinter. It creates and edits Windows
icons (`.ico`), cursors (`.cur`) and animated cursors (`.ani`).

## Requirements

* Python 3.8 or newer
* Tkinter. It comes with the python.org installers on Windows and macOS. On
  Debian/Ubuntu, install it with `sudo apt install python3-tk`.

You don't need any third-party packages. The file formats (ICO/CUR with
BMP or PNG images, ANI RIFF containers and PNG) are implemented in pure
Python.

## Running

```sh
python main.py                 # start with a new 32x32 icon
python main.py path/to/file.ani
python -m icon_editor file.ico # alternative
```

## Features

* **File types:** Open and save `.ico`, `.cur` and `.ani` files. Save As
  converts between them based on the file extension.
* **Multiple image sizes per file:** For example, 16x16, 32x32, 48x48 and
  256x256. Sizes from 1 to 256 px are supported. You can add, remove and
  resize images. A new size can start blank or as a scaled copy of the
  current image.
* **32-bit colour with alpha.** Images smaller than 256 px are stored as
  32-bit DIBs with an AND mask. 256 px images are stored as PNG, like
  Windows does. The editor reads 1, 4, 8, 16, 24 and 32-bit bitmaps, plus
  PNG-compressed entries.
* **Drawing tools:** Pencil, eraser, flood fill, line, rectangle, filled
  rectangle, ellipse, filled ellipse and colour picker. The left mouse
  button draws with the left colour and the right button with the right
  colour. Each colour has its own alpha slider.
* **Image operations:** Undo/redo, clear, flip, rotate, shift (wraps around
  the edges), and copy/paste an image between sizes (it's scaled
  automatically). You can import a PNG into the current image and export
  the current image as a PNG.
* **Cursors:** Set the hotspot with the Hotspot tool or with
  *Image → Set Hotspot...*.
* **Animated cursors:**
  * Add, duplicate, delete and reorder frames.
  * Set a display rate for each frame, in jiffies (1/60 s).
  * Play the animation in the preview.
  * Edit the title and author.
* **Zoom and grid:** Zoom with *View* or with Ctrl + mouse wheel. You can
  turn the pixel grid on and off.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+N / Ctrl+O | New / Open |
| Ctrl+S / Ctrl+Shift+S | Save / Save As |
| Ctrl+Z / Ctrl+Y | Undo / Redo |
| Ctrl+C / Ctrl+V | Copy / Paste image |
| Ctrl++ / Ctrl+- | Zoom in / out |
| Delete | Clear image |

## Tests

```sh
python -m unittest discover -s tests
```

GUI tests need a display. They're skipped automatically when no display is
available. On a headless Linux machine, use `xvfb-run`. If Pillow is
installed, extra tests cross-check the file formats against it.

## Project layout

```
main.py                 launcher
icon_editor/app.py      Tkinter user interface
icon_editor/model.py    document model (images, frames, hotspots)
icon_editor/ico.py      .ico / .cur reader and writer
icon_editor/ani.py      .ani reader and writer
icon_editor/png.py      PNG encoder/decoder
icon_editor/fileio.py   loading/saving helpers
tests/                  unit tests
```
