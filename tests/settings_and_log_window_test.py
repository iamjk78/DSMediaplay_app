"""The Save button of the log window and the font of the settings: both used to claim they worked and did not."""
import json
import logging
import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from gui_app import gui
from gui_app.log_box import LoggingTextBox
from gui_app.settings_dialog import SettingsWindow


def close(widget):
    try:
        if widget.winfo_exists():
            widget.destroy()
    except tk.TclError:  # the whole application is gone already
        pass


class WindowCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = os.path.join(self.directory.name, "logins.json")
        with open(self.config, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}, file)
        self.start_app()

    def start_app(self):
        patcher = patch("gui_app.gui.credentials.get_password", return_value="")
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            self.app = gui.DSMediaplayApp(self.config)
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(close, self.app)
        self.app.update()

    def saved(self):
        with open(self.config, encoding="utf-8") as file:
            return json.load(file)


class SaveLogTest(WindowCase):
    def open_box(self, text):
        with patch("gui_app.log_box.ThreadManager.start_thread"):
            box = LoggingTextBox("remove_unused_playlists", url="http://example.com", login="u", password="p",
                                 data="", master=self.app)
        self.addCleanup(close, box)
        box.log_text.configure(state="normal")
        box.log_text.insert("1.0", text)
        return box

    def test_the_log_is_saved_in_the_chosen_file_and_the_message_says_where(self):
        box = self.open_box("Řádek 1: úspěch")
        target = os.path.join(self.directory.name, "log.txt")

        with patch("gui_app.log_box.filedialog.asksaveasfilename", return_value=target), \
                patch("gui_app.log_box.messagebox.showinfo") as info:
            box.save_text()

        with open(target, encoding="utf-8") as file:
            self.assertEqual(file.read(), "Řádek 1: úspěch")
        self.assertIn(target, info.call_args.args[1])

    def test_cancelling_the_dialog_does_nothing_instead_of_failing(self):
        box = self.open_box("text")
        for answer in ("", ()):  # what the dialog gives back on the platforms
            with self.subTest(answer=answer):
                with patch("gui_app.log_box.filedialog.asksaveasfilename", return_value=answer), \
                        patch("gui_app.log_box.messagebox.showinfo") as info, \
                        patch("gui_app.log_box.messagebox.showwarning") as warning:
                    box.save_text()

                info.assert_not_called()
                warning.assert_not_called()

    def test_a_file_that_cannot_be_written_is_reported_to_the_user(self):
        box = self.open_box("text")

        with patch("gui_app.log_box.filedialog.asksaveasfilename", return_value=self.directory.name), \
                patch("gui_app.log_box.messagebox.showinfo") as info, \
                patch("gui_app.log_box.messagebox.showwarning") as warning:
            box.save_text()  # a folder, not a file

        warning.assert_called_once()
        info.assert_not_called()


class SettingsFontTest(WindowCase):
    def save_settings(self, font, size):
        window = SettingsWindow(self.app, self.app.lang)
        self.addCleanup(close, window)
        window.font_var.set(font)
        window.size_var.set(size)
        with patch("gui_app.settings_dialog.messagebox.showinfo"):
            window.save_settings()

    def test_the_chosen_font_is_saved_in_the_config_file(self):
        self.save_settings("Arial", 16)

        self.assertEqual(self.saved()["font"], ["Arial", 16])
        self.assertEqual(self.app.font, ("Arial", 16))

    def test_the_font_is_the_same_after_the_application_is_started_again(self):
        self.save_settings("Arial", 16)
        self.app.destroy()

        self.start_app()

        self.assertEqual(self.app.font, ("Arial", 16))
        self.assertEqual(self.app.emphasised_font(2), ("Arial", 18, "bold"))  # the size is a number, not a text

    def test_restoring_the_defaults_restores_the_font_in_the_file_too(self):
        self.save_settings("Arial", 16)
        window = SettingsWindow(self.app, self.app.lang)
        self.addCleanup(close, window)

        with patch("gui_app.settings_dialog.messagebox.showinfo"):
            window.restore_default()

        self.assertEqual(self.saved()["font"], ["Helvetica", 12])


