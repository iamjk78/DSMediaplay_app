"""The messages about a wrong line say the same things for every action: in which column the problem is (number and name),
what was entered, and what that column takes, as the template of the action describes it."""
import json
import unittest

from pasted_playlists_test import ProcessorCase, line
from processor.input_processing import (ACTION_OF_PROCESSOR, AssetValidityProcessor, CreateGroupProcessor,
                                        GroupRenameProcessor, LocationRenameProcessor, LocationTimesProcessor,
                                        PlayerConfigLocationProcessor, PlayerGroupProcessor, PlayerLabelsProcessor,
                                        PlayerRenameProcessor, PlaylistSettingsProcessor, RemovePlaylistsProcessor,
                                        AssetToPlaylistProcessor)
from util.input_templates import LANGUAGES, column_info, example_line, has_template


class InputErrorsTest(ProcessorCase):
    def setUp(self):
        super().setUp()
        self.server.get_player_names.return_value = ["P1", "P2", "abc_PB3434_x"]
        self.server.get_location_names.return_value = ["L1"]
        self.server.get_asset_names.return_value = ["a.jpg"]
        self.server.get_labels.return_value = ["Cat"]

    def errors(self, logger):
        return self.messages(logger) + self.messages(logger, "warning")

    def test_a_line_with_too_many_columns_gives_the_count_the_columns_and_a_model(self):
        processor, logger = self.load(PlayerGroupProcessor, line("P1", "G1", "extra"), real_text=True,
                                      action="set_groups_to_players")

        message = self.messages(logger)[0]
        self.assertIn("Řádek 1: špatný počet sloupců: zadáno 3, očekává se 2.", message)
        self.assertIn("Přebývá sloupců: 1.", message)
        self.assertIn("Sloupce: 1. název přehrávače; 2. název skupiny.", message)
        self.assertIn("Zadáno: P1⇥G1⇥extra", message)
        self.assertIn("Vzor: <název přehrávače>⇥<název skupiny>", message)

    def test_a_name_that_the_account_does_not_have_says_the_column(self):
        processor, logger = self.load(PlayerGroupProcessor, line("P1", "Nowhere"), real_text=True,
                                      action="set_groups_to_players")

        self.assertTrue(any(message.startswith("Řádek 1, sloupec 2 (název skupiny): zadáno „Nowhere“, očekává se: "
                                               "název skupiny. Takové jméno v účtu není")
                            for message in self.errors(logger)))

    def test_an_unknown_asset_among_many_says_its_own_column(self):
        processor, logger = self.load(AssetToPlaylistProcessor, line("Default", "a.jpg", "", "ghost.jpg"), real_text=True,
                                      action="set_assets_to_playlists")

        self.assertTrue(any(message.startswith("Řádek 1, sloupec 4 (názvy assetů): zadáno „ghost.jpg“")
                            for message in self.errors(logger)))

    def test_a_location_that_is_not_in_the_account_is_in_the_second_column_of_the_line_of_a_player(self):
        processor, logger = self.load(PlayerConfigLocationProcessor, line("P1", "Nowhere"), real_text=True,
                                      action="set_player_config_location")

        self.assertTrue(any(message.startswith("Řádek 1, sloupec 2 (název lokace): zadáno „Nowhere“")
                            for message in self.errors(logger)))

    def test_a_category_that_is_not_in_the_account_says_its_column(self):
        processor, logger = self.load(PlayerLabelsProcessor, line("P1", "Cat", "Missing"), real_text=True,
                                      action="set_player_labels")

        self.assertTrue(any(message.startswith("Řádek 1, sloupec 3 (názvy kategorií): zadáno „Missing“")
                            for message in self.errors(logger)))

    def test_the_hours_of_the_location_name_their_day_and_their_column(self):
        cells = ["L1", "8:00", "7:00", "x", ""] + [""] * 10
        processor, logger = self.load(LocationTimesProcessor, line(*cells), real_text=True, action="set_location_plan")

        errors = self.errors(logger)
        self.assertIn("Řádek 1, sloupce 2 a 3 (neděle - zapnutí / neděle - vypnutí): „08:00“ není před „07:00“, začátek "
                      "musí být před koncem.", errors)
        self.assertIn("Řádek 1, sloupec 4 (pondělí - zapnutí): zadáno „x“, očekává se: čas HH:MM, např. 08:00, nebo "
                      "prázdné.", errors)

    def test_the_validity_of_an_asset_says_the_columns_of_its_dates_and_hours(self):
        processor, logger = self.load(AssetValidityProcessor, line("a.jpg", "2026-01-01", "", "8:30", "25"),
                                      real_text=True, action="set_asset_validity")

        errors = self.errors(logger)
        self.assertTrue(any(message.startswith("Řádek 1, sloupec 2 (platí od): zadáno „2026-01-01“, očekává se: datum")
                            and message.endswith("Název assetu „a.jpg“.") for message in errors))
        self.assertTrue(any(message.startswith("Řádek 1, sloupec 4 (od kolika hodin): zadáno „8:30“") for message in errors))
        self.assertTrue(any(message.startswith("Řádek 1, sloupec 5 (do kolika hodin): zadáno „25“") for message in errors))

    def test_the_interval_of_the_dominance_says_the_column(self):
        processor, logger = self.load(PlaylistSettingsProcessor, line("Promo", "abc"), real_text=True,
                                      action="set_playlist_settings")

        self.assertTrue(any(message.startswith("Řádek 1, sloupec 2 (interval dominance): zadáno „abc“, očekává se: celé "
                                               "číslo") for message in self.errors(logger)))

    def test_an_empty_keyword_says_the_column(self):
        processor, logger = self.load(RemovePlaylistsProcessor, line("G1", ""), real_text=True,
                                      action="remove_playlists_from_group")

        self.assertTrue(any(message.startswith("Řádek 1, sloupec 2 (klíčové slovo): zadáno „(prázdné)“")
                            and "Prázdné klíčové slovo by odebralo všechno." in message for message in self.errors(logger)))

    def test_a_new_name_that_exists_or_has_characters_that_are_not_allowed_says_which(self):
        self.server.get_group_names.return_value = ["G1", "G2"]
        processor, logger = self.load(CreateGroupProcessor, "G1\nškoda;x\nNew", real_text=True, action="create_group")

        errors = self.errors(logger)
        self.assertTrue(any(message.startswith("Řádek 1, sloupec 1 (nový název skupiny): zadáno „G1“")
                            and message.endswith("Takový název už v účtu je.") for message in errors))
        self.assertTrue(any(message.startswith("Řádek 2, sloupec 1 (nový název skupiny): zadáno „škoda;x“")
                            and message.endswith("Nepovolené znaky: ;, š.") for message in errors))

    def test_a_new_name_for_a_rename_is_judged_in_the_second_column_with_the_reason(self):
        processor, logger = self.load(GroupRenameProcessor, "G1\tbad name\nG2\tG1", real_text=True,
                                      action="set_group_rename")

        errors = self.errors(logger)
        self.assertTrue(any(message.startswith("Řádek 1, sloupec 2 (nový název): zadáno „bad name“, očekává se: bez mezery")
                            and message.endswith("Starý název: „G1“.") for message in errors))
        self.assertTrue(any(message.startswith("Řádek 2, sloupec 2 (nový název): zadáno „G1“")
                            and "už v účtu existuje" in message for message in errors))

    def test_a_player_may_not_change_its_identifier_and_the_message_says_so(self):
        processor, logger = self.load(PlayerRenameProcessor, line("abc_PB3434_x", "abc_PB9999_x"), real_text=True,
                                      action="set_player_rename")

        self.assertTrue(any("sloupec 2 (nový název)" in message and "identifikátor přehrávače, ten se měnit nesmí" in message
                            for message in self.errors(logger)))

    def test_the_same_name_twice_is_said_in_its_column(self):
        processor, logger = self.load(PlayerGroupProcessor, "P1\tG1\nP1\tG2", real_text=True,
                                      action="set_groups_to_players")

        self.assertTrue(any(message.startswith("Řádek 2, sloupec 1 (název přehrávače): zadáno „P1“")
                            and "jen jednou" in message for message in self.errors(logger)))


