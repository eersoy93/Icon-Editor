import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from icon_editor import fileio  # noqa: E402
from icon_editor.model import IconDocument, KIND_ANI, KIND_CUR, KIND_ICO  # noqa: E402

try:
    import tkinter as tk
    from icon_editor import app as app_module
    _root = tk.Tk()
    _root.destroy()
    HAVE_DISPLAY = True
except Exception:  # pragma: no cover - depends on environment
    HAVE_DISPLAY = False

RED = (255, 0, 0, 255)


@unittest.skipUnless(HAVE_DISPLAY, "Tk display not available")
class AppTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = app_module.IconEditorApp(self.root)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.app.dirty = False
        self.root.destroy()
        self.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_draw_undo_redo(self):
        app = self.app
        app.set_color(RED)
        app.tool_var.set("pencil")
        app.begin_stroke(1, 1)
        app.continue_stroke(4, 1)
        app.end_stroke()
        self.assertEqual(app.image.get_pixel(3, 1), RED)
        self.assertTrue(app.dirty)
        app.undo()
        self.assertEqual(app.image.get_pixel(3, 1), (0, 0, 0, 0))
        app.redo()
        self.assertEqual(app.image.get_pixel(3, 1), RED)

    def test_shapes_and_fill(self):
        app = self.app
        app.set_color(RED)
        app.tool_var.set("rect")
        app.begin_stroke(2, 2)
        app.continue_stroke(20, 20)
        app.continue_stroke(5, 5)  # preview of the larger shape is removed
        app.end_stroke()
        self.assertEqual(app.image.get_pixel(5, 3), RED)
        self.assertEqual(app.image.get_pixel(20, 2)[3], 0)
        app.tool_var.set("fill")
        app.set_color((0, 0, 255, 255))
        app.begin_stroke(3, 3)
        self.assertEqual(app.image.get_pixel(4, 4), (0, 0, 255, 255))
        self.assertEqual(app.image.get_pixel(0, 0)[3], 0)
        app.tool_var.set("picker")
        app.begin_stroke(2, 2, primary=False)
        self.assertEqual(app.secondary, RED)

    def test_save_and_open_ico(self):
        app = self.app
        app.set_color(RED)
        app.begin_stroke(0, 0)
        app.end_stroke()
        app.add_image_size(16, 16, scale=True)
        path = self.path("a.ico")
        self.assertTrue(app.save_to_path(path))
        self.assertFalse(app.dirty)
        doc = fileio.load(path)
        self.assertEqual([(i.width, i.height) for i in doc.images], [(32, 32), (16, 16)])
        self.assertTrue(app.open_path(path))
        self.assertEqual(app.doc, doc)

    def test_cursor_hotspot(self):
        app = self.app
        app._reset(IconDocument.new(KIND_CUR, [(32, 32)]), None)
        app.tool_var.set("hotspot")
        app.begin_stroke(7, 9)
        self.assertEqual(app.image.hotspot, (7, 9))
        path = self.path("c.cur")
        app.save_to_path(path)
        self.assertEqual(fileio.load(path).images[0].hotspot, (7, 9))

    def test_animation(self):
        app = self.app
        app._reset(IconDocument.new(KIND_ANI, [(32, 32)]), None)
        app.set_color(RED)
        app.begin_stroke(0, 0)
        app.end_stroke()
        app.duplicate_frame()
        app.add_frame()
        self.assertEqual(len(app.doc.frames), 3)
        self.assertEqual(app.frame_index, 2)
        app.rate_var.set(30)
        app._rate_changed()
        app.move_frame(-1)
        self.assertEqual(app.frame_index, 1)
        app.toggle_play()
        self.root.update()
        app.toggle_play()
        app.select(frame_index=0)
        app.delete_frame()
        path = self.path("x.ani")
        app.save_to_path(path)
        doc = fileio.load(path)
        self.assertEqual(len(doc.frames), 2)
        self.assertEqual([f.rate for f in doc.frames], [30, 10])

    def test_convert_ani_to_ico_on_save(self):
        app = self.app
        app._reset(IconDocument.new(KIND_ANI, [(16, 16)]), None)
        app.add_frame()
        path = self.path("conv.ico")
        with mock.patch.object(app_module.messagebox, "askokcancel", return_value=True):
            self.assertTrue(app.save_to_path(path))
        self.assertEqual(app.doc.kind, KIND_ICO)
        self.assertEqual(fileio.load(path).kind, KIND_ICO)

    def test_image_operations(self):
        app = self.app
        app.set_color(RED)
        app.begin_stroke(0, 0)
        app.end_stroke()
        app.flip_horizontal()
        self.assertEqual(app.image.get_pixel(31, 0), RED)
        app.copy_image()
        app.add_image_size(64, 64, scale=False)
        app.paste_image()
        self.assertEqual(app.image.get_pixel(63, 0), RED)
        app.resize_current(48, 48)
        self.assertEqual((app.image.width, app.image.height), (48, 48))
        app.remove_image()
        self.assertEqual(len(app.frame.images), 1)
        app.zoom_in()
        app.zoom_out()
        app.clear_image()
        self.assertEqual(app.image.get_pixel(31, 0)[3], 0)

    def test_import_png(self):
        from icon_editor import png
        path = self.path("big.png")
        with open(path, "wb") as fh:
            fh.write(png.encode(300, 300, bytes(RED) * (300 * 300)))
        self.assertTrue(self.app.import_png_path(path))
        self.assertEqual(self.app.image.get_pixel(10, 10), RED)

    def test_open_invalid_file(self):
        path = self.path("bad.ico")
        with open(path, "wb") as fh:
            fh.write(b"nonsense")
        with mock.patch.object(app_module.messagebox, "showerror") as err:
            self.assertFalse(self.app.open_path(path))
            err.assert_called_once()


if __name__ == "__main__":
    unittest.main()
