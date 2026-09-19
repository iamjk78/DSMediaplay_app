import tkinter as tk
from typing import Callable, Optional

TOOLTIP_DELAY_MS = 500
# Distance from the pointer's hotspot: the arrow cursor reaches ~15 px to the right of it, and the tooltip must never
# sit under the pointer, or entering it would count as leaving the button and the tooltip would flicker
GAP_RIGHT_OF_POINTER = 20
GAP_LEFT_OF_POINTER = 8


class Tooltip:
    """
    Floating help shown to the right of the pointer (to the left when there is no room) when it rests on `widget`
    for `delay_ms`, hidden when it leaves or the widget is clicked. The text is read when the tooltip appears,
    so it always follows the current language.
    """

    def __init__(self, widget: tk.Widget, text: Callable[[], str], delay_ms: int = TOOLTIP_DELAY_MS) -> None:
        self._widget = widget
        self._text = text
        self._delay_ms = delay_ms
        self._after_id: Optional[str] = None
        self._window: Optional[tk.Toplevel] = None
        self._label: Optional[tk.Label] = None
        self._pointer = (0, 0)
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Motion>", self._remember_pointer, add="+")
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

    def _remember_pointer(self, event: tk.Event) -> None:
        self._pointer = (event.x_root, event.y_root)

    def _on_enter(self, event: tk.Event) -> None:
        self._remember_pointer(event)
        self._schedule()

    def _schedule(self) -> None:
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
        pointer_x, pointer_y = self._pointer
        x = pointer_x + GAP_RIGHT_OF_POINTER
        if x + width > widget.winfo_screenwidth() - 4:
            x = pointer_x - GAP_LEFT_OF_POINTER - width
        y = pointer_y - height // 2
        y = min(max(y, 0), widget.winfo_screenheight() - height - 4)
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
