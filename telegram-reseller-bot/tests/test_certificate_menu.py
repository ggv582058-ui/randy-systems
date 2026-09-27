import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST_TOKEN")
os.environ.setdefault("ADMIN_BOT_TOKEN", "456:TEST_TOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

import bot
import certificate_experience


class CertificateMenuTests(unittest.IsolatedAsyncioTestCase):
    def test_certificate_menu_starts_with_one_delivery_action(self):
        order = {"id": 7, "install_token": "private"}
        buttons = certificate_experience.delivery_menu(order).inline_keyboard
        names = " ".join(button.text for row in buttons for button in row)
        self.assertEqual(names, "Obtener certificado")
        self.assertNotIn("Feather", names)
        self.assertNotIn("Scarlet", names)
        self.assertNotIn("KSign", names)

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

    async def test_device_selection_precedes_udid_and_password(self):
        row = {"key_code": "CERT-TEST", "status": "available"}
        with patch.object(bot.db, "certificate_key", return_value=row):
            await bot.begin_certificate_key(self.update, self.context, "CERT-TEST")
        self.assertEqual(self.context.user_data["flow"]["name"], "certificate_device")
        buttons = self.reply.await_args.kwargs["reply_markup"].inline_keyboard[0]
        self.assertEqual([button.callback_data for button in buttons],
                         ["certdevice:iphone", "certdevice:ipad"])

        query = SimpleNamespace(data="certdevice:iphone", from_user=SimpleNamespace(id=2),
                                answer=AsyncMock(), edit_message_reply_markup=AsyncMock(),
                                message=SimpleNamespace(reply_text=self.reply))
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        with patch.object(bot, "current_user", return_value=self.user), \
             patch.object(bot, "panel", return_value="reseller"):
            await bot.callback(update, self.context)
        self.assertEqual(self.context.user_data["flow"]["name"], "certificate_udid")

        message = SimpleNamespace(text="00008120-001C41480C23601E",
                                  from_user=SimpleNamespace(id=2), reply_text=self.reply)
        with patch.object(bot, "current_user", return_value=self.user):
            await bot.handle_flow(SimpleNamespace(effective_message=message), self.context)
        self.assertEqual(self.context.user_data["flow"]["name"], "certificate_password")
        self.assertIn("Contraseña P12", self.reply.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
