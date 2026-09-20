import queue
import threading
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from typing import Callable, Dict, List, Optional

import requests

from api_testing.request_calls import LoginError, ServerApi
from gui_app.icons import set_window_icon
from gui_app.tooltip import Tooltip
from util.player_filter import PlayerFilter, PlayerRow, apply_filter, player_row, sort_rows

# key, header message, default width in characters
COLUMNS = (
    ("name", "pb_col_name", 30),
    ("status", "pb_col_status", 9),
    ("group", "pb_col_group", 20),
    ("location", "pb_col_location", 22),
    ("synced", "pb_col_synced", 17),
)
MIN_COLUMN_WIDTH = 40  # pixels
MAX_COLUMN_WIDTH = 1500
SEPARATOR_WIDTH = 7  # the grab area of the line between two columns; the line itself is 1 px
SEPARATOR_COLOR = "black"
SNAPSHOT_COLUMN_MINSIZE = 110
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


class PlayerBrowser(tk.Toplevel):
    """
    The players of one account in a table that can be filtered by name, state, group, location and category.
    The data is fetched once (and again on "Refresh"); the filters work on it locally. The columns can be resized by
    dragging the black lines between them; `save_column_widths` is called with the widths when the user lets go
    (and with {} when they go back to the defaults).
    """

    def __init__(self, master, *, url: str, login: str, password: str, account_name: str,
                 fetch: Callable[[str, str, str], List[Dict]] = fetch_players_from_server,
                 column_widths: Optional[Dict[str, int]] = None,
                 save_column_widths: Callable[[Dict[str, int]], None] = lambda widths: None):
        super().__init__(master)
        self.lang = master.lang
        self.connection = (url, login)
        self._credentials = (url, login, password)
        self._fetch = fetch
        self._save_column_widths = save_column_widths
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

    def _button(self, bar, message: str, tip: str, command) -> ttk.Button:
        button = ttk.Button(bar, text=self.lang.get_message(message), command=command)
        button.pack(side="left", padx=(0, 6))
        Tooltip(button, lambda: self.lang.get_message(tip))
        return button

    def _build_filters(self):
        """The filters stand in the order of the columns they belong to; the category has no column, so it is last."""
        bar = self._filter_bar = tk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", padx=10, pady=8)
        self.name_var = tk.StringVar()
        self.name_var.trace_add("write", lambda *_: self._schedule_filter())
        self._label(bar, "pb_name", 0)
        self.name_entry = tk.Entry(bar, textvariable=self.name_var, width=20, font=self._font)
        self.name_entry.grid(row=0, column=1, padx=(0, 12))
        self.name_entry.focus_set()
        self.status_box = self._combobox(bar, "pb_status", 2, width=9)
        self.group_box = self._combobox(bar, "pb_group", 4)
        self.location_box = self._combobox(bar, "pb_location", 6)
        self.label_box = self._combobox(bar, "pb_label", 8)
        self._set_choices(self.status_box, {self.lang.get_message("pb_all"): None,
                                            self.lang.get_message("pb_online"): True,
                                            self.lang.get_message("pb_offline"): False})

    def _label(self, bar, message: str, column: int):
        tk.Label(bar, text=self.lang.get_message(message), font=self._font).grid(row=0, column=column, padx=(0, 4))

    def _combobox(self, bar, message: str, column: int, width: int = 16) -> ttk.Combobox:
        self._label(bar, message, column)
        box = ttk.Combobox(bar, state="readonly", width=width, font=self._font)
        box.grid(row=0, column=column + 1, padx=(0, 12))
        box.bind("<<ComboboxSelected>>", lambda _: self.apply_filters())
        return box

    def _build_table(self):
        frame = tk.Frame(self)
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
            cell = tk.Label(self._header, font=bold, width=1, anchor="w", cursor="hand2")
            cell.grid(row=0, column=2 * index, sticky="ew", padx=CELL_PADDING)
            cell.bind("<Button-1>", lambda _, column=key: self._sort_by(column))
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
        self.bind("<MouseWheel>", self._on_mouse_wheel)
        self.bind("<Shift-MouseWheel>", self._on_shift_mouse_wheel)

    def _header_separator(self, index: int, key: str) -> tk.Canvas:
        middle = SEPARATOR_WIDTH // 2
        separator = tk.Canvas(self._header, width=SEPARATOR_WIDTH, height=1, highlightthickness=0, borderwidth=0,
                              cursor="sb_h_double_arrow")
        line = separator.create_line(middle, 0, middle, 1, fill=SEPARATOR_COLOR)
        separator.bind("<Configure>", lambda event: separator.coords(line, middle, 0, middle, event.height))
        separator.bind("<ButtonPress-1>", lambda event: self._start_drag(key, event))
        separator.bind("<B1-Motion>", self._drag_to)
        separator.bind("<ButtonRelease-1>", self._end_drag)
        separator.grid(row=0, column=2 * index + 1, sticky="ns")
        return separator

    def _fit_window(self):
        """Opens wide enough for the filters and, as far as the screen allows, for the whole table."""
        self.update_idletasks()
        self._header_canvas.configure(height=self._header.winfo_reqheight())
        filters = max(self._filter_bar.winfo_reqwidth(), self._actions_bar.winfo_reqwidth()) + 30
        table = self._header.winfo_reqwidth() + self._scrollbar.winfo_reqwidth() + 30
        self.minsize(filters, 300)
        self.geometry(f"{min(max(filters, table), self.winfo_screenwidth() - 80)}x600")

    # ---- column widths

    def column_widths(self) -> Dict[str, int]:
        return dict(self._widths)

    def _apply_widths(self):
        """Every column is exactly as wide as set; the text that does not fit is cut off."""
        for frame in (self._header, self._body):
            for index, (key, _, _) in enumerate(COLUMNS):
                frame.grid_columnconfigure(2 * index, minsize=self._widths[key])
                frame.grid_columnconfigure(2 * index + 1, minsize=SEPARATOR_WIDTH)
            frame.grid_columnconfigure(2 * len(COLUMNS), minsize=SNAPSHOT_COLUMN_MINSIZE)

    def _start_drag(self, key: str, event):
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
        all_text = self.lang.get_message("pb_all")
        self._set_choices(self.group_box, {all_text: None} | (
            {self.lang.get_message("pb_no_group"): ""} if any(not row.group for row in rows) else {}) | {
            group: group for group in sorted({row.group for row in rows if row.group}, key=str.casefold)})
        self._set_choices(self.label_box, {all_text: None} | {
            label: label for label in sorted({label for row in rows for label in row.labels}, key=str.casefold)})
        self._set_choices(self.location_box, {all_text: None} | {
            location: location for location in sorted({row.location for row in rows if row.location},
                                                      key=str.casefold)})
        self.apply_filters()

    def _row_widgets(self, row: PlayerRow) -> List[tk.Widget]:
        synced = row.synced.strftime("%d.%m.%Y %H:%M") if row.synced else self.lang.get_message("pb_never")
        texts = (row.name, self.lang.get_message("pb_online" if row.online else "pb_offline"), row.group,
                 row.location, synced)
        widgets: List[tk.Widget] = [tk.Label(self._body, text=text, font=self._font, width=1, anchor="w")
                                    for text in texts]
        widgets[1].configure(foreground=ONLINE_COLOR if row.online else OFFLINE_COLOR)
        button = ttk.Button(self._body, text=self.lang.get_message("pb_snapshot"))
        button.state(["disabled"])  # its function is defined later
        return widgets + [button]

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
        return PlayerFilter(name=self.name_var.get(), group=chosen(self.group_box), label=chosen(self.label_box),
                            location=chosen(self.location_box), online=chosen(self.status_box))

    def _schedule_filter(self):
        if self._filter_after_id:
            self.after_cancel(self._filter_after_id)
        self._filter_after_id = self.after(NAME_FILTER_DELAY_MS, self.apply_filters)

    def reset_filters(self):
        """Clears the name and puts every drop-down back on "(all)"."""
        self.name_var.set("")
        for box in (self.status_box, self.group_box, self.location_box, self.label_box):
            box.set(next(iter(self._combo_values[box])))
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
            for column, widget in enumerate(self._widgets[id(row)]):
                widget.grid(row=index, column=2 * column, sticky="ew" if column < len(COLUMNS) else "",
                            padx=CELL_PADDING, pady=1)
        for column, line in enumerate(self._body_separators):  # the lines run down beside the rows
            line.grid(row=0, column=2 * column + 1, rowspan=max(1, len(visible)), sticky="ns")
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
