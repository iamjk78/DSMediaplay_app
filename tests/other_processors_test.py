"""The actions that had no test at all: creating and renaming things, deleting what is unused, updating players,
cloning their details and taking the additional playlists away."""
import unittest
from unittest.mock import MagicMock, patch

from destructive_actions_test import make_processor
from pasted_playlists_test import ProcessorCase, line
from processor.input_processing import (CreateGroupProcessor, CreateLabelProcessor, CreateLocationProcessor, FormatException,
                                        CreatePlayerProcessor, CreatePlaylistProcessor,
                                        DeleteAdditionalPlaylistProcessor, LocationRenameProcessor,
                                        PlayerDetailsCloneProcessor, PlayerRenameProcessor, PlayerUpdateProcessor,
                                        PlaylistRenameProcessor, RemoveExpiredPlaylistsProcessor, RemovePlaylistsByListProcessor, RemoveAllUnusedAssetsProcessor,
                                        RemoveAllUnusedGroupsProcessor, RemoveAllUnusedLabelsProcessor,
                                        RemoveAllUnusedLocationsProcessor, RemoveAllUnusedPlaylistsProcessor)

CREATES = (  # the action, how the server lists what exists, how it creates
    (CreateLocationProcessor, "get_location_names", "create_location"),
    (CreatePlayerProcessor, "get_player_names", "create_player"),
    (CreatePlaylistProcessor, "get_playlist_names", "create_playlist"),
    (CreateLabelProcessor, "get_labels", "create_label"),
    (CreateGroupProcessor, "get_group_names", "create_group"),
)


class CreateTest(ProcessorCase):
    @staticmethod
    def reported(logger, level, key):
        return sum(call.args[0] == key for call in getattr(logger, level).call_args_list)

    def make(self, processor_class, listing, existing=("Old",), real_text=False):
        getattr(self.server, listing).return_value = list(existing)
        return make_processor(processor_class, self.server, real_text=real_text)

    def load(self, processor_class, listing, text, existing=("Old",), real_text=False):
        processor, logger, patcher = self.make(processor_class, listing, existing, real_text)
        self.addCleanup(patcher.stop)
        try:
            processor.load(text)
            processor.refused = False
        except Exception as error:
            processor.refused = type(error).__name__ == "FormatException"
            if not processor.refused:
                raise
        return processor, logger

    def test_new_names_are_taken_in_the_order_they_were_written(self):
        for action, listing, _ in CREATES:
            with self.subTest(action=action.__name__):
                processor, _ = self.load(action, listing, "Zeta\nAlfa\n\nMika\n")

                self.assertFalse(processor.refused)
                self.assertEqual(processor.data, ["Zeta", "Alfa", "Mika"])

    def test_a_name_that_exists_or_has_what_the_server_does_not_like_is_refused(self):
        for action, listing, _ in CREATES:
            for text, key in (("Old", "not_new"), ("Škoda", "name_fail"), ("a;b", "name_fail"),
                              ("ŠKODA", "name_fail")):
                with self.subTest(action=action.__name__, text=text):
                    processor, logger = self.load(action, listing, text)

                    self.assertTrue(processor.refused)
                    self.assertIn(key, self.messages(logger) + self.messages(logger, "warning"))

    def test_a_name_written_twice_is_created_once(self):
        processor, _ = self.load(CreateGroupProcessor, "get_group_names", "New\n New \nNew")

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data, ["New"])

    def test_the_line_of_a_wrong_name_is_numbered_as_the_user_sees_it(self):
        processor, logger = self.load(CreateGroupProcessor, "get_group_names", "New\n\nOld", real_text=True)

        self.assertTrue(any("Řádek 3" in message for message in self.messages(logger)))

    def test_nothing_to_create_is_not_a_success(self):
        processor, _ = self.load(CreateGroupProcessor, "get_group_names", "\n  \n")

        self.assertTrue(processor.refused)

    def test_each_name_is_created_in_order_and_a_failure_does_not_stop_the_others(self):
        for action, listing, creating in CREATES:
            with self.subTest(action=action.__name__):
                server = MagicMock()
                getattr(server, listing).return_value = []
                create = getattr(server, creating)
                create.side_effect = [{"success": True}, RuntimeError("boom"), {"success": True}]
                processor, logger, patcher = make_processor(action, server)
                self.addCleanup(patcher.stop)
                processor.load("One\nTwo\nThree")

                list(processor.run())

                self.assertEqual([call.args[0] for call in create.call_args_list], ["One", "Two", "Three"])
                self.assertEqual(self.reported(logger, "info", "success_create"), 2)
                self.assertEqual(logger.error.call_count, 1)  # the one that failed


