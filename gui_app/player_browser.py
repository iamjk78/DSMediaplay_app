import queue
import threading
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional

import requests

from api_testing.request_calls import LoginError, ServerApi
from gui_app.color_button import GREEN, RED, make_color_button, set_button_colors
from gui_app.icons import set_window_icon
from gui_app.multi_select import MultiSelectCombo
from gui_app.tooltip import Tooltip
from util.player_filter import AGE_OPTIONS, PlayerFilter, PlayerRow, apply_filter, player_row, sort_rows

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
)
TOGGLE_COLUMNS = ("group", "location", "label", "synced", "reported", "note")  # the others are always shown
MIN_COLUMN_WIDTH = 40  # pixels
MAX_COLUMN_WIDTH = 1500
SEPARATOR_WIDTH = 7  # the space between two columns; the line itself is 1 px wide
EDGE_ZONE = 10  # pixels to each side of a line where the pointer changes and the column can be resized
RESIZE_CURSOR = "sb_h_double_arrow"
SORT_CURSOR = "hand2"
SEPARATOR_COLOR = "black"
SNAPSHOT_COLUMN_MINSIZE = 110  # the first column, with the button; its width is fixed
FILTER_GAP = 10
ONLINE_COLOR = "#2e7d32"
OFFLINE_COLOR = "#c62828"
NAME_FILTER_DELAY_MS = 150
POLL_INTERVAL_MS = 100
CELL_PADDING = 4


def fetch_players_from_server(url: str, login: str, password: str) -> List[Dict]:
    with ServerApi(url=f"{url}/api", login=login, password=password) as server:
        return server.get_player_objects()


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


