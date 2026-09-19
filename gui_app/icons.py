import sys
import tkinter as tk

from PIL import Image, ImageTk
from util.paths import resource_path


def set_window_icon(window: tk.Wm) -> None:
    """
    Windows: the multi-size .ico, sharp at any display scaling (taskbar, title bar, Alt+Tab).
    macOS build: nothing to do, the Dock shows the icon of the .app bundle and iconphoto would replace it
    with the small window image.
    Running from source: the small window image is the only icon available.
    """
    if sys.platform == "win32":
        window.iconbitmap(default=str(resource_path("assets/app.ico")))
    elif not getattr(sys, "frozen", False):
        window.tk_image = ImageTk.PhotoImage(Image.open(resource_path("assets/ds_media_icon.jpg")))
        window.iconphoto(True, window.tk_image)
