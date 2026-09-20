import tkinter as tk
from typing import Callable, Optional

TOOLTIP_DELAY_MS = 500
WATCH_INTERVAL_MS = 250
# Distance from the pointer's hotspot: the arrow cursor reaches ~15 px to the right of it, and the tooltip must never
# sit under the pointer, or entering it would count as leaving the button and the tooltip would flicker
GAP_RIGHT_OF_POINTER = 20
GAP_LEFT_OF_POINTER = 8


class Tooltip:
    """
    Floating help shown to the right of the pointer (to the left when there is no room) when it rests on `widget`
    for `delay_ms`, hidden when it leaves or the widget is clicked. The text is read when the tooltip appears,
    so it always follows the current language.

    It must never stay behind: a <Leave> is not always delivered (a window opened over the widget, a modal window
    holding the grab, the window hidden or the application switched away), so while the tooltip is showing it is
    checked every WATCH_INTERVAL_MS that the pointer is still on the widget, and it goes away when it is not.
    """

    def __init__(self, widget: tk.Widget, text: Callable[[], str], delay_ms: int = TOOLTIP_DELAY_MS) -> None:
        self._widget = widget
        self._text = text
        self._delay_ms = delay_ms
        self._after_id: Optional[str] = None
        self._watch_id: Optional[str] = None
        self._window: Optional[tk.Toplevel] = None
        self._label: Optional[tk.Label] = None
        self._pointer = (0, 0)
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Motion>", self._remember_pointer, add="+")
        # A button that binds <ButtonPress-1> itself (the canvas-drawn ones) would shadow a generic <ButtonPress>
        # binding, since only the most specific matching sequence runs: the left click needs its own entry
        for event in ("<Leave>", "<ButtonPress>", "<ButtonPress-1>", "<Destroy>"):
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
        self._label = tk.Label(window, font=self._font(), background="#ffffe1", foreground="#000000",
                               relief="solid", borderwidth=1, padx=6, pady=3, justify="left", wraplength=340)
        self._label.pack()
        for event in ("<Enter>", "<ButtonPress>"):  # a tooltip under the pointer is always in the way: dismiss it
            window.bind(event, self._hide)
            self._label.bind(event, self._hide)
        self._window = window

    def _font(self):
        try:
            return self._widget.cget("font")
        except tk.TclError:  # themed (ttk) buttons have no font option of their own
            return "TkDefaultFont"

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

    def _pointer_over_widget(self) -> bool:
        """The pointer is on the widget itself, not on a window that has been opened over it."""
        try:
            return str(self._widget.winfo_containing(*self._widget.winfo_pointerxy())) == str(self._widget)
        except (tk.TclError, KeyError):  # the widget is gone; a popup under the pointer is not in Tk's window table
            return False

    def _watch(self) -> None:
        self._watch_id = None
        if self._window is None or self._window.state() != "normal":
            return
        if self._pointer_over_widget():
            self._watch_id = self._widget.after(WATCH_INTERVAL_MS, self._watch)
        else:
            self._hide()

    def _show(self) -> None:
        self._after_id = None
        text = self._text()
        if not text or not self._pointer_over_widget():
            return
        widget, window = self._widget, self._window
        self._label.configure(text=text, font=self._font())
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
        self._watch_id = widget.after(WATCH_INTERVAL_MS, self._watch)

    def _hide(self, _event=None) -> None:
        try:
            for pending in (self._after_id, self._watch_id):
                if pending is not None:
                    self._widget.after_cancel(pending)
            if self._window is not None:
                self._window.withdraw()
        except tk.TclError:  # the widget is already being destroyed
            pass
        self._after_id = self._watch_id = None
