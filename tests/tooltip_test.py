import time
import tkinter as tk
from tkinter import ttk
import unittest

from unittest.mock import patch

from gui_app.color_button import GREEN, ColorButton
from gui_app.tooltip import (GAP_LEFT_OF_POINTER, GAP_RIGHT_OF_POINTER, TOOLTIP_DELAY_MS, WATCH_INTERVAL_MS,
                             Tooltip)


class TooltipTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        # The synthetic events below do not move the real pointer, so it is taken to be on the widget
        self.over = True
        patcher = patch.object(Tooltip, "_pointer_over_widget", lambda tooltip: self.over)
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def hover_at(self, x, y):
        self.button.event_generate("<Enter>", x=1, y=1, rootx=x, rooty=y)
        self.wait(120)

    def rectangle(self):
        window = self.tooltip._window
        return window.winfo_rootx(), window.winfo_rooty(), window.winfo_width(), window.winfo_height()

    def test_appears_to_the_right_of_the_pointer_centred_on_it(self):
        self.hover_at(400, 300)

        x, y, width, height = self.rectangle()

        self.assertEqual(x, 400 + GAP_RIGHT_OF_POINTER)
        self.assertAlmostEqual(y + height / 2, 300, delta=2)

    def test_never_covers_the_pointer(self):
        for pointer in ((400, 300), (5, 5), (self.root.winfo_screenwidth() - 3, 200)):
            with self.subTest(pointer=pointer):
                self.button.event_generate("<Leave>")
                self.hover_at(*pointer)

                x, y, width, height = self.rectangle()

                self.assertFalse(x <= pointer[0] < x + width and y <= pointer[1] < y + height)

    def test_moves_to_the_left_of_the_pointer_when_there_is_no_room_on_the_right(self):
        pointer_x = self.root.winfo_screenwidth() - 10
        self.hover_at(pointer_x, 300)

        x, y, width, height = self.rectangle()

        self.assertEqual(x + width, pointer_x - GAP_LEFT_OF_POINTER)

    def test_stays_inside_the_screen_vertically(self):
        self.hover_at(400, self.root.winfo_screenheight() - 1)

        x, y, width, height = self.rectangle()

        self.assertLessEqual(y + height, self.root.winfo_screenheight())

    def test_uses_the_latest_pointer_position(self):
        self.button.event_generate("<Enter>", x=1, y=1, rootx=400, rooty=300)
        self.button.event_generate("<Motion>", x=2, y=2, rootx=450, rooty=310)
        self.wait(120)

        self.assertEqual(self.rectangle()[0], 450 + GAP_RIGHT_OF_POINTER)

    def test_destroying_the_widget_with_a_pending_tooltip_raises_nothing(self):
        self.button.event_generate("<Enter>")
        self.button.destroy()

        self.wait(120)  # the cancelled timer must not fire on a destroyed widget


    def test_works_on_a_themed_button_that_has_no_font_option(self):
        themed = ttk.Button(self.root, text="themed")
        themed.pack()
        Tooltip(themed, lambda: "help", delay_ms=40)
        self.root.update()

        themed.event_generate("<Enter>", x=1, y=1, rootx=300, rooty=300)
        self.wait(150)

        self.assertEqual(themed.tooltip._label.cget("text"), "help")



