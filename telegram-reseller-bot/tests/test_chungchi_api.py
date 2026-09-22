import io
import json
import unittest
import urllib.error

from chungchi_api import ChungChiClient, ChungChiError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode()


class ChungChiClientTests(unittest.TestCase):
    def test_create_order_uses_bearer_and_required_fields(self):
        captured = {}

        def opener(request, timeout):
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data)
            return FakeResponse({"data": {"order": {"order_code": "ABC123", "status": "pending"}}})

        client = ChungChiClient("https://chungchi.store", " secret\n", opener=opener)
        order = client.create_order(23, "00008110-001C0CAE2101801E", "iphone", "1")
        self.assertEqual(order["order_code"], "ABC123")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(captured["payload"]["plan_id"], 23)

    def test_insufficient_balance_has_safe_error(self):
        def opener(_request, timeout):
            raise urllib.error.HTTPError(
                "https://chungchi.store/api/v1/orders", 402, "Payment Required", {},
                io.BytesIO(b'{"error":{"code":"INSUFFICIENT_BALANCE","message":"Insufficient balance."}}'),
            )

        client = ChungChiClient("https://chungchi.store", "secret", opener=opener)
        with self.assertRaises(ChungChiError) as caught:
            client.create_order(23, "00008110-001C0CAE2101801E", "iphone", "1")
        self.assertEqual(caught.exception.status, 402)
        self.assertEqual(caught.exception.code, "INSUFFICIENT_BALANCE")

    def test_download_rejects_foreign_host(self):
        client = ChungChiClient("https://chungchi.store", "secret")
        with self.assertRaisesRegex(ChungChiError, "no válido"):
            client.download("https://evil.example/certificate.zip")


if __name__ == "__main__":
    unittest.main()
