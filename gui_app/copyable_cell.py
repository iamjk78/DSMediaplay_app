import tkinter as tk
from typing import Callable, Optional


class CopyableCell(tk.Entry):
    """
    A cell of a table whose text can be selected with the mouse and copied (a Label cannot): a drag selects, a double
    click selects a word, a triple click the whole text, and the usual Copy shortcut copies it. A click with the other
    mouse button opens a small menu that copies the selection (or the whole text of the cell when nothing is selected)
    or, when `row_text` is given, the whole row.

    It is made to be used in place of a Label: `configure(text=...)` and `cget("text")` work, and a new text clears
    what was selected in the old one (a table reuses its cells for other rows).
    """

    def __init__(self, master: tk.Misc, font, copy_label: str = "Copy", copy_row_label: str = "Copy row",
                 row_text: Optional[Callable[[], str]] = None) -> None:
        self._text = tk.StringVar()
        super().__init__(master, textvariable=self._text, font=font, width=1, state="readonly", relief="flat",
                         borderwidth=0, highlightthickness=0, takefocus=0,
                         readonlybackground=master.cget("background"))
        self._copy_label, self._copy_row_label, self._row_text = copy_label, copy_row_label, row_text
        context_button = "<Button-2>" if self.tk.call("tk", "windowingsystem") == "aqua" else "<Button-3>"
        self.bind(context_button, self._show_menu)
        if context_button == "<Button-2>":
            self.bind("<Control-Button-1>", self._show_menu)

    def configure(self, cnf=None, **options):
        if "text" in options:
            text = options.pop("text")
            if text != self._text.get():
                self.selection_clear()
                self._text.set(text)
                self.xview_moveto(0)
        if cnf or options:
            return super().configure(cnf, **options)
        return None

    config = configure

    def cget(self, key):
        return self._text.get() if key == "text" else super().cget(key)

    __getitem__ = cget

    def set_labels(self, copy_label: str, copy_row_label: str) -> None:
        self._copy_label, self._copy_row_label = copy_label, copy_row_label

    def selected_text(self) -> str:
        """What is selected in the cell; the whole text when nothing is."""
        if self.selection_present():
            return self._text.get()[self.index("sel.first"):self.index("sel.last")]
        return self._text.get()

    def copy(self, text: Optional[str] = None) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.selected_text() if text is None else text)

    def _show_menu(self, event) -> str:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label=self._copy_label, command=self.copy)
        if self._row_text is not None:
            menu.add_command(label=self._copy_row_label, command=lambda: self.copy(self._row_text()))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"
