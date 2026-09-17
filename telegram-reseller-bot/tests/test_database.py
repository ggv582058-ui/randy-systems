import tempfile
import unittest
from pathlib import Path

from database import Database, InsufficientBalance, OutOfStock


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


if __name__ == "__main__":
    unittest.main()
