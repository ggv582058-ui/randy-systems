import json
import tempfile
import unittest
from pathlib import Path

from database import Database, StoreError
from zentry_api import ZentryClient, ZentryError


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self):
        return json.dumps(self.payload).encode()


class KeyDurationSafetyTests(unittest.TestCase):
    def client(self, info):
        requests = []
        def opener(request, timeout):
            requests.append(request.full_url)
            payload = {"data": {"license_key": "TEST-KEY", "duration": "7 days"}}
            return Response(info if request.full_url.endswith('/info') else payload)
        return ZentryClient('https://example.test', 'seller', 'secret', opener=opener), requests

    def test_seven_day_creation_rejects_actual_lifetime_despite_correct_create_label(self):
        client, requests = self.client({'data': {'duration': 'lifetime'}})
        with self.assertRaisesRegex(ZentryError, 'lifetime'):
            client.create_license(7)
        self.assertEqual(len(requests), 2)

    def test_thirty_one_days_rejects_one_year(self):
        client, _ = self.client({'data': {'duration_days': 365}})
        with self.assertRaisesRegex(ZentryError, '365 días'):
            client.verify_license_duration('TEST-KEY', 31)

    def test_valid_finite_plans(self):
        for days in (1, 5, 7, 30, 31, 365):
            with self.subTest(days=days):
                client, _ = self.client({'data': {'duration': f'{days} days'}})
                self.assertEqual(client.create_license(days), 'TEST-KEY')

    def test_missing_or_conflicting_duration_never_delivers(self):
        for info in ({'data': {'remaining_days': 7}},
                     {'data': {'duration_days': 7, 'is_lifetime': True}},
                     {'data': {'duration_days': 7, 'duration': '365 days'}},
                     {'data': {'license_key': 'ANOTHER', 'duration_days': 7}},
                     {'data': {'duration_days': True}},
                     {'data': {'duration': '1 year'}}):
            with self.subTest(info=info):
                client, _ = self.client(info)
                with self.assertRaises(ZentryError):
                    client.verify_license_duration('TEST-KEY', 7)

    def test_invalid_requested_duration_never_creates(self):
        client, requests = self.client({})
        for days in (0, -1, True, '7', 7.5):
            with self.assertRaises(ZentryError):
                client.create_license(days)
        self.assertEqual(requests, [])

    def test_unit_duration_and_seconds(self):
        for info in ({'data': {'duration_type': 'weeks', 'duration_value': 1}},
                     {'result': {'duration_seconds': 604800}}):
            client, _ = self.client(info)
            client.verify_license_duration('TEST-KEY', 7)

    def test_stock_or_duration_changes_do_not_charge_or_sell(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / 'store.db')
            db.initialize()
            db.ensure_user(1, 'owner', 'Owner', True)
            product = db.create_product('Randy Mod', 100, duration_days=7)
            db.add_keys(product, ['TEST-KEY'])
            topup = db.create_topup(1, 500, 'text', 'proof')
            db.approve_topup(topup, 1)
            candidate = db.purchase_candidate(product)
            before = db.user(1)['balance_cents']
            with self.assertRaises(StoreError):
                db.purchase(1, product, expected_key_id=candidate['id'] + 1, expected_duration_days=7)
            db.update_product(product, 'duration_days', 31)
            with self.assertRaises(StoreError):
                db.purchase(1, product, expected_key_id=candidate['id'], expected_duration_days=7)
            self.assertEqual(db.user(1)['balance_cents'], before)
            self.assertEqual(db.product(product)['stock'], 1)
            with db.connect() as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)

    def test_seven_days_rejects_twenty_five_weeks_from_reported_incident(self):
        for info in ({"data": {"duration": "25 weeks"}},
                     {"data": {"duration_type": "weeks", "duration_value": 25}}):
            with self.subTest(info=info):
                client, _ = self.client(info)
                with self.assertRaisesRegex(ZentryError, "175 días"):
                    client.verify_license_duration("TEST-KEY", 7)

