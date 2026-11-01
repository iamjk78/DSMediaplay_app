"""What the log window adds around an action: how many lines were read and how many empty ones are skipped, a backup of what
the action changes (the action does not start without it), the warnings and errors once more at the end under "Zjištěné
chyby:" in red, and a click on such a line, which opens the input at the line the error names."""
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from gui_app import gui
from gui_app.input_box import InputTextBox
from gui_app.log_box import LoggingTextBox
from main_buttons_test import MainWindowCase
from processor.csv_generator import CSVTaskFactory
from processor.input_processing import DeploySelectedGroupsProcessor, GroupRenameProcessor, ProcessorFactory
from util import backup
from util.actions import NO_INPUT_PLACEHOLDER


class BackupMapTest(unittest.TestCase):
    def test_every_backed_up_action_is_a_processor_and_its_files_are_csv_exports_that_exist(self):
        for processor_type, tasks in backup.BACKUPS.items():
            with self.subTest(processor_type=processor_type):
                ProcessorFactory.create_processor(processor_type, MagicMock(), "https://x", "u", "p", MagicMock())
                self.assertTrue(tasks)
                for task in tasks:
                    CSVTaskFactory.create_task(task, None, url="https://x", login="u", password="p")

    def test_what_only_adds_renames_or_hands_out_needs_no_backup(self):
        for processor_type in ("create_group", "create_playlist", "create_label", "create_location", "add_detailed_playlist",
                               "group_rename", "player_rename", "location_rename", "playlist_rename", "player_snapshot",
                               "deploy_all_players", "deploy_selected_groups"):
            with self.subTest(processor_type=processor_type):
                self.assertEqual(backup.csv_tasks_for(processor_type), ())

    def test_what_overwrites_or_deletes_is_backed_up(self):
        for processor_type in ("detailed_playlist", "group_settings", "player_group", "remove_all_unused_groups",
                               "remove_unused_playlists", "remove_playlists", "asset_validity"):
            with self.subTest(processor_type=processor_type):
                self.assertTrue(backup.csv_tasks_for(processor_type))


class RepeatedRowsTest(unittest.TestCase):
    """A line that is in the input more than once is read once; the processor counts the ones it left out."""

    @staticmethod
    def processor(processor_class=GroupRenameProcessor):
        return processor_class(MagicMock(), url="http://x", login="u", password="p", lang=MagicMock())

    def test_the_repeats_are_counted_and_left_out(self):
        processor = self.processor()

        rows = processor._indexed_rows("a\tb\n\na\tb\nc\td\na\tb")

        self.assertEqual(rows, [(0, "a\tb"), (3, "c\td")])
        self.assertEqual(processor.skipped_repeated_rows, 2)

    def test_nothing_is_counted_when_there_are_no_repeats(self):
        processor = self.processor()
        processor._indexed_rows("a\nb\n\nc")

        self.assertEqual(processor.skipped_repeated_rows, 0)

    def test_an_action_that_reports_a_repeated_name_itself_counts_nothing(self):
        processor = self.processor()

        rows = processor._indexed_rows("a\na", keep_repeats=True)

        self.assertEqual(len(rows), 2)
        self.assertEqual(processor.skipped_repeated_rows, 0)

    def test_reading_the_same_input_twice_does_not_count_twice(self):
        processor = self.processor()
        processor._indexed_rows("a\na")
        processor._indexed_rows("a\na")

        self.assertEqual(processor.skipped_repeated_rows, 1)

    def test_a_row_made_of_the_same_cells_is_a_repeat_even_when_the_line_differs_in_blanks(self):
        processor = self.processor()

        processor._indexed_rows("g1 \ng1", str.strip)

        self.assertEqual(processor.skipped_repeated_rows, 1)

    def test_the_groups_to_deploy_are_counted_too(self):
        processor = self.processor(DeploySelectedGroupsProcessor)
        server = MagicMock()
        server.get_group_names.return_value = ["g1", "g2"]
        with patch.object(processor, "_try_server_login", return_value=server):
            processor.load("g1\ng1\n g1\ng2")

        self.assertEqual(sorted(processor.data["groups"]), ["g1", "g2"])
        self.assertEqual(processor.skipped_repeated_rows, 2)


