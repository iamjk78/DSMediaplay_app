import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from util.paths import resource_path


class InputTextBox(tk.Toplevel):
    def __init__(self, master=None, callback=None):
        super().__init__(master=master)
        self.lang = master.lang
        self.details_text = None
        self.tk_image = None
        entity_type = master.entity_type_var.get()
        action_name = master.option_choose_action.get()
        self.title(f"{self.lang.get_message("input")} - {entity_type} - {action_name}")
        self._callback = callback
        try:
            self._font = self.master.font
        except Exception:
            self._font = ("Helvetica", 12)
        self._button_row = 2
        self.setup_ui()
        self.grab_set()
        self.focus_set()

    def _set_geometry(self):
        dpi_scale = self.winfo_fpixels('1i')
        scaled_width = int(400 * (dpi_scale / 96))
        scaled_height = int(250 * (dpi_scale / 96))
        start_screen_height = int(self.winfo_screenheight() - (330 * (dpi_scale / 96)))
        self.geometry(f"{scaled_width}x{scaled_height}+0+{start_screen_height - scaled_height - 30}")

    def setup_icons(self):
        dsm_icon = resource_path("assets/ds_media_icon_input.jpg")
        icon_bitmap = Image.open(dsm_icon)
        self.tk_image = ImageTk.PhotoImage(icon_bitmap)
        # noinspection PyTypeChecker
        self.iconphoto(False, self.tk_image)

    def setup_ui(self):
        self.setup_icons()
        self._set_geometry()
        self.setup_text_area()
        self.setup_buttons()
        self.configure_grid()

    def setup_text_area(self):
        details_text = tk.Text(self, font=self._font, wrap="none")
        details_text.grid(row=0, column=0, padx=3, pady=3, sticky="nsew", columnspan=4)

        x_scrollbar = ttk.Scrollbar(self, orient="horizontal", command=details_text.xview,
                                    style="Horizontal.TScrollbar")
        x_scrollbar.grid(row=1, column=0, sticky="ew", columnspan=3)
        details_text.config(xscrollcommand=x_scrollbar.set)

        y_scrollbar = ttk.Scrollbar(self, orient="vertical", command=details_text.yview)
        y_scrollbar.grid(row=0, column=4, sticky="ns")
        details_text.config(yscrollcommand=y_scrollbar.set)
        self.details_text = details_text

    def setup_buttons(self):
        pad_x = 5
        pad_y = 5
        close_button = tk.Button(self, text=self.lang.get_message("close"), font=self._font, command=self.destroy)
        close_button.grid(row=self._button_row, column=0, padx=pad_x, pady=pad_y)

        clear_button = tk.Button(self, text=self.lang.get_message("delete"), font=self._font, command=self.clear_text)
        clear_button.grid(row=self._button_row, column=1, padx=pad_x, pady=pad_y)

        example_button = tk.Button(self, text=self.lang.get_message("input_help"), font=self._font, command=self.help)
        example_button.grid(row=self._button_row, column=2, padx=pad_x, pady=pad_y)

        save_button = tk.Button(self, text=self.lang.get_message("save"), font=self._font, command=self.save_text)
        save_button.grid(row=self._button_row, column=3, padx=pad_x, pady=pad_y)

    def clear_text(self):
        self.details_text.delete("1.0", tk.END)

    def save_text(self):
        if self._callback:
            self._callback(self.details_text.get("1.0", tk.END))
        self.destroy()

    def configure_grid(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)

    @staticmethod
    def help():
        """"""
        messagebox.showwarning("Not Implemented", "Not implemented yet!")
