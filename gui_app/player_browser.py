import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional

import requests

from api_testing.request_calls import LoginError, ServerApi
from gui_app.icons import set_window_icon
from util.player_filter import PlayerFilter, PlayerRow, apply_filter, player_row, sort_rows

# key, header message, width in characters (the same for the header cell and the row cells, so they line up)
COLUMNS = (
    ("name", "pb_col_name", 30),
    ("status", "pb_col_status", 9),
    ("group", "pb_col_group", 20),
    ("location", "pb_col_location", 22),
    ("synced", "pb_col_synced", 17),
)
SNAPSHOT_COLUMN_MINSIZE = 110  # pixels; the button is not a text cell
ONLINE_COLOR = "#2e7d32"
OFFLINE_COLOR = "#c62828"
NAME_FILTER_DELAY_MS = 150
POLL_INTERVAL_MS = 100
CELL_PADDING = 4


def fetch_players_from_server(url: str, login: str, password: str) -> List[Dict]:
    with ServerApi(url=f"{url}/api", login=login, password=password) as server:
        return server.get_player_objects()


class PlayerBrowser(tk.Toplevel):
    """
    The players of one account in a table that can be filtered by name, group, category, location and
    online/offline state. The data is fetched once (and again on "Refresh"); the filters work on it locally.
    """

    def __init__(self, master, *, url: str, login: str, password: str, account_name: str,
                 fetch: Callable[[str, str, str], List[Dict]] = fetch_players_from_server):
        super().__init__(master)
        self.lang = master.lang
        self.connection = (url, login)
        self._credentials = (url, login, password)
        self._fetch = fetch
        self._font = master.font
        self._rows: List[PlayerRow] = []
        self._visible: List[PlayerRow] = []
        self._widgets: Dict[int, List[tk.Widget]] = {}
        self._sort = ("name", False)
        self._results: "queue.Queue" = queue.Queue()
        self._loading = False
        self._filter_after_id: Optional[str] = None
        self._poll_after_id: Optional[str] = None
        self._combo_values: Dict[ttk.Combobox, Dict[str, Optional[str]]] = {}

        self.title(self.lang.get_message("pb_title", account=account_name))
        set_window_icon(self)
        self._build_filters()
        self._build_table()
        self.status_var = tk.StringVar()
        tk.Label(self, textvariable=self.status_var, font=self._font, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.update_idletasks()
        self._canvas.configure(width=self._header.winfo_reqwidth())  # the rows have exactly the header's width
        self.update_idletasks()
        width = max(self._header.winfo_reqwidth() + self._scrollbar.winfo_reqwidth(), self._bar.winfo_reqwidth()) + 30
        self.geometry(f"{width}x600")
        self.minsize(width, 300)  # narrower would cut off the filters or the table
        self.refresh()

    # ---- construction

    def _build_filters(self):
        bar = self._bar = tk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=10, pady=8)
        self.name_var = tk.StringVar()
        self.name_var.trace_add("write", lambda *_: self._schedule_filter())
        self._label(bar, "pb_name", 0)
        entry = tk.Entry(bar, textvariable=self.name_var, width=20, font=self._font)
        entry.grid(row=0, column=1, padx=(0, 12))
        entry.focus_set()
        self.group_box = self._combobox(bar, "pb_group", 2)
        self.label_box = self._combobox(bar, "pb_label", 4)
        self.location_box = self._combobox(bar, "pb_location", 6)
        self.status_box = self._combobox(bar, "pb_status", 8, width=9)
        self._set_choices(self.status_box, {self.lang.get_message("pb_all"): None,
                                            self.lang.get_message("pb_online"): True,
                                            self.lang.get_message("pb_offline"): False})
        self.refresh_button = ttk.Button(bar, text=self.lang.get_message("pb_refresh"), command=self.refresh)
        self.refresh_button.grid(row=0, column=10, padx=(4, 0))

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
        frame.grid(row=1, column=0, sticky="nsew", padx=10)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self._header = tk.Frame(frame)
        self._header.grid(row=0, column=0, sticky="w")
        self._header_cells: Dict[str, tk.Label] = {}
        for index, (key, message, width) in enumerate(COLUMNS):
            cell = tk.Label(self._header, font=(self._font[0], self._font[1], "bold"), width=width, anchor="w",
                            cursor="hand2")
            cell.grid(row=0, column=index, padx=CELL_PADDING)
            cell.bind("<Button-1>", lambda _, column=key: self._sort_by(column))
            self._header_cells[key] = cell
        self._header.grid_columnconfigure(len(COLUMNS), minsize=SNAPSHOT_COLUMN_MINSIZE)
        self._show_sort_arrow()

        self._canvas = tk.Canvas(frame, highlightthickness=0, borderwidth=0)
        self._scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.grid(row=1, column=0, sticky="nsew")
        self._scrollbar.grid(row=1, column=1, sticky="ns")
        self._body = tk.Frame(self._canvas)
        self._body.grid_columnconfigure(len(COLUMNS), minsize=SNAPSHOT_COLUMN_MINSIZE)
        self._canvas.create_window((0, 0), window=self._body, anchor="nw")
        self._body.bind("<Configure>", lambda _: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self.bind("<MouseWheel>", self._on_mouse_wheel)

    def _on_mouse_wheel(self, event):
        step = -event.delta if self.tk.call("tk", "windowingsystem") == "aqua" else -event.delta // 120
        self._canvas.yview_scroll(step, "units")

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
        self._set_choices(self.group_box, {self.lang.get_message("pb_all"): None} | (
            {self.lang.get_message("pb_no_group"): ""} if any(not row.group for row in rows) else {}) | {
            group: group for group in sorted({row.group for row in rows if row.group}, key=str.casefold)})
        self._set_choices(self.label_box, {self.lang.get_message("pb_all"): None} | {
            label: label for label in sorted({label for row in rows for label in row.labels}, key=str.casefold)})
        self._set_choices(self.location_box, {self.lang.get_message("pb_all"): None} | {
            location: location for location in sorted({row.location for row in rows if row.location},
                                                      key=str.casefold)})
        self.apply_filters()

    def _row_widgets(self, row: PlayerRow) -> List[tk.Widget]:
        synced = row.synced.strftime("%d.%m.%Y %H:%M") if row.synced else self.lang.get_message("pb_never")
        texts = (row.name, self.lang.get_message("pb_online" if row.online else "pb_offline"), row.group,
                 row.location, synced)
        widgets: List[tk.Widget] = [
            tk.Label(self._body, text=text, font=self._font, width=width, anchor="w")
            for text, (_, _, width) in zip(texts, COLUMNS)]
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
        self._filter_after_id = None
        visible = sort_rows(apply_filter(self._rows, self._criteria()), *self._sort)
        shown = {id(row) for row in visible}
        for row in self._rows:
            if id(row) not in shown:
                for widget in self._widgets[id(row)]:
                    widget.grid_remove()
        for index, row in enumerate(visible):
            for column, widget in enumerate(self._widgets[id(row)]):
                widget.grid(row=index, column=column, sticky="w", padx=CELL_PADDING, pady=1)
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
