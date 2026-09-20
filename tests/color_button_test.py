import tkinter as tk
import unittest

from gui_app.color_button import (DISABLED, GREEN, GREEN_DARK, RED, ColorButton, button_enabled, make_color_button,
                                  set_button_colors, set_button_enabled)


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


def luminance(colour):
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first, second):
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class ColourReadabilityTest(unittest.TestCase):
    def test_the_text_is_readable_on_every_shade_the_buttons_use(self):
        for name, colors in (("GREEN", GREEN), ("RED", RED), ("GREEN_DARK", GREEN_DARK)):
            for shade in ("normal", "hover", "pressed"):
                with self.subTest(colors=name, shade=shade):
                    self.assertGreaterEqual(contrast(colors.text, getattr(colors, shade)), 4.5)

    def test_light_green_has_black_text_and_dark_green_white_text(self):
        self.assertEqual(GREEN.text, "#000000")
        self.assertEqual(GREEN_DARK.text, "#ffffff")


class SetColorsTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")

    def tearDown(self):
        self.root.destroy()

    def test_changing_the_colours_redraws_the_fill_and_the_text(self):
        button = make_color_button(self.root, "Input", None, ("Helvetica", 12, "bold"), GREEN)
        button.pack()

        set_button_colors(button, GREEN_DARK)
        self.root.update()

        if isinstance(button, ColorButton):
            self.assertEqual(button.itemcget(button.find_withtag("all")[0], "fill"), GREEN_DARK.normal)
            self.assertEqual(button.itemcget(button.find_withtag("all")[1], "fill"), "#ffffff")
        else:
            self.assertEqual((button.cget("background"), button.cget("foreground")), (GREEN_DARK.normal, "#ffffff"))



class DisabledButtonTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.root.destroy)
        self.clicks = []
        self.button = ColorButton(self.root, "Start", lambda: self.clicks.append(1), ("Helvetica", 12, "bold"), GREEN)
        self.button.pack()
        self.root.update()

    def fill(self):
        return self.button.itemcget(self.button.find_withtag("all")[0], "fill")

    def click(self):
        self.button.event_generate("<ButtonPress-1>", x=5, y=5)
        self.button.event_generate("<ButtonRelease-1>", x=5, y=5)

    def test_it_is_enabled_at_first(self):
        self.assertTrue(self.button.enabled)
        self.assertEqual(self.fill(), GREEN.normal)

    def test_disabled_it_is_grey_and_keeps_its_size_and_text(self):
        size = (self.button.winfo_reqwidth(), self.button.winfo_reqheight())

        self.button.set_enabled(False)
        self.root.update()

        self.assertEqual(self.fill(), DISABLED.normal)
        self.assertEqual((self.button.winfo_reqwidth(), self.button.winfo_reqheight()), size)
        self.assertEqual(self.button.cget("text"), "Start")

    def test_disabled_it_ignores_the_pointer_and_clicks(self):
        self.button.set_enabled(False)

        self.button.event_generate("<Enter>")
        self.assertEqual(self.fill(), DISABLED.normal)
        self.click()

        self.assertEqual(self.clicks, [])
        self.assertEqual(self.fill(), DISABLED.normal)

    def test_enabled_again_it_has_its_colour_and_works(self):
        self.button.set_enabled(False)
        self.button.set_enabled(True)

        self.assertEqual(self.fill(), GREEN.normal)
        self.click()
        self.assertEqual(self.clicks, [1])

    def test_a_press_that_started_before_it_was_disabled_does_not_run_it(self):
        self.button.event_generate("<ButtonPress-1>", x=5, y=5)
        self.button.set_enabled(False)
        self.button.event_generate("<ButtonRelease-1>", x=5, y=5)

        self.assertEqual(self.clicks, [])

    def test_the_helpers_work_for_the_canvas_button(self):
        set_button_enabled(self.button, False, GREEN)
        self.assertFalse(button_enabled(self.button))
        set_button_enabled(self.button, True, GREEN)
        self.assertTrue(button_enabled(self.button))

    def test_the_helpers_work_for_a_native_button_too(self):
        native = tk.Button(self.root, text="Native", command=lambda: self.clicks.append(1), background=GREEN.normal)
        native.pack()

        set_button_enabled(native, False, GREEN)
        self.assertFalse(button_enabled(native))
        self.assertEqual(str(native.cget("background")), DISABLED.normal)
        native.invoke()
        self.assertEqual(self.clicks, [])
        set_button_enabled(native, True, GREEN)
        self.assertTrue(button_enabled(native))
        self.assertEqual(str(native.cget("background")), GREEN.normal)
        native.invoke()
        self.assertEqual(self.clicks, [1])


if __name__ == "__main__":
    unittest.main()
