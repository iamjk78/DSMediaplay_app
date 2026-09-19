import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
from gui_app.settings_dialog import SettingsWindow
from util.language import LanguageManager
from util import credentials
from util.paths import resource_path


class ScrollableFrame(tk.Frame):
    """
    A scrollable frame that acts like a div with scroll support.
    Contains dynamic modules.
    """
    def __init__(self, parent, *args, **kwargs):
        tk.Frame.__init__(self, parent, *args, **kwargs)

        self.canvas = tk.Canvas(self)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")


class Module:
    """
    Class representing a dynamically added module with comboboxes, entries, etc.
    """
    def __init__(self, parent, row, lang, font):
        self.row = row
        self.lang = lang
        self.font = font

        self.create_combobox(parent, "customer_account", 0, "option_choose_administration")
        self.create_combobox(parent, "name", 1, "option_choose_name")
        self.create_label_and_entry(parent, "password", 2, "input_for_password", show="*")

    def create_combobox(self, parent, label_key, row, var_name, text_var=None):
        pad_x, pad_y = 3, 2
        label = ttk.Label(parent, text=self.lang.get_message(label_key), font=self.font)
        label.grid(row=row, column=0, padx=pad_x, pady=pad_y, sticky="w")
        combobox = ttk.Combobox(parent, textvariable=text_var, state="readonly", width=40)
        combobox.grid(row=row, column=1, padx=pad_x, pady=pad_y, sticky="w")
        combobox.config(font=self.font)
        setattr(self, f"{var_name}_combobox", combobox)

    def create_label_and_entry(self, parent, label_key, row, var_name, **entry_options):
        pad_x, pad_y = 3, 2
        label = ttk.Label(parent, text=self.lang.get_message(label_key), font=self.font)
        label.grid(row=row, column=0, padx=pad_x, pady=pad_y, sticky="w")
        entry = ttk.Entry(parent, **entry_options, width=40)
        entry.grid(row=row, column=1, padx=pad_x, pady=pad_y, sticky="w")
        setattr(self, f"{var_name}_entry", entry)


