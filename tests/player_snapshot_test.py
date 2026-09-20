import logging
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import requests

from api_testing.request_calls import ResponseError, ServerApi, SnapshotError
from processor.input_processing import InternalException, PlayerSnapshotProcessor, ProcessorFactory
from util.language import LanguageManager

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"
JPEG = b"\xff\xd8\xff\xe0" + b"pixels"
SERVER = "https://demo.example.com"


def api() -> ServerApi:
    instance = ServerApi.__new__(ServerApi)  # no login: only what the download needs
    instance._url = f"{SERVER}/api"
    instance._assert_hostname = None
    instance._session_token = "secret-token"
    return instance


def response(content: bytes = PNG, ok: bool = True) -> MagicMock:
    result = MagicMock()
    result.ok = ok
    result.content = content
    return result


class DownloadSnapshotTest(unittest.TestCase):
    def download(self, address, **answer):
        with patch("api_testing.request_calls.requests.request", return_value=response(**answer)) as own, \
                patch("api_testing.request_calls.requests.get", return_value=response(**answer)) as foreign:
            try:
                return api().download_snapshot(address), own, foreign
            except SnapshotError as error:
                return error, own, foreign

    def test_an_image_of_the_servers_own_host_is_downloaded_with_the_token(self):
        result, own, foreign = self.download(f"{SERVER}/snapshots/a.png")

        self.assertEqual(result, (PNG, ".png"))
        self.assertEqual(own.call_args.kwargs["params"], {"token": "secret-token"})
        foreign.assert_not_called()

    def test_a_relative_address_is_resolved_against_the_server(self):
        _, own, _ = self.download("/snapshots/a.png")

        self.assertEqual(own.call_args.args[:2], ("get", f"{SERVER}/snapshots/a.png"))

    def test_the_token_never_goes_to_another_host(self):
        result, own, foreign = self.download("https://cdn.example.org/a.png")

        self.assertEqual(result, (PNG, ".png"))
        own.assert_not_called()
        self.assertNotIn("params", foreign.call_args.kwargs)
        self.assertNotIn("secret-token", str(foreign.call_args))

    def test_the_extension_follows_the_content(self):
        result, _, _ = self.download("/a", content=JPEG)

        self.assertEqual(result, (JPEG, ".jpg"))

    def test_only_https_addresses_are_followed(self):
        for address in ("http://demo.example.com/a.png", "file:///etc/passwd", "ftp://demo.example.com/a.png"):
            with self.subTest(address=address):
                result, own, foreign = self.download(address)

                self.assertEqual(result.reason, "bad_url")
                own.assert_not_called()
                foreign.assert_not_called()

    def test_something_that_is_not_an_image_is_refused(self):
        result, _, _ = self.download("/a", content=b"<html>login</html>")

        self.assertEqual(result.reason, "not_image")

    def test_a_huge_response_is_refused(self):
        with patch("api_testing.request_calls.SNAPSHOT_MAX_BYTES", 10):
            result, _, _ = self.download("/a", content=PNG + b"x" * 20)

        self.assertEqual(result.reason, "too_large")

    def test_a_failed_download_is_a_snapshot_error(self):
        result, _, _ = self.download("/a", ok=False)
        self.assertEqual(result.reason, "download")

        with patch("api_testing.request_calls.requests.request", side_effect=requests.exceptions.Timeout):
            with self.assertRaises(SnapshotError) as caught:
                api().download_snapshot("/a")
        self.assertEqual(caught.exception.reason, "download")

    def test_taking_a_snapshot_posts_to_the_players_id(self):
        instance = api()
        instance.get_player_id_by_name = MagicMock(return_value="abc123")
        instance._make_request = MagicMock(return_value={"data": {"url": "/s.png", "lastTaken": 1}})

        self.assertEqual(instance.take_player_snapshot("Lobby"), {"url": "/s.png", "lastTaken": 1})
        self.assertEqual(instance._make_request.call_args.args, ("post", "/snapshot/abc123"))


class PlayerSnapshotProcessorTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = os.path.join(self.directory.name, "snapshots")
        self.lang = LanguageManager("cz")
        self.messages = []

        class Collect(logging.Handler):
            def emit(handler, record):
                self.messages.append(record)

        logger = logging.getLogger(f"snapshot-test-{id(self)}")
        logger.handlers = [Collect()]
        logger.setLevel(logging.INFO)
        self.processor = PlayerSnapshotProcessor(logger, url=SERVER, login="l", password="p", lang=self.lang,
                                                 output_dir=self.output)
        self.server = MagicMock()
        self.server.__enter__.return_value = self.server
        self.server.take_player_snapshot.side_effect = lambda name: {"url": f"/{name}.png"}
        self.server.download_snapshot.return_value = (PNG, ".png")
        patcher = patch.object(self.processor, "_try_server_login", return_value=self.server)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_for(self, *players):
        self.processor.data = list(players)
        return list(self.processor.run())

    def saved(self):
        return sorted(os.listdir(self.output))

    def test_the_processor_is_registered_and_takes_the_output_folder(self):
        processor = ProcessorFactory.create_processor("player_snapshot", MagicMock(), SERVER, "l", "p", self.lang,
                                                      output_dir=self.output)

        self.assertIsInstance(processor, PlayerSnapshotProcessor)

    def test_every_player_gets_its_own_file_with_the_image(self):
        self.run_for("Lobby", "Bar")

        names = self.saved()
        self.assertEqual(len(names), 2)
        self.assertTrue(names[0].startswith("Bar_") and names[1].startswith("Lobby_"))
        with open(os.path.join(self.output, names[0]), "rb") as file:
            self.assertEqual(file.read(), PNG)

    def test_the_player_name_cannot_leave_the_folder(self):
        names = ("../../evil", "a/b\\c", "..", "...", "č ř ž")
        for name in names:
            with self.subTest(name=name):
                self.run_for(name)

        self.assertEqual(os.listdir(self.directory.name), ["snapshots"])
        self.assertEqual(len(self.saved()), len(names))
        self.assertTrue(all("/" not in n and "\\" not in n and not n.startswith(".") for n in self.saved()))

    def test_two_names_with_the_same_file_name_do_not_overwrite_each_other(self):
        self.run_for("a b", "a_b")

        self.assertEqual(len(self.saved()), 2)

    def test_a_failing_player_is_reported_and_the_others_are_still_done(self):
        self.server.take_player_snapshot.side_effect = [ResponseError({"params": {"token": "secret-token"}}),
                                                        {"url": "/ok.png"}]

        self.run_for("Offline", "Online")

        self.assertEqual(len(self.saved()), 1)
        self.assertTrue(self.saved()[0].startswith("Online_"))
        text = " ".join(record.getMessage() for record in self.messages)
        self.assertIn("Offline", text)
        self.assertNotIn("secret-token", text)

    def test_a_bad_image_is_reported_with_its_reason(self):
        self.server.download_snapshot.side_effect = SnapshotError("not_image")

        self.run_for("Lobby")

        self.assertEqual(self.saved(), [])
        self.assertIn(self.lang.get_message("snapshot_reason_not_image"), self.messages[-1].getMessage())

    def test_a_network_error_while_asking_is_reported_not_raised(self):
        self.server.take_player_snapshot.side_effect = requests.exceptions.ConnectionError

        self.run_for("Lobby")

        self.assertIn(self.lang.get_message("snapshot_reason_download"), self.messages[-1].getMessage())

    def test_an_unexpected_answer_without_url_is_reported(self):
        self.server.take_player_snapshot.side_effect = lambda name: {}

        self.run_for("Lobby")

        self.assertEqual(self.saved(), [])
        self.assertEqual(self.messages[-1].levelno, logging.ERROR)

    def test_an_unwritable_folder_ends_the_run_with_an_internal_error(self):
        self.processor.output_dir = os.path.join(self.directory.name, "file")
        with open(self.processor.output_dir, "w"):
            pass

        with self.assertRaises(InternalException):
            self.run_for("Lobby")

    def test_the_texts_exist_in_both_languages(self):
        for language in ("cz", "en"):
            lang = LanguageManager(language)
            with self.subTest(language=language):
                lang.get_message("snapshot_saved", player="p", path="x")
                lang.get_message("snapshot_failed", player="p", reason="r")
                for reason in ("server", "download", "bad_url", "not_image", "too_large"):
                    lang.get_message(f"snapshot_reason_{reason}")
                lang.get_message("actions.Players.set_player_snapshot")


if __name__ == "__main__":
    unittest.main()
