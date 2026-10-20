import json
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from gui_app import gui
from gui_app.color_button import BLUE, DISABLED, GREEN, PURPLE, YELLOW, ColorButton, equalize_widths

URL = "https://demo.example.com"


class MainWindowCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = os.path.join(self.directory.name, "logins.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {
                "Demo": {"url": URL, "names": {"jane": {"login": "jane"}}}}}, file)
        patcher = patch("gui_app.gui.credentials.get_password", return_value="")
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            self.app = gui.DSMediaplayApp(path)
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.close_app)
        self.app.update()

    def close_app(self):
        try:
            self.app.destroy()
        except tk.TclError:  # a test may have closed it already
            pass

    def log_in(self, password="secret"):
        self.app.option_choose_administration.set("Demo")
        self.app.fill_login_details()
        self.app.option_choose_name.set("jane")
        self.app.input_for_password.delete(0, tk.END)
        self.app.input_for_password.insert(0, password)

    def buttons(self):
        return self.app.outage_button, self.app.live_view_button, self.app.deploy_all_button, self.app.start_button


class MainButtonsTest(MainWindowCase):
    # ---- look and place

    def test_the_new_buttons_and_start_are_the_same_size_and_font(self):
        outage, live, deploy, start = self.buttons()

        self.assertEqual({(b.winfo_width(), b.winfo_height()) for b in self.buttons()}, {(start.winfo_width(), 28)})
        self.assertEqual(len({str(b.cget("font")) for b in self.buttons()}), 1)
        self.assertEqual((outage.cget("text"), live.cget("text"), deploy.cget("text")),
                         ("Výpadky", "Live-view", "DEPLOY ALL"))

    def test_they_are_stacked_at_the_right_edge_outage_above_live_view_above_deploy_above_start(self):
        outage, live, deploy, start = self.buttons()

        right_edges = {b.winfo_rootx() + b.winfo_width() for b in self.buttons()}
        self.assertEqual(len(right_edges), 1)
        self.assertLess(outage.winfo_rooty() + outage.winfo_height(), live.winfo_rooty() + 1)
        self.assertLess(live.winfo_rooty() + live.winfo_height(), deploy.winfo_rooty() + 1)
        self.assertLess(deploy.winfo_rooty() + deploy.winfo_height(), start.winfo_rooty())
        self.assertLessEqual(max(right_edges), self.app.winfo_rootx() + self.app.winfo_width())

    def test_outage_live_view_and_deploy_are_in_their_own_rows(self):
        outage, live, deploy, _ = self.buttons()

        self.assertEqual(outage.grid_info()["row"], self.app._outage_row)
        self.assertEqual(live.grid_info()["row"], self.app._entity_type_row)
        self.assertEqual(deploy.grid_info()["row"], self.app._action_row)

    def test_they_do_not_touch_the_drop_downs_or_widen_the_window(self):
        outage, live, deploy, _ = self.buttons()
        width = self.app.winfo_width()

        # A guaranteed minimum gap, not just "somewhere to the right": on Windows a native button can be wide
        # enough to butt straight up against a wide combobox otherwise.
        for button, box in ((live, self.app.entity_type_combobox), (deploy, self.app.option_choose_action)):
            self.assertGreaterEqual(button.winfo_rootx() - (box.winfo_rootx() + box.winfo_width()),
                                    gui.ACTION_ROW_GAP_X)
        self.assertGreater(outage.winfo_rootx(), self.app.entity_type_combobox.winfo_rootx())
        self.assertEqual(self.app.winfo_reqwidth(), width)

    def test_the_colours_are_light_purple_light_blue_light_yellow_and_light_green(self):
        outage, live, deploy, start = self.buttons()

        self.log_in()
        self.assertEqual((outage._colors, live._colors, deploy._colors, start._colors), (PURPLE, BLUE, YELLOW, GREEN))
        self.assertTrue(all(b.enabled for b in self.buttons()))

    def test_the_buttons_have_tooltips_and_the_texts_exist_in_both_languages(self):
        for button in (self.app.outage_button, self.app.live_view_button, self.app.deploy_all_button):
            self.assertTrue(button.tooltip._text())
        self.app.lang.set_language("en")
        for key in ("outages", "live_view", "deploy_all", "tip_outages", "tip_live_view", "tip_deploy_all"):
            self.assertTrue(self.app.lang.get_message(key))

    def test_a_language_change_keeps_the_texts_and_the_equal_size(self):
        self.app.all_data["lang"] = "en"
        self.app.lang.set_language("en")
        self.app.refresh_ui()
        self.app.update()

        self.assertEqual((self.app.outage_button.cget("text"), self.app.live_view_button.cget("text"),
                          self.app.deploy_all_button.cget("text")), ("Outages", "Live-view", "DEPLOY ALL"))
        self.assertEqual(len({b.winfo_width() for b in self.buttons()}), 1)

    def test_a_larger_font_makes_them_larger_and_still_equal(self):
        before = self.app.deploy_all_button.winfo_width()
        self.app.font = ("Helvetica", 18)
        self.app.update_all_widgets_font()
        self.app.update()

        self.assertEqual(len({b.winfo_width() for b in self.buttons()}), 1)
        self.assertGreater(self.app.deploy_all_button.winfo_width(), before)

    # ---- what they do

    def test_deploy_all_starts_the_same_action_as_the_menu_entry_and_asks_nothing_in_the_main_window(self):
        # The question comes later, in the log window, once the number of players is known (DeployConfirmationTest)
        self.log_in()
        with patch.object(self.app, "open_action_log_box") as start, \
                patch.object(gui.messagebox, "askyesno", side_effect=AssertionError("no confirmation")), \
                patch.object(gui.messagebox, "showinfo") as info:
            self.app.deploy_all_button.event_generate("<ButtonPress-1>", x=5, y=5)
            self.app.deploy_all_button.event_generate("<ButtonRelease-1>", x=5, y=5)
            button_call = start.call_args

            start.reset_mock()
            self.app.entity_type_var.set("Deploy")
            self.app.update_action_selection()
            label = next(l for l, k in self.app.entity_actions["Deploy"].items() if k == "set_deploy_all_players")
            self.app.option_choose_action.set(label)
            self.app.execute_action()

        self.assertEqual(button_call, start.call_args)
        self.assertEqual(button_call.args[:4], ("deploy_all_players", URL, "jane", "secret"))
        info.assert_not_called()

    def test_deploy_all_uses_the_batch_settings_of_the_deploy_actions(self):
        self.log_in()
        self.app.all_data["deploy_batch_size"], self.app.all_data["deploy_batch_interval"] = 7, 5
        with patch("gui_app.gui.LoggingTextBoxFactory.create_log_box") as factory, \
                patch.object(self.app, "wait_window"):
            self.app.deploy_all()

        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["processor_type"], "deploy_all_players")
        self.assertEqual(kwargs["extra_settings"], {"batch_size": 7, "batch_interval": 5, "account_name": "Demo"})

    def test_live_view_opens_the_player_window_of_the_selected_account(self):
        self.log_in()
        with patch.object(self.app, "open_player_browser") as opened:
            self.app.live_view_button.event_generate("<ButtonPress-1>", x=5, y=5)
            self.app.live_view_button.event_generate("<ButtonRelease-1>", x=5, y=5)

        opened.assert_called_once_with(URL, "jane", "secret")

    def test_outages_opens_the_player_window_prefiltered_to_active_offline_newest_reported_first(self):
        self.log_in()
        with patch.object(self.app, "open_player_browser") as opened:
            self.app.outage_button.event_generate("<ButtonPress-1>", x=5, y=5)
            self.app.outage_button.event_generate("<ButtonRelease-1>", x=5, y=5)

        opened.assert_called_once()
        args, kwargs = opened.call_args
        self.assertEqual(args, (URL, "jane", "secret"))
        browser = MagicMock()
        kwargs["on_open"](browser)
        browser.set_filter_and_sort.assert_called_once_with(name="aktivni", online=False, sort_column="reported",
                                                            sort_descending=True)

    def test_without_a_selected_login_nothing_starts_and_a_hint_is_shown(self):
        for name, target in (("deploy_all", "open_action_log_box"), ("live_view", "open_player_browser"),
                             ("outages", "open_player_browser")):
            with self.subTest(button=name):
                with patch.object(self.app, target) as start, patch.object(gui.messagebox, "showinfo") as info:
                    getattr(self.app, name)()

                start.assert_not_called()
                info.assert_called_once()

    def test_with_a_login_but_without_a_password_nothing_starts_either(self):
        self.log_in(password="")
        for name, target in (("deploy_all", "open_action_log_box"), ("live_view", "open_player_browser"),
                             ("outages", "open_player_browser")):
            with self.subTest(button=name):
                with patch.object(self.app, target) as start, patch.object(gui.messagebox, "showinfo") as info:
                    getattr(self.app, name)()

                start.assert_not_called()
                info.assert_called_once()


