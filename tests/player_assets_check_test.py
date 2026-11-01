"""The check of the files on the online players: what the groups send them is compared with what the players have in the
folder of the media; a player is asked one by one, only when it is still online, and the result is written as it comes."""
import unittest
from unittest.mock import MagicMock, patch

import requests

from api_testing.request_calls import PLAYER_COMMAND_TIMEOUT, PLAYER_FILES_COMMAND, PlayerCommandError, ServerApi
from destructive_actions_test import make_processor
from main_buttons_test import MainWindowCase
from processor.input_processing import FormatException, PlayerAssetsCheckProcessor, ProcessorFactory
from util.actions import action_input_optional, action_kind, action_needs_input


def player(name, online=True, group="g1"):
    return {"name": name, "_id": f"id-{name}", "isConnected": online, "group": {"_id": group} if group else None}


class ProcessorCase(unittest.TestCase):
    def setUp(self):
        self.server = MagicMock()
        self.server.get_player_objects.return_value = [player("B"), player("A"), player("C", online=False)]
        self.server.is_player_online.return_value = True
        self.server.get_group_files.return_value = ["a.mp4", "__P.json"]
        self.server.get_files_without_content.return_value = set()
        self.server.list_player_files.return_value = ["a.mp4", "__P.json", "other.mp4"]
        self.processor, self.logger, patcher = make_processor(PlayerAssetsCheckProcessor, self.server, real_text=True)
        self.addCleanup(patcher.stop)
        sleeper = patch("processor.input_processing.sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def run_all(self, text=""):
        self.processor.load(text)
        return list(self.processor.run())

    def lines(self, level):
        return [c.args[0] for c in getattr(self.logger, level).call_args_list]


class LoadTest(ProcessorCase):
    def test_an_empty_input_takes_all_the_online_players_by_name_and_counts_the_offline_ones(self):
        self.processor.load("")

        self.assertEqual([p["name"] for p in self.processor.data], ["A", "B"])
        self.assertIn("Online přehrávačů ke kontrole: 2, offline (přeskočí se): 1.", self.lines("info"))

    def test_names_narrow_it_down(self):
        self.processor.load("B\n\nC")

        self.assertEqual([p["name"] for p in self.processor.data], ["B"])
        self.assertIn("Online přehrávačů ke kontrole: 1, offline (přeskočí se): 1.", self.lines("info"))

    def test_an_unknown_name_stops_it_before_anything_is_asked(self):
        with self.assertRaises(FormatException):
            self.processor.load("A\nNobody")

        self.server.list_player_files.assert_not_called()

    def test_it_asks_before_it_starts_and_says_it_changes_nothing(self):
        self.processor.load("")

        question = self.processor.confirmation()

        self.assertIn("(2)", question.text)
        self.assertIn("Nic se nemění", question.text)

    def test_nothing_online_asks_nothing_and_says_so(self):
        self.server.get_player_objects.return_value = [player("C", online=False)]

        self.run_all()

        self.assertIsNone(self.processor.confirmation())
        self.assertIn("Žádný online přehrávač ke kontrole.", self.lines("info"))
        self.server.list_player_files.assert_not_called()


class RunTest(ProcessorCase):
    def test_a_player_that_has_everything_is_reported_so_and_the_summary_is_all_fine(self):
        self.run_all()

        info = self.lines("info")
        self.assertIn("Přehrávač A:", info)
        self.assertIn("  Má mít (2): a.mp4, __P.json", info)
        self.assertEqual(info.count("  Má všechny soubory."), 2)
        self.assertIn("Souhrn: zkontrolováno 2, vše v pořádku 2, chybí soubory 0, nezjištěno 0, offline 1.", info)
        self.assertIn("Všechny zkontrolované online přehrávače mají soubory, které mají mít.", info)
        self.assertEqual(self.lines("error"), [])

    def test_the_missing_files_are_red_and_the_summary_lists_them_for_each_player(self):
        self.server.list_player_files.side_effect = [["a.mp4", "__P.json"], ["x.mp4"]]

        self.run_all()

        errors = self.lines("error")
        self.assertIn("  CHYBÍ (2): a.mp4, __P.json", errors)
        self.assertIn("Přehrávače, kterým chybí soubory (1):", errors)
        self.assertIn("B: a.mp4, __P.json", errors)
        self.assertNotIn("Všechny zkontrolované online přehrávače mají soubory, které mají mít.", self.lines("info"))

    def test_the_red_lines_are_not_collected_as_problems_once_more_because_the_summary_names_the_players(self):
        self.server.list_player_files.return_value = []

        self.run_all()

        errors = self.logger.error.call_args_list
        self.assertEqual(len(errors), 2 + 3)  # a line for each of the two players, then the heading and a line for each
        self.assertTrue(all(c.kwargs["extra"]["progress"] for c in errors))

    def test_the_file_of_a_playlist_without_content_is_not_expected_on_the_players(self):
        self.server.get_group_files.return_value = ["a.mp4", "__P.json", "__TV_OFF.json"]
        self.server.get_files_without_content.return_value = {"__TV_OFF.json"}

        self.run_all()

        self.assertIn("  Má mít (2): a.mp4, __P.json", self.lines("info"))
        self.assertEqual(self.lines("error"), [])

    def test_a_player_that_went_offline_is_not_asked_and_is_not_waited_for(self):
        self.server.is_player_online.side_effect = [True, False]

        self.run_all()

        self.assertEqual(self.server.list_player_files.call_count, 1)
        self.assertIn("  B: přehrávač je mezitím offline, přeskočeno.", self.lines("warning"))
        self.assertIn("offline 2.", self.lines("info")[-2])

    def test_a_player_that_does_not_answer_is_skipped_and_the_next_one_is_checked(self):
        self.server.list_player_files.side_effect = [PlayerCommandError("no_answer"), ["a.mp4", "__P.json"]]

        self.run_all()

        self.assertIn("  Přehrávač neodpověděl do 30 sekund, přeskočeno.", self.lines("error"))
        self.assertIn("Nezjištěno (1): A", self.lines("error"))
        self.assertEqual(self.server.list_player_files.call_count, 2)
        self.assertNotIn("Všechny zkontrolované online přehrávače mají soubory, které mají mít.", self.lines("info"))

    def test_a_failure_of_the_connection_skips_the_player_without_the_text_of_the_error(self):
        self.server.list_player_files.side_effect = requests.exceptions.ConnectionError("secret-token")

        self.run_all()

        self.assertTrue(all("secret-token" not in line for line in self.lines("error")))
        self.assertEqual(self.server.list_player_files.call_count, 2)

    def test_there_is_a_pause_between_the_players_but_not_before_the_first(self):
        self.run_all()

        self.sleep.assert_called_once_with(0.2)

    def test_the_files_of_a_group_are_read_once(self):
        self.run_all()

        self.server.get_group_files.assert_called_once_with("g1")

    def test_a_player_without_a_group_is_skipped(self):
        self.server.get_player_objects.return_value = [player("A", group=None)]

        self.run_all()

        self.assertIn("  A: přehrávač nemá skupinu, přeskočeno.", self.lines("warning"))
        self.server.list_player_files.assert_not_called()

    def test_every_step_is_given_back_to_the_window_so_that_stop_can_work(self):
        self.assertEqual(len(self.run_all()), 2)

    def test_the_processor_is_registered(self):
        processor = ProcessorFactory.create_processor("player_assets_check", MagicMock(), "https://x", "u", "p", MagicMock())

        self.assertIsInstance(processor, PlayerAssetsCheckProcessor)


class ServerApiTest(unittest.TestCase):
    def api(self, answer=None, error=None):
        api = ServerApi.__new__(ServerApi)
        api._make_request = MagicMock(side_effect=error, return_value=answer)
        return api

    def test_the_command_is_fixed_only_reads_and_has_a_timeout_of_30_seconds(self):
        api = self.api({"data": {"err": None, "stdout": "a.mp4\n__P.json\n", "stderr": ""}})

        files = api.list_player_files("pid")

        self.assertEqual(files, ["a.mp4", "__P.json"])
        api._make_request.assert_called_once_with("post", "/pishell/pid", json={"cmd": PLAYER_FILES_COMMAND},
                                                  timeout=PLAYER_COMMAND_TIMEOUT)
        self.assertEqual(PLAYER_COMMAND_TIMEOUT[1], 30)
        self.assertTrue(PLAYER_FILES_COMMAND.startswith("ls "))

    def test_a_timeout_and_an_error_of_the_player_are_a_player_that_did_not_answer(self):
        for api in (self.api(error=requests.exceptions.ReadTimeout()),
                    self.api({"data": {"err": "Could not get response from the player", "stdout": ""}})):
            with self.subTest():
                with self.assertRaises(PlayerCommandError) as raised:
                    api.list_player_files("pid")
                self.assertEqual(raised.exception.reason, "no_answer")

    def test_an_error_of_the_command_is_a_failure(self):
        api = self.api({"data": {"err": None, "stdout": "", "stderr": "ls: cannot access"}})

        with self.assertRaises(PlayerCommandError) as raised:
            api.list_player_files("pid")

        self.assertEqual(raised.exception.reason, "failed")

    def test_only_a_playlist_without_rows_has_a_file_that_no_player_gets(self):
        api = self.api()
        api._playlist_objects = MagicMock(return_value=[{"name": "TV_OFF", "assets": []}, {"name": "P", "assets": [{}]},
                                                        {"name": "Q"}])

        self.assertEqual(api.get_files_without_content(), {"__TV_OFF.json", "__Q.json"})

    def test_the_state_of_one_player_is_read_with_one_small_request(self):
        api = self.api({"data": {"isConnected": True}})

        self.assertTrue(api.is_player_online("pid"))
        api._make_request.assert_called_once_with("get", "/players/pid")


class ActionTest(MainWindowCase):
    def test_the_action_is_in_the_blue_block_and_its_input_is_optional(self):
        self.assertEqual(action_kind("set_player_assets_check"), "change")
        self.assertTrue(action_needs_input("set_player_assets_check"))
        self.assertTrue(action_input_optional("set_player_assets_check"))
        self.assertFalse(action_input_optional("set_player_snapshot"))

    def test_the_action_is_offered_among_the_players_and_starts_with_an_empty_input(self):
        self.app.entity_type_var.set("Players")
        self.app.update_action_selection()
        label = next(label for label, key in self.app.entity_actions["Players"].items()
                     if key == "set_player_assets_check")
        self.assertIn(label, self.app.option_choose_action["values"])
        self.assertEqual(label, "Kontrola assetů přehrávačů")

        with patch.object(self.app, "open_action_log_box") as opened:
            self.app.perform_set_action("set_player_assets_check", "https://x", "u", "p", None)

        opened.assert_called_once_with("player_assets_check", "https://x", "u", "p", "")

    def test_another_action_still_refuses_an_empty_input(self):
        with patch.object(self.app, "open_action_log_box") as opened, patch("gui_app.gui.messagebox"):
            self.app.perform_set_action("set_player_snapshot", "https://x", "u", "p", "  ")

        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
