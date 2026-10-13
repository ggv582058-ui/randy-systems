import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
os.environ.setdefault('TELEGRAM_BOT_TOKEN','123:TEST_TOKEN')
os.environ.setdefault('ADMIN_IDS','1')
import bot
import certificate_experience
from database import Database
from zentry_api import ZentryError

class ManualStockTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(Path(self.tmp.name)/'store.db');self.db.initialize()
        self.db.ensure_user(1,'owner','Owner',True)
        self.db.ensure_user(2,'buyer','Buyer',False);self.db.set_role(2,'reseller')
        self.product=self.db.create_product('PC product',100,duration_days=7)
        self.db.add_keys(self.product,['DEMO-PC-KEY'])
        topup=self.db.create_topup(2,500,'text','proof');self.db.approve_topup(topup,1)
    def tearDown(self):self.tmp.cleanup()
    async def call(self,data,uid=1,panel='admin',client=None):
        query=AsyncMock();query.data=data;query.from_user.id=uid
        update=SimpleNamespace(callback_query=query,effective_user=SimpleNamespace(id=uid))
        context=SimpleNamespace(application=SimpleNamespace(bot_data={'panel':panel}),user_data={})
        client=client or MagicMock(configured=True)
        with patch.object(bot,'db',self.db),patch.object(bot,'current_user',return_value=self.db.user(uid)),\
             patch.object(bot,'zentry',client),patch.object(bot,'reply_with_icons',new_callable=AsyncMock) as receipt,\
             patch.object(bot,'notify_key_api',new_callable=AsyncMock):
            await certificate_experience._original_callback(update,context)
        return query,receipt,client
    async def test_admin_selects_manual_and_setting_survives_restart(self):
        q,_,_=await self.call(f'product:keymode:{self.product}:manual')
        self.assertEqual(Database(self.db.path).private_setting(f'product_key_mode:{self.product}'),'manual')
        self.assertIn('Stock manual',q.message.reply_text.call_args.args[0])
        self.assertEqual(q.message.reply_text.call_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data,f'addkeys:{self.product}')
    async def test_manual_purchase_delivers_and_charges_once_without_api(self):
        self.db.set_private_setting(f'product_key_mode:{self.product}','manual')
        q,receipt,client=await self.call(f'confirm:{self.product}',2,'reseller')
        client.verify_license_duration.assert_not_called();receipt.assert_awaited_once()
        self.assertEqual(self.db.user(2)['balance_cents'],400);self.assertEqual(self.db.product(self.product)['stock'],0)
        self.assertIn('DEMO-PC-KEY',receipt.call_args.args[1])
        await self.call(f'confirm:{self.product}',2,'reseller')
        self.assertEqual(self.db.user(2)['balance_cents'],400)
    async def test_api_mode_still_blocks_bad_duration_and_never_charges(self):
        client=MagicMock(configured=True);client.verify_license_duration.side_effect=ZentryError('wrong duration')
        q,receipt,client=await self.call(f'confirm:{self.product}',2,'reseller',client)
        receipt.assert_not_awaited();client.verify_license_duration.assert_called_once_with('DEMO-PC-KEY',7)
        self.assertEqual(self.db.user(2)['balance_cents'],500);self.assertEqual(self.db.product(self.product)['stock'],1)
    async def test_mode_cannot_be_changed_from_public_bot_or_by_reseller(self):
        for uid,panel in ((1,'reseller'),(2,'admin')):
            await self.call(f'product:keymode:{self.product}:manual',uid,panel)
            self.assertFalse(self.db.private_setting(f'product_key_mode:{self.product}'))
    async def test_return_to_api_and_invalid_mode_or_product(self):
        self.db.set_private_setting(f'product_key_mode:{self.product}','manual')
        await self.call(f'product:keymode:{self.product}:api')
        self.assertEqual(self.db.private_setting(f'product_key_mode:{self.product}'),'api')
        await self.call(f'product:keymode:{self.product}:other')
        self.assertEqual(self.db.private_setting(f'product_key_mode:{self.product}'),'api')
        await self.call('product:keymode:999:manual')
        self.assertFalse(self.db.private_setting('product_key_mode:999'))
