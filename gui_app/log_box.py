import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from gui_app.icons import set_window_icon
import logging
from util.thread_manager import ThreadManager
from gui_app.logger import TextHandler, OptionalLevelFormatter
from processor.input_processing import FormatException, ProcessorFactory, InternalException


CONFIRM_LIST_LIMIT = 15


class LoggingTextBoxFactory:
    @staticmethod
    def create_log_box(processor_type: str, master: "DSMediaplayApp", url: str, login: str, password: str, data: str,
                       extra_settings: dict = None):
        class_map = {
            "assets_to_playlists": PlaylistAssetsLogBox,
            "remove_assets_from_playlists": PlaylistRemoveAsset,
            "playlists_to_groups": PlaylistsToGroupLogBox,
            "detailed_playlists_to_groups": DetailedPlaylistsToGroupLogBox,
            "remove_playlists_from_group": GroupRemovePlaylist,
            "remove_playlist_list": RemovePlaylistList,
            "groups_to_players": GroupToPlayerLogBox,
            "notes_to_players": NotesToPlayerLogBox,
            "player_snapshot": PlayerSnapshotLogBox,
            "player_config_location": PlayerConfigLocationLogBox,
            "location_plan": LocationsPlanLogBox,
            "group_rename": GroupRenameLogBox,
            "player_rename": PlayerRenameLogBox,
            "player_labels": PlayerLabelLogBox,
            "group_settings": GroupSettingsLogBox,
            "playlist_settings": PlaylistSettingsLogBox,
            "add_playlist_to_group": AddPlaylistToGroupLogBox,
            "add_detailed_playlist_to_group": AddDetailedPlaylistToGroupLogBox,
            "location_rename": LocationRenameLogBox,
            "remove_expired_playlists": GroupRemoveExpiredPlaylistLogBox,
            "remove_all_expired_playlists": GroupRemoveAllExpiredPlaylistLogBox,
            "create_location": CreateLocationLogBox,
            "create_group": CreateGroupLogBox,
            "create_player": CreatePlayerLogBox,
            "create_playlist": CreatePlaylistLogBox,
            "create_label": CreateLabelLogBox,
            "remove_additional_playlists": DeleteAdditionalPlaylistLogBox,
            "remove_unused_groups": RemoveUnusedGroupsLogBox,
            "remove_unused_playlists": RemoveUnusedPlaylistsLogBox,
            "remove_unused_assets": RemoveUnusedAssetsLogBox,
            "remove_unused_labels": RemoveUnusedLabelsLogBox,
            "remove_unused_locations": RemoveUnusedLocationsLogBox,
            "clone_player": ClonePlayersLogBox,
            "asset_validity": AssetValidityLogBox,
            "player_update": PlayerUpdateLogBox,
            "remove_all_unused_groups": RemoveAllUnusedGroupsLogBox,
            "remove_all_unused_playlists": RemoveAllUnusedPlaylistsLogBox,
            "remove_all_unused_assets": RemoveAllUnusedAssetsLogBox,
            "remove_all_unused_labels": RemoveAllUnusedLabelsLogBox,
            "remove_all_unused_locations": RemoveAllUnusedLocationsLogBox,
            "deploy_all_players": DeployAllPlayersLogBox,
            "deploy_selected_groups": DeploySelectedGroupsLogBox
        }
        log_box_class = class_map.get(processor_type)
        if not log_box_class:
            raise ValueError(f"Unknown processor type: {processor_type}")
        return log_box_class(master=master, url=url, login=login, password=password, data=data,
                             extra_settings=extra_settings)


