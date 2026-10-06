import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from icon_editor.model import IconDocument, IconImage, KIND_ANI  # noqa: E402

R = (255, 0, 0, 255)
G = (0, 255, 0, 255)


class IconImageTests(unittest.TestCase):
    def test_size_limits(self):
        with self.assertRaises(ValueError):
            IconImage(0, 16)
        with self.assertRaises(ValueError):
            IconImage(257, 16)
        IconImage(256, 1)

    def test_hotspot_clamped(self):
        img = IconImage(8, 8, hotspot=(20, -3))
        self.assertEqual(img.hotspot, (7, 0))

    def test_flood_fill(self):
        img = IconImage(5, 5)
        for y in range(5):
            img.set_pixel(2, y, R)
        img.flood_fill(0, 0, G)
        self.assertEqual(img.get_pixel(1, 4), G)
        self.assertEqual(img.get_pixel(2, 2), R)
        self.assertEqual(img.get_pixel(3, 0), (0, 0, 0, 0))

    def test_flips_and_rotate(self):
        img = IconImage(3, 2, hotspot=(0, 0))
        img.set_pixel(0, 0, R)
        img.flip_horizontal()
        self.assertEqual(img.get_pixel(2, 0), R)
        self.assertEqual(img.hotspot, (2, 0))
        img.flip_vertical()
        self.assertEqual(img.get_pixel(2, 1), R)
        self.assertEqual(img.hotspot, (2, 1))
        img.rotate_clockwise()
        self.assertEqual((img.width, img.height), (2, 3))
        self.assertEqual(img.get_pixel(0, 2), R)
        self.assertEqual(img.hotspot, (0, 2))

    def test_shift_wraps(self):
        img = IconImage(3, 3)
        img.set_pixel(2, 2, R)
        img.shift(1, 1)
        self.assertEqual(img.get_pixel(0, 0), R)

    def test_resize(self):
        img = IconImage(4, 4)
        img.clear(R)
        small = img.resized(2, 2)
        self.assertEqual(small.get_pixel(1, 1), R)
        big = img.resized(8, 8)
        self.assertEqual(big.get_pixel(7, 7), R)

    def test_document_copy_is_deep(self):
        doc = IconDocument.new(KIND_ANI, [(16, 16)])
        dup = doc.copy()
        dup.images[0].set_pixel(0, 0, R)
        self.assertNotEqual(doc, dup)


if __name__ == "__main__":
    unittest.main()
