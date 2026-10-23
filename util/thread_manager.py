import threading

class ThreadManager:
    def __init__(self, target, logger, login_info, data):
        self.thread = None
        self.is_running = False
        self.target = target  # This target function should take no arguments
        self.logger = logger
        self.login_info = login_info
        self.data = data
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Initially not paused

    def start_thread(self):
        if not self.is_running or not (self.thread and self.thread.is_alive()):
            self.is_running = True
            self.stop_event.clear()
            self.thread = threading.Thread(target=self.target_wrapper)
            self.thread.daemon = True
            self.thread.start()

    def target_wrapper(self):
        """Wrapper for the target function to include stop and pause handling"""
        try:
            self.target()
        except Exception as e:
            self.logger.error(f"Error in thread execution: {e}")
        finally:
            self.is_running = False

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()

    def stop(self):
        self.stop_event.set()
        self.pause_event.set()

    def is_paused(self):
        return not self.pause_event.is_set()
