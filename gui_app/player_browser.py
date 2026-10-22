import contextlib
import functools
import math
import queue
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from tkinter import font as tkfont
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Tuple

import requests

from api_testing.request_calls import LoginError, ServerApi
from gui_app.color_button import GREEN, RED, make_color_button, set_button_colors, set_button_interactive
from gui_app.icons import set_window_icon
from gui_app.multi_select import MultiSelectCombo
from gui_app.snapshot_viewer import (CASCADE_STEP, SnapshotSlots, SnapshotViewer, fetch_snapshot_from_server,
                                     valid_window_size)
from gui_app.tooltip import Tooltip, hide_if_shown
from util.accounts import DEFAULT_HIDDEN_COLUMNS
from gui_app.wheel import wheel_units
from util.player_filter import (AGE_OPTIONS, TEMPERATURE_OPTIONS, PlayerFilter, PlayerRow, apply_filter, player_row,
                                sort_rows, version_key)

# key, header message, default width in characters
COLUMNS = (
    ("name", "pb_col_name", 30),
    ("status", "pb_col_status", 9),
    ("group", "pb_col_group", 20),
    ("location", "pb_col_location", 22),
    ("label", "pb_col_label", 22),
    ("synced", "pb_col_synced", 17),
    ("reported", "pb_col_reported", 17),
    ("note", "pb_col_note", 30),
    ("temperature", "pb_col_temperature", 12),
    ("version", "pb_col_version", 14),
)
TOGGLE_COLUMNS = ("group", "location", "label", "synced", "reported", "note", "temperature", "version")  # the others are always shown
MIN_COLUMN_WIDTH = 56  # pixels; a column is never narrower than its filter needs either
MAX_COLUMN_WIDTH = 1500
SEPARATOR_WIDTH = 7  # the space between two columns; the line itself is 1 px wide
EDGE_ZONE = 10  # pixels to each side of a line where the pointer changes and the column can be resized
RESIZE_CURSOR = "sb_h_double_arrow"
SORT_CURSOR = "hand2"
SEPARATOR_COLOR = "black"
SNAPSHOT_COLUMN_MINSIZE = 110  # the first column, with the button; as wide as this at least
MIN_FONT_SIZE, MAX_FONT_SIZE = 8, 20
BUTTON_STYLE = "PlayerBrowser.TButton"
CHECK_STYLE = "PlayerBrowser.TCheckbutton"
SMALL_A_STYLE = "PlayerBrowserSmallA.TButton"
LARGE_A_STYLE = "PlayerBrowserLargeA.TButton"
ONLINE_COLOR = "#2e7d32"
OFFLINE_COLOR = "#c62828"
NAME_FILTER_DELAY_MS = 150
GEOMETRY_REPORT_DELAY_MS = 600  # quiet time after the window was moved or resized before that is reported
MIN_WINDOW_SIDE, MAX_WINDOW_SIDE, MAX_WINDOW_POSITION = 300, 10000, 20000
WINDOW_HEIGHT = 600  # of a window that has no size saved
SCREEN_MARGIN = (20, 120)  # what a window is kept smaller than the screen by: the room for the borders and the dock
GEOMETRY_PATTERN = re.compile(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)")
MAX_SNAPSHOT_WINDOWS = 5  # players whose snapshot can be open at the same time
MIN_REFRESH_INTERVAL = 10  # seconds between the starts of two downloads, however often the button is pressed
AUTO_REFRESH_SECONDS = 600  # a window that is left open updates itself this long after its last download started
AUTO_REFRESH_RETRY_MS = 5000  # how long an automatic update waits when the user is in the middle of something
COUNTDOWN_TICK_MS = 500
POLL_INTERVAL_MS = 100
CELL_PADDING = 4
ROW_PADY = 1
POOL_OVERSCAN = 1  # a couple more pool rows than the canvas strictly needs, so a partial row is never left blank


def _clock() -> float:
    return time.monotonic()