class LogWindowCase(WindowCase):
    def open_box(self):
        with patch("gui_app.log_box.ThreadManager.start_thread"):
            box = LoggingTextBox("remove_unused_playlists", url="http://example.com", login="u", password="p",
                                 data="", master=self.app)
        self.addCleanup(close, box)
        box.unbind("<Visibility>")  # showing the window would start the real operation
        return box

    def pump(self, seconds=0.0):
        end = time.monotonic() + seconds
        self.app.update()
        while time.monotonic() < end:
            self.app.update()
            time.sleep(0.01)

class CloseLogWindowTest(LogWindowCase):
    """The window of a running operation used to close and leave the operation running, unwatched and unstoppable."""

    def test_closing_a_window_whose_operation_is_not_running_asks_nothing(self):
        box = self.open_box()

        with patch("gui_app.log_box.messagebox.askyesno") as ask:
            box._close()
            self.pump()

        ask.assert_not_called()
        self.assertFalse(box.winfo_exists())

    def test_refusing_to_stop_leaves_the_window_and_the_operation_alone(self):
        box = self.open_box()
        box.thread_manager.is_running = True

        with patch("gui_app.log_box.messagebox.askyesno", return_value=False) as ask:
            box._close()
            self.pump()

        self.assertTrue(box.winfo_exists())
        self.assertFalse(box.thread_manager.stop_event.is_set())
        self.assertEqual(ask.call_args.kwargs["default"], "no")

    def test_agreeing_stops_the_operation_and_the_window_closes_only_when_it_has_ended(self):
        box = self.open_box()
        box.thread_manager.is_running = True

        with patch("gui_app.log_box.messagebox.askyesno", return_value=True):
            box._close()
        self.pump(0.7)  # the operation is still finishing its batch: the window waits for it

        self.assertTrue(box.thread_manager.stop_event.is_set())
        self.assertTrue(box.winfo_exists())
        self.assertEqual(box.indication_label.cget("text"), "Zastavuji…")
        box.thread_manager.is_running = False
        self.pump(0.7)
        self.assertFalse(box.winfo_exists())

    def test_the_cross_of_the_window_and_the_close_button_ask_the_same_question(self):
        for how in ("cross", "button"):
            with self.subTest(how=how):
                box = self.open_box()
                box.thread_manager.is_running = True
                with patch("gui_app.log_box.messagebox.askyesno", return_value=False) as ask:
                    if how == "cross":
                        box.tk.call(box.protocol("WM_DELETE_WINDOW"))
                    else:
                        next(b for b in reversed(box.winfo_children())
                             if isinstance(b, tk.Button) and b.cget("text") == "Zavřít").invoke()

                ask.assert_called_once()
                self.assertTrue(box.winfo_exists())

    def test_a_running_operation_is_really_stopped_by_closing_its_window(self):
        steps = []

        def run():
            for _ in range(1000):
                time.sleep(0.01)
                steps.append(1)
                yield

        processor = MagicMock()
        processor.confirmation.return_value = None
        processor.run.side_effect = run
        with patch("gui_app.log_box.ProcessorFactory.create_processor", return_value=processor):
            box = LoggingTextBox("remove_unused_playlists", url="http://example.com", login="u", password="p",
                                 data="", master=self.app)
            self.addCleanup(close, box)
            box.thread_manager.start_thread()
            deadline = time.monotonic() + 15

            def watch():
                if not box.winfo_exists() or time.monotonic() > deadline:
                    self.app.quit()
                else:
                    self.app.after(20, watch)

            with patch("gui_app.log_box.messagebox.askyesno", return_value=True):
                self.app.after(300, box._close)
                self.app.after(20, watch)
                self.app.mainloop()  # like in the application: the worker thread reaches Tk through it

        self.assertFalse(box.winfo_exists(), "the window is still there")
        self.assertFalse(box.thread_manager.is_running)
        self.assertTrue(0 < len(steps) < 1000, steps)

    def test_a_stop_asked_for_while_the_input_is_loaded_prevents_even_the_first_step(self):
        box = self.open_box()
        processor = MagicMock()
        processor.confirmation.return_value = None
        processor.load.side_effect = lambda text: box.thread_manager.stop_event.set()
        with patch("gui_app.log_box.ProcessorFactory.create_processor", return_value=processor):
            box.run_input_processing()

        processor.run.assert_not_called()
        self.assertEqual(box.indication_label.cget("text"), "Zrušeno")


