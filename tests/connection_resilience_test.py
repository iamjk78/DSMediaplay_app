"""A lost connection in the middle of a batch: a request whose connection could not be made is tried again, what is
still wrong is said in words (not as a dump of the error of the library), and a batch that stops says how far it got and
what is left. Between the steps of a batch there is a short pause, which STOP cuts short."""
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import requests
import urllib3.exceptions

from api_testing import request_calls
from api_testing.request_calls import CONNECT_RETRY_DELAYS, ResponseError, never_reached_the_server
from destructive_actions_test import make_processor
from log_problems_test import LogCase
from processor.input_processing import (INTERRUPTED_LIST_LIMIT, InternalException, PlayerGroupProcessor)
from server_requests_test import make_api


def connection_refused():
    reason = urllib3.exceptions.NewConnectionError(None, "refused")
    return requests.exceptions.ConnectionError(urllib3.exceptions.MaxRetryError(None, "/x", reason=reason))


def connect_timed_out():
    return requests.exceptions.ConnectTimeout(
        urllib3.exceptions.MaxRetryError(None, "/x", reason=urllib3.exceptions.ConnectTimeoutError(None, "slow")))


class NeverReachedTheServerTest(unittest.TestCase):
    def test_a_connection_that_could_not_be_made_is_one_the_server_never_saw(self):
        for label, error in (("connect timeout", requests.exceptions.ConnectTimeout()),
                             ("a library connect timeout", connect_timed_out()),
                             ("refused or unresolved", connection_refused())):
            with self.subTest(label):
                self.assertTrue(never_reached_the_server(error))

    def test_anything_that_may_have_been_sent_is_not(self):
        reset = urllib3.exceptions.ProtocolError("reset by peer")
        for label, error in (("read timeout", requests.exceptions.ReadTimeout()),
                             ("a plain timeout", requests.exceptions.Timeout()),
                             ("a lost connection", requests.exceptions.ConnectionError("reset")),
                             ("a connection reset", requests.exceptions.ConnectionError(
                                 urllib3.exceptions.MaxRetryError(None, "/x", reason=reset))),
                             ("a failed handshake", requests.exceptions.SSLError()),
                             ("another error", requests.exceptions.HTTPError())):
            with self.subTest(label):
                self.assertFalse(never_reached_the_server(error))


@patch("api_testing.request_calls.time.sleep")
class RetryTest(unittest.TestCase):
    def test_two_failed_connections_and_then_an_answer_are_one_successful_request(self, sleep):
        api = make_api()
        api._request.side_effect = [connect_timed_out(), connection_refused(), api._request.return_value]

        self.assertTrue(api._make_request("get", "/groups")["success"])

        self.assertEqual(api._request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], list(CONNECT_RETRY_DELAYS))

    def test_a_writing_request_is_repeated_too_because_nothing_of_it_was_sent(self, sleep):
        api = make_api()
        api._request.side_effect = [connect_timed_out(), api._request.return_value]

        api._make_request("post", "/groups/1", json={"a": 1})

        self.assertEqual(api._request.call_count, 2)
        self.assertEqual(api._request.call_args_list[0], api._request.call_args_list[1])

    def test_a_server_that_stays_away_ends_in_the_error_after_the_last_try(self, sleep):
        api = make_api()
        api._request.side_effect = connect_timed_out()

        with self.assertRaises(requests.exceptions.ConnectTimeout):
            api._make_request("get", "/groups")

        self.assertEqual(api._request.call_count, len(CONNECT_RETRY_DELAYS) + 1)
        self.assertEqual(sleep.call_count, len(CONNECT_RETRY_DELAYS))

    def test_what_may_have_been_sent_is_never_sent_again(self, sleep):
        for method in ("get", "post"):
            for error in (requests.exceptions.ReadTimeout(), requests.exceptions.ConnectionError("reset"),
                          requests.exceptions.Timeout()):
                with self.subTest(method=method, error=type(error).__name__):
                    api = make_api()
                    api._request.side_effect = error
                    with self.assertRaises(type(error)):
                        api._make_request(method, "/groups")
                    self.assertEqual(api._request.call_count, 1)
        sleep.assert_not_called()

    def test_an_answer_of_the_server_is_never_a_reason_to_try_again(self, sleep):
        for status in (400, 404, 500, 503):
            with self.subTest(status=status):
                api = make_api(status=status)
                with self.assertRaises(ResponseError):
                    api._make_request("get", "/groups")
                self.assertEqual(api._request.call_count, 1)
        sleep.assert_not_called()

    def test_an_error_that_is_not_about_the_connection_is_raised_at_once(self, sleep):
        api = make_api()
        api._request.side_effect = RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            api._make_request("get", "/groups")

        self.assertEqual(api._request.call_count, 1)

    def test_a_request_that_works_does_not_wait(self, sleep):
        make_api()._make_request("get", "/groups")

        sleep.assert_not_called()

    def test_the_waiting_is_short_enough_not_to_hang_a_batch(self, sleep):
        self.assertLessEqual(sum(CONNECT_RETRY_DELAYS), 10)
        self.assertEqual(request_calls.CONNECT_RETRY_DELAYS, (2, 5))


