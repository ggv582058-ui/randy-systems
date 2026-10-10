import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from database import Database
from admin_records import AdminRecords, PAGE_SIZE, certificate_text, client_text

class RecordsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/'records.db');self.db.initialize()
        self.db.ensure_user(1,'owner','Owner',True)
        self.db.ensure_user(2,'seller','Seller',False);self.db.set_role(2,'reseller')
        self.db.ensure_user(3,'other','Other',False)
        topup=self.db.create_topup(2,10000,'text','proof');self.db.approve_topup(topup,1)
        self.db.buy_certificate_key(2,'CERT-TEST',350)
        self.order=self.db.create_certificate_order(2,'CERT-TEST',23,'DEMO-UDID','iphone','SECRET-PASSWORD','Alex <Client>','SECRET-TOKEN','2030-01-01T00:00:00+00:00')
        self.records=AdminRecords(self.db)
    def tearDown(self):self.tmp.cleanup()
    def update(self,uid=1,data='records:list:clients:0:all'):
        message=AsyncMock()
        return SimpleNamespace(effective_user=SimpleNamespace(id=uid),effective_message=message,
            callback_query=SimpleNamespace(data=data,message=message,answer=AsyncMock()))
    def context(self,panel='admin'):
        return SimpleNamespace(application=SimpleNamespace(bot_data={'panel':panel}),user_data={})
    def test_totals_and_certificate_details_do_not_duplicate_purchases(self):
        row=self.records.client(2)
        self.assertEqual(row['certificate_count'],1);self.assertEqual(row['certificate_key_count'],1)
        self.assertEqual(row['spent_cents'],350)
        text=certificate_text(self.records.certificate(self.order['id']))
        self.assertIn('Alex &lt;Client&gt;',text);self.assertNotIn('SECRET',text);self.assertIn('DEMO-UDID',text)
        self.assertEqual(len(self.records.rows('purchases',uid=2)),1);self.assertEqual(self.records.rows('purchases',uid=3),[])
        self.assertIn('$3.50',client_text(row))
    def test_search_and_pagination(self):
        for needle in ('Alex','@seller','2','DEMO-UDID'):
            self.assertEqual([r['telegram_id'] for r in self.records.rows('clients',search=needle)],[2])
            self.assertEqual([r['id'] for r in self.records.rows('certificates',search=needle)],[self.order['id']])
        self.assertEqual(self.records.rows('clients',search="' OR 1=1 --"),[])
        self.assertEqual(self.records.rows('clients',search='%'),[])
        for uid in range(10,30):self.db.ensure_user(uid,str(uid),'Person',False)
        first=self.records.rows('clients',page=0)[:PAGE_SIZE];second=self.records.rows('clients',page=1)[:PAGE_SIZE]
        self.assertFalse({r['telegram_id'] for r in first}&{r['telegram_id'] for r in second})
    async def test_private_access_for_every_entry_point(self):
        for uid,panel in ((1,'reseller'),(2,'admin'),(3,'admin')):
            update=self.update(uid);context=self.context(panel)
            self.assertTrue(await self.records.callback(update,context))
            update.callback_query.answer.assert_awaited_once_with('Solo Admin en el bot privado',show_alert=True)
            update.effective_message.reply_text.assert_not_awaited()
            self.assertTrue(await self.records.menu(update,context,'👤 Clientes'))
            self.assertIn('solo',update.effective_message.reply_text.call_args.args[0])
    async def test_customer_and_certificate_buttons_open_real_records(self):
        for data,needle in (('records:client:2','CLIENTE // RANDY MOD'),(f'records:certificate:{self.order["id"]}','CERTIFICADO // ADMIN')):
            update=self.update(data=data);self.assertTrue(await self.records.callback(update,self.context()))
            text=update.effective_message.reply_text.call_args.args[0];self.assertIn(needle,text);self.assertNotIn('SECRET',text)
    async def test_search_flow_and_reset(self):
        update=self.update(data='records:search:certificates');context=self.context()
        await self.records.callback(update,context);self.assertEqual(context.user_data['records_searching'],'certificates')
        await self.records.menu(update,context,'DEMO-UDID');self.assertNotIn('records_searching',context.user_data)
        self.assertIn('Alex &lt;Client&gt;',update.effective_message.reply_text.call_args.args[0])
        update.callback_query.data='records:clear:certificates';await self.records.callback(update,context)
        self.assertEqual(context.user_data['records_search'],{})
    async def test_invalid_and_missing_callback_records(self):
        for data in ('records:certificate:nope','records:client:999','records:list:clients:nope:all'):
            update=self.update(data=data);self.assertTrue(await self.records.callback(update,self.context()))
            self.assertGreater(update.callback_query.answer.await_count,0)

class MenuIntegrationTests(unittest.TestCase):
    def test_new_actions_keep_existing_emoji_slots_and_styled_navigation(self):
        import bot
        from typography import developer_text
        self.assertEqual(bot.menu_slot('admin',5,0),'admin_stats')
        self.assertEqual(bot.menu_slot('admin',5,1),'admin_language')
        for label,slot in (('👤 Clientes','admin_clients'),('🍎 Certificados','admin_certificates'),('📚 Compras','admin_purchases')):
            self.assertEqual(bot.canonical_menu_text(developer_text(label)),label)
            self.assertIn(slot,[bot.menu_slot('admin',r,c) for r,row in enumerate(bot.ADMIN_MENU.keyboard) for c,_ in enumerate(row)])
        markup=bot.admin_menu({'role':'admin','language':'es'})
        self.assertEqual(len(markup.keyboard),8)
