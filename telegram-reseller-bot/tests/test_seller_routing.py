import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
os.environ.setdefault('TELEGRAM_BOT_TOKEN','123:TEST_TOKEN')
os.environ.setdefault('ADMIN_IDS','1')
from zentry_api import ZentryClient
from test_zentry_api import FakeResponse
import bot

class SellerRoutingTests(unittest.TestCase):
    def test_panel_base_and_legacy_config_route_to_same_seller_endpoint(self):
        for base in ('https://api.zentryauth.com','https://api.zentryauth.com/v1',
                     'https://api.zentryauth.com/seller/v1','https://zentryauth.com',
                     'https://zentryauth.com/api','https://zentryauth.com/api/seller/v1/',
                     'https://zentryauth.com/seller/v1'):
            with self.subTest(base=base):
                calls=[]
                def opener(request,timeout):
                    calls.append(request)
                    return FakeResponse({'success':True})
                client=ZentryClient(base,'test-seller','test-secret',opener=opener)
                client.reset_hwid('DEMO-KEY')
                self.assertEqual(calls[0].full_url,'https://zentryauth.com/api/seller/v1/licenses/reset')
                self.assertEqual(json.loads(calls[0].data),{'license_key':'DEMO-KEY'})
                self.assertEqual(calls[0].get_header('X-seller-key'),'test-seller')
                self.assertEqual(calls[0].get_header('X-seller-secret'),'test-secret')
    def test_create_info_ban_and_unban_share_the_panel_base(self):
        urls=[]
        def opener(request,timeout):
            urls.append(request.full_url)
            return FakeResponse({'success':True,'data':{'license_key':'DEMO-KEY','duration_days':7}})
        client=ZentryClient('https://zentryauth.com/api/seller/v1','test','test',opener=opener)
        self.assertEqual(client.create_license(7),'DEMO-KEY')
        client.ban_license('DEMO-KEY');client.unban_license('DEMO-KEY')
        self.assertEqual(urls,[f'https://zentryauth.com/api/seller/v1/licenses/{action}' for action in ('create','info','ban','unban')])
    def test_custom_api_hosts_preserve_explicit_configuration(self):
        calls=[]
        def opener(request,timeout):
            calls.append(request.full_url);return FakeResponse({'success':True})
        ZentryClient('https://custom.example/api','test','test',opener=opener).reset_hwid('DEMO')
        self.assertEqual(calls,['https://custom.example/api/seller/v1/licenses/reset'])

class ResetPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_and_vip_can_reset_in_each_bot_regular_cannot(self):
        for panel in ('admin','reseller'):
            for role,tier,allowed in (('admin','regular',True),('reseller','vip',True),('reseller','regular',False)):
                with self.subTest(panel=panel,role=role,tier=tier):
                    calls=[]
                    def opener(request,timeout):
                        calls.append(request.full_url);return FakeResponse({'success':True})
                    client=ZentryClient('https://zentryauth.com/api/seller/v1','test','test',opener=opener)
                    user={'telegram_id':1,'role':role,'tier':tier,'language':'es'}
                    msg=AsyncMock();update=SimpleNamespace(effective_user=SimpleNamespace(id=1),effective_message=msg)
                    ctx=SimpleNamespace(args=['DEMO-KEY'],application=SimpleNamespace(bot_data={'panel':panel}))
                    with patch.object(bot,'current_user',return_value=user),patch.object(bot.db,'user',return_value=user),patch.object(bot,'zentry',client):
                        await bot.run_key_command(update,ctx,'reset')
                    self.assertEqual(bool(calls),allowed)
                    self.assertIn('Reset HWID' if allowed else 'solo para Admin',msg.reply_text.call_args.args[0])