class LoginApp(tk.Tk):
    """
    Simplified DSMediaplayApp for login and basic buttons.
    """

    def __init__(self, logins_file: str, *, language_file: str = str(resource_path("assets/messages.json"))):
        """
        Initializes the DSMediaplayApp with the given logins file.
        """
        super().__init__()
        self.input_for_password = None
        self.option_choose_name = None
        self.option_choose_administration = None
        self.title("DSMediaplay Control Panel")
        self.config_file = logins_file
        self.all_data = self.load_account_configs()
        self.lang = LanguageManager(language=self.all_data.get("lang", "en"), config_path=language_file)
        self.font = tuple(self.all_data.get("font", ["Helvetica", 12]))
        self.account_data = self.all_data["logins"]
        self.default = self.all_data["default"]

        self.administration_label = None
        self.name_label = None
        self.password_label = None
        self.save_button = None
        self.reload_button = None
        self.settings_button = None
        self.start_button = None
        self.quit_button = None

        self._admin_row = 0
        self._profile_row = 1
        self._password_row = 2
        self._save_button_row = 3
        self._action_buttons_row = 4

        self._modules_row = 5
        self.setup_ui()
        self.fill_default_login_details()

    def setup_ui(self):
        self.create_combobox(self, "customer_account", self._admin_row,
                             "option_choose_administration", self.fill_login_details)
        self.create_combobox(self, "name", self._profile_row,
                             "option_choose_name", self.fill_password_details)
        self.create_label_and_entry(self, "password", self._password_row,
                                    "input_for_password", show="*")
        self.create_button(self, "save_login_details", self._save_button_row,
                           self.save_login_details)
        self.create_action_buttons()

    def create_combobox(self, parent, label_key, row, var_name, command, text_var=None):
        pad_x, pad_y = 3, 2
        label = ttk.Label(parent, text=self.lang.get_message(label_key), font=self.font)
        label.grid(row=row, column=0, padx=pad_x, pady=pad_y, sticky="w")
        combobox = ttk.Combobox(parent, textvariable=text_var, state="readonly", width=40)
        combobox.grid(row=row, column=1, padx=pad_x, pady=pad_y, sticky="w")
        combobox.config(font=self.font)
        combobox.bind("<<ComboboxSelected>>", command)
        setattr(self, f"{label_key}_label", label)
        setattr(self, var_name, combobox)

    def create_label_and_entry(self, parent, label_key, row, var_name, **entry_options):
        pad_x, pad_y = 3, 2
        label = ttk.Label(parent, text=self.lang.get_message(label_key), font=self.font)
        label.grid(row=row, column=0, padx=pad_x, pady=pad_y, sticky="w")
        entry = ttk.Entry(parent, **entry_options, width=40)
        entry.grid(row=row, column=1, padx=pad_x, pady=pad_y, sticky="w")
        setattr(self, f"{label_key}_label", label)
        setattr(self, var_name, entry)

    def create_button(self, parent, label_key, row, command):
        pad_x, pad_y = 5, 5
        button = tk.Button(parent, text=self.lang.get_message(label_key), font=self.font, command=command)
        button.grid(row=row, column=0, columnspan=2, padx=pad_x, pady=pad_y, sticky="w")
        setattr(self, f"{label_key}_button", button)

    def create_action_buttons(self):
        pad_x, pad_y = 5, 5
        self.quit_button = tk.Button(self, text=self.lang.get_message("quit"), font=self.font, command=self.quit)
        self.quit_button.grid(row=self._action_buttons_row, column=0, padx=pad_x, pady=pad_y, sticky="w")
        self.settings_button = tk.Button(self, text=self.lang.get_message("settings"), font=self.font,
                                         command=self.open_settings_window)
        self.settings_button.grid(row=self._action_buttons_row, column=1, padx=pad_x, pady=pad_y, sticky="w")
        self.start_button = tk.Button(self, text=self.lang.get_message("start"), font=self.font,
                                      command=self.execute_action)
        self.start_button.grid(row=self._action_buttons_row, column=2, padx=pad_x, pady=pad_y, sticky="w")

    def save_login_details(self):
        administration = self.option_choose_administration.get()
        account_name = self.option_choose_name.get()
        password = self.input_for_password.get()
        if administration and account_name and password:
            login = self.account_data[administration].get("names", {})[account_name]["login"]
            try:
                credentials.set_password(self.account_data[administration].get("url", ""), login, password)
            except credentials.KeyringError as error:
                messagebox.showerror(self.lang.get_message("error_title"),
                                     self.lang.get_message("credential_store_error", error=str(error)))
                return
            messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("save_success"))
        else:
            messagebox.showerror(self.lang.get_message("error_title"), self.lang.get_message("missing_data_or_login"))

    def fill_login_details(self, _=None):
        account = self.option_choose_administration.get()
        if account in self.account_data:
            names = sorted(list(self.account_data[account].get("names", {}).keys()))
            self.option_choose_name.config(values=names)

    def fill_password_details(self, _=None):
        account = self.option_choose_administration.get()
        name = self.option_choose_name.get()
        if account in self.account_data and name in self.account_data[account].get("names", []):
            url = self.account_data[account].get("url", "")
            login = self.account_data[account]["names"][name]["login"]
            self.input_for_password.delete(0, tk.END)
            self.input_for_password.insert(0, credentials.get_password(url, login))

    def load_account_configs(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, "r", encoding='utf-8') as file:
                return json.load(file)
        else:
            return {"default": ["", ""], "logins": {}}

    def save_account_configs(self):
        with open(self.config_file, "w", encoding='utf-8') as file:
            json.dump(self.all_data, file, indent=4, ensure_ascii=False)

    def open_settings_window(self):
        settings_window = SettingsWindow(self, self.lang)
        self.wait_window(settings_window)

    @staticmethod
    def execute_action():
        messagebox.showinfo("Action", "Start button clicked")

    def fill_default_login_details(self):
        admin, name = self.default
        if admin in self.account_data:
            self.option_choose_administration.set(admin)
            self.option_choose_name['values'] = sorted(list(self.account_data[admin].get("names", {}).keys()))

            if name in self.account_data[admin].get("names", {}):
                self.option_choose_name.set(name)
            else:
                self.option_choose_name.set("")
