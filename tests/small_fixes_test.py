"""Smaller things found in the review: an error while logging out must not turn a done action into a failed one, a
server that is down is not a wrong password, the protection of "test" labels covers every case, a name that is to be
renamed twice is refused, and a typed password is not replaced by the stored one."""
import itertools
import unittest
from unittest.mock import MagicMock, patch

import requests

from api_testing.request_calls import LoginError, ResponseError, ServerApi
from destructive_actions_test import make_processor
from pasted_playlists_test import ProcessorCase, line
from processor.input_processing import (CreateGroupProcessor, FormatException, GroupRenameProcessor,
                                        RemoveProcessor)
from settings_and_log_window_test import WindowCase


def api_with(status=200, body=None):
    api = ServerApi.__new__(ServerApi)
    api._url, api._login, api._password, api._assert_hostname = "https://x/api", "l", "p", None
    reply = MagicMock()
    reply.status_code, reply.ok = status, status < 400
    reply.json.return_value = body
    api._post = MagicMock(return_value=reply)
    return api


class LoginAndLogoutTest(unittest.TestCase):
    def test_a_server_that_is_down_is_not_reported_as_a_wrong_password(self):
        for status in (500, 502, 503):
            with self.subTest(status=status):
                with self.assertRaises(ResponseError):
                    api_with(status)._get_session_token()

    def test_a_refused_login_is_still_a_wrong_password(self):
        for status, body in ((401, None), (403, None), (200, None), (200, {"nothing": 1})):
            with self.subTest(status=status, body=body):
                with self.assertRaises(LoginError):
                    api_with(status, body)._get_session_token()

    def test_a_token_is_returned(self):
        self.assertEqual(api_with(200, {"token": "abc"})._get_session_token(), "abc")

    def test_a_failed_logout_does_not_turn_the_work_done_into_an_error(self):
        api = ServerApi.__new__(ServerApi)
        api._make_request = MagicMock(side_effect=ResponseError(params={}, status=500, request="DELETE /session"))
        api._session_token = "t"

        with api:
            pass  # raised ResponseError when leaving the block

        self.assertIsNone(api._session_token)


class RetrieveNamesTest(ProcessorCase):
    def test_the_real_status_of_a_refused_request_is_reported_not_a_made_up_one(self):
        for status in (404, 500):
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status
                self.server.get_group_names.side_effect = requests.exceptions.HTTPError(response=response)
                processor, logger, patcher = make_processor(GroupRenameProcessor, self.server, real_text=True)
                self.addCleanup(patcher.stop)

                names = processor._retrieve_names(self.server, "group_names")

                self.assertIsNone(names)
                self.assertTrue(any(str(status) in call.args[0] for call in logger.error.call_args_list
                                    + logger.warning.call_args_list), logger.mock_calls)


class LoginOfAProcessorTest(ProcessorCase):
    def login_with(self, error):
        processor, logger, patcher = make_processor(GroupRenameProcessor, self.server, real_text=True)
        patcher.stop()  # the real _try_server_login, with a server class that fails
        self.addCleanup(patch.stopall)
        patch("processor.input_processing.ServerApi", side_effect=error).start()
        return processor, logger, processor._try_server_login()

    def test_the_status_of_a_refused_login_request_is_reported(self):
        for status in (404, 500):
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status

                processor, logger, server = self.login_with(requests.exceptions.HTTPError(response=response))

                self.assertIsNone(server)
                self.assertTrue(any(str(status) in call.args[0] for call in logger.error.call_args_list
                                    + logger.warning.call_args_list), logger.mock_calls)

    def test_a_server_that_is_down_is_not_reported_as_a_wrong_password(self):
        processor, logger, server = self.login_with(ResponseError(params={}, status=503, request="POST /session"))

        self.assertIsNone(server)
        self.assertTrue(any("503" in call.args[0] for call in logger.error.call_args_list + logger.warning.call_args_list))
        self.assertNotIn(processor.lang.get_message("incorrect_login"),
                         [call.args[0] for call in logger.error.call_args_list])


