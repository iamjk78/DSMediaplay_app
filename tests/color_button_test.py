import tkinter as tk
import unittest

from gui_app.color_button import GREEN, RED, ColorButton, make_color_button


class ColorButtonTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.clicks = []
        self.button = ColorButton(self.root, "Start", lambda: self.clicks.append(1), ("Helvetica", 12, "bold"), GREEN)
        self.button.pack()
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def fill(self):
        return self.button.itemcget(self.button.find_withtag("all")[0], "fill")

    def click(self, x, y, release_x=None, release_y=None):
        self.button.event_generate("<Enter>", x=x, y=y)
        self.button.event_generate("<ButtonPress-1>", x=x, y=y)
        self.button.event_generate("<ButtonRelease-1>", x=x if release_x is None else release_x,
                                   y=y if release_y is None else release_y)
        self.root.update()

    def test_click_runs_the_command_once(self):
        self.click(10, 10)

        self.assertEqual(self.clicks, [1])

    def test_releasing_outside_the_button_does_not_run_the_command(self):
        self.click(10, 10, release_x=self.button.winfo_width() + 50, release_y=10)

        self.assertEqual(self.clicks, [])

    def test_colour_follows_hover_and_press(self):
        self.assertEqual(self.fill(), GREEN.normal)

        self.button.event_generate("<Enter>")
        self.assertEqual(self.fill(), GREEN.hover)

        self.button.event_generate("<ButtonPress-1>", x=5, y=5)
        self.assertEqual(self.fill(), GREEN.pressed)

        self.button.event_generate("<Leave>")
        self.assertEqual(self.fill(), GREEN.normal)

    def test_configure_and_cget_work_like_a_button(self):
        before = self.button.winfo_reqwidth()

        self.button.configure(text="Spustit akci", font=("Helvetica", 16, "bold"))
        self.button.config(text="Spustit akci dlouhý text")

        self.assertEqual(self.button.cget("text"), "Spustit akci dlouhý text")
        self.assertEqual(self.button.cget("font"), ("Helvetica", 16, "bold"))
        self.assertGreater(self.button.winfo_reqwidth(), before)

    def test_larger_font_makes_a_larger_button(self):
        small = ColorButton(self.root, "Start", None, ("Helvetica", 12, "bold"), RED)
        large = ColorButton(self.root, "Start", None, ("Helvetica", 14, "bold"), RED)

        self.assertGreater(large.winfo_reqwidth(), small.winfo_reqwidth())
        self.assertGreater(large.winfo_reqheight(), small.winfo_reqheight())

    def test_factory_returns_a_working_button_on_this_platform(self):
        button = make_color_button(self.root, "Quit", lambda: self.clicks.append(2), ("Helvetica", 12, "bold"), RED)
        button.pack()
        self.root.update()

        self.assertEqual(button.cget("text"), "Quit")


if __name__ == "__main__":
    unittest.main()
