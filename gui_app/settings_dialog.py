import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from util.language import LanguageManager
from gui_app.icons import set_window_icon
import os


# What the drop-down shows for the codes of the languages (each in its own language, so it is found in any)
LANGUAGE_NAMES = {"en": "English", "cz": "Čeština"}


# noinspection PyUnresolvedReferences
class SettingsWindow(tk.Toplevel):
    def __init__(self, master: "DSMediaplayApp", lang_manager: LanguageManager):
        super().__init__(master)
        self.lang_manager = lang_manager
        self.master = master
        self.title(self.lang_manager.get_message("settings"))
        self.font = self.master.font
        self.language_var = tk.StringVar(value=self.lang_manager.language)
        self.font_var = tk.StringVar(value=self.master.font[0])
        self.size_var = tk.IntVar(value=self.master.font[1])
        self.deploy_batch_size_var = tk.IntVar(value=self.master.all_data.get("deploy_batch_size", 10))
        self.deploy_batch_interval_var = tk.IntVar(value=self.master.all_data.get("deploy_batch_interval", 3))
        self.create_widgets()
        self.setup_icons()

    def setup_icons(self):
        set_window_icon(self)

    def create_widgets(self):
        pad_x = 5
        pad_y = 5

        language_label = ttk.Label(self, text=self.lang_manager.get_message("select_language"), font=self.font)
        language_label.grid(row=0, column=0, padx=pad_x, pady=pad_y, sticky="w")

        language_combobox = ttk.Combobox(self, values=list(LANGUAGE_NAMES.values()), state="readonly", width=20)
        language_combobox.set(LANGUAGE_NAMES.get(self.language_var.get(), self.language_var.get()))
        language_combobox.bind("<<ComboboxSelected>>", lambda _event: self.language_var.set(
            next(code for code, name in LANGUAGE_NAMES.items() if name == language_combobox.get())))
        language_combobox.grid(row=0, column=1, padx=pad_x, pady=pad_y, sticky="w")

        font_label = ttk.Label(self, text=self.lang_manager.get_message("select_font"), font=self.font)
        font_label.grid(row=1, column=0, padx=pad_x, pady=pad_y, sticky="w")

        fonts = ["Helvetica", "Arial", "Times New Roman"]
        font_combobox = ttk.Combobox(self, textvariable=self.font_var, values=fonts, state="readonly", width=20)
        font_combobox.grid(row=1, column=1, padx=pad_x, pady=pad_y, sticky="w")

        size_label = ttk.Label(self, text=self.lang_manager.get_message("select_size"), font=self.font)
        size_label.grid(row=2, column=0, padx=pad_x, pady=pad_y, sticky="w")

        sizes = list(range(8, 25))
        size_combobox = ttk.Combobox(self, textvariable=self.size_var, values=sizes, state="readonly", width=20)
        size_combobox.grid(row=2, column=1, padx=pad_x, pady=pad_y, sticky="w")

        deploy_batch_size_label = ttk.Label(self, text=self.lang_manager.get_message("deploy_batch_size_label"),
                                            font=self.font)
        deploy_batch_size_label.grid(row=3, column=0, padx=pad_x, pady=pad_y, sticky="w")

        deploy_batch_size_combobox = ttk.Combobox(self, textvariable=self.deploy_batch_size_var,
                                                  values=list(range(1, 21)), state="readonly", width=20)
        deploy_batch_size_combobox.grid(row=3, column=1, padx=pad_x, pady=pad_y, sticky="w")

        deploy_batch_interval_label = ttk.Label(self, text=self.lang_manager.get_message("deploy_batch_interval_label"),
                                                font=self.font)
        deploy_batch_interval_label.grid(row=4, column=0, padx=pad_x, pady=pad_y, sticky="w")

        deploy_batch_interval_combobox = ttk.Combobox(self, textvariable=self.deploy_batch_interval_var,
                                                      values=list(range(1, 61)), state="readonly", width=20)
        deploy_batch_interval_combobox.grid(row=4, column=1, padx=pad_x, pady=pad_y, sticky="w")

        save_button = ttk.Button(self, text=self.lang_manager.get_message("save"), command=self.save_settings)
        save_button.grid(row=5, column=0, padx=pad_x, pady=pad_y, sticky="w")

        close_button = ttk.Button(self, text=self.lang_manager.get_message("close"), command=self.destroy)
        close_button.grid(row=5, column=1, padx=pad_x, pady=pad_y, sticky="w")

        open_button = ttk.Button(self, text=self.lang_manager.get_message("default"), command=self.restore_default)
        open_button.grid(row=5, column=2, padx=pad_x, pady=pad_y, sticky="w")

        if os.getenv("JSON_EDITOR_PASSWORD"):  # without it nobody can get in, so the button would only mislead
            json_manager_button = ttk.Button(self, text=self.lang_manager.get_message("edit_json"),
                                             command=self.prompt_password)
            json_manager_button.grid(row=6, column=0, padx=pad_x, pady=pad_y, sticky="w")

    def prompt_password(self):
        password = simpledialog.askstring(self.lang_manager.get_message("password").rstrip(":"),
                                          self.lang_manager.get_message("json_password_prompt"), show='*', parent=self)
        if password is None:  # cancelled
            return
        actual_password = os.getenv("JSON_EDITOR_PASSWORD")
        if actual_password and password == actual_password:
            self.open_json_editor()
        else:
            messagebox.showerror(self.lang_manager.get_message("error_title"),
                                 self.lang_manager.get_message("json_password_wrong"), parent=self)

    def open_json_editor(self):
        from json_manager.json_manager import JsonEditorApp
        JsonEditorApp(self.master)
        self.destroy()

    def apply_look(self, language: str, font: tuple) -> None:
        """
        Applies a language and a font. The window is rebuilt only when one of them really changed: the rebuild forgets
        the selected action and the text typed for it and closes the player table, which a change of the batch size of a
        deploy has no reason to do.
        """
        changed = language != self.lang_manager.language or tuple(font) != tuple(self.master.font)
        self.lang_manager.set_language(language)
        self.master.update_font(font)
        if changed:
            self.master.refresh_ui()

    def restore_default(self):
        selected_language = "en"
        selected_font = "Helvetica"
        selected_size = 12
        self.apply_look(selected_language, (selected_font, selected_size))
        self.master.all_data["lang"] = selected_language
        self.master.all_data["font"] = [selected_font, selected_size]
        self.master.all_data["deploy_batch_size"] = 10
        self.master.all_data["deploy_batch_interval"] = 3
        self.master.save_account_configs()
        messagebox.showinfo(self.lang_manager.get_message("success"), self.lang_manager.get_message("settings_saved"))
        self.destroy()

    def save_settings(self):
        selected_language = self.language_var.get()
        selected_font = self.font_var.get()
        selected_size = self.size_var.get()
        self.apply_look(selected_language, (selected_font, int(selected_size)))
        self.master.all_data["lang"] = selected_language
        self.master.all_data["font"] = [selected_font, selected_size]
        self.master.all_data["deploy_batch_size"] = self.deploy_batch_size_var.get()
        self.master.all_data["deploy_batch_interval"] = self.deploy_batch_interval_var.get()
        self.master.save_account_configs()
        messagebox.showinfo(self.lang_manager.get_message("success"), self.lang_manager.get_message("settings_saved"))
        self.destroy()