class EveryActionTest(unittest.TestCase):
    def test_every_action_has_a_template_that_names_its_first_column_and_gives_a_model_line(self):
        for action in set(ACTION_OF_PROCESSOR.values()):
            for language in LANGUAGES:
                with self.subTest(action=action, language=language):
                    self.assertTrue(has_template(action))
                    self.assertIsNotNone(column_info(action, language, 1))
                    self.assertTrue(example_line(action, language))

    def test_every_action_that_has_a_template_is_known_to_a_processor(self):
        import os
        with open(os.path.join(os.path.dirname(__file__), "..", "assets", "input_templates.json"), encoding="utf-8") as file:
            actions = json.load(file)["cz"]["actions"]

        self.assertEqual(set(actions), set(ACTION_OF_PROCESSOR.values()))

    def test_the_columns_of_the_actions_with_more_than_one_column_are_all_described(self):
        for action, columns in (("set_group_settings", 10), ("set_location_plan", 15), ("set_asset_validity", 5),
                                ("set_player_labels", 4), ("set_detailed_playlists_to_groups", 14)):
            for language in LANGUAGES:
                for column in range(1, columns + 1):
                    with self.subTest(action=action, language=language, column=column):
                        info = column_info(action, language, column)
                        self.assertIsNotNone(info)
                        self.assertTrue(info.name and info.expected)


if __name__ == "__main__":
    unittest.main()
