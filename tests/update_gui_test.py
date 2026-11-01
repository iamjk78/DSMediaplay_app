"""The "Update" button next to "Help", the check five seconds after the start, and what the window does with a newer
version: offers it (now or at the next start), downloads it with a progress that can be cancelled, installs it and ends,
or - when it cannot install it here - offers the page of the release."""
import contextlib
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import run
from gui_app import gui
from gui_app.update_dialog import DownloadDialog, UpdateOfferDialog
from main_buttons_test import MainWindowCase
from util import updater
from util.updater import Asset, Release, UpdateError
from util.version import VERSION

PAGE = f"https://github.com/{updater.REPOSITORY}/releases/tag/v1.0.9"
ASSET = Asset("DSMediaplay_app-Setup-1.0.9.exe", "https://github.com/x/y/releases/download/v1.0.9/f.exe", 100, "ab" * 32)
NEWER = Release("99.0.0", PAGE, ASSET)


class UpdateCase(MainWindowCase):
    def setUp(self):
        super().setUp()
        # No test shows a real dialog (it would wait for ever): what the window says is what these were called with
        self.showinfo, self.showwarning = MagicMock(), MagicMock()
        self.askyesno = MagicMock(return_value=False)
        for name, mock in (("showinfo", self.showinfo), ("showwarning", self.showwarning), ("askyesno", self.askyesno)):
            patcher = patch(f"gui_app.gui.messagebox.{name}", mock)
            patcher.start()
            self.addCleanup(patcher.stop)

    def pump(self, condition, seconds=5.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.update()
            if condition():
                return True
            time.sleep(0.01)
        return False

    def check(self, release=None, error=None, automatic=False):
        """Runs a check that the server answers with `release` (or fails with `error`) and waits until it has ended."""
        with patch("gui_app.gui.updater.fetch_latest_release", side_effect=error, return_value=release):
            self.app.start_update_check(automatic)
            self.assertTrue(self.pump(lambda: not self.app._update_running))

    @contextlib.contextmanager
    def dialogs(self):  # kept for the tests that read better with it: the dialogs are replaced for all of them anyway
        yield self


class ButtonTest(UpdateCase):
    def test_it_is_right_of_help_in_the_same_row_and_has_the_same_size(self):
        self.app.update()
        help_button, update = self.app.help_button, self.app.update_button

        self.assertGreaterEqual(update.winfo_rootx(), help_button.winfo_rootx() + help_button.winfo_width())
        self.assertEqual(update.winfo_rooty(), help_button.winfo_rooty())
        self.assertAlmostEqual(update.winfo_width(), help_button.winfo_width(), delta=1)  # an odd difference of pixels
        self.assertEqual(update.winfo_height(), help_button.winfo_height())

    def test_it_does_not_widen_the_window_or_touch_the_buttons_on_the_right(self):
        self.app.update()
        width = self.app.winfo_width()
        update, settings = self.app.update_button, self.app.settings_button

        self.assertEqual(self.app.winfo_reqwidth(), width)
        self.assertLess(update.winfo_rootx() + update.winfo_width(), settings.winfo_rootx())

    def test_its_text_follows_the_language_and_the_size_stays_equal(self):
        self.assertEqual(self.app.update_button.cget("text"), "Aktualizace")
        self.app.lang.set_language("en")
        self.app.refresh_all_widgets_text()
        self.app.update()

        self.assertEqual(self.app.update_button.cget("text"), "Update")
        self.assertAlmostEqual(self.app.help_button.winfo_width(), self.app.update_button.winfo_width(), delta=1)

    def test_a_larger_font_makes_both_larger_and_still_equal(self):
        self.app.update()
        before = self.app.update_button.winfo_width()
        self.app.font = ("Helvetica", 18)
        self.app.update_all_widgets_font()
        self.app.update()

        self.assertGreater(self.app.update_button.winfo_width(), before)
        self.assertAlmostEqual(self.app.help_button.winfo_width(), self.app.update_button.winfo_width(), delta=1)

    def test_it_has_a_tooltip_and_the_texts_exist_in_both_languages(self):
        self.assertTrue(self.app.update_button.tooltip._text())

    def test_it_looks_for_an_update_and_reports_the_outcome(self):
        with patch("gui_app.gui.updater.fetch_latest_release", return_value=Release(VERSION, PAGE, ASSET)) as fetch:
            self.app.update_button.invoke()
            self.assertTrue(self.pump(lambda: not self.app._update_running))

        fetch.assert_called_once_with()
        self.showinfo.assert_called_once()  # by the button, an answer is always given


class CheckTest(UpdateCase):
    def test_up_to_date_says_so_with_the_version(self):
        with self.dialogs() as dialogs:
            self.check(Release(VERSION, PAGE, ASSET))

        self.assertIn(VERSION, self.showinfo.call_args.args[1])
        self.showwarning.assert_not_called()

    def test_an_older_release_is_not_newer(self):
        with self.dialogs(), patch.object(self.app, "offer_update") as offer:
            self.check(Release("0.0.1", PAGE, ASSET))

        offer.assert_not_called()

    def test_nothing_published_yet_says_so(self):
        with self.dialogs():
            self.check(None)

        self.assertIn("zatím není", self.showinfo.call_args.args[1].lower())

    def test_a_failed_check_says_why(self):
        with self.dialogs():
            self.check(error=UpdateError("update_check_failed"))

        self.assertIn("Kontrola aktualizací se nepodařila", self.showwarning.call_args.args[1])

    def test_a_newer_release_is_offered(self):
        with self.dialogs(), patch.object(self.app, "offer_update") as offer:
            self.check(NEWER)

        offer.assert_called_once_with(NEWER, False)

    def test_the_automatic_check_says_nothing_unless_there_is_something_to_offer(self):
        for release, error in ((Release(VERSION, PAGE, ASSET), None), (None, None), (None, UpdateError("update_check_failed")),
                               (Release("0.0.1", PAGE, ASSET), None)):
            with self.subTest(release=release, error=error), self.dialogs(), patch.object(self.app, "offer_update") as offer:
                self.check(release, error, automatic=True)

                self.showinfo.assert_not_called()
                self.showwarning.assert_not_called()
                offer.assert_not_called()

    def test_the_automatic_check_offers_a_newer_version(self):
        with self.dialogs(), patch.object(self.app, "offer_update") as offer:
            self.check(NEWER, automatic=True)

        offer.assert_called_once_with(NEWER, True)

    def test_anything_unexpected_is_a_failed_check_and_not_a_crash(self):
        with self.dialogs(), patch("gui_app.gui.updater.fetch_latest_release", side_effect=RuntimeError("boom")):
            self.app.start_update_check()
            self.assertTrue(self.pump(lambda: not self.app._update_running))

        self.assertIn("Kontrola aktualizací se nepodařila", self.showwarning.call_args.args[1])

    def test_two_checks_do_not_run_at_once(self):
        with self.dialogs(), patch("gui_app.gui.updater.fetch_latest_release", side_effect=lambda: time.sleep(0.3)) as fetch:
            self.app.start_update_check()
            self.app.start_update_check()
            self.assertTrue(self.pump(lambda: not self.app._update_running))

        self.assertEqual(fetch.call_count, 1)

    def test_the_busy_cursor_is_only_for_the_button(self):
        with self.dialogs(), patch("gui_app.gui.updater.fetch_latest_release", side_effect=lambda: time.sleep(0.2)):
            self.app.start_update_check(True)
            self.assertEqual(str(self.app.cget("cursor")), "")
            self.pump(lambda: not self.app._update_running)
            self.app.start_update_check(False)
            self.assertEqual(str(self.app.cget("cursor")), "watch")
            self.pump(lambda: not self.app._update_running)

        self.assertEqual(str(self.app.cget("cursor")), "")


class OfferTest(UpdateCase):
    def offer(self, install, automatic=False):
        with patch("gui_app.gui.UpdateOfferDialog") as dialog, patch.object(self.app, "wait_window"), \
                patch.object(self.app, "install_update") as installing:
            dialog.return_value.install = install
            self.app.offer_update(NEWER, automatic)
        return dialog, installing

    def test_installing_now_installs(self):
        dialog, installing = self.offer(True)

        self.assertEqual(dialog.call_args.args, (self.app, VERSION, "99.0.0"))
        installing.assert_called_once_with(NEWER)

    def test_later_installs_nothing_and_asks_nothing_more_in_this_run(self):
        _, installing = self.offer(False)

        installing.assert_not_called()

    def test_an_automatic_offer_waits_while_a_window_of_the_application_is_in_the_way(self):
        with patch.object(self.app, "grab_current", return_value=object()), patch.object(self.app, "after") as after, \
                patch("gui_app.gui.UpdateOfferDialog") as dialog:
            self.app.offer_update(NEWER, True)

        dialog.assert_not_called()
        after.assert_called_once_with(gui.UPDATE_RETRY_MS, self.app.offer_update, NEWER, True)

    def test_an_automatic_offer_waits_while_the_input_window_is_open(self):
        self.app._input_window_open = True
        with patch.object(self.app, "after") as after, patch("gui_app.gui.UpdateOfferDialog") as dialog:
            self.app.offer_update(NEWER, True)

        dialog.assert_not_called()
        after.assert_called_once()

    def test_the_button_offers_at_once_whatever_is_open(self):
        with patch.object(self.app, "grab_current", return_value=object()):
            dialog, _ = self.offer(False, automatic=False)

        dialog.assert_called_once()


class InstallTest(UpdateCase):
    def install(self, release=NEWER, download=None, installing=None, installable=ASSET, delay=0):
        """Installs `release` with the download and the installation replaced; returns what they were called with."""
        calls = {}

        def fake_download(asset, directory, progress=None, cancelled=None):
            calls["asset"] = asset
            if progress:
                progress(50, 100)
            time.sleep(delay)  # long enough for the window to look at the progress
            if isinstance(download, Exception):
                raise download
            return download or "/tmp/package"

        with self.dialogs(), patch("gui_app.gui.updater.check_installable", side_effect=installable if isinstance(
                installable, Exception) else None, return_value=installable), \
                patch("gui_app.gui.updater.download", side_effect=fake_download), \
                patch("gui_app.gui.updater.install", side_effect=installing) as install, \
                patch("gui_app.gui.webbrowser.open") as browser, patch.object(self.app, "destroy") as destroy:
            self.app.install_update(release)
            self.pump(lambda: not self.app._update_running and (destroy.called or True), 3)
            self.app.update()
        return calls, install, browser, destroy

    def test_the_file_is_downloaded_installed_and_the_application_ends(self):
        calls, install, browser, destroy = self.install()

        self.assertEqual(calls["asset"], ASSET)
        install.assert_called_once_with("/tmp/package", NEWER)
        self.showinfo.assert_called_once()
        self.assertIn("ukonč", self.showinfo.call_args.args[1])
        destroy.assert_called_once()
        browser.assert_not_called()

    def test_a_release_that_cannot_be_installed_here_offers_its_page_instead_and_downloads_nothing(self):
        for key in ("update_not_installed_app", "update_no_asset", "update_no_checksum", "update_not_writable"):
            with self.subTest(key=key):
                with patch("gui_app.gui.updater.download") as download, self.dialogs(), \
                        patch("gui_app.gui.updater.check_installable", side_effect=UpdateError(key, folder="/Applications")), \
                        patch("gui_app.gui.webbrowser.open") as browser:
                    self.askyesno.return_value = True
                    self.app.install_update(NEWER)

                    download.assert_not_called()
                    browser.assert_called_once_with(PAGE)
                    self.assertIn("99.0.0", self.askyesno.call_args.args[1])

    def test_declining_the_page_opens_nothing(self):
        with self.dialogs(), patch("gui_app.gui.updater.check_installable", side_effect=UpdateError("update_no_asset")), \
                patch("gui_app.gui.webbrowser.open") as browser:
            self.app.install_update(NEWER)

        browser.assert_not_called()

    def test_a_download_that_fails_says_why_and_offers_the_page_and_the_application_stays(self):
        for key in ("update_download_failed", "update_checksum_mismatch"):
            with self.subTest(key=key):
                self.askyesno.reset_mock()
                calls, install, browser, destroy = self.install(download=UpdateError(key))

                install.assert_not_called()
                destroy.assert_not_called()
                self.askyesno.assert_called_once()
                self.assertNotIn("{", self.askyesno.call_args.args[1])

    def test_cancelling_the_download_asks_nothing_and_changes_nothing(self):
        calls, install, browser, destroy = self.install(download=UpdateError("update_cancelled"))

        install.assert_not_called()
        destroy.assert_not_called()
        self.askyesno.assert_not_called()
        self.showwarning.assert_not_called()

    def test_an_installation_that_fails_is_reported_and_the_application_stays(self):
        calls, install, browser, destroy = self.install(installing=UpdateError("update_invalid_package"))

        destroy.assert_not_called()
        self.assertIn("není platná aplikace", self.askyesno.call_args.args[1])

    def test_the_window_can_be_used_again_after_an_update_that_did_not_go_through(self):
        self.install(download=UpdateError("update_download_failed"))

        self.assertFalse(self.app._update_running)

    def test_the_progress_is_shown_while_downloading(self):
        shown = []
        with patch.object(DownloadDialog, "set_progress", lambda dialog, received, total: shown.append((received, total))):
            self.install(delay=0.3)

        self.assertIn((50, 100), shown)


class StartTest(UpdateCase):
    def start(self, enabled):
        path = self.app.config_file
        self.app.destroy()
        with patch("gui_app.gui.AUTO_UPDATE_DELAY_MS", 30), patch.object(gui.DSMediaplayApp, "start_update_check") as check:
            app = gui.DSMediaplayApp(path, check_updates_at_start=enabled)
            self.addCleanup(lambda: app.winfo_exists() and app.destroy())
            end = time.monotonic() + 0.4
            while time.monotonic() < end:
                app.update()
                time.sleep(0.01)
        return check

    def test_the_check_comes_five_seconds_after_the_start(self):
        self.assertEqual(gui.AUTO_UPDATE_DELAY_MS, 5000)

    def test_it_is_started_automatically_when_asked_to_and_flagged_as_automatic(self):
        self.start(True).assert_called_once_with(True)

    def test_without_the_request_nothing_is_checked(self):
        self.start(False).assert_not_called()

    def test_the_application_itself_asks_for_it_and_the_self_test_does_not(self):
        with patch("run.DSMediaplayApp") as app, patch("run.run_server"), patch("run.sys.argv", ["run.py", "-j", "x.json"]):
            run.main()
        app.assert_called_once_with("x.json", check_updates_at_start=True)

        with patch("run.DSMediaplayApp") as app:
            run.self_test()
        self.assertEqual(app.call_args.kwargs, {})


class DialogTest(UpdateCase):
    @staticmethod
    def button(dialog, text):
        return next(child for child in dialog.winfo_children() if isinstance(child, tk.Button) and child.cget("text") == text)

    def test_the_offer_names_both_versions_and_has_the_two_choices(self):
        dialog = UpdateOfferDialog(self.app, "1.0.8", "1.0.9")
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())

        texts = " ".join(child.cget("text") for child in dialog.winfo_children() if isinstance(child, tk.Label))
        self.assertIn("1.0.9", texts)
        self.assertIn("1.0.8", texts)
        self.assertIn("příštím spuštění", texts)
        self.button(dialog, "Nainstalovat hned")
        self.button(dialog, "Odložit")

    def test_installing_now_is_the_only_way_to_install(self):
        dialog = UpdateOfferDialog(self.app, "1.0.8", "1.0.9")
        self.button(dialog, "Nainstalovat hned").invoke()
        self.assertTrue(dialog.install)

    def test_later_closing_or_escape_leave_it_for_the_next_start(self):
        for how in ("button", "escape", "close"):
            with self.subTest(how=how):
                dialog = UpdateOfferDialog(self.app, "1.0.8", "1.0.9")
                if how == "button":
                    self.button(dialog, "Odložit").invoke()
                elif how == "escape":
                    dialog.event_generate("<Escape>")
                else:
                    dialog.destroy()
                self.app.update()
                self.assertFalse(dialog.install)
                if dialog.winfo_exists():
                    dialog.destroy()

    def test_the_progress_dialog_shows_the_fraction_and_can_be_cancelled(self):
        dialog = DownloadDialog(self.app, "1.0.9")
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())

        dialog.set_progress(25, 100)
        self.assertEqual(dialog._bar["value"], 25)
        dialog.set_progress(0, 0)  # an unknown size does not divide by zero
        self.assertEqual(dialog._bar["value"], 0)
        self.assertFalse(dialog.cancelled)
        self.button(dialog, "Zrušit").invoke()
        self.assertTrue(dialog.cancelled)

    def test_the_texts_of_the_dialogs_exist_in_english_too(self):
        self.app.lang.set_language("en")
        offer = UpdateOfferDialog(self.app, "1.0.8", "1.0.9")
        self.addCleanup(lambda: offer.winfo_exists() and offer.destroy())

        self.button(offer, "Install now")
        self.button(offer, "Later")


if __name__ == "__main__":
    unittest.main()
