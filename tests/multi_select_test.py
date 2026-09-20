import time
import tkinter as tk
import unittest
from tkinter import ttk
from unittest.mock import patch

from gui_app.multi_select import MAX_POPUP_HEIGHT, MIN_POPUP_WIDTH, MIN_TEXT_AREA, MultiSelectCombo

OPTIONS = [("(bez skupiny)", ""), ("Kancelář", "Kancelář"), ("Obchod Praha", "Obchod Praha"),
           ("Obchod Přerov", "Obchod Přerov"), ("Sklad", "Sklad")]


class MultiSelectTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.root.destroy)
        self.window = tk.Toplevel(self.root)
        self.window.geometry("700x500+40+40")
        self.changes = 0
        self.combo = MultiSelectCombo(self.window, self.window, font=("Helvetica", 12), width=11,
                                      on_change=self.changed)
        self.combo.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.elsewhere = tk.Frame(self.window, width=200, height=200)
        self.elsewhere.grid(row=1, column=0, sticky="w")
        self.combo.set_options(OPTIONS)
        self.window.update()

    def changed(self):
        self.changes += 1

    def arrow_click(self):
        """A click on the arrow part of the combo box, at its right edge."""
        entry = self.combo.entry
        entry.event_generate("<ButtonPress-1>", x=entry.winfo_width() - 6, y=entry.winfo_height() // 2)

    def visible_labels(self):
        return [button.cget("text") for button in self.combo._buttons.values() if button.winfo_manager()]

    def pump(self, seconds=0.05):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.root.update()
            time.sleep(0.005)

    def bound_scripts(self):
        return {sequence: self.window.bind(sequence).count("if {") + self.window.bind(sequence).count("\n")
                for sequence in ("<ButtonPress>", "<Escape>", "<Configure>", "<Unmap>")}

    # ---- what the user chose

    def test_nothing_is_chosen_at_first(self):
        self.assertEqual((self.combo.text(), self.combo.checked()), ("", frozenset()))
        self.assertFalse(self.combo._badge.winfo_ismapped())

    def test_typing_is_a_change(self):
        self.combo.text_var.set("obch")

        self.assertEqual(self.combo.text(), "obch")
        self.assertEqual(self.changes, 1)

    def test_ticking_values_is_a_change_shown_as_a_count(self):
        self.combo._vars["Sklad"].set(True)
        self.combo._vars["Kancelář"].set(True)
        self.window.update()

        self.assertEqual(self.combo.checked(), frozenset({"Sklad", "Kancelář"}))
        self.assertEqual(self.changes, 2)
        self.assertEqual(self.combo._badge.cget("text"), "2✓")
        self.assertTrue(self.combo._badge.winfo_ismapped())
        self.combo._vars["Sklad"].set(False)
        self.assertEqual(self.combo._badge.cget("text"), "1✓")
        self.combo._vars["Kancelář"].set(False)
        self.window.update()
        self.assertFalse(self.combo._badge.winfo_ismapped())

    def test_the_empty_value_can_be_ticked_like_any_other(self):
        self.combo._vars[""].set(True)

        self.assertEqual(self.combo.checked(), frozenset({""}))

    def test_clear_removes_the_text_and_every_tick(self):
        self.combo.text_var.set("x")
        self.combo._vars["Sklad"].set(True)

        self.combo.clear()
        self.window.update()

        self.assertEqual((self.combo.text(), self.combo.checked()), ("", frozenset()))
        self.assertFalse(self.combo._badge.winfo_ismapped())

    def test_new_options_keep_the_ticks_of_the_values_that_are_still_offered(self):
        self.combo._vars["Sklad"].set(True)
        self.combo._vars["Kancelář"].set(True)

        self.combo.set_options([("Sklad", "Sklad"), ("Nový", "Nový")])

        self.assertEqual(self.combo.checked(), frozenset({"Sklad"}))
        self.assertEqual(self.combo._badge.cget("text"), "1✓")

    # ---- the list

    def test_the_arrow_opens_and_closes_the_list_inside_the_window(self):
        self.arrow_click()
        self.window.update()

        self.assertTrue(self.combo.is_open)
        popup = self.combo._popup
        self.assertEqual(popup.winfo_toplevel(), self.window)  # a part of the window, not a window of its own
        self.assertGreaterEqual(popup.winfo_rootx(), self.window.winfo_rootx())
        self.assertLessEqual(popup.winfo_rootx() + popup.winfo_width(), self.window.winfo_rootx() + self.window.winfo_width())
        self.assertEqual(popup.winfo_rooty(), self.combo.winfo_rooty() + self.combo.winfo_height())
        self.assertGreaterEqual(popup.winfo_width(), MIN_POPUP_WIDTH)
        self.assertEqual(self.visible_labels(), [label for label, _ in OPTIONS])
        self.arrow_click()
        self.assertFalse(self.combo.is_open)

    def test_a_click_on_the_text_part_does_not_open_the_list_but_the_arrow_part_does(self):
        entry = self.combo.entry

        entry.event_generate("<ButtonPress-1>", x=10, y=entry.winfo_height() // 2)
        self.assertFalse(self.combo.is_open)
        entry.event_generate("<ButtonPress-1>", x=entry.winfo_width() - 4, y=entry.winfo_height() // 2)
        self.assertTrue(self.combo.is_open)

    def test_the_windows_name_of_the_arrow_element_works_too(self):
        entry = self.combo.entry
        with patch.object(ttk.Combobox, "identify", return_value="Combobox.downarrow"):
            entry.event_generate("<ButtonPress-1>", x=entry.winfo_width() - 6, y=8)
            self.assertTrue(self.combo.is_open)
            self.combo.close()
            entry.event_generate("<ButtonPress-1>", x=10, y=8)  # the text part is never the arrow
            self.assertFalse(self.combo.is_open)

    def test_the_border_of_the_field_is_not_the_arrow(self):
        entry = self.combo.entry

        entry.event_generate("<ButtonPress-1>", x=1, y=1)

        self.assertFalse(self.combo.is_open)

    def test_the_native_list_of_the_combo_box_is_never_posted(self):
        entry = self.combo.entry
        self.assertEqual(entry.event_generate("<ButtonPress-1>", x=entry.winfo_width() - 6, y=8), None)

        self.assertEqual(self.combo.entry.tk.call("winfo", "exists", f"{entry}.popdown"), 0)

    def test_the_down_key_opens_the_list(self):
        self.combo.entry.focus_force()
        self.window.update()

        self.combo.entry.event_generate("<Key-Down>")

        self.assertTrue(self.combo.is_open)

    def test_it_is_the_same_native_widget_as_the_other_drop_downs(self):
        self.assertIsInstance(self.combo.entry, ttk.Combobox)
        readonly = ttk.Combobox(self.window, state="readonly", width=11, font=("Helvetica", 12))
        readonly.grid(row=2, column=0)
        self.window.update()

        self.assertEqual(self.combo.entry.winfo_height(), readonly.winfo_height())
        self.assertEqual(self.combo.entry.winfo_width(), readonly.winfo_width())

    def test_the_list_is_above_the_other_widgets(self):
        self.combo.open()
        self.window.update()

        x, y = self.combo._popup.winfo_rootx() + 20, self.combo._popup.winfo_rooty() + 5
        self.assertTrue(str(self.window.winfo_containing(x, y)).startswith(str(self.combo._popup)))

    def test_the_typed_text_narrows_the_list_ignoring_case_and_diacritics(self):
        self.combo.open()

        self.combo.text_var.set("OBCHOD pr")
        self.window.update()
        self.assertEqual(self.visible_labels(), ["Obchod Praha", "Obchod Přerov"])
        self.combo.text_var.set("kancelar")
        self.window.update()
        self.assertEqual(self.visible_labels(), ["Kancelář"])
        self.combo.text_var.set("")
        self.window.update()
        self.assertEqual(len(self.visible_labels()), 5)

    def test_the_narrowed_list_is_shorter(self):
        self.combo.open()
        self.window.update()
        full = self.combo._popup.winfo_height()

        self.combo.text_var.set("sklad")
        self.window.update()

        self.assertLess(self.combo._popup.winfo_height(), full)

    def test_a_click_elsewhere_closes_the_list(self):
        self.combo.open()

        self.elsewhere.event_generate("<ButtonPress-1>", x=5, y=5)

        self.assertFalse(self.combo.is_open)

    def test_a_click_in_the_list_or_on_the_field_does_not_close_it(self):
        self.combo.open()
        self.window.update()

        next(iter(self.combo._buttons.values())).event_generate("<ButtonPress-1>", x=2, y=2)
        self.combo._canvas.event_generate("<ButtonPress-1>", x=2, y=2)
        self.combo.entry.event_generate("<ButtonPress-1>", x=2, y=2)

        self.assertTrue(self.combo.is_open)

    def test_escape_closes_the_list(self):
        self.combo.entry.focus_force()  # the key goes to the field the user is typing in, and reaches the window
        self.window.update()
        self.combo.open()

        self.combo.entry.event_generate("<Escape>")

        self.assertFalse(self.combo.is_open)

    def test_moving_or_resizing_the_window_closes_the_list(self):
        self.combo.open()
        self.window.geometry("640x480+60+60")
        self.pump(0.15)

        self.assertFalse(self.combo.is_open)

    def test_hiding_the_window_closes_the_list(self):
        self.combo.open()

        self.window.withdraw()
        self.pump(0.1)

        self.assertFalse(self.combo.is_open)

    def test_opening_and_closing_again_and_again_does_not_pile_up_bindings(self):
        before = {sequence: len(self.window.bind(sequence).splitlines()) for sequence in ("<ButtonPress>", "<Escape>",
                                                                                          "<Configure>", "<Unmap>")}
        for _ in range(8):
            self.combo.open()
            self.combo.close()

        after = {sequence: len(self.window.bind(sequence).splitlines()) for sequence in before}
        self.assertEqual(after, before)

    def test_new_options_close_the_list(self):
        self.combo.open()

        self.combo.set_options(OPTIONS[:2])

        self.assertFalse(self.combo.is_open)

    def test_destroying_the_window_with_the_list_open_raises_nothing(self):
        self.combo.open()

        self.window.destroy()
        self.pump(0.1)

    def test_a_long_list_is_cut_to_a_height_and_scrolls(self):
        self.combo.set_options([(f"Hodnota {index:03d}", f"v{index}") for index in range(200)])
        self.combo.open()
        self.window.update()

        self.assertLessEqual(self.combo._popup.winfo_height(), MAX_POPUP_HEIGHT + 4)
        self.assertLess(self.combo._canvas.yview()[1], 1)
        self.combo._canvas.event_generate("<MouseWheel>", delta=-3)
        self.window.update()
        self.assertGreater(self.combo._canvas.yview()[0], 0)

    def test_the_wheel_over_the_list_does_not_reach_the_window(self):
        reached = []
        self.window.bind("<MouseWheel>", lambda event: reached.append(1))
        self.combo.set_options([(f"Hodnota {index:03d}", f"v{index}") for index in range(200)])
        self.combo.open()
        self.window.update()

        self.combo._canvas.event_generate("<MouseWheel>", delta=-3)

        self.assertEqual(reached, [])

    def test_the_list_stays_inside_the_window_near_its_right_edge(self):
        self.combo.grid_configure(padx=(560, 0))
        self.window.update()

        self.combo.open()
        self.window.update()

        popup = self.combo._popup
        self.assertLessEqual(popup.winfo_rootx() + popup.winfo_width(), self.window.winfo_rootx() + self.window.winfo_width())
        self.assertGreaterEqual(popup.winfo_rootx(), self.window.winfo_rootx())

    def test_the_ticks_made_in_the_list_count(self):
        self.combo.open()
        self.window.update()

        self.combo._buttons["Sklad"].invoke()
        self.combo._buttons["Kancelář"].invoke()

        self.assertEqual(self.combo.checked(), frozenset({"Sklad", "Kancelář"}))
        self.combo._buttons["Sklad"].invoke()
        self.assertEqual(self.combo.checked(), frozenset({"Kancelář"}))


class MultiSelectSizeTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.root.destroy)
        self.combo = MultiSelectCombo(self.root, self.root, font=("Helvetica", 12), width=1)
        self.combo.set_options(OPTIONS)
        self.root.update()

    def test_it_asks_for_next_to_no_width_and_takes_the_width_it_is_given(self):
        self.combo.grid(row=0, column=0, sticky="ew")
        self.root.grid_columnconfigure(0, minsize=300)
        self.root.update()

        self.assertLess(self.combo.winfo_reqwidth(), 80)
        self.assertEqual(self.combo.winfo_width(), 300)
        self.assertEqual(self.combo.entry.winfo_width(), 300)  # the combo box fills it (no ticks: no count beside it)

    def test_the_count_of_ticks_takes_its_room_from_the_combo_box_not_from_the_column(self):
        self.combo.grid(row=0, column=0, sticky="ew")
        self.root.grid_columnconfigure(0, minsize=200)
        self.root.update()
        before = self.combo.entry.winfo_width()

        self.combo._vars["Sklad"].set(True)
        self.root.update()

        self.assertEqual(self.combo.winfo_width(), 200)
        self.assertLess(self.combo.entry.winfo_width(), before)
        self.assertTrue(self.combo._badge.winfo_ismapped())

    def test_the_minimum_width_leaves_room_for_the_combo_box_to_type_and_for_the_count(self):
        minimum = self.combo.minimum_width()

        self.assertGreaterEqual(minimum, self.combo.entry.winfo_reqwidth() + MIN_TEXT_AREA)
        self.combo.grid(row=0, column=0, sticky="ew")
        self.root.grid_columnconfigure(0, minsize=minimum)
        self.combo._vars["Sklad"].set(True)
        self.root.update()

        self.assertEqual(self.combo.winfo_width(), minimum)  # with the count shown, still exactly the minimum
        self.assertGreaterEqual(self.combo.entry.winfo_width(), self.combo.entry.winfo_reqwidth() + MIN_TEXT_AREA - 2)


if __name__ == "__main__":
    unittest.main()
