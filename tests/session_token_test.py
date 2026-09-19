import unittest
from unittest.mock import MagicMock, patch

from api_testing.request_calls import LoginError, ServerApi


def api() -> ServerApi:
    instance = ServerApi.__new__(ServerApi)  # only the login request, nothing else
    instance._url = "https://demo.example.com/api"
    instance._login = "user"
    instance._password = "secret"
    instance._assert_hostname = None
    return instance


def answer(status_code: int, body) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    return response


class SessionTokenTest(unittest.TestCase):
    def test_returns_the_token(self):
        with patch("api_testing.request_calls.requests.post", return_value=answer(200, {"token": "abc"})):
            self.assertEqual(api()._get_session_token(), "abc")

    def test_wrong_credentials_answer_401_with_null_body(self):
        # what the real server returns: HTTP 401 and the JSON literal null
        with patch("api_testing.request_calls.requests.post", return_value=answer(401, None)):
            with self.assertRaises(LoginError):
                api()._get_session_token()

    def test_null_body_or_missing_token_is_a_failed_login_even_with_status_200(self):
        for body in (None, {}, {"token": ""}, [], "text"):
            with self.subTest(body=body):
                with patch("api_testing.request_calls.requests.post", return_value=answer(200, body)):
                    with self.assertRaises(LoginError):
                        api()._get_session_token()

    def test_login_request_has_a_timeout(self):
        with patch("api_testing.request_calls.requests.post", return_value=answer(200, {"token": "abc"})) as post:
            api()._get_session_token()

        self.assertIsNotNone(post.call_args.kwargs.get("timeout"))


if __name__ == "__main__":
    unittest.main()
