import tkinter as tk
from tkinter import ttk

from gui_app.icons import set_window_icon


class UpdateOfferDialog(tk.Toplevel):
    """
    Tells that a newer version is there and asks whether to install it now or later. `install` is True only for "now":
    closing the window or "later" leave the update for the next start of the application.
    """

    def __init__(self, master, current: str, new: str):
        super().__init__(master=master)
        lang, font = master.lang, master.font
        self.install = False
        self.title(lang.get_message("update_title"))
        self.resizable(False, False)
        set_window_icon(self)
        tk.Label(self, text=lang.get_message("update_available", new=new, current=current), font=font, justify="left",
                 wraplength=440).grid(row=0, column=0, columnspan=2, padx=20, pady=(18, 12), sticky="w")
        now = tk.Button(self, text=lang.get_message("update_install_now"), font=font, command=self._install)
        now.grid(row=1, column=0, padx=(20, 5), pady=(0, 15), sticky="e")
        tk.Button(self, text=lang.get_message("update_later"), font=font, command=self.destroy
                  ).grid(row=1, column=1, padx=(5, 20), pady=(0, 15), sticky="w")
        self.bind("<Return>", lambda _: self._install())
        self.bind("<Escape>", lambda _: self.destroy())
        self.transient(master)
        self.grab_set()
        now.focus_set()

    def _install(self) -> None:
        self.install = True
        self.destroy()


class DownloadDialog(tk.Toplevel):
    """The progress of the download, which can be cancelled. The download itself runs in another thread."""

    def __init__(self, master, version: str):
        super().__init__(master=master)
        lang, font = master.lang, master.font
        self.cancelled = False
        self.title(lang.get_message("update_title"))
        self.resizable(False, False)
        set_window_icon(self)
        tk.Label(self, text=lang.get_message("update_downloading", version=version), font=font
                 ).grid(row=0, column=0, padx=20, pady=(18, 8), sticky="w")
        self._bar = ttk.Progressbar(self, length=360, maximum=100)
        self._bar.grid(row=1, column=0, padx=20, pady=4)
        tk.Button(self, text=lang.get_message("update_cancel"), font=font, command=self.cancel
                  ).grid(row=2, column=0, pady=(8, 15))
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.transient(master)
        self.grab_set()

    def set_progress(self, received: int, total: int) -> None:
        self._bar["value"] = 100 * received / total if total else 0

    def cancel(self) -> None:
        self.cancelled = True