RENAMES = (  # the action, how the server lists what exists, how it renames, a good new name, a bad one
    (PlayerRenameProcessor, "get_player_names", "rename_player", "PB1234_", "Lobby"),
    (PlaylistRenameProcessor, "get_playlist_names", "rename_playlist", "Promo2026", "Promo 2026"),
    (LocationRenameProcessor, "get_location_names", "rename_location", "Hall2", "Hall 2"),
)


class RenameTest(ProcessorCase):
    def start(self, action, listing, existing=("Old", "Other")):
        getattr(self.server, listing).return_value = list(existing)
        processor, logger, patcher = make_processor(action, self.server)
        self.addCleanup(patcher.stop)
        return processor, logger

    def test_a_good_new_name_is_taken_and_a_bad_one_refused(self):
        for action, listing, _, good, bad in RENAMES:
            with self.subTest(action=action.__name__):
                processor, logger = self.start(action, listing)
                processor.load(line("Old", good))
                self.assertEqual(processor.data, {"Old": good})

                processor, logger = self.start(action, listing)
                with self.assertRaises(Exception) as caught:
                    processor.load(line("Old", bad))
                self.assertEqual(type(caught.exception).__name__, "FormatException")

    def test_a_name_that_is_taken_already_is_refused_as_a_new_name(self):
        for action, listing, _, good, _ in RENAMES:
            with self.subTest(action=action.__name__):
                processor, logger = self.start(action, listing, existing=("Old", good))

                with self.assertRaises(Exception) as caught:
                    processor.load(line("Old", good))

                self.assertEqual(type(caught.exception).__name__, "FormatException")

    def test_an_old_name_that_is_not_there_is_refused(self):
        for action, listing, _, good, _ in RENAMES:
            with self.subTest(action=action.__name__):
                processor, logger = self.start(action, listing)

                with self.assertRaises(Exception) as caught:
                    processor.load(line("Nobody", good))

                self.assertEqual(type(caught.exception).__name__, "FormatException")

    def test_the_server_is_asked_to_rename_each_one(self):
        for action, listing, renaming, good, _ in RENAMES:
            with self.subTest(action=action.__name__):
                server = MagicMock()
                getattr(server, listing).return_value = ["Old"]
                getattr(server, renaming).side_effect = lambda old, new: {"data": {"name": new}}
                processor, logger, patcher = make_processor(action, server)
                self.addCleanup(patcher.stop)
                processor.load(line("Old", good))

                list(processor.run())

                getattr(server, renaming).assert_called_once_with("Old", good)
                logger.info.assert_called_with("success_rename")


class PlayerRenameRulesTest(ProcessorCase):
    PLAYERS = ("abc_PB3434_aktivni", "stary player", "RPI001", "no identifier")

    def load_rename(self, *rows):
        self.server.get_player_names.return_value = list(self.PLAYERS)
        return self.load(PlayerRenameProcessor, "\n".join(line(*row) for row in rows))

    def test_the_identifier_has_to_be_followed_by_an_underscore(self):
        for new_name, accepted in (("x_PB3434_y", True), ("PB3434_", True), ("x_PB3434", False), ("PB3434", False),
                                   ("x_RPI001_", True), ("x_rpi001_", True), ("x_RPI001", False)):
            with self.subTest(new_name=new_name):
                processor, logger = self.load_rename(("no identifier", new_name))
                self.assertEqual(processor.refused, not accepted)
                if not accepted:
                    self.assertEqual(self.messages(logger)[0], "invalid_player_name")

    def test_the_identifier_of_the_old_name_cannot_be_changed(self):
        for new_name in ("abc_PB3455_aktivni", "abc_PC3434_aktivni", "abc_RPI001_x", "abc_PB3434_PB3434_PB9999_"):
            with self.subTest(new_name=new_name):
                processor, logger = self.load_rename(("abc_PB3434_aktivni", new_name))
                self.assertTrue(processor.refused)
                self.assertEqual(self.messages(logger)[0], "player_identifier_changed")
                self.assertEqual(processor.data, {})

    def test_the_rest_of_the_name_can_change_when_the_identifier_stays(self):
        processor, _ = self.load_rename(("abc_PB3434_aktivni", "Praha_PB3434_lobby"), ("RPI001", "RPI001_Brno"))
        self.assertFalse(processor.refused)
        self.assertEqual(processor.data, {"abc_PB3434_aktivni": "Praha_PB3434_lobby", "RPI001": "RPI001_Brno"})

    def test_forbidden_characters_are_refused_in_the_new_name_only(self):
        for new_name in ("a b_PB3434_", 'a"b_PB3434_', "a,b_PB3434_", "a;b_PB3434_"):
            with self.subTest(new_name=new_name):
                processor, logger = self.load_rename(("no identifier", new_name))
                self.assertTrue(processor.refused)
                self.assertEqual(self.messages(logger)[0], "invalid_player_name")

        processor, _ = self.load_rename(("stary player", "new_PB1234_"))  # a space in the old name is not a reason
        self.assertFalse(processor.refused)

    def test_an_old_name_given_twice_is_refused_and_the_line_numbers_are_those_of_the_input(self):
        text = line("abc_PB3434_aktivni", "x_PB3434_") + "\n\n" + line("abc_PB3434_aktivni", "y_PB3434_")
        self.server.get_player_names.return_value = list(self.PLAYERS)
        processor, logger, patcher = make_processor(PlayerRenameProcessor, self.server)
        self.addCleanup(patcher.stop)
        processor.lang.get_message.side_effect = lambda key, **kw: (key, kw.get("line_number"))

        with self.assertRaises(FormatException):
            processor.load(text)

        self.assertIn(("collision", 3), self.messages(logger, "warning"))


