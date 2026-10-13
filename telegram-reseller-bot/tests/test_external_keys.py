import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
from database import Database,StoreError,NotApproved
from external_keys import ExternalKeys,api_expiry,status_text,parse_expiry
from zentry_api import ZentryError

class ExternalKeyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(Path(self.tmp.name)/'store.db');self.db.initialize()
        self.db.ensure_user(1,'owner','Owner',True)
        for uid in (2,3):self.db.ensure_user(uid,str(uid),'Client',False);self.db.set_role(uid,'reseller')
        self.client=MagicMock();self.client.license_info.return_value={'data':{'license_key':'DEMO-KEY','expires_at':'2026-10-21 05:03'}}
        self.registry=ExternalKeys(self.db,self.client)
    def tearDown(self):self.tmp.cleanup()
    def update(self,uid=1,data='extkey:add:2',text='DEMO-KEY | Randy Mod'):
        msg=AsyncMock();msg.text=text
        return SimpleNamespace(effective_user=SimpleNamespace(id=uid),effective_message=msg,
            callback_query=SimpleNamespace(data=data,message=msg,answer=AsyncMock()))
    def context(self,panel='admin'):return SimpleNamespace(application=SimpleNamespace(bot_data={'panel':panel}),user_data={})
    def link(self):return self.db.link_external_key(2,'DEMO-KEY','Randy Mod','2026-10-21T05:03:00+00:00','api',1)
    def test_registration_preserves_expiration_and_never_creates_purchase_or_charge(self):
        row=self.link();before=self.db.user(2)['balance_cents']
        with self.db.connect() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM orders').fetchone()[0],0)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM ledger').fetchone()[0],0)
        self.db.link_external_key(2,'demo-key','Randy Mod',row['expires_at'],'api',1)
        self.assertEqual(len(self.db.external_keys_for_user(2)),1)
        self.assertEqual(self.db.user(2)['balance_cents'],before)
        self.assertEqual(Database(self.db.path).external_key_by_value('DEMO-KEY',2)['expires_at'],row['expires_at'])
        self.assertIsNone(self.db.external_key_by_value('DEMO-KEY',3))
        text=status_text(row,now=datetime(2026,10,13,5,3,tzinfo=timezone.utc))
        self.assertIn('8 d · 0 h · 0 min',text)
    def test_duplicate_assignment_and_inventory_keys_are_rejected(self):
        self.link()
        with self.assertRaises(StoreError):self.db.link_external_key(3,'demo-key','Randy','2026-10-21T05:03:00+00:00','api',1)
        with self.assertRaises(NotApproved):self.db.link_external_key(2,'OTHER-KEY','Randy','2026-10-21T05:03:00+00:00','api',2)
        product=self.db.create_product('P',100);self.db.add_keys(product,['IN-STOCK'])
        with self.assertRaises(StoreError):self.db.link_external_key(2,'IN-STOCK','P','2026-10-21T05:03:00+00:00','api',1)
    def test_expired_and_timezone_dates(self):
        row=self.link();self.assertIn('Vencida',status_text(row,now=datetime(2026,10,22,tzinfo=timezone.utc)))
        self.assertEqual(parse_expiry('2026-10-21T01:03:00-04:00'),'2026-10-21T05:03:00+00:00')
    def test_api_requires_real_exact_expiry_and_matching_key(self):
        self.assertEqual(api_expiry(self.client.license_info.return_value,'DEMO-KEY'),'2026-10-21T05:03:00+00:00')
        for data in ({'duration_days':31},{'expires_at':'2026-10-21'},
                     {'key':'OTHER','expires_at':'2026-10-21 05:03'},
                     {'expires_at':'2026-10-21 05:03','data':{'expires_at':'2026-10-22 05:03'}}):
            with self.assertRaises(ValueError):api_expiry(data,'DEMO-KEY')
    async def test_admin_imports_api_key_into_selected_customer_history(self):
        update=self.update();context=self.context()
        await self.registry.callback(update,context)
        await self.registry.handle_text(update,context)
        row=self.db.external_key_by_value('DEMO-KEY',2)
        self.assertEqual(row['source'],'api');self.assertEqual(row['name'],'Randy Mod')
        self.assertNotIn('flow',context.user_data)
        self.client.license_info.assert_called_once_with('DEMO-KEY')
    async def test_manual_fallback_records_absolute_date_without_inventing_days(self):
        self.client.license_info.side_effect=ZentryError('unavailable')
        update=self.update();context=self.context();await self.registry.callback(update,context)
        await self.registry.handle_text(update,context)
        self.assertEqual(context.user_data['flow']['name'],'external_expiry')
        self.assertEqual(self.db.external_keys_for_user(2),[])
        update.effective_message.text='31';await self.registry.handle_text(update,context)
        self.assertEqual(self.db.external_keys_for_user(2),[])
        update.effective_message.text='2026-10-21 05:03 UTC';await self.registry.handle_text(update,context)
        row=self.db.external_keys_for_user(2)[0];self.assertEqual(row['source'],'admin')
        self.assertIn('registrado por Admin',status_text(row))
    async def test_import_is_private_admin_only(self):
        for uid,panel in ((1,'reseller'),(2,'admin'),(3,'admin')):
            update=self.update(uid);context=self.context(panel)
            await self.registry.callback(update,context)
            self.assertNotIn('flow',context.user_data)
            context.user_data['flow']={'name':'external_key','target':2}
            await self.registry.handle_text(update,context)
            self.client.license_info.assert_not_called()
        self.assertEqual(self.db.external_keys_for_user(2),[])
    async def test_customer_refresh_is_owner_scoped_and_keeps_old_date_on_api_error(self):
        row=self.link();update=self.update(3,f'extkey:refresh:{row["id"]}:2');context=self.context('reseller')
        await self.registry.callback(update,context);self.client.license_info.assert_not_called()
        update=self.update(2,f'extkey:refresh:{row["id"]}:2')
        self.client.license_info.side_effect=ZentryError('unavailable')
        await self.registry.callback(update,context)
        self.assertEqual(self.db.external_keys_for_user(2)[0]['expires_at'],row['expires_at'])
        self.assertIn('conserva',update.effective_message.reply_text.call_args_list[0].args[0])
        self.client.license_info.side_effect=None
        self.client.license_info.return_value={'data':{'key':'DEMO-KEY','expires_at':'2026-10-25 05:03'}}
        await self.registry.callback(update,context)
        self.assertEqual(self.db.external_keys_for_user(2)[0]['expires_at'],'2026-10-25T05:03:00+00:00')
    async def test_mis_keys_includes_external_license_without_a_bot_purchase(self):
        import os
        os.environ.setdefault('TELEGRAM_BOT_TOKEN','123:TEST_TOKEN');os.environ.setdefault('ADMIN_IDS','1')
        import bot
        from unittest.mock import patch
        self.link();update=self.update(2)
        with patch.object(bot,'db',self.db),patch.object(bot,'current_user',return_value=self.db.user(2)),patch.object(bot,'external_keys',self.registry):
            await bot.show_my_keys(update)
        self.assertIn('DEMO-KEY',update.effective_message.reply_text.call_args.args[0])
        self.assertIn('Tiempo restante',update.effective_message.reply_text.call_args.args[0])
        self.assertEqual(self.db.user_keys(2),[])
        self.client.license_info.assert_not_called()
