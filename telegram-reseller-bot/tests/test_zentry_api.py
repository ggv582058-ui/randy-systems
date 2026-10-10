import io
import json
import unittest
import urllib.error

from zentry_api import ZentryClient, ZentryError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class ZentryClientTests(unittest.TestCase):
    def test_create_license_uses_seller_headers(self):
        captured = {}

        def opener(request, timeout):
            captured["headers"] = dict(request.header_items())
            if request.full_url.endswith("/create"):
                captured["payload"] = json.loads(request.data)
            captured["timeout"] = timeout
            return FakeResponse({"success": True, "data": {"license_key": "RANDY-1234", "duration_days": 31}})

        client = ZentryClient("https://api.zentryauth.com", "seller", "secret", opener=opener)
        self.assertEqual(client.create_license(31, "RANDY"), "RANDY-1234")
        self.assertEqual(captured["payload"]["duration_value"], 31)
        self.assertEqual(captured["payload"]["duration_type"], "days")
        self.assertEqual(captured["headers"]["X-seller-key"], "seller")
        self.assertEqual(captured["headers"]["X-seller-secret"], "secret")

    def test_not_configured_never_calls_network(self):
        client = ZentryClient("https://api.zentryauth.com", "", "")
        with self.assertRaisesRegex(ZentryError, "ZENTRY_SELLER_KEY"):
            client.create_license(30)

    def test_http_error_returns_safe_api_message(self):
        def opener(_request, timeout):
            raise urllib.error.HTTPError(
                "https://api.zentryauth.com", 401, "Unauthorized", {},
                io.BytesIO(b'{"success":false,"code":"INVALID_SELLER_KEY"}'),
            )

        client = ZentryClient("https://api.zentryauth.com", "seller", "secret", opener=opener)
        with self.assertRaisesRegex(ZentryError, "INVALID_SELLER_KEY"):
            client.reset_hwid("KEY")

    def test_pasted_credentials_are_compacted_before_headers(self):
        captured = {}

        def opener(request, timeout):
            captured["headers"] = dict(request.header_items())
            return FakeResponse({"success": True, "data": {"license_key": "RANDY-OK", "duration_days": 31}})

        client = ZentryClient(
            "https://api.zentryauth.com",
            "  seller-key\n",
            "seller-secret\nwrapped  ",
            opener=opener,
        )
        self.assertEqual(client.create_license(31), "RANDY-OK")
        self.assertEqual(captured["headers"]["X-seller-key"], "seller-key")
        self.assertEqual(captured["headers"]["X-seller-secret"], "seller-secretwrapped")

    def test_create_license_accepts_nested_key_response(self):
        client = ZentryClient(
            "https://api.zentryauth.com", "seller", "secret",
            opener=lambda _request, timeout: FakeResponse({
                "success": True, "data": {"license": {"key": "RANDY-NESTED", "duration_days": 31}}
            }),
        )
        self.assertEqual(client.create_license(31), "RANDY-NESTED")

    def test_create_license_accepts_camel_case_response(self):
        client = ZentryClient(
            "https://api.zentryauth.com", "seller", "secret",
            opener=lambda _request, timeout: FakeResponse({
                "success": True, "result": {"licenseKey": "RANDY-CAMEL", "duration_days": 31}
            }),
        )
        self.assertEqual(client.create_license(31), "RANDY-CAMEL")

    def test_create_license_accepts_string_data_response(self):
        client = ZentryClient(
            "https://api.zentryauth.com", "seller", "secret",
            opener=lambda _request, timeout: FakeResponse({"success": True, "data": "RANDY-DIRECT", "duration_days": 31}),
        )
        self.assertEqual(client.create_license(31), "RANDY-DIRECT")


if __name__ == "__main__":
    unittest.main()
