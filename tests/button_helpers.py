"""The coloured buttons of the application are drawn on a canvas on macOS and are native buttons on Windows. These
look at them, and press them, the same way on both."""
from gui_app.color_button import ColorButton, button_enabled, button_interactive

__all__ = ["press", "is_enabled", "is_interactive", "fill", "normal_fill", "font_of"]


def press(button) -> None:
    """A click on the button, as the mouse does it (a disabled native button does nothing, like the real one)."""
    if isinstance(button, ColorButton):
        button.event_generate("<ButtonPress-1>", x=5, y=5)
        button.event_generate("<ButtonRelease-1>", x=5, y=5)
    else:
        button.invoke()


def is_enabled(button) -> bool:
    return button_enabled(button)


def is_interactive(button) -> bool:
    return button_interactive(button)


def fill(button) -> str:
    """The colour the button is filled with now."""
    if isinstance(button, ColorButton):
        return button.itemcget(button.find_withtag("all")[0], "fill")
    return str(button.cget("background"))


def normal_fill(button) -> str:
    """The colour the button has when nothing touches it: its own colour, or grey when it is off."""
    if isinstance(button, ColorButton):
        return button._colors.normal if button.enabled else fill(button)
    return str(button.cget("background"))


def font_of(widget) -> tuple:
    """The font of a widget as (family, size, style...), whatever way Tk gives it back."""
    value = widget.cget("font")
    parts = tuple(widget.tk.splitlist(value)) if isinstance(value, str) else tuple(value)
    return (parts[0], int(parts[1])) + tuple(parts[2:])
