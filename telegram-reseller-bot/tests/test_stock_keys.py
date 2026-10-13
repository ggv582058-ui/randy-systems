import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from database import Database
from stock_keys import StockKeys

class StockKeyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Database(Path(self.temp.name)/'db');self.db.initialize()
        self.db.ensure_user(1,'owner','Owner',True)
        self.pid=self.db.create_product('Demo',100);self.db.add_keys(self.pid,['AVAILABLE','SOLD'])
        with self.db.transaction() as con:
            con.execute("UPDATE inventory_keys SET status='sold' WHERE secret_value='SOLD'")
        self.handler=StockKeys(self.db)
    def tearDown(self):self.temp.cleanup()
    async def call(self,keyid,panel='admin',action='remove'):
        msg=AsyncMock();q=SimpleNamespace(data=f'stockkeys:{action}:{self.pid}:{keyid}:0',answer=AsyncMock(),message=msg)
        await self.handler.callback(SimpleNamespace(callback_query=q,effective_user=SimpleNamespace(id=1)),SimpleNamespace(application=SimpleNamespace(bot_data={'panel':panel})))
        return msg
    async def test_only_available_removed_and_repeated_click_safe(self):
        await self.call(1);await self.call(1);await self.call(2)
        with self.db.connect() as con:
            rows=con.execute('SELECT secret_value,status FROM inventory_keys').fetchall()
        self.assertEqual([(r['secret_value'],r['status']) for r in rows],[('SOLD','sold')])
    async def test_public_bot_cannot_remove(self):
        await self.call(1,'reseller')
        with self.db.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM inventory_keys').fetchone()[0],2)
    async def test_confirmation_does_not_remove(self):
        msg=await self.call(1,action='confirm')
        self.assertIn('Confirmar quitar',str(msg.reply_text.call_args))
        with self.db.connect() as con:self.assertEqual(con.execute('SELECT COUNT(*) FROM inventory_keys').fetchone()[0],2)