class EndOfTheOperationTest(LogWindowCase):
    """What the window says when the operation has ended: done, stopped half way, or broken."""

    def run_with(self, processor):
        box = self.open_box()
        with patch("gui_app.log_box.ProcessorFactory.create_processor", return_value=processor):
            with self.assertLogs(box.logger, "INFO") as logged:
                box.run_input_processing()
        return box, "\n".join(logged.output)

    @staticmethod
    def processor(steps, stop_after=None, box_holder=None):
        processor = MagicMock()
        processor.confirmation.return_value = None

        def run():
            for number in range(1, steps + 1):
                if number == stop_after:  # the user presses Stop while this step is being done
                    box_holder[0].thread_manager.stop_event.set()
                yield  # the step is done

        processor.run.side_effect = run
        return processor

    def test_an_operation_that_went_through_everything_says_it_is_done(self):
        box, log = self.run_with(self.processor(3))

        self.assertIn(box.lang.get_message("operation_successful"), log)
        self.assertEqual(box.indication_label.cget("text"), box.lang.get_message("done"))

    def test_an_operation_that_was_stopped_half_way_says_so_and_how_far_it_got(self):
        holder = []
        box = self.open_box()
        holder.append(box)
        processor = self.processor(10, stop_after=3, box_holder=holder)
        with patch("gui_app.log_box.ProcessorFactory.create_processor", return_value=processor):
            with self.assertLogs(box.logger, "INFO") as logged:
                box.run_input_processing()

        log = "\n".join(logged.output)
        self.assertIn(box.lang.get_message("operation_stopped_after", steps=3), log)
        self.assertNotIn(box.lang.get_message("operation_successful"), log)
        self.assertEqual(box.indication_label.cget("text"), box.lang.get_message("stopped"))

    def test_anything_a_processor_lets_out_ends_in_the_error_state_not_in_working_for_ever(self):
        processor = MagicMock()
        processor.load.side_effect = KeyError("line_num")

        box, log = self.run_with(processor)

        self.assertIn(box.lang.get_message("internal_error", error_msg="'line_num'"), log)
        self.assertEqual(box.indication_label.cget("text"), box.lang.get_message("error"))
        self.assertNotIn(box.lang.get_message("operation_successful"), log)


class LogWindowHousekeepingTest(LogWindowCase):
    def buttons(self, box):
        return [child for child in box.winfo_children() if isinstance(child, tk.Button)]

    def test_the_buttons_are_not_piled_up_when_the_run_ends(self):
        box = self.open_box()
        self.assertEqual(len(self.buttons(box)), 3)

        box.display_success()
        box.display_error()
        box.setup_buttons()

        self.assertEqual(len(self.buttons(box)), 3)

    def test_a_closed_window_leaves_no_logger_behind(self):
        box = self.open_box()
        name = box.logger.name
        self.assertIn(name, logging.Logger.manager.loggerDict)

        box.destroy()

        self.assertNotIn(name, logging.Logger.manager.loggerDict)
        self.assertEqual(box.logger.handlers, [])

    def test_a_window_that_gets_the_name_of_a_closed_one_logs_only_into_itself(self):
        first = self.open_box()
        first.destroy()
        second = self.open_box()

        second.logger.info("hello")
        self.app.update()

        self.assertIn("hello", second.log_text.get("1.0", tk.END))
        self.assertEqual(len(second.logger.handlers), 1)


if __name__ == "__main__":
    unittest.main()
