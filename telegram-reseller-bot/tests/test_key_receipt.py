import os
import unittest
from unittest.mock import patch
from unittest.mock import AsyncMock
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path
from database import Database

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST_TOKEN")
os.environ.setdefault("ADMIN_BOT_TOKEN", "456:TEST_TOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

import bot


class KeyReceiptTests(unittest.TestCase):
    def setUp(self):
        self.sale = {
            "product_name": "Randy Mod", "key": "ABCD-1234", "order_id": 17,
            "duration_days": 30, "expires_at": "2026-11-02T16:00:00+00:00",
            "balance_cents": 2500, "instructions": "Activa tu key en la app",
        }

    def test_default_receipt_keeps_copyable_key_and_order_details(self):
        with patch.object(bot.db, "private_setting", return_value=""):
            receipt = bot.key_receipt_text(self.sale)
        self.assertIn("<code>ABCD-1234</code>", receipt)
        self.assertIn("Referencia: <code>#17</code>", receipt)
        self.assertIn("<b>🔑 Mis keys</b>", receipt)

    def test_custom_text_is_escaped_without_changing_purchase_data(self):
        values = {"key_receipt_title": "VIP <Randy>",
                  "key_receipt_footer": "Gracias <amigo> & disfruta"}
        with patch.object(bot.db, "private_setting", side_effect=lambda key: values.get(key, "")):
            receipt = bot.key_receipt_text(self.sale)
        self.assertIn("VIP &lt;Randy&gt;", receipt)
        self.assertIn("Gracias &lt;amigo&gt; &amp; disfruta", receipt)
        self.assertIn("<code>ABCD-1234</code>", receipt)

    def test_complete_template_preserves_custom_emoji_and_copyable_key(self):
        template = '<tg-emoji emoji-id="5319007286004299794">💎</tg-emoji> <b>{producto}</b>\nTu key: {key}\n{saldo}'
        with patch.object(bot.db, "private_setting", side_effect=lambda key: template if key == "key_receipt_template_html" else ""):
            receipt = bot.key_receipt_text(self.sale)
        self.assertIn('emoji-id="5319007286004299794"', receipt)
        self.assertIn('<b>Randy Mod</b>', receipt)
        self.assertIn('<code>ABCD-1234</code>', receipt)
        self.assertIn('$25.00', receipt)


class ReceiptEditorTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_telegram_edit_updates_saved_emoji_template(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory)/"test.db"); db.initialize()
            message = SimpleNamespace(text="💎 Mi título", text_html='<tg-emoji emoji-id="5319007286004299794">💎</tg-emoji> Mi título',
                                      chat_id=1,message_id=42,reply_text=AsyncMock())
            update = SimpleNamespace(effective_message=message,effective_user=SimpleNamespace(id=1),
                                     effective_chat=SimpleNamespace(id=1),edited_message=message)
            context = SimpleNamespace(user_data={})
            db.set_private_setting("key_receipt_source:title", "1:42")
            with patch.object(bot,"db",db), patch.object(bot,"current_user",return_value={"role":"admin"}), \
                 patch.object(bot,"panel",return_value="admin"), patch.object(bot,"is_admin",return_value=True):
                await bot.handle_text_menu(update,context)
            self.assertEqual(db.private_setting("key_receipt_title_html"),message.text_html)
            self.assertNotIn("flow",context.user_data)


if __name__ == "__main__":
    unittest.main()
