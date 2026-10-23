"""The help is served from this computer; if its port is taken by another application the help must not open that
application's pages, and must still open."""
import socket
import unittest
from unittest.mock import patch

from documentation import server
from settings_and_log_window_test import WindowCase


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class BindServerTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, server, "bound_port", server.bound_port)

    def test_the_wanted_port_is_used_when_it_is_free(self):
        port = free_port()
        with patch.object(server, "PORT", port):
            httpd = server.bind_server()
        self.addCleanup(httpd.server_close)

        self.assertEqual(httpd.server_address, ("127.0.0.1", port))
        self.assertEqual(server.bound_port, port)

    def test_another_free_port_is_used_when_something_listens_on_the_wanted_one(self):
        with socket.socket() as other:
            other.bind(("127.0.0.1", 0))
            other.listen()
            busy = other.getsockname()[1]
            with patch.object(server, "PORT", busy):
                httpd = server.bind_server()
            self.addCleanup(httpd.server_close)

            self.assertNotEqual(server.bound_port, busy)
            self.assertEqual(httpd.server_address[1], server.bound_port)
            self.assertEqual(httpd.server_address[0], "127.0.0.1")  # this computer only

    def test_without_any_port_there_is_no_server(self):
        with patch.object(server, "DocumentationServer", side_effect=OSError("no port")):
            self.assertIsNone(server.bind_server())


class OpenHelpTest(WindowCase):
    def test_the_help_opens_on_the_port_of_the_server_in_the_language_of_the_application(self):
        with patch.object(server, "bound_port", 51234), patch("gui_app.gui.webbrowser.open") as opened:
            self.app.open_help()

        opened.assert_called_once_with(f"http://localhost:51234/{self.app.lang.language}/")

    def test_without_a_server_it_says_so_instead_of_opening_a_page_that_is_not_ours(self):
        with patch.object(server, "bound_port", None), patch("gui_app.gui.webbrowser.open") as opened, \
                patch("gui_app.gui.messagebox.showinfo") as info:
            self.app.open_help()

        opened.assert_not_called()
        info.assert_called_once()


if __name__ == "__main__":
    unittest.main()
