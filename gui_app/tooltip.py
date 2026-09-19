import tkinter as tk
from typing import Callable, Optional

TOOLTIP_DELAY_MS = 500


class Tooltip:
    """
    Floating help shown when the pointer rests on `widget` for `delay_ms`, hidden when it leaves or the widget is
    clicked. The text is read when the tooltip appears, so it always follows the current language.
    """

    def __init__(self, widget: tk.Widget, text: Callable[[], str], delay_ms: int = TOOLTIP_DELAY_MS) -> None:
        self._widget = widget
        self._text = text
        self._delay_ms = delay_ms
        self._after_id: Optional[str] = None
        self._window: Optional[tk.Toplevel] = None
        self._label: Optional[tk.Label] = None
        widget.bind("<Enter>", self._schedule, add="+")
        for event in ("<Leave>", "<ButtonPress>", "<Destroy>"):
            widget.bind(event, self._hide, add="+")
        widget.tooltip = self

    def _create_window(self) -> None:
        """Built while the delay runs: creating a window on demand added ~130 ms to the first appearance."""
        window = tk.Toplevel(self._widget)
        window.withdraw()
        if window.tk.call("tk", "windowingsystem") == "aqua":
            # A plain borderless window is drawn below the application window on macOS; the "help" style is the
            # one Tk itself uses for tooltips: no title bar, no activation, above normal windows
            window.tk.call("::tk::unsupported::MacWindowStyle", "style", window, "help", "noActivates")
        else:
            window.wm_overrideredirect(True)
        window.attributes("-topmost", True)
        # Fixed light colours: readable on both light and dark system themes
        self._label = tk.Label(window, font=self._widget.cget("font"), background="#ffffe1", foreground="#000000",
                               relief="solid", borderwidth=1, padx=6, pady=3, justify="left", wraplength=340)
        self._label.pack()
        self._window = window

    def _schedule(self, _event=None) -> None:
        self._hide()
        self._after_id = self._widget.after(self._delay_ms, self._show)
        if self._window is None:  # after the timer started, so building the window does not lengthen the delay
            self._create_window()

    def _show(self) -> None:
        self._after_id = None
        text = self._text()
        if not text:
            return
        widget, window = self._widget, self._window
        self._label.configure(text=text, font=widget.cget("font"))
        window.update_idletasks()
        width, height = window.winfo_reqwidth(), window.winfo_reqheight()
        x = min(widget.winfo_rootx(), widget.winfo_screenwidth() - width - 8)
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        if y + height > widget.winfo_screenheight():
            y = widget.winfo_rooty() - height - 4
        window.geometry(f"+{max(x, 0)}+{y}")
        window.deiconify()

    def _hide(self, _event=None) -> None:
        try:
            if self._after_id is not None:
                self._widget.after_cancel(self._after_id)
            if self._window is not None:
                self._window.withdraw()
        except tk.TclError:  # the widget is already being destroyed
            pass
        self._after_id = None