class LogCase(MainWindowCase):
    def run_box(self, processor=None, data="", processor_type="group_rename", backup_path=None, factory=None):
        """
        The log window with `processor` (or what `factory` makes of the logger of the window, as the application's own
        factory does) running in it, the way the application does it: in a thread, Tk in the main loop.
        """
        create = {"side_effect": factory} if factory else {"return_value": processor}
        with patch("gui_app.log_box.ThreadManager.start_thread"), \
                patch("gui_app.log_box.ProcessorFactory.create_processor", **create):
            box = LoggingTextBox(processor_type, url="http://example.com", login="u", password="p", data=data,
                                 master=self.app, backup_path=backup_path)
            self.addCleanup(lambda: box.winfo_exists() and box.destroy())
            self.app.update()
            worker = threading.Thread(target=box.run_input_processing, daemon=True)
            deadline = time.monotonic() + 10

            def stop_when_done():
                if worker.is_alive() and time.monotonic() < deadline:
                    self.app.after(20, stop_when_done)
                else:
                    self.app.after(100, self.app.quit)  # the last lines of the log are added by the main loop

            worker.start()
            self.app.after(20, stop_when_done)
            self.app.mainloop()
            self.assertFalse(worker.is_alive(), "the worker is stuck")
        return box

    @staticmethod
    def quiet_processor():
        processor = MagicMock()
        processor.confirmation.return_value = None
        processor.run.return_value = iter([])
        return processor

    @staticmethod
    def text(box):
        return box.log_text.get("1.0", tk.END)

    def rename_factory(self, names=("g1", "g2")):
        """A real rename processor on a server that has these groups; `self.server` is the server."""
        self.server = MagicMock()
        self.server.get_group_names.return_value = list(names)
        self.server.__enter__.return_value = self.server

        def make(processor_type, logger, url, login, password, lang, **kwargs):
            processor = GroupRenameProcessor(logger, url=url, login=login, password=password, lang=lang)
            patcher = patch.object(processor, "_try_server_login", return_value=self.server)
            patcher.start()
            self.addCleanup(patcher.stop)
            return processor
        return make

    def tagged(self, box, tag):
        ranges = box.log_text.tag_ranges(tag)
        return [box.log_text.get(start, end) for start, end in zip(ranges[::2], ranges[1::2])]


class InputSummaryTest(LogCase):
    def test_it_says_how_many_lines_were_read_and_how_many_empty_ones_between_them_are_skipped(self):
        box = self.run_box(self.quiet_processor(), data="\n\na\tb\n\n\nc\td\n\n")

        self.assertIn("Načteno řádků: 2", self.text(box))
        self.assertIn("Prázdné řádky, které se přeskočí: 2", self.text(box))

    def test_it_does_not_mention_empty_lines_when_there_are_none_between_the_lines(self):
        box = self.run_box(self.quiet_processor(), data="a\tb\nc\td\n\n")

        self.assertIn("Načteno řádků: 2", self.text(box))
        self.assertNotIn("Prázdné řádky", self.text(box))

    def test_a_line_of_blanks_counts_as_empty(self):
        box = self.run_box(self.quiet_processor(), data="a\tb\n   \t \nc\td")

        self.assertIn("Prázdné řádky, které se přeskočí: 1", self.text(box))

    def test_an_action_without_input_says_nothing_about_lines(self):
        for data in (NO_INPUT_PLACEHOLDER, "", None):
            with self.subTest(data=data):
                box = self.run_box(self.quiet_processor(), data=data)
                self.assertNotIn("Načteno řádků", self.text(box))

    def test_the_repeated_lines_that_were_left_out_are_counted(self):
        processor = self.quiet_processor()
        processor.skipped_repeated_rows = 2

        box = self.run_box(processor, data="a\tb\na\tb\na\tb")

        self.assertIn("Přeskočeno opakujících se řádků: 2", self.text(box))

    def test_nothing_is_said_about_repeats_when_there_were_none(self):
        processor = self.quiet_processor()
        processor.skipped_repeated_rows = 0

        box = self.run_box(processor, data="a\tb")

        self.assertNotIn("opakujících", self.text(box))

    def test_the_repeats_are_counted_with_a_real_processor_even_when_the_input_has_an_error(self):
        box = self.run_box(factory=self.rename_factory(), data="g1\tbad name\ng1\tbad name\ng2\tfine")

        self.assertIn("Přeskočeno opakujících se řádků: 1", self.text(box))
        self.assertIn("Řádek 1: Nevalidní jméno skupiny", self.text(box))
        self.server.rename_group.assert_not_called()

    def test_an_error_in_a_line_is_reported_and_nothing_runs(self):
        box = self.run_box(factory=self.rename_factory(), data="g1\tbad name\n\ng2\tfine")

        self.assertIn("Načteno řádků: 2", self.text(box))
        self.assertIn("Prázdné řádky, které se přeskočí: 1", self.text(box))
        self.assertIn("Řádek 1: Nevalidní jméno skupiny", self.text(box))
        self.server.rename_group.assert_not_called()


