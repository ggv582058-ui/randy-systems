import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST_TOKEN")
os.environ.setdefault("ADMIN_BOT_TOKEN", "456:TEST_TOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

import bot


class PaymentMethodTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
