import io
import os
import unittest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:TEST_TOKEN")
os.environ.setdefault("ADMIN_BOT_TOKEN", "456:TEST_TOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

from PIL import Image
import bot
from certificate_card import purchase_offer_card


class CertificateOfferCardTests(unittest.TestCase):
    def test_card_renders_and_uses_customer_price(self):
        a = purchase_offer_card(None, "$3.50", "12 meses")
        b = purchase_offer_card(None, "$2.19", "12 meses")
        self.assertNotEqual(a, b)
        with Image.open(io.BytesIO(a)) as image:
            self.assertEqual(image.size, (960, 1090))

    def test_purchase_actions_and_caption(self):
        buttons = bot.certificate_purchase_buttons().inline_keyboard
        self.assertEqual(buttons[0][0].callback_data, "cert:confirm")
        self.assertEqual(buttons[1][0].callback_data, "cancel")
        self.assertEqual(buttons[0][0].style, "success")
        self.assertEqual(buttons[1][0].style, "danger")
        caption = bot.certificate_purchase_caption(219, "12 meses")
        self.assertIn("$2.19", caption)
        self.assertIn("50 días", caption)
        self.assertIn("GBox", caption)