class ActionButtonsEnabledTest(MainWindowCase):
    """Start, Live-view and Deploy all are usable only with an account, one of its logins and a password."""

    def fills(self):
        return [b._colors.normal if b.enabled else DISABLED.normal for b in self.buttons()]

    def all_enabled(self):
        return [b.enabled for b in self.buttons()]

    def test_at_first_without_an_account_all_three_are_grey_and_off(self):
        self.assertEqual(self.all_enabled(), [False, False, False, False])
        for button in self.buttons():
            self.assertTrue(button.winfo_ismapped())  # still there, only grey

    def test_an_account_alone_is_not_enough_and_neither_is_an_account_with_a_login(self):
        self.app.option_choose_administration.set("Demo")
        self.assertEqual(self.all_enabled(), [False, False, False, False])
        self.app.fill_login_details()
        self.app.option_choose_name.set("jane")
        self.assertEqual(self.all_enabled(), [False, False, False, False])  # no password yet

    def test_a_password_without_an_account_or_login_is_not_enough(self):
        self.app.input_for_password.insert(0, "secret")
        self.assertEqual(self.all_enabled(), [False, False, False, False])
        self.app.option_choose_administration.set("Demo")
        self.assertEqual(self.all_enabled(), [False, False, False, False])

    def test_the_account_the_login_and_the_password_together_switch_them_on(self):
        self.log_in()

        self.assertEqual(self.all_enabled(), [True, True, True, True])
        self.assertEqual(self.fills(), [PURPLE.normal, BLUE.normal, YELLOW.normal, GREEN.normal])

    def test_they_follow_each_change_at_once(self):
        self.log_in()
        self.app.input_for_password.delete(0, tk.END)
        self.assertEqual(self.all_enabled(), [False, False, False, False])
        self.app.input_for_password.insert(0, "x")
        self.assertEqual(self.all_enabled(), [True, True, True, True])
        self.app.option_choose_name.set("")
        self.assertEqual(self.all_enabled(), [False, False, False, False])
        self.app.option_choose_name.set("jane")
        self.assertEqual(self.all_enabled(), [True, True, True, True])
        self.app.option_choose_administration.set("")
        self.assertEqual(self.all_enabled(), [False, False, False, False])

    def test_a_login_that_is_not_one_of_the_accounts_does_not_count(self):
        self.log_in()
        self.app.option_choose_name.set("somebody else")

        self.assertEqual(self.all_enabled(), [False, False, False, False])

    def test_a_grey_button_does_not_react_to_the_pointer_or_run_its_command(self):
        outage, live, deploy, start = self.buttons()
        with patch.object(self.app, "open_player_browser") as opened, \
                patch.object(self.app, "open_action_log_box") as log_box, \
                patch.object(self.app, "execute_action") as execute:
            start._command = self.app.execute_action  # the patched one
            for button in self.buttons():
                button.event_generate("<Enter>")
                self.assertEqual(button._state, "normal")
                button.event_generate("<ButtonPress-1>", x=5, y=5)
                button.event_generate("<ButtonRelease-1>", x=5, y=5)

        opened.assert_not_called()
        log_box.assert_not_called()
        execute.assert_not_called()

    def test_the_grey_button_looks_grey_whatever_its_own_colour(self):
        fills = []
        for button in self.buttons():
            item = button.find_withtag("all")[0]
            fills.append(button.itemcget(item, "fill"))

        self.assertEqual(fills, [DISABLED.normal] * 4)

    def test_the_tooltip_of_a_grey_button_says_what_is_missing_and_the_normal_one_what_it_does(self):
        outage, live, deploy, start = self.buttons()

        self.assertIn("vyberte zákaznický účet", start.tooltip._text().lower())
        self.assertEqual(live.tooltip._text(), deploy.tooltip._text())
        self.log_in()
        self.assertNotIn("vyberte", start.tooltip._text().lower())
        self.assertIn("Deploy", deploy.tooltip._text())

    def test_they_are_on_when_the_window_opens_with_a_remembered_account_login_and_password(self):
        path = os.path.join(self.directory.name, "remembered.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump({"lang": "cz", "font": ["Helvetica", 12], "default": ["Demo", "jane"], "logins": {
                "Demo": {"url": URL, "names": {"jane": {"login": "jane"}}, "last": "jane"}}}, file)
        self.app.destroy()  # one window at a time: the window icon belongs to the first Tk interpreter
        with patch("gui_app.gui.credentials.get_password", return_value="stored"):
            app = gui.DSMediaplayApp(path)
        self.addCleanup(app.destroy)
        app.update()

        self.assertEqual([b.enabled for b in (app.outage_button, app.live_view_button, app.deploy_all_button,
                                              app.start_button)], [True, True, True, True])

    def test_they_are_off_after_the_account_is_removed(self):
        self.log_in()
        with patch.object(gui.messagebox, "askyesno", return_value=True):
            self.app.remove_account()

        self.assertEqual(self.all_enabled(), [False, False, False, False])

    def test_they_are_off_after_the_login_is_removed(self):
        self.log_in()
        with patch.object(gui.messagebox, "askyesno", return_value=True):
            self.app.remove_login()

        self.assertEqual(self.all_enabled(), [False, False, False, False])

    def test_a_change_of_the_config_file_from_outside_is_noticed(self):
        self.log_in()
        self.assertEqual(self.all_enabled(), [True, True, True, True])
        with open(self.app.config_file, encoding="utf-8") as file:
            data = json.load(file)
        data["logins"]["Demo"]["names"] = {}  # the login is gone from the file
        with open(self.app.config_file, "w", encoding="utf-8") as file:
            json.dump(data, file)
        os.utime(self.app.config_file, (1, 1))  # a different modification time

        self.app.sync_from_disk()

        self.assertEqual(self.all_enabled(), [False, False, False, False])

    def test_the_language_and_font_changes_keep_the_state_and_the_equal_size(self):
        self.log_in()
        self.app.all_data["lang"] = "en"
        self.app.lang.set_language("en")
        self.app.refresh_ui()  # this clears the selection, as always
        self.app.update()
        self.assertEqual(self.all_enabled(), [False, False, False, False])
        self.log_in()
        self.app.font = ("Helvetica", 16)
        self.app.update_all_widgets_font()
        self.app.update()

        self.assertEqual(self.all_enabled(), [True, True, True, True])
        self.assertEqual(len({b.winfo_width() for b in self.buttons()}), 1)

    def test_a_grey_button_can_still_be_started_by_the_code_and_reports_the_missing_login(self):
        with patch.object(gui.messagebox, "showinfo") as info, patch.object(self.app, "open_action_log_box") as start:
            self.app.deploy_all()

        start.assert_not_called()
        info.assert_called_once()

    def test_the_other_buttons_of_the_window_are_not_affected(self):
        for button in (self.app.quit_button, self.app.input_prompt_button):
            self.assertTrue(getattr(button, "enabled", True))
        self.assertEqual(str(self.app.help_button.cget("state")), "normal")


