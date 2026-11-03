"""Lines of the table "playlists of the groups" are cut into blocks of six cells (name, dates, days, times). They used
to be cut from the wrong cell, so an empty block moved the cells of the next one to another playlist."""
import unittest
from unittest.mock import MagicMock

from processor.input_processing import (AddDetailedPlaylistProcessor, DetailedPlaylistProcessor, FormatException,
                                        PlaylistProcessor)
from destructive_actions_test import make_processor

BLOCK_1 = ["Promo", "01.01.2026", "31.12.2026", "mo,tu", "08:00", "18:00"]
BLOCK_2 = ["Night", "", "", "su", "20:00", "23:00"]
EMPTY = [""] * 6
PROMO = ("Promo", "2026-01-01T00:00:00.000Z", "2026-12-31T00:00:00.000Z", [2, 3], "08:00", "18:00")
NIGHT = ("Night", None, None, [1], "20:00", "23:00")


def line(*cells):
    return "\t".join(cells)


class ProcessorCase(unittest.TestCase):
    def setUp(self):
        self.server = MagicMock()
        self.server.get_group_names.return_value = ["G1", "G2"]
        self.server.get_playlist_names.return_value = ["Default", "Promo", "Night"]

    def load(self, processor_class, text, real_text=False, action=None):
        """
        The processor and its logger; `refused` says whether the load found something wrong (FormatException). `action`
        is the one the processor works for (the factory sets it), which the texts about a wrong line describe the columns by.
        """
        processor, logger, patcher = make_processor(processor_class, self.server, real_text=real_text)
        self.addCleanup(patcher.stop)
        processor.action_key = action
        try:
            processor.load(text)
            processor.refused = False
        except FormatException:
            processor.refused = True
        return processor, logger

    def messages(self, logger, level="error"):
        return [call.args[0] for call in getattr(logger, level).call_args_list]


class PastedPlaylistsTest(ProcessorCase):
    def test_an_empty_block_in_the_middle_does_not_move_the_cells_of_the_next_one(self):
        processor, _ = self.load(DetailedPlaylistProcessor, line("G1", "Default", *BLOCK_1, *EMPTY, *BLOCK_2))

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data, {"G1": [("Default", None, None, None, None, None), PROMO, NIGHT]})

    def test_empty_cells_at_the_end_of_the_line_are_nothing(self):
        processor, _ = self.load(DetailedPlaylistProcessor, line("G1", "Default", *BLOCK_1, *EMPTY, *EMPTY[:3]))

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data["G1"][1:], [PROMO])

    def test_a_blank_default_playlist_and_a_line_with_only_the_group_are_fine(self):
        processor, _ = self.load(DetailedPlaylistProcessor, line("G1", "", *BLOCK_1) + "\n" + "G2")

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data, {"G1": [PROMO], "G2": []})

    def test_a_line_cut_short_is_completed_with_empty_cells(self):
        for kept in range(1, 6):  # however many cells of the last block are there
            with self.subTest(cells=kept):
                processor, _ = self.load(DetailedPlaylistProcessor, line("G1", "Default", *BLOCK_1[:kept]))

                self.assertFalse(processor.refused)
                self.assertEqual(processor.data["G1"][1][0], "Promo")

    def test_times_of_a_block_without_a_playlist_are_refused_not_given_to_another_playlist(self):
        for cells in (["", "", "", "mo", "08:00", "18:00"], ["", "01.01.2026", "", "", "", ""]):
            with self.subTest(cells=cells):
                processor, logger = self.load(DetailedPlaylistProcessor, line("G1", "Default", *BLOCK_1, *cells))

                self.assertTrue(any(key.startswith("cell_error") for key in self.messages(logger)))
                self.assertTrue(processor.refused)

    def test_a_wrong_value_in_a_block_says_the_column_the_block_and_what_the_column_takes(self):
        bad_block = ["Nowhere", "32.01.2026", "31.12.2026", "xx", "8am", "25:00"]
        processor, logger = self.load(DetailedPlaylistProcessor, line("G1", "Default", *BLOCK_1, *bad_block), real_text=True,
                                      action="set_detailed_playlists_to_groups")

        errors = self.messages(logger) + self.messages(logger, "warning")
        for message in (
                "Řádek 1, sloupec 9 (název playlistu, blok playlistu 2): zadáno „Nowhere“, očekává se: název playlistu. "
                "Takové jméno v účtu není (musí odpovídat přesně: velikost písmen, diakritika, bez mezer na okrajích). "
                "Skupina „G1“.",
                "Řádek 1, sloupec 10 (platí od, blok playlistu 2): zadáno „32.01.2026“, očekává se: datum DD.MM.RRRR, "
                "např. 01.01.2026, nebo prázdné. "
                "Skupina „G1“, playlist „Nowhere“.",
                "Řádek 1, sloupec 12 (dny v týdnu, blok playlistu 2): zadáno „xx“, očekává se: kódy mo,tu,we,th,fr,sa,su "
                "(nebo čísla 1-7) oddělené čárkou, nebo prázdné. "
                "Skupina „G1“, playlist „Nowhere“.",
                "Řádek 1, sloupec 13 (od kolika hodin, blok playlistu 2): zadáno „8am“, očekává se: čas HH:MM, např. "
                "08:00, nebo prázdné (prázdné = od 00:00). "
                "Skupina „G1“, playlist „Nowhere“.",
                "Řádek 1, sloupec 14 (do kolika hodin, blok playlistu 2): zadáno „25:00“, očekává se: čas HH:MM, např. "
                "18:00, nebo prázdné (prázdné = do 23:59). "
                "Skupina „G1“, playlist „Nowhere“."):
            self.assertIn(message, errors)
        self.assertTrue(processor.refused)

    def test_the_order_of_the_dates_and_of_the_times_names_both_columns(self):
        block = ["Promo", "31.12.2026", "01.01.2026", "", "18:00", "08:00"]
        processor, logger = self.load(DetailedPlaylistProcessor, line("G1", "Default", *block), real_text=True,
                                      action="set_detailed_playlists_to_groups")
        processor_2, logger_2 = self.load(DetailedPlaylistProcessor, line("G1", "Default", "Promo", "", "", "", "18:00",
                                                                           "08:00"), real_text=True,
                                          action="set_detailed_playlists_to_groups")

        self.assertIn("Řádek 1, sloupce 4 a 5 (platí od / platí do, blok playlistu 1): „31.12.2026“ je po „01.01.2026“, začátek platnosti "
                      "nesmí být po konci. Skupina „G1“, playlist „Promo“.", self.messages(logger))
        self.assertIn("Řádek 1, sloupce 7 a 8 (od kolika hodin / do kolika hodin, blok playlistu 1): „18:00“ není před „08:00“, začátek musí "
                      "být před koncem. Skupina „G1“, playlist „Promo“.", self.messages(logger_2))

    def test_a_default_playlist_that_does_not_exist_is_an_error_not_a_group_without_it(self):
        processor, logger = self.load(DetailedPlaylistProcessor, line("G1", "Deleted", *BLOCK_1))

        self.assertIn("name_fail", self.messages(logger, "warning"))
        self.assertTrue(processor.refused)

    def test_the_lines_are_numbered_as_the_user_sees_them_and_the_names_are_asked_for_once(self):
        text = "\n".join([line("G1", "", *BLOCK_1), "", line("G2", "", "Unknown", *EMPTY[1:])])
        processor, logger = self.load(DetailedPlaylistProcessor, text, real_text=True)

        self.assertTrue(any("Řádek 3" in message for message in self.messages(logger, "warning")))
        self.server.get_playlist_names.assert_called_once()

    def test_a_line_pasted_twice_is_read_once(self):
        text = line("G1", "", *BLOCK_1)
        processor, logger = self.load(DetailedPlaylistProcessor, text + "\n" + text)

        self.assertEqual(processor.data, {"G1": [PROMO]})
        self.assertEqual(self.messages(logger, "warning"), [])