class ProblemsAtTheEndTest(LogCase):
    DATA = "g1\tbad name\nnobody\tx\ng2\tfine"

    def test_the_errors_are_listed_once_more_at_the_end_under_the_heading_in_red(self):
        box = self.run_box(factory=self.rename_factory(), data=self.DATA)

        text = self.text(box)
        heading = text.index("Zjištěné chyby:")
        self.assertEqual(text.count("Zjištěné chyby:"), 1)
        first, second = text.index("Řádek 1: Nevalidní jméno skupiny"), text.rindex("Řádek 1: Nevalidní jméno skupiny")
        self.assertLess(first, heading)
        self.assertGreater(second, heading)
        self.assertIn("Řádek 2: Chyba při rozpoznávání jména nobody", text[heading:])
        red = "".join(self.tagged(box, "error"))
        self.assertIn("Zjištěné chyby:", red)
        self.assertGreater(red.count("Řádek 1: Nevalidní jméno skupiny"), 1)

    def test_nothing_is_added_when_there_was_no_problem(self):
        box = self.run_box(self.quiet_processor(), data="a\tb")

        self.assertNotIn("Zjištěné chyby", self.text(box))

    def test_the_lines_that_name_a_line_can_be_clicked_and_the_heading_cannot(self):
        box = self.run_box(factory=self.rename_factory(), data=self.DATA)

        clickable = self.tagged(box, "problem")
        self.assertTrue(clickable)
        self.assertTrue(all("Řádek" in line for line in clickable), clickable)
        self.assertNotIn("Zjištěné chyby:", "".join(clickable))

    def test_a_click_opens_the_input_at_the_line_of_the_error(self):
        box = self.run_box(factory=self.rename_factory(), data=self.DATA)
        start = box.log_text.tag_ranges("problem")[0]
        x, y, _, _ = box.log_text.bbox(start)

        with patch.object(self.app, "edit_input_at") as edit:
            box._open_input_at_clicked_line(MagicMock(x=x + 3, y=y + 3))

        edit.assert_called_once_with(1)

    def test_a_click_on_a_line_with_no_number_does_nothing(self):
        box = self.run_box(factory=self.rename_factory(), data=self.DATA)
        x, y, _, _ = box.log_text.bbox(box.log_text.search("Zjištěné chyby:", "1.0"))

        with patch.object(self.app, "edit_input_at") as edit:
            box._open_input_at_clicked_line(MagicMock(x=x + 3, y=y + 3))

        edit.assert_not_called()

    def test_a_click_while_the_action_still_runs_does_nothing(self):
        box = self.run_box(factory=self.rename_factory(), data=self.DATA)
        start = box.log_text.tag_ranges("problem")[0]
        x, y, _, _ = box.log_text.bbox(start)
        box.thread_manager.is_running = True

        with patch.object(self.app, "edit_input_at") as edit:
            box._open_input_at_clicked_line(MagicMock(x=x + 3, y=y + 3))

        edit.assert_not_called()

    def test_the_line_numbers_are_found_in_both_languages(self):
        from gui_app.log_box import LINE_NUMBER
        for text, number in (("2026 - Řádek 12: chyba", "12"), ("Line 7: error", "7"), ("Line 3 incorrect line format", "3")):
            self.assertEqual(LINE_NUMBER.search(text).group(1), number)


class BackupTest(LogCase):
    def backing_up(self, processor_type, processor=None, fail=False):
        task = MagicMock()
        calls = []
        task.generate_csv.side_effect = (RuntimeError("boom") if fail else lambda path: calls.append(("backup", path)))
        processor = processor or self.quiet_processor()
        processor.run.side_effect = lambda: iter(calls.append(("run", None)) or [])
        patcher = patch("gui_app.log_box.CSVTaskFactory.create_task", return_value=task)
        created = patcher.start()
        self.addCleanup(patcher.stop)
        box = self.run_box(processor, data="x", processor_type=processor_type,
                           backup_path=lambda kind: f"/downloads/Demo-backup-{kind}.csv")
        return box, processor, created, calls

    def test_the_backup_is_saved_before_the_action_runs_and_the_log_says_where(self):
        box, processor, created, calls = self.backing_up("group_settings")

        self.assertEqual(calls, [("backup", "/downloads/Demo-backup-group_settings.csv"), ("run", None)])
        self.assertIn("Záloha uložena: /downloads/Demo-backup-group_settings.csv", self.text(box))
        self.assertEqual(created.call_args.kwargs["task_type"], "group_settings")

    def test_an_action_that_changes_more_than_one_kind_of_data_saves_each(self):
        _, _, created, calls = self.backing_up("remove_all_unused_groups")

        self.assertEqual([call.kwargs["task_type"] for call in created.call_args_list],
                         ["group_settings", "detailed_groups_with_playlists"])
        self.assertEqual([kind for kind, _ in calls], ["backup", "backup", "run"])

    def test_without_a_backup_the_action_does_not_start(self):
        box, processor, _, calls = self.backing_up("group_settings", fail=True)

        processor.run.assert_not_called()
        self.assertEqual(calls, [])
        self.assertIn("Zálohu se nepodařilo uložit", self.text(box))
        self.assertIn("Akce nebyla spuštěna", self.text(box))

    def test_an_action_that_only_adds_is_not_backed_up(self):
        _, _, created, calls = self.backing_up("create_group")

        created.assert_not_called()
        self.assertEqual(calls, [("run", None)])

    def test_a_refused_question_saves_nothing(self):
        processor = self.quiet_processor()
        processor.confirmation.return_value = MagicMock(title="t", text="x")
        with patch("gui_app.log_box.messagebox.askyesno", return_value=False):
            _, _, created, _ = self.backing_up("remove_all_unused_groups", processor)

        created.assert_not_called()
        processor.run.assert_not_called()

    def test_an_input_with_an_error_saves_nothing(self):
        with patch("gui_app.log_box.CSVTaskFactory.create_task") as created:
            self.run_box(factory=self.rename_factory(), data="g1\tbad name", processor_type="group_settings",
                         backup_path=lambda kind: "/x.csv")

        created.assert_not_called()

    def test_without_a_place_for_the_backup_the_action_just_runs(self):
        processor = self.quiet_processor()
        with patch("gui_app.log_box.CSVTaskFactory.create_task") as created:
            self.run_box(processor, data="x", processor_type="group_settings", backup_path=None)

        created.assert_not_called()
        processor.run.assert_called_once()


