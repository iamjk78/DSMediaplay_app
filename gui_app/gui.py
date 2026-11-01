import tkinter as tk
from tkinter import font as tkfont, ttk, messagebox
from gui_app.color_button import (BLUE, GREEN, GREEN_DARK, PURPLE, RED, YELLOW, button_enabled, equalize_widths,
                                  make_color_button, set_button_colors, set_button_enabled)
from gui_app.icons import set_window_icon
from gui_app.tooltip import ListTooltip, TclListbox, Tooltip
from gui_app.update_dialog import DownloadDialog, UpdateOfferDialog
import copy
import json
import os
import queue
import re
import tempfile
import threading
from gui_app.input_box import InputTextBox
from gui_app.settings_dialog import SettingsWindow
from gui_app.account_dialogs import EntryDialog, LanguageDialog
from documentation import server as documentation_server
from processor.csv_generator import CSVTaskFactory
from api_testing.request_calls import LoginError
from processor.input_processing import try_login
from datetime import datetime
from util.language import LanguageManager
from gui_app.log_box import LoggingTextBoxFactory
from gui_app.player_browser import PlayerBrowser
from util import accounts, credentials, input_templates, legacy_import, updater
from util import action_descriptions
from util.actions import NO_INPUT_PLACEHOLDER, action_kind, action_needs_input, entity_actions
from util.paths import legacy_login_file, resource_path
from util.version import VERSION
import requests
import webbrowser


# The same for Start and Deploy all: narrow enough for the free space right of the action drop-down
DEPLOY_PADDING_X = 12
# Minimum breathing room, in pixels, between the category/action drop-downs and Live-view/Deploy all to their
# right; see _ensure_gap_from_dropdowns for why this can't just be a bigger padx on the buttons.
ACTION_ROW_GAP_X = 24
# create_combobox's own padx, right side: _ensure_gap_from_dropdowns resets to this before each measurement,
# so a previous, possibly wrong top-up is never compounded by a later one.
DROPDOWN_PAD_X = 3
LIST_EXTRA_WIDTH = 40  # the scrollbar and the padding of the list of actions
ACTION_TINTS = {"read": GREEN, "change": BLUE, "remove": RED}  # the entries of the list of actions, by what they do


def get_download_path():
    """Returns the default downloads path for linux or windows"""
    if os.name == 'nt':
        import winreg
        sub_key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
        downloads_guid = '{374DE290-123F-4565-9164-39C4925E467B}'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
            location = winreg.QueryValueEx(key, downloads_guid)[0]
        return location
    else:
        return os.path.join(os.path.expanduser('~'), 'downloads')


BLINK_INTERVAL_MS = 500
CSV_POLL_MS = 100  # how often the window looks whether what the server was asked for (a file, a login) is ready
LAST_COLUMN = 4  # of the grid of the main window: the one with the "+" and "-" buttons, right of the drop-downs
BOTTOM_ROW_GAP_X = 10  # the least space between the two groups of buttons in the bottom row
AUTO_UPDATE_DELAY_MS = 5000  # the check for a newer version, after the start
UPDATE_RETRY_MS = 10000  # the offer of one, when a window of the application is in the way
UPDATE_POLL_MS = 100  # how often the window looks whether the check or the download of a version has ended


