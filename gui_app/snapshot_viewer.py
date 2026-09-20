import math
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from io import BytesIO
from tkinter import filedialog, ttk
from typing import Callable, Optional, Tuple

import requests
from PIL import Image, ImageTk

from api_testing.request_calls import LoginError, ServerApi, SnapshotError, snapshot_file_stem, snapshot_reason
from gui_app.icons import set_window_icon
from gui_app.tooltip import Tooltip

LIVE_INTERVALS = (2, 5, 10, 15, 20)  # seconds between two snapshots of the live view; 2 is the least a player can bear
DEFAULT_LIVE_INTERVAL = 5
MIN_REQUEST_INTERVAL = 10  # seconds between the starts of two snapshots asked for with the button of the table
MAX_CONCURRENT_SNAPSHOTS = 3
SLOT_RETRY_MS = 500
POLL_INTERVAL_MS = 100
RESIZE_DELAY_MS = 40
IMAGE_BACKGROUND = "#1e1e1e"
ERROR_COLOR = "#c62828"


def _clock() -> float:
    return time.monotonic()


class SnapshotSlots:
    """How many snapshots may be taken at the same time: each one is real work for a player and for the server."""

    def __init__(self, limit: int = MAX_CONCURRENT_SNAPSHOTS):
        self.limit = limit
        self._semaphore = threading.BoundedSemaphore(limit)

    def try_acquire(self) -> bool:
        return self._semaphore.acquire(blocking=False)

    def release(self) -> None:
        self._semaphore.release()


def fetch_snapshot_from_server(url: str, login: str, password: str, player_id: str) -> Tuple[bytes, str]:
    """Asks the player for a snapshot and downloads it: the image and its file extension."""
    server = ServerApi(url=f"{url}/api", login=login, password=password)
    try:
        return server.download_snapshot(server.take_snapshot(player_id)["url"])
    finally:
        server.close_quietly()


def decode_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(data))
        image.load()
        return image.convert("RGB")
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise SnapshotError("not_image")


def ask_save_path(window: tk.Misc, initial_file: str, extension: str) -> str:
    return filedialog.asksaveasfilename(parent=window, initialfile=initial_file, defaultextension=extension,
                                        filetypes=[(extension.lstrip(".").upper(), f"*{extension}")])


