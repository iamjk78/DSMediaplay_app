import unittest
from unittest.mock import MagicMock, patch

from api_testing.request_calls import ServerApi, main_account_url

COLLABORATOR = "https://acmeshop_asmi.signage.dsmediaplay.com"
MAIN = "https://acmeshop.signage.dsmediaplay.com"


class MainAccountUrlTest(unittest.TestCase):
    def test_the_abbreviation_of_the_user_is_left_out(self):
        self.assertEqual(main_account_url(COLLABORATOR), MAIN)
        self.assertEqual(main_account_url("https://acmeshop_jdoe.signage.dsmediaplay.com"), MAIN)

    def test_an_address_of_a_main_account_stays(self):
        self.assertEqual(main_account_url(MAIN), MAIN)
        self.assertEqual(main_account_url("https://acme-shop.signage.dsmediaplay.com"),
                         "https://acme-shop.signage.dsmediaplay.com")

    def test_the_path_the_port_and_the_rest_of_the_host_stay(self):
        self.assertEqual(main_account_url(f"{COLLABORATOR}/api"), f"{MAIN}/api")
        self.assertEqual(main_account_url("https://acme_bobb.example.com:8443/api"), "https://acme.example.com:8443/api")

    def test_only_an_underscore_with_four_letters_at_the_end_is_an_abbreviation(self):
        for address in ("https://acme_shp.signage.dsmediaplay.com",  # three letters: a name with an underscore
                        "https://shop_admin.signage.dsmediaplay.com",  # five letters
                        "https://acme_ab12.signage.dsmediaplay.com",  # not letters
                        "https://acme_jdoe_x.signage.dsmediaplay.com",  # not at the end
                        "https://acmejkre.signage.dsmediaplay.com"):
            with self.subTest(address=address):
                self.assertEqual(main_account_url(address), address)

    def test_the_abbreviation_is_taken_off_the_end_only(self):
        self.assertEqual(main_account_url("https://acme_shp_jdoe.signage.dsmediaplay.com"),
                         "https://acme_shp.signage.dsmediaplay.com")
        self.assertEqual(main_account_url("https://acme_TMRA.signage.dsmediaplay.com"),
                         "https://acme.signage.dsmediaplay.com")

    def test_the_users_from_the_examples(self):
        for user in ("bwhi", "asmi", "jdoe", "cgre"):
            with self.subTest(user=user):
                self.assertEqual(main_account_url(f"https://acmeshop_{user}.signage.dsmediaplay.com"), MAIN)

    def test_an_underscore_elsewhere_in_the_host_is_not_touched(self):
        self.assertEqual(main_account_url("https://acme.some_serv.example.com"), "https://acme.some_serv.example.com")

    def test_a_host_without_dots_and_the_userinfo_are_handled_safely(self):
        self.assertEqual(main_account_url("https://acme_jdoe:8443/api"), "https://acme:8443/api")
        self.assertEqual(main_account_url("https://acme_jdoe"), "https://acme")
        self.assertEqual(main_account_url("https://user:pw@acme_jdoe.example.com"),
                         "https://user:pw@acme_jdoe.example.com")

    def test_nothing_before_the_abbreviation_means_nothing_to_leave_out(self):
        self.assertEqual(main_account_url("https://_jdoe.signage.dsmediaplay.com"),
                         "https://_jdoe.signage.dsmediaplay.com")


class ServerApiUsesTheMainAccountTest(unittest.TestCase):
    def login_answer(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"token": "abc"}
        return response

    def test_the_login_goes_to_the_main_account(self):
        with patch("api_testing.request_calls.requests.post", return_value=self.login_answer()) as post:
            api = ServerApi(url=f"{COLLABORATOR}/api", login="jdoe", password="secret")

        self.assertEqual(post.call_args.args[0], f"{MAIN}/api/session")
        self.assertEqual(api._url, f"{MAIN}/api")
        self.assertEqual(post.call_args.kwargs["json"]["email"], "jdoe")  # the login itself is unchanged

    def test_the_hostname_is_verified_normally_after_the_change(self):
        with patch("api_testing.request_calls.requests.post", return_value=self.login_answer()):
            api = ServerApi(url=f"{COLLABORATOR}/api", login="jdoe", password="secret")

        self.assertIsNone(api._assert_hostname)  # no underscore left: the certificate matches as it is

    def test_the_later_requests_go_to_the_main_account_too(self):
        with patch("api_testing.request_calls.requests.post", return_value=self.login_answer()):
            api = ServerApi(url=f"{COLLABORATOR}/api", login="jdoe", password="secret")
        answer = MagicMock(ok=True)
        answer.json.return_value = {"success": True, "data": {"objects": []}}

        with patch("api_testing.request_calls.requests.request", return_value=answer) as request:
            api.get_player_objects()

        self.assertEqual(request.call_args.args[:2], ("get", f"{MAIN}/api/players"))

    def test_an_image_of_the_main_account_gets_the_token(self):
        with patch("api_testing.request_calls.requests.post", return_value=self.login_answer()):
            api = ServerApi(url=f"{COLLABORATOR}/api", login="jdoe", password="secret")
        image = MagicMock(ok=True, content=b"\x89PNG\r\n\x1a\nxx")

        with patch("api_testing.request_calls.requests.request", return_value=image) as own, \
                patch("api_testing.request_calls.requests.get") as foreign:
            api.download_snapshot(f"{MAIN}/media/s.png")

        own.assert_called_once()
        self.assertEqual(own.call_args.kwargs["headers"], {"x-access-token": "abc"})
        self.assertNotIn("params", own.call_args.kwargs)
        self.assertNotIn("abc", own.call_args.args[1])  # the token is not in the address
        foreign.assert_not_called()


if __name__ == "__main__":
    unittest.main()
