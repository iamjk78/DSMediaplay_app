import time
import tkinter as tk
import unittest

from gui_app.tooltip import TOOLTIP_DELAY_MS, Tooltip


class TooltipTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.button = tk.Button(self.root, text="button")
        self.button.pack()
        self.text = "first"
        self.tooltip = Tooltip(self.button, lambda: self.text, delay_ms=40)
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def wait(self, milliseconds):
        end = time.monotonic() + milliseconds / 1000
        while time.monotonic() < end:
            self.root.update()
            time.sleep(0.005)

    def visible(self):
        window = self.tooltip._window
        return window is not None and window.state() == "normal"

    def test_default_delay_is_half_a_second(self):
        self.assertEqual(TOOLTIP_DELAY_MS, 500)
        self.assertEqual(Tooltip(self.button, lambda: "x")._delay_ms, 500)

    def test_appears_only_after_the_delay(self):
        self.button.event_generate("<Enter>")
        self.wait(10)
        self.assertFalse(self.visible())

        self.wait(120)

        self.assertTrue(self.visible())

    def test_hides_when_the_pointer_leaves(self):
        self.button.event_generate("<Enter>")
        self.wait(120)

        self.button.event_generate("<Leave>")
        self.root.update()

        self.assertFalse(self.visible())

    def test_never_appears_when_the_pointer_leaves_before_the_delay(self):
        self.button.event_generate("<Enter>")
        self.wait(10)
        self.button.event_generate("<Leave>")

        self.wait(150)

        self.assertFalse(self.visible())

    def test_hides_when_the_button_is_clicked(self):
        self.button.event_generate("<Enter>")
        self.wait(120)

        self.button.event_generate("<ButtonPress-1>")
        self.root.update()

        self.assertFalse(self.visible())

    def test_text_is_read_when_it_appears(self):
        self.text = "second"
        self.button.event_generate("<Enter>")
        self.wait(120)

        self.assertEqual(self.tooltip._label.cget("text"), "second")

    def test_second_appearance_shows_the_current_text(self):
        self.button.event_generate("<Enter>")
        self.wait(120)
        self.button.event_generate("<Leave>")
        self.text = "changed language"

        self.button.event_generate("<Enter>")
        self.wait(120)

        self.assertTrue(self.visible())
        self.assertEqual(self.tooltip._label.cget("text"), "changed language")

    def test_destroying_the_widget_with_a_pending_tooltip_raises_nothing(self):
        self.button.event_generate("<Enter>")
        self.button.destroy()

        self.wait(120)  # the cancelled timer must not fire on a destroyed widget


if __name__ == "__main__":
    unittest.main()
