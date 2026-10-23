"""The texts of the table of players can be selected with the mouse and copied."""
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from gui_app.copyable_cell import CopyableCell
from player_browser_test import BrowserTestCase, player


class CopyableCellTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.root.destroy)
        self.cell = CopyableCell(self.root, ("Helvetica", 12), "Copy", "Copy row", lambda: "a\tb\tc")
        self.cell.pack()
        self.cell.configure(text="Lobby Praha 001")
        self.root.update()

    def drag(self, start, end):
        self.cell.event_generate("<Button-1>", x=start, y=5)
        self.cell.event_generate("<B1-Motion>", x=end, y=5)
        self.cell.event_generate("<ButtonRelease-1>", x=end, y=5)

    def test_it_takes_and_gives_its_text_like_a_label(self):
        self.assertEqual(self.cell.cget("text"), "Lobby Praha 001")
        self.assertEqual(self.cell["text"], "Lobby Praha 001")

        self.cell.configure(text="Other")

        self.assertEqual(self.cell.cget("text"), "Other")

    def test_other_options_still_go_through(self):
        self.cell.configure(foreground="red", font=("Helvetica", 18))

        self.assertEqual(str(self.cell.cget("foreground")), "red")
        self.assertEqual(self.cell.cget("text"), "Lobby Praha 001")

    def test_a_drag_selects_a_part_of_the_text_and_nothing_can_be_typed_into_it(self):
        self.drag(2, 200)
        self.assertTrue(self.cell.selection_present())

        self.assertEqual(str(self.cell.cget("state")), "readonly")  # the class bindings of an Entry change nothing then
        self.cell.event_generate("<Key>", keysym="x")
        self.cell.event_generate("<BackSpace>")

        self.assertEqual(self.cell.cget("text"), "Lobby Praha 001")
        self.assertEqual(self.cell.selected_text(), self.cell.get()[self.cell.index("sel.first"):self.cell.index("sel.last")])

    def test_what_is_selected_is_copied_and_the_whole_text_when_nothing_is(self):
        self.cell.selection_range(6, 11)
        self.cell.copy()
        self.assertEqual(self.root.clipboard_get(), "Praha")

        self.cell.selection_clear()
        self.cell.copy()
        self.assertEqual(self.root.clipboard_get(), "Lobby Praha 001")

    def test_the_usual_copy_shortcut_copies_the_selection(self):
        self.cell.focus_force()
        self.cell.selection_range(0, 5)
        self.root.clipboard_clear()

        self.cell.event_generate("<<Copy>>")

        self.assertEqual(self.root.clipboard_get(), "Lobby")

    def test_a_new_text_does_not_keep_the_selection_of_the_old_one_the_same_text_does(self):
        self.cell.selection_range(0, 5)
        self.cell.configure(text="Lobby Praha 001")
        self.assertTrue(self.cell.selection_present())

        self.cell.configure(text="Another player")

        self.assertFalse(self.cell.selection_present())

    def test_the_menu_copies_the_cell_or_the_row(self):
        with patch("gui_app.copyable_cell.tk.Menu") as menu_class:
            self.cell._show_menu(MagicMock(x_root=10, y_root=10))

        menu = menu_class.return_value
        entries = {call.kwargs["label"]: call.kwargs["command"] for call in menu.add_command.call_args_list}
        self.assertEqual(list(entries), ["Copy", "Copy row"])
        entries["Copy"]()
        self.assertEqual(self.root.clipboard_get(), "Lobby Praha 001")
        entries["Copy row"]()
        self.assertEqual(self.root.clipboard_get(), "a\tb\tc")
        menu.tk_popup.assert_called_once_with(10, 10)

    def test_without_a_row_the_menu_has_the_cell_only(self):
        cell = CopyableCell(self.root, ("Helvetica", 12), "Copy", "Copy row")
        with patch("gui_app.copyable_cell.tk.Menu") as menu_class:
            cell._show_menu(MagicMock(x_root=1, y_root=1))

        self.assertEqual(menu_class.return_value.add_command.call_count, 1)

    def test_the_other_mouse_button_opens_the_menu(self):
        windowing = self.root.tk.call("tk", "windowingsystem")
        button = "<Button-2>" if windowing == "aqua" else "<Button-3>"

        self.assertTrue(self.cell.bind(button))


class TableCopyTest(BrowserTestCase):
    def cells_of(self, browser, name):
        row = next(r for r in browser._rows if r.name == name)
        return browser.widgets_for(row)[1:]

    def test_the_cells_of_the_table_are_selectable(self):
        browser = self.open()

        for widget in self.cells_of(browser, "Lobby"):
            self.assertIsInstance(widget, CopyableCell)

    def test_the_text_of_a_field_is_copied_from_the_table(self):
        browser = self.open()
        name, status, group, *_ = self.cells_of(browser, "Lobby")

        group.copy()

        self.assertEqual(browser.clipboard_get(), group.cget("text"))
        self.assertEqual(name.cget("text"), "Lobby")

    def test_a_row_is_copied_as_the_shown_columns_separated_by_tabs(self):
        browser = self.open(hidden_columns=["note", "synced", "label", "temperature", "version"])
        row = next(r for r in browser._rows if r.name == "Lobby")
        index = browser._pool_rows.index(row)

        text = browser._row_text(index)

        self.assertEqual(text.split("\t")[0], "Lobby")
        self.assertEqual(len(text.split("\t")), 5)  # name, status, group, location and when it last reported
        self.assertEqual(text.split("\t")[2:4], ["Kancelar", "Praha"])
        self.assertNotIn("hlavní vchod", text)  # the note is hidden

    def test_a_row_with_every_column_has_one_field_for_every_column(self):
        browser = self.open()
        row = next(r for r in browser._rows if r.name == "Lobby")

        fields = browser._row_text(browser._pool_rows.index(row)).split("\t")

        self.assertEqual(len(fields), len(self.cells_of(browser, "Lobby")))
        self.assertEqual(fields[0], "Lobby")

    def test_scrolling_does_not_leave_a_selection_on_another_player(self):
        browser = self.open(players=[player(f"P{i:03d}") for i in range(300)])
        first = browser._pool[0][1]
        first.selection_range(0, 2)
        self.assertTrue(first.selection_present())

        browser._scroll_y("moveto", 1.0)
        self.app.update()

        self.assertNotEqual(first.cget("text"), "P000")
        self.assertFalse(first.selection_present())
