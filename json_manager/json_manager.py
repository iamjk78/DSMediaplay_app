"""
The editor of accounts and logins behind the "Edit JSON" button of the settings (it asks for a password that is set in
the environment). It works on the data of the main window, through the same functions the window itself uses: the
addresses are checked, the file is written whole or not at all, a change made outside is read first, and the passwords
stay in the credential store (moved with an address, removed with their login).
"""
import tkinter as tk
from tkinter import ttk, messagebox

from util import accounts, credentials


def create_input_box(parent, **kwargs):
    label_text = kwargs.get('label_text')
    text_var = kwargs.get('text_var')
    row = kwargs.get('row')
    column = kwargs.get('column')
    colspan = kwargs.get('colspan', 1)
    entry_width = kwargs.get('entry_width', 30)

    label = tk.Label(parent, text=label_text)
    label.grid(row=row, column=column, sticky="e", padx=5, pady=5)
    entry = tk.Entry(parent, textvariable=text_var, width=entry_width, show=kwargs.get('show', ''))
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
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.new_url_var = tk.StringVar()
        self.display_name_var = tk.StringVar()
        self.login_name_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.admin_url_var = tk.StringVar()
        self.admin_name_var = tk.StringVar()
        self.title("JSON Editor")
        self.create_widgets()

    # ---- the data: always the current one, never a copy that could be stale

    def data(self) -> dict:
        self.app.sync_from_disk()
        return self.app.all_data

    def save(self) -> None:
        """Writes the config and shows the change in the main window and in the lists of this one."""
        self.app.save_account_configs()
        self.app.refresh_selection_lists()
        self.update_admin_combobox()

    def accounts_found(self) -> list:
        return sorted(self.data()["logins"])

    def warn(self, error: accounts.AccountError) -> None:
        messagebox.showwarning("Input Error", self.app.lang.get_message(error.key), parent=self)

    # ---- the windows

    def create_widgets(self):
        self.setup_admin_frame()
        self.setup_edit_url_frame()
        self.setup_login_frame()
        self.setup_default_frame()
        self.update_admin_combobox()

    def setup_admin_frame(self):
        admin_frame = tk.LabelFrame(self, text="Administration", padx=10, pady=10)
        admin_frame.grid(row=0, column=0, padx=10, pady=5, sticky="n")

        create_input_box(admin_frame, label_text="Admin Name:", text_var=self.admin_name_var, row=0, column=0)
        create_input_box(admin_frame, label_text="Admin URL:", text_var=self.admin_url_var, row=1, column=0)
        create_button(admin_frame, text="Add Administration", command=self.add_administration,
                      row=2, column=0, colspan=2)

        self.delete_admin_combobox = ttk.Combobox(admin_frame, values=self.accounts_found(), state="readonly",
                                                  width=27)
        self.delete_admin_combobox.grid(row=3, column=1, padx=5, pady=5)
        tk.Label(admin_frame, text="Select Admin to Delete:").grid(row=3, column=0, sticky="e")
        create_button(admin_frame, text="Delete Administration", command=self.delete_administration,
                      row=4, column=0, colspan=2)

    def setup_edit_url_frame(self):
        edit_url_frame = tk.LabelFrame(self, text="Edit URL", padx=10, pady=10)
        edit_url_frame.grid(row=0, column=1, padx=10, pady=5, sticky="n")

        self.edit_admin_combobox = ttk.Combobox(edit_url_frame, values=self.accounts_found(), state="readonly",
                                                width=27)
        self.edit_admin_combobox.grid(row=0, column=1, padx=5, pady=5)
        tk.Label(edit_url_frame, text="Select Admin:").grid(row=0, column=0, sticky="e")
        self.edit_admin_combobox.bind("<<ComboboxSelected>>", self.fill_url_entry)

        create_input_box(edit_url_frame, label_text="New URL:", text_var=self.new_url_var, row=1, column=0)
        create_button(edit_url_frame, text="Edit URL", command=self.edit_url, row=2, column=0, colspan=2)

    def setup_login_frame(self):
        login_frame = tk.LabelFrame(self, text="Login", padx=10, pady=10)
        login_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="n")

        self.admin_combobox = ttk.Combobox(login_frame, values=self.accounts_found(), state="readonly", width=27)
        self.admin_combobox.grid(row=0, column=1, padx=5, pady=5)
        tk.Label(login_frame, text="Admin:").grid(row=0, column=0, sticky="e")
        self.admin_combobox.bind("<<ComboboxSelected>>", self.update_login_combobox)

        create_input_box(login_frame, label_text="Display Name:", text_var=self.display_name_var, row=1, column=0)
        create_input_box(login_frame, label_text="Login:", text_var=self.login_name_var, row=2, column=0)
        self.password_entry = create_input_box(login_frame, label_text="Password:", text_var=self.password_var,
                                               row=3, column=0, show="*")
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

        self.default_admin_combobox = ttk.Combobox(default_frame, values=self.accounts_found(), state="readonly",
                                                   width=27)
        self.default_admin_combobox.grid(row=0, column=1, padx=5, pady=5)
        tk.Label(default_frame, text="Admin:").grid(row=0, column=0, sticky="e")
        self.default_admin_combobox.bind("<<ComboboxSelected>>", self.update_default_login_combobox)

        self.default_login_combobox = ttk.Combobox(default_frame, state="readonly", width=27)
        self.default_login_combobox.grid(row=1, column=1, padx=5, pady=5)
        tk.Label(default_frame, text="Login:").grid(row=1, column=0, sticky="e")

        create_button(default_frame, text="Set Default", command=self.set_default, row=2, column=0, colspan=2)

    # ---- the actions

    def add_administration(self):
        try:
            name = accounts.add_account(self.data(), self.admin_name_var.get(), self.admin_url_var.get())
        except accounts.AccountError as error:
            self.warn(error)
            return
        self.save()
        messagebox.showinfo("Success", f"Administration '{name}' added.", parent=self)

    def delete_administration(self):
        name = self.delete_admin_combobox.get().strip()
        if name not in self.data()["logins"]:
            messagebox.showwarning("Input Error", "Please select an admin to delete.", parent=self)
            return
        if not messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete the administration '{name}'?",
                                   parent=self):
            return
        entry = self.data()["logins"][name]
        self.app.close_player_browser_of(entry.get("url", ""),
                                         {details.get("login") for details in entry.get("names", {}).values()})
        unused = accounts.remove_account(self.data(), name)
        self.save()
        self.app.delete_passwords(unused)
        messagebox.showinfo("Success", f"Administration '{name}' has been deleted.", parent=self)

    def edit_url(self):
        name = self.edit_admin_combobox.get().strip()
        if name not in self.data()["logins"]:
            messagebox.showwarning("Input Error", "Both fields are required.", parent=self)
            return
        entry = self.data()["logins"][name]
        logins = sorted({details["login"] for details in entry.get("names", {}).values()})
        try:
            new_url = accounts.normalize_url(self.new_url_var.get())
            # The passwords are kept under the address: copy them first, so a store that fails changes nothing.
            moved = [(login, credentials.get_password(entry.get("url", ""), login)) for login in logins]
            for login, password in moved:
                if password:
                    credentials.set_password(new_url, login, password)
        except accounts.AccountError as error:
            self.warn(error)
            return
        except credentials.KeyringError as error:
            messagebox.showerror("Error", f"Passwords could not be moved in the credential store:\n{error}",
                                 parent=self)
            return
        old_url, _ = accounts.change_url(self.data(), name, new_url)
        self.app.close_player_browser_of(old_url, set(logins))
        self.save()
        self.app.delete_passwords(accounts.unused_credentials(self.data(), [(old_url, login) for login in logins]))
        messagebox.showinfo("Success", f"URL for '{name}' updated.", parent=self)

    def add_login(self):
        self.save_login(must_exist=False)

    def edit_login(self):
        self.save_login(must_exist=True)

    def save_login(self, must_exist: bool):
        account = self.admin_combobox.get().strip()
        login = self.login_name_var.get().strip()
        display_name = self.display_name_var.get().strip() or login
        password = self.password_var.get().strip()
        if account not in self.data()["logins"] or not login:
            messagebox.showwarning("Input Error", "Admin and login are required.", parent=self)
            return
        entry = self.data()["logins"][account]
        names = entry.setdefault("names", {})
        if must_exist != (display_name in names):
            messagebox.showwarning("Input Error", "This login does not exist for the selected admin." if must_exist
                                   else "This login already exists for the selected admin.", parent=self)
            return
        if password:
            try:
                credentials.set_password(entry.get("url", ""), login, password)
            except credentials.KeyringError as error:
                messagebox.showerror("Error", f"Password could not be stored in the system credential store:\n{error}",
                                     parent=self)
                return
        previous = names.get(display_name, {}).get("login")
        names[display_name] = {"login": login}
        self.save()
        if previous and previous != login:  # its password is not needed any more, unless another entry uses it
            self.app.delete_passwords(accounts.unused_credentials(self.data(), [(entry.get("url", ""), previous)]))
        messagebox.showinfo("Success", f"Login '{display_name}' {'updated' if must_exist else 'added'} for "
                                       f"'{account}'.", parent=self)

    def remove_login(self):
        account = self.admin_combobox.get().strip()
        display_name = self.login_combobox.get().strip()
        if display_name not in self.data()["logins"].get(account, {}).get("names", {}):
            messagebox.showwarning("Input Error", "Please select both admin and display name.", parent=self)
            return
        entry = self.data()["logins"][account]
        self.app.close_player_browser_of(entry.get("url", ""), {entry["names"][display_name]["login"]})
        unused = accounts.remove_login(self.data(), account, display_name)
        self.save()
        self.app.delete_passwords(unused)
        messagebox.showinfo("Success", f"Login '{display_name}' removed from '{account}'.", parent=self)

    def set_default(self):
        account = self.default_admin_combobox.get().strip()
        display_name = self.default_login_combobox.get().strip()
        if display_name not in self.data()["logins"].get(account, {}).get("names", {}):
            messagebox.showwarning("Input Error", "Please select both admin and login to set as default.", parent=self)
            return
        accounts.remember_selection(self.data(), account, display_name)
        self.save()
        messagebox.showinfo("Success", f"Default login set to '{display_name}' for '{account}'.", parent=self)

    # ---- the lists

    def update_admin_combobox(self):
        found = self.accounts_found()
        for combobox in (self.admin_combobox, self.edit_admin_combobox, self.default_admin_combobox,
                         self.delete_admin_combobox):
            combobox.config(values=found)
            combobox.set('')
        self.update_login_combobox()
        self.update_default_login_combobox()

    def logins_of(self, account: str) -> list:
        return sorted(self.data()["logins"].get(account, {}).get("names", {}))

    def update_login_combobox(self, event=None):
        self.login_combobox.config(values=self.logins_of(self.admin_combobox.get().strip()))
        self.login_combobox.set('')

    def update_default_login_combobox(self, event=None):
        self.default_login_combobox.config(values=self.logins_of(self.default_admin_combobox.get().strip()))
        self.default_login_combobox.set('')

    def fill_url_entry(self, event=None):
        account = self.edit_admin_combobox.get().strip()
        if account in self.data()["logins"]:
            self.new_url_var.set(self.data()["logins"][account].get("url", ""))

    def fill_login_details(self, event=None):
        account = self.admin_combobox.get().strip()
        display_name = self.login_combobox.get().strip()
        names = self.data()["logins"].get(account, {}).get("names", {})
        if display_name in names:
            login = names[display_name]["login"]
            self.display_name_var.set(display_name)
            self.login_name_var.set(login)
            self.password_var.set(credentials.get_password(self.data()["logins"][account].get("url", ""), login))
