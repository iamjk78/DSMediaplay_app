import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, FrozenSet, List, Tuple

from util.player_filter import plain_text

MAX_POPUP_HEIGHT = 280
MIN_POPUP_WIDTH = 220


class MultiSelectCombo(tk.Frame):
    """
    A text field with an arrow. What is typed filters by a part of the value; the arrow opens a list with a
    check box for every value, and any number of them can be ticked. The typed text also narrows the list.

    The list is a frame placed inside `popup_parent` (the window), not a window of its own: it can never be left
    behind on the screen the way a separate pop-up window can. It closes on a click anywhere else, on Escape,
    and when the window is moved, resized or hidden.
    """

    def __init__(self, master, popup_parent: tk.Misc, *, font, width: int = 12,
                 on_change: Callable[[], None] = lambda: None):
        super().__init__(master)
        self._parent = popup_parent
        self._font = font
        self._on_change = on_change
        self._choices: List[Tuple[str, str]] = []
        self._vars: Dict[str, tk.BooleanVar] = {}
        self._buttons: Dict[str, ttk.Checkbutton] = {}
        self._bindings: Dict[str, str] = {}  # what is bound on the window while the list is open

        self.text_var = tk.StringVar()
        self.text_var.trace_add("write", lambda *_: self._text_changed())
        self.entry = tk.Entry(self, textvariable=self.text_var, width=width, font=font)
        self.entry.grid(row=0, column=0)
        self._badge = tk.Label(self, font=font, foreground="#1565c0")
        self._badge.grid(row=0, column=1, padx=(3, 0))
        self._badge.grid_remove()
        self.arrow = ttk.Button(self, text="▾", width=2, command=self.toggle)
        self.arrow.grid(row=0, column=2)

        self._popup = tk.Frame(popup_parent, borderwidth=1, relief="solid", background="white")
        self._canvas = tk.Canvas(self._popup, highlightthickness=0, borderwidth=0, background="white", width=1,
                                 height=1)
        self._scrollbar = ttk.Scrollbar(self._popup, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._scrollbar.pack(side="right", fill="y")
        self._list = tk.Frame(self._canvas, background="white")
        self._canvas.create_window((0, 0), window=self._list, anchor="nw", tags="list")
        self._list.bind("<Configure>", lambda _: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", lambda event: self._canvas.itemconfigure("list", width=event.width))
        for widget in (self._canvas, self._list):
            widget.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Destroy>", lambda event: self.close() if event.widget is self else None, add="+")

    # ---- what the user chose

    def text(self) -> str:
        return self.text_var.get()

    def checked(self) -> FrozenSet[str]:
        return frozenset(value for value, var in self._vars.items() if var.get())

    def set_options(self, options: List[Tuple[str, str]]):
        """(shown text, value) pairs; the ticks of the values that are still offered are kept."""
        previous = self.checked()
        self.close()
        for button in self._buttons.values():
            button.destroy()
        self._choices, self._vars, self._buttons = list(options), {}, {}
        for label, value in self._choices:
            var = tk.BooleanVar(value=value in previous)
            var.trace_add("write", lambda *_: self._ticks_changed())
            button = ttk.Checkbutton(self._list, text=label, variable=var)
            button.bind("<MouseWheel>", self._on_wheel)
            self._vars[value], self._buttons[value] = var, button
        self._update_badge()

    def clear(self):
        """Empties the text and removes every tick."""
        for var in self._vars.values():
            var.set(False)
        self.text_var.set("")

    # ---- the list

    @property
    def is_open(self) -> bool:
        return bool(self._popup.winfo_manager())

    def toggle(self):
        self.close() if self.is_open else self.open()

    def open(self):
        if self.is_open:
            return
        self._fill_list()
        self._popup.lift()
        self._place_popup()
        close_on_window = lambda event: self.close() if event.widget is self._parent else None
        for sequence, handler in (("<ButtonPress>", self._on_click_elsewhere), ("<Escape>", self._on_escape),
                                  ("<Configure>", close_on_window), ("<Unmap>", close_on_window)):
            self._bindings[sequence] = self._parent.bind(sequence, handler, add="+")

    def close(self):
        for sequence, function_id in self._bindings.items():
            try:
                self._parent.unbind(sequence, function_id)
            except tk.TclError:  # the window is being destroyed
                pass
        self._bindings = {}
        try:
            self._popup.place_forget()
        except tk.TclError:
            pass

    def _fill_list(self):
        """Shows the values that contain the typed text."""
        typed = plain_text(self.text_var.get().strip())
        shown = 0
        for label, value in self._choices:
            button = self._buttons[value]
            if plain_text(label).find(typed) >= 0:
                button.grid(row=shown, column=0, sticky="w", padx=6, pady=1)
                shown += 1
            else:
                button.grid_remove()
        self._list.update_idletasks()
        self._canvas.yview_moveto(0)

    def _place_popup(self):
        self._list.update_idletasks()
        parent = self._parent
        width = max(self.winfo_width(), MIN_POPUP_WIDTH, self._list.winfo_reqwidth() + self._scrollbar.winfo_reqwidth())
        height = min(max(self._list.winfo_reqheight(), 24), MAX_POPUP_HEIGHT)
        x = self.winfo_rootx() - parent.winfo_rootx()
        y = self.winfo_rooty() - parent.winfo_rooty() + self.winfo_height()
        x = max(0, min(x, parent.winfo_width() - width - 4))
        self._canvas.configure(height=height)
        self._popup.place(x=x, y=y, width=width, height=height + 2)

    def _on_click_elsewhere(self, event):
        inside = str(event.widget)
        for own in (self._popup, self):
            if inside == str(own) or inside.startswith(str(own) + "."):
                return
        self.close()

    def _on_escape(self, _event):
        if self.is_open:
            self.close()

    def _on_wheel(self, event):
        step = -event.delta if self.tk.call("tk", "windowingsystem") == "aqua" else -event.delta // 120
        self._canvas.yview_scroll(step, "units")
        return "break"

    # ---- changes

    def _text_changed(self):
        if self.is_open:
            self._fill_list()
            self._place_popup()
        self._on_change()

    def _ticks_changed(self):
        self._update_badge()
        self._on_change()

    def _update_badge(self):
        count = len(self.checked())
        if count:
            self._badge.configure(text=f"{count}✓")
            self._badge.grid()
        else:
            self._badge.grid_remove()
