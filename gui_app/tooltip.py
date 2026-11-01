import time
import tkinter as tk
from typing import Callable, Optional

TOOLTIP_DELAY_MS = 1000
WATCH_INTERVAL_MS = 250
# However long a tooltip has genuinely been read, this is well past it: a last-resort ceiling for whatever kind of
# stuck state the defences below do not catch (an unknown one is what a ceiling like this is for)
MAX_VISIBLE_MS = 4000
# Showing the tooltip's own window can itself fire more than one spurious <Activate> in a row right afterwards
# (measured, on a window that has several tooltips of its own): this is longer than that whole burst ever takes,
# and far too short for a user to have genuinely switched to another application and back in the meantime
IGNORE_ACTIVATE_AFTER_SHOW_MS = 150
# Distance from the pointer's hotspot: the arrow cursor reaches ~15 px to the right of it, and the tooltip must never
# sit under the pointer, or entering it would count as leaving the button and the tooltip would flicker
GAP_RIGHT_OF_POINTER = 20
# The entries of a list are read one after another, so the help comes sooner and stays while it is being read
LIST_TOOLTIP_DELAY_MS = 350
POINTER_POLL_MS = 80  # how often the pointer is looked for while the list of a drop-down is open
LIST_TOOLTIP_MAX_VISIBLE_MS = 30000
GAP_LEFT_OF_POINTER = 8


class Tooltip:
    """
    Floating help shown to the right of the pointer (to the left when there is no room) when it rests on `widget`
    for `delay_ms`, hidden when it leaves or the widget is clicked. The text is read when the tooltip appears,
    so it always follows the current language.

    It must never stay behind: a <Leave> is not always delivered (a window opened over the widget, a modal window
    holding the grab, or the window hidden), so while the tooltip is showing it is checked every WATCH_INTERVAL_MS
    that the pointer is still on the widget, and it goes away when it is not. When another application is brought to
    the front instead (e.g. "Help" opening the browser), the pointer does not move at all, so that check alone
    would not catch it; <Activate> (measured to fire reliably when this application becomes the active one again,
    unlike <Deactivate> or <FocusOut> when it loses that status) closes it the moment the user comes back. The first
    IGNORE_ACTIVATE_AFTER_SHOW_MS after the tooltip appears are not trusted for that, since showing the tooltip's
    own little window fires spurious <Activate> events of its own right away (measured too). Whatever neither of
    those two catches, MAX_VISIBLE_MS does, however that happened.
    """

    def __init__(self, widget: tk.Widget, text: Callable[[], str], delay_ms: int = TOOLTIP_DELAY_MS,
                 max_visible_ms: Optional[int] = None) -> None:
        self._widget = widget
        self._text = text
        self._delay_ms = delay_ms
        self._max_visible_ms = max_visible_ms
        self._after_id: Optional[str] = None
        self._watch_id: Optional[str] = None
        self._expire_id: Optional[str] = None
        self._shown_at: Optional[float] = None
        self._window: Optional[tk.Toplevel] = None
        self._label: Optional[tk.Label] = None
        self._pointer = (0, 0)
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Motion>", self._remember_pointer, add="+")
        # A button that binds <ButtonPress-1> itself (the canvas-drawn ones) would shadow a generic <ButtonPress>
        # binding, since only the most specific matching sequence runs: the left click needs its own entry
        for event in ("<Leave>", "<ButtonPress>", "<ButtonPress-1>", "<Destroy>"):
            widget.bind(event, self._hide, add="+")
        self._watch_activation()
        widget.tooltip = self

    def _watch_activation(self) -> None:
        """
        One <Activate> binding on the window serves all its tooltips (a window of the player table has dozens, and
        every one of them had a binding of its own that Tk ran on each activation).
        """
        top = self._widget.winfo_toplevel()
        registry = getattr(top, "_tooltips", None)
        if registry is None:
            registry = top._tooltips = set()
            top.bind("<Activate>", lambda event: [tooltip._on_activate(event) for tooltip in list(registry)], add="+")
        registry.add(self)
        self._widget.bind("<Destroy>", lambda event: registry.discard(self) if event.widget is self._widget else None,
                          add="+")

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
        self._shown_at = time.monotonic()
        window.deiconify()
        self._watch_id = widget.after(WATCH_INTERVAL_MS, self._watch)
        self._expire_id = widget.after(MAX_VISIBLE_MS if self._max_visible_ms is None else self._max_visible_ms,
                                       self._hide)

    def _on_activate(self, event: tk.Event) -> None:
        if self._shown_at is None or time.monotonic() - self._shown_at >= IGNORE_ACTIVATE_AFTER_SHOW_MS / 1000:
            self._hide(event)

    def _hide(self, _event=None) -> None:
        try:
            for pending in (self._after_id, self._watch_id, self._expire_id):
                if pending is not None:
                    self._widget.after_cancel(pending)
            if self._window is not None:
                self._window.withdraw()
        except tk.TclError:  # the widget is already being destroyed
            pass
        self._after_id = self._watch_id = self._expire_id = None
        self._shown_at = None