class DSMediaplayApp(tk.Tk):
    """
    Main application class for the DSMediaplay control panel.
    """

    def __init__(self, logins_file: str, *, language_file: str = str(resource_path("assets/messages.json")),
                 check_updates_at_start: bool = False):
        """
        Initializes the DSMediaplayApp with the given logins file. `check_updates_at_start`: look for a newer version
        a few seconds after the start (the application turns it on, the tests do not).
        """
        super().__init__()
        self.title(f"DSMediaplay Control Panel {VERSION}")
        self.config_file = logins_file
        self._file_stamp = None  # (mtime, size) of the config file as this app last read or wrote it
        try:
            self.all_data = self.load_account_configs()
        except (OSError, ValueError):
            self.all_data = self.recover_unreadable_config(language_file)
        if "lang" not in self.all_data:
            self.ask_language()
        self.lang = LanguageManager(language=self.all_data.get("lang", "en"), config_path=language_file)
        self.import_legacy_accounts()
        self.migrate_plaintext_passwords()
        self.migrate_credential_items()
        self.font = tuple(self.all_data.get("font", ["Helvetica", 12]))
        self.account_data = self.all_data["logins"]
        self.default = self.all_data["default"]
        self.selected_file = None
        self.entity_type_var = tk.StringVar()
        self.action_var = tk.StringVar()
        self.entity_actions = self.load_actions()
        self.setup_icons()

        # Initialize attributes for UI components
        self.administration_label = None
        self.name_label = None
        self.password_label = None
        self.entity_type_label = None
        self.action_label = None
        self.option_choose_administration = None
        self.option_choose_name = None
        self.input_for_password = None
        self.save_button = None
        self.entity_type_combobox = None
        self.option_choose_action = None
        self.text_box_label = None
        self.text_box = None
        self.settings_button = None
        self.help_button = None
        self.update_button = None
        self.start_button = None
        self.deploy_all_button = None
        self.live_view_button = None
        self.outage_button = None
        self.quit_button = None
        self.select_entity_type_label = None
        self.select_action_label = None
        self.customer_account_label = None
        self.text_box_button = None
        self.input_prompt_button = None
        self.save_login_details_button = None
        self.input_prompt_label = None
        self._text_box_data = None

        self._emphasis = {}  # widget -> size offset; these buttons are always bold, whatever the font setting
        self._blink_id = None
        self._blink_dark = False
        self._input_window_open = False
        self._player_browser = None
        self._csv_running = False
        self._login_check_running = False
        self._update_running = False  # a check, or a download, of a newer version is going on

        self._admin_row = 0
        self._profile_row = 1
        self._login_row = 2
        self._password_row = 3
        self._save_button_row = 4
        self._outage_row = 5
        self._entity_type_row = 6
        self._action_row = 7
        self._text_box_row = 8
        self._action_buttons_row = 9

        self.setup_ui()
        self.fill_default_login_details()
        self.update_action_buttons()
        self.bind("<FocusIn>", self.on_focus_in)
        self.resizable(False, False)
        if check_updates_at_start:
            self.after(AUTO_UPDATE_DELAY_MS, self.start_update_check, True)

    def load_actions(self):
        return entity_actions(self.lang.get_message("actions"))

    def setup_icons(self):
        set_window_icon(self)

    def setup_ui(self):
        # The values of these three decide whether the buttons that start something can be used
        self.account_var, self.login_var, self.password_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for variable in (self.account_var, self.login_var, self.password_var):
            variable.trace_add("write", lambda *_: self.update_action_buttons())
        self.create_combobox(self, "customer_account", self._admin_row,
                             "option_choose_administration", self.on_account_selected, self.account_var, columnspan=3)
        self.create_combobox(self, "name", self._profile_row,
                             "option_choose_name", self.on_login_selected, self.login_var, columnspan=3)
        self.create_label_and_entry(self, "password", self._password_row,
                                    "input_for_password", textvariable=self.password_var, show="*")
        self.create_button(self, "save_login_details", self._save_button_row,
                           self.save_login_details, columnspan=3)
        self.create_combobox(self, "select_entity_type", self._entity_type_row,
                             "entity_type_combobox", self.on_entity_selected,
                             self.entity_type_var, list(self.entity_actions.keys()), columnspan=3)
        self.create_combobox(self, "select_action", self._action_row,
                             "option_choose_action", self.on_action_selected, self.action_var, columnspan=3)
        self.setup_action_list()
        self.input_prompt_button = self.create_emphasised_button("input_prompt", self._generate_textbox, GREEN,
                                                                 size_offset=0)
        self.add_tooltip(self.input_prompt_button, "tip_input_prompt")
        self.input_prompt_button.grid(row=self._text_box_row, column=1, columnspan=3, padx=5, pady=5, sticky="w")
        # Each group sits in its own frame: buttons sharing grid columns with wider ones were pushed far apart
        for row, add_command, remove_command, tips in (
                (self._admin_row, self.open_add_account_dialog, self.remove_account,
                 ("tip_add_account", "tip_remove_account")),
                (self._profile_row, self.open_add_login_dialog, self.remove_login,
                 ("tip_add_login", "tip_remove_login"))):
            group = tk.Frame(self)
            group.grid(row=row, column=4, sticky="e")
            self.create_symbol_button(group, 0, "+", add_command, tips[0])
            self.create_symbol_button(group, 1, "\u2212", remove_command, tips[1])
        self.create_action_buttons()
        self.refresh_ui()
        self.fill_default_login_details()
        self.restore_last_action()

    def create_combobox(self, parent, label_key, row, var_name, command, text_var=None, values=None, columnspan=1):
        pad_x, pad_y = DROPDOWN_PAD_X, 2
        label = ttk.Label(parent, text=self.lang.get_message(label_key), font=self.font)
        label.grid(row=row, column=0, padx=pad_x, pady=pad_y, sticky="w")
        combobox = ttk.Combobox(parent, textvariable=text_var, state="readonly", width=40)
        combobox.grid(row=row, column=1, columnspan=columnspan, padx=pad_x, pady=pad_y, sticky="w")
        combobox.config(font=self.font)
        combobox.bind("<<ComboboxSelected>>", command)
        if values:
            combobox['values'] = values
        setattr(self, f"{label_key}_label", label)
        setattr(self, var_name, combobox)

    def create_label_and_entry(self, parent, label_key, row, var_name, **entry_options):
        pad_x, pad_y = 3, 2
        label = ttk.Label(parent, text=self.lang.get_message(label_key), font=self.font)
        label.grid(row=row, column=0, padx=pad_x, pady=pad_y, sticky="w")
        entry = ttk.Entry(parent, **entry_options, width=40)
        entry.grid(row=row, column=1, columnspan=3, padx=pad_x, pady=pad_y, sticky="w")
        setattr(self, f"{label_key}_label", label)
        setattr(self, var_name, entry)

    def add_tooltip(self, widget, key):
        Tooltip(widget, lambda: self.lang.get_message(key))

    def create_button(self, parent, label_key, row, command, column=1, columnspan=1):
        pad_x, pad_y = 5, 5
        button = tk.Button(parent, text=self.lang.get_message(label_key), font=self.font, command=command)
        self.add_tooltip(button, f"tip_{label_key}")
        button.grid(row=row, column=column, columnspan=columnspan, padx=pad_x, pady=pad_y, sticky="w")
        setattr(self, f"{label_key}_button", button)

    def create_symbol_button(self, parent, column, symbol, command, tip_key):
        button = tk.Button(parent, text=symbol, font=self.font, width=2, command=command)
        self.add_tooltip(button, tip_key)
        button.grid(row=0, column=column, padx=5, pady=2, sticky="w")

    def create_label_and_button(self, parent, label_key, row, button_var_name, command, columnspan=1):
        pad_x, pad_y = 5, 5
        label = ttk.Label(parent, text=self.lang.get_message(label_key), font=self.font)
        label.grid(row=row, column=0, padx=pad_x, pady=pad_y, sticky="w")
        button = tk.Button(parent, text=self.lang.get_message(label_key), font=self.font, command=command)
        button.grid(row=row, column=1, columnspan=columnspan, padx=pad_x, pady=pad_y, sticky="w")
        setattr(self, f"{label_key}_label", label)
        setattr(self, button_var_name, button)

    def create_action_buttons(self):
        pad_x, pad_y = 5, 5
        self.quit_button = self.create_emphasised_button("quit", self.quit, RED, size_offset=0)
        self.quit_button.grid(row=self._action_buttons_row, column=0, padx=pad_x, pady=pad_y, sticky="w")
        self.add_tooltip(self.quit_button, "tip_quit")
        # One row for both groups: "Help" and "Update" on the left, "Settings" and "Start" on the right. They are in a frame
        # of their own, so that the window is as wide as the two groups need and they never overlap, in any language or font
        bottom_row = tk.Frame(self)
        bottom_row.grid(row=self._action_buttons_row, column=1, columnspan=4, sticky="ew")
        bottom_row.grid_columnconfigure(0, weight=1)
        help_buttons = tk.Frame(bottom_row)
        help_buttons.grid(row=0, column=0, sticky="w")
        self.help_button = tk.Button(help_buttons, text=self.lang.get_message("help"), font=self.font,
                                     command=self.open_help)
        self.help_button.grid(row=0, column=0, padx=pad_x, pady=pad_y, sticky="w")
        self.add_tooltip(self.help_button, "tip_help")
        self.update_button = tk.Button(help_buttons, text=self.lang.get_message("update"), font=self.font,
                                       command=self.start_update_check)
        self.update_button.grid(row=0, column=1, padx=pad_x, pady=pad_y, sticky="w")
        self.add_tooltip(self.update_button, "tip_update")
        # Its right edge is the one of the "+ -" buttons
        right_buttons = tk.Frame(bottom_row)
        right_buttons.grid(row=0, column=1, padx=(BOTTOM_ROW_GAP_X, 0), sticky="e")
        self.create_button(right_buttons, "settings", 0, self.open_settings_window, column=0)
        self.start_button = self.create_emphasised_button("start", self.execute_action, GREEN, size_offset=2,
                                                          parent=right_buttons, padding_x=DEPLOY_PADDING_X)
        self.start_button.grid(row=0, column=1, padx=pad_x, pady=pad_y, sticky="w")
        self.add_action_tooltip(self.start_button, "tip_start", needs_action=True)
        # Above "Live-view", same font, size and right edge
        self.outage_button = self.create_emphasised_button("outages", self.outages, PURPLE, size_offset=2,
                                                            padding_x=DEPLOY_PADDING_X)
        self.outage_button.grid(row=self._outage_row, column=1, columnspan=4, padx=pad_x, sticky="e")
        self.add_action_tooltip(self.outage_button, "tip_outages")
        # Right of the drop-downs, in line with the right edge of "Start"; same font and size as it
        self.live_view_button = self.create_emphasised_button("live_view", self.live_view, BLUE, size_offset=2,
                                                              padding_x=DEPLOY_PADDING_X)
        self.live_view_button.grid(row=self._entity_type_row, column=1, columnspan=4, padx=pad_x, pady=(3, 0),
                                   sticky="e")
        self.add_action_tooltip(self.live_view_button, "tip_live_view")
        self.deploy_all_button = self.create_emphasised_button("deploy_all", self.deploy_all, YELLOW, size_offset=2,
                                                               padding_x=DEPLOY_PADDING_X)
        self.deploy_all_button.grid(row=self._action_row, column=1, columnspan=4, padx=pad_x, pady=(3, 0), sticky="e")
        self.add_action_tooltip(self.deploy_all_button, "tip_deploy_all")
        self._equalize_action_buttons()
        self.update_action_buttons()

    def emphasised_font(self, size_offset):
        return (self.font[0], self.font[1] + size_offset, "bold")

    def create_emphasised_button(self, label_key, command, colors, size_offset, parent=None, **options):
        button = make_color_button(parent or self, self.lang.get_message(label_key), command,
                                   self.emphasised_font(size_offset), colors, **options)
        self._emphasis[button] = size_offset
        return button

    def has_input(self):
        return bool(self._text_box_data and self._text_box_data.strip())

    def start_blinking(self):
        """Until the user has entered the input, the Input Prompt button alternates between light and dark green."""
        if self._blink_id is None and not self._input_window_open:
            self._blink_id = self.after(BLINK_INTERVAL_MS, self._blink)

    def _blink(self):
        self._blink_dark = not self._blink_dark
        set_button_colors(self.input_prompt_button, GREEN_DARK if self._blink_dark else GREEN)
        self._blink_id = self.after(BLINK_INTERVAL_MS, self._blink)

    def stop_blinking(self):
        if self._blink_id is not None:
            self.after_cancel(self._blink_id)
            self._blink_id = None
        self._blink_dark = False
        set_button_colors(self.input_prompt_button, GREEN)

    def open_settings_window(self):
        settings_window = SettingsWindow(self, self.lang)
        self.wait_window(settings_window)

    def setup_action_list(self):
        """
        Prepares the list of actions: its entries are coloured by what they do (see ACTION_TINTS), and resting the
        pointer on one shows what it does. The list is filled again every time it opens, which drops the colours, so
        they are put on when its window appears.
        """
        popdown = self.tk.call("ttk::combobox::PopdownWindow", self.option_choose_action)
        self.tk.call("bind", popdown, "<Map>", self.register(lambda: self._prepare_action_list(popdown)))
        self._action_list_help = ListTooltip(TclListbox(self, f"{popdown}.f.l"), self._action_description)

    def _action_description(self, index: int) -> str:
        labels = self.option_choose_action["values"]
        action = self.entity_actions.get(self.entity_type_var.get(), {}).get(labels[index]) if 0 <= index < len(labels) else None
        return action_descriptions.describe(action, self.lang.language) if action else ""

    def _prepare_action_list(self, popdown: str):
        self._action_list_help.watch()
        listbox = f"{popdown}.f.l"
        actions = self.entity_actions.get(self.entity_type_var.get(), {})
        labels = self.option_choose_action["values"]
        for index, label in enumerate(labels):
            colors = ACTION_TINTS[action_kind(actions.get(label, ""))]
            # the entry that is selected or under the pointer keeps its colour, one shade darker
            self.tk.call(listbox, "itemconfigure", index, "-background", colors.normal, "-foreground", colors.text,
                         "-selectbackground", colors.pressed, "-selectforeground", colors.text)
        # The list is as wide as the box, and the scrollbar takes some of that: a long label would be cut off
        font = tkfont.Font(font=self.tk.call(listbox, "cget", "-font"))
        needed = max((font.measure(label) for label in labels), default=0) + LIST_EXTRA_WIDTH
        if needed > int(self.tk.call("winfo", "width", popdown)):
            self.tk.call("wm", "geometry", popdown, f"{needed}x{self.tk.call('winfo', 'height', popdown)}")

    def update_action_selection(self, _=None):
        entity_type = self.entity_type_var.get()
        actions_dict = self.entity_actions.get(entity_type, {})
        actions = list(actions_dict)
        self.option_choose_action['values'] = actions
        if actions:
            default_label = next((label for label, action in actions_dict.items()
                                  if action == "set_deploy_all_players"), actions[0])
            self.option_choose_action.set(default_label)
        else:
            self.option_choose_action.set('')

        self._text_box_data = None
        self.update_input_button()
        self.update_action_buttons()

    def on_entity_selected(self, _=None):
        self.update_action_selection()
        self.remember_action()

    def on_action_selected(self, _=None):
        self.reset_data()
        self.remember_action()

    def remember_action(self):
        """Stores the last used category and action, so the next start opens them again."""
        self.sync_from_disk()
        if accounts.remember_action(self.all_data, self.entity_type_var.get(), self.current_action() or ""):
            self.save_account_configs()

    def restore_last_action(self):
        """Selects the category and action of the last use. A removing action is not restored (see remember_action)."""
        entity_type, action = accounts.last_action(self.all_data)
        if entity_type not in self.entity_actions:
            return
        self.entity_type_var.set(entity_type)
        self.update_action_selection()
        label = next((label for label, key in self.entity_actions[entity_type].items() if key == action), None)
        if label and action_kind(action) != "remove":
            self.option_choose_action.set(label)
            self.reset_data()

    def reset_data(self, _=None):
        self._text_box_data = None
        self.update_input_button()

    def current_action(self):
        """The key of the selected action, or None."""
        return self.entity_actions.get(self.entity_type_var.get(), {}).get(self.option_choose_action.get())

    def update_input_button(self):
        """Shows the "Input Prompt" button only when the selected action takes input."""
        action = self.current_action()
        button = self.input_prompt_button
        if action and action_needs_input(action):
            button.grid()
            if self.has_input():
                self.stop_blinking()
            else:
                self.start_blinking()
        else:
            button.grid_remove()
            self.stop_blinking()
        # The row keeps its height either way, so the window does not jump when the button comes and goes
        self.grid_rowconfigure(self._text_box_row, minsize=button.winfo_reqheight() + 10)

    def refresh_ui(self):
        """Refreshes the entire UI to reflect changes in language or other settings."""
        self.lang = LanguageManager(language=self.lang.language, config_path=self.lang.config_path)
        self.close_player_browser()  # its texts are in the old language
        self.reload_account_configs()
        self.entity_actions = self.load_actions()

        self.title(f"{self.lang.get_message('title')} {VERSION}")

        self.refresh_all_widgets_text()

        self.update_all_widgets_font()

        self.refresh_dropdowns()

        self.fill_default_login_details()
        self.update_action_buttons()

    def refresh_all_widgets_text(self):
        """Refreshes the text of all labels, buttons, and other UI elements."""
        # Refreshing Labels
        if self.customer_account_label:
            self.customer_account_label.config(text=self.lang.get_message("customer_account"))
        if self.name_label:
            self.name_label.config(text=self.lang.get_message("name"))
        if self.password_label:
            self.password_label.config(text=self.lang.get_message("password"))
        if self.select_entity_type_label:
            self.select_entity_type_label.config(text=self.lang.get_message("select_entity_type"))
        if self.select_action_label:
            self.select_action_label.config(text=self.lang.get_message("select_action"))
        if self.text_box_label:
            self.text_box_label.config(text=self.lang.get_message("input_prompt"))
        if self.input_prompt_label:
            self.input_prompt_label.config(text=self.lang.get_message("input_prompt"))

        # Refreshing Buttons
        if self.save_button:
            self.save_button.config(text=self.lang.get_message("save_login_details"))
        if self.start_button:
            self.start_button.config(text=self.lang.get_message("start"))
        if self.quit_button:
            self.quit_button.config(text=self.lang.get_message("quit"))
        if self.settings_button:
            self.settings_button.config(text=self.lang.get_message("settings"))
        if self.help_button:
            self.help_button.config(text=self.lang.get_message("help"))
        if self.update_button:
            self.update_button.config(text=self.lang.get_message("update"))
        if self.save_login_details_button:
            self.save_login_details_button.config(text=self.lang.get_message("save_login_details"))
        if self.input_prompt_button:
            self.input_prompt_button.config(text=self.lang.get_message("input_prompt"))
        if self.deploy_all_button:
            self.deploy_all_button.config(text=self.lang.get_message("deploy_all"))
        if self.live_view_button:
            self.live_view_button.config(text=self.lang.get_message("live_view"))
        if self.outage_button:
            self.outage_button.config(text=self.lang.get_message("outages"))
        self._equalize_action_buttons()

    def update_all_widgets_font(self):
        """Updates the font for all widgets to the current font settings."""
        def update(parent):
            for widget in parent.winfo_children():
                self._update_widget_font(widget)
                update(widget)

        update(self)
        self._equalize_action_buttons()  # the size follows the font

    def _update_widget_font(self, widget):
        """Applies the current font to a given widget, if applicable."""
        try:
            widget.configure(font=self.emphasised_font(self._emphasis[widget]) if widget in self._emphasis
                             else self.font)
        except tk.TclError:
            pass

    def refresh_dropdowns(self):
        """Refreshes the values in all comboboxes based on current settings."""
        self.option_choose_administration.configure(font=self.font)
        self.option_choose_name.configure(font=self.font)
        self.option_choose_action.configure(font=self.font)
        self.entity_type_combobox.configure(font=self.font)

        self.option_choose_administration['values'] = sorted(list(self.account_data.keys()))
        self.entity_type_combobox['values'] = list(self.entity_actions.keys())

        # Clear selections to ensure they are reset
        self.option_choose_administration.set('')
        self.option_choose_name.set('')
        self.option_choose_action.set('')
        self.entity_type_var.set('')

        # Update action options based on the selected entity type
        self.update_action_selection()

    def execute_action(self):
        administration = self.option_choose_administration.get()
        url = self.account_data[administration].get("url", "")
        account_name = self.option_choose_name.get()
        password = self.input_for_password.get()
        entity_type = self.entity_type_var.get()
        action_name = self.option_choose_action.get()
        data = self._text_box_data
        login = self.account_data[administration].get("names", {})[account_name]["login"]
        action = self.entity_actions.get(entity_type, {}).get(action_name)
        if entity_type in self.entity_actions and action:
            action_map = {
                "get_": self.perform_get_action,
                "set_": self.perform_set_action,
                "remove_": self.perform_remove_action,
                "create_": self.perform_create_action,
                "show_": self.perform_show_action,
            }
            for prefix, method in action_map.items():
                if action.startswith(prefix):
                    # noinspection PyArgumentList
                    method(action, url, login, password, data)

    @staticmethod
    def input_missing(data):
        """No input, or only blanks: what remains when the user leaves nothing but the template."""
        return data is None or not data.strip()

    def perform_get_action(self, action, url, login, password, _):
        if "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("login_info"))
            return
        self.generate_csv(action[4:], url, login, password)

    def add_action_tooltip(self, button, key, needs_action=False):
        """While the button cannot be used its tooltip says what is missing."""
        def text():
            if not self.can_start_actions():
                return self.lang.get_message("tip_login_required")
            if needs_action and not self.current_action():
                return self.lang.get_message("tip_choose_action")
            return self.lang.get_message(key)
        Tooltip(button, text)

    def can_start_actions(self) -> bool:
        """An account, one of its logins and a password are there: what every action needs."""
        names = self.account_data.get(self.account_var.get(), {}).get("names", {})
        return self.login_var.get() in names and bool(self.password_var.get())

    def update_action_buttons(self):
        """Start, Live-view, Deploy all and Výpadky are grey until an account, a login and a password are there."""
        enabled = self.can_start_actions()
        for button, colors, needs_action in ((self.start_button, GREEN, True), (self.deploy_all_button, YELLOW, False),
                                             (self.live_view_button, BLUE, False), (self.outage_button, PURPLE, False)):
            if button is not None:
                # Start runs the selected action: with none selected it would do nothing
                set_button_enabled(button, enabled and (bool(self.current_action()) or not needs_action), colors)

    def _equalize_action_buttons(self):
        self._equalize_help_buttons()
        buttons = [self.start_button, self.deploy_all_button, self.live_view_button, self.outage_button]
        if all(buttons):
            equalize_widths(*buttons)
            self._ensure_gap_from_dropdowns()

    def _equalize_help_buttons(self):
        """
        "Help" and "Update" are equally wide: the width of the wider one, measured in pixels. (A width in characters
        would make both wider than the longer text needs, and the bottom row of buttons would not fit in the window.)
        """
        buttons = [button for button in (self.help_button, self.update_button) if button]
        if len(buttons) < 2:
            return
        for button in buttons:
            button.configure(width=0)
            button.grid_configure(ipadx=0)
        self.update_idletasks()
        widest = max(button.winfo_reqwidth() for button in buttons)
        for button in buttons:
            button.grid_configure(ipadx=(widest - button.winfo_reqwidth()) // 2)

    def _ensure_gap_from_dropdowns(self):
        """Live-view/Deploy all only reserve their own padx as a floor within whatever width their row already
        has; a wide enough button (native on Windows, unlike the pixel-measured canvas one on macOS) can already
        fill that row on its own and leave no real gap before the category/action drop-down, or even touch it.
        Growing a plain, otherwise-unclaimed column (tried column 2) does not help: Tk's grid steals the extra
        back from a sibling column that the drop-down's own 3-column span also touches, leaving the drop-down's
        total footprint - and so the gap - unchanged. The drop-down's own right padx is not up for stealing like
        that, so growing it is what actually reserves the space.

        That holds while the drop-down is what makes the window as wide as it is. When something else does (the row
        of buttons at the bottom, in a language with long names), the columns the drop-down spans have room to spare
        and its padx is absorbed there. So the last column, which the drop-down does not span and which has contents of its
        own, is made as much wider as is missing. The window gets wider, the buttons on the right move away from the
        drop-downs, and the "+" and "-" buttons stay in line with "Start" (they sit at the right edge of that column).

        Uses winfo_x(), position within this window, not winfo_rootx() (position on the screen): the latter is
        only valid once the window manager has actually placed the window, which on some platforms can still be
        pending here and reads back as 0 or another placeholder, producing a wild, bogus deficit. Reset to
        DROPDOWN_PAD_X before every measurement, rather than measuring on top of whatever a previous call may
        have already added, so this is a fresh, idempotent computation every time, not one that could compound
        an earlier bad reading call after call."""
        for box, button in ((self.entity_type_combobox, self.live_view_button),
                            (self.option_choose_action, self.deploy_all_button)):
            left = box.grid_info()["padx"]
            left = left[0] if isinstance(left, tuple) else left
            box.grid_configure(padx=(left, DROPDOWN_PAD_X))
        self.grid_columnconfigure(LAST_COLUMN, minsize=0)
        self.update_idletasks()
        for box, button in ((self.entity_type_combobox, self.live_view_button),
                            (self.option_choose_action, self.deploy_all_button)):
            gap = button.winfo_x() - (box.winfo_x() + box.winfo_width())
            # A sanity cap: a real deficit here is at most a couple of button widths, never more - anything
            # bigger means the measurement above is not trustworthy, so it is safer to leave the default padx
            # than to apply a runaway one.
            deficit = ACTION_ROW_GAP_X - gap
            if 0 < deficit <= 300:
                left = box.grid_info()["padx"]
                left = left[0] if isinstance(left, tuple) else left
                box.grid_configure(padx=(left, DROPDOWN_PAD_X + deficit))
        self.update_idletasks()
        missing = max(ACTION_ROW_GAP_X - (button.winfo_x() - (box.winfo_x() + box.winfo_width()))
                      for box, button in ((self.entity_type_combobox, self.live_view_button),
                                          (self.option_choose_action, self.deploy_all_button)))
        if 0 < missing <= 300:  # what the padx did not reserve (it did where the drop-down makes the window as wide as it is)
            self.grid_columnconfigure(LAST_COLUMN, minsize=self.grid_bbox(column=LAST_COLUMN, row=0)[2] + missing)

    def _selected_connection(self):
        """(url, login, password) of the selected account and login, or None with a hint when no login is selected."""
        administration = self.option_choose_administration.get()
        names = self.account_data.get(administration, {}).get("names", {})
        account_name = self.option_choose_name.get()
        if account_name not in names:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("login_info"))
            return None
        return (self.account_data[administration].get("url", ""), names[account_name]["login"],
                self.input_for_password.get())

    def deploy_all(self):
        """The action "Deploy - all players" on one button: no selection and no confirmation, only the login."""
        connection = self._selected_connection()
        if connection:
            self.perform_set_action("set_deploy_all_players", *connection, None)

    def live_view(self):
        """The action "Players - Screenshot - view" on one button."""
        connection = self._selected_connection()
        if connection:
            self.perform_show_action("show_player_snapshots", *connection, None)

    def outages(self):
        """The action "Live-view", limited to active players ("aktivni" in the name) that are offline, newest
        reported first: every click reapplies the filter and sort, even if the window is already open."""
        connection = self._selected_connection()
        if not connection:
            return
        url, login, password = connection
        if "" in (login, password):
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("login_info"))
            return
        self.open_player_browser(url, login, password, refresh_if_open=True,
                                 on_open=lambda browser: browser.set_filter_and_sort(
                                     name="aktivni", online=False, sort_column="reported", sort_descending=True))

    def perform_show_action(self, action, url, login, password, _):
        if "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("login_info"))
            return
        self.open_player_browser(url, login, password)

    def open_player_browser(self, url, login, password, on_open=None, refresh_if_open=False):
        """One window at a time: the same account and login brings the open one to the front. `on_open`, when
        given, is called with the window every time it is shown, whether newly created or brought forward;
        `refresh_if_open` makes a window that was already open fetch the players again (what it shows can be old)."""
        browser = self._player_browser
        if browser is not None and browser.winfo_exists():
            if browser.is_for(url, login, password):  # with another password it is the window of a login that failed
                browser.deiconify()
                browser.lift()
                browser.focus_force()
                if refresh_if_open:
                    browser.refresh()
                if on_open:
                    on_open(browser)
                return
            browser.destroy()
        self.sync_from_disk()
        account = self.option_choose_administration.get()
        self._player_browser = PlayerBrowser(
            self, url=url, login=login, password=password, account_name=account,
            column_widths=accounts.player_columns(self.all_data, account),
            save_column_widths=lambda widths: self.save_player_columns(account, widths),
            hidden_columns=accounts.hidden_player_columns(self.all_data, account),
            save_hidden_columns=lambda hidden: self.save_hidden_player_columns(account, hidden),
            font_size=accounts.player_font_size(self.all_data, account),
            save_font_size=lambda size: self.save_player_font_size(account, size),
            window_geometry=accounts.player_window_geometry(self.all_data, account),
            save_window_geometry=lambda geometry: self.save_player_window_geometry(account, geometry),
            snapshot_size=accounts.snapshot_window_size(self.all_data, account),
            save_snapshot_size=lambda size: self.save_snapshot_window_size(account, size))
        if on_open:
            on_open(self._player_browser)

    def save_player_window_geometry(self, account, geometry):
        """The size and position of the player table window are remembered per account too."""
        self.sync_from_disk()
        if account in self.account_data:
            accounts.set_player_window_geometry(self.all_data, account, geometry)
            self.save_account_configs()

    def save_snapshot_window_size(self, account, size):
        """The size the user gave the snapshot windows is remembered per account too."""
        self.sync_from_disk()
        if account in self.account_data:
            accounts.set_snapshot_window_size(self.all_data, account, size)
            self.save_account_configs()

    def save_player_font_size(self, account, size):
        """The font size of the player table is remembered per account as well."""
        self.sync_from_disk()
        if account in self.account_data:
            accounts.set_player_font_size(self.all_data, account, size)
            self.save_account_configs()

    def save_hidden_player_columns(self, account, hidden):
        """Which optional columns of the player table are switched off is remembered per account too."""
        self.sync_from_disk()
        if account in self.account_data:
            accounts.set_hidden_player_columns(self.all_data, account, hidden)
            self.save_account_configs()

    def save_player_columns(self, account, widths):
        """The column widths the user set in the player table are remembered per account."""
        self.sync_from_disk()
        if account in self.account_data:
            accounts.set_player_columns(self.all_data, account, widths)
            self.save_account_configs()

    def close_player_browser(self):
        if self._player_browser is not None and self._player_browser.winfo_exists():
            self._player_browser.destroy()
        self._player_browser = None

    def perform_set_action(self, action, url, login, password, data):
        if not action_needs_input(action):
            data = NO_INPUT_PLACEHOLDER
        if self.input_missing(data) or "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("missing_data_or_login"))
            return
        self.open_action_log_box(action[4:], url, login, password, data)

    def perform_remove_action(self, action, url, login, password, data):
        if not action_needs_input(action):
            data = NO_INPUT_PLACEHOLDER
        if self.input_missing(data) or "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("missing_data_or_login"))
            return
        self.open_action_log_box(action, url, login, password, data)

    def perform_create_action(self, action, url, login, password, data):
        if self.input_missing(data) or "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("missing_data_or_login"))
            return
        self.open_action_log_box(action, url, login, password, data)

    def csv_file_path(self, task_type: str, kind: str = "", account: str = None) -> str:
        """Where a CSV file goes: the downloads folder, named after the account, `kind` (e.g. backup), the data and the time."""
        date = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        administration = self.option_choose_administration.get() if account is None else account
        account_part = re.sub(r'[^\w.-]+', '_', administration).strip('._') or 'account'  # no path, no odd characters
        kind_part = f"{kind}-" if kind else ""
        return os.path.join(get_download_path(), f'{account_part}-{kind_part}{task_type}-{date}.csv')

    def generate_csv(self, task_type, url, login, password):
        file_path = self.csv_file_path(task_type)
        csv_task = CSVTaskFactory.create_task(
            task_type=task_type,
            log_handler=None,
            url=url,
            login=login,
            password=password
        )
        if self._csv_running:
            return
        self._csv_running = True
        outcome = queue.Queue()

        def work():  # reading the server takes seconds, so not in the thread of the window; it touches nothing of Tk
            try:
                csv_task.generate_csv(file_path)
                outcome.put(None)
            except Exception as error:
                outcome.put(error)

        self.config(cursor="watch")
        threading.Thread(target=work, daemon=True).start()
        self._finish_csv(outcome, file_path)

    def _finish_csv(self, outcome: queue.Queue, file_path: str):
        try:
            error = outcome.get_nowait()
        except queue.Empty:
            self.after(CSV_POLL_MS, self._finish_csv, outcome, file_path)
            return
        self._csv_running = False
        self.config(cursor="")
        if error is None:
            messagebox.showinfo(self.lang.get_message("info_title"),
                                self.lang.get_message("file_saved", file_path=file_path))
        else:
            messagebox.showwarning(self.lang.get_message("warning_title"), self.csv_error_text(error))

    def csv_error_text(self, error: Exception) -> str:
        if isinstance(error, LoginError):
            return self.lang.get_message("login_error")
        if isinstance(error, OSError) and not isinstance(error, requests.exceptions.RequestException):
            return self.lang.get_message("file_save_error")  # the file could not be written
        return self.lang.get_message("csv_failed", error=str(error))

    def open_action_log_box(self, processor_type, url, login, password, data):
        extra_settings = None
        if processor_type.startswith("deploy_"):
            extra_settings = {
                "batch_size": self.all_data.get("deploy_batch_size", 10),
                "batch_interval": self.all_data.get("deploy_batch_interval", 3),
                "account_name": self.option_choose_administration.get()
            }
        elif processor_type == "player_snapshot":
            extra_settings = {"output_dir": os.path.join(get_download_path(), "DSMediaplay_snapshots")}
        account = self.option_choose_administration.get()  # read here: the backup is written by the thread of the log
        log_box = LoggingTextBoxFactory.create_log_box(
            processor_type=processor_type,
            master=self,
            url=url,
            login=login,
            password=password,
            data=data,
            extra_settings=extra_settings,
            backup_path=lambda task_type: self.csv_file_path(task_type, "backup", account)
        )
        self.wait_window(log_box)

    def _config_stamp(self):
        try:
            stat = os.stat(self.config_file)
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def load_account_configs(self):
        stamp = self._config_stamp()  # taken before reading: a change during the read is noticed next time
        if stamp is None:
            return {"default": ["", ""], "logins": {}}
        with open(self.config_file, "r", encoding='utf-8') as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError("the account list is not a JSON object")
        data.setdefault("logins", {})
        data.setdefault("default", ["", ""])
        self._file_stamp = stamp
        return data

    def save_account_configs(self):
        """Written to a temporary file first, so a crash or a concurrent reader never sees a half-written file."""
        directory = os.path.dirname(os.path.abspath(self.config_file))
        handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding='utf-8') as file:
                json.dump(self.all_data, file, indent=4, ensure_ascii=False)
            os.replace(temporary, self.config_file)
        except BaseException:
            os.unlink(temporary)
            raise
        self._file_stamp = self._config_stamp()

    def sync_from_disk(self):
        """
        Picks up changes made to the config file outside the app (Edit JSON, a text editor, another instance).
        Called before every change, so a save never overwrites them with stale in-memory data.
        Returns True when the file was re-read; an unreadable file is ignored and the app keeps its data.
        """
        if self._config_stamp() == self._file_stamp:
            return False
        try:
            data = self.load_account_configs()
        except (OSError, ValueError):
            return False
        self.all_data, self.account_data, self.default = data, data["logins"], data["default"]
        self.refresh_selection_lists()
        return True

    def refresh_selection_lists(self):
        """Updates the drop-down lists after the data changed, keeping the current selection while it is valid."""
        account = self.option_choose_administration.get()
        self.option_choose_administration['values'] = sorted(self.account_data.keys())
        if account not in self.account_data:
            self.option_choose_administration.set("")
            account = ""
        login = self.option_choose_name.get()
        names = sorted(self.account_data.get(account, {}).get("names", {}).keys())
        self.option_choose_name.config(values=names)
        if login not in names:
            self.option_choose_name.set("")
        self.fill_password_details(keep_typed=login in names)
        self.update_action_buttons()  # the data may have changed without any of the fields changing

    def on_focus_in(self, event):
        if event.widget is self:  # the window itself came to the front, e.g. after Edit JSON or a text editor
            self.sync_from_disk()

    def recover_unreadable_config(self, language_file: str) -> dict:
        """
        The account list is damaged (or cannot be read). Nothing is thrown away: the user is asked whether to keep a
        copy of the file next to it and go on with an empty list (the passwords stay in the credential store, so
        adding the accounts again is all that is left to do), or to quit and look at the file. The language of the
        user is not known here (it is in that file), so the question is asked in both.
        """
        backup = f"{self.config_file}.unreadable-{datetime.now():%Y%m%d-%H%M%S}"
        languages = [LanguageManager(language=code, config_path=language_file) for code in ("cz", "en")]

        def say(key: str, separator: str = "\n\n", **values) -> str:
            return separator.join(lang.get_message(key, **values) for lang in languages)

        title = say("config_unreadable_title", " / ")
        self.withdraw()
        keep_going = messagebox.askyesno(title, say("config_unreadable_text", file=self.config_file, backup=backup),
                                         icon="error", default="yes")
        if keep_going:
            try:
                os.replace(self.config_file, backup)
            except OSError as error:
                messagebox.showerror(title, say("config_unreadable_backup_failed", error=error))
                keep_going = False
        if not keep_going:
            self.destroy()
            raise SystemExit(1)
        self.deiconify()
        self._file_stamp = None
        return {"default": ["", ""], "logins": {}}

    def ask_language(self):
        """First start only: the choice is stored in the config, so it is never asked again."""
        self.withdraw()
        dialog = LanguageDialog(self)
        self.wait_window(dialog)
        self.deiconify()
        if dialog.language:
            self.all_data["lang"] = dialog.language
            self.save_account_configs()

    def open_add_account_dialog(self):
        EntryDialog(self, self.lang.get_message("add_account"),
                    [self.lang.get_message("account_name"), self.lang.get_message("account_url")],
                    self.add_account)

    def add_account(self, name, url):
        self.sync_from_disk()
        name = accounts.add_account(self.all_data, name, url)
        self.save_account_configs()
        self.option_choose_administration['values'] = sorted(self.account_data.keys())
        self.option_choose_administration.set(name)
        self.on_account_selected()

    def open_add_login_dialog(self):
        if not self.option_choose_administration.get():
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("select_account_first"))
            return
        EntryDialog(self, self.lang.get_message("add_login"), [self.lang.get_message("login")], self.add_login)

    def add_login(self, login):
        self.sync_from_disk()
        login = accounts.add_login(self.all_data, self.option_choose_administration.get(), login)
        self.save_account_configs()
        self.fill_login_details()
        self.option_choose_name.set(login)
        self.on_login_selected()

    def remove_login(self):
        self.sync_from_disk()
        account = self.option_choose_administration.get()
        name = self.option_choose_name.get()
        if name not in self.account_data.get(account, {}).get("names", {}):
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("select_login_first"))
            return
        if not messagebox.askyesno(self.lang.get_message("warning_title"),
                                   self.lang.get_message("remove_login_confirm", login=name, account=account)):
            return
        self.close_player_browser_of(self.account_data[account].get("url", ""),
                                     {self.account_data[account]["names"][name]["login"]})
        unused = accounts.remove_login(self.all_data, account, name)
        self.save_account_configs()
        self.delete_passwords(unused)
        self.fill_login_details()

    def remove_account(self):
        self.sync_from_disk()
        account = self.option_choose_administration.get()
        if account not in self.account_data:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("select_account_first"))
            return
        count = len(self.account_data[account].get("names", {}))
        if not messagebox.askyesno(self.lang.get_message("warning_title"),
                                   self.lang.get_message("remove_account_confirm", account=account, count=count)):
            return
        self.close_player_browser_of(self.account_data[account].get("url", ""),
                                     {details.get("login") for details in self.account_data[account]["names"].values()})
        unused = accounts.remove_account(self.all_data, account)
        self.save_account_configs()
        self.delete_passwords(unused)
        self.default = self.all_data["default"]
        self.option_choose_administration['values'] = sorted(self.account_data.keys())
        self.option_choose_administration.set("")
        self.option_choose_name.config(values=[])
        self.option_choose_name.set("")
        self.input_for_password.delete(0, tk.END)

    def close_player_browser_of(self, url: str, logins: set):
        """A player window of a login that has been removed would keep its password and go on refreshing."""
        browser = self._player_browser
        if browser is not None and browser.winfo_exists() and browser.connection[0] == url \
                and browser.connection[1] in logins:
            browser.destroy()

    def delete_passwords(self, unused):
        """Deletes the passwords of removed logins; a store failure is reported once, the removal stays."""
        error = None
        for url, login in unused:
            try:
                credentials.delete_password(url, login)
            except credentials.KeyringError as failure:
                error = failure
        if error:
            messagebox.showwarning(self.lang.get_message("warning_title"),
                                   self.lang.get_message("credential_delete_failed", error=str(error)))

    def import_legacy_accounts(self):
        """
        One-time, silent import of the accounts, logins and passwords of the old, network-drive-launched version of
        this app (Windows only; on macOS/Linux there is nothing to find, so this quietly does nothing). An account
        or a login already present here is left exactly as it is; only what is not here yet is added. Runs at most
        once per config file, whatever it finds: a flag in it remembers that this ran, so it is never retried and
        never reintroduces something the user has since removed on purpose.

        A password store that cannot be used aborts the whole import before anything of it is saved (the flag
        included), so it is tried again, from the untouched original file, the next time the application starts.
        """
        if self.all_data.get("legacy_import_done"):
            return
        legacy = legacy_import.read_legacy_accounts(legacy_login_file())
        # Worked out on a copy: the merge puts the passwords of the old app into it as plaintext fields, which a store
        # that cannot be used would leave there, for the next save of the config to write into the file.
        merged = copy.deepcopy(self.all_data)
        if legacy is not None:
            legacy_import.merge_legacy_accounts(merged, legacy)
        merged["legacy_import_done"] = True
        try:
            # The merge above only ever adds plaintext "password" fields (never removes existing ones), so this
            # also covers any of those already in the file from before this ran, exactly as it would a moment later.
            credentials.migrate_plaintext_passwords(merged)
        except credentials.KeyringError as error:
            messagebox.showwarning(self.lang.get_message("warning_title"),
                                   self.lang.get_message("credential_store_error", error=str(error)))
            return
        self.all_data.clear()
        self.all_data.update(merged)
        self.save_account_configs()

    def migrate_plaintext_passwords(self):
        """One-time move of passwords from an older config file into the OS credential store."""
        try:
            if credentials.migrate_plaintext_passwords(self.all_data):
                self.save_account_configs()
        except credentials.KeyringError as error:
            messagebox.showwarning(self.lang.get_message("warning_title"),
                                   self.lang.get_message("credential_store_error", error=str(error)))

    def migrate_credential_items(self):
        """
        Move of passwords from an item of their own (one per account, the shape every account had before this) into
        the one item every account now shares: on macOS this is what makes the credential store ask to allow access
        once for the whole application, instead of once per customer account. Nothing in the config file changes,
        so there is nothing to save; it costs nothing once it has already moved everything there is to move.
        """
        try:
            credentials.migrate_per_account_items(self.all_data)
        except credentials.KeyringError as error:
            messagebox.showwarning(self.lang.get_message("warning_title"),
                                   self.lang.get_message("credential_store_error", error=str(error)))

    def save_login_details(self):
        self.sync_from_disk()
        administration = self.option_choose_administration.get()
        account_name = self.option_choose_name.get()
        if account_name not in self.account_data.get(administration, {}).get("names", {}):
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("select_login_first"))
            return
        login = self.account_data[administration]["names"][account_name]["login"]
        password = self.input_for_password.get()
        url = self.account_data[administration].get("url", "")
        if not password:
            messagebox.showerror(self.lang.get_message("error_title"), self.lang.get_message("password_required"))
            return
        if self._login_check_running:
            return
        self._login_check_running = True
        outcome = queue.Queue()

        def work():  # asking the server takes seconds, so not in the thread of the window; it touches nothing of Tk
            try:
                outcome.put((try_login(url, login, password), None))
            except Exception as error:
                outcome.put((False, error))

        self.config(cursor="watch")
        threading.Thread(target=work, daemon=True).start()
        self._finish_login_check(outcome, administration, account_name, url, login, password)

    def _finish_login_check(self, outcome: queue.Queue, administration, account_name, url, login, password):
        try:
            successful_login, error = outcome.get_nowait()
        except queue.Empty:
            self.after(CSV_POLL_MS, self._finish_login_check, outcome, administration, account_name, url, login,
                       password)
            return
        self._login_check_running = False
        self.config(cursor="")
        if error is not None:
            messagebox.showerror(self.lang.get_message("error_title"),
                                 self.lang.get_message("login_check_failed", error=str(error)))
            return
        if not successful_login:
            messagebox.showerror(self.lang.get_message("error_title"), self.lang.get_message("save_failure"))
            return
        self.sync_from_disk()
        if account_name not in self.account_data.get(administration, {}).get("names", {}):
            return  # removed while the server was being asked
        try:
            credentials.set_password(url, login, password)
        except credentials.KeyringError as error:
            messagebox.showerror(self.lang.get_message("error_title"),
                                 self.lang.get_message("credential_store_error", error=str(error)))
            return
        self.account_data[administration]["names"][account_name] = {"login": login}
        self.save_account_configs()
        messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("save_success"))

    def fill_login_details(self, _=None):
        account = self.option_choose_administration.get()
        if account in self.account_data:
            names = sorted(list(self.account_data[account].get("names", []).keys()))
            self.option_choose_name.config(values=names)
            last = self.account_data[account].get("last")
            self.option_choose_name.set(last if last in names else "")
            self.fill_password_details()

    def on_account_selected(self, _=None):
        self.fill_login_details()
        self.remember_selection()

    def on_login_selected(self, _=None):
        self.fill_password_details()
        self.remember_selection()

    def remember_selection(self):
        """Stores the last used account and its last used login, so the next start opens them again."""
        self.sync_from_disk()
        account = self.option_choose_administration.get()
        if account in self.account_data and accounts.remember_selection(
                self.all_data, account, self.option_choose_name.get()):
            self.default = self.all_data["default"]
            self.save_account_configs()

    def fill_password_details(self, _=None, keep_typed=False):
        """Shows the stored password of the selected login. `keep_typed`: the login is the same as before, so a
        password the person is typing is not replaced by the stored one (this runs before every save of the config)."""
        account = self.option_choose_administration.get()
        name = self.option_choose_name.get()
        if keep_typed and self.input_for_password.get():
            return
        self.input_for_password.delete(0, tk.END)
        if account in self.account_data and name in self.account_data[account].get("names", []):
            url = self.account_data[account].get("url", "")
            login = self.account_data[account]["names"][name]["login"]
            self.input_for_password.insert(0, credentials.get_password(url, login))

    def save_data_from_text_box(self, data):
        # Normalize line endings: Spreadsheet applications on macOS separate copied rows with a bare \r,
        # Windows uses \r\n - both must become \n before processors split on it.
        text = data.replace('\r\n', '\n').replace('\r', '\n')
        action = self.current_action()
        self._text_box_data = input_templates.strip_template(text, action) if action else text
        self.update_input_button()

    def _generate_textbox(self, text: str = "", line: int = None):
        self._input_window_open = True
        self.stop_blinking()  # steady while the input window is open
        try:
            options = {name: value for name, value in (("text", text), ("line", line)) if value}
            self.wait_window(InputTextBox(self, self.save_data_from_text_box, **options))
        finally:
            self._input_window_open = False
            self.update_input_button()  # blinks again when the window was closed without any input

    def edit_input_at(self, line: int):
        """The input window again, with the input of the last Start and the cursor on the line the log named."""
        self._generate_textbox(text=self._text_box_data or "", line=line)

    def reload_account_configs(self):
        try:
            data = self.load_account_configs()
        except (OSError, ValueError):  # damaged meanwhile: the app keeps what it has, and the next save is a good file
            return
        self.all_data = data
        self.account_data = self.all_data["logins"]
        self.default = self.all_data["default"]

    def fill_default_login_details(self):
        admin, name = (list(self.default) + ["", ""])[:2]
        if admin in self.account_data:
            self.option_choose_administration.set(admin)
            self.option_choose_name['values'] = sorted(list(self.account_data[admin].get("names", {}).keys()))

            if name in self.account_data[admin].get("names", {}):
                self.option_choose_name.set(name)
            else:
                self.option_choose_name.set("")

            self.fill_password_details()

    def start_update_check(self, automatic: bool = False):
        """
        Looks in the releases of the repository for a newer version and offers it. `automatic`: the check after the
        start, which says nothing unless there is something to offer; the button reports the outcome either way.
        """
        if self._update_running:
            return
        self._update_running = True
        outcome = queue.Queue()

        def work():  # asking the server takes a moment, so not in the thread of the window; it touches nothing of Tk
            try:
                outcome.put((updater.fetch_latest_release(), None))
            except updater.UpdateError as error:
                outcome.put((None, error))
            except Exception:
                outcome.put((None, updater.UpdateError("update_check_failed")))

        if not automatic:
            self.config(cursor="watch")
        threading.Thread(target=work, daemon=True).start()
        self.after(UPDATE_POLL_MS, self._finish_update_check, outcome, automatic)

    def _finish_update_check(self, outcome: queue.Queue, automatic: bool):
        try:
            release, error = outcome.get_nowait()
        except queue.Empty:
            self.after(UPDATE_POLL_MS, self._finish_update_check, outcome, automatic)
            return
        self._update_running = False
        self.config(cursor="")
        title = self.lang.get_message("update_title")
        if error:
            if not automatic:
                messagebox.showwarning(title, self.update_text(error))
            return
        if release is None:
            if not automatic:
                messagebox.showinfo(title, self.lang.get_message("update_none_published"))
            return
        if not updater.is_newer(release.version, VERSION):
            if not automatic:
                messagebox.showinfo(title, self.lang.get_message("update_up_to_date", version=VERSION))
            return
        self.offer_update(release, automatic)

    def update_text(self, error: "updater.UpdateError") -> str:
        return self.lang.get_message(error.key, **error.values)

    def offer_update(self, release: "updater.Release", automatic: bool = False):
        """Asks whether to install the version now; "later" leaves it for the next start of the application."""
        if automatic and (self.grab_current() is not None or self._input_window_open):
            self.after(UPDATE_RETRY_MS, self.offer_update, release, True)  # a window of the application is in the way
            return
        offer = UpdateOfferDialog(self, VERSION, release.version)
        self.wait_window(offer)
        if offer.install:
            self.install_update(release)

    def install_update(self, release: "updater.Release"):
        try:
            asset = updater.check_installable(release)
        except updater.UpdateError as error:
            self.offer_release_page(release, error)
            return
        self._update_running = True
        dialog = DownloadDialog(self, release.version)
        progress = {"received": 0, "total": asset.size}
        outcome = queue.Queue()

        def work():
            try:
                outcome.put((updater.download(asset, updater.update_directory(),
                                              lambda received, total: progress.update(received=received, total=total),
                                              lambda: dialog.cancelled), None))
            except updater.UpdateError as error:
                outcome.put((None, error))
            except Exception:
                outcome.put((None, updater.UpdateError("update_download_failed")))

        threading.Thread(target=work, daemon=True).start()
        self.after(UPDATE_POLL_MS, self._finish_download, release, dialog, progress, outcome)

    def _finish_download(self, release, dialog, progress, outcome: queue.Queue):
        try:
            package, error = outcome.get_nowait()
        except queue.Empty:
            dialog.set_progress(progress["received"], progress["total"])
            self.after(UPDATE_POLL_MS, self._finish_download, release, dialog, progress, outcome)
            return
        dialog.destroy()
        self._update_running = False
        title = self.lang.get_message("update_title")
        if error is None:
            try:
                updater.install(package, release)
            except updater.UpdateError as install_error:
                error = install_error
            else:
                messagebox.showinfo(title, self.lang.get_message("update_installing"))
                self.destroy()  # the installer, or the script that swaps the bundle, goes on without it
                return
        if error.key != "update_cancelled":
            self.offer_release_page(release, error)

    def offer_release_page(self, release: "updater.Release", error: "updater.UpdateError"):
        """The update cannot be installed from here: says why, and offers the page of the release to download it by hand."""
        if messagebox.askyesno(self.lang.get_message("update_title"),
                               self.lang.get_message("update_open_page", reason=self.update_text(error),
                                                     version=release.version)):
            webbrowser.open(release.page)

    def open_help(self):
        if not documentation_server.bound_port:  # the server has not started, or no port could be had for it
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("help_unavailable"))
            return
        webbrowser.open(f"http://localhost:{documentation_server.bound_port}/{self.lang.language}/")

    def update_font(self, font):
        self.font = font


if __name__ == "__main__":
    app = DSMediaplayApp(logins_file="path/to/logins.json")
    app.mainloop()
