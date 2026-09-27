import asyncio
import os
import plistlib
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from health import BotHTTPServer, HealthHandler
import certificate_experience  # noqa: F401 - activates the bot's production delivery flow


class InstallManifestTests(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.server = BotHTTPServer(("127.0.0.1", 0), HealthHandler, self.loop)
        self.server.certificate_lookup = lambda token: {"id": 9, "status": "completed"} if token == "private" else None
        self.server.certificate_signed_lookup = lambda order_id, kind: {
            "ipa": b"IPA-TEST", "bundle_id": "com.example.esign", "version": "5.0.2"
        } if order_id == 9 and kind == "esign" else None
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
        self.loop.close()

    def test_private_manifest_points_to_private_signed_ipa(self):
        with patch.dict(os.environ, {"RENDER_EXTERNAL_URL": "https://example.test"}):
            with urlopen(self.base + "/certificate/manifest/private/esign.plist") as response:
                manifest = plistlib.loads(response.read())
        self.assertEqual(manifest["items"][0]["assets"][0]["url"],
                         "https://example.test/certificate/app/private/esign.ipa")
        with urlopen(self.base + "/certificate/app/private/esign.ipa") as response:
            self.assertEqual(response.read(), b"IPA-TEST")
        for path in ("/certificate/app/other/esign.ipa", "/certificate/app/private/gbox.ipa"):
            with self.assertRaises(HTTPError) as failure:
                urlopen(self.base + path)
            self.assertEqual(failure.exception.code, 404)

    def test_private_page_shows_install_button_after_signing(self):
        self.server.certificate_lookup = lambda token: {
            "id": 9, "status": "completed", "download_url": "private", "display_name": "Randy",
            "p12_password": "test", "udid": "00008101-001C6D642268801E", "device": "iPhone",
            "completed_at": "2026-09-27T12:00:00Z", "created_at": "2026-09-27T12:00:00Z",
            "plan_id": "one"
        } if token == "private" else None
        with patch.dict(os.environ, {"RENDER_EXTERNAL_URL": "https://example.test"}):
            with urlopen(self.base + "/certificate/install/private?app=esign") as response:
                page = response.read().decode()
        self.assertIn("Instalar ESign", page)
        self.assertIn("itms-services://", page)
        self.assertLess(page.index("Instalar ESign"), page.index("ARCHIVOS DEL CERTIFICADO"))
        self.assertIn('/certificate/logo/private/esign', page)


if __name__ == "__main__":
    unittest.main()