class EqualWidthsTest(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display available")
        self.addCleanup(self.root.destroy)

    def make(self, text, padding=12):
        button = ColorButton(self.root, text, lambda: None, ("Helvetica", 14, "bold"), GREEN, padding_x=padding)
        button.pack()
        return button

    def test_the_buttons_get_the_width_of_the_widest(self):
        short, long = self.make("OK"), self.make("A much longer text")
        self.root.update()
        widest = long.winfo_width()
        self.assertLess(short.winfo_width(), widest)

        equalize_widths(short, long)
        self.root.update()

        self.assertEqual((short.winfo_width(), long.winfo_width()), (widest, widest))

    def test_equalizing_again_after_a_text_change_follows_the_new_widest(self):
        first, second = self.make("Short"), self.make("Longer text")
        equalize_widths(first, second)
        first.configure(text="A really very long text here")
        equalize_widths(first, second)
        self.root.update()

        self.assertEqual(first.winfo_width(), second.winfo_width())
        self.assertEqual(first.winfo_width(), first.natural_width())

    def test_the_padding_is_part_of_the_width(self):
        narrow, wide = self.make("Same", 8), self.make("Same", 20)

        self.assertEqual(wide.natural_width() - narrow.natural_width(), 24)


if __name__ == "__main__":
    unittest.main()
