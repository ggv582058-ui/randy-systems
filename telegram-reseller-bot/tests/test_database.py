import tempfile
import unittest
import sqlite3
from datetime import datetime, timedelta, timezone
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

    def test_edit_product_preserves_inventory_and_partner_price(self):
        self.db.add_keys(self.product, ["KEY-EXISTING"])
        self.db.set_reseller_price(2, self.product, 350)
        self.assertTrue(self.db.update_product(self.product, "name", "💎 Producto :D"))
        self.assertTrue(self.db.update_product(self.product, "price_cents", 700))
        self.assertEqual(self.db.product(self.product)["stock"], 1)
        row = self.db.product_for_user(self.product, 2)
        self.assertEqual(row["name"], "💎 Producto :D")
        self.assertEqual(row["effective_price_cents"], 350)

    def test_custom_emoji_and_photos_survive_database_restart(self):
        markup = 'Randy <tg-emoji emoji-id="12345">📍</tg-emoji> Mod'
        self.assertTrue(self.db.update_product_name(self.product, "Randy 📍 Mod", markup, "12345"))
        self.db.set_product_photo(self.product, b"photo-bytes")
        self.db.set_certificate_offer_photo(b"certificate-photo")
        reopened = Database(self.db.path)
        reopened.initialize()
        self.assertEqual(reopened.product(self.product)["name_html"], markup)
        self.assertEqual(reopened.product(self.product)["custom_emoji_id"], "12345")
        self.assertEqual(reopened.product_media(self.product)["photo_data"], b"photo-bytes")
        self.assertEqual(reopened.certificate_offer_photo(), b"certificate-photo")

    def test_daily_announcement_claims_once_and_survives_restart(self):
        self.db.set_daily_announcement("💎 Hola :D", "10:30")
        self.assertIsNone(self.db.claim_daily_announcement("2026-09-25", "10:29"))
        self.assertEqual(self.db.claim_daily_announcement("2026-09-25", "10:30"), "💎 Hola :D")
        self.assertIsNone(self.db.claim_daily_announcement("2026-09-25", "10:31"))
        restarted = Database(self.db.path)
        restarted.initialize()
        self.assertEqual(restarted.claim_daily_announcement("2026-09-26", "10:30"), "💎 Hola :D")
        restarted.pause_daily_announcement()
        self.assertIsNone(restarted.claim_daily_announcement("2026-09-27", "10:30"))

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

    def test_vip_partner_language_and_rank_persist(self):
        self.db.ensure_user(555, "vip", "VIP", False)
        self.db.create_partner("vipuser", "secret123", 500, "reseller", "vip")
        self.assertTrue(self.db.activate_partner("vipuser", "secret123", 555))
        self.assertEqual(self.db.user(555)["tier"], "vip")
        self.assertTrue(self.db.set_language(555, "en"))
        self.db.initialize()
        self.assertEqual(self.db.user(555)["tier"], "vip")
        self.assertEqual(self.db.user(555)["language"], "en")

    def test_regular_can_lookup_only_own_purchased_key(self):
        self.credit(1000)
        self.db.add_keys(self.product, ["OWN-KEY"])
        self.db.purchase(2, self.product)
        self.assertEqual(self.db.user_key(2, "own-key")["secret_value"], "OWN-KEY")
        self.assertIsNone(self.db.user_key(1, "OWN-KEY"))

    def test_initialize_creates_backup_without_losing_data(self):
        self.db.initialize()
        backups = list((Path(self.tmp.name) / "backups").glob("test-*.db"))
        self.assertTrue(backups)
        self.assertEqual(self.db.product(self.product)["name"], "Test Product")

    def test_legacy_users_are_migrated_without_deletion(self):
        path = Path(self.tmp.name) / "legacy.db"
        con = sqlite3.connect(path)
        con.execute(
            """CREATE TABLE users (telegram_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT NOT NULL,
               role TEXT NOT NULL DEFAULT 'pending', balance_cents INTEGER NOT NULL DEFAULT 0,
               requested_access INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
        )
        con.execute(
            "INSERT INTO users VALUES(?,?,?,?,?,?,?,?)",
            (99, "old", "Old User", "reseller", 1234, 0, "2026-01-01", "2026-01-01"),
        )
        con.commit()
        con.close()
        legacy = Database(path)
        legacy.initialize()
        user = legacy.user(99)
        self.assertEqual(user["balance_cents"], 1234)
        self.assertEqual(user["tier"], "regular")
        self.assertEqual(user["language"], "es")

    def test_certificate_key_charge_and_completion_are_atomic(self):
        self.credit(1000)
        issued = self.db.buy_certificate_key(2, "CERT-AAAA-BBBB-CCCC", 350)
        self.assertEqual(issued["balance_cents"], 650)
        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        order = self.db.create_certificate_order(
            2, issued["key_code"], 23, "00008110-001C0CAE2101801E", "iphone",
            "1", "Randy Test", "private-token", expires,
        )
        self.assertEqual(self.db.certificate_key(2, issued["key_code"])["status"], "processing")
        order = self.db.attach_provider_order(order["id"], {
            "order_code": "6XB32G", "status": "pending", "amount": 2.04,
        })
        completed = self.db.update_certificate_order("6XB32G", {
            "order_code": "6XB32G", "status": "completed",
            "download_url": "https://chungchi.store/storage/cert.zip",
        })
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(self.db.certificate_key(2, issued["key_code"])["status"], "used")

    def test_failed_certificate_order_releases_key_without_refunding_purchase(self):
        self.credit(1000)
        issued = self.db.buy_certificate_key(2, "CERT-DDDD-EEEE-FFFF", 350)
        expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        order = self.db.create_certificate_order(
            2, issued["key_code"], 23, "00008110-001C0CAE2101801E", "iphone",
            "1", "Retry", "retry-token", expires,
        )
        self.db.mark_certificate_error(order["id"], "invalid request", True)
        self.assertEqual(self.db.certificate_key(2, issued["key_code"])["status"], "available")
        self.assertEqual(self.db.user(2)["balance_cents"], 650)

    def test_completed_certificate_waits_for_download_and_extends_private_link(self):
        self.credit(1000)
        issued = self.db.buy_certificate_key(2, "CERT-LINK-READY-TEST", 350)
        old_expiry = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
        local = self.db.create_certificate_order(
            2, issued["key_code"], 23, "00008110-001C0CAE2101801E", "iphone",
            "1", "Randy Test", "private-token", old_expiry,
        )
        self.db.attach_provider_order(local["id"], {"order_code": "LATE-ZIP", "status": "pending"})
        incomplete = self.db.update_certificate_order("LATE-ZIP", {"status": "completed"})
        self.assertIsNone(incomplete["download_url"])
        self.assertGreater(datetime.fromisoformat(incomplete["install_expires_at"]),
                           datetime.now(timezone.utc) + timedelta(hours=23))
        self.assertIn(local["id"], [row["id"] for row in self.db.pending_certificate_orders()])
        ready = self.db.update_certificate_order("LATE-ZIP", {
            "status": "completed", "download_url": "https://chungchi.store/storage/cert.zip",
        })
        self.assertEqual(ready["status"], "completed")
        self.db.mark_certificate_delivered(local["id"])
        self.assertNotIn(local["id"], [row["id"] for row in self.db.pending_certificate_orders()])
        reopened = self.db.renew_certificate_link(local["id"], 2)
        self.assertGreater(datetime.fromisoformat(reopened["install_expires_at"]),
                           datetime.now(timezone.utc) + timedelta(hours=23))


if __name__ == "__main__":
    unittest.main()
