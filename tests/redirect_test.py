"""A redirect is not followed by the requests that carry the session token or the password: it would take them to
wherever the redirect points, and with a 307 or 308 the body of the request too."""
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from api_testing.request_calls import ResponseError, ServerApi


class Servers:
    """Two local servers: the first one redirects everything to the second one, which writes down what it receives."""

    def __init__(self, status):
        self.received = []
        received = self.received

        class Target(BaseHTTPRequestHandler):
            def do_ANY(handler):
                length = int(handler.headers.get("Content-Length") or 0)
                received.append((handler.headers.get("x-access-token"), handler.rfile.read(length)))
                handler.send_response(200)
                handler.end_headers()
                handler.wfile.write(b'{"success": true, "data": {}}')

            do_GET = do_POST = do_ANY

            def log_message(handler, *args):
                pass

        self.target = HTTPServer(("127.0.0.1", 0), Target)

        class Redirecting(BaseHTTPRequestHandler):
            def do_ANY(handler):
                handler.send_response(status)
                handler.send_header("Location", f"http://127.0.0.1:{self.target.server_port}/stolen")
                handler.send_header("Content-Length", "0")
                handler.end_headers()

            do_GET = do_POST = do_ANY

            def log_message(handler, *args):
                pass

        self.source = HTTPServer(("127.0.0.1", 0), Redirecting)
        for server in (self.target, self.source):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def close(self):
        for server in (self.target, self.source):
            server.shutdown()
            server.server_close()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.source.server_port}"


class RedirectTest(unittest.TestCase):
    def api(self, servers):
        api = ServerApi.__new__(ServerApi)
        api._url = servers.url
        api._assert_hostname = None
        api._session_token = "secret-token"
        api._login = "user"
        api._password = "secret-password"
        return api

    def test_a_redirect_takes_neither_the_token_nor_the_body_to_another_host(self):
        for status in (302, 307, 308):
            for method in ("get", "post"):
                with self.subTest(status=status, method=method):
                    servers = Servers(status)
                    self.addCleanup(servers.close)
                    api = self.api(servers)

                    with self.assertRaises(ResponseError):
                        api._make_request(method, "/players", json={"password": "secret-password"})

                    self.assertEqual(servers.received, [])

    def test_the_login_is_not_sent_on_either(self):
        for status in (302, 307, 308):
            with self.subTest(status=status):
                servers = Servers(status)
                self.addCleanup(servers.close)
                api = self.api(servers)

                with self.assertRaises(ResponseError):
                    api._get_session_token()

                self.assertEqual(servers.received, [])


if __name__ == "__main__":
    unittest.main()
