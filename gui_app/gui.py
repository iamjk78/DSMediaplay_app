import tkinter as tk
from tkinter import ttk, messagebox
from gui_app.color_button import (BLUE, GREEN, GREEN_DARK, RED, YELLOW, button_enabled, equalize_widths,
                                  make_color_button, set_button_colors, set_button_enabled)
from gui_app.icons import set_window_icon
from gui_app.tooltip import Tooltip
import json
import os
import tempfile
from gui_app.input_box import InputTextBox
from gui_app.settings_dialog import SettingsWindow
from gui_app.account_dialogs import EntryDialog, LanguageDialog
from processor.csv_generator import CSVTaskFactory
from processor.input_processing import try_login
from datetime import datetime
from util.language import LanguageManager
from gui_app.log_box import LoggingTextBoxFactory
from gui_app.player_browser import PlayerBrowser
from util import accounts, credentials, input_templates, legacy_import
from util.actions import action_needs_input
from util.paths import legacy_login_file, resource_path
import requests
import webbrowser


# The same for Start and Deploy all: narrow enough for the free space right of the action drop-down
DEPLOY_PADDING_X = 12


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


class DSMediaplayApp(tk.Tk):
    """
    Main application class for the DSMediaplay control panel.
    """

    def __init__(self, logins_file: str, *, language_file: str = str(resource_path("assets/messages.json"))):
        """
        Initializes the DSMediaplayApp with the given logins file.
        """
        super().__init__()
        self.title("DSMediaplay Control Panel")
        self.version = "1.0"
        self.config_file = logins_file
        self._file_stamp = None  # (mtime, size) of the config file as this app last read or wrote it
        self.all_data = self.load_account_configs()
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
        self.start_button = None
        self.deploy_all_button = None
        self.live_view_button = None
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

        self._admin_row = 0
        self._profile_row = 1
        self._login_row = 2
        self._password_row = 3
        self._save_button_row = 4
        self._entity_type_row = 5
        self._action_row = 6
        self._text_box_row = 7
        self._action_buttons_row = 8

        self.setup_ui()
        self.fill_default_login_details()
        self.update_action_buttons()
        self.bind("<FocusIn>", self.on_focus_in)
        self.resizable(False, False)

    def load_actions(self):
        actions = self.lang.get_message("actions")
        return {
            "Playlists": {
                actions["Playlists"]["get_details_csv"]: "get_playlist_details",
                actions["Playlists"]["set_assets_to_playlists"]: "set_assets_to_playlists",
                actions["Playlists"]["remove_assets_from_playlists"]: "remove_assets_from_playlists",
                actions["Playlists"]["create_playlist"]: "create_playlist",
                actions["Playlists"]["get_playlist_unused"]: "get_playlist_unused",
                actions["Playlists"]["remove_unused_playlists"]: "remove_unused_playlists",
                actions["Playlists"]["remove_all_unused_playlists"]: "remove_all_unused_playlists",
                actions["Playlists"]["get_playlist_settings"]: "get_playlist_settings",
                actions["Playlists"]["set_playlist_settings"]: "set_playlist_settings"
            },
            "Groups": {
                # actions["Groups"]["get_groups_playlists_csv"]: "get_groups_with_playlists",
                # actions["Groups"]["set_playlists_to_groups"]: "set_playlists_to_groups",
                actions["Groups"]["get_detailed_groups_playlists_csv"]: "get_detailed_groups_with_playlists",
                actions["Groups"]["set_detailed_playlists_to_groups"]: "set_detailed_playlists_to_groups",
                actions["Groups"]["remove_playlists_from_group"]: "remove_playlists_from_group",
                actions["Groups"]["remove_playlist_list"]: "remove_playlist_list",
                actions["Groups"]["group_rename"]: "set_group_rename",
                actions["Groups"]["get_group_settings"]: "get_group_settings",
                actions["Groups"]["set_group_settings"]: "set_group_settings",
                # actions["Groups"]["set_add_playlist_to_group"]: "set_add_playlist_to_group",
                actions["Groups"]["set_add_detailed_playlist_to_group"]: "set_add_detailed_playlist_to_group",
                actions["Groups"]["remove_expired_playlists"]: "remove_expired_playlists",
                actions["Groups"]["remove_all_expired_playlists"]: "remove_all_expired_playlists",
                actions["Groups"]["create_group"]: "create_group",
                actions["Groups"]["get_group_unused"]: "get_group_unused",
                actions["Groups"]["remove_unused_groups"]: "remove_unused_groups",
                actions["Groups"]["remove_all_unused_groups"]: "remove_all_unused_groups",
                actions["Groups"]["get_identical_groups"]: "get_identical_groups"
            },
            "Players": {
                actions["Players"]["set_groups_to_players"]: "set_groups_to_players",
                actions["Players"]["get_players_groups_csv"]: "get_players_with_groups",
                actions["Players"]["set_notes_to_players"]: "set_notes_to_players",
                actions["Players"]["get_player_locations_csv"]: "get_player_locations",
                actions["Players"]["set_player_config_location"]: "set_player_config_location",
                actions["Players"]["get_player_notes_csv"]: "get_player_notes",
                actions["Players"]["get_player_labels"]: "get_player_categories",
                actions["Players"]["get_label_unused"]: "get_category_unused",
                actions["Players"]["remove_unused_labels"]: "remove_unused_labels",
                actions["Players"]["remove_all_unused_labels"]: "remove_all_unused_labels",
                actions["Players"]["set_player_labels"]: "set_player_labels",
                actions["Players"]["get_player_details"]: "get_player_details",
                actions["Players"]["set_player_rename"]: "set_player_rename",
                actions["Players"]["set_player_snapshot"]: "set_player_snapshot",
                actions["Players"]["show_player_snapshots"]: "show_player_snapshots",
                # actions["Players"]["create_player"]: "create_player",
                actions["Players"]["get_player_versions"]: "get_player_versions",
                actions["Players"]["create_label"]: "create_label",
                actions["Players"]["get_player_overview"]: "get_player_overview",
                actions["Players"]["get_additional_playlists"]: "get_additional_playlists",
                actions["Players"]["remove_additional_playlists"]: "remove_additional_playlists"
            },
            "Locations": {
                actions["Locations"]["get_locations_plan"]: "get_locations_plan",
                actions["Locations"]["set_locations_plan"]: "set_location_plan",
                actions["Locations"]["set_location_rename"]: "set_location_rename",
                actions["Locations"]["create_location"]: "create_location",
                actions["Locations"]["remove_unused_locations"]: "remove_unused_locations",
                actions["Locations"]["remove_all_unused_locations"]: "remove_all_unused_locations",
                actions["Locations"]["get_location_unused"]: "get_location_unused"
            },
            "Assets": {
                actions["Assets"]["get_asset_unused"]: "get_asset_unused",
                actions["Assets"]["remove_unused_assets"]: "remove_unused_assets",
                actions["Assets"]["remove_all_unused_assets"]: "remove_all_unused_assets",
                actions["Assets"]["get_asset_details"]: "get_asset_details",
                actions["Assets"]["get_asset_validity"]: "get_asset_validity",
                actions["Assets"]["set_asset_validity"]: "set_asset_validity"
            },
            "Deploy": {
                actions["Deploy"]["deploy_all_players"]: "set_deploy_all_players",
                actions["Deploy"]["deploy_selected_groups"]: "set_deploy_selected_groups"
            },
        }

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
                             "entity_type_combobox", self.update_action_selection,
                             self.entity_type_var, list(self.entity_actions.keys()), columnspan=3)
        self.create_combobox(self, "select_action", self._action_row,
                             "option_choose_action", self.reset_data, self.action_var, columnspan=3)
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
            group.grid(row=row, column=4, sticky="w")
            self.create_symbol_button(group, 0, "+", add_command, tips[0])
            self.create_symbol_button(group, 1, "\u2212", remove_command, tips[1])
        self.create_action_buttons()
        self.refresh_ui()
        self.fill_default_login_details()

    def create_combobox(self, parent, label_key, row, var_name, command, text_var=None, values=None, columnspan=1):
        pad_x, pad_y = 3, 2
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
        self.help_button = tk.Button(self, text=self.lang.get_message("help"), font=self.font, command=self.open_help)
        self.help_button.grid(row=self._action_buttons_row, column=1, padx=pad_x, pady=pad_y, sticky="w")
        self.add_tooltip(self.help_button, "tip_help")
        # Spans the columns to its left, so it does not widen the window: its right edge is the one of the "+ -" buttons
        right_buttons = tk.Frame(self)
        right_buttons.grid(row=self._action_buttons_row, column=1, columnspan=4, sticky="e")
        self.create_button(right_buttons, "settings", 0, self.open_settings_window, column=0)
        self.start_button = self.create_emphasised_button("start", self.execute_action, GREEN, size_offset=2,
                                                          parent=right_buttons, padding_x=DEPLOY_PADDING_X)
        self.start_button.grid(row=0, column=1, padx=pad_x, pady=pad_y, sticky="w")
        self.add_action_tooltip(self.start_button, "tip_start")
        # Right of the drop-downs, in line with the right edge of "Start"; same font and size as it
        self.live_view_button = self.create_emphasised_button("live_view", self.live_view, BLUE, size_offset=2,
                                                              padding_x=DEPLOY_PADDING_X)
        self.live_view_button.grid(row=self._entity_type_row, column=1, columnspan=4, padx=pad_x, sticky="e")
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

    def update_action_selection(self, _=None):
        entity_type = self.entity_type_var.get()
        actions_dict = self.entity_actions.get(entity_type, {})
        actions = sorted(list(actions_dict))
        self.option_choose_action['values'] = actions
        if actions:
            default_label = next((label for label, action in actions_dict.items()
                                  if action == "set_deploy_all_players"), actions[0])
            self.option_choose_action.set(default_label)
        else:
            self.option_choose_action.set('')

        self._text_box_data = None
        self.update_input_button()

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

        self.title(self.lang.get_message("title"))

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
        if self.save_login_details_button:
            self.save_login_details_button.config(text=self.lang.get_message("save_login_details"))
        if self.input_prompt_button:
            self.input_prompt_button.config(text=self.lang.get_message("input_prompt"))
        if self.deploy_all_button:
            self.deploy_all_button.config(text=self.lang.get_message("deploy_all"))
        if self.live_view_button:
            self.live_view_button.config(text=self.lang.get_message("live_view"))
        self._equalize_action_buttons()

    def update_all_widgets_font(self):
        """Updates the font for all widgets to the current font settings."""
        for widget in self.winfo_children():
            self._update_widget_font(widget)
            for child in widget.winfo_children():
                self._update_widget_font(child)
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

    def add_action_tooltip(self, button, key):
        """While the button cannot be used its tooltip says what is missing."""
        Tooltip(button, lambda: self.lang.get_message(key if self.can_start_actions() else "tip_login_required"))

    def can_start_actions(self) -> bool:
        """An account, one of its logins and a password are there: what every action needs."""
        names = self.account_data.get(self.account_var.get(), {}).get("names", {})
        return self.login_var.get() in names and bool(self.password_var.get())

    def update_action_buttons(self):
        """Start, Live-view and Deploy all are grey until an account, a login and a password are there."""
        enabled = self.can_start_actions()
        for button, colors in ((self.start_button, GREEN), (self.deploy_all_button, YELLOW),
                               (self.live_view_button, BLUE)):
            if button is not None:
                set_button_enabled(button, enabled, colors)

    def _equalize_action_buttons(self):
        buttons = [self.start_button, self.deploy_all_button, self.live_view_button]
        if all(buttons):
            equalize_widths(*buttons)

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

    def perform_show_action(self, action, url, login, password, _):
        if "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("login_info"))
            return
        self.open_player_browser(url, login, password)

    def open_player_browser(self, url, login, password):
        """One window at a time: the same account and login brings the open one to the front."""
        browser = self._player_browser
        if browser is not None and browser.winfo_exists():
            if browser.connection == (url, login):
                browser.deiconify()
                browser.lift()
                browser.focus_force()
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
            data = "Non-empty"
        if self.input_missing(data) or "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("missing_data_or_login"))
            return
        self.open_action_log_box(action[4:], url, login, password, data)

    def perform_remove_action(self, action, url, login, password, data):
        if not action_needs_input(action):
            data = "Non-empty"
        if self.input_missing(data) or "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("missing_data_or_login"))
            return
        self.open_action_log_box(action, url, login, password, data)

    def perform_create_action(self, action, url, login, password, data):
        if self.input_missing(data) or "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("missing_data_or_login"))
            return
        self.open_action_log_box(action, url, login, password, data)

    def generate_csv(self, task_type, url, login, password):
        date = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        administration = self.option_choose_administration.get()
        file_name = f'{administration}-{task_type}-{date}.csv'
        file_path = os.path.join(get_download_path(), file_name)
        csv_task = CSVTaskFactory.create_task(
            task_type=task_type,
            log_handler=None,
            url=url,
            login=login,
            password=password
        )
        try:
            csv_task.generate_csv(file_path)
            messagebox.showinfo(self.lang.get_message("info_title"),
                                self.lang.get_message("file_saved", file_path=file_path))
        except Exception:
            self.show_warning()

    def show_warning(self):
        messagebox.showwarning(self.lang.get_message("warning_title"), self.lang.get_message("file_save_error"))

    def open_action_log_box(self, processor_type, url, login, password, data):
        extra_settings = None
        if processor_type.startswith("deploy_"):
            extra_settings = {
                "batch_size": self.all_data.get("deploy_batch_size", 10),
                "batch_interval": self.all_data.get("deploy_batch_interval", 3)
            }
        elif processor_type == "player_snapshot":
            extra_settings = {"output_dir": os.path.join(get_download_path(), "DSMediaplay_snapshots")}
        log_box = LoggingTextBoxFactory.create_log_box(
            processor_type=processor_type,
            master=self,
            url=url,
            login=login,
            password=password,
            data=data,
            extra_settings=extra_settings
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
        self.fill_password_details()
        self.update_action_buttons()  # the data may have changed without any of the fields changing

    def on_focus_in(self, event):
        if event.widget is self:  # the window itself came to the front, e.g. after Edit JSON or a text editor
            self.sync_from_disk()

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
        unused = accounts.remove_account(self.all_data, account)
        self.save_account_configs()
        self.delete_passwords(unused)
        self.default = self.all_data["default"]
        self.option_choose_administration['values'] = sorted(self.account_data.keys())
        self.option_choose_administration.set("")
        self.option_choose_name.config(values=[])
        self.option_choose_name.set("")
        self.input_for_password.delete(0, tk.END)

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
        if legacy is not None:
            legacy_import.merge_legacy_accounts(self.all_data, legacy)
        self.all_data["legacy_import_done"] = True
        try:
            # The merge above only ever adds plaintext "password" fields (never removes existing ones), so this
            # also covers any of those already in the file from before this ran, exactly as it would a moment later.
            credentials.migrate_plaintext_passwords(self.all_data)
        except credentials.KeyringError as error:
            del self.all_data["legacy_import_done"]
            messagebox.showwarning(self.lang.get_message("warning_title"),
                                   self.lang.get_message("credential_store_error", error=str(error)))
            return
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
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            successful_login = try_login(url, login, password)
        except requests.exceptions.RequestException as error:
            messagebox.showerror(self.lang.get_message("error_title"),
                                 self.lang.get_message("login_check_failed", error=str(error)))
            return
        finally:
            self.config(cursor="")
        if not successful_login:
            messagebox.showerror(self.lang.get_message("error_title"), self.lang.get_message("save_failure"))
            return
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

    def fill_password_details(self, _=None):
        account = self.option_choose_administration.get()
        name = self.option_choose_name.get()
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

    def _generate_textbox(self):
        self._input_window_open = True
        self.stop_blinking()  # steady while the input window is open
        try:
            self.wait_window(InputTextBox(self, self.save_data_from_text_box))
        finally:
            self._input_window_open = False
            self.update_input_button()  # blinks again when the window was closed without any input

    def reload_account_configs(self):
        self.all_data = self.load_account_configs()
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

    def open_help(self):
        webbrowser.open(f"http://localhost:8080/{self.lang.language}/")
        # messagebox.showwarning("Not implemented", "Not yet implemented")

    def update_font(self, font):
        self.font = font


if __name__ == "__main__":
    app = DSMediaplayApp(logins_file="path/to/logins.json")
    app.mainloop()
