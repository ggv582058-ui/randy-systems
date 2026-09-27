import io
import plistlib
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app_signing import SigningError, ipa_info, profile_info
from database import Database
from pathlib import Path
from tempfile import TemporaryDirectory


def sample_ipa(bundle_id="com.example.test"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("Payload/Test.app/Info.plist", plistlib.dumps({
            "CFBundleIdentifier": bundle_id, "CFBundleShortVersionString": "1.0",
            "CFBundleExecutable": "Test",
        }))
        archive.writestr("Payload/Test.app/Test", b"test" * 300)
    return output.getvalue()


class AppSigningTests(unittest.TestCase):
    def test_ipa_structure_without_explicit_directory_entries(self):
        self.assertEqual(ipa_info(sample_ipa()), ("com.example.test", "1.0"))

    def test_refuse_unsafe_archive_path(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("Payload/../../escaped", b"unsafe")
            archive.writestr("Payload/Test.app/Info.plist", b"x" * 1024)
        with self.assertRaisesRegex(SigningError, "rutas inseguras"):
            ipa_info(data.getvalue())

    def test_new_ipa_replaces_previous_signatures(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "bot.db")
            db.initialize()
            db.set_certificate_ipa("esign", sample_ipa(), "com.example.test", "1.0")
            self.assertEqual(db.certificate_ipa("esign")["bundle_id"], "com.example.test")
            db.set_certificate_ipa("esign", sample_ipa("com.example.next"), "com.example.next", "1.0")
            restarted = Database(db.path)
            restarted.initialize()
            self.assertEqual(restarted.certificate_ipa("esign")["bundle_id"], "com.example.next")

    def test_profile_rejects_expired_and_other_devices(self):
        def decoded(expiration, devices):
            raw = plistlib.dumps({"ExpirationDate": expiration,
                                  "Entitlements": {"application-identifier": "TEAM.com.example.test"},
                                  "ProvisionedDevices": devices})
            return SimpleNamespace(returncode=0, stdout=raw)
        future = datetime.now(timezone.utc) + timedelta(days=10)
        with patch("app_signing.subprocess.run", return_value=decoded(future, ["OTHER"])):
            with self.assertRaisesRegex(SigningError, "UDID"):
                profile_info(b"profile", "MINE", "com.example.test")
        with patch("app_signing.subprocess.run", return_value=decoded(future - timedelta(days=11), ["MINE"])):
            with self.assertRaisesRegex(SigningError, "venció"):
                profile_info(b"profile", "MINE", "com.example.test")
        with patch("app_signing.subprocess.run", return_value=decoded(future, ["MINE"])):
            self.assertEqual(profile_info(b"profile", "MINE", "com.example.test"), "com.example.test")


if __name__ == "__main__":
    unittest.main()