UNUSED = (  # the action, how the server lists what is unused
    (RemoveAllUnusedGroupsProcessor, "get_unused_groups"),
    (RemoveAllUnusedLocationsProcessor, "get_unused_locations"),
    (RemoveAllUnusedPlaylistsProcessor, "get_unused_playlists"),
    (RemoveAllUnusedLabelsProcessor, "get_unused_labels"),
    (RemoveAllUnusedAssetsProcessor, "get_unused_assets"),
)


class RemoveAllUnusedTest(unittest.TestCase):
    def test_what_the_server_reports_as_unused_is_what_is_to_go(self):
        for action, listing in UNUSED:
            with self.subTest(action=action.__name__):
                server = MagicMock()
                getattr(server, listing).return_value = ["a", "b"]
                processor, logger, patcher = make_processor(action, server)
                self.addCleanup(patcher.stop)

                processor.load("")

                self.assertEqual(processor.data, ["a", "b"])

    def test_when_nothing_is_unused_it_says_so_instead_of_blaming_the_server(self):
        for action, listing in UNUSED:
            with self.subTest(action=action.__name__):
                server = MagicMock()
                getattr(server, listing).return_value = []
                processor, logger, patcher = make_processor(action, server)
                self.addCleanup(patcher.stop)

                processor.load("")

                logger.warning.assert_called_once_with("nothing_unused")
                self.assertFalse(processor.data)
                self.assertIsNone(processor.confirmation())  # nothing to be asked about


class PlayerUpdateTest(ProcessorCase):
    def start(self, text="P1\nP2", **options):
        self.server.get_player_names.return_value = ["P1", "P2", "P3"]
        processor, logger, patcher = make_processor(PlayerUpdateProcessor, self.server, **options)
        self.addCleanup(patcher.stop)
        sleeping = patch("processor.input_processing.sleep")
        sleeping.start()
        self.addCleanup(sleeping.stop)
        processor.load(text)
        return processor, logger

    def test_the_players_are_taken_in_the_order_written_and_an_unknown_one_is_refused(self):
        processor, _ = self.start("P2\nP1")
        self.assertEqual(processor.data, ["P2", "P1"])

        with self.assertRaises(Exception) as caught:
            self.start("P1\nNobody")
        self.assertEqual(type(caught.exception).__name__, "FormatException")

    def test_each_player_gets_the_watchdog_stopped_and_then_the_update(self):
        processor, logger = self.start()

        list(processor.run())

        calls = [(c[0], c.args[0]) for c in self.server.method_calls if c[0] in ("send_player_command", "player_update")]
        self.assertEqual(calls, [("send_player_command", "P1"), ("player_update", "P1"),
                                 ("send_player_command", "P2"), ("player_update", "P2")])
        self.assertEqual(self.server.send_player_command.call_args.args[1], "sudo systemctl stop watchdog.service")
        self.assertEqual(sum(c.args[0] == "success_update" for c in logger.info.call_args_list), 2)

    def test_a_player_that_fails_is_reported_with_the_reason_and_the_next_one_goes_on(self):
        processor, logger = self.start()
        failure = RuntimeError("no route")
        self.server.player_update.side_effect = [failure, None]

        list(processor.run())

        self.assertEqual([c.args[0] for c in logger.error.call_args_list], ["error_update"])
        self.assertEqual(sum(c.args[0] == "success_update" for c in logger.info.call_args_list), 1)
        self.assertEqual(self.server.player_update.call_count, 2)
        self.assertEqual(self.server.send_player_command.call_count, 2)

    def test_the_message_of_a_failed_update_says_what_failed(self):
        processor, logger = self.start("P1", real_text=True)
        self.server.player_update.side_effect = RuntimeError("no route")

        list(processor.run())

        self.assertIn("RuntimeError", logger.error.call_args.args[0])

    def test_a_player_whose_watchdog_could_not_be_stopped_is_not_updated(self):
        processor, logger = self.start("P1")
        self.server.send_player_command.side_effect = RuntimeError("refused")

        list(processor.run())

        self.server.player_update.assert_not_called()
        self.assertEqual(logger.error.call_count, 1)