def frozen_table(method):
    """The method changes the table (its rows, columns or text size) with the table hidden meanwhile; see _frozen."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._frozen():
            return method(self, *args, **kwargs)
    return wrapper


def fetch_players_from_server(url: str, login: str, password: str) -> List[Dict]:
    server = ServerApi(url=f"{url}/api", login=login, password=password)
    try:
        return server.get_player_objects()
    finally:
        server.close_quietly()  # an answer to the logout that is not what was expected must not lose the players


def valid_widths(raw) -> Dict[str, int]:
    """The saved widths that make sense; anything else (a hand-edited or damaged config) is ignored."""
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key, _, _ in COLUMNS
            if isinstance(raw.get(key), int) and not isinstance(raw[key], bool)
            and MIN_COLUMN_WIDTH <= raw[key] <= MAX_COLUMN_WIDTH}


def valid_hidden(raw) -> FrozenSet[str]:
    """The saved hidden columns that exist and may be hidden; anything else is ignored."""
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(key for key in raw if key in TOGGLE_COLUMNS)


def valid_window_geometry(raw) -> Optional[Tuple[int, int, int, int]]:
    """A saved size and position as (width, height, x, y), or None: a hand-edited or damaged config is ignored."""
    if not (isinstance(raw, (list, tuple)) and len(raw) == 4
            and all(isinstance(value, int) and not isinstance(value, bool) for value in raw)):
        return None
    width, height, x, y = raw
    if (MIN_WINDOW_SIDE <= width <= MAX_WINDOW_SIDE and MIN_WINDOW_SIDE <= height <= MAX_WINDOW_SIDE
            and abs(x) <= MAX_WINDOW_POSITION and abs(y) <= MAX_WINDOW_POSITION):
        return width, height, x, y
    return None


def valid_font_size(raw) -> Optional[int]:
    """A saved font size that makes sense, or None."""
    if isinstance(raw, int) and not isinstance(raw, bool) and MIN_FONT_SIZE <= raw <= MAX_FONT_SIZE:
        return raw
    return None


class PlayerBrowser(tk.Toplevel):
    """
    The players of one account in a table that can be filtered by every column but the button.
    The data is fetched once (and again on "Refresh"); the filters work on it locally. The columns can be resized by
    dragging the black lines between them (anywhere along a line, EDGE_ZONE pixels to each side of it);
    `save_column_widths` is called with the widths when the user lets go
    (and with {} when they go back to the defaults).

    The rows on the screen (`_pool`) are a fixed, small set of widgets, as many as fit the window: with an account
    of thousands of players a row of widgets for every single one would be far too many for Tk to keep up with, so
    scrolling instead moves which player's data a row shows (`_first_index`, the index into `_visible` the pool
    starts at), the same few dozen widgets the whole time. A player scrolled out of view has no widgets of its own
    until it is scrolled back into view.
    """

    def __init__(self, master, *, url: str, login: str, password: str, account_name: str,
                 fetch: Callable[[str, str, str], List[Dict]] = fetch_players_from_server,
                 column_widths: Optional[Dict[str, int]] = None,
                 save_column_widths: Callable[[Dict[str, int]], None] = lambda widths: None,
                 hidden_columns: Optional[Iterable[str]] = None,
                 save_hidden_columns: Callable[[List[str]], None] = lambda hidden: None,
                 font_size: Optional[int] = None,
                 save_font_size: Callable[[int], None] = lambda size: None,
                 snapshot_fetch: Callable[[str, str, str, str], Tuple[bytes, str]] = fetch_snapshot_from_server,
                 snapshot_size=None,
                 save_snapshot_size: Callable[[Tuple[int, int]], None] = lambda size: None,
                 window_geometry=None,
                 save_window_geometry: Callable[[Tuple[int, int, int, int]], None] = lambda geometry: None):
        super().__init__(master)
        self.lang = master.lang
        self.connection = (url, login)
        self._credentials = (url, login, password)
        self._fetch = fetch
        self._save_column_widths = save_column_widths
        self._hidden = set(DEFAULT_HIDDEN_COLUMNS) if hidden_columns is None else set(valid_hidden(hidden_columns))
        self._save_hidden_columns = save_hidden_columns
        self._family = master.font[0]
        self._font_size = valid_font_size(font_size) or min(max(master.font[1], MIN_FONT_SIZE), MAX_FONT_SIZE)
        self._font = (self._family, self._font_size)
        self._save_font_size = save_font_size
        self._first_width = SNAPSHOT_COLUMN_MINSIZE
        self._configure_styles()
        self._rows: List[PlayerRow] = []
        self._visible: List[PlayerRow] = []
        self._pool: List[List[tk.Widget]] = []  # the row widgets on screen, reused for whatever row scrolls into them
        self._pool_rows: List[Optional[PlayerRow]] = []  # which row (if any) each pool slot currently shows
        self._pool_size = 0
        self._whole_rows = 1  # how many rows are entirely inside the canvas; the one beyond them is cut off
        self._first_index = 0  # index into _visible of the row the pool's first slot currently shows
        self._sort = ("name", False)
        self._results: "queue.Queue" = queue.Queue()
        self._snapshot_fetch = snapshot_fetch
        self._saved_geometry = valid_window_geometry(window_geometry)  # where the user left this window last time
        self._save_window_geometry = save_window_geometry
        self._known_geometry: Optional[Tuple[int, int, int, int]] = None
        self._geometry_after_id: Optional[str] = None
        self._snapshot_size = valid_window_size(snapshot_size)  # what the user made the snapshot windows, if they did
        self._save_snapshot_size = save_snapshot_size
        self._snapshot_slots = SnapshotSlots()  # shared by the snapshot windows of this account
        self._viewers: Dict[str, SnapshotViewer] = {}  # by the id of the player: one window for each
        self._loading = False
        self._drag = None
        self._filter_after_id: Optional[str] = None
        self._poll_after_id: Optional[str] = None
        self._tick_after_id: Optional[str] = None
        self._auto_after_id: Optional[str] = None
        self._settle_after_id: Optional[str] = None
        self._last_fetch_started: Optional[float] = None
        self._pending = False  # an update was asked for while it was too early: it runs when the interval is over
        self._updated_at: Optional[datetime] = None  # when the players shown were fetched
        self._failed = False  # the last download failed: what is shown is older
        self._combo_values: Dict[ttk.Combobox, Dict[str, Optional[str]]] = {}
        zero = tkfont.Font(root=self, font=self._font).measure("0")
        self._default_widths = {key: chars * zero + 2 * CELL_PADDING for key, _, chars in COLUMNS}
        self._customized = bool(valid_widths(column_widths))  # the user has set widths: they follow the font by ratio
        self._widths = {**self._default_widths, **valid_widths(column_widths)}

        self.title(self.lang.get_message("pb_title", account=account_name))
        set_window_icon(self)
        self._build_actions()
        self._build_table()
        self.status_var = tk.StringVar()
        self.updated_var = tk.StringVar()
        bottom = tk.Frame(self)
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        bottom.grid_columnconfigure(0, weight=1)
        self._status_label = tk.Label(bottom, textvariable=self.status_var, font=self._font, anchor="w")
        self._status_label.grid(row=0, column=0, sticky="ew")
        self._default_status_color = str(self._status_label.cget("foreground"))
        self._updated_label = tk.Label(bottom, textvariable=self.updated_var, font=self._font, anchor="e")
        self._updated_label.grid(row=0, column=1, sticky="e")
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._fit_window()
        self.bind("<Configure>", self._on_window_configure, add="+")
        self.refresh()

    # ---- construction

    def _build_actions(self):
        bar = self._actions_bar = tk.Frame(self)
        bar.grid(row=0, column=0, sticky="w", padx=10, pady=(8, 0))
        left = self._actions_left = tk.Frame(bar)
        left.grid(row=0, column=0, sticky="w")
        self.refresh_button = self._button(left, "pb_refresh", "pb_tip_refresh", self.refresh)
        self.reset_button = self._button(left, "pb_reset", "pb_tip_reset", self.reset_filters)
        self.default_columns_button = self._button(left, "pb_default_columns", "pb_tip_default_columns",
                                                   self.reset_columns)
        self._toggle_separator = ttk.Separator(bar, orient="vertical")
        group = self._toggle_group = tk.Frame(bar)
        self._columns_label = tk.Label(group, text=self.lang.get_message("pb_columns"), font=self._font)
        self._columns_label.pack(side="left", padx=(0, 8))
        header = {key: message for key, message, _ in COLUMNS}
        self.column_buttons: Dict[str, tk.Widget] = {}
        for key in TOGGLE_COLUMNS:  # each as wide as its text; green = shown, red = hidden
            button = make_color_button(group, self.lang.get_message(header[key]),
                                       lambda column=key: self.toggle_column(column), self._font, GREEN)
            button.pack(side="left", padx=(0, 6))
            self.column_buttons[key] = button
        self._layout_actions()
        self._update_toggle_colors()

    def _layout_actions(self):
        """The column switches stand right of the buttons; on a screen too narrow for that they go below them."""
        self.update_idletasks()
        fits = (self._actions_left.winfo_reqwidth() + self._toggle_group.winfo_reqwidth() + 60
                <= self.winfo_screenwidth() - 40)
        if fits:
            self._toggle_separator.grid(row=0, column=1, sticky="ns", padx=(8, 12))
            self._toggle_group.grid(row=0, column=2, sticky="w", pady=0)
        else:
            self._toggle_separator.grid_remove()
            self._toggle_group.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def _button(self, bar, message: str, tip: str, command) -> ttk.Button:
        button = ttk.Button(bar, text=self.lang.get_message(message), command=command, style=BUTTON_STYLE)
        button.pack(side="left", padx=(0, 6))
        Tooltip(button, lambda: self.lang.get_message(tip))
        return button

    def _build_filters(self):
        """
        One filter per column, standing in the column it filters: the left edge of a filter is the left edge of its
        column and it is as wide as the column (the widgets ask for next to no width, so the column decides).
        """
        self._filter_widgets: Dict[str, tk.Widget] = {}
        self.name_var = tk.StringVar()
        self.name_var.trace_add("write", lambda *_: self._schedule_filter())
        self.note_var = tk.StringVar()
        self.note_var.trace_add("write", lambda *_: self._schedule_filter())
        self.name_entry = tk.Entry(self._filters, textvariable=self.name_var, width=1, font=self._font)
        self.name_entry.focus_set()
        self.status_box = self._combobox()
        self.group_box = self._multi_select()
        self.location_box = self._multi_select()
        self.label_box = self._multi_select()
        self.synced_box = self._combobox()
        self.reported_box = self._combobox()
        self.note_entry = tk.Entry(self._filters, textvariable=self.note_var, width=1, font=self._font)
        self.temperature_box = self._combobox()
        self.version_box = self._multi_select()
        for index, (key, widget) in enumerate(zip(
                (key for key, _, _ in COLUMNS),
                (self.name_entry, self.status_box, self.group_box, self.location_box, self.label_box,
                 self.synced_box, self.reported_box, self.note_entry, self.temperature_box, self.version_box))):
            widget.grid(row=0, column=self._cell_column(index), sticky="ew", padx=CELL_PADDING, pady=2)
            self._filter_widgets[key] = widget
        self._build_font_buttons()
        all_text = self.lang.get_message("pb_all")
        self._set_choices(self.status_box, {all_text: None, self.lang.get_message("pb_online"): True,
                                            self.lang.get_message("pb_offline"): False})
        ages = {all_text: None} | {self.lang.get_message(f"pb_age_{key}"): criterion for key, criterion in AGE_OPTIONS}
        self._set_choices(self.synced_box, ages)
        self._set_choices(self.reported_box, ages)
        self._set_choices(self.temperature_box, {all_text: None} | {
            self.lang.get_message(f"pb_temp_{key}"): criterion for key, criterion in TEMPERATURE_OPTIONS})

    def _build_font_buttons(self):
        """A small and a large "A" in the free place above the screenshot buttons: smaller and larger text."""
        holder = self._font_holder = tk.Frame(self._filters)
        holder.grid(row=0, column=0, sticky="w", padx=CELL_PADDING, pady=2)
        self.smaller_font_button = ttk.Button(holder, text="A", style=SMALL_A_STYLE, width=1,
                                              command=lambda: self.change_font_size(-1))
        self.smaller_font_button.pack(side="left", padx=(0, 3))
        self.larger_font_button = ttk.Button(holder, text="A", style=LARGE_A_STYLE, width=1,
                                             command=lambda: self.change_font_size(1))
        self.larger_font_button.pack(side="left")
        Tooltip(self.smaller_font_button, lambda: self.lang.get_message("pb_font_smaller", size=self._font_size))
        Tooltip(self.larger_font_button, lambda: self.lang.get_message("pb_font_larger", size=self._font_size))
        self._update_font_buttons()

    def _combobox(self) -> ttk.Combobox:
        box = ttk.Combobox(self._filters, state="readonly", width=1, font=self._font)
        box.bind("<<ComboboxSelected>>", lambda _: self.apply_filters())
        return box

    def _multi_select(self) -> MultiSelectCombo:
        return MultiSelectCombo(self._filters, self, font=self._font, width=1, on_change=self._schedule_filter,
                                check_style=CHECK_STYLE)

    def _compute_minimum_widths(self):
        """A column cannot be narrower than what its filter needs, so a filter is never squeezed out of sight."""
        self.update_idletasks()
        self._min_widths = {}
        for key, widget in self._filter_widgets.items():
            needed = widget.minimum_width() if isinstance(widget, MultiSelectCombo) else widget.winfo_reqwidth()
            self._min_widths[key] = max(MIN_COLUMN_WIDTH, needed + 2 * CELL_PADDING)
        self._default_widths = {key: max(width, self._min_widths[key]) for key, width in self._default_widths.items()}
        self._widths = {key: max(width, self._min_widths[key]) for key, width in self._widths.items()}
        self._measure_first_column()

    def _measure_first_column(self):
        """The first column holds the screenshot buttons and the font buttons: never narrower than they need."""
        probe = make_color_button(self, self.lang.get_message("pb_snapshot"), lambda: None, self._font, GREEN)
        self.update_idletasks()
        needed = max(probe.winfo_reqwidth(), self._font_holder.winfo_reqwidth())
        probe.destroy()
        self._first_width = max(SNAPSHOT_COLUMN_MINSIZE, needed + 2 * CELL_PADDING)

    def _build_table(self):
        frame = self._table = tk.Frame(self)
        frame.grid(row=1, column=0, sticky="nsew", padx=10)
        frame.grid_rowconfigure(2, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        bold = (self._font[0], self._font[1], "bold")

        # The filters, the header and the rows are three grids with the same column widths; all scroll sideways together
        self._filter_canvas = tk.Canvas(frame, height=1, width=1, highlightthickness=0, borderwidth=0)
        self._filter_canvas.grid(row=0, column=0, sticky="ew", pady=(8, 0))
        self._filters = tk.Frame(self._filter_canvas)
        self._filter_canvas.create_window((0, 0), window=self._filters, anchor="nw")
        self._build_filters()
        self._header_canvas = tk.Canvas(frame, height=1, width=1, highlightthickness=0, borderwidth=0)
        self._header_canvas.grid(row=1, column=0, sticky="ew")
        self._header = tk.Frame(self._header_canvas)
        self._header_canvas.create_window((0, 0), window=self._header, anchor="nw")
        self._header_cells: Dict[str, tk.Label] = {}
        self._header_separators: List[tk.Canvas] = []
        for index, (key, _, _) in enumerate(COLUMNS):
            cell = tk.Label(self._header, font=bold, width=1, anchor="w", cursor=SORT_CURSOR)
            cell.grid(row=0, column=self._cell_column(index), sticky="ew", padx=CELL_PADDING)
            cell.bind("<Button-1>", lambda event, column=key: self._on_header_click(event, column))
            self._header_cells[key] = cell
            self._header_separators.append(self._header_separator(index, key))
        self._show_sort_arrow()

        self._canvas = tk.Canvas(frame, width=1, height=1, highlightthickness=0, borderwidth=0)
        # The vertical scrollbar does not reflect the canvas (there is nothing left of it to scroll: see _scroll_y);
        # _update_scrollbar sets it instead, whenever the pool's position in the filtered rows changes.
        self._scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self._scroll_y)
        self._x_scrollbar = ttk.Scrollbar(frame, orient="horizontal", command=self._scroll_x)
        self._canvas.configure(xscrollcommand=self._on_x_scrolled)
        self._canvas.grid(row=2, column=0, sticky="nsew")
        self._scrollbar.grid(row=2, column=1, sticky="ns")
        self._x_scrollbar.grid(row=3, column=0, sticky="ew")
        self._body = tk.Frame(self._canvas)
        self._body_separators = [tk.Frame(self._body, width=1, background=SEPARATOR_COLOR) for _ in COLUMNS]
        self._body_item = self._canvas.create_window((0, 0), window=self._body, anchor="nw")
        self._frozen_depth = 0
        self._canvas.bind("<Configure>", lambda _: self._on_canvas_resized())
        for widget in (self._body, self._header, self._filters):
            widget.bind("<Configure>", lambda _: self._update_scroll_regions())
        self._compute_minimum_widths()
        self._apply_widths()
        self._apply_visibility()
        self.bind("<MouseWheel>", self._on_mouse_wheel)
        self.bind("<Shift-MouseWheel>", self._on_shift_mouse_wheel)
        # On the window, not on the lines: the events of every widget of the table arrive here, so the whole
        # length of a line (header and rows) can be grabbed, and the zone reaches over the text beside it.
        # The filters above are left out: a filter is used, not resized
        self.bind("<Motion>", self._on_pointer_move, add="+")
        self.bind("<Leave>", self._on_pointer_leave, add="+")
        self.bind("<ButtonPress-1>", self._start_drag, add="+")
        self.bind("<B1-Motion>", self._drag_to, add="+")
        self.bind("<ButtonRelease-1>", self._end_drag, add="+")

    def _header_separator(self, index: int, key: str) -> tk.Canvas:
        middle = SEPARATOR_WIDTH // 2
        separator = tk.Canvas(self._header, width=SEPARATOR_WIDTH, height=1, highlightthickness=0, borderwidth=0)
        line = separator.create_line(middle, 0, middle, 1, fill=SEPARATOR_COLOR)
        separator.bind("<Configure>", lambda event: separator.coords(line, middle, 0, middle, event.height))
        separator.grid(row=0, column=self._cell_column(index) + 1, sticky="ns")
        return separator

    @staticmethod
    def _cell_column(index: int) -> int:
        """The grid column of the text column `index`: the first grid column holds the button, a line follows each."""
        return 1 + 2 * index

    def _fit_window(self):
        """Opens wide enough for the buttons and, as far as the screen allows, for the whole table."""
        self._layout_actions()
        self.update_idletasks()
        self._header_canvas.configure(height=self._header.winfo_reqheight())
        self._filter_canvas.configure(height=self._filters.winfo_reqheight())
        buttons = self._actions_bar.winfo_reqwidth() + 30
        table = self._header.winfo_reqwidth() + self._scrollbar.winfo_reqwidth() + 30
        self.minsize(buttons, 300)
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        if self._saved_geometry is None:
            self.geometry(f"{min(max(buttons, table), screen_width - SCREEN_MARGIN[0])}x{WINDOW_HEIGHT}")
            return
        width, height, x, y = self._saved_geometry
        width = min(max(width, buttons), screen_width - SCREEN_MARGIN[0])
        height = min(height, screen_height - SCREEN_MARGIN[1])
        place = f"+{x}+{y}" if self._is_reachable(x, y, width) else ""
        self.geometry(f"{width}x{height}{place}")

    def _is_reachable(self, x: int, y: int, width: int) -> bool:
        """
        A position the user can still get at: a monitor may have been unplugged since it was saved. macOS moves a
        window that is off every screen by itself (and Tk knows only the main screen there), elsewhere the position
        is checked against the whole desktop.
        """
        if self.tk.call("tk", "windowingsystem") == "aqua":
            return True
        left, top = self.winfo_vrootx(), self.winfo_vrooty()
        right, bottom = left + self.winfo_vrootwidth(), top + self.winfo_vrootheight()
        return left - width + 100 <= x <= right - 100 and top <= y <= bottom - 50

    def _current_geometry(self) -> Optional[Tuple[int, int, int, int]]:
        found = GEOMETRY_PATTERN.fullmatch(self.geometry())
        return tuple(int(value) for value in found.groups()) if found else None

    def _on_window_configure(self, event):
        """When the user has moved or resized the window (and let go of it) its new place is reported, to be remembered."""
        if event.widget is not self:
            return
        geometry = self._current_geometry()
        if geometry is None or min(geometry[:2]) < MIN_WINDOW_SIDE:  # a new window is 1 x 1 until it gets its size
            return
        if self._known_geometry is None:  # where the window appears: not something the user did
            self._known_geometry = geometry
            return
        if geometry == self._known_geometry:
            return
        self._known_geometry = geometry
        if self._geometry_after_id:
            self.after_cancel(self._geometry_after_id)
        self._geometry_after_id = self.after(GEOMETRY_REPORT_DELAY_MS, self._report_geometry)

    def _report_geometry(self):
        self._geometry_after_id = None
        geometry = self._current_geometry()
        if geometry and valid_window_geometry(geometry) and geometry != self._saved_geometry:
            self._saved_geometry = geometry
            self._save_window_geometry(geometry)

    # ---- font size

    @property
    def font_size(self) -> int:
        return self._font_size

    def _configure_styles(self):
        """The ttk buttons and check boxes take their font from styles; the two "A" buttons keep theirs."""
        style = ttk.Style(self)
        style.configure(BUTTON_STYLE, font=self._font)
        style.configure(CHECK_STYLE, font=self._font)
        style.configure(SMALL_A_STYLE, font=(self._family, 9))
        style.configure(LARGE_A_STYLE, font=(self._family, 15, "bold"))

    def change_font_size(self, step: int):
        self.set_font_size(self._font_size + step)

    def set_font_size(self, size: int):
        """
        Sets the size of the text in this window: the table, the header, the filters and the buttons. The widths the
        user set follow it by ratio (the widths that were never set follow it by themselves).
        """
        size = min(max(size, MIN_FONT_SIZE), MAX_FONT_SIZE)
        if size == self._font_size:
            return
        ratio = size / self._font_size
        self._font_size, self._font = size, (self._family, size)
        self._apply_font(ratio)
        self._save_font_size(size)
        if self._customized:
            self._save_column_widths(self.column_widths())

    @contextlib.contextmanager
    def _frozen(self):
        """
        Hides the rows of the table for as long as it is being changed and shows them, finished, at the end. Every cell
        is a window of its own, and while the table is on the screen each of them is moved and redrawn one after the
        other: with a few hundred players that takes many seconds for a change of the text size, a column or a filter.
        Hidden, the same change takes a fraction of a second. Nothing is painted in between, so nothing flickers.
        Changes inside changes are fine: the rows are shown when the outermost one is done.
        """
        self._frozen_depth += 1
        if self._frozen_depth == 1:
            self._canvas.itemconfigure(self._body_item, state="hidden")
        try:
            yield
        finally:
            self._frozen_depth -= 1
            if self._frozen_depth == 0:
                self.update_idletasks()  # the geometry is worked out while the rows are hidden, which is cheap
                self._canvas.itemconfigure(self._body_item, state="normal")

    @frozen_table
    def _apply_font(self, ratio: float):
        self._configure_styles()
        bold = (self._family, self._font_size, "bold")
        for widget in (self.name_entry, self.note_entry, self.status_box, self.synced_box, self.reported_box,
                       self._status_label, self._updated_label, self._columns_label, *self.column_buttons.values()):
            widget.configure(font=self._font)
        for box in (self.group_box, self.location_box, self.label_box):
            box.set_font(self._font)
        for cell in self._header_cells.values():
            cell.configure(font=bold)
        for viewer in self._viewers.values():
            viewer.set_font(self._font)
        for widgets in self._pool:
            for widget in widgets:  # the button first, then the cells
                widget.configure(font=self._font)
        zero = tkfont.Font(root=self, font=self._font).measure("0")
        self._default_widths = {key: chars * zero + 2 * CELL_PADDING for key, _, chars in COLUMNS}
        self._widths = ({key: round(width * ratio) for key, width in self._widths.items()} if self._customized
                        else dict(self._default_widths))
        self._compute_minimum_widths()
        self._apply_widths()
        self._layout_actions()
        self.update_idletasks()
        self._header_canvas.configure(height=self._header.winfo_reqheight())
        self._filter_canvas.configure(height=self._filters.winfo_reqheight())
        self.minsize(self._actions_bar.winfo_reqwidth() + 30, 300)
        self._update_font_buttons()
        self._render_pool()  # a row's height changed: how many of them fit the canvas may have too
        self._schedule_scroll_update()

    def _update_font_buttons(self):
        # A disabled button cannot be trusted to still say when the pointer leaves it (a known Tk/Aqua shortcoming),
        # so its tooltip is closed right away rather than left to <Leave> or the watchdog to catch, possibly late
        if self._font_size <= MIN_FONT_SIZE:
            hide_if_shown(self.smaller_font_button)
        self.smaller_font_button.state(["disabled"] if self._font_size <= MIN_FONT_SIZE else ["!disabled"])
        if self._font_size >= MAX_FONT_SIZE:
            hide_if_shown(self.larger_font_button)
        self.larger_font_button.state(["disabled"] if self._font_size >= MAX_FONT_SIZE else ["!disabled"])

    # ---- column widths

    def column_widths(self) -> Dict[str, int]:
        return dict(self._widths)

    @frozen_table
    def _apply_widths(self):
        """Every column is exactly as wide as set; the text that does not fit is cut off."""
        for frame in (self._filters, self._header, self._body):
            frame.grid_columnconfigure(0, minsize=self._first_width)
            for index, (key, _, _) in enumerate(COLUMNS):
                hidden = key in self._hidden
                frame.grid_columnconfigure(self._cell_column(index), minsize=0 if hidden else self._widths[key])
                frame.grid_columnconfigure(self._cell_column(index) + 1, minsize=0 if hidden else SEPARATOR_WIDTH)
        self._schedule_scroll_update()

    def _edge_at(self, x_root: int) -> Optional[str]:
        """The column whose right-hand line is within EDGE_ZONE pixels of the pointer, if any."""
        for (key, _, _), separator in zip(COLUMNS, self._header_separators):
            if key in self._hidden:
                continue
            if abs(x_root - (separator.winfo_rootx() + SEPARATOR_WIDTH // 2)) <= EDGE_ZONE:
                return key
        return None

    def _in_table(self, widget) -> bool:
        """The header and the rows, where the lines are; not the filters above them."""
        path = str(widget)
        return any(path == str(part) or path.startswith(str(part) + ".") for part in (self._header_canvas, self._canvas))

    def _on_pointer_move(self, event):
        if not self._in_table(event.widget):
            return
        resize = self._drag is not None or self._edge_at(event.x_root) is not None
        self._set_cursor(event.widget, RESIZE_CURSOR if resize else None)

    def _on_pointer_leave(self, event):
        if self._drag is None and self._in_table(event.widget):
            self._set_cursor(event.widget, None)

    def _set_cursor(self, widget, cursor: Optional[str]):
        """The resize cursor, or the widget's own (the header cells sort, everything else has none)."""
        own = SORT_CURSOR if widget in self._header_cells.values() else ""
        try:
            widget.configure(cursor=cursor or own)
        except tk.TclError:
            pass

    def _on_header_click(self, event, column: str):
        if self._edge_at(event.x_root) is None:  # a press on a line's zone is the start of a resize
            self._sort_by(column)

    def _start_drag(self, event):
        key = self._edge_at(event.x_root) if self._in_table(event.widget) else None
        if key:
            self._drag = (key, event.x_root, self._widths[key])

    def _drag_to(self, event):
        if self._drag:
            key, start, width = self._drag
            self._widths[key] = min(max(width + event.x_root - start, self._min_widths[key]), MAX_COLUMN_WIDTH)
            self._apply_widths()

    def _end_drag(self, _event):
        if self._drag:
            self._drag = None
            self._customized = True
            self._save_column_widths(self.column_widths())

    def reset_columns(self):
        self._customized = False
        self._widths = dict(self._default_widths)
        self._apply_widths()
        self._save_column_widths({})

    def _update_scroll_regions(self):
        width = self._body.winfo_reqwidth()
        self._canvas.configure(scrollregion=(0, 0, width, self._body.winfo_reqheight()))
        self._header_canvas.configure(scrollregion=(0, 0, width, self._header.winfo_reqheight()))
        self._filter_canvas.configure(scrollregion=(0, 0, width, self._filters.winfo_reqheight()))
        self._settle_views()

    def _schedule_scroll_update(self):
        """
        The sizes are known once the geometry has been worked out, and a canvas does not always report the resize of
        a window that is scrolled out of view: so the scroll regions are also brought up to date when things are idle.
        """
        if not self._settle_after_id:
            self._settle_after_id = self.after_idle(self._update_scroll_later)

    def _update_scroll_later(self):
        self._settle_after_id = None
        self.update_idletasks()  # the grids first say how large they have become
        self._update_scroll_regions()

    def _on_canvas_resized(self):
        """A taller or shorter window may fit a different number of rows; a wider or narrower one, its scrollbar."""
        self._update_scroll_regions()
        self._render_pool()

    def _fits(self, axis: str) -> bool:
        """The table has nothing to scroll in this direction: sideways, it is not wider than the window; up and
        down, every (filtered) player is already entirely on the screen, so there is no further row to scroll to."""
        if axis == "x":
            return self._body.winfo_reqwidth() <= self._canvas.winfo_width()
        return len(self._visible) <= self._whole_rows

    def _settle_views(self):
        """A Tk canvas that is larger than its content can still be scrolled, which pushes the content away from the
        corner and leaves an empty band (and the header and the filters behind); what fits stays where it belongs.
        The rows never really scroll the canvas at all any more (see _scroll_y), so they are pinned at its corner."""
        if self._fits("x"):
            for canvas in (self._canvas, self._header_canvas, self._filter_canvas):
                canvas.xview_moveto(0)
        self._canvas.yview_moveto(0)

    def _scroll_x(self, *args):
        if self._fits("x"):
            self._settle_views()
            return
        for canvas in (self._canvas, self._header_canvas, self._filter_canvas):
            canvas.xview(*args)

    def _scroll_y(self, *args):
        """
        Unlike _scroll_x, there is no real canvas view behind this: the rows on screen are a fixed pool (see the
        class docstring), so "scrolling" means asking a different slice of _visible to fill it instead of moving
        anything. A "unit" is one row, a "page" a poolful of them (a click in the scrollbar's trough).
        """
        if args[0] == "moveto":
            first = round(float(args[1]) * len(self._visible))
        elif args[0] == "scroll":
            first = self._first_index + int(args[1]) * (self._whole_rows if args[2] == "pages" else 1)
        else:
            return
        self._set_first_index(first)

    def _set_first_index(self, first: int):
        # The last position puts the last player in the last row that is entirely on the screen. The pool has slots
        # beyond those (the partly visible row and a spare one): they are empty then, never where the last player is.
        first = min(max(first, 0), max(0, len(self._visible) - self._whole_rows))
        if first != self._first_index:
            self._first_index = first
            self._render_pool()

    def _on_x_scrolled(self, first, last):
        """The scroll bar shows only while the table is wider than the window."""
        self._x_scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self._x_scrollbar.grid_remove()
        else:
            self._x_scrollbar.grid()

    def _wheel_step(self, event) -> int:
        return wheel_units(event.delta, self.tk.call("tk", "windowingsystem") == "aqua")

    def _on_mouse_wheel(self, event):
        self._scroll_y("scroll", self._wheel_step(event), "units")

    def _on_shift_mouse_wheel(self, event):
        self._scroll_x("scroll", self._wheel_step(event), "units")

    # ---- shown and hidden columns

    def hidden_columns(self) -> List[str]:
        return [key for key in TOGGLE_COLUMNS if key in self._hidden]

    @frozen_table
    def toggle_column(self, key: str):
        """Shows or hides an optional column together with its filter; hiding also clears that filter."""
        if key in self._hidden:
            self._hidden.discard(key)
        else:
            self._hidden.add(key)
            self._clear_filter(key)
            if self._sort[0] == key:  # the table is not left sorted by something that cannot be seen
                self._sort = ("name", False)
                self._show_sort_arrow()
        self._update_toggle_colors()
        self._apply_visibility()
        self._apply_widths()
        self.apply_filters()
        self._save_hidden_columns(self.hidden_columns())

    def _update_toggle_colors(self):
        for key, button in self.column_buttons.items():
            set_button_colors(button, RED if key in self._hidden else GREEN)

    def _apply_visibility(self):
        """The header of a hidden column and its line go; the cells of the rows follow in apply_filters."""
        for index, (key, _, _) in enumerate(COLUMNS):
            for widget in (self._header_cells[key], self._header_separators[index], self._filter_widgets[key]):
                widget.grid_remove() if key in self._hidden else widget.grid()
        self._schedule_scroll_update()

    def _clear_filter(self, key: str):
        if key == "note":
            self.note_var.set("")
            return
        box = {"group": self.group_box, "location": self.location_box, "label": self.label_box,
               "synced": self.synced_box, "reported": self.reported_box, "temperature": self.temperature_box,
               "version": self.version_box}[key]
        if isinstance(box, MultiSelectCombo):
            box.clear()
        else:
            box.set(next(iter(self._combo_values[box])))

    # ---- loading

    def is_for(self, url: str, login: str, password: str) -> bool:
        """Whether this window shows the players of exactly this account, login and password."""
        return self._credentials == (url, login, password)

    def refresh(self):
        """
        Fetches the players from the server again. Two downloads start at least MIN_REFRESH_INTERVAL seconds apart:
        a press that comes earlier (or while a download is running) is remembered, and the update runs as soon as the
        interval is over. Further presses before that change nothing; when the update starts the request is used up
        and the next press asks for the next one.
        """
        if self._loading or self._seconds_until_refresh() > 0:
            self._pending = True
            self._update_refresh_state()
            return
        self._start_download()

    def _start_download(self):
        """The download runs in the background, so the window stays responsive."""
        self._pending = False
        self._loading = True
        self._last_fetch_started = _clock()
        self._set_status(self.lang.get_message("pb_loading"))
        self._update_refresh_state()
        threading.Thread(target=self._load, daemon=True).start()
        self._poll_after_id = self.after(POLL_INTERVAL_MS, self._poll)
        self._schedule_auto_refresh(AUTO_REFRESH_SECONDS * 1000)

    def _schedule_auto_refresh(self, delay_ms: int):
        if self._auto_after_id:
            self.after_cancel(self._auto_after_id)
        self._auto_after_id = self.after(int(delay_ms), self._auto_refresh)

    def _auto_refresh(self):
        """
        The update of a window that has been open a long time (a player can have gone offline meanwhile). It waits
        while the user is in the middle of something the new data would disturb: a list of choices that is open,
        a column that is being resized.
        """
        self._auto_after_id = None
        if self._drag is not None or any(box.is_open for box in (self.group_box, self.location_box, self.label_box,
                                                                  self.version_box)):
            self._schedule_auto_refresh(AUTO_REFRESH_RETRY_MS)
            return
        self.refresh()

    def _seconds_until_refresh(self) -> float:
        if self._last_fetch_started is None:
            return 0
        return max(0.0, MIN_REFRESH_INTERVAL - (_clock() - self._last_fetch_started))

    def _update_refresh_state(self):
        """
        Starts the update that was asked for early as soon as it is due, and shows how fresh the data is and, while an
        update is waiting, how long until it runs.
        """
        remaining = self._seconds_until_refresh()
        if self._pending and remaining <= 0 and not self._loading:
            self._start_download()
            return
        parts = []
        if self._updated_at:
            parts.append(self.lang.get_message("pb_data_from" if self._failed else "pb_updated",
                                               time=self._updated_at.strftime("%H:%M:%S")))
        if self._pending and remaining > 0:
            parts.append(self.lang.get_message("pb_next_update", seconds=math.ceil(remaining)))
        self.updated_var.set(" · ".join(parts))
        if self._tick_after_id:
            self.after_cancel(self._tick_after_id)
            self._tick_after_id = None
        if self._pending:  # look again when it is due, at the latest after a tick (for the countdown)
            delay = COUNTDOWN_TICK_MS if remaining <= 0 else min(COUNTDOWN_TICK_MS, max(int(remaining * 1000), 1))
            self._tick_after_id = self.after(delay, self._update_refresh_state)

    def _set_status(self, text: str, failed: bool = False):
        self.status_var.set(text)
        self._status_label.configure(foreground=OFFLINE_COLOR if failed else self._default_status_color)

    def _load(self):
        try:
            self._results.put(("rows", [player_row(player) for player in self._fetch(*self._credentials)]))
        except LoginError:
            self._results.put(("error", self.lang.get_message("incorrect_login")))
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            self._results.put(("error", self.lang.get_message("connection_error")))
        except requests.exceptions.RequestException as error:
            code = error.response.status_code if error.response is not None else None
            self._results.put(("error", self.lang.get_message("fail_response", code=code) if code
                               else self.lang.get_message("connection_error")))
        except Exception:  # never show the exception itself: it can carry the request, including the token
            self._results.put(("error", self.lang.get_message("no_server_returned")))

    def _poll(self):
        try:
            kind, value = self._results.get_nowait()
        except queue.Empty:
            self._poll_after_id = self.after(POLL_INTERVAL_MS, self._poll)
            return
        self._poll_after_id = None
        self._loading = False
        self._failed = kind == "error"
        if kind == "error":
            # What was shown before stays, but it has to be plain that it is not current
            self._set_status(self.lang.get_message("pb_load_failed", reason=value), failed=True)
        else:
            self._updated_at = datetime.now()
            self._show_players(value)
        self._update_refresh_state()

    @frozen_table
    def _show_players(self, rows: List[PlayerRow]):
        self._rows = rows
        no_group = [(self.lang.get_message("pb_no_group"), "")] if any(not row.group for row in rows) else []
        self.group_box.set_options(no_group + [(group, group) for group in sorted(
            {row.group for row in rows if row.group}, key=str.casefold)])
        self.label_box.set_options([(label, label) for label in sorted(
            {label for row in rows for label in row.labels}, key=str.casefold)])
        self.version_box.set_options([(version, version) for version in sorted(
            {row.version for row in rows if row.version}, key=version_key)])
        self.location_box.set_options([(location, location) for location in sorted(
            {row.location for row in rows if row.location}, key=str.casefold)])
        self.apply_filters(keep_scroll=True)  # _first_index itself already survives: the pool is never rebuilt

    def _moment(self, moment) -> str:
        return moment.strftime("%d.%m.%Y %H:%M") if moment else self.lang.get_message("pb_never")

    # ---- the pool of row widgets (see the class docstring)

    def _ensure_pool(self):
        """As many reusable row slots as the canvas currently fits; once made, one is never taken away again."""
        if not self._pool:
            row = self._new_pool_row(0)
            self._pool.append(row)
            self._pool_rows.append(None)
            button, first_cell, *_ = row
            button.grid(row=0, column=0, padx=CELL_PADDING, pady=ROW_PADY)
            first_cell.grid(row=0, column=self._cell_column(0), sticky="ew", padx=CELL_PADDING, pady=ROW_PADY)
        row_height = self._row_height()
        canvas_height = max(self._canvas.winfo_height(), 1)
        self._whole_rows = max(1, canvas_height // row_height)
        self._pool_size = max(len(self._pool), math.ceil(canvas_height / row_height) + POOL_OVERSCAN)
        while len(self._pool) < self._pool_size:
            self._pool.append(self._new_pool_row(len(self._pool)))
            self._pool_rows.append(None)

    def _row_height(self) -> int:
        """The height of a row of the table: that of its tallest widget (the button is taller than a cell) and its
        padding. The same number decides how many rows are there and how far the list can be scrolled."""
        self.update_idletasks()
        button, *cells = self._pool[0]
        return max(button.winfo_reqheight(), *(cell.winfo_reqheight() for cell in cells)) + 2 * ROW_PADY

    def _new_pool_row(self, index: int) -> List[tk.Widget]:
        """One reusable slot in the window of rows on screen: the button first, then one cell for each column."""
        cells = [tk.Label(self._body, font=self._font, width=1, anchor="w") for _ in COLUMNS]
        button = make_color_button(self._body, self.lang.get_message("pb_snapshot"),
                                   lambda: self._click_snapshot(index), self._font, GREEN)
        Tooltip(button, lambda: self._snapshot_tip(index))
        return [button] + cells

    def _row_at(self, index: int) -> Optional[PlayerRow]:
        """The player the pool slot `index` currently shows, if any."""
        return self._pool_rows[index] if index < len(self._pool_rows) else None

    def _click_snapshot(self, index: int):
        row = self._row_at(index)
        if row is not None and row.online and row.player_id:  # an offline player cannot answer
            self.show_snapshot(row)

    def _snapshot_tip(self, index: int) -> str:
        row = self._row_at(index)
        can_ask = row is not None and row.online and bool(row.player_id)
        return self.lang.get_message("pb_tip_snapshot" if can_ask else "pb_tip_snapshot_offline")

    def _fill_slot(self, index: int, row: Optional[PlayerRow]):
        """Shows `row` in pool slot `index`, reusing the widgets already there; empties the slot when there is none."""
        button, *cells = self._pool[index]
        self._pool_rows[index] = row
        if row is None:
            button.grid_remove()
            for cell in cells:
                cell.grid_remove()
            return
        texts = (row.name, self.lang.get_message("pb_online" if row.online else "pb_offline"), row.group,
                 row.location, ", ".join(row.labels), self._moment(row.synced), self._moment(row.reported), row.note,
                 f"{row.temperature:g} °C" if row.temperature is not None else "", row.version)
        for column, (cell, text) in enumerate(zip(cells, texts)):
            if COLUMNS[column][0] in self._hidden:
                cell.grid_remove()
                continue
            cell.configure(text=text)
            cell.grid(row=index, column=self._cell_column(column), sticky="ew", padx=CELL_PADDING, pady=ROW_PADY)
        cells[1].configure(foreground=ONLINE_COLOR if row.online else OFFLINE_COLOR)  # cells[0] is the name
        can_ask = row.online and bool(row.player_id)  # an offline player cannot answer
        # Green where a snapshot can be asked for, red where it cannot: seen at a glance
        set_button_interactive(button, can_ask, GREEN if can_ask else RED)
        button.grid(row=index, column=0, padx=CELL_PADDING, pady=ROW_PADY)

    def _render_pool(self):
        """Fills the pool with the slice of _visible that starts at _first_index; empties whatever is left of it."""
        self._ensure_pool()
        total = len(self._visible)
        self._first_index = min(max(self._first_index, 0), max(0, total - self._whole_rows))
        shown = 0
        for offset in range(self._pool_size):
            index = self._first_index + offset
            row = self._visible[index] if index < total else None
            self._fill_slot(offset, row)
            shown += row is not None
        for column, line in enumerate(self._body_separators):  # the lines run down beside the rows
            if COLUMNS[column][0] in self._hidden:
                line.grid_remove()
            else:
                line.grid(row=0, column=self._cell_column(column) + 1, rowspan=max(1, shown), sticky="ns")
        self._update_scrollbar()
        self._schedule_scroll_update()

    def _update_scrollbar(self):
        total = len(self._visible)
        if total <= self._whole_rows:
            self._scrollbar.set(0.0, 1.0)
        else:
            self._scrollbar.set(self._first_index / total, min(1.0, (self._first_index + self._whole_rows) / total))

    def widgets_for(self, row: PlayerRow) -> Optional[List[tk.Widget]]:
        """The button and the cells currently showing `row`, if it is scrolled into view; None if it is not."""
        for index, current in enumerate(self._pool_rows):
            if current is row:
                return self._pool[index]
        return None

    def _remember_snapshot_size(self, size: Tuple[int, int]):
        """The next snapshot windows open in the size the user has just given one of them."""
        if valid_window_size(size) and size != self._snapshot_size:
            self._snapshot_size = size
            self._save_snapshot_size(size)

    def show_snapshot(self, row: PlayerRow):
        """Opens the window with the player's snapshot; when it is open already it is brought forward."""
        viewer = self._viewers.get(row.player_id)
        if viewer is not None and viewer.winfo_exists():
            viewer.request_snapshot()
            return
        if len(self._viewers) >= MAX_SNAPSHOT_WINDOWS:
            messagebox.showinfo(self.lang.get_message("info_title"),
                                self.lang.get_message("pb_viewer_limit", count=MAX_SNAPSHOT_WINDOWS), parent=self)
            return
        viewer = SnapshotViewer(self, player_name=row.name, player_id=row.player_id, credentials=self._credentials,
                                slots=self._snapshot_slots, font=self._font, button_style=BUTTON_STYLE,
                                fetch=self._snapshot_fetch, size=self._snapshot_size,
                                on_resized=self._remember_snapshot_size,
                                offset=CASCADE_STEP * len(self._viewers))
        self._viewers[row.player_id] = viewer
        viewer.bind("<Destroy>", lambda event: self._viewers.pop(row.player_id, None) if event.widget is viewer else None,
                    add="+")

    # ---- filtering and sorting

    def _set_choices(self, box: ttk.Combobox, choices: Dict[str, Optional[str]]):
        """Fills a drop-down; the previous choice is kept while it still exists, otherwise "(all)" is chosen."""
        previous = box.get()
        self._combo_values[box] = choices
        box.configure(values=list(choices))
        box.set(previous if previous in choices else next(iter(choices)))

    def _criteria(self) -> PlayerFilter:
        def chosen(box):
            return self._combo_values[box].get(box.get())
        criteria = dict(name=self.name_var.get(), online=chosen(self.status_box))
        if "group" not in self._hidden:
            criteria.update(group_text=self.group_box.text(), groups=self.group_box.checked())
        if "location" not in self._hidden:
            criteria.update(location_text=self.location_box.text(), locations=self.location_box.checked())
        if "label" not in self._hidden:
            criteria.update(label_text=self.label_box.text(), labels=self.label_box.checked())
        if "synced" not in self._hidden:
            criteria.update(synced=chosen(self.synced_box))
        if "reported" not in self._hidden:
            criteria.update(reported=chosen(self.reported_box))
        if "note" not in self._hidden:
            criteria.update(note=self.note_var.get())
        if "temperature" not in self._hidden:
            criteria.update(temperature=chosen(self.temperature_box))
        if "version" not in self._hidden:
            criteria.update(version_text=self.version_box.text(), versions=self.version_box.checked())
        return PlayerFilter(**criteria)

    def _schedule_filter(self):
        if self._filter_after_id:
            self.after_cancel(self._filter_after_id)
        self._filter_after_id = self.after(NAME_FILTER_DELAY_MS, self.apply_filters)

    def _clear_filters(self):
        """Clears the texts and the ticks and puts every drop-down back on "(all)"; does not show the result."""
        self.name_var.set("")
        self.note_var.set("")
        for box in (self.status_box, self.synced_box, self.reported_box, self.temperature_box):
            box.set(next(iter(self._combo_values[box])))
        for box in (self.group_box, self.location_box, self.label_box, self.version_box):
            box.clear()

    def reset_filters(self):
        """Clears the texts and the ticks and puts every drop-down back on "(all)"."""
        self._clear_filters()
        self.apply_filters()
        self.name_entry.focus_set()

    def set_filter_and_sort(self, *, name: str = "", online: Optional[bool] = None, sort_column: str = "name",
                            sort_descending: bool = False):
        """
        Shows exactly this view, as if chosen by hand: every other filter is cleared (one left over from before
        could hide the very players looked for), the column it is sorted by is shown (a table sorted by a column
        that cannot be seen would give no arrow to say so) and the filters and the order are applied.
        """
        if sort_column in self._hidden:
            self.toggle_column(sort_column)
        self._clear_filters()
        self.name_var.set(name)
        for label, value in self._combo_values[self.status_box].items():
            if value == online:
                self.status_box.set(label)
                break
        self._sort = (sort_column, sort_descending)
        self._show_sort_arrow()
        self.apply_filters()

    def _sort_by(self, column: str):
        self._sort = (column, not self._sort[1] if self._sort[0] == column else False)
        self._show_sort_arrow()
        self.apply_filters()

    def _show_sort_arrow(self):
        for key, message, _ in COLUMNS:
            arrow = (" ▼" if self._sort[1] else " ▲") if key == self._sort[0] else ""
            self._header_cells[key].configure(text=self.lang.get_message(message) + arrow)

    @frozen_table
    def apply_filters(self, keep_scroll: bool = False):
        """Shows the players that match all the filters, in the chosen order (from the top, unless `keep_scroll`)."""
        if self._filter_after_id:
            self.after_cancel(self._filter_after_id)
            self._filter_after_id = None
        self._visible = sort_rows(apply_filter(self._rows, self._criteria()), *self._sort)
        if not keep_scroll:
            self._first_index = 0
        self._render_pool()
        if not self._rows:
            self._set_status(self.lang.get_message("pb_no_players"), self._failed)
        elif not self._visible:
            self._set_status(self.lang.get_message("pb_empty"), self._failed)
        else:
            self._set_status(self.lang.get_message("pb_count", shown=len(self._visible), total=len(self._rows)),
                             self._failed)

    def visible_names(self) -> List[str]:
        return [row.name for row in self._visible]

    def destroy(self):
        if self._geometry_after_id:  # moved or resized and closed at once: the place is still remembered
            self.after_cancel(self._geometry_after_id)
            self._report_geometry()
        for after_id in (self._filter_after_id, self._poll_after_id, self._tick_after_id, self._auto_after_id,
                         self._settle_after_id):
            if after_id:
                self.after_cancel(after_id)
        super().destroy()