class BackupFileNameTest(MainWindowCase):
    def test_the_backup_goes_to_the_downloads_folder_named_after_the_account_the_kind_of_data_and_the_time(self):
        with patch("gui_app.gui.get_download_path", return_value="/downloads"):
            path = self.app.csv_file_path("group_settings", "backup", "My Account")

        self.assertRegex(path, r"^/downloads/My_Account-backup-group_settings-\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.csv$")

    def test_an_ordinary_csv_file_keeps_its_name(self):
        self.app.option_choose_administration.set("Demo")
        with patch("gui_app.gui.get_download_path", return_value="/downloads"):
            path = self.app.csv_file_path("group_settings")

        self.assertRegex(path, r"^/downloads/Demo-group_settings-\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.csv$")

    def test_the_log_window_gets_the_place_for_the_backup_with_the_account_read_in_the_main_thread(self):
        self.app.option_choose_administration.set("Demo")
        with patch("gui_app.gui.LoggingTextBoxFactory.create_log_box") as factory, patch.object(self.app, "wait_window"):
            self.app.open_action_log_box("group_settings", "https://x", "jane", "pw", "x")
        self.app.option_choose_administration.set("Other")  # chosen later: the backup is still the account of the Start

        with patch("gui_app.gui.get_download_path", return_value="/downloads"):
            path = factory.call_args.kwargs["backup_path"]("group_settings")

        self.assertIn("/downloads/Demo-backup-group_settings-", path)


class InputWindowAtLineTest(MainWindowCase):
    def open_input(self, text, line):
        window = InputTextBox(self.app, lambda data: None, text=text, line=line)
        self.addCleanup(lambda: window.winfo_exists() and window.destroy())
        return window

    def test_the_text_of_the_last_start_is_there_and_the_line_of_the_error_is_marked(self):
        window = self.open_input("first\nsecond\nthird", 2)

        self.assertEqual(window.details_text.get("1.0", "end-1c"), "first\nsecond\nthird\n")
        marked = window.details_text.tag_ranges("problem_line")
        self.assertEqual(window.details_text.get(marked[0], marked[1]).strip(), "second")
        self.assertEqual(window.details_text.index("insert"), "2.0")

    def test_a_line_that_is_not_there_marks_nothing(self):
        window = self.open_input("first\nsecond", 9)

        self.assertFalse(window.details_text.tag_ranges("problem_line"))

    def test_without_a_text_and_a_line_it_is_empty_as_before(self):
        window = self.open_input("", None)

        self.assertEqual(window.details_text.get("1.0", "end-1c"), "")
        self.assertFalse(window.details_text.tag_ranges("problem_line"))

    def test_the_main_window_opens_it_with_the_input_of_the_last_start(self):
        self.app._text_box_data = "a\nb"
        with patch("gui_app.gui.InputTextBox") as window, patch.object(self.app, "wait_window"):
            self.app.edit_input_at(2)

        self.assertEqual((window.call_args.kwargs["text"], window.call_args.kwargs["line"]), ("a\nb", 2))

    def test_the_corrected_input_replaces_the_one_of_the_last_start(self):
        self.app._text_box_data = "a\nb"
        self.app.option_choose_action.set("")

        self.app.save_data_from_text_box("a\nfixed\n")

        self.assertEqual(self.app._text_box_data, "a\nfixed\n")


if __name__ == "__main__":
    unittest.main()
