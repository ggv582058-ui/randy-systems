import asyncio
import io
import os
import plistlib
import threading
import unittest
import zipfile
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from health import BotHTTPServer, HealthHandler
import certificate_experience  # noqa: F401 - activates the bot's production delivery flow
import certificate_reliability  # noqa: F401 - installs the production webhook wrapper


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

    def test_esign_import_requires_secret_and_validates_source(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Payload/ESign.app/Info.plist", plistlib.dumps({
                "CFBundleIdentifier": "p3.xyz.yyyue.esign", "CFBundleShortVersionString": "5.0.2",
                "CFBundleExecutable": "ESign",
            }))
            z.writestr("Payload/ESign.app/ESign", os.urandom(1200))
        saved = []
        self.server.certificate_ipa_save = lambda *args: saved.append(args)
        with patch.dict(os.environ, {"IPA_IMPORT_SECRET": "a" * 64}):
            url = self.base + "/maintenance/import-esign"
            with self.assertRaises(HTTPError) as failure:
                urlopen(Request(url, data=archive.getvalue(), method="POST"))
            self.assertEqual(failure.exception.code, 404)
            request = Request(url, data=archive.getvalue(), method="POST",
                              headers={"X-IPA-Import-Secret": "a" * 64})
            with urlopen(request) as response:
                self.assertEqual(response.status, 200)
        self.assertEqual(saved[0][0], "esign")
        self.assertEqual(saved[0][2:], ("p3.xyz.yyyue.esign", "5.0.2"))


if __name__ == "__main__":
    unittest.main()