class TestLabelTest(unittest.TestCase):
    def test_every_way_of_writing_test_is_asked_for(self):
        asked = []

        def server_method(label):
            asked.append(label)
            return [f"entity-{label}"]

        found = RemoveProcessor.get_labeled_test(server_method)

        self.assertEqual(len(set(asked)), 16)
        for variant in ("test", "TEST", "Test", "tEsT", "teST", "TeSt"):
            self.assertIn(f"entity-{variant}", found)
        self.assertEqual({a.lower() for a in asked}, {"test"})
        self.assertEqual(len(list(itertools.product("01", repeat=4))), len(set(asked)))


class RenameInputTest(ProcessorCase):
    def load(self, text, real_text=False):
        return super().load(GroupRenameProcessor, text, real_text)

    def test_two_new_names_for_one_group_are_refused_instead_of_a_random_one_winning(self):
        processor, logger = self.load(line("G1", "First") + "\n" + line("G1", "Second"))

        self.assertTrue(processor.refused)
        self.assertIn("collision", self.messages(logger, "warning"))

    def test_a_clean_rename_is_taken_and_the_line_is_numbered_as_the_user_sees_it(self):
        processor, _ = self.load(line("G1", "First") + "\n" + line("G2", "Second"))

        self.assertFalse(processor.refused)
        self.assertEqual(processor.data, {"G1": "First", "G2": "Second"})
        processor, logger = self.load(line("G1", "ok") + "\n\n" + line("G2", "bad name"), real_text=True)
        self.assertTrue(any("3" in message for message in self.messages(logger)))


class CreateNameTest(ProcessorCase):
    def test_the_characters_the_server_does_not_like_are_refused_in_capitals_too(self):
        for name in ("Ěkoun", "ŠKODA", "Čaj", "Řeka", "Žába", "Ýgrek", "Álfa", "Ídol", "Éra", "ěkoun", "a;b"):
            with self.subTest(name=name):
                self.server.get_group_names.return_value = []
                processor, logger, patcher = make_processor(CreateGroupProcessor, self.server)
                self.addCleanup(patcher.stop)
                try:
                    processor.load(name)
                    refused = False
                except FormatException:
                    refused = True

                self.assertTrue(refused)

    def test_an_ordinary_name_is_taken(self):
        self.server.get_group_names.return_value = []
        processor, _, patcher = make_processor(CreateGroupProcessor, self.server)
        self.addCleanup(patcher.stop)

        processor.load("Shop_1")

        self.assertEqual(list(processor.data), ["Shop_1"])


class TypedPasswordTest(WindowCase):
    def setUp(self):
        super().setUp()
        self.app.all_data["logins"]["Demo"] = {"url": "https://x.example.com", "names": {"jane": {"login": "jane"}}}
        self.app.account_data = self.app.all_data["logins"]
        self.app.save_account_configs()
        self.app.option_choose_administration.set("Demo")
        self.app.fill_login_details()
        self.app.option_choose_name.set("jane")

    def change_the_file_from_outside(self):
        data = self.saved()
        data["logins"]["Other"] = {"url": "https://y.example.com", "names": {}}
        with open(self.config, "w", encoding="utf-8") as file:
            import json
            json.dump(data, file)

    def test_a_password_being_typed_survives_the_config_being_changed_outside(self):
        self.app.input_for_password.insert(0, "typed-now")
        self.change_the_file_from_outside()

        self.assertTrue(self.app.sync_from_disk())

        self.assertEqual(self.app.input_for_password.get(), "typed-now")
        self.assertIn("Other", self.app.account_data)

    def test_the_stored_password_is_shown_when_nothing_is_typed_and_when_the_login_changes(self):
        from unittest.mock import patch
        with patch("gui_app.gui.credentials.get_password", return_value="stored"):
            self.app.fill_password_details()
            self.assertEqual(self.app.input_for_password.get(), "stored")
            self.app.input_for_password.delete(0, "end")
            self.change_the_file_from_outside()
            self.app.sync_from_disk()
            self.assertEqual(self.app.input_for_password.get(), "stored")  # nothing typed: the stored one

            self.app.input_for_password.delete(0, "end")
            self.app.input_for_password.insert(0, "typed")
            self.app.option_choose_name.set("")
            self.app.fill_password_details()  # the person chose another login: that one's password
            self.assertEqual(self.app.input_for_password.get(), "")


if __name__ == "__main__":
    unittest.main()
