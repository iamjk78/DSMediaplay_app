import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from util.language import LanguageManager
from gui_app.icons import set_window_icon
import os


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

        languages = ["en", "cz"]
        language_combobox = ttk.Combobox(self, textvariable=self.language_var, values=languages, state="readonly",
                                         width=20)
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

        json_manager_button = ttk.Button(self, text="Edit JSON", command=self.prompt_password)
        json_manager_button.grid(row=6, column=0, padx=pad_x, pady=pad_y, sticky="w")

    def prompt_password(self):
        password = simpledialog.askstring("Password", "Enter the password:", show='*')
        actual_password = os.getenv("JSON_EDITOR_PASSWORD")
        if actual_password and password == actual_password:
            self.open_json_editor()
        else:
            messagebox.showerror("Error", "Incorrect password")

    def open_json_editor(self):
        from json_manager.json_manager import JsonEditorApp
        JsonEditorApp(self.master, self.master.config_file)
        self.destroy()

    def restore_default(self):
        selected_language = "en"
        selected_font = "Helvetica"
        selected_size = 12
        self.lang_manager.set_language(selected_language)
        self.master.update_font((selected_font, selected_size))
        self.master.refresh_ui()
        self.master.all_data["lang"] = selected_language
        self.master.all_data["deploy_batch_size"] = 10
        self.master.all_data["deploy_batch_interval"] = 3
        self.master.save_account_configs()
        messagebox.showinfo(self.lang_manager.get_message("success"), self.lang_manager.get_message("settings_saved"))
        self.destroy()

    def save_settings(self):
        selected_language = self.language_var.get()
        selected_font = self.font_var.get()
        selected_size = self.size_var.get()
        self.lang_manager.set_language(selected_language)
        self.master.update_font((selected_font, selected_size))
        self.master.refresh_ui()
        self.master.all_data["lang"] = selected_language
        self.master.all_data["deploy_batch_size"] = self.deploy_batch_size_var.get()
        self.master.all_data["deploy_batch_interval"] = self.deploy_batch_interval_var.get()
        self.master.save_account_configs()
        messagebox.showinfo(self.lang_manager.get_message("success"), self.lang_manager.get_message("settings_saved"))
        self.destroy()
