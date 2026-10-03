import os
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
