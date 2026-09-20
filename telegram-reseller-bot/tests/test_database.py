import tempfile
import unittest
from pathlib import Path

from database import Database, InsufficientBalance, OutOfStock, ProductRestricted


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.db.initialize()
        self.db.ensure_user(1, "admin", "Admin", True)
        self.db.ensure_user(2, "seller", "Seller", False)
        self.db.set_role(2, "reseller")
        self.product = self.db.create_product("Test Product", 500, "")

    def tearDown(self):
        self.tmp.cleanup()

    def credit(self, cents=1000):
        topup = self.db.create_topup(2, cents, "text", "proof")
        changed, _ = self.db.approve_topup(topup, 1)
        self.assertTrue(changed)

    def test_purchase_is_atomic_and_key_is_unique(self):
        self.credit()
        self.db.add_keys(self.product, ["ABC-123"])
        sale = self.db.purchase(2, self.product)
        self.assertEqual(sale["key"], "ABC-123")
        self.assertEqual(sale["balance_cents"], 500)
        with self.assertRaises(OutOfStock):
            self.db.purchase(2, self.product)

    def test_topup_approval_is_idempotent(self):
        topup = self.db.create_topup(2, 1200, "text", "proof")
        first, _ = self.db.approve_topup(topup, 1)
        second, _ = self.db.approve_topup(topup, 1)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(self.db.user(2)["balance_cents"], 1200)

    def test_insufficient_balance_does_not_consume_key(self):
        self.db.add_keys(self.product, ["SAFE-KEY"])
        with self.assertRaises(InsufficientBalance):
            self.db.purchase(2, self.product)
        self.assertEqual(self.db.product(self.product)["stock"], 1)

    def test_partner_credentials_bind_once(self):
        self.db.ensure_user(222, "socio", "Socio", False)
        self.db.create_partner("partner1", "secret123")
        self.assertFalse(self.db.activate_partner("partner1", "wrong", 222))
        self.assertTrue(self.db.activate_partner("partner1", "secret123", 222))
        self.db.ensure_user(333, "otro", "Otro", False)
        self.assertFalse(self.db.activate_partner("partner1", "secret123", 333))
        self.assertEqual(self.db.user(222)["role"], "reseller")

    def test_admin_balance_adjustment_and_special_price(self):
        self.assertEqual(self.db.adjust_balance(2, 3000, 1), 3000)
        self.db.set_reseller_price(2, self.product, 700)
        self.db.add_keys(self.product, ["SPECIAL-KEY"])
        sale = self.db.purchase(2, self.product)
        self.assertEqual(sale["price_cents"], 700)
        self.assertEqual(sale["balance_cents"], 2300)
        with self.assertRaises(InsufficientBalance):
            self.db.adjust_balance(2, -3000, 1)

    def test_product_file_bytes_are_returned_with_sale(self):
        self.credit(1000)
        self.db.add_keys(self.product, ["FILE-KEY"])
        self.db.set_product_file(self.product, "admin-only-file-id", "tool.zip", b"zip-content")
        sale = self.db.purchase(2, self.product)
        self.assertEqual(sale["file"]["file_name"], "tool.zip")
        self.assertEqual(sale["file"]["file_data"], b"zip-content")

    def test_purchase_tracks_duration_and_my_keys(self):
        timed = self.db.create_product("31 Days", 400, "", 31, "Activate it")
        self.credit(1000)
        self.db.add_keys(timed, ["TIME-KEY"])
        sale = self.db.purchase(2, timed)
        self.assertEqual(sale["duration_days"], 31)
        self.assertTrue(sale["expires_at"])
        keys = self.db.user_keys(2)
        self.assertEqual(keys[0]["secret_value"], "TIME-KEY")
        self.assertEqual(keys[0]["duration_days"], 31)

    def test_product_limit_blocks_purchase(self):
        self.credit(1000)
        self.db.add_keys(self.product, ["BLOCKED-KEY"])
        allowed = self.db.toggle_product_access(2, self.product)
        self.assertFalse(allowed)
        with self.assertRaises(ProductRestricted):
            self.db.purchase(2, self.product)
        self.assertEqual(self.db.product(self.product)["stock"], 1)

    def test_created_admin_role_and_initial_balance(self):
        self.db.ensure_user(444, "helper", "Helper", False)
        self.db.create_partner("helperadmin", "secret123", 2500, "admin")
        self.assertTrue(self.db.activate_partner("helperadmin", "secret123", 444))
        self.assertEqual(self.db.user(444)["role"], "admin")
        self.assertEqual(self.db.user(444)["balance_cents"], 2500)
        self.assertTrue(self.db.activate_partner("helperadmin", "secret123", 444))
        self.assertEqual(self.db.user(444)["balance_cents"], 2500)


if __name__ == "__main__":
    unittest.main()
