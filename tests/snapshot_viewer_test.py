import builtins
import gc
import glob
import json
import os
import re
import tempfile
import threading
import time
import tkinter as tk
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from api_testing.request_calls import LoginError, ResponseError, SnapshotError
from gui_app import gui
from gui_app.tooltip import Tooltip
from gui_app.snapshot_viewer import (DEFAULT_WINDOW_SIZE, LIVE_INTERVALS, MIN_REQUEST_INTERVAL, SnapshotSlots,
                                     SnapshotViewer, ask_save_path, valid_window_size)
from util.language import LanguageManager


def png(size=(64, 36), color="red") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


RED, BLUE = png(color="red"), png(size=(32, 32), color="blue")


class ViewerTestCase(unittest.TestCase):
    def setUp(self):
        # Tk variables left over from earlier tests are freed by whichever thread the collector happens to run in;
        # in a worker thread that call waits for the main loop for a second each time. So they are freed here.
        gc.collect()
        self.addCleanup(gc.collect)
        self.clock = [500.0]
        clock_patch = patch("gui_app.snapshot_viewer._clock", lambda: self.clock[0])
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = os.path.join(self.directory.name, "logins.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
        try:
            self.app = gui.DSMediaplayApp(path)
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.app.destroy)
        self.app.update()

    def open(self, fetch=None, slots=None, ask_path=None, wait=True, **options) -> SnapshotViewer:
        kwargs = {"ask_path": ask_path, **options} if ask_path else dict(options)
        viewer = SnapshotViewer(self.app, player_name="Lobby 1", player_id="id-1",
                                credentials=("https://demo.example.com", "jane", "pw"),
                                slots=slots or SnapshotSlots(), font=("Helvetica", 12),
                                fetch=fetch or MagicMock(return_value=(RED, ".png")), **kwargs)
        self.addCleanup(lambda: viewer.winfo_exists() and viewer.destroy())
        if wait:
            self.wait_for(lambda: not viewer.busy)
        return viewer

    def wait_for(self, condition, seconds=5):
        end = time.monotonic() + seconds
        while not condition() and time.monotonic() < end:
            self.app.update()
            time.sleep(0.01)
        self.assertTrue(condition(), "timed out")

    @staticmethod
    def blocking_fetch(image=RED):
        """A fetch that returns only when the test lets it; `calls` says how often it was asked."""
        release = threading.Event()
        calls = []

        def fetch(*args):
            calls.append(args)
            release.wait(5)
            return image, ".png"
        return fetch, release, calls


