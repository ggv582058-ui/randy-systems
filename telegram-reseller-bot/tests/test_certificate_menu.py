import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST_TOKEN")
os.environ.setdefault("ADMIN_BOT_TOKEN", "456:TEST_TOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

import bot


class CertificateMenuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reply = AsyncMock()
        self.context = SimpleNamespace(user_data={"flow": {"name": "certificate_udid"},
                                                  "certificate_pending": {"key": "old"}})
        self.update = SimpleNamespace(
            effective_user=SimpleNamespace(id=2),
            effective_message=SimpleNamespace(text="👋 Welcome!", reply_text=self.reply),
        )
        self.user = {"role": "reseller", "language": "es"}

    async def test_welcome_works_during_udid_prompt_and_clears_old_input(self):
        with patch.object(bot, "current_user", return_value=self.user), \
             patch.object(bot, "panel", return_value="reseller"):
            await bot.handle_text_menu(self.update, self.context)

        message = self.reply.await_args.args[0]
        self.assertIn("Bienvenido a Randy Certificates", message)
        self.assertIn("Certificado iOS", message)
        self.assertNotIn("flow", self.context.user_data)
        self.assertNotIn("certificate_pending", self.context.user_data)
        self.assertEqual(self.reply.await_args.kwargs["reply_markup"], bot.CERTIFICATE_MENU)

    async def test_check_udid_switches_away_from_key_prompt(self):
        self.update.effective_message.text = "🔍 Check UDID"
        with patch.object(bot, "current_user", return_value=self.user), \
             patch.object(bot, "panel", return_value="reseller"):
            await bot.handle_text_menu(self.update, self.context)

        self.assertEqual(self.context.user_data["flow"], {"name": "certificate_lookup_udid"})
        self.assertNotIn("certificate_pending", self.context.user_data)
        self.assertIn("Envía el UDID", self.reply.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