class LoggingTextBox(tk.Toplevel):
    def __init__(self, processor_type: str, *, url: str, login: str, password: str, data: str,
                 master: "DSMediaplayApp" = None, extra_settings: dict = None):
        super().__init__(master=master)
        self.indication_label = None
        self._activity_icon = None
        self._activity_canvas = None
        self.lang = master.lang
        self.title(self.lang.get_message("log_title"))
        self.processor_type = processor_type
        self.input_processor = None
        self.logger = None
        self._login_info = {
            "login": login,
            "password": password,
            "url": url
        }
        self._raw_data = data
        self._extra_settings = extra_settings or {}
        self.log_text = None
        try:
            self._font = self.master.font
        except Exception:
            self._font = ("Helvetica", 12)
        self.grab_set()
        self.focus_set()
        self._textbox_row = 0
        self._buttons_row = 1
        self.setup_ui()
        self.setup_logging()
        self.thread_manager = ThreadManager(self.run, self.logger, self._login_info, self._raw_data)
        self.bind("<Visibility>", self.start_action)
        self.setup_buttons()

    def start_action(self, _):
        """ Initiates operations on a separate thread to avoid blocking the GUI. """
        self.thread_manager.start_thread()
        self.unbind("<Visibility>")

    def setup_icons(self):
        set_window_icon(self)

    def run(self):
        self.run_input_processing()

    def run_input_processing(self):
        """Initiates operations and checks for stop/pause events"""
        self.input_processor = ProcessorFactory.create_processor(
            self.processor_type,
            self.logger,
            self._login_info["url"],
            self._login_info["login"],
            self._login_info["password"],
            self.lang,
            **self._extra_settings
        )
        try:
            self.input_processor.load(self._raw_data)
            to_confirm = self.input_processor.items_to_confirm()
            if to_confirm and not self._confirm_removal(to_confirm):
                self.logger.info(self.lang.get_message("operation_cancelled"))
                self.update_activity_circle("C")
                self.setup_buttons()
                return
            for _ in self.input_processor.run():
                # Check if the thread is stopped
                if self.thread_manager.stop_event.is_set():
                    self.logger.info(self.lang.get_message("operation_stopped"))
                    break

                # Check if the thread is paused
                if self.thread_manager.is_paused():
                    self.thread_manager.pause_event.wait()  # Wait until resume is called

            self.logger.info(self.lang.get_message("operation_successful"))
            self.setup_buttons()
            self.display_success()

        except FormatException:
            self.display_error()
        except InternalException:
            self.display_error()

    def _confirm_removal(self, items: list) -> bool:
        """
        Asks, before anything is deleted for good, whether to go on; the answer of a modal dialog that the
        main thread shows while this (the worker) thread waits. The default answer is "No".
        """
        shown = items[:CONFIRM_LIST_LIMIT]
        lines = [f"• {item}" for item in shown]
        if len(items) > len(shown):
            lines.append(self.lang.get_message("confirm_remove_more", count=len(items) - len(shown)))
        text = self.lang.get_message("confirm_remove_text", count=len(items), items="\n".join(lines))
        answer = []
        answered = threading.Event()

        def ask():
            try:
                answer.append(messagebox.askyesno(self.lang.get_message("confirm_remove_title"), text,
                                                  icon="warning", default="no", parent=self))
            finally:
                answered.set()

        try:
            self.after(0, ask)
        except tk.TclError:  # the window is gone
            return False
        while not answered.wait(0.5):
            try:
                if not self.winfo_exists():  # closed before the dialog was shown: nobody is going to answer
                    return False
            except tk.TclError:
                return False
        return bool(answer and answer[0])

    def setup_ui(self):
        self.setup_text_area()
        self.setup_icons()
        self.setup_activity()
        self.configure_grid()

    def setup_text_area(self):
        self.log_text = scrolledtext.ScrolledText(self, font=self._font, wrap="word", state="disabled")
        self.log_text.grid(row=self._textbox_row, column=0, columnspan=4, sticky="nsew", padx=3, pady=3)

        self.log_text.tag_configure('info', foreground='black')
        self.log_text.tag_configure('warning', foreground='orange', font=(self._font[0], self._font[1], 'bold'))
        self.log_text.tag_configure('error', foreground='red', font=(self._font[0], self._font[1], 'bold'))

    def setup_buttons(self):
        pad_x = 5
        pad_y = 5

        stop_button = tk.Button(self, text="STOP", font=self._font, command=self._stop_action)
        stop_button.grid(row=self._buttons_row, column=1, sticky="ew", padx=pad_x, pady=pad_y)

        close_button = tk.Button(self, text=self.lang.get_message("close"), font=self._font, command=self.destroy)
        close_button.grid(row=self._buttons_row, column=2, sticky="ew", padx=pad_x, pady=pad_y)

        save_button = tk.Button(self, text=self.lang.get_message("save"), font=self._font, command=self.save_text)
        save_button.grid(row=self._buttons_row, column=3, padx=pad_x, pady=pad_y)

    def save_text(self):
        file_path = filedialog.asksaveasfilename(defaultextension=".txt",
                                                 filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        with open(file_path, "w") as file:
            log_content = self.log_text.get("1.0", tk.END).strip()
            file.write(log_content)
        messagebox.showinfo(self.lang.get_message("info_title"), self.lang.get_message("file_saved"))

    def configure_grid(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

    def display_error(self):
        self.update_activity_circle("R")
        self.setup_buttons()

    def display_success(self):
        self.update_activity_circle("G")
        self.setup_buttons()

    def setup_logging(self):
        # Create a logger for this window
        self.logger = logging.getLogger(f"LoggingTextBox-{id(self)}")
        self.logger.setLevel(logging.INFO)

        # Create a text handler that outputs logs to the ScrolledText widget
        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(OptionalLevelFormatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(text_handler)

    def setup_activity(self):
        activity_frame = tk.Frame(self, width=60, height=60)
        activity_frame.grid(row=self._buttons_row, column=0, sticky="w", padx=5, pady=5)

        self._activity_canvas = tk.Canvas(activity_frame, width=40, height=40)
        self._activity_canvas.pack(side=tk.LEFT)
        self._activity_icon = self.create_circle(20, 20, 10, fill="orange")

        self.indication_label = ttk.Label(activity_frame, text=self.lang.get_message("working"))
        self.indication_label.pack(side=tk.LEFT, padx=5)

    def create_circle(self, x, y, r, **kwargs):
        return self._activity_canvas.create_oval(x - r, y - r, x + r, y + r, **kwargs)

    def update_activity_circle(self, color: {"R", "G", "O", "C"}):
        colors = {"R": ("red", self.lang.get_message("error")), "G": ("green", self.lang.get_message("done")),
                  "O": ("orange", self.lang.get_message("working")),
                  "C": ("gray", self.lang.get_message("cancelled"))}
        self._activity_canvas.itemconfig(self._activity_icon, fill=colors[color][0])
        self.indication_label.config(text=colors[color][1])

    def _stop_action(self):
        self.thread_manager.stop()

    def _pause_action(self):
        self.thread_manager.pause()

    def _resume_action(self):
        self.thread_manager.resume()


class GroupToPlayerLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="player_group", **kwargs)


class PlaylistsToGroupLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="playlist", **kwargs)


class DetailedPlaylistsToGroupLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="detailed_playlist", **kwargs)


class PlaylistAssetsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="asset_to_playlist", **kwargs)


class PlaylistRemoveAsset(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_assets", **kwargs)


class GroupRemovePlaylist(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_playlists", **kwargs)


class RemovePlaylistList(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_playlist_list", **kwargs)


class NotesToPlayerLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="player_note", **kwargs)


class PlayerConfigLocationLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="player_config_location", **kwargs)


class GroupRenameLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="group_rename", **kwargs)


class LocationsPlanLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="location_plan", **kwargs)


class PlayerLabelLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="player_labels", **kwargs)


class GroupSettingsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="group_settings", **kwargs)


class PlaylistSettingsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="playlist_settings", **kwargs)


class PlayerSnapshotLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="player_snapshot", **kwargs)


class PlayerRenameLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="player_rename", **kwargs)


class AddPlaylistToGroupLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="add_playlist", **kwargs)


class AddDetailedPlaylistToGroupLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="add_detailed_playlist", **kwargs)


class LocationRenameLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="location_rename", **kwargs)


class GroupRemoveExpiredPlaylistLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_expired_playlists", **kwargs)


class GroupRemoveAllExpiredPlaylistLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_all_expired_playlists", **kwargs)


class CreateLocationLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="create_location", **kwargs)


class CreateGroupLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="create_group", **kwargs)


class CreatePlayerLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="create_player", **kwargs)


class CreatePlaylistLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="create_playlist", **kwargs)


class CreateLabelLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="create_label", **kwargs)


class RemoveUnusedGroupsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_unused_groups", **kwargs)


class RemoveUnusedPlaylistsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_unused_playlists", **kwargs)


class RemoveUnusedAssetsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_unused_assets", **kwargs)


class RemoveUnusedLabelsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_unused_labels", **kwargs)


class RemoveUnusedLocationsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_unused_locations", **kwargs)


class ClonePlayersLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="clone_player", **kwargs)


class RemoveAllUnusedGroupsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_all_unused_groups", **kwargs)


class RemoveAllUnusedPlaylistsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_all_unused_playlists", **kwargs)


class RemoveAllUnusedAssetsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_all_unused_assets", **kwargs)


class RemoveAllUnusedLabelsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_all_unused_labels", **kwargs)


class RemoveAllUnusedLocationsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_all_unused_locations", **kwargs)


class AssetValidityLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="asset_validity", **kwargs)


class PlayerUpdateLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="player_update", **kwargs)


class DeleteAdditionalPlaylistLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="remove_additional_playlists", **kwargs)


class DeployAllPlayersLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="deploy_all_players", **kwargs)


class DeploySelectedGroupsLogBox(LoggingTextBox):
    def __init__(self, **kwargs):
        super().__init__(processor_type="deploy_selected_groups", **kwargs)