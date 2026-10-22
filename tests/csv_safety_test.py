"""The CSV files are opened in a spreadsheet by people, and what they contain comes from the account: the notes and
names of players, labels and so on."""
import csv
import os
import tempfile
import unittest

from processor import csv_generator
from processor.csv_generator import CSVTask, safe_cell
from settings_and_log_window_test import WindowCase


class SafeCellTest(unittest.TestCase):
    def test_text_a_spreadsheet_would_run_gets_a_text_mark(self):
        for text in ("=1+1", "=cmd|' /C calc'!A0", "@SUM(A1)", "+cmd|x", "-2+3+cmd", "\tx", "\rx", "-abc", "+ahoj"):
            with self.subTest(text=text):
                self.assertEqual(safe_cell(text), "'" + text)

    def test_numbers_phone_numbers_and_ordinary_text_stay_as_they_are(self):
        for value in ("+420 123 456 789", "-5", "-1.5", "+1 (555) 123-4567", "Lobby", "a=b", "", "1+1", None, 7, 0.5):
            with self.subTest(value=value):
                self.assertEqual(safe_cell(value), value)


class CsvFileTest(unittest.TestCase):
    def write(self, rows, headers=("A", "B")):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "x.csv")
            CSVTask._write_to_csv(path, rows, list(headers))
            with open(path, "rb") as file:
                raw = file.read()
            with open(path, encoding="utf-8-sig", newline="") as file:
                return raw, list(csv.reader(file, delimiter=";"))

    def test_the_file_starts_with_the_mark_that_makes_excel_read_the_accents(self):
        raw, rows = self.write([["Příliš žluťoučký kůň", "Ž"]])

        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(rows[1], ["Příliš žluťoučký kůň", "Ž"])

    def test_a_formula_in_a_note_is_written_as_text_the_headers_are_left_alone(self):
        _, rows = self.write([["PC1", "=HYPERLINK(\"http://evil\")"], ["PC2", "+420 777 000 111"]], ("=A", "B"))

        self.assertEqual(rows[0], ["=A", "B"])
        self.assertEqual(rows[1][1], "'=HYPERLINK(\"http://evil\")")
        self.assertEqual(rows[2][1], "+420 777 000 111")


def concrete_tasks():
    found, pending = [], [CSVTask]
    while pending:
        for subclass in pending.pop().__subclasses__():
            pending.append(subclass)
            if not getattr(subclass.get_headers, "__isabstractmethod__", False):
                found.append(subclass)
    return found


class AccountWithNothingTest(unittest.TestCase):
    """An account with no groups, labels or players has nothing to write, which used to end in max() of nothing."""

    def test_there_are_tasks_to_check(self):
        self.assertGreaterEqual(len(concrete_tasks()), 10)

    def test_every_task_makes_headers_for_no_data(self):
        for task_class in concrete_tasks():
            with self.subTest(task=task_class.__name__):
                task = task_class(None, url="https://x", login="l", password="p")

                task.get_headers([])  # raised ValueError: max() arg is an empty sequence


class FileNameTest(WindowCase):
    def test_the_name_of_the_account_cannot_leave_the_folder_or_break_the_name(self):
        for account, expected in (("Lagardère LVH", "Lagardère_LVH-"), ("../../etc/passwd", "etc_passwd-"),
                                  ('a:b*c?"d<e>|f', "a_b_c_d_e_f-"), ("", "account-"), ("...", "account-")):
            with self.subTest(account=account):
                self.app.option_choose_administration.set(account)

                path = self.app.csv_file_path("players")

                self.assertEqual(os.path.dirname(path), os.path.dirname(self.app.csv_file_path("x")))
                self.assertTrue(os.path.basename(path).startswith(expected), path)
                self.assertTrue(path.endswith(".csv"))


if __name__ == "__main__":
    unittest.main()
