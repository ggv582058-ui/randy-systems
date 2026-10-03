import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
os.environ.setdefault('TELEGRAM_BOT_TOKEN','123:TEST_TOKEN')
os.environ.setdefault('ADMIN_BOT_TOKEN','456:TEST_TOKEN')
os.environ.setdefault('ADMIN_IDS','1')
import bot

class UDIDReturnTests(unittest.IsolatedAsyncioTestCase):
    def test_entry_uses_miniapp_not_internal_browser_link(self):
        with patch.dict(os.environ,{'RENDER_EXTERNAL_URL':'https://example.test'}), patch.object(bot.db,'create_udid_session'):
            button=bot.udid_buttons(2).inline_keyboard[0][0]
        self.assertIsNone(button.url)
        self.assertTrue(button.web_app.url.startswith('https://example.test/udid/'))

    async def test_return_keeps_pending_registration_and_supplies_udid(self):
        message=SimpleNamespace(reply_text=AsyncMock())
        update=SimpleNamespace(effective_user=SimpleNamespace(id=2),effective_message=message)
        context=SimpleNamespace(args=['udid_private'], user_data={'flow':{'name':'certificate_udid','certificate_key':'CERT','device':'iphone'}})
        row={'user_id':2,'udid':'00008101-001C6D642268801E','model':'iPhone17,1'}
        with patch.object(bot.db,'udid_session',return_value=row):
            await bot.start(update,context)
        self.assertEqual(context.user_data['flow']['udid'],row['udid'])
        self.assertEqual(context.user_data['flow']['certificate_key'],'CERT')
        self.assertEqual(context.user_data['flow']['name'],'certificate_password')

    async def test_another_account_cannot_retrieve_private_result(self):
        message=SimpleNamespace(reply_text=AsyncMock())
        update=SimpleNamespace(effective_user=SimpleNamespace(id=3),effective_message=message)
        context=SimpleNamespace(user_data={})
        with patch.object(bot.db,'udid_session',return_value={'user_id':2,'udid':'secret'}):
            await bot.use_captured_udid(update,context,'private')
        self.assertNotIn('secret',message.reply_text.await_args.args[0])
