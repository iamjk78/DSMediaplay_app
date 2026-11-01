import unittest
from unittest.mock import patch

from api_testing.request_calls import ServerApi, _AssertHostnameAdapter, _assert_hostname_for


def api_for(url: str) -> ServerApi:
    api = ServerApi.__new__(ServerApi)  # transport layer only, no login
    api._url = url
    api._assert_hostname = _assert_hostname_for(url)
    return api


class TlsVerificationTest(unittest.TestCase):
    def test_regular_host_uses_default_verification(self):
        with patch("api_testing.request_calls.requests.request") as request:
            api_for("https://acme.signage.dsmediaplay.com")._request("get", "https://acme.signage.dsmediaplay.com/x")

        self.assertNotIn("verify", request.call_args.kwargs)

    def test_login_uses_default_verification(self):
        with patch("api_testing.request_calls.requests.request") as post:
            api_for("https://acme.signage.dsmediaplay.com")._post("https://acme.signage.dsmediaplay.com/session")

        self.assertNotIn("verify", post.call_args.kwargs)

    def test_underscore_host_is_checked_against_hyphenated_name(self):
        self.assertEqual(_assert_hostname_for("https://shop_admin.signage.dsmediaplay.com"),
                         "shop-admin.signage.dsmediaplay.com")
        self.assertIsNone(_assert_hostname_for("https://shop-admin.signage.dsmediaplay.com"))

    def test_the_hyphenated_name_is_used_only_for_the_servers_of_the_accounts(self):
        for url in ("https://shop_admin.example.com", "https://shop_admin.signage.dsmediaplay.com.evil.example",
                    "https://shop_admin.dsmediaplay.com", "https://shop_admin", "https://shop_admin.signage.example.com"):
            with self.subTest(url=url):
                self.assertIsNone(_assert_hostname_for(url))  # a name with an underscore must match as it is
        self.assertEqual(_assert_hostname_for("https://SHOP_admin.signage.dsmediaplay.com:8443/api"),  # a host name has no case
                         "shop-admin.signage.dsmediaplay.com")

    def test_adapter_passes_hostname_to_pool_manager(self):
        adapter = _AssertHostnameAdapter("shop-admin.signage.dsmediaplay.com")

        self.assertEqual(adapter.poolmanager.connection_pool_kw["assert_hostname"],
                         "shop-admin.signage.dsmediaplay.com")

    def test_underscore_host_never_disables_verification(self):
        with patch("api_testing.request_calls.requests.Session") as session_class:
            session = session_class.return_value.__enter__.return_value
            api_for("https://shop_admin.signage.dsmediaplay.com")._request("get", "https://shop_admin.x/y")

        self.assertNotIn("verify", session.request.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
