import re
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import json
import os
from gui_app.input_box import InputTextBox
from gui_app.settings_dialog import SettingsWindow
from processor.csv_generator import CSVTaskFactory
from processor.input_processing import try_login
from datetime import datetime
from util.language import LanguageManager
from gui_app.log_box import LoggingTextBoxFactory
from util import credentials
from util.paths import resource_path
import webbrowser


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


class DSMediaplayApp(tk.Tk):
    """
    Main application class for the DSMediaplay control panel.
    """

    def __init__(self, logins_file: str, *, language_file: str = str(resource_path("assets/messages.json"))):
        """
        Initializes the DSMediaplayApp with the given logins file.
        """
        super().__init__()
        self.tk_image = None
        self.title("DSMediaplay Control Panel")
        self.version = "1.0"
        self.config_file = logins_file
        self.all_data = self.load_account_configs()
        self.lang = LanguageManager(language=self.all_data.get("lang", "en"), config_path=language_file)
        self.migrate_plaintext_passwords()
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
        self.reload_button = None
        self.settings_button = None
        self.help_button = None
        self.start_button = None
        self.quit_button = None
        self.select_entity_type_label = None
        self.select_action_label = None
        self.customer_account_label = None
        self.text_box_button = None
        self.input_prompt_button = None
        self.save_login_details_button = None
        self.input_prompt_label = None
        self._text_box_data = None

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
                # actions["Players"]["create_player"]: "create_player",
                actions["Players"]["get_player_versions"]: "get_player_versions",
                actions["Players"]["create_label"]: "create_label",
                actions["Players"]["set_clone_player"]: "set_clone_player",
                actions["Players"]["get_player_overview"]: "get_player_overview",
                actions["Players"]["set_player_update"]: "set_player_update",
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
        dsm_icon = resource_path("assets/ds_media_icon.jpg")
        icon_bitmap = Image.open(dsm_icon)
        self.tk_image = ImageTk.PhotoImage(icon_bitmap)
        # noinspection PyTypeChecker
        self.iconphoto(False, self.tk_image)

    def setup_ui(self):
        self.create_combobox(self, "customer_account", self._admin_row,
                             "option_choose_administration", self.fill_login_details, columnspan=3)
        self.create_combobox(self, "name", self._profile_row,
                             "option_choose_name", self.fill_password_details, columnspan=3)
        self.create_label_and_entry(self, "password", self._password_row,
                                    "input_for_password", show="*")
        self.create_button(self, "save_login_details", self._save_button_row,
                           self.save_login_details, columnspan=3)
        self.create_combobox(self, "select_entity_type", self._entity_type_row,
                             "entity_type_combobox", self.update_action_selection,
                             self.entity_type_var, list(self.entity_actions.keys()), columnspan=3)
        self.create_combobox(self, "select_action", self._action_row,
                             "option_choose_action", self.reset_data, self.action_var, columnspan=3)
        self.create_button(self, "input_prompt", self._text_box_row, self._generate_textbox, columnspan=3)
        self.create_button(self, "reload", self._admin_row, self.refresh_ui, column=4)
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

    def create_button(self, parent, label_key, row, command, column=1, columnspan=1):
        pad_x, pad_y = 5, 5
        button = tk.Button(parent, text=self.lang.get_message(label_key), font=self.font, command=command)
        button.grid(row=row, column=column, columnspan=columnspan, padx=pad_x, pady=pad_y, sticky="w")
        setattr(self, f"{label_key}_button", button)

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
        self.quit_button = tk.Button(self, text=self.lang.get_message("quit"), font=self.font, command=self.quit)
        self.quit_button.grid(row=self._action_buttons_row, column=0, padx=pad_x, pady=pad_y, sticky="w")
        self.help_button = tk.Button(self, text=self.lang.get_message("help"), font=self.font, command=self.open_help)
        self.help_button.grid(row=self._action_buttons_row, column=1, padx=pad_x, pady=pad_y, sticky="w")
        self.create_button(self, "settings", self._action_buttons_row, self.open_settings_window, column=3)
        self.start_button = tk.Button(self, text=self.lang.get_message("start"), font=self.font,
                                      command=self.execute_action)
        self.start_button.grid(row=self._action_buttons_row, column=4, padx=pad_x, pady=pad_y, sticky="w")

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

    def reset_data(self, _=None):
        self._text_box_data = None

    def refresh_ui(self):
        """Refreshes the entire UI to reflect changes in language or other settings."""
        self.lang = LanguageManager(language=self.lang.language, config_path=self.lang.config_path)
        self.reload_account_configs()
        self.entity_actions = self.load_actions()

        self.title(self.lang.get_message("title"))

        self.refresh_all_widgets_text()

        self.update_all_widgets_font()

        self.refresh_dropdowns()

        self.fill_default_login_details()

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
        if self.reload_button:
            self.reload_button.config(text=self.lang.get_message("reload"))
        if self.settings_button:
            self.settings_button.config(text=self.lang.get_message("settings"))
        if self.help_button:
            self.help_button.config(text=self.lang.get_message("help"))
        if self.save_login_details_button:
            self.save_login_details_button.config(text=self.lang.get_message("save_login_details"))
        if self.input_prompt_button:
            self.input_prompt_button.config(text=self.lang.get_message("input_prompt"))

    def update_all_widgets_font(self):
        """Updates the font for all widgets to the current font settings."""
        for widget in self.winfo_children():
            self._update_widget_font(widget)
            for child in widget.winfo_children():
                self._update_widget_font(child)

    def _update_widget_font(self, widget):
        """Applies the current font to a given widget, if applicable."""
        try:
            widget.configure(font=self.font)
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
            }
            for prefix, method in action_map.items():
                if action.startswith(prefix):
                    # noinspection PyArgumentList
                    method(action, url, login, password, data)

    def perform_get_action(self, action, url, login, password, _):
        if "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("login_info"))
            return
        self.generate_csv(action[4:], url, login, password)

    def perform_set_action(self, action, url, login, password, data):
        if action == "set_deploy_all_players":
            data = "Non-empty"
        if data is None or "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("missing_data_or_login"))
            return
        self.open_action_log_box(action[4:], url, login, password, data)

    def perform_remove_action(self, action, url, login, password, data):
        if re.findall(r"remove_all", action):
            data = "Non-empty"
        if data is None or "" in [login, password]:
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("missing_data_or_login"))
            return
        self.open_action_log_box(action, url, login, password, data)

    def perform_create_action(self, action, url, login, password, data):
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

    def load_account_configs(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, "r", encoding='utf-8') as file:
                return json.load(file)
        else:
            return {"default": ["", ""], "logins": {}}

    def save_account_configs(self):
        with open(self.config_file, "w", encoding='utf-8') as file:
            json.dump(self.all_data, file, indent=4, ensure_ascii=False)

    def migrate_plaintext_passwords(self):
        """One-time move of passwords from an older config file into the OS credential store."""
        try:
            if credentials.migrate_plaintext_passwords(self.all_data):
                self.save_account_configs()
        except credentials.KeyringError as error:
            messagebox.showwarning(self.lang.get_message("warning_title"),
                                   self.lang.get_message("credential_store_error", error=str(error)))

    def save_login_details(self):
        administration = self.option_choose_administration.get()
        account_name = self.option_choose_name.get()
        login = self.account_data[administration].get("names", {})[account_name]["login"]
        password = self.input_for_password.get()
        url = self.account_data[administration].get("url", [])
        successful_login = try_login(url, login, password)
        if not successful_login:
            messagebox.showerror(self.lang.get_message("error_title"), self.lang.get_message("save_failure"))
            return
        if login and password:
            try:
                credentials.set_password(url, login, password)
            except credentials.KeyringError as error:
                messagebox.showerror(self.lang.get_message("error_title"),
                                     self.lang.get_message("credential_store_error", error=str(error)))
                return
            self.account_data[administration].get("names", {})[account_name] = {"login": login}
            self.save_account_configs()
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("save_success"))
        else:
            messagebox.showerror(self.lang.get_message("error_title"), self.lang.get_message("missing_data_or_login"))

    def fill_login_details(self, _=None):
        account = self.option_choose_administration.get()
        previous_name = self.option_choose_name.get()
        if account in self.account_data:
            names = sorted(list(self.account_data[account].get("names", []).keys()))
            self.option_choose_name.config(values=names)

            if previous_name in names:
                self.option_choose_name.set(previous_name)
            else:
                self.option_choose_name.set("")

            self.fill_password_details()

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
        self._text_box_data = data.replace('\r\n', '\n').replace('\r', '\n')

    def _generate_textbox(self):
        text_box = InputTextBox(self, self.save_data_from_text_box)
        self.wait_window(text_box)

    def reload_account_configs(self):
        self.all_data = self.load_account_configs()
        self.account_data = self.all_data["logins"]
        self.default = self.all_data["default"]

    def fill_default_login_details(self):
        admin, name = self.default
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