class InterruptedBatchTest(unittest.TestCase):
    DATA = {"p1": "g1", "p2": "g1", "p3": "g2"}

    def run_batch(self, error, data=None, real_text=True):
        server = MagicMock()
        server.set_group_to_player.side_effect = [{"data": {"name": "p1"}}, error] + [error] * 100
        processor, logger, patcher = make_processor(PlayerGroupProcessor, server, real_text=real_text)
        self.addCleanup(patcher.stop)
        processor.data = dict(self.DATA if data is None else data)
        with self.assertRaises(InternalException):
            list(processor.run())
        return [call.args[0] for call in logger.error.call_args_list], logger

    def test_a_lost_connection_is_said_in_words_and_without_the_address(self):
        errors, _ = self.run_batch(connect_timed_out())

        self.assertIn("Server neodpovídá", errors[0])
        self.assertNotIn("HTTPSConnectionPool", " ".join(errors))
        self.assertNotIn("Max retries", " ".join(errors))

    def test_it_says_how_far_it_got_and_what_is_left(self):
        errors, logger = self.run_batch(connect_timed_out())

        self.assertEqual(errors[1], "Přerušeno po 1 z 3 krocích. Nezpracováno nebo nepotvrzeno (2): p2, p3")
        self.assertEqual(logger.info.call_count, 1)  # what was done before it stopped is reported as it was

    def test_each_kind_of_lost_connection_has_its_own_text(self):
        for error, text in ((requests.exceptions.ConnectTimeout(), "nepodařilo se s ním navázat spojení"),
                            (requests.exceptions.ReadTimeout(), "neodpověděl včas"),
                            (requests.exceptions.ConnectionError("reset"), "Spojení se serverem se přerušilo")):
            with self.subTest(error=type(error).__name__):
                errors, _ = self.run_batch(error)
                self.assertIn(text, errors[0])

    def test_any_other_error_is_still_reported_as_it_was(self):
        errors, _ = self.run_batch(RuntimeError("boom"))

        self.assertEqual(errors[0], "Interní chyba: boom")
        self.assertIn("Přerušeno po 1 z 3 krocích", errors[1])

    def test_a_long_list_of_what_is_left_is_cut_and_the_rest_counted(self):
        data = {f"player{number:02d}": "g" for number in range(INTERRUPTED_LIST_LIMIT + 10)}

        errors, _ = self.run_batch(connect_timed_out(), data)

        left = len(data) - 1
        self.assertIn(f"({left})", errors[1])
        self.assertIn("player01", errors[1])
        self.assertIn(f"player{INTERRUPTED_LIST_LIMIT:02d}", errors[1])
        self.assertNotIn(f"player{INTERRUPTED_LIST_LIMIT + 1:02d}", errors[1])
        self.assertIn(f"a dalších {left - INTERRUPTED_LIST_LIMIT}", errors[1])

    def test_the_english_texts_exist(self):
        server = MagicMock()
        server.set_group_to_player.side_effect = [{"data": {"name": "p1"}}, connect_timed_out()]
        processor, logger, patcher = make_processor(PlayerGroupProcessor, server, real_text=True)
        self.addCleanup(patcher.stop)
        processor.lang.set_language("en")
        processor.data = dict(self.DATA)

        with self.assertRaises(InternalException):
            list(processor.run())

        errors = [call.args[0] for call in logger.error.call_args_list]
        self.assertIn("The server does not answer", errors[0])
        self.assertEqual(errors[1], "Interrupted after 1 of 3 steps. Not done or not confirmed (2): p2, p3")

    def test_without_a_dict_of_steps_nothing_is_listed_and_nothing_breaks(self):
        processor, logger, patcher = make_processor(PlayerGroupProcessor, MagicMock(), real_text=True)
        self.addCleanup(patcher.stop)
        processor.data = ["a", "b"]

        processor._write_interrupted(1)

        logger.error.assert_not_called()


class StepPauseTest(LogCase):
    @staticmethod
    def steps(count):
        processor = MagicMock()
        processor.confirmation.return_value = None
        processor.run.return_value = iter([None] * count)
        return processor

    def timed(self, processor, processor_type="group_rename", **kwargs):
        started = time.monotonic()
        box = self.run_box(processor, data="a\tb", processor_type=processor_type, **kwargs)
        return time.monotonic() - started, box

    def test_there_is_a_tenth_of_a_second_between_the_steps(self):
        self.assertEqual(gui_log_box().STEP_PAUSE_SECONDS, 0.1)

    def test_every_step_is_followed_by_the_pause(self):
        with patch("gui_app.log_box.STEP_PAUSE_SECONDS", 0.25):
            elapsed, _ = self.timed(self.steps(4))

        self.assertGreaterEqual(elapsed, 4 * 0.25)

    def test_the_deploys_pace_themselves_and_get_no_pause_of_this_kind(self):
        with patch("gui_app.log_box.STEP_PAUSE_SECONDS", 0.5):
            elapsed, _ = self.timed(self.steps(4), processor_type="deploy_all_players")

        self.assertLess(elapsed, 4 * 0.5)

    def test_stop_ends_the_pause_at_once_and_the_log_says_where_it_stopped(self):
        stop_later = lambda box: threading.Timer(0.3, box.thread_manager.stop_event.set).start()  # noqa: E731
        with patch("gui_app.log_box.STEP_PAUSE_SECONDS", 20):
            elapsed, box = self.timed(self.steps(5), on_ready=stop_later)

        self.assertLess(elapsed, 5)
        self.assertIn("zastaven", self.text(box).lower())
        self.assertIn("po 1", self.text(box))

    def test_a_batch_without_steps_does_not_wait(self):
        with patch("gui_app.log_box.STEP_PAUSE_SECONDS", 2):
            elapsed, _ = self.timed(self.steps(0))

        self.assertLess(elapsed, 2)


def gui_log_box():
    from gui_app import log_box
    return log_box


if __name__ == "__main__":
    unittest.main()