class TakingSnapshotsTest(ViewerTestCase):
    def test_a_snapshot_is_taken_when_the_window_opens_and_shown(self):
        fetch = MagicMock(return_value=(RED, ".png"))
        viewer = self.open(fetch)

        fetch.assert_called_once_with("https://demo.example.com", "jane", "pw", "id-1")
        self.assertTrue(viewer.has_image)
        self.assertEqual(viewer.title(), "Snímek - Lobby 1")
        self.assertIn("Snímek pořízen v", viewer.status_var.get())
        self.assertTrue(viewer.canvas.find_all())
        self.assertFalse(viewer.busy)

    def test_how_long_it_took_is_shown(self):
        def slow(*_):
            self.clock[0] += 3.24
            return RED, ".png"
        viewer = self.open(slow)

        self.assertIn("získání snímku trvalo 3,2 s", viewer.status_var.get())

    def test_the_duration_uses_a_decimal_point_in_english(self):
        self.app.lang.set_language("en")
        self.addCleanup(self.app.lang.set_language, "cz")

        def slow(*_):
            self.clock[0] += 1.5
            return RED, ".png"
        viewer = self.open(slow)

        self.assertIn("1.5 s", viewer.status_var.get())

    def test_a_new_snapshot_replaces_the_previous_one_in_memory(self):
        fetch = MagicMock(side_effect=[(RED, ".png"), (BLUE, ".png")])
        viewer = self.open(fetch)
        first = viewer._image

        viewer.take_snapshot()
        self.wait_for(lambda: not viewer.busy)

        self.assertEqual(viewer._raw, BLUE)
        self.assertEqual(viewer._image.size, (32, 32))
        self.assertIsNot(viewer._image, first)
        self.assertEqual(len(viewer.canvas.find_all()), 1)

    def test_nothing_is_written_to_the_disk_while_snapshots_are_taken(self):
        real_open = builtins.open
        written = []

        def watching_open(file, mode="r", *args, **kwargs):
            if any(letter in str(mode) for letter in "wxa+"):
                written.append(file)
            return real_open(file, mode, *args, **kwargs)
        with patch("builtins.open", watching_open):
            viewer = self.open(MagicMock(side_effect=[(RED, ".png"), (BLUE, ".png")]))
            viewer.take_snapshot()
            self.wait_for(lambda: not viewer.busy)
            viewer.destroy()

        self.assertEqual(written, [])

    def test_only_one_snapshot_at_a_time_and_the_button_says_so(self):
        fetch, release, calls = self.blocking_fetch()
        viewer = self.open(fetch, wait=False)
        self.wait_for(lambda: len(calls) == 1)

        self.assertTrue(viewer.busy)
        self.assertIn("disabled", viewer.retake_button.state())
        self.assertEqual(viewer.status_var.get(), "Pořizuji snímek...")
        viewer.take_snapshot()
        self.app.update()
        self.assertEqual(len(calls), 1)

        release.set()
        self.wait_for(lambda: not viewer.busy)
        self.assertNotIn("disabled", viewer.retake_button.state())

    def test_a_tooltip_showing_on_the_retake_button_closes_when_it_is_disabled(self):
        """
        A disabled widget cannot be relied on to still say when the pointer leaves it, so a tooltip that happened
        to be showing is closed the moment the button is disabled, instead of possibly lingering on screen.
        """
        viewer = self.open(MagicMock(return_value=(RED, ".png")))
        tooltip = viewer.retake_button.tooltip
        fetch, release, calls = self.blocking_fetch()
        viewer._fetch = fetch
        with patch.object(Tooltip, "_pointer_over_widget", lambda self: True):
            viewer.retake_button.event_generate("<Enter>")
            self.wait_for(lambda: tooltip._window is not None and tooltip._window.state() == "normal", seconds=2)

            viewer.take_snapshot()
            self.wait_for(lambda: len(calls) == 1)

            self.assertEqual(tooltip._window.state(), "withdrawn")

        release.set()
        self.wait_for(lambda: not viewer.busy)

    def test_an_image_that_cannot_be_read_is_an_error(self):
        viewer = self.open(MagicMock(return_value=(b"\x89PNG\r\n\x1a\nnot really", ".png")))

        self.assertFalse(viewer.has_image)
        self.assertIn("server nevrátil obrázek", viewer.status_var.get())

    def test_a_failure_shows_the_reason_and_keeps_the_last_image(self):
        viewer = self.open(MagicMock(side_effect=[(RED, ".png"), SnapshotError("download")]))
        viewer.take_snapshot()
        self.wait_for(lambda: not viewer.busy)

        self.assertIn("Snímek se nepodařilo pořídit: obrázek se nepodařilo stáhnout", viewer.status_var.get())
        self.assertEqual(str(viewer._status_label.cget("foreground")), "#c62828")
        self.assertEqual(viewer._raw, RED)

    def test_the_reasons_of_the_other_failures(self):
        for error, text in ((LoginError(), "Přihlašovací údaje nejsou platné."),
                            (requests_error(), "Chyba internetového připojení."),
                            (ResponseError({"params": {"token": "secret-token"}}), "player je pravděpodobně offline")):
            with self.subTest(error=type(error).__name__):
                viewer = self.open(MagicMock(side_effect=error))
                self.assertIn(text, viewer.status_var.get())
                self.assertNotIn("secret-token", viewer.status_var.get())
                viewer.destroy()

    def test_a_working_snapshot_after_a_failure_clears_the_error_colour(self):
        viewer = self.open(MagicMock(side_effect=[SnapshotError("download"), (RED, ".png")]))
        viewer.take_snapshot()
        self.wait_for(lambda: not viewer.busy)

        self.assertNotEqual(str(viewer._status_label.cget("foreground")), "#c62828")


