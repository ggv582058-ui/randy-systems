import io
import os
import unittest
import zipfile
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST_TOKEN")
os.environ.setdefault("ADMIN_BOT_TOKEN", "456:TEST_TOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

import bot
import certificate_experience as experience


class CertificateDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_orders_status_files_app_and_web_last(self):
        order = {
            "id": 41, "user_id": 123, "status": "completed", "download_url": "https://provider.test/private",
            "display_name": "Test User", "udid": "00008101-001C6D642268801E", "device": "iphone",
            "completed_at": "2026-09-27T12:00:00Z", "created_at": "2026-09-27T12:00:00Z",
            "p12_password": "secret", "plan_id": 9, "install_token": "private",
        }
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("key.p12", b"p12-content")
            z.writestr("profile.mobileprovision", b"profile-content")
        events = []
        client = AsyncMock()
        client.send_message.side_effect = lambda *a, **kw: events.append(("message", a, kw))
        client.send_media_group.side_effect = lambda *a, **kw: events.append(("documents", a, kw))
        client.send_photo.side_effect = lambda *a, **kw: events.append(("app", a, kw))
        with patch.object(bot.chungchi, "download", return_value=archive.getvalue()), \
             patch.object(bot.db, "certificate_logo", return_value=None), \
             patch.object(bot.db, "signed_certificate_app", return_value=None), \
             patch.object(bot.db, "mark_certificate_delivered") as marked, \
             patch.dict("os.environ", {"RENDER_EXTERNAL_URL": "https://example.test"}):
            await experience.deliver(client, order)

        self.assertEqual([item[0] for item in events], ["message", "documents", "message", "app"])
        self.assertIn("Garantía estimada", events[0][1][1])
        documents = events[1][1][1]
        self.assertEqual([item.caption for item in documents], ["Certificado P12", "MobileProvision"])
        self.assertIn("secret", events[2][1][1])
        buttons = events[3][2]["reply_markup"].inline_keyboard
        self.assertEqual(buttons[0][0].callback_data, "certapp:sign_gbox:41")
        self.assertEqual(buttons[1][0].callback_data, "certapp:import_gbox:41")
        self.assertIn("/certificate/install/private", buttons[-1][0].url)
        marked.assert_called_once_with(41)


if __name__ == "__main__":
    unittest.main()
