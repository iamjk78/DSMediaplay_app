import logging
import tkinter as tk
from tkinter import scrolledtext


class OptionalLevelFormatter(logging.Formatter):
    """
    Formatter that omits the levelname for records marked with extra={'hide_level': True},
    while keeping the record's levelno intact so TextHandler still colors the line correctly.
    """

    def format(self, record):
        if getattr(record, 'hide_level', False):
            return f"{self.formatTime(record)} - {record.getMessage()}"
        return super().format(record)


class ProblemCollector(logging.Handler):
    """Remembers the warnings and errors of a run, to list them once more at its end."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages = []
        self.enabled = True  # off while the list is being written, which would otherwise collect itself

    def emit(self, record) -> None:
        # progress lines are logged as errors only to be coloured, they are not problems of the run
        if self.enabled and not getattr(record, 'progress', False):
            self.messages.append(record.getMessage())


class TextHandler(logging.Handler):
    """
    class allowing logging into tkinter ScrollBox

    """

    def __init__(self, text_output: scrolledtext.ScrolledText) -> None:
        logging.Handler.__init__(self)
        self.text_output = text_output

    def emit(self, record) -> None:
        msg = self.format(record)

        def append():
            self.text_output.configure(state='normal')
            # a line that can be clicked (see LoggingTextBox) is marked by extra={'problem': True}
            problem = ('problem',) if getattr(record, 'problem', False) else ()
            if record.levelno == logging.WARNING:
                self.text_output.insert(tk.END, msg + '\n', ('warning',) + problem)
            elif record.levelno == logging.ERROR:
                self.text_output.insert(tk.END, msg + '\n', ('error',) + problem)
            elif record.levelno == logging.INFO:
                self.text_output.insert(tk.END, msg + '\n', 'info')
            else:
                self.text_output.insert(tk.END, msg + '\n')
            self.text_output.configure(state='disabled')
            self.text_output.yview(tk.END)  # Autoscroll after writing a line

        # This is necessary for if the box is on another thread
        self.text_output.after(0, append)
