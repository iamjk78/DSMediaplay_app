import tkinter as tk
from tkinter import ttk, messagebox
from json_manager.backend import JsonManager
from util import credentials


def create_input_box(parent, **kwargs):
    label_text = kwargs.get('label_text')
    text_var = kwargs.get('text_var')
    row = kwargs.get('row')
    column = kwargs.get('column')
    colspan = kwargs.get('colspan', 1)
    entry_width = kwargs.get('entry_width', 30)

    label = tk.Label(parent, text=label_text)
    label.grid(row=row, column=column, sticky="e", padx=5, pady=5)
    entry = tk.Entry(parent, textvariable=text_var, width=entry_width)
    entry.grid(row=row, column=column + 1, sticky="w", padx=5, pady=5, columnspan=colspan)
    return entry


def create_button(parent, **kwargs):
    text = kwargs.get('text')
    command = kwargs.get('command')
    row = kwargs.get('row')
    column = kwargs.get('column')
    colspan = kwargs.get('colspan', 1)

    button = tk.Button(parent, text=text, command=command)
    button.grid(row=row, column=column, columnspan=colspan, padx=5, pady=5)
    return button


class JsonEditorApp(tk.Toplevel):
    def __init__(self, parent, file: str):
        super().__init__(parent)
        self.delete_admin_combobox = None
        self.new_url_var = tk.StringVar()
        self.display_name_var = tk.StringVar()
        self.login_name_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.admin_url_var = tk.StringVar()
        self.admin_name_var = tk.StringVar()
        self.login_combobox = None
        self.admin_combobox = None
        self.edit_admin_combobox = None
        self.default_admin_combobox = None
        self.default_login_combobox = None
        self.json_manager = JsonManager(file)
        self.title("JSON Editor")
        self.create_widgets()

    def create_widgets(self):
        self.setup_admin_frame()
        self.setup_edit_url_frame()
        self.setup_login_frame()
        self.setup_default_frame()
        self.update_admin_combobox()

    def setup_admin_frame(self):
        admin_frame = tk.LabelFrame(self, text="Administration", padx=10, pady=10)
        admin_frame.grid(row=0, column=0, padx=10, pady=5, sticky="n")

        self.admin_name_var = tk.StringVar()
        self.admin_url_var = tk.StringVar()
        create_input_box(admin_frame, label_text="Admin Name:", text_var=self.admin_name_var, row=0, column=0)
        create_input_box(admin_frame, label_text="Admin URL:", text_var=self.admin_url_var, row=1, column=0)
        create_button(admin_frame,
                      text="Add Administration",
                      command=self.add_administration,
                      row=2, column=0, colspan=2)

        self.delete_admin_combobox = ttk.Combobox(admin_frame,
                                                  values=sorted(list(self.json_manager.data["logins"].keys())),
                                                  state="readonly",
                                                  width=27)

        self.delete_admin_combobox.grid(row=3, column=1, padx=5, pady=5)
        tk.Label(admin_frame, text="Select Admin to Delete:").grid(row=3, column=0, sticky="e")

        create_button(admin_frame,
                      text="Delete Administration",
                      command=self.delete_administration,
                      row=4, column=0, colspan=2)

    def setup_edit_url_frame(self):
        edit_url_frame = tk.LabelFrame(self, text="Edit URL", padx=10, pady=10)
        edit_url_frame.grid(row=0, column=1, padx=10, pady=5, sticky="n")

        self.edit_admin_combobox = ttk.Combobox(edit_url_frame,
                                                values=list(self.json_manager.data["logins"].keys()),
                                                state="readonly", width=27)
        self.edit_admin_combobox.grid(row=0, column=1, padx=5, pady=5)
        tk.Label(edit_url_frame, text="Select Admin:").grid(row=0, column=0, sticky="e")
        self.edit_admin_combobox.bind("<<ComboboxSelected>>", self.fill_url_entry)

        self.new_url_var = tk.StringVar()
        create_input_box(edit_url_frame, label_text="New URL:", text_var=self.new_url_var, row=1, column=0)
        create_button(edit_url_frame, text="Edit URL", command=self.edit_url, row=2, column=0, colspan=2)

    def setup_login_frame(self):
        login_frame = tk.LabelFrame(self, text="Login", padx=10, pady=10)
        login_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="n")

        self.admin_combobox = ttk.Combobox(login_frame,
                                           values=list(self.json_manager.data["logins"].keys()),
                                           state="readonly", width=27)
        self.admin_combobox.grid(row=0, column=1, padx=5, pady=5)
        tk.Label(login_frame, text="Admin:").grid(row=0, column=0, sticky="e")
        self.admin_combobox.bind("<<ComboboxSelected>>", self.update_login_combobox)

        create_input_box(login_frame, label_text="Display Name:", text_var=self.display_name_var, row=1, column=0)
        create_input_box(login_frame, label_text="Login:", text_var=self.login_name_var, row=2, column=0)
        create_input_box(login_frame, label_text="Password:", text_var=self.password_var, row=3, column=0)
        create_button(login_frame, text="Add Login", command=self.add_login, row=4, column=0, colspan=2)
        create_button(login_frame, text="Edit Login", command=self.edit_login, row=4, column=2)
        create_button(login_frame, text="Remove Login", command=self.remove_login, row=4, column=3)

        self.login_combobox = ttk.Combobox(login_frame, state="readonly", width=27)
        self.login_combobox.grid(row=1, column=3, padx=5, pady=5)
        tk.Label(login_frame, text="Select Login:").grid(row=1, column=2, sticky="e")
        self.login_combobox.bind("<<ComboboxSelected>>", self.fill_login_details)

    def setup_default_frame(self):
        default_frame = tk.LabelFrame(self, text="Set Default Login", padx=10, pady=10)
        default_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=5, sticky="n")

        self.default_admin_combobox = ttk.Combobox(default_frame,
                                                   values=list(self.json_manager.data["logins"].keys()),
                                                   state="readonly", width=27)
        self.default_admin_combobox.grid(row=0, column=1, padx=5, pady=5)
        tk.Label(default_frame, text="Admin:").grid(row=0, column=0, sticky="e")
        self.default_admin_combobox.bind("<<ComboboxSelected>>", self.update_default_login_combobox)

        self.default_login_combobox = ttk.Combobox(default_frame, state="readonly", width=27)
        self.default_login_combobox.grid(row=1, column=1, padx=5, pady=5)
        tk.Label(default_frame, text="Login:").grid(row=1, column=0, sticky="e")

        create_button(default_frame, text="Set Default", command=self.set_default, row=2, column=0, colspan=2)

    def add_administration(self):
        admin_name = self.admin_name_var.get().strip()
        admin_url = self.admin_url_var.get().strip()
        if admin_name and admin_url:
            self.json_manager.add_administration(admin_name, admin_url)
            self.update_admin_combobox()
            messagebox.showinfo("Success", f"Administration '{admin_name}' added.")
        else:
            messagebox.showwarning("Input Error", "Both fields are required.")

    def add_login(self):
        admin_name = self.admin_combobox.get().strip()
        display_name = self.display_name_var.get().strip()
        login_name = self.login_name_var.get().strip()
        password = self.password_var.get().strip()
        if admin_name and display_name and login_name:
            if display_name in self.json_manager.data["logins"][admin_name]["names"]:
                messagebox.showwarning("Input Error", "This login already exists for the selected admin.")
            else:
                if self.save_login(admin_name, display_name, login_name, password):
                    self.update_login_combobox()
                    messagebox.showinfo("Success", f"Login '{display_name}' added to '{admin_name}'.")
        else:
            messagebox.showwarning("Input Error", "All fields except password are required.")

    def edit_login(self):
        admin_name = self.admin_combobox.get().strip()
        display_name = self.display_name_var.get().strip()
        login_name = self.login_name_var.get().strip()
        password = self.password_var.get().strip()
        if admin_name and display_name and login_name:
            if display_name in self.json_manager.data["logins"][admin_name]["names"]:
                if self.save_login(admin_name, display_name, login_name, password):
                    self.update_login_combobox()
                    messagebox.showinfo("Success", f"Login '{display_name}' updated for '{admin_name}'.")
            else:
                messagebox.showwarning("Input Error", "This login does not exist for the selected admin.")
        else:
            messagebox.showwarning("Input Error", "All fields except password are required.")

    def save_login(self, admin_name, display_name, login_name, password) -> bool:
        if password:
            try:
                credentials.set_password(self.json_manager.get_url(admin_name), login_name, password)
            except credentials.KeyringError as error:
                messagebox.showerror("Error", f"Password could not be stored in the system credential store:\n{error}")
                return False
        self.json_manager.add_login(admin_name, display_name, login_name)
        return True

    def remove_login(self):
        admin_name = self.admin_combobox.get().strip()
        display_name = self.login_combobox.get().strip()
        if admin_name and display_name:
            self.json_manager.remove_login(admin_name, display_name)
            self.update_login_combobox()
            messagebox.showinfo("Success", f"Login '{display_name}' removed from '{admin_name}'.")
        else:
            messagebox.showwarning("Input Error", "Please select both admin and display name.")

    def edit_url(self):
        admin_name = self.edit_admin_combobox.get().strip()
        new_url = self.new_url_var.get().strip()
        if admin_name and new_url:
            self.json_manager.update_url(admin_name, new_url)
            messagebox.showinfo("Success", f"URL for '{admin_name}' updated.")
        else:
            messagebox.showwarning("Input Error", "Both fields are required.")

    def set_default(self):
        admin_name = self.default_admin_combobox.get().strip()
        display_name = self.default_login_combobox.get().strip()
        if admin_name and display_name:
            self.json_manager.set_default(admin_name, display_name)
            messagebox.showinfo("Success", f"Default login set to '{display_name}' for '{admin_name}'.")
        else:
            messagebox.showwarning("Input Error", "Please select both admin and login to set as default.")

    def update_admin_combobox(self):
        admin_keys = list(self.json_manager.data["logins"].keys())
        self.admin_combobox.config(values=admin_keys)
        self.edit_admin_combobox.config(values=admin_keys)
        self.default_admin_combobox.config(values=admin_keys)
        self.admin_combobox.set('')
        self.edit_admin_combobox.set('')
        self.default_admin_combobox.set('')
        self.update_login_combobox()

    def update_login_combobox(self, event=None):
        admin_name = self.admin_combobox.get().strip()
        if admin_name in self.json_manager.data["logins"]:
            self.login_combobox.config(values=list(self.json_manager.data["logins"][admin_name]["names"].keys()))
        else:
            self.login_combobox.config(values=[])
        self.login_combobox.set('')

    def update_default_login_combobox(self, event=None):
        admin_name = self.default_admin_combobox.get().strip()
        if admin_name in self.json_manager.data["logins"]:
            self.default_login_combobox.config(values=list(self.json_manager.data["logins"][admin_name]["names"].keys()))
        else:
            self.default_login_combobox.config(values=[])
        self.default_login_combobox.set('')

    def fill_url_entry(self, event=None):
        admin_name = self.edit_admin_combobox.get().strip()
        if admin_name in self.json_manager.data["logins"]:
            current_url = self.json_manager.data["logins"][admin_name]["url"]
            self.new_url_var.set(current_url)

    def fill_login_details(self, event=None):
        admin_name = self.admin_combobox.get().strip()
        display_name = self.login_combobox.get().strip()
        if admin_name in self.json_manager.data["logins"] and display_name in self.json_manager.data["logins"][admin_name]["names"]:
            login_details = self.json_manager.data["logins"][admin_name]["names"][display_name]
            self.display_name_var.set(display_name)
            self.login_name_var.set(login_details["login"])
            self.password_var.set(credentials.get_password(self.json_manager.get_url(admin_name), login_details["login"]))

    def delete_administration(self):
        admin_name = self.delete_admin_combobox.get().strip()
        if admin_name:
            if messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete the administration '{admin_name}'?"):
                self.json_manager.remove_administration(admin_name)
                self.update_admin_combobox()
                messagebox.showinfo("Success", f"Administration '{admin_name}' has been deleted.")
        else:
            messagebox.showwarning("Input Error", "Please select an admin to delete.")


if __name__ == "__main__":
    a = JsonEditorApp("../login_new.json")
    a.mainloop()
