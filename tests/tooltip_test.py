import time
import tkinter as tk
from tkinter import ttk
import unittest

from unittest.mock import patch

from gui_app.color_button import GREEN, ColorButton
from gui_app.tooltip import (GAP_LEFT_OF_POINTER, GAP_RIGHT_OF_POINTER, IGNORE_ACTIVATE_AFTER_SHOW_MS,
                             MAX_VISIBLE_MS, TOOLTIP_DELAY_MS, WATCH_INTERVAL_MS, Tooltip, hide_if_shown)


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

    def test_default_delay_is_one_second(self):
        self.assertEqual(TOOLTIP_DELAY_MS, 1000)
        self.assertEqual(Tooltip(self.button, lambda: "x")._delay_ms, 1000)

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

    def test_hide_if_shown_closes_a_visible_tooltip(self):
        self.button.event_generate("<Enter>")
        self.wait(120)
        self.assertTrue(self.visible())

        hide_if_shown(self.button)

        self.assertFalse(self.visible())

    def test_hide_if_shown_does_nothing_to_a_widget_without_a_tooltip(self):
        plain = tk.Button(self.root, text="plain")  # never wrapped in Tooltip(): no .tooltip attribute at all

        hide_if_shown(plain)  # must not raise

    def test_hide_if_shown_on_one_that_is_not_showing_does_nothing(self):
        hide_if_shown(self.button)  # never entered: nothing to hide, must not raise

        self.assertFalse(self.visible())

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

    def test_it_goes_away_when_the_application_becomes_active_again(self):
        """
        E.g. "Help" opens the browser and takes the active application away from this one: the pointer does not
        move at all, so the pointer check (patched here to always say "still over it", as it would in that case
        too) never notices; when the user comes back, <Activate> fires on the window and closes it at once.
        """
        self.show()
        self.wait(IGNORE_ACTIVATE_AFTER_SHOW_MS + 30)  # past its own, self-caused <Activate> (see the next test)

        self.root.event_generate("<Activate>")

        self.assertFalse(self.visible())

    def test_showing_it_does_not_close_it_through_its_own_activate(self):
        """
        Deiconifying the tooltip's little window is itself measured to fire one or more spurious <Activate> events
        on the main window right away (worse still with several tooltips on the same window, each of them bound to
        it): none of those may be mistaken for the user coming back from elsewhere and close the tooltip they belong
        to. A second, independent Tooltip on the same root stands in for that "several tooltips" case.
        """
        another = tk.Button(self.root, text="another")
        another.pack()
        Tooltip(another, lambda: "x", delay_ms=30)

        self.show()
        for _ in range(5):  # as many as a burst of them right after showing
            self.root.event_generate("<Activate>")
        self.root.update()

        self.assertTrue(self.visible())

    def test_it_goes_away_on_its_own_after_a_ceiling_however_it_got_stuck(self):
        with patch("gui_app.tooltip.MAX_VISIBLE_MS", 300):  # more than show()'s own 120 ms wait
            self.show()

            self.wait(300)

        self.assertFalse(self.visible())

    def test_the_ceiling_does_not_cut_a_normal_appearance_short(self):
        with patch("gui_app.tooltip.MAX_VISIBLE_MS", 100_000):
            self.show()

            self.wait(WATCH_INTERVAL_MS * 3)

        self.assertTrue(self.visible())


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


class ActivationBindingTest(unittest.TestCase):
    """A window with dozens of tooltips (the player table) must not have dozens of <Activate> bindings."""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.root.destroy)
        self.root.update()  # on Windows an <Activate> generated before the window is shown is not delivered

    def tooltips(self, count):
        buttons = [tk.Button(self.root, text=str(i)) for i in range(count)]
        for button in buttons:
            button.pack()
        return buttons, [Tooltip(button, lambda: "text") for button in buttons]

    def test_all_the_tooltips_of_a_window_share_one_binding_and_all_are_told(self):
        buttons, tooltips = self.tooltips(20)
        told = []
        with patch.object(Tooltip, "_on_activate", lambda self, event: told.append(self)):
            self.root.event_generate("<Activate>")
            self.root.update()

        self.assertEqual(self.root.bind("<Activate>").count("if {"), 1)
        self.assertEqual(set(map(id, told)), set(map(id, tooltips)))  # the system may fire an <Activate> of its own too

    def test_a_destroyed_widget_is_no_longer_told(self):
        buttons, tooltips = self.tooltips(3)
        buttons[0].destroy()
        self.root.update()
        told = []

        with patch.object(Tooltip, "_on_activate", lambda self, event: told.append(self)):
            self.root.event_generate("<Activate>")
            self.root.update()

        self.assertEqual(set(map(id, told)), set(map(id, tooltips[1:])))


if __name__ == "__main__":
    unittest.main()
