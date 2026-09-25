import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST_TOKEN")
os.environ.setdefault("ADMIN_BOT_TOKEN", "456:TEST_TOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

import bot


class CertificateMenuTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_waits_for_product_selection_before_sending_a_photo(self):
        message = SimpleNamespace(reply_text=AsyncMock(), reply_photo=AsyncMock())
        update = SimpleNamespace(effective_user=SimpleNamespace(id=2), effective_message=message)
        product = {"id": 17, "name": "Randy Mod", "effective_price_cents": 1500,
                   "stock": 3, "custom_emoji_id": None}
        with patch.object(bot.db, "products_for_user", return_value=[product]), \
             patch.object(bot.db, "product_media") as product_media:
            await bot.show_buy(update)
        message.reply_text.assert_awaited_once()
        message.reply_photo.assert_not_awaited()
        product_media.assert_not_called()
        button = message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.callback_data, "buy:17")

    def test_randy_cover_is_packaged_for_default_offers(self):
        cover = bot.randy_cover()
        self.assertGreater(len(cover), 1000)
        self.assertTrue(cover.startswith(b"\xff\xd8\xff"))
        self.assertEqual(bot.product_cover({"name": "Randy 📍 Mod"}, None)[0], cover)

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
