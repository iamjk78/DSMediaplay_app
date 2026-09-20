"""
Lets the GUI tests run without disturbing whoever is working at the computer.

The tests open real Tk windows (nothing else tests the behaviour of real widgets), and on macOS a Tk application
takes the focus from the current application and shows its windows. Here every Tk and Toplevel window is made
fully transparent (a transparent window is also not hit by clicks), and on macOS the test process is not allowed to
become the active application, so the focus stays where it was. Set DSM_TESTS_VISIBLE=1 to see the windows.
"""
import ctypes
import ctypes.util
import os
import sys
import tkinter as tk

_installed = False
_activation_prohibited = False


def _prohibit_activation() -> None:
    """macOS: NSApplicationActivationPolicyProhibited. Only after Tk has created its own NSApplication object."""
    global _activation_prohibited
    if _activation_prohibited or sys.platform != "darwin":
        return
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = objc.objc_msgSend
    send.restype = ctypes.c_void_p
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    application = send(objc.objc_getClass(b"NSApplication"), objc.sel_registerName(b"sharedApplication"))
    send.restype = ctypes.c_bool
    send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
    send(application, objc.sel_registerName(b"setActivationPolicy:"), 2)
    _activation_prohibited = True


def _quiet(window: tk.Wm) -> None:
    _prohibit_activation()
    try:
        window.attributes("-alpha", 0.0)
    except tk.TclError:  # a window system without transparency, or the window is already gone
        pass


def install() -> None:
    global _installed
    if _installed or os.environ.get("DSM_TESTS_VISIBLE") == "1":
        return
    original_tk_init = tk.Tk.__init__
    original_toplevel_init = tk.Toplevel.__init__

    def quiet_tk_init(self, *args, **kwargs):
        original_tk_init(self, *args, **kwargs)
        _quiet(self)

    def quiet_toplevel_init(self, *args, **kwargs):
        original_toplevel_init(self, *args, **kwargs)
        # Not at once: setting the transparency creates the native window, and the code that made this window may
        # still be about to give it another style (the tooltips do), which would then be applied to a titled window
        self.after_idle(_quiet, self)

    tk.Tk.__init__ = quiet_tk_init
    tk.Toplevel.__init__ = quiet_toplevel_init
    _installed = True
