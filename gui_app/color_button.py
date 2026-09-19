import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from typing import Callable, List, Optional, Union

FontSpec = Union[str, tuple]

PADDING_X, PADDING_Y, RADIUS = 16, 6, 7


@dataclass(frozen=True)
class ButtonColors:
    normal: str
    hover: str
    pressed: str
    border: str
    text: str = "#000000"  # fixed dark text: the light fills stay readable in a dark system theme too


GREEN = ButtonColors(normal="#c6efce", hover="#b4e7bf", pressed="#9fd9ac", border="#7fb88b")
RED = ButtonColors(normal="#ffc7ce", hover="#ffb5be", pressed="#f79ea9", border="#d98c96")


def _rounded_rectangle(x1: float, y1: float, x2: float, y2: float, radius: float) -> List[float]:
    """Polygon points that Tk smooths into a rounded rectangle."""
    return [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius, x2, y2 - radius, x2, y2,
            x2 - radius, y2, x1 + radius, y2, x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]


class ColorButton(tk.Canvas):
    """
    A push button with its own background colour. Tk's native macOS buttons ignore the background option, so this
    one is drawn on a canvas, rounded like the native ones. It answers `configure(text=..., font=..., command=...)`
    and `cget` like a tk.Button so the rest of the application can treat both alike.
    """

    def __init__(self, master: tk.Misc, text: str, command: Callable[[], None], font: FontSpec,
                 colors: ButtonColors) -> None:
        super().__init__(master, background=master.cget("background"), highlightthickness=0, borderwidth=0,
                         takefocus=0)
        self._text, self._command, self._font, self._colors = text, command, font, colors
        self._state = "normal"
        self._draw()
        self.bind("<Enter>", lambda _: self._set_state("hover"))
        self.bind("<Leave>", lambda _: self._set_state("normal"))
        self.bind("<ButtonPress-1>", lambda _: self._set_state("pressed"))
        self.bind("<ButtonRelease-1>", self._release)

    def _draw(self) -> None:
        measure = tkfont.Font(root=self, font=self._font)
        width = measure.measure(self._text) + 2 * PADDING_X
        height = measure.metrics("linespace") + 2 * PADDING_Y
        tk.Canvas.configure(self, width=width, height=height)
        self.delete("all")
        fill = {"normal": self._colors.normal, "hover": self._colors.hover, "pressed": self._colors.pressed}
        self.create_polygon(_rounded_rectangle(1, 1, width - 1, height - 1, RADIUS), smooth=True,
                            fill=fill[self._state], outline=self._colors.border)
        self.create_text(width / 2, height / 2, text=self._text, font=self._font, fill=self._colors.text)

    def _set_state(self, state: str) -> None:
        self._state = state
        self._draw()

    def _release(self, event: tk.Event) -> None:
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self._set_state("hover" if inside else "normal")
        if inside and self._command:
            self._command()

    def configure(self, cnf: Optional[dict] = None, **options):
        options = {**(cnf or {}), **options}
        changed = False
        for name in ("text", "font", "command"):
            if name in options:
                setattr(self, "_" + name, options.pop(name))
                changed = True
        if options:
            tk.Canvas.configure(self, **options)
        if changed:
            self._draw()

    config = configure

    def cget(self, key: str):
        if key in ("text", "font", "command"):
            return getattr(self, "_" + key)
        return tk.Canvas.cget(self, key)


def make_color_button(master: tk.Misc, text: str, command: Callable[[], None], font: FontSpec,
                      colors: ButtonColors) -> tk.Widget:
    """A coloured button: canvas-drawn on macOS (native buttons cannot be coloured), a plain tk.Button elsewhere."""
    if master.tk.call("tk", "windowingsystem") == "aqua":
        return ColorButton(master, text, command, font, colors)
    return tk.Button(master, text=text, command=command, font=font, background=colors.normal,
                     activebackground=colors.pressed, foreground=colors.text, activeforeground=colors.text)
