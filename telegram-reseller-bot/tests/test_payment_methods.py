import os
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST_TOKEN")
os.environ.setdefault("ADMIN_BOT_TOKEN", "456:TEST_TOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

import bot


class PaymentMethodTests(unittest.IsolatedAsyncioTestCase):
    async def test_menu_shows_payment_methods_before_amount(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        context = SimpleNamespace(user_data={})
        await bot.begin_topup(SimpleNamespace(effective_message=message), context)
        self.assertEqual(context.user_data["flow"]["name"], "topup_choose_method")
        labels = [row[0].text for row in message.reply_text.await_args.kwargs["reply_markup"].inline_keyboard]
        self.assertTrue(any("Cash App" in label for label in labels))
        self.assertTrue(any("PayPal" in label for label in labels))

    async def test_select_method_then_amount_shows_payment_card(self):
        message = SimpleNamespace(reply_text=AsyncMock(), reply_photo=AsyncMock(), text="25.00")
        query = SimpleNamespace(data="pay:method:cashapp", from_user=SimpleNamespace(id=2),
                                answer=AsyncMock(), message=message)
        context = SimpleNamespace(user_data={"flow": {"name": "topup_choose_method"}})
        configured = replace(bot.settings, cash_app_url="https://cash.app/$SampleAccount")
        with patch.object(bot, "settings", configured), \
             patch.object(bot, "current_user", return_value={"role": "reseller"}), \
             patch.object(bot, "panel", return_value="reseller"):
            await bot.callback(SimpleNamespace(callback_query=query), context)
            self.assertEqual(context.user_data["flow"]["name"], "topup_amount")
            await bot.handle_flow(SimpleNamespace(effective_message=message), context)
        self.assertEqual(context.user_data["flow"]["name"], "topup_method")
        self.assertIn("$25.00", message.reply_photo.await_args.kwargs["caption"])

    async def test_amount_requires_method_before_proof(self):
        message = SimpleNamespace(text="25.00", photo=None, document=None, reply_text=AsyncMock())
        update = SimpleNamespace(effective_message=message)
        context = SimpleNamespace(user_data={"flow": {"name": "topup_amount"}})
        with patch.object(bot.db, "create_topup") as create_topup:
            handled = await bot.handle_flow(update, context)
        self.assertTrue(handled)
        self.assertEqual(context.user_data["flow"]["name"], "topup_method")
        self.assertEqual(context.user_data["flow"]["amount_cents"], 2500)
        create_topup.assert_not_called()

    async def test_pending_method_cannot_advance_to_proof(self):
        query = SimpleNamespace(data="pay:method:paypal", from_user=SimpleNamespace(id=2),
                                answer=AsyncMock(), message=SimpleNamespace(reply_photo=AsyncMock(), reply_text=AsyncMock()))
        context = SimpleNamespace(user_data={"flow": {"name": "topup_method", "amount_cents": 2500}})
        with patch.object(bot, "current_user", return_value={"role": "reseller"}), \
             patch.object(bot, "panel", return_value="reseller"):
            await bot.callback(SimpleNamespace(callback_query=query), context)
        self.assertEqual(context.user_data["flow"]["name"], "topup_method")
        self.assertIsNone(context.user_data["flow"]["method"])
        self.assertIn("en proceso", query.message.reply_photo.await_args.kwargs["caption"])

    async def test_zelle_requires_selection_before_accepting_proof(self):
        query = SimpleNamespace(data="pay:proof", from_user=SimpleNamespace(id=2),
                                answer=AsyncMock(), message=SimpleNamespace(reply_text=AsyncMock()))
        context = SimpleNamespace(user_data={"flow": {"name": "topup_method", "amount_cents": 2500}})
        with patch.object(bot, "current_user", return_value={"role": "reseller"}), \
             patch.object(bot, "panel", return_value="reseller"):
            await bot.callback(SimpleNamespace(callback_query=query), context)
        self.assertEqual(context.user_data["flow"]["name"], "topup_method")
        query.message.reply_text.assert_not_awaited()

    async def test_cash_app_link_opens_payment_and_accepts_proof(self):
        query = SimpleNamespace(data="pay:method:cashapp", from_user=SimpleNamespace(id=2),
                                answer=AsyncMock(), message=SimpleNamespace(reply_photo=AsyncMock(), reply_text=AsyncMock()))
        context = SimpleNamespace(user_data={"flow": {"name": "topup_method", "amount_cents": 2500}})
        configured = replace(bot.settings, cash_app_url="https://cash.app/$SampleAccount")
        with patch.object(bot, "settings", configured), \
             patch.object(bot, "current_user", return_value={"role": "reseller"}), \
             patch.object(bot, "panel", return_value="reseller"):
            await bot.callback(SimpleNamespace(callback_query=query), context)
            buttons = query.message.reply_photo.await_args.kwargs["reply_markup"].inline_keyboard
            self.assertEqual(buttons[0][0].url, "https://cash.app/$SampleAccount")
            self.assertEqual(buttons[1][0].callback_data, "pay:proof")
            query.data = "pay:proof"
            await bot.callback(SimpleNamespace(callback_query=query), context)
        self.assertEqual(context.user_data["flow"]["name"], "topup_proof")

    def test_payment_link_rejects_other_hosts(self):
        with patch.object(bot, "settings", replace(bot.settings, paypal_url="https://paypal.me.bad.example/user")):
            self.assertFalse(bot.payment_ready("paypal"))


if __name__ == "__main__":
    unittest.main()
