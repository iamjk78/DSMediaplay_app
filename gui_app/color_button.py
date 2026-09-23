import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from typing import Callable, List, Optional, Union

from gui_app.tooltip import hide_if_shown

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
# White text needs a really dark fill: 5.1:1 contrast (the light fills with black text have more than 14:1)
GREEN_DARK = ButtonColors(normal="#2e7d32", hover="#276b2b", pressed="#205a24", border="#1b4d1f", text="#ffffff")


YELLOW = ButtonColors(normal="#fff2b3", hover="#ffea8a", pressed="#ffe066", border="#d1b640")
PURPLE = ButtonColors(normal="#e4d1f7", hover="#d6bdf2", pressed="#c7a5ec", border="#a97fd1")
# A button that cannot be used: grey, dark enough text to read but clearly not the coloured one
DISABLED = ButtonColors(normal="#e6e6e6", hover="#e6e6e6", pressed="#e6e6e6", border="#c4c4c4", text="#8a8a8a")
BLUE = ButtonColors(normal="#c7dcf7", hover="#b4d0f3", pressed="#9ec2ec", border="#7f9fcc")


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
                 colors: ButtonColors, min_width: int = 0, padding_x: int = PADDING_X) -> None:
        super().__init__(master, background=master.cget("background"), highlightthickness=0, borderwidth=0,
                         takefocus=0)
        self._text, self._command, self._font, self._colors = text, command, font, colors
        self._min_width, self._padding_x = min_width, padding_x
        self._enabled = True
        self._interactive = True
        self._state = "normal"
        self._draw()
        self.bind("<Enter>", lambda _: self._set_state("hover"))
        self.bind("<Leave>", lambda _: self._set_state("normal"))
        self.bind("<ButtonPress-1>", lambda _: self._set_state("pressed"))
        self.bind("<ButtonRelease-1>", self._release)

    def natural_width(self) -> int:
        """The width the text needs, whatever the minimum width is."""
        return tkfont.Font(root=self, font=self._font).measure(self._text) + 2 * self._padding_x

    def set_min_width(self, width: int) -> None:
        self._min_width = width
        self._draw()

    def _draw(self) -> None:
        measure = tkfont.Font(root=self, font=self._font)
        width = max(self.natural_width(), self._min_width)
        height = measure.metrics("linespace") + 2 * PADDING_Y
        tk.Canvas.configure(self, width=width, height=height)
        self.delete("all")
        colors = self._colors if self._enabled else DISABLED
        fill = {"normal": colors.normal, "hover": colors.hover, "pressed": colors.pressed}
        self.create_polygon(_rounded_rectangle(1, 1, width - 1, height - 1, RADIUS), smooth=True,
                            fill=fill[self._state], outline=colors.border)
        self.create_text(width / 2, height / 2, text=self._text, font=self._font, fill=colors.text)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """A disabled button is grey, does not react to the pointer and does not run its command."""
        self._enabled = enabled
        self._state = "normal"
        self._draw()

    @property
    def interactive(self) -> bool:
        return self._interactive

    def set_interactive(self, interactive: bool) -> None:
        """A button that is not interactive keeps its colours but does not react to the pointer or run its command."""
        self._interactive = interactive
        self._state = "normal"
        self._draw()

    def set_colors(self, colors: ButtonColors) -> None:
        self._colors = colors
        self._draw()

    def _set_state(self, state: str) -> None:
        if not self._enabled or not self._interactive:
            return
        self._state = state
        self._draw()

    def _release(self, event: tk.Event) -> None:
        if not self._enabled or not self._interactive:
            return
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


def set_button_colors(button: tk.Widget, colors: ButtonColors) -> None:
    """Changes the colours of a button made by make_color_button."""
    if isinstance(button, ColorButton):
        button.set_colors(colors)
    else:
        button.configure(background=colors.normal, activebackground=colors.pressed, foreground=colors.text,
                         activeforeground=colors.text)


def make_color_button(master: tk.Misc, text: str, command: Callable[[], None], font: FontSpec,
                      colors: ButtonColors, padding_x: int = PADDING_X) -> tk.Widget:
    """A coloured button: canvas-drawn on macOS (native buttons cannot be coloured), a plain tk.Button elsewhere."""
    if master.tk.call("tk", "windowingsystem") == "aqua":
        return ColorButton(master, text, command, font, colors, padding_x=padding_x)
    return tk.Button(master, text=text, command=command, font=font, background=colors.normal,
                     activebackground=colors.pressed, foreground=colors.text, activeforeground=colors.text)


def equalize_widths(*buttons: tk.Widget) -> None:
    """Gives buttons made by make_color_button the same width: the widest one's (canvas), or the same number of
    characters (native buttons, which are sized in characters of their font)."""
    canvas_buttons = [button for button in buttons if isinstance(button, ColorButton)]
    if canvas_buttons:
        for button in canvas_buttons:
            button.set_min_width(0)
        widest = max(button.natural_width() for button in canvas_buttons)
        for button in canvas_buttons:
            button.set_min_width(widest)
    else:
        characters = max(len(str(button.cget("text"))) for button in buttons)
        for button in buttons:
            button.configure(width=characters)


def set_button_enabled(button: tk.Widget, enabled: bool, colors: ButtonColors) -> None:
    """Switches a button made by make_color_button on (in `colors`) or off (grey)."""
    if not enabled:
        hide_if_shown(button)  # a disabled button cannot be trusted to still say when the pointer leaves it
    if isinstance(button, ColorButton):
        button.set_enabled(enabled)
    else:
        shown = colors if enabled else DISABLED
        button.configure(state="normal" if enabled else "disabled", background=shown.normal,
                         activebackground=shown.pressed, foreground=shown.text, activeforeground=shown.text,
                         disabledforeground=DISABLED.text)


def button_enabled(button: tk.Widget) -> bool:
    return button.enabled if isinstance(button, ColorButton) else str(button.cget("state")) != "disabled"


def set_button_interactive(button: tk.Widget, interactive: bool, colors: ButtonColors) -> None:
    """Shows a button in `colors` and lets it be pressed, or not: unlike a disabled button it stays coloured."""
    if not interactive:
        hide_if_shown(button)  # a disabled button cannot be trusted to still say when the pointer leaves it
    if isinstance(button, ColorButton):
        button.set_colors(colors)
        button.set_interactive(interactive)
    else:
        button.configure(state="normal" if interactive else "disabled", background=colors.normal,
                         activebackground=colors.pressed, foreground=colors.text, activeforeground=colors.text,
                         disabledforeground=colors.text)


def button_interactive(button: tk.Widget) -> bool:
    return button.interactive if isinstance(button, ColorButton) else str(button.cget("state")) != "disabled"
