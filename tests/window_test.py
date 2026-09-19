import json
import os
import tempfile
import tkinter as tk
import unittest

from gui_app.gui import DSMediaplayApp


class WindowSizeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = os.path.join(self.directory.name, "logins.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
        try:
            self.app = DSMediaplayApp(path)
        except tk.TclError:
            self.skipTest("no display available")
        self.app.update()

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.destroy()
        self.directory.cleanup()

    def fits_its_content(self):
        self.app.update()
        return (self.app.winfo_width(), self.app.winfo_height()) == (self.app.winfo_reqwidth(),
                                                                     self.app.winfo_reqheight())

    def test_the_user_cannot_resize_the_window(self):
        self.assertEqual(self.app.resizable(), (False, False))

    def test_the_window_fits_its_content(self):
        self.assertTrue(self.fits_its_content())

    def test_the_window_still_adapts_when_the_language_changes(self):
        self.app.lang.set_language("en")
        self.app.refresh_ui()

        self.assertTrue(self.fits_its_content())

    def test_the_window_still_adapts_when_the_font_size_changes(self):
        before = self.app.winfo_width()

        self.app.update_font(("Helvetica", 18))
        self.app.refresh_ui()

        self.assertTrue(self.fits_its_content())
        self.assertGreater(self.app.winfo_width(), before)

    def test_start_lines_up_with_the_right_edge_of_the_minus_buttons(self):
        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)

        minus = [w for w in walk(self.app) if hasattr(w, "tooltip") and w.cget("text") == "−"]
        right = lambda w: w.winfo_rootx() + w.winfo_width()

        self.assertEqual(len(minus), 2)
        for button in minus:
            self.assertAlmostEqual(right(self.app.start_button), right(button), delta=1)


if __name__ == "__main__":
    unittest.main()