class StuckTooltipTest(unittest.TestCase):
    """A tooltip must not stay on the screen when the pointer is gone, whatever the reason."""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.over = True
        patcher = patch.object(Tooltip, "_pointer_over_widget", lambda tooltip: self.over)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.root.destroy)
        self.clicked = []
        self.button = ColorButton(self.root, "Start", lambda: self.clicked.append(1), ("Helvetica", 12), GREEN)
        self.button.pack()
        self.tooltip = Tooltip(self.button, lambda: "help", delay_ms=30)
        self.root.update()

    def wait(self, milliseconds):
        end = time.monotonic() + milliseconds / 1000
        while time.monotonic() < end:
            self.root.update()
            time.sleep(0.005)

    def visible(self):
        window = self.tooltip._window
        return window is not None and window.state() == "normal"

    def show(self):
        self.button.event_generate("<Enter>", x=5, y=5, rootx=300, rooty=300)
        self.wait(120)
        self.assertTrue(self.visible())

    def test_a_left_click_on_a_canvas_drawn_button_hides_the_tooltip_and_still_runs_the_button(self):
        self.show()

        self.button.event_generate("<ButtonPress-1>", x=5, y=5)
        self.assertFalse(self.visible())
        self.button.event_generate("<ButtonRelease-1>", x=5, y=5)
        self.assertEqual(self.clicked, [1])

    def test_it_goes_away_when_the_pointer_left_without_a_leave_event(self):
        self.show()

        self.over = False  # e.g. a window opened over the button, or a modal window holds the grab
        self.wait(WATCH_INTERVAL_MS * 2 + 100)

        self.assertFalse(self.visible())

    def test_it_stays_while_the_pointer_is_on_the_widget(self):
        self.show()

        self.wait(WATCH_INTERVAL_MS * 3)

        self.assertTrue(self.visible())

    def test_it_does_not_appear_when_the_pointer_is_no_longer_on_the_widget(self):
        self.over = False
        self.button.event_generate("<Enter>", x=5, y=5, rootx=300, rooty=300)

        self.wait(150)

        self.assertFalse(self.visible())

    def test_it_goes_away_when_the_window_holding_the_button_is_hidden(self):
        self.show()

        self.root.withdraw()
        self.over = False  # nothing of a hidden window is under the pointer
        self.wait(WATCH_INTERVAL_MS * 2 + 100)

        self.assertFalse(self.visible())

    def test_the_pointer_coming_onto_the_tooltip_dismisses_it(self):
        self.show()

        self.tooltip._label.event_generate("<Enter>")

        self.assertFalse(self.visible())

    def test_a_click_on_the_tooltip_dismisses_it(self):
        self.show()

        self.tooltip._window.event_generate("<ButtonPress-1>")

        self.assertFalse(self.visible())

    def test_the_watch_stops_when_it_is_hidden_and_starts_again_with_the_next_tooltip(self):
        self.show()
        self.button.event_generate("<Leave>")
        self.assertIsNone(self.tooltip._watch_id)

        self.show()

        self.assertIsNotNone(self.tooltip._watch_id)

    def test_destroying_the_button_with_a_visible_tooltip_raises_nothing(self):
        self.show()

        self.button.destroy()
        self.wait(WATCH_INTERVAL_MS * 2)


class PointerOverWidgetTest(unittest.TestCase):
    """The real check, without the patch: what the pointer is on, as Tk sees it."""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.root.destroy)
        self.button = tk.Button(self.root, text="button")
        self.button.pack(padx=40, pady=40)
        self.tooltip = Tooltip(self.button, lambda: "help")
        self.root.update()

    def pointer_at(self, x, y):
        self.button.winfo_pointerxy = lambda: (x, y)

    def test_true_on_the_widget_false_beside_it(self):
        self.pointer_at(self.button.winfo_rootx() + 5, self.button.winfo_rooty() + 5)
        self.assertTrue(self.tooltip._pointer_over_widget())

        self.pointer_at(self.button.winfo_rootx() - 30, self.button.winfo_rooty() - 30)
        self.assertFalse(self.tooltip._pointer_over_widget())

    def test_false_when_another_window_of_the_application_is_over_the_widget(self):
        x, y = self.button.winfo_rootx() + 5, self.button.winfo_rooty() + 5
        cover = tk.Toplevel(self.root)
        cover.geometry(f"200x100+{x - 20}+{y - 20}")
        tk.Label(cover, text="covering").pack(expand=True, fill="both")
        cover.update()
        self.root.update()
        self.pointer_at(x, y)

        self.assertFalse(self.tooltip._pointer_over_widget())

    def test_false_when_the_widget_is_destroyed(self):
        self.pointer_at(self.button.winfo_rootx() + 5, self.button.winfo_rooty() + 5)
        self.button.destroy()

        self.assertFalse(self.tooltip._pointer_over_widget())


if __name__ == "__main__":
    unittest.main()
