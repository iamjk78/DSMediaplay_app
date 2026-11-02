"""The check of the files on the online players: what the groups send them is compared with what the players have in the
folder of the media; a player is asked one by one, only when it is still online, and the result is written as it comes."""
import unittest
from unittest.mock import MagicMock, patch

import requests

from api_testing.request_calls import PLAYER_COMMAND_TIMEOUT, PLAYER_FILES_COMMAND, PlayerCommandError, ServerApi
from util.player_audit import PLAYER_AUDIT_COMMAND
from destructive_actions_test import make_processor
from main_buttons_test import MainWindowCase
from processor.input_processing import FormatException, PlayerAssetsCheckProcessor, ProcessorFactory
from util.actions import action_input_optional, action_kind, action_needs_input


def expectation(files=("a.mp4", "__P.json"), **changes):
    """What the group sends, as ServerApi.get_group_expectation gives it, with the digests of what a good player has."""
    return {"group": "G", "files": list(files), "sizes": {"a.mp4": (100, 1)}, "deployed": "d1", "validity": "v1",
            "values": {"deployed": [{"name": "P", "settings": {"domination": {"timeInterval": 5}}}],
                       "validity": [{"name": "a.mp4", "enddate": "2027"}], "settings": {"kioskUi": {"enable": True}},
                       "playlists": {"P": {"layout": "1", "settings": {"ads": {"adCount": 1}},
                                           "assets": [{"filename": "a.mp4", "duration": 5}, {"filename": "b.mp4"}]}}},
            "settings": {"kioskUi": "s1"}, "playlists": {"P": {part: "p" for part in
                                                              ("layout", "settings", "templateName", "schedule", "videoWindow",
                                                               "zoneVideoWindow", "order", "rows")}},
            "undeployed": [], **changes}


def on_player(**changes):
    """What a player that has all of it reports (ServerApi.audit_player)."""
    return {"files": {"a.mp4": 100, "__P.json": 500, "other.mp4": 5}, "deployed": "d1", "validity": "v1",
            "settings": {"kioskUi": "s1"}, "playlists": {"P": {part: "p" for part in
                                                              ("layout", "settings", "templateName", "schedule", "videoWindow",
                                                               "zoneVideoWindow", "order", "rows")}}, **changes}


def player(name, online=True, group="g1"):
    return {"name": name, "_id": f"id-{name}", "isConnected": online, "group": {"_id": group} if group else None}