class AddPastedPlaylistsTest(ProcessorCase):
    def setUp(self):
        super().setUp()
        self.server.get_groups_playlists_details.return_value = {"G1": [
            {"playlist_name": "Default", "start_date": None, "end_date": None, "days_of_week": None,
             "start_time": "00:00", "end_time": "23:59"}]}

    def test_new_blocks_are_added_after_the_ones_the_group_has_with_an_empty_block_between(self):
        processor, _ = self.load(AddDetailedPlaylistProcessor, line("G1", *BLOCK_1, *EMPTY, *BLOCK_2))

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data, {"G1": [("Default", None, None, None, "00:00", "23:59"), PROMO, NIGHT]})

    def test_the_line_of_a_wrong_name_is_numbered_as_the_user_sees_it(self):
        text = "\n".join([line("G1", *BLOCK_1), "", line("Nowhere", *BLOCK_1)])
        processor, logger = self.load(AddDetailedPlaylistProcessor, text, real_text=True)

        self.assertTrue(any("Řádek 3" in message for message in self.messages(logger, "warning")))

    def test_the_blocks_of_the_add_action_start_in_column_2(self):
        processor, logger = self.load(AddDetailedPlaylistProcessor, line("G1", "Promo", "x.y.z", "", "", "", ""),
                                      real_text=True, action="set_add_detailed_playlist_to_group")

        self.assertTrue(any(message.startswith("Řádek 1, sloupec 3 (platí od): zadáno „x.y.z“")
                            for message in self.messages(logger)))


class OlderPlaylistProcessorTest(ProcessorCase):
    def test_blocks_of_five_cells_follow_the_same_rules(self):
        processor, _ = self.load(PlaylistProcessor, line("G1", "Default", "Promo", "01.01.2026", "31.12.2026", "08:00",
                                                         "18:00", *EMPTY[:5], "Night", "", "", "20:00", "23:00"))

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data["G1"], [
            ("Default", None, None, None, None),
            ("Promo", "2026-01-01T00:00:00.000Z", "2026-12-31T00:00:00.000Z", "08:00", "18:00"),
            ("Night", None, None, "20:00", "23:00")])

    def test_a_line_with_the_group_only_does_not_fail(self):
        processor, logger = self.load(PlaylistProcessor, "G1")

        self.assertIn("name_fail", self.messages(logger, "warning"))
        self.assertTrue(processor.refused)


if __name__ == "__main__":
    unittest.main()