class PlayerBrowser(tk.Toplevel):
    """
    The players of one account in a table that can be filtered by every column but the button.
    The data is fetched once (and again on "Refresh"); the filters work on it locally. The columns can be resized by
    dragging the black lines between them (anywhere along a line, EDGE_ZONE pixels to each side of it);
    `save_column_widths` is called with the widths when the user lets go
    (and with {} when they go back to the defaults).
    """

    def __init__(self, master, *, url: str, login: str, password: str, account_name: str,
                 fetch: Callable[[str, str, str], List[Dict]] = fetch_players_from_server,
                 column_widths: Optional[Dict[str, int]] = None,
                 save_column_widths: Callable[[Dict[str, int]], None] = lambda widths: None,
                 hidden_columns: Optional[Iterable[str]] = None,
                 save_hidden_columns: Callable[[List[str]], None] = lambda hidden: None):
        super().__init__(master)
        self.lang = master.lang
        self.connection = (url, login)
        self._credentials = (url, login, password)
        self._fetch = fetch
        self._save_column_widths = save_column_widths
        self._hidden = set(valid_hidden(hidden_columns))
        self._save_hidden_columns = save_hidden_columns
        self._font = master.font
        self._rows: List[PlayerRow] = []
        self._visible: List[PlayerRow] = []
        self._widgets: Dict[int, List[tk.Widget]] = {}
        self._sort = ("name", False)
        self._results: "queue.Queue" = queue.Queue()
        self._loading = False
        self._drag = None
        self._filter_after_id: Optional[str] = None
        self._poll_after_id: Optional[str] = None
        self._combo_values: Dict[ttk.Combobox, Dict[str, Optional[str]]] = {}
        zero = tkfont.Font(root=self, font=self._font).measure("0")
        self._default_widths = {key: chars * zero + 2 * CELL_PADDING for key, _, chars in COLUMNS}
        self._widths = {**self._default_widths, **valid_widths(column_widths)}

        self.title(self.lang.get_message("pb_title", account=account_name))
        set_window_icon(self)
        self._build_actions()
        self._build_filters()
        self._build_table()
        self.status_var = tk.StringVar()
        tk.Label(self, textvariable=self.status_var, font=self._font, anchor="w").grid(
            row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._fit_window()
        self.refresh()

    # ---- construction

    def _build_actions(self):
        bar = self._actions_bar = tk.Frame(self)
        bar.grid(row=0, column=0, sticky="w", padx=10, pady=(8, 0))
        self.refresh_button = self._button(bar, "pb_refresh", "pb_tip_refresh", self.refresh)
        self.reset_button = self._button(bar, "pb_reset", "pb_tip_reset", self.reset_filters)
        self.default_columns_button = self._button(bar, "pb_default_columns", "pb_tip_default_columns",
                                                   self.reset_columns)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=(8, 12))
        tk.Label(bar, text=self.lang.get_message("pb_columns"), font=self._font).pack(side="left", padx=(0, 8))
        header = {key: message for key, message, _ in COLUMNS}
        self.column_buttons: Dict[str, tk.Widget] = {}
        for key in TOGGLE_COLUMNS:  # each as wide as its text; green = shown, red = hidden
            button = make_color_button(bar, self.lang.get_message(header[key]), lambda column=key: self.toggle_column(column),
                                       self._font, GREEN)
            button.pack(side="left", padx=(0, 6))
            self.column_buttons[key] = button
        self._update_toggle_colors()

    def _button(self, bar, message: str, tip: str, command) -> ttk.Button:
        button = ttk.Button(bar, text=self.lang.get_message(message), command=command)
        button.pack(side="left", padx=(0, 6))
        Tooltip(button, lambda: self.lang.get_message(tip))
        return button

    def _build_filters(self):
        """One filter per column, in the order of the columns; they stand in one row if the screen is wide enough."""
        bar = self._filter_bar = tk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", padx=10, pady=8)
        self._filter_groups: List[tk.Frame] = []
        self.name_var = tk.StringVar()
        self.name_var.trace_add("write", lambda *_: self._schedule_filter())
        self._filter_column: Dict[tk.Frame, str] = {}  # the optional columns' filters go with their column
        self.name_entry = self._filter("pb_name", lambda parent: tk.Entry(
            parent, textvariable=self.name_var, width=12, font=self._font))
        self.name_entry.focus_set()
        self.status_box = self._filter("pb_status", lambda parent: self._combobox(parent, 8))
        self.group_box = self._filter("pb_group", self._multi_select, "group")
        self.location_box = self._filter("pb_location", self._multi_select, "location")
        self.label_box = self._filter("pb_label", self._multi_select, "label")
        self.synced_box = self._filter("pb_synced", lambda parent: self._combobox(parent, 10), "synced")
        self.reported_box = self._filter("pb_reported", lambda parent: self._combobox(parent, 10), "reported")
        self.note_var = tk.StringVar()
        self.note_var.trace_add("write", lambda *_: self._schedule_filter())
        self.note_entry = self._filter("pb_note", lambda parent: tk.Entry(
            parent, textvariable=self.note_var, width=10, font=self._font), "note")
        all_text = self.lang.get_message("pb_all")
        self._set_choices(self.status_box, {all_text: None, self.lang.get_message("pb_online"): True,
                                            self.lang.get_message("pb_offline"): False})
        ages = {all_text: None} | {self.lang.get_message(f"pb_age_{key}"): criterion for key, criterion in AGE_OPTIONS}
        self._set_choices(self.synced_box, ages)
        self._set_choices(self.reported_box, ages)

    def _filter(self, message: str, make_widget, column: Optional[str] = None) -> tk.Widget:
        group = tk.Frame(self._filter_bar)
        if column:
            self._filter_column[group] = column
        tk.Label(group, text=self.lang.get_message(message), font=self._font).pack(side="left", padx=(0, 4))
        widget = make_widget(group)
        widget.pack(side="left")
        self._filter_groups.append(group)
        return widget

    def _combobox(self, parent, width: int) -> ttk.Combobox:
        box = ttk.Combobox(parent, state="readonly", width=width, font=self._font)
        box.bind("<<ComboboxSelected>>", lambda _: self.apply_filters())
        return box

    def _multi_select(self, parent) -> MultiSelectCombo:
        return MultiSelectCombo(parent, self, font=self._font, width=9, on_change=self._schedule_filter)

    def _flow_filters(self):
        """All the filters in one row; on a screen too narrow for that, the rest goes to the next row."""
        self.update_idletasks()
        limit = self.winfo_screenwidth() - 40
        row = column = used = 0
        for group in self._filter_groups:
            if self._filter_column.get(group) in self._hidden:  # the filter of a hidden column is hidden too
                group.grid_remove()
                continue
            width = group.winfo_reqwidth() + FILTER_GAP
            if column and used + width > limit:
                row, column, used = row + 1, 0, 0
            group.grid(row=row, column=column, sticky="w", padx=(0, FILTER_GAP), pady=2)
            used += width
            column += 1

    def _build_table(self):
        frame = self._table = tk.Frame(self)
        frame.grid(row=2, column=0, sticky="nsew", padx=10)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        bold = (self._font[0], self._font[1], "bold")

        # The header and the rows are two grids with the same column widths; both scroll sideways together
        self._header_canvas = tk.Canvas(frame, height=1, width=1, highlightthickness=0, borderwidth=0)
        self._header_canvas.grid(row=0, column=0, sticky="ew")
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
        self._scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self._canvas.yview)
        self._x_scrollbar = ttk.Scrollbar(frame, orient="horizontal", command=self._scroll_x)
        self._canvas.configure(yscrollcommand=self._scrollbar.set, xscrollcommand=self._on_x_scrolled)
        self._canvas.grid(row=1, column=0, sticky="nsew")
        self._scrollbar.grid(row=1, column=1, sticky="ns")
        self._x_scrollbar.grid(row=2, column=0, sticky="ew")
        self._body = tk.Frame(self._canvas)
        self._body_separators = [tk.Frame(self._body, width=1, background=SEPARATOR_COLOR) for _ in COLUMNS]
        self._canvas.create_window((0, 0), window=self._body, anchor="nw")
        for widget in (self._body, self._header):
            widget.bind("<Configure>", lambda _: self._update_scroll_regions())
        self._apply_widths()
        self._apply_visibility()
        self.bind("<MouseWheel>", self._on_mouse_wheel)
        self.bind("<Shift-MouseWheel>", self._on_shift_mouse_wheel)
        # On the window, not on the lines: the events of every widget of the table arrive here, so the whole
        # length of a line (header and rows) can be grabbed, and the zone reaches over the text beside it
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
        """Opens wide enough for the filters and, as far as the screen allows, for the whole table."""
        self._flow_filters()
        self.update_idletasks()
        self._header_canvas.configure(height=self._header.winfo_reqheight())
        filters = max(self._filter_bar.winfo_reqwidth(), self._actions_bar.winfo_reqwidth()) + 30
        table = self._header.winfo_reqwidth() + self._scrollbar.winfo_reqwidth() + 30
        self.minsize(filters, 300)
        self.geometry(f"{min(max(filters, table), self.winfo_screenwidth() - 20)}x600")

    # ---- column widths

    def column_widths(self) -> Dict[str, int]:
        return dict(self._widths)

    def _apply_widths(self):
        """Every column is exactly as wide as set; the text that does not fit is cut off."""
        for frame in (self._header, self._body):
            frame.grid_columnconfigure(0, minsize=SNAPSHOT_COLUMN_MINSIZE)
            for index, (key, _, _) in enumerate(COLUMNS):
                hidden = key in self._hidden
                frame.grid_columnconfigure(self._cell_column(index), minsize=0 if hidden else self._widths[key])
                frame.grid_columnconfigure(self._cell_column(index) + 1, minsize=0 if hidden else SEPARATOR_WIDTH)

    def _edge_at(self, x_root: int) -> Optional[str]:
        """The column whose right-hand line is within EDGE_ZONE pixels of the pointer, if any."""
        for (key, _, _), separator in zip(COLUMNS, self._header_separators):
            if key in self._hidden:
                continue
            if abs(x_root - (separator.winfo_rootx() + SEPARATOR_WIDTH // 2)) <= EDGE_ZONE:
                return key
        return None

    def _in_table(self, widget) -> bool:
        return str(widget) == str(self._table) or str(widget).startswith(str(self._table) + ".")

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
            self._widths[key] = min(max(width + event.x_root - start, MIN_COLUMN_WIDTH), MAX_COLUMN_WIDTH)
            self._apply_widths()

    def _end_drag(self, _event):
        if self._drag:
            self._drag = None
            self._save_column_widths(self.column_widths())

    def reset_columns(self):
        self._widths = dict(self._default_widths)
        self._apply_widths()
        self._save_column_widths({})

    def _update_scroll_regions(self):
        width = self._body.winfo_reqwidth()
        self._canvas.configure(scrollregion=(0, 0, width, self._body.winfo_reqheight()))
        self._header_canvas.configure(scrollregion=(0, 0, width, self._header.winfo_reqheight()))

    def _scroll_x(self, *args):
        self._canvas.xview(*args)
        self._header_canvas.xview(*args)

    def _on_x_scrolled(self, first, last):
        """The scroll bar shows only while the table is wider than the window."""
        self._x_scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self._x_scrollbar.grid_remove()
        else:
            self._x_scrollbar.grid()

    def _wheel_step(self, event) -> int:
        return -event.delta if self.tk.call("tk", "windowingsystem") == "aqua" else -event.delta // 120

    def _on_mouse_wheel(self, event):
        self._canvas.yview_scroll(self._wheel_step(event), "units")

    def _on_shift_mouse_wheel(self, event):
        self._scroll_x("scroll", self._wheel_step(event), "units")

    # ---- shown and hidden columns

    def hidden_columns(self) -> List[str]:
        return [key for key in TOGGLE_COLUMNS if key in self._hidden]

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
        self._flow_filters()
        self.apply_filters()
        self._save_hidden_columns(self.hidden_columns())

    def _update_toggle_colors(self):
        for key, button in self.column_buttons.items():
            set_button_colors(button, RED if key in self._hidden else GREEN)

    def _apply_visibility(self):
        """The header of a hidden column and its line go; the cells of the rows follow in apply_filters."""
        for index, (key, _, _) in enumerate(COLUMNS):
            for widget in (self._header_cells[key], self._header_separators[index]):
                widget.grid_remove() if key in self._hidden else widget.grid()

    def _clear_filter(self, key: str):
        if key == "note":
            self.note_var.set("")
            return
        box = {"group": self.group_box, "location": self.location_box, "label": self.label_box,
               "synced": self.synced_box, "reported": self.reported_box}[key]
        if isinstance(box, MultiSelectCombo):
            box.clear()
        else:
            box.set(next(iter(self._combo_values[box])))

    # ---- loading

    def refresh(self):
        """Fetches the players again in the background, so the window stays responsive."""
        if self._loading:
            return
        self._loading = True
        self.refresh_button.state(["disabled"])
        self.status_var.set(self.lang.get_message("pb_loading"))
        threading.Thread(target=self._load, daemon=True).start()
        self._poll_after_id = self.after(POLL_INTERVAL_MS, self._poll)

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
        self.refresh_button.state(["!disabled"])
        if kind == "error":
            self.status_var.set(self.lang.get_message("pb_load_failed", reason=value))
            return
        self._show_players(value)

    def _show_players(self, rows: List[PlayerRow]):
        for widgets in self._widgets.values():
            for widget in widgets:
                widget.destroy()
        self._rows, self._widgets = rows, {}
        for row in rows:
            self._widgets[id(row)] = self._row_widgets(row)
        no_group = [(self.lang.get_message("pb_no_group"), "")] if any(not row.group for row in rows) else []
        self.group_box.set_options(no_group + [(group, group) for group in sorted(
            {row.group for row in rows if row.group}, key=str.casefold)])
        self.label_box.set_options([(label, label) for label in sorted(
            {label for row in rows for label in row.labels}, key=str.casefold)])
        self.location_box.set_options([(location, location) for location in sorted(
            {row.location for row in rows if row.location}, key=str.casefold)])
        self.apply_filters()

    def _moment(self, moment) -> str:
        return moment.strftime("%d.%m.%Y %H:%M") if moment else self.lang.get_message("pb_never")

    def _row_widgets(self, row: PlayerRow) -> List[tk.Widget]:
        """The button first, then one cell for each column."""
        texts = (row.name, self.lang.get_message("pb_online" if row.online else "pb_offline"), row.group,
                 row.location, ", ".join(row.labels), self._moment(row.synced), self._moment(row.reported), row.note)
        cells: List[tk.Widget] = [tk.Label(self._body, text=text, font=self._font, width=1, anchor="w")
                                  for text in texts]
        cells[1].configure(foreground=ONLINE_COLOR if row.online else OFFLINE_COLOR)
        button = ttk.Button(self._body, text=self.lang.get_message("pb_snapshot"))
        button.state(["disabled"])  # its function is defined later
        return [button] + cells

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
        return PlayerFilter(**criteria)

    def _schedule_filter(self):
        if self._filter_after_id:
            self.after_cancel(self._filter_after_id)
        self._filter_after_id = self.after(NAME_FILTER_DELAY_MS, self.apply_filters)

    def reset_filters(self):
        """Clears the texts and the ticks and puts every drop-down back on "(all)"."""
        self.name_var.set("")
        self.note_var.set("")
        for box in (self.status_box, self.synced_box, self.reported_box):
            box.set(next(iter(self._combo_values[box])))
        for box in (self.group_box, self.location_box, self.label_box):
            box.clear()
        self.apply_filters()
        self.name_entry.focus_set()

    def _sort_by(self, column: str):
        self._sort = (column, not self._sort[1] if self._sort[0] == column else False)
        self._show_sort_arrow()
        self.apply_filters()

    def _show_sort_arrow(self):
        for key, message, _ in COLUMNS:
            arrow = (" ▼" if self._sort[1] else " ▲") if key == self._sort[0] else ""
            self._header_cells[key].configure(text=self.lang.get_message(message) + arrow)

    def apply_filters(self):
        """Shows the players that match all the filters, in the chosen order."""
        if self._filter_after_id:
            self.after_cancel(self._filter_after_id)
            self._filter_after_id = None
        visible = sort_rows(apply_filter(self._rows, self._criteria()), *self._sort)
        shown = {id(row) for row in visible}
        for row in self._rows:
            if id(row) not in shown:
                for widget in self._widgets[id(row)]:
                    widget.grid_remove()
        for index, row in enumerate(visible):
            button, *cells = self._widgets[id(row)]
            button.grid(row=index, column=0, padx=CELL_PADDING, pady=1)
            for column, cell in enumerate(cells):
                if COLUMNS[column][0] in self._hidden:
                    cell.grid_remove()
                else:
                    cell.grid(row=index, column=self._cell_column(column), sticky="ew", padx=CELL_PADDING, pady=1)
        for column, line in enumerate(self._body_separators):  # the lines run down beside the rows
            if COLUMNS[column][0] in self._hidden:
                line.grid_remove()
            else:
                line.grid(row=0, column=self._cell_column(column) + 1, rowspan=max(1, len(visible)), sticky="ns")
        self._canvas.yview_moveto(0)
        self._visible = visible
        if not self._rows:
            self.status_var.set(self.lang.get_message("pb_no_players"))
        elif not visible:
            self.status_var.set(self.lang.get_message("pb_empty"))
        else:
            self.status_var.set(self.lang.get_message("pb_count", shown=len(visible), total=len(self._rows)))

    def visible_names(self) -> List[str]:
        return [row.name for row in self._visible]

    def destroy(self):
        for after_id in (self._filter_after_id, self._poll_after_id):
            if after_id:
                self.after_cancel(after_id)
        super().destroy()