class ProcessorCase(unittest.TestCase):
    def setUp(self):
        self.server = MagicMock()
        self.server.get_player_objects.return_value = [player("B"), player("A"), player("C", online=False)]
        self.server.is_player_online.return_value = True
        self.server.get_group_expectation.return_value = expectation()
        self.server.audit_player.return_value = on_player()
        self.server.read_player_details.side_effect = PlayerCommandError("failed")  # the values are not read unless asked for
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

        self.server.audit_player.assert_not_called()

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
        self.assertEqual(info.count("  Má všechny soubory a nastavení odpovídá serveru."), 2)
        self.assertIn("Souhrn: zkontrolováno 2, vše v pořádku 2, odlišnosti od serveru 0, nezjištěno 0, offline 1.", info)
        self.assertIn("Všechny zkontrolované online přehrávače mají soubory, které mají mít.", info)
        self.assertEqual(self.lines("error"), [])

    def test_the_missing_files_are_red_and_the_summary_lists_them_for_each_player(self):
        self.server.audit_player.side_effect = [on_player(files={"x.mp4": 1}), on_player()]

        self.run_all()

        errors = self.lines("error")
        self.assertIn("  CHYBÍ (2): a.mp4, __P.json", errors)
        self.assertIn("Přehrávače s odlišnostmi od serveru (1):", errors)
        self.assertIn("A: CHYBÍ (2): a.mp4, __P.json", errors)  # the players are checked by name
        self.assertNotIn("Všechny zkontrolované online přehrávače mají soubory, které mají mít.", self.lines("info"))

    def test_a_file_of_another_size_is_named_with_both_sizes(self):
        self.server.audit_player.return_value = on_player(files={"a.mp4": 40, "__P.json": 500})

        self.run_all()

        self.assertIn("  JINÁ VELIKOST (1): a.mp4 (server 100 B, přehrávač 40 B)", self.lines("error"))

    def test_the_settings_that_differ_are_named(self):
        self.server.audit_player.return_value = on_player(deployed="other", validity="other",
                                                          settings={"kioskUi": "x"},
                                                          playlists={"P": {**on_player()["playlists"]["P"], "order": "x",
                                                                           "rows": "x", "settings": "x"}})

        self.run_all()

        errors = self.lines("error")
        self.assertIn("  Seznam playlistů a jejich nastavení (platnost, domination, přeskočení podle rozvrhu…) se liší od "
                      "serveru.", errors)
        self.assertIn("  Omezení platnosti assetů se liší od serveru.", errors)
        self.assertIn("  Nastavení skupiny se liší (1): kioskUi", errors)
        self.assertIn("  Playlist P se liší od serveru: nastavení playlistu, pořadí nebo seznam assetů", errors)

    def test_where_a_value_differs_the_value_on_the_server_and_on_the_player_are_listed(self):
        self.server.audit_player.return_value = on_player(deployed="x", validity="x", settings={"kioskUi": "x"},
                                                          playlists={"P": {**on_player()["playlists"]["P"], "order": "x",
                                                                           "settings": "x"}})
        self.server.read_player_details.side_effect = None
        self.server.read_player_details.return_value = {
            "deployed": [{"name": "P", "settings": {"domination": {"timeInterval": 10}}}],
            "validity": [{"name": "a.mp4", "enddate": "2026"}], "settings": {"kioskUi": {"enable": False}},
            "playlists": {"P": {"order": ["b.mp4", "a.mp4"], "settings": {"ads": {"adCount": 2}}}}}

        self.run_all()

        errors = self.lines("error")
        for line in ("      P.settings.domination.timeInterval: server 5, přehrávač 10",
                     "      a.mp4.enddate: server \"2027\", přehrávač \"2026\"",
                     "      kioskUi: enable: server true, přehrávač false",
                     "      nastavení playlistu: ads.adCount: server 1, přehrávač 2",
                     "      pořadí nebo seznam assetů: pořadí: server [\"a.mp4\", \"b.mp4\"], přehrávač [\"b.mp4\", \"a.mp4\"]"):
            self.assertIn(line, errors)
        self.assertEqual(self.server.read_player_details.call_args.args[1]["playlists"],
                         {"P": ["settings", "order"]})
        self.assertTrue(all(c.kwargs["extra"]["progress"] for c in self.logger.error.call_args_list))

    def test_the_summary_names_what_differs_without_the_values(self):
        self.server.audit_player.return_value = on_player(deployed="x")
        self.server.read_player_details.side_effect = None
        self.server.read_player_details.return_value = {"deployed": []}

        self.run_all()

        summary = [line for line in self.lines("error") if line.startswith("A: ")]
        self.assertEqual(len(summary), 1)
        self.assertNotIn("server", summary[0].split("od serveru")[-1])

    def test_a_playlist_that_only_the_server_has_in_the_group_is_named_as_such(self):
        self.server.audit_player.return_value = on_player(deployed="x")
        self.server.get_group_expectation.return_value = expectation(values={
            **expectation()["values"], "deployed": [{"name": "TV_OFF"}, {"name": "A"}, {"name": "B"}]})
        self.server.read_player_details.side_effect = None
        self.server.read_player_details.return_value = {"deployed": [{"name": "TV_OFF"}, {"name": "B"}]}

        self.run_all()

        self.assertIn("      jen na serveru: server [\"A\"], přehrávač <není>", self.lines("error"))
        self.assertEqual(len([line for line in self.lines("error") if line.startswith("      ")]), 2)  # no cascade

    def test_a_player_that_cannot_tell_the_values_still_gets_the_line_of_what_differs(self):
        self.server.audit_player.return_value = on_player(deployed="x")  # the values cannot be read (set in setUp)

        self.run_all()

        self.assertIn("  Seznam playlistů a jejich nastavení (platnost, domination, přeskočení podle rozvrhu…) se liší od "
                      "serveru.", self.lines("error"))
        self.server.read_player_details.assert_called()

    def test_only_the_first_places_are_listed_and_the_rest_is_counted(self):
        self.server.audit_player.return_value = on_player(deployed="x")
        self.server.get_group_expectation.return_value = expectation(values={
            **expectation()["values"], "deployed": [{"name": "P", "settings": {f"k{i}": i for i in range(10)}}]})
        self.server.read_player_details.side_effect = None
        self.server.read_player_details.return_value = {"deployed": [{"name": "P", "settings": {f"k{i}": -i for i in range(10)}}]}

        self.run_all()

        errors = self.lines("error")
        self.assertEqual(len([line for line in errors if line.startswith("      P.")]), 12)  # 6 places, for two players
        self.assertIn("      … a dalších 3", errors)  # k0 is 0 on both sides
        self.assertIn("      P.settings.k1: server 1, přehrávač -1", errors)

    def test_a_player_that_cannot_run_the_script_is_checked_for_its_files_only_and_says_so(self):
        self.server.audit_player.side_effect = PlayerCommandError("failed")
        self.server.list_player_files.return_value = ["a.mp4", "__P.json"]

        self.run_all()

        self.assertIn("  A: nastavení nelze ověřit (přehrávač neumí spustit kontrolní skript), zkontrolovány jsou jen soubory.",
                      self.lines("warning"))
        self.assertEqual(self.lines("error"), [])
        self.server.list_player_files.assert_called()

    def test_changes_of_a_group_that_were_not_deployed_are_said_once_for_the_group(self):
        self.server.get_group_expectation.return_value = expectation(undeployed=["playlists", "assets"])

        self.run_all()

        warnings = self.lines("warning")
        self.assertEqual(warnings.count("  Skupina G má změny, které ještě nebyly nasazeny (seznam playlistů, seznam souborů). "
                                        "Rozdíly níže mohou být jen tím, je potřeba Deploy."), 1)

    def test_the_red_lines_are_not_collected_as_problems_once_more_because_the_summary_names_the_players(self):
        self.server.audit_player.return_value = on_player(files={})

        self.run_all()

        errors = self.logger.error.call_args_list
        self.assertEqual(len(errors), 2 + 3)  # a line for each of the two players, then the heading and a line for each
        self.assertTrue(all(c.kwargs["extra"]["progress"] for c in errors))

    def test_a_player_that_went_offline_is_not_asked_and_is_not_waited_for(self):
        self.server.is_player_online.side_effect = [True, False]

        self.run_all()

        self.assertEqual(self.server.audit_player.call_count, 1)
        self.assertIn("  B: přehrávač je mezitím offline, přeskočeno.", self.lines("warning"))
        self.assertIn("offline 2.", self.lines("info")[-2])

    def test_a_player_that_does_not_answer_is_skipped_and_the_next_one_is_checked(self):
        self.server.audit_player.side_effect = [PlayerCommandError("no_answer"), on_player()]

        self.run_all()

        self.assertIn("  Přehrávač neodpověděl do 30 sekund, přeskočeno.", self.lines("error"))
        self.assertIn("Nezjištěno (1): A", self.lines("error"))
        self.assertEqual(self.server.audit_player.call_count, 2)
        self.assertNotIn("Všechny zkontrolované online přehrávače mají soubory, které mají mít.", self.lines("info"))

    def test_a_failure_of_the_connection_skips_the_player_without_the_text_of_the_error(self):
        self.server.audit_player.side_effect = requests.exceptions.ConnectionError("secret-token")

        self.run_all()

        self.assertTrue(all("secret-token" not in line for line in self.lines("error")))
        self.assertEqual(self.server.audit_player.call_count, 2)

    def test_there_is_a_pause_between_the_players_but_not_before_the_first(self):
        self.run_all()

        self.sleep.assert_called_once_with(0.2)

    def test_what_a_group_should_have_is_read_once(self):
        self.run_all()

        self.server.get_group_expectation.assert_called_once_with("g1")

    def test_a_player_without_a_group_is_skipped(self):
        self.server.get_player_objects.return_value = [player("A", group=None)]

        self.run_all()

        self.assertIn("  A: přehrávač nemá skupinu, přeskočeno.", self.lines("warning"))
        self.server.audit_player.assert_not_called()

    def test_a_group_without_files_is_said_so_and_not_judged(self):
        self.server.get_group_expectation.return_value = expectation(files=())

        self.run_all()

        self.assertIn("  A: skupina přehrávače nemá žádné soubory ke stažení.", self.lines("warning"))
        self.server.audit_player.assert_not_called()

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

    def expectation(self, group, playlists, sizes=None):
        api = self.api({"data": group})
        api._playlist_objects = MagicMock(return_value=playlists)
        api._asset_sizes = MagicMock(return_value=sizes or {})
        return api.get_group_expectation("g")

    def test_the_files_of_a_group_are_those_it_sends_and_those_its_playlists_need(self):
        group = {"_id": "g", "name": "G", "logo": "logo.png", "assets": ["a.mp4", "old.mp4"], "playlists": [{"name": "P"}]}
        playlists = [{"name": "P", "layout": "1", "assets": [{"filename": "a.mp4"}, {"filename": "b.mp4"}]}]

        result = self.expectation(group, playlists, {"a.mp4": (100, 1), "zzz": (1, 1)})

        self.assertEqual(result["files"], ["a.mp4", "old.mp4", "b.mp4", "__P.json", "logo.png"])
        self.assertEqual(result["sizes"], {"a.mp4": (100, 1)})  # of the sizes only those of its own files
        self.assertEqual(result["group"], "G")

    def test_a_group_without_the_list_of_files_still_needs_the_files_of_its_playlists(self):
        playlists = [{"name": "P", "layout": "1", "assets": [{"filename": "a.mp4"}]}]

        result = self.expectation({"_id": "g", "assets": [], "playlists": [{"name": "P"}]}, playlists)

        self.assertEqual(result["files"], ["a.mp4", "__P.json"])

    def test_what_was_deployed_is_expected_not_what_is_set_since_and_the_change_is_named(self):
        playlists = [{"name": "Old", "layout": "1", "assets": [{"filename": "o.mp4"}]},
                     {"name": "New", "layout": "1", "assets": [{"filename": "n.mp4"}]}]
        group = {"_id": "g", "playlists": [{"name": "New"}], "deployedPlaylists": [{"name": "Old"}],
                 "assets": ["n.mp4", "__New.json"], "deployedAssets": ["o.mp4", "__Old.json"]}

        result = self.expectation(group, playlists)

        self.assertEqual(result["files"], ["o.mp4", "__Old.json"])
        self.assertEqual(result["undeployed"], ["playlists", "assets"])

    def test_a_group_that_was_deployed_has_nothing_undeployed(self):
        group = {"_id": "g", "playlists": [{"name": "P"}], "deployedPlaylists": [{"name": "P"}], "assets": ["a"],
                 "deployedAssets": ["a"]}

        self.assertEqual(self.expectation(group, [])["undeployed"], [])

    def test_the_files_of_playlists_without_rows_are_not_expected(self):
        group = {"_id": "g", "playlists": [{"name": "TV_OFF"}], "assets": ["__TV_OFF.json"]}

        result = self.expectation(group, [{"name": "TV_OFF", "assets": []}])

        self.assertEqual(result["files"], [])

    def test_the_sizes_of_the_account_are_read_once_and_parsed(self):
        api = self.api({"data": {"dbdata": [{"name": "a.mp4", "size": "7401KB"}, {"name": "b.jpg", "size": "351839B"},
                                            {"name": "c", "size": "?"}, {"size": "1B"}]}})

        self.assertEqual(api._asset_sizes(), {"a.mp4": (7401000, 1000), "b.jpg": (351839, 0)})
        api._asset_sizes()
        api._make_request.assert_called_once()

    def test_what_the_player_has_is_read_by_one_fixed_command_that_only_reads(self):
        api = self.api({"data": {"err": None, "stdout": '{"files": {"a.mp4": 5}, "deployed": "d"}\n', "stderr": ""}})

        self.assertEqual(api.audit_player("pid"), {"files": {"a.mp4": 5}, "deployed": "d"})
        sent = api._make_request.call_args.kwargs["json"]["cmd"]
        self.assertEqual(sent, PLAYER_AUDIT_COMMAND)
        for forbidden in ("rm ", "kill", "chmod", "mv ", ">", "open(path, \"w", "subprocess", "os.system", "write"):
            self.assertNotIn(forbidden, sent)

    def test_an_answer_that_is_not_what_the_script_prints_is_a_failure(self):
        for stdout in ("", "garbage", "[1]", '{"no": "files"}'):
            with self.subTest(stdout=stdout):
                with self.assertRaises(PlayerCommandError) as raised:
                    self.api({"data": {"err": None, "stdout": stdout, "stderr": ""}}).audit_player("pid")
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