class CloneAndAdditionalTest(ProcessorCase):
    def test_the_details_of_one_player_are_cloned_to_another_in_the_order_written(self):
        self.server.get_player_names.return_value = ["A", "B", "C"]
        self.server.clone_player_details.side_effect = lambda old, new: {"data": {"name": old}}
        processor, _, patcher = make_processor(PlayerDetailsCloneProcessor, self.server)
        self.addCleanup(patcher.stop)

        processor.load(line("B", "X") + "\n" + line("A", "Y"))
        list(processor.run())

        self.assertEqual([c.args for c in self.server.clone_player_details.call_args_list], [("B", "X"), ("A", "Y")])

    def test_a_line_without_two_names_or_with_an_unknown_player_is_refused(self):
        self.server.get_player_names.return_value = ["A"]
        for text in ("A", line("A", "X", "Z") + "\t", line("Nobody", "X")):
            with self.subTest(text=text):
                processor, _, patcher = make_processor(PlayerDetailsCloneProcessor, self.server)
                self.addCleanup(patcher.stop)

                with self.assertRaises(Exception) as caught:
                    processor.load(text)

                self.assertEqual(type(caught.exception).__name__, "FormatException")
                self.assertEqual(processor.data, {})

    def test_only_the_players_that_have_additional_playlists_are_touched(self):
        self.server.get_player_names.return_value = ["P1", "P2"]
        self.server.get_additional_playlists.return_value = [("P1", ["Extra"]), ("P2", [])]
        self.server.set_player_additional_playlist.side_effect = lambda player, playlists: {"data": {"name": player}}
        processor, _, patcher = make_processor(DeleteAdditionalPlaylistProcessor, self.server)
        self.addCleanup(patcher.stop)

        processor.load("P1\nP2")
        list(processor.run())

        self.server.set_player_additional_playlist.assert_called_once_with("P1", [])


class RemovePlaylistsByListInputTest(ProcessorCase):
    def test_a_playlist_that_does_not_exist_is_skipped_with_a_warning_not_with_a_crash(self):
        self.server.get_group_names.return_value = ["G"]
        self.server.get_playlist_names.return_value = ["Known"]
        self.server.get_groups_playlists.return_value = {"G": [("Known", None, None, None, None)]}
        processor, logger, patcher = make_processor(RemovePlaylistsByListProcessor, self.server, real_text=True)
        self.addCleanup(patcher.stop)

        processor.load("Known\nTypo\nOther typo")

        self.assertEqual(processor.data, ["Known"])
        self.assertIn("Typo, Other typo", logger.warning.call_args.args[0])


class ListOfNamesTest(ProcessorCase):
    """The base of the actions that take a list of names, one on a line (here "remove expired playlists")."""

    def setUp(self):
        super().setUp()
        self.server.get_group_names.return_value = ["G1", "G2", "G3"]

    def load(self, text, real_text=False):
        processor, logger, patcher = make_processor(RemoveExpiredPlaylistsProcessor, self.server, real_text=real_text)
        self.addCleanup(patcher.stop)
        try:
            processor.load(text)
            processor.refused = False
        except Exception as error:
            processor.refused = type(error).__name__ == "FormatException"
            if not processor.refused:
                raise
        return processor, logger

    def test_the_names_are_taken_in_the_order_written_a_repeated_one_once(self):
        processor, _ = self.load("G3\nG1\n\nG3\nG2")

        self.assertEqual(processor.data, ["G3", "G1", "G2"])

    def test_an_unknown_name_is_refused_with_the_number_of_its_line(self):
        processor, logger = self.load("G1\n\nNobody", real_text=True)

        self.assertTrue(processor.refused)
        self.assertTrue(any("Řádek 3" in call.args[0] for call in logger.warning.call_args_list))


if __name__ == "__main__":
    unittest.main()
