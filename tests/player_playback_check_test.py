"""The check of the playback on the online players: each is asked, one by one and only when it is still online, which
video players run on it; one that seems not to play is asked once more after a pause."""
import unittest
from unittest.mock import MagicMock, patch

import requests

from api_testing.request_calls import (PLAYER_PLAYBACK_COMMAND, PlayerCommandError, ServerApi, parse_etime,
                                       parse_playback)
from destructive_actions_test import make_processor
from main_buttons_test import MainWindowCase
from processor.input_processing import PlayerPlaybackCheckProcessor, ProcessorFactory
from util.actions import action_input_optional, action_kind, action_needs_input

PLAYING = [{"age": 7, "process": "omxplayer.bin", "file": "a.mp4", "loop": False}]


def player(name, online=True, playlist="P"):
    return {"name": name, "_id": f"id-{name}", "isConnected": online, "currentPlaylist": playlist, "group": {"_id": "g"}}


class ProcessorCase(unittest.TestCase):
    def setUp(self):
        self.server = MagicMock()
        self.server.get_player_objects.return_value = [player("B"), player("A"), player("C", online=False)]
        self.server.is_player_online.return_value = True
        self.server.get_playlists_without_video.return_value = set()
        self.server.read_player_playback.return_value = PLAYING
        self.processor, self.logger, patcher = make_processor(PlayerPlaybackCheckProcessor, self.server, real_text=True)
        self.addCleanup(patcher.stop)
        sleeper = patch("processor.input_processing.sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def run_all(self, text=""):
        self.processor.load(text)
        return list(self.processor.run())

    def lines(self, level):
        return [c.args[0] for c in getattr(self.logger, level).call_args_list]


LONG = [{"age": 3 * 3600, "process": "omxplayer.bin", "file": "a.mp4", "loop": False}]


def looks(**answers):
    """The answers of the players, one after another: {"id-A": [[], PLAYING]}; a player that is not named always plays, the last answer of one that is named is its answer from then on."""
    def read(player_id):
        if player_id not in answers:
            return PLAYING
        return answers[player_id].pop(0) if len(answers[player_id]) > 1 else answers[player_id][0]  # the last one stays
    return read


class RunTest(ProcessorCase):
    def sleeps(self):
        return [c.args[0] for c in self.sleep.call_args_list]

    def test_a_player_that_plays_at_the_first_query_is_asked_once_and_its_result_is_playing(self):
        self.run_all()

        info = self.lines("info")
        self.assertIn("Přehrávač A:", info)
        self.assertEqual(info.count("  Přehrává: a.mp4 (běží 7 s)"), 2)
        self.assertEqual(info.count("  Výsledek: přehrává."), 2)
        self.assertIn("Souhrn: zkontrolováno 2, přehrává 2, nepřehrává 0, nezvykle dlouhé video 0, bez videa v playlistu 0, "
                      "nezjištěno 0, offline 1.", info)
        self.assertIn("Všechny zkontrolované online přehrávače s videem přehrávají.", info)
        self.assertEqual(self.lines("error"), [])
        self.assertEqual(self.server.read_player_playback.call_count, 2)  # one query for each player, no more
        self.assertEqual(self.sleeps(), [0.2])

    def test_a_player_that_does_not_play_at_the_first_query_and_plays_at_the_second_works(self):
        self.server.read_player_playback.side_effect = looks(**{"id-A": [[], PLAYING]})

        self.run_all()

        info = self.lines("info")
        self.assertIn("  Dotaz 1: neběží přehrávač videa.", info)
        self.assertIn("  Výsledek: přehrává (první dotaz přehrávač videa nezachytil, další ano).", info)
        self.assertEqual(self.lines("error"), [])  # what the first query did not see is no error
        self.assertIn("Všechny zkontrolované online přehrávače s videem přehrávají.", info)
        self.assertEqual(self.sleeps(), [1.5, 0.2])  # A is asked first, its second query is 1.5 s later
        self.assertEqual(self.server.read_player_playback.call_count, 3)

    def test_the_third_query_is_the_last_and_one_that_sees_the_playback_ends_it(self):
        self.server.read_player_playback.side_effect = looks(**{"id-A": [[], [], PLAYING]})

        self.run_all()

        self.assertEqual(self.sleeps(), [1.5, 1.5, 0.2])
        self.assertIn("  Dotaz 2: neběží přehrávač videa.", self.lines("info"))
        self.assertEqual(self.lines("error"), [])

    def test_a_player_that_none_of_the_three_queries_sees_playing_is_red_in_the_log_and_the_summary(self):
        self.server.read_player_playback.side_effect = looks(**{"id-A": [[]]})

        self.run_all()

        errors = self.lines("error")
        self.assertEqual([c.args[0] for c in self.server.read_player_playback.call_args_list].count("id-A"), 3)
        self.assertIn("  Dotaz 1: neběží přehrávač videa.", self.lines("info"))
        self.assertEqual(errors.count("  NEPŘEHRÁVÁ: neběží žádný přehrávač videa (playlist P)"), 1)  # the last query decides
        self.assertIn("  Výsledek: NEPŘEHRÁVÁ (přehrávač videa nebyl vidět v žádném ze 3 dotazů).", errors)
        self.assertIn("Nepřehrávají (1):", errors)
        self.assertIn("A: playlist P", errors)
        self.assertNotIn("Všechny zkontrolované online přehrávače s videem přehrávají.", self.lines("info"))

    def test_a_video_that_runs_for_hours_in_all_three_queries_is_reported_as_unusual(self):
        self.server.read_player_playback.return_value = LONG

        self.run_all()

        errors = self.lines("error")
        self.assertIn("  Video běží nezvykle dlouho: a.mp4 (3 h)", errors)
        self.assertIn("  Výsledek: VIDEO BĚŽÍ NEZVYKLE DLOUHO (ve všech 3 dotazech).", errors)
        self.assertIn("Video běží nezvykle dlouho (2):", errors)
        self.assertEqual(self.server.read_player_playback.call_count, 6)

    def test_an_unusually_long_video_that_is_gone_at_the_second_query_is_no_error(self):
        self.server.read_player_playback.side_effect = looks(**{"id-A": [LONG, PLAYING]})

        self.run_all()

        self.assertIn("  Dotaz 1: video běží nezvykle dlouho: a.mp4 (3 h).", self.lines("info"))
        self.assertEqual(self.lines("error"), [])

    def test_a_video_played_in_a_loop_runs_for_days_and_that_is_fine(self):
        self.server.read_player_playback.return_value = [{"age": 12 * 86400, "process": "omxplayer.bin", "file": "a.mp4",
                                                          "loop": True}]

        self.run_all()

        self.assertIn("  Přehrává ve smyčce: a.mp4 (běží 12 d)", self.lines("info"))
        self.assertEqual(self.lines("error"), [])
        self.assertEqual(self.server.read_player_playback.call_count, 2)

    def test_every_player_ends_with_a_result_whatever_became_of_it(self):
        self.server.get_player_objects.return_value = [player("A"), player("B"), player("C"), player("D", playlist="Q")]
        self.server.get_playlists_without_video.return_value = {"Q"}
        self.server.is_player_online.side_effect = lambda player_id: player_id != "id-C"
        self.server.read_player_playback.side_effect = lambda player_id: (_ for _ in ()).throw(PlayerCommandError("no_answer")) \
            if player_id == "id-B" else PLAYING

        self.run_all()

        self.assertEqual([line for line in self.lines("info") if line.startswith("  Výsledek")],
                         ["  Výsledek: přehrává.", "  Výsledek: nezjištěno.", "  Výsledek: offline, přeskočeno.",
                          "  Výsledek: nelze posoudit (playlist bez videa)."])

    def test_a_playlist_without_a_video_is_not_asked(self):
        self.server.get_playlists_without_video.return_value = {"P"}

        self.run_all()

        self.server.read_player_playback.assert_not_called()
        self.assertIn("  Playlist P neobsahuje video, podle procesu přehrávání to nelze posoudit.", self.lines("info"))
        self.assertIn("bez videa v playlistu 2", self.lines("info")[-2])

    def test_a_player_that_went_offline_is_not_asked(self):
        self.server.is_player_online.side_effect = [True, False]

        self.run_all()

        self.assertEqual(self.server.read_player_playback.call_count, 1)
        self.assertIn("  B: přehrávač je mezitím offline, přeskočeno.", self.lines("warning"))

    def test_a_player_that_does_not_answer_is_skipped_and_named_as_unknown(self):
        self.server.read_player_playback.side_effect = [PlayerCommandError("no_answer"), PLAYING]

        self.run_all()

        self.assertIn("  Přehrávač neodpověděl do 30 sekund, přeskočeno.", self.lines("error"))
        self.assertIn("Nezjištěno (1): A", self.lines("error"))
        self.assertEqual(self.server.read_player_playback.call_count, 2)

    def test_a_failure_of_the_connection_names_no_secret(self):
        self.server.read_player_playback.side_effect = requests.exceptions.ConnectionError("secret-token")

        self.run_all()

        self.assertTrue(all("secret-token" not in line for line in self.lines("error")))

    def test_there_is_a_pause_between_the_players_and_between_the_queries_of_one(self):
        self.server.read_player_playback.return_value = []

        self.run_all()

        self.assertEqual(self.sleeps(), [1.5, 1.5, 0.2, 1.5, 1.5])

    def test_the_red_lines_are_not_collected_as_problems_once_more(self):
        self.server.read_player_playback.return_value = []

        self.run_all()

        self.assertTrue(all(c.kwargs["extra"]["progress"] for c in self.logger.error.call_args_list))

    def test_it_asks_first_and_says_that_it_changes_nothing(self):
        self.processor.load("")

        question = self.processor.confirmation()

        self.assertIn("(2)", question.text)
        self.assertIn("Nic se nemění", question.text)
        self.assertIn("1,5 s", question.text)

    def test_the_processor_is_registered(self):
        processor = ProcessorFactory.create_processor("player_playback_check", MagicMock(), "https://x", "u", "p", MagicMock())

        self.assertIsInstance(processor, PlayerPlaybackCheckProcessor)


class ServerApiTest(unittest.TestCase):
    def api(self, answer):
        api = ServerApi.__new__(ServerApi)
        api._make_request = MagicMock(return_value=answer)
        return api

    def test_the_age_of_a_process_is_read_as_ps_writes_it(self):
        self.assertEqual([parse_etime(text) for text in ("00:07", "02:18:35", "1-02:03:04", "x", "")],
                         [7, 8315, 93784, None, None])

    def test_the_file_of_a_video_player_is_read_with_the_spaces_of_its_name(self):
        line = ("      00:07 omxplayer.bin /usr/bin/omxplayer.bin --orientation 0 --win 0 0 1920 1080 --vol -3999 "
                "--no-osd -o hdmi /home/pi/media/8169_MBS _new_CCW.mp4 -n -1\n")

        self.assertEqual(parse_playback(line), [{"age": 7, "process": "omxplayer.bin", "file": "8169_MBS _new_CCW.mp4",
                                                 "loop": False}])
        self.assertTrue(parse_playback(line.rstrip("\n") + " --loop\n")[0]["loop"])
        self.assertEqual(parse_playback(""), [])
        self.assertEqual(parse_playback("garbage without an age\n"), [])

    def test_the_command_is_fixed_and_only_lists_processes(self):
        api = self.api({"data": {"err": None, "stdout": "00:07 mpv mpv /home/pi/media/a.mp4\n", "stderr": ""}})

        self.assertEqual(api.read_player_playback("pid")[0]["process"], "mpv")
        self.assertEqual(api._make_request.call_args.kwargs["json"], {"cmd": PLAYER_PLAYBACK_COMMAND})
        self.assertTrue(PLAYER_PLAYBACK_COMMAND.startswith("ps "))
        for forbidden in (";", "&&", ">", "kill", "rm "):
            self.assertNotIn(forbidden, PLAYER_PLAYBACK_COMMAND)

    def test_no_process_is_an_empty_answer_and_not_an_error(self):
        api = self.api({"data": {"err": None, "stdout": "", "stderr": ""}})

        self.assertEqual(api.read_player_playback("pid"), [])

    def test_the_playlists_without_a_video_are_those_with_no_video_in_a_row_or_a_zone(self):
        api = self.api(None)
        api._playlist_objects = MagicMock(return_value=[
            {"name": "Images", "assets": [{"filename": "a.JPG"}, {"filename": "b.png"}]},
            {"name": "Video", "assets": [{"filename": "a.jpg"}, {"filename": "c.MP4"}]},
            {"name": "ZoneVideo", "assets": [{"filename": "a.jpg", "side": "z.mov"}]},
            {"name": "TV_OFF", "assets": []}, {"name": "NoRows"}])

        self.assertEqual(api.get_playlists_without_video(), {"Images", "TV_OFF", "NoRows"})


class ActionTest(MainWindowCase):
    def test_the_action_is_in_the_blue_block_with_an_optional_input(self):
        self.assertEqual(action_kind("set_player_playback_check"), "change")
        self.assertTrue(action_needs_input("set_player_playback_check"))
        self.assertTrue(action_input_optional("set_player_playback_check"))

    def test_the_action_is_offered_among_the_players_and_starts_with_an_empty_input(self):
        self.app.entity_type_var.set("Players")
        self.app.update_action_selection()
        label = next(label for label, key in self.app.entity_actions["Players"].items()
                     if key == "set_player_playback_check")
        self.assertIn(label, self.app.option_choose_action["values"])
        self.assertEqual(label, "Kontrola přehrávání")

        with patch.object(self.app, "open_action_log_box") as opened:
            self.app.perform_set_action("set_player_playback_check", "https://x", "u", "p", None)

        opened.assert_called_once_with("player_playback_check", "https://x", "u", "p", "")


if __name__ == "__main__":
    unittest.main()
