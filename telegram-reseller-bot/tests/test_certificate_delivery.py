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
    async def test_delivery_waits_for_get_certificate_then_offers_mini_app(self):
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

        self.assertEqual([item[0] for item in events], ["message"])
        self.assertIn("Garantía estimada", events[0][1][1])
        self.assertEqual(events[0][2]["reply_markup"].inline_keyboard[0][0].callback_data, "certapp:replay:41")
        with patch.object(bot.chungchi, "download", return_value=archive.getvalue()), \
             patch.object(bot.db, "certificate_logo", return_value=None), \
             patch.object(bot.db, "signed_certificate_app", return_value=None), \
             patch.dict("os.environ", {"RENDER_EXTERNAL_URL": "https://example.test"}):
            await experience.send_files(client, order)
            await experience.send_app_selector(client, order)
        self.assertEqual([item[0] for item in events], ["message", "documents", "message", "message"])
        self.assertEqual([item.caption for item in events[1][1][1]], ["P12 · Test User", "Perfil · Test User"])
        self.assertEqual([item.media.filename for item in events[1][1][1]],
                         ["Test User.p12", "Test User.mobileprovision"])
        self.assertTrue(all(item.thumbnail for item in events[1][1][1]))
        self.assertIn("secret", events[2][1][1])
        buttons = events[3][2]["reply_markup"].inline_keyboard
        self.assertEqual([button.callback_data for button in buttons[0]],
                         ["certapp:gbox:41", "certapp:esign:41"])
        self.assertIn("/certificate/install/private", buttons[-1][0].url)
        with patch.object(bot.db, "signed_certificate_app", return_value={"version": "6.1.2"}), \
             patch.dict("os.environ", {"RENDER_EXTERNAL_URL": "https://example.test"}):
            signed_buttons = experience.app_menu(order).inline_keyboard
        self.assertIn("/certificate/mini/private?app=gbox", signed_buttons[0][0].web_app.url)
        self.assertIn("✅ Estado", bot.certificate_status_text(order))
        self.assertIn("👤 Nombre", bot.certificate_status_text(order))
        self.assertNotIn("▯", bot.certificate_status_text(order))
        marked.assert_called_once_with(41)

    def test_emoji_ids_can_be_assigned_to_app_buttons(self):
        with patch.object(bot, "certificate_emoji", side_effect=lambda slot: "5319007286004299794" if slot == "gbox" else None):
            buttons = experience.app_selector_menu({"id": 41, "install_token": "private"}).inline_keyboard[0]
        self.assertEqual(buttons[0].icon_custom_emoji_id, "5319007286004299794")
        self.assertEqual(buttons[0].text, "GBox")
        self.assertEqual(buttons[1].text, "🔷 ESign")


if __name__ == "__main__":
    unittest.main()