def requests_error():
    import requests
    return requests.exceptions.ConnectionError("secret-token")


class ScalingTest(ViewerTestCase):
    """The image follows the size of the window and keeps its proportions (400 x 200 here, so 2 : 1)."""

    def open_wide_image(self):
        viewer = self.open(MagicMock(return_value=(png((400, 200)), ".png")))
        viewer.geometry("800x600")
        self.app.update()
        return viewer

    @staticmethod
    def shown(viewer):
        return viewer._photo.width(), viewer._photo.height()

    def assert_fits_with_proportions(self, viewer):
        width, height = self.shown(viewer)
        canvas = viewer.canvas.winfo_width(), viewer.canvas.winfo_height()
        self.assertLessEqual(width, canvas[0])
        self.assertLessEqual(height, canvas[1])
        self.assertTrue(width == canvas[0] or height == canvas[1], "the image is as large as the window allows")
        self.assertAlmostEqual(width / height, 2.0, delta=0.05)

    def test_the_image_fills_the_window_with_its_proportions(self):
        viewer = self.open_wide_image()

        self.assert_fits_with_proportions(viewer)
        self.assertGreater(self.shown(viewer)[0], 400)  # a smaller image is enlarged too

    def test_the_image_grows_and_shrinks_with_the_window(self):
        viewer = self.open_wide_image()
        medium = self.shown(viewer)

        viewer.geometry("1200x800")
        self.app.update()
        large = self.shown(viewer)
        self.assert_fits_with_proportions(viewer)

        viewer.geometry("600x500")
        self.app.update()
        small = self.shown(viewer)
        self.assert_fits_with_proportions(viewer)

        self.assertGreater(large[0], medium[0])
        self.assertLess(small[0], medium[0])

    def test_widening_the_window_alone_does_not_change_the_image(self):
        viewer = self.open_wide_image()
        viewer.geometry("800x400")  # the height is what limits the image now
        self.app.update()
        before = self.shown(viewer)

        viewer.geometry("1200x400")
        self.app.update()

        self.assertEqual(self.shown(viewer), before)
        self.assertAlmostEqual(before[0] / before[1], 2.0, delta=0.05)

    def test_heightening_the_window_alone_does_not_change_the_image(self):
        viewer = self.open_wide_image()
        before = self.shown(viewer)  # 800 wide: the width limits it

        viewer.geometry("800x900")
        self.app.update()

        self.assertEqual(self.shown(viewer), before)

    def test_the_image_stays_in_the_middle(self):
        viewer = self.open_wide_image()
        viewer.geometry("1200x800")
        self.app.update()

        item = viewer.canvas.find_all()[0]
        self.assertEqual(viewer.canvas.coords(item), [viewer.canvas.winfo_width() // 2,
                                                       viewer.canvas.winfo_height() // 2])

    def test_the_image_follows_the_window_at_once_and_is_sharpened_when_it_stops(self):
        viewer = self.open_wide_image()

        viewer.geometry("1000x550")
        self.app.update()  # no waiting: the image is already scaled to the new size
        self.assert_fits_with_proportions(viewer)
        self.assertIsNotNone(viewer._sharpen_id)

        self.wait_for(lambda: viewer._sharpen_id is None)
        self.assert_fits_with_proportions(viewer)

    def test_a_new_snapshot_is_scaled_to_the_current_window_size(self):
        viewer = self.open(MagicMock(side_effect=[(png((400, 200)), ".png"), (png((200, 400)), ".png")]))
        viewer.geometry("1000x550")
        self.app.update()

        viewer.take_snapshot()
        self.wait_for(lambda: not viewer.busy)

        width, height = self.shown(viewer)
        self.assertAlmostEqual(width / height, 0.5, delta=0.05)  # the new image is tall
        self.assertLessEqual(height, viewer.canvas.winfo_height())


class WindowSizeTest(ViewerTestCase):
    """The window opens in the size it is asked for and says when the user gives it another."""

    def setUp(self):
        super().setUp()
        # Comfortably above what a real geometry() + update() cycle costs under the test suite (measured up to ~100 ms):
        # too close to that and three rapid resizes in a row (see test_a_resize_is_reported_once...) can each
        # have their delay elapse before the next one arrives, reporting every one instead of only the last.
        patcher = patch("gui_app.snapshot_viewer.RESIZE_REPORT_DELAY_MS", 400)
        patcher.start()
        self.addCleanup(patcher.stop)

    def size(self, viewer):
        return viewer.winfo_width(), viewer.winfo_height()

    def pump(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.update()
            time.sleep(0.01)

    def test_it_opens_in_the_default_size(self):
        viewer = self.open()

        self.assertEqual(self.size(viewer), DEFAULT_WINDOW_SIZE)

    def test_it_opens_in_the_size_it_is_asked_for(self):
        viewer = self.open(size=(1100, 550))

        self.assertEqual(self.size(viewer), (1100, 550))

    def test_a_size_larger_than_the_screen_is_cut_down_to_it(self):
        viewer = self.open(size=(9000, 9000))

        self.assertLess(viewer.winfo_width(), viewer.winfo_screenwidth())
        self.assertLess(viewer.winfo_height(), viewer.winfo_screenheight())

    def test_opening_reports_nothing(self):
        reported = MagicMock()
        self.open(size=(1100, 550), on_resized=reported)
        self.pump(0.4)

        reported.assert_not_called()

    def test_a_resize_is_reported_once_with_the_final_size(self):
        reported = MagicMock()
        viewer = self.open(on_resized=reported)

        for geometry in ("1000x510", "1050x540", "1150x570"):  # the pointer keeps moving
            viewer.geometry(geometry)
            self.app.update()
        self.wait_for(lambda: reported.called)
        self.pump(0.2)

        reported.assert_called_once_with((1150, 570))

    def test_a_window_closed_right_after_a_resize_still_reports_it(self):
        reported = MagicMock()
        viewer = self.open(on_resized=reported)
        viewer.geometry("1000x510")
        self.app.update()

        viewer.destroy()

        reported.assert_called_once_with((1000, 510))

    def test_a_saved_size_is_used_only_when_it_makes_sense(self):
        self.assertEqual(valid_window_size([1100, 700]), (1100, 700))
        self.assertEqual(valid_window_size((1100, 700)), (1100, 700))
        for raw in (None, [], [1100], [1100, 700, 5], "1100x700", [1100.5, 700], [True, 700], [10, 700],
                    [1100, 99999], {"w": 1}):
            with self.subTest(raw=raw):
                self.assertIsNone(valid_window_size(raw))

    def test_windows_opened_one_after_another_are_shifted(self):
        first = self.open(offset=0)
        second = self.open(offset=30)

        self.assertEqual(second.winfo_x() - first.winfo_x(), 30)
        self.assertEqual(second.winfo_y() - first.winfo_y(), 30)


class SlotsTest(ViewerTestCase):
    def test_no_more_than_the_limit_can_be_taken_at_once(self):
        slots = SnapshotSlots(3)
        self.assertEqual([slots.try_acquire() for _ in range(4)], [True, True, True, False])
        slots.release()
        self.assertTrue(slots.try_acquire())

    def test_a_window_without_a_free_slot_waits_and_takes_the_snapshot_when_one_frees(self):
        slots = SnapshotSlots(1)
        fetch, release, calls = self.blocking_fetch()
        first = self.open(fetch, slots, wait=False)
        self.wait_for(lambda: len(calls) == 1)
        second_fetch = MagicMock(return_value=(BLUE, ".png"))

        second = self.open(second_fetch, slots, wait=False)
        self.wait_for(lambda: "Čekám na volné místo" in second.status_var.get())
        second_fetch.assert_not_called()

        release.set()
        self.wait_for(lambda: not first.busy and not second.busy)
        second_fetch.assert_called_once()
        self.assertEqual(second._raw, BLUE)

    def test_the_slot_is_given_back_after_a_failure_too(self):
        slots = SnapshotSlots(1)
        self.open(MagicMock(side_effect=SnapshotError("download")), slots)

        self.assertTrue(slots.try_acquire())

    def test_the_slot_is_given_back_when_the_window_is_closed_meanwhile(self):
        slots = SnapshotSlots(1)
        fetch, release, calls = self.blocking_fetch()
        viewer = self.open(fetch, slots, wait=False)
        self.wait_for(lambda: len(calls) == 1)

        viewer.destroy()
        release.set()

        end = time.monotonic() + 5
        given_back = False
        while not given_back and time.monotonic() < end:
            given_back = slots.try_acquire()
            time.sleep(0.01)
        self.assertTrue(given_back, "the slot was never given back")


class LiveViewTest(ViewerTestCase):
    def test_the_intervals_offered(self):
        viewer = self.open()

        self.assertEqual(LIVE_INTERVALS, (2, 5, 10, 15, 20))
        self.assertEqual(list(viewer.interval_box.cget("values")), ["2 s", "5 s", "10 s", "15 s", "20 s"])
        self.assertEqual(viewer.interval, 5)

    def test_the_interval_is_chosen_in_the_box(self):
        viewer = self.open()
        viewer.interval_box.current(0)
        viewer.interval_box.event_generate("<<ComboboxSelected>>")
        self.app.update()

        self.assertEqual(viewer.interval, 2)

    def test_the_live_view_keeps_taking_snapshots(self):
        fetch = MagicMock(side_effect=lambda *_: (RED, ".png"))
        viewer = self.open(fetch)
        viewer.interval_box.current(0)
        viewer._interval_changed()

        viewer.start_live()
        self.wait_for(lambda: fetch.call_count >= 3, seconds=8)
        viewer.pause()
        count = fetch.call_count
        self.wait_for(lambda: not viewer.busy)
        time.sleep(0.3)
        self.app.update()

        self.assertLessEqual(fetch.call_count, count + 1)  # only one that was on its way can still come
        self.assertFalse(viewer.live)

    def test_the_next_snapshot_follows_the_start_of_the_last_by_the_interval(self):
        viewer = self.open()
        viewer.interval_box.current(0)
        viewer._interval_changed()
        viewer._live = True
        viewer._last_start = self.clock[0] - 0.5
        viewer.after = MagicMock(return_value="tick")

        viewer._schedule_live()

        self.assertEqual(viewer.after.call_args.args[0], 1500)
        self.assertEqual(viewer.after.call_args.args[1], viewer.take_snapshot)

    def test_a_snapshot_that_took_longer_than_the_interval_is_followed_at_once(self):
        viewer = self.open()
        viewer.interval_box.current(0)
        viewer._interval_changed()
        viewer._last_start = self.clock[0] - 7
        viewer.after = MagicMock(return_value="tick")

        viewer._schedule_live()

        self.assertEqual(viewer.after.call_args.args[0], 0)

    def test_changing_the_interval_while_live_reschedules(self):
        viewer = self.open()
        viewer.start_live()
        self.wait_for(lambda: not viewer.busy)
        viewer.after = MagicMock(return_value="tick")

        viewer.interval_box.current(4)
        viewer._interval_changed()

        self.assertEqual(viewer.interval, 20)
        self.assertTrue(viewer.after.called)
        viewer.pause()

    def test_the_button_becomes_pause_and_back(self):
        viewer = self.open()
        self.assertEqual(viewer.live_button.cget("text"), "Live-view")

        viewer.toggle_live()
        self.assertTrue(viewer.live)
        self.assertEqual(viewer.live_button.cget("text"), "Pauza")
        self.wait_for(lambda: not viewer.busy)
        self.assertIn("Live-view běží, každých 5 s", viewer.status_var.get())

        viewer.toggle_live()
        self.assertFalse(viewer.live)
        self.assertEqual(viewer.live_button.cget("text"), "Live-view")
        self.assertNotIn("běží", viewer.status_var.get())
        self.assertIsNone(viewer._next_id)

    def test_pause_lets_the_snapshot_on_its_way_arrive_and_starts_no_further_one(self):
        fetch, release, calls = self.blocking_fetch(BLUE)
        viewer = self.open(fetch, wait=False)
        viewer.start_live()
        self.wait_for(lambda: len(calls) == 1)

        viewer.pause()
        release.set()
        self.wait_for(lambda: not viewer.busy)

        self.assertEqual(viewer._raw, BLUE)
        self.assertIsNone(viewer._next_id)
        self.assertEqual(len(calls), 1)

    def test_pause_while_waiting_for_a_slot_does_not_leave_the_window_stuck(self):
        slots = SnapshotSlots(1)
        self.assertTrue(slots.try_acquire())
        viewer = self.open(slots=slots, wait=False)
        self.wait_for(lambda: "Čekám" in viewer.status_var.get())

        viewer.start_live()
        viewer.pause()
        slots.release()
        self.wait_for(lambda: not viewer.busy)

        self.assertTrue(viewer.has_image)

    def test_a_failure_ends_the_live_view(self):
        viewer = self.open(MagicMock(side_effect=[(RED, ".png"), SnapshotError("download")]))
        viewer.start_live()
        self.wait_for(lambda: not viewer.busy and not viewer.live)

        self.assertFalse(viewer.live)
        self.assertEqual(viewer.live_button.cget("text"), "Live-view")
        self.assertIsNone(viewer._next_id)
        self.assertIn("nepodařilo pořídit", viewer.status_var.get())

    def test_closing_the_window_stops_everything(self):
        fetch = MagicMock(side_effect=lambda *_: (RED, ".png"))
        viewer = self.open(fetch)
        viewer.start_live()
        self.wait_for(lambda: not viewer.busy)

        viewer.destroy()
        count = fetch.call_count
        for _ in range(20):
            self.app.update()
            time.sleep(0.01)

        self.assertEqual(fetch.call_count, count)


class TableButtonTest(ViewerTestCase):
    def test_a_press_after_the_interval_takes_a_snapshot_at_once(self):
        fetch = MagicMock(return_value=(RED, ".png"))
        viewer = self.open(fetch)
        self.clock[0] += MIN_REQUEST_INTERVAL

        viewer.request_snapshot()
        self.wait_for(lambda: fetch.call_count == 2 and not viewer.busy)

    def test_an_early_press_is_remembered_and_served_when_the_time_is_up(self):
        fetch = MagicMock(return_value=(RED, ".png"))
        viewer = self.open(fetch)
        self.clock[0] += 3
        viewer.after = MagicMock(return_value="tick")

        viewer.request_snapshot()
        viewer.request_snapshot()  # a second press changes nothing

        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(viewer._pending)
        self.assertEqual(viewer.after.call_args.args[0], 7000)
        self.assertIn(f"{MIN_REQUEST_INTERVAL} s", viewer.status_var.get())

        del viewer.after  # real timers again
        self.clock[0] += 7
        viewer.take_snapshot()  # what the timer does
        self.wait_for(lambda: fetch.call_count == 2 and not viewer.busy)
        self.assertFalse(viewer._pending)

    def test_while_the_live_view_runs_the_press_only_brings_the_window_forward(self):
        fetch = MagicMock(return_value=(RED, ".png"))
        viewer = self.open(fetch)
        viewer._live = True
        self.clock[0] += 30

        viewer.request_snapshot()
        self.app.update()

        self.assertEqual(fetch.call_count, 1)
        viewer._live = False


class SavingTest(ViewerTestCase):
    def test_the_shown_image_is_saved_where_the_user_says(self):
        target = os.path.join(self.directory.name, "mine.png")
        ask = MagicMock(return_value=target)
        viewer = self.open(MagicMock(return_value=(RED, ".png")), ask_path=ask)

        viewer.save()

        with open(target, "rb") as file:
            self.assertEqual(file.read(), RED)
        self.assertRegex(ask.call_args.args[1], r"^Lobby_1_\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.png$")
        self.assertEqual(ask.call_args.args[2], ".png")
        self.assertIn("Uloženo:", viewer.status_var.get())

    def test_the_image_shown_when_saving_started_is_the_one_saved(self):
        target = os.path.join(self.directory.name, "mine.png")
        fetch = MagicMock(side_effect=[(RED, ".png"), (BLUE, ".png")])
        viewer_holder = []

        def ask(*_):  # while the dialog is open the live view brings a new image
            viewer_holder[0].take_snapshot()
            end = time.monotonic() + 5
            while viewer_holder[0].busy and time.monotonic() < end:
                self.app.update()
                time.sleep(0.01)
            return target
        viewer = self.open(fetch, ask_path=ask)
        viewer_holder.append(viewer)

        viewer.save()

        with open(target, "rb") as file:
            self.assertEqual(file.read(), RED)

    def test_the_dialog_starts_in_the_downloads_folder_of_the_user(self):
        downloads = os.path.join(self.directory.name, "Downloads")
        os.mkdir(downloads)
        with patch("util.paths.user_downloads_path", return_value=Path(downloads)), \
                patch("gui_app.snapshot_viewer.filedialog.asksaveasfilename", return_value="") as dialog:
            ask_save_path(self.app, "Lobby_1.png", ".png")

        self.assertEqual(dialog.call_args.kwargs["initialdir"], downloads)
        self.assertEqual(dialog.call_args.kwargs["initialfile"], "Lobby_1.png")

    def test_without_a_downloads_folder_the_dialog_starts_in_the_home_folder(self):
        missing = Path(self.directory.name) / "nowhere"
        with patch("util.paths.user_downloads_path", return_value=missing), \
                patch("gui_app.snapshot_viewer.filedialog.asksaveasfilename", return_value="") as dialog:
            ask_save_path(self.app, "Lobby_1.png", ".png")

        self.assertEqual(dialog.call_args.kwargs["initialdir"], os.path.expanduser("~"))

    def test_cancelling_the_dialog_saves_nothing(self):
        viewer = self.open(ask_path=MagicMock(return_value=""))
        before = set(os.listdir(self.directory.name))

        viewer.save()

        self.assertEqual(set(os.listdir(self.directory.name)), before)
        self.assertNotIn("Uloženo", viewer.status_var.get())

    def test_a_file_that_cannot_be_written_is_reported(self):
        viewer = self.open(ask_path=MagicMock(return_value=os.path.join(self.directory.name, "missing", "a.png")))

        viewer.save()

        self.assertIn("Snímek se nepodařilo uložit", viewer.status_var.get())
        self.assertEqual(str(viewer._status_label.cget("foreground")), "#c62828")

    def test_there_is_nothing_to_save_before_the_first_image(self):
        ask = MagicMock(return_value="x.png")
        fetch, release, calls = self.blocking_fetch()
        viewer = self.open(fetch, ask_path=ask, wait=False)

        self.assertIn("disabled", viewer.save_button.state())
        viewer.save()
        ask.assert_not_called()

        release.set()
        self.wait_for(lambda: not viewer.busy)
        self.assertNotIn("disabled", viewer.save_button.state())


class MessagesTest(unittest.TestCase):
    def test_every_text_of_the_window_exists_in_both_languages(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        keys = set()
        for path in glob.glob(os.path.join(root, "gui_app", "snapshot_viewer.py")) + [
                os.path.join(root, "gui_app", "player_browser.py")]:
            with open(path, encoding="utf-8") as file:
                keys |= set(re.findall(r'"((?:sv|pb_tip_snapshot|pb_viewer)[a-z_]*)"', file.read()))
        self.assertGreater(len(keys), 15)
        for language in ("cz", "en"):
            messages = LanguageManager(language).messages[language]
            for key in sorted(keys):
                with self.subTest(language=language, key=key):
                    self.assertIn(key, messages)


if __name__ == "__main__":
    unittest.main()
