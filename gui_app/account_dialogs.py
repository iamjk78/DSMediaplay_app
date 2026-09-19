import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, List, Optional

from PIL import Image, ImageTk
from util.accounts import AccountError
from util.paths import resource_path


def _set_icon(window: tk.Toplevel) -> None:
    window.tk_image = ImageTk.PhotoImage(Image.open(resource_path("assets/ds_media_icon_input.jpg")))
    # noinspection PyTypeChecker
    window.iconphoto(False, window.tk_image)


class LanguageDialog(tk.Toplevel):
    """Asked once on the first start, before any language is known, hence the fixed bilingual texts."""

    LANGUAGES = (("cz", "Čeština"), ("en", "English"))

    def __init__(self, master=None):
        super().__init__(master=master)
        self.language: Optional[str] = None
        self.title("Jazyk / Language")
        self.resizable(False, False)
        _set_icon(self)
        ttk.Label(self, text="Vyberte jazyk aplikace\nChoose the application language",
                  justify="center").grid(row=0, column=0, columnspan=2, padx=20, pady=(15, 10))
        for column, (code, label) in enumerate(self.LANGUAGES):
            tk.Button(self, text=label, width=12, command=lambda chosen=code: self._choose(chosen)
                      ).grid(row=1, column=column, padx=10, pady=(0, 15))
        self.grab_set()
        self.focus_set()

    def _choose(self, language: str) -> None:
        self.language = language
        self.destroy()


class EntryDialog(tk.Toplevel):
    """Small modal form; `on_submit` receives the entered values and raises AccountError to reject them."""

    def __init__(self, master, title: str, labels: List[str], on_submit: Callable[..., None]):
        super().__init__(master=master)
        self._lang = master.lang
        self._font = master.font
        self._on_submit = on_submit
        self._entries: List[ttk.Entry] = []
        self.title(title)
        self.resizable(False, False)
        _set_icon(self)
        for row, label in enumerate(labels):
            ttk.Label(self, text=label, font=self._font).grid(row=row, column=0, padx=5, pady=5, sticky="w")
            entry = ttk.Entry(self, width=40, font=self._font)
            entry.grid(row=row, column=1, columnspan=2, padx=5, pady=5, sticky="w")
            self._entries.append(entry)
        buttons_row = len(labels)
        tk.Button(self, text=self._lang.get_message("save"), font=self._font, command=self._submit
                  ).grid(row=buttons_row, column=1, padx=5, pady=5, sticky="e")
        tk.Button(self, text=self._lang.get_message("close"), font=self._font, command=self.destroy
                  ).grid(row=buttons_row, column=2, padx=5, pady=5, sticky="w")
        self.bind("<Return>", lambda _: self._submit())
        self.bind("<Escape>", lambda _: self.destroy())
        self.transient(master)
        self.grab_set()
        self._entries[0].focus_set()

    def _submit(self) -> None:
        try:
            self._on_submit(*(entry.get() for entry in self._entries))
        except AccountError as error:
            messagebox.showerror(self._lang.get_message("error_title"), self._lang.get_message(error.key), parent=self)
            return
        self.destroy()