class TclListbox(tk.Listbox):
    """
    A Listbox that Tcl made (the list of a ttk drop-down has no Python object), taken as a widget a Tooltip can work
    with: it knows its path and the application, which is all that Tk needs to call its methods.
    """

    def __init__(self, master: tk.Misc, path: str) -> None:  # deliberately not creating a widget: it is there already
        self.master, self.tk, self._w, self.children, self.widgetName = master, master.tk, path, {}, "listbox"

    def winfo_toplevel(self) -> tk.Misc:  # the toplevel of the path is a Tcl-made popup that Tk's name lookup cannot find
        return self.master.winfo_toplevel()


class ListTooltip(Tooltip):
    """
    A Tooltip for the entries of a Listbox: its text is the one `text_of(index)` gives for the entry under the pointer,
    and moving the pointer to another entry hides it and starts the delay again. It stays as long as the pointer rests
    on the entry (the text is read, not glanced at), until the pointer leaves the list.

    The list of a drop-down is open under a grab of the combobox, and the pointer events of such a list do not reach
    a binding reliably, so the pointer is not waited for: while the list is on the screen (`watch`) it is asked where
    the pointer is, like the tooltips ask it whether the pointer is still where they were shown.
    """

    def __init__(self, listbox: tk.Listbox, text_of: Callable[[int], str], delay_ms: int = LIST_TOOLTIP_DELAY_MS) -> None:
        self._index: Optional[int] = None
        self._text_of = text_of
        self._poll_id: Optional[str] = None
        super().__init__(listbox, self._text_of_entry, delay_ms, max_visible_ms=LIST_TOOLTIP_MAX_VISIBLE_MS)

    def _text_of_entry(self) -> str:
        return self._text_of(self._index) if self._index is not None else ""

    def watch(self) -> None:
        """
        Follows the pointer for as long as the list is on the screen; called when it appears. The first look is a
        moment later: the event that says the list appears comes before the list itself is mapped.
        """
        if self._poll_id is None:
            self._poll_id = self._widget.after(POINTER_POLL_MS, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        widget = self._widget
        try:
            if not widget.winfo_ismapped():
                self._index = None
                self._hide()
                return
            pointer_x, pointer_y = widget.winfo_pointerxy()
            x, y = pointer_x - widget.winfo_rootx(), pointer_y - widget.winfo_rooty()
            index = widget.nearest(y) if 0 <= x < widget.winfo_width() and 0 <= y < widget.winfo_height() else None
            self._pointer = (pointer_x, pointer_y)
            if index != self._index:
                self._index = index
                if index is None:
                    self._hide()
                else:
                    self._schedule()
            self._poll_id = widget.after(POINTER_POLL_MS, self._poll)
        except tk.TclError:  # the list is gone
            self._index = None

    def _on_enter(self, event: tk.Event) -> None:  # the poll knows better than an <Enter> that may not come
        pass

    def _pointer_over_widget(self) -> bool:
        return self._index is not None


def hide_if_shown(widget: tk.Widget) -> None:
    """
    Hides `widget`'s tooltip right away, if it has one. For code that is about to disable a widget the pointer
    might still be resting on: a disabled widget cannot be relied on to still report the pointer leaving it (a
    known Tk/Aqua shortcoming), so neither <Leave> nor the watchdog can be trusted to close the tooltip there.
    """
    tooltip = getattr(widget, "tooltip", None)
    if tooltip is not None:
        tooltip._hide()