class SnapshotViewer(tk.Toplevel):
    """
    The snapshot of one player, in a window of its own. The image lives only in memory: a new snapshot replaces the
    one before it, and nothing is written to the disk unless the user saves the one that is shown.

    "Live-view" takes a snapshot again and again, `interval` seconds after the start of the previous one (or at once,
    when a snapshot lasts longer); "Pause" stops that. A failed snapshot stops it as well: the player or the server
    has a problem, and asking over and over would not help. At most `slots.limit` snapshots run at once (the slots
    are shared by the windows of an account); a window that finds none free waits for one.
    """

    def __init__(self, master, *, player_name: str, player_id: str, credentials: Tuple[str, str, str],
                 slots: SnapshotSlots, font, button_style: str = "TButton",
                 fetch: Callable[[str, str, str, str], Tuple[bytes, str]] = fetch_snapshot_from_server,
                 ask_path: Callable[[tk.Misc, str, str], str] = ask_save_path):
        super().__init__(master)
        self.lang = master.lang
        self.player_name = player_name
        self._player_id = player_id
        self._credentials = credentials
        self._slots = slots
        self._fetch = fetch
        self._ask_path = ask_path
        self._font = font
        self._results: "queue.Queue" = queue.Queue()
        self._busy = False  # a snapshot is being taken (or is waiting for a free slot)
        self._live = False
        self._pending = False  # the table's button was pressed too early: the snapshot follows when the time is up
        self._last_start: Optional[float] = None
        self._interval = DEFAULT_LIVE_INTERVAL
        self._image: Optional[Image.Image] = None
        self._raw: Optional[bytes] = None
        self._extension = ""
        self._taken_at: Optional[datetime] = None
        self._duration: Optional[float] = None  # seconds it took to get the image that is shown
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._next_id: Optional[str] = None
        self._poll_id: Optional[str] = None
        self._slot_id: Optional[str] = None  # the wait for a free slot
        self._resize_id: Optional[str] = None
        self._closed = False

        self.title(self.lang.get_message("sv_title", player=player_name))
        set_window_icon(self)
        self._build(button_style)
        self._place_near(master)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._update_controls()
        self.take_snapshot()

    # ---- construction

    def _build(self, button_style: str):
        bar = tk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 6))
        bar.grid_columnconfigure(3, weight=1)
        message = self.lang.get_message
        self.retake_button = self._button(bar, "sv_retake", lambda: message("sv_tip_retake"), self.take_snapshot,
                                          button_style)
        self.retake_button.grid(row=0, column=0, padx=(0, 6))
        self.live_button = self._button(
            bar, "sv_live", lambda: message("sv_tip_pause" if self._live else "sv_tip_live"), self.toggle_live,
            button_style)
        # "Pause" and "Live-view" take turns on this button: as wide for both, so nothing beside it moves
        self.live_button.configure(width=max(len(message("sv_live")), len(message("sv_pause"))) + 2)
        self.live_button.grid(row=0, column=1, padx=(0, 10))
        interval = tk.Frame(bar)
        interval.grid(row=0, column=2)
        self._interval_label = tk.Label(interval, text=message("sv_interval"), font=self._font)
        self._interval_label.pack(side="left", padx=(0, 6))
        self.interval_box = ttk.Combobox(interval, state="readonly", width=5, font=self._font,
                                         values=[message("sv_seconds", seconds=seconds) for seconds in LIVE_INTERVALS])
        self.interval_box.current(LIVE_INTERVALS.index(self._interval))
        self.interval_box.bind("<<ComboboxSelected>>", lambda _: self._interval_changed())
        self.interval_box.pack(side="left")
        Tooltip(self.interval_box, lambda: message("sv_tip_interval"))
        self.save_button = self._button(bar, "sv_save", lambda: message("sv_tip_save"), self.save, button_style)
        self.save_button.grid(row=0, column=4, sticky="e")

        self.canvas = tk.Canvas(self, background=IMAGE_BACKGROUND, highlightthickness=0, borderwidth=0, width=1,
                                height=1)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=10)
        self.canvas.bind("<Configure>", lambda _: self._schedule_render())

        bottom = tk.Frame(self)
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 8))
        bottom.grid_columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=80)
        self.progress.grid(row=0, column=0, padx=(0, 8))
        self.progress.grid_remove()
        self.status_var = tk.StringVar()
        self._status_label = tk.Label(bottom, textvariable=self.status_var, font=self._font, anchor="w")
        self._status_label.grid(row=0, column=1, sticky="ew")
        self._default_status_color = str(self._status_label.cget("foreground"))
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.update_idletasks()
        self.minsize(bar.winfo_reqwidth() + 20, 300)

    def _button(self, bar, message: str, tip: Callable[[], str], command, style: str) -> ttk.Button:
        button = ttk.Button(bar, text=self.lang.get_message(message), command=command, style=style)
        Tooltip(button, tip)
        return button

    def _place_near(self, master):
        self.geometry(f"960x620+{master.winfo_rootx() + 40}+{master.winfo_rooty() + 40}")

    def set_font(self, font) -> None:
        self._font = font
        for widget in (self._interval_label, self.interval_box, self._status_label):
            widget.configure(font=font)

    # ---- taking snapshots

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def live(self) -> bool:
        return self._live

    @property
    def has_image(self) -> bool:
        return self._image is not None

    def take_snapshot(self):
        """Takes a snapshot now (as soon as a slot is free); nothing happens while one is already on its way."""
        if self._busy or self._closed:
            return
        self._cancel_next()
        self._pending = False
        self._busy = True
        self._update_controls()
        if self._image is None:
            self._render()  # the placeholder says a snapshot is on its way
        self._try_start()

    def request_snapshot(self):
        """
        The button of the table: brings the window forward and takes a snapshot, but not more often than every
        MIN_REQUEST_INTERVAL seconds. A press that comes earlier is remembered and served when the time is up. The
        live view keeps the image fresh by itself, so for it the press only brings the window forward.
        """
        self.deiconify()
        self.lift()
        self.focus_force()
        if self._busy or self._live:
            return
        wait = self._seconds_until_request()
        if wait <= 0:
            self.take_snapshot()
            return
        self._pending = True
        self._cancel_next()
        self._next_id = self.after(math.ceil(wait * 1000), self.take_snapshot)
        self._show_idle_status()

    def _seconds_until_request(self) -> float:
        if self._last_start is None:
            return 0
        return max(0.0, MIN_REQUEST_INTERVAL - (_clock() - self._last_start))

    def _try_start(self):
        self._slot_id = None
        if self._closed:
            return
        self._show_progress(True)
        if not self._slots.try_acquire():
            self._set_status(self.lang.get_message("sv_waiting", count=self._slots.limit))
            self._slot_id = self.after(SLOT_RETRY_MS, self._try_start)
            return
        self._last_start = _clock()
        self._set_status(self.lang.get_message("sv_taking"))
        threading.Thread(target=self._work, daemon=True).start()
        self._poll_id = self.after(POLL_INTERVAL_MS, self._poll)

    def _work(self):
        try:
            outcome = self._take()
        except Exception:  # whatever happens, the window has to hear about it: it would wait for ever otherwise
            outcome = "error", self.lang.get_message("snapshot_reason_download")
        finally:
            self._slots.release()
        self._results.put(outcome)

    def _take(self):
        try:
            started = _clock()
            data, extension = self._fetch(*self._credentials, self._player_id)
            image = decode_image(data)
            return "image", (data, extension, image, _clock() - started)
        except LoginError:
            return "error", self.lang.get_message("incorrect_login")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            return "error", self.lang.get_message("connection_error")
        except Exception as error:  # never show the exception itself: it can carry the request, including the token
            return "error", self.lang.get_message(f"snapshot_reason_{snapshot_reason(error)}")

    def _poll(self):
        try:
            kind, value = self._results.get_nowait()
        except queue.Empty:
            self._poll_id = self.after(POLL_INTERVAL_MS, self._poll)
            return
        self._poll_id = None
        self._busy = False
        self._show_progress(False)
        if kind == "image":
            self._show_image(*value)
            self._show_idle_status()
        else:
            self._live = False  # a failed snapshot ends the live view
            self._set_status(self.lang.get_message("sv_failed", reason=value), failed=True)
        self._update_controls()
        if self._live:
            self._schedule_live()

    # ---- the image

    def _show_image(self, data: bytes, extension: str, image: Image.Image, duration: float):
        """The previous image is let go of here: only the newest one is kept."""
        self._raw, self._extension, self._image, self._taken_at = data, extension, image, datetime.now()
        self._duration = duration
        self._render()

    def _schedule_render(self):
        if self._resize_id:
            self.after_cancel(self._resize_id)
        self._resize_id = self.after(RESIZE_DELAY_MS, self._render)

    def _render(self):
        self._resize_id = None
        self.canvas.delete("all")
        self._photo = None
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if self._image is None:
            text = self.lang.get_message("sv_taking" if self._busy else "sv_no_image")
            self.canvas.create_text(width // 2, height // 2, text=text,
                                    fill="#9e9e9e", font=self._font)
            return
        scale = min(width / self._image.width, height / self._image.height)
        size = (max(1, int(self._image.width * scale)), max(1, int(self._image.height * scale)))
        self._photo = ImageTk.PhotoImage(self._image.resize(size, Image.Resampling.LANCZOS))
        self.canvas.create_image(width // 2, height // 2, image=self._photo, anchor="center")

    # ---- live view

    def toggle_live(self):
        if self._live:
            self.pause()
        else:
            self.start_live()

    def start_live(self):
        self._live = True
        self._pending = False
        self._update_controls()
        if self._busy:  # the snapshot on its way is the first one; the next follows it
            return
        self._cancel_next()
        self._show_idle_status()
        self.take_snapshot()

    def pause(self):
        """Stops the live view; a snapshot that is on its way still arrives."""
        self._live = False
        self._cancel_next()
        self._update_controls()
        self._show_idle_status()

    def _interval_changed(self):
        self._interval = LIVE_INTERVALS[self.interval_box.current()]
        if self._live and not self._busy:
            self._schedule_live()
        self._show_idle_status()

    @property
    def interval(self) -> int:
        return self._interval

    def _schedule_live(self):
        """The next snapshot starts `interval` seconds after the start of the last one, or at once if that is past."""
        self._cancel_next()
        elapsed = _clock() - (self._last_start if self._last_start is not None else _clock())
        self._next_id = self.after(max(0, math.ceil((self._interval - elapsed) * 1000)), self.take_snapshot)

    def _cancel_next(self):
        if self._next_id:
            self.after_cancel(self._next_id)
            self._next_id = None

    # ---- saving

    def save(self):
        """Saves the image that is shown to a file the user picks (the only way an image reaches the disk)."""
        raw, extension, taken_at = self._raw, self._extension, self._taken_at  # a live view can replace them meanwhile
        if raw is None or taken_at is None:
            return
        path = self._ask_path(self, snapshot_file_stem(self.player_name, taken_at) + extension, extension)
        if not path:
            return
        try:
            with open(path, "wb") as file:
                file.write(raw)
        except OSError as error:
            self._set_status(self.lang.get_message("sv_save_failed", reason=error.strerror or type(error).__name__),
                             failed=True)
            return
        self._set_status(self.lang.get_message("sv_saved", path=path))

    # ---- state shown

    def _update_controls(self):
        self.retake_button.state(["disabled"] if self._busy else ["!disabled"])
        self.save_button.state(["!disabled"] if self._image is not None else ["disabled"])
        self.live_button.configure(text=self.lang.get_message("sv_pause" if self._live else "sv_live"))

    def _show_progress(self, on: bool):
        if on:
            self.progress.grid()
            self.progress.start(15)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def _show_idle_status(self):
        """When the image is from, and what the live view is doing; a snapshot on its way shows its own text."""
        if self._busy:
            return
        parts = []
        if self._live:
            parts.append("● " + self.lang.get_message("sv_live_running", seconds=self._interval))
        if self._pending:
            parts.append(self.lang.get_message("sv_next_snapshot", seconds=MIN_REQUEST_INTERVAL))
        if self._taken_at:
            parts.append(self.lang.get_message("sv_taken", time=self._taken_at.strftime("%H:%M:%S")))
            parts.append(self.lang.get_message("sv_duration", seconds=self._seconds_text(self._duration or 0)))
        elif not self._live:
            parts.append(self.lang.get_message("sv_no_image"))
        self._set_status(" · ".join(parts))

    def _seconds_text(self, seconds: float) -> str:
        text = f"{seconds:.1f}"
        return text.replace(".", ",") if self.lang.language == "cz" else text

    def _set_status(self, text: str, failed: bool = False):
        self.status_var.set(text)
        self._status_label.configure(foreground=ERROR_COLOR if failed else self._default_status_color)

    def destroy(self):
        self._closed = True
        self._live = False
        for after_id in (self._next_id, self._slot_id, self._poll_id, self._resize_id):
            if after_id:
                self.after_cancel(after_id)
        self._image = self._photo = self._raw = None
        super().destroy()
