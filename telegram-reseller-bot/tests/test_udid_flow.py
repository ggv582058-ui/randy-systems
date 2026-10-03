import plistlib
import io
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock
import subprocess
import tempfile
import unittest
import asyncio
import os
import threading
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen
from urllib.error import HTTPError

from database import Database
from udid_flow import profile, device_response, UDIDService
from health import BotHTTPServer, HealthHandler


class UDIDTests(unittest.TestCase):
    def test_private_udid_page_and_profile_reject_unknown_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(Path(directory)/"data.db");db.initialize();db.ensure_user(2,"test","Test",False)
            db.create_udid_session("private",2)
            loop=asyncio.new_event_loop()
            server=BotHTTPServer(("127.0.0.1",0),HealthHandler,loop)
            server.udid_service=UDIDService(db,None,loop)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            try:
                with patch.dict(os.environ,{"RENDER_EXTERNAL_URL":"https://example.test"}):
                    with urlopen(base+"/udid/private") as response:
                        page=response.read().decode()
                    self.assertIn("Obtener mi UDID",page)
                    self.assertIn("/udid/profile/private",page)
                    self.assertIn("tg.openLink(",page)
                    self.assertIn("try_browser:'safari'",page)
                    self.assertIn('onclick="getProfile(event)"',page)
                    with urlopen(base+"/udid/profile/private") as response:
                        self.assertEqual(response.headers.get_content_type(),"application/x-apple-aspen-config")
                        self.assertIsNone(response.headers.get("Content-Disposition"))
                        self.assertEqual(plistlib.loads(response.read())["PayloadContent"]["Challenge"],"private")
                    db.complete_udid_session("private","00008101-001C6D642268801E","iPhone17,1")
                    with urlopen(base+"/udid/private") as response:
                        result=response.read().decode()
                    self.assertIn("tg://resolve?domain=XxResellerbot&start=udid_private",result)
                    self.assertIn("const captured=true",result)
                    self.assertIn("Continuar en Telegram",result)
                    with self.assertRaises(HTTPError) as failure:
                        urlopen(base+"/udid/unknown")
                    self.assertEqual(failure.exception.code,404)
            finally:
                server.shutdown();server.server_close();thread.join();loop.close()

    def test_profile_requests_only_udid_and_model_with_private_challenge(self):
        payload = plistlib.loads(profile("https://example.test", "private-token"))
        self.assertEqual(payload["PayloadType"], "Profile Service")
        self.assertEqual(payload["PayloadContent"]["DeviceAttributes"], ["UDID", "PRODUCT"])
        self.assertEqual(payload["PayloadContent"]["Challenge"], "private-token")
        self.assertEqual(payload["PayloadContent"]["URL"], "https://example.test/udid/callback/private-token")

    def test_signed_response_and_one_time_private_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(root/"key"),
                            "-out", str(root/"cert"), "-subj", "/CN=Test Device", "-days", "1"],
                           check=True, capture_output=True)
            value = "00008101-001C6D642268801E"
            signed = subprocess.run(["openssl", "cms", "-sign", "-binary", "-nodetach", "-outform", "DER",
                                     "-signer", str(root/"cert"), "-inkey", str(root/"key")],
                input=plistlib.dumps({"UDID":value,"PRODUCT":"iPhone17,1","CHALLENGE":"token"}),
                capture_output=True, check=True).stdout
            self.assertEqual(device_response(signed,"token"), (value,"iPhone17,1"))
            db=Database(root/"callback.db"); db.initialize(); db.ensure_user(2,"test","Test",False)
            db.create_udid_session("token",2)
            client=SimpleNamespace(send_message=AsyncMock(), username="XxResellerbot")
            service=UDIDService(db,client,None)
            handler=SimpleNamespace(headers={"Content-Length":str(len(signed))}, rfile=io.BytesIO(signed),
                send_response=MagicMock(),send_header=MagicMock(),end_headers=MagicMock(),send_error=MagicMock())
            with patch.dict(os.environ,{"RENDER_EXTERNAL_URL":"https://example.test"}), patch("udid_flow.asyncio.run_coroutine_threadsafe",side_effect=lambda coro,loop: asyncio.run(coro)):
                self.assertTrue(service.handle_post(handler,"/udid/callback/token"))
            handler.send_response.assert_called_once_with(301)
            handler.send_header.assert_any_call("Location","https://example.test/udid/token")
            self.assertEqual(client.send_message.await_count,1)
            button=client.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
            self.assertEqual(button.callback_data,"udid:use:token")
            self.assertEqual(db.udid_session("token")["udid"],value)

            with self.assertRaises(ValueError):
                device_response(signed,"other")
            with self.assertRaises(ValueError):
                device_response(b"bad response","token")
            db=Database(root/"data.db"); db.initialize(); db.ensure_user(2,"test","Test",False)
            db.create_udid_session("token",2)
            self.assertEqual(db.udid_session("token")["user_id"],2)
            self.assertTrue(db.complete_udid_session("token",value,"iPhone17,1"))
            self.assertFalse(db.complete_udid_session("token",value,"iPhone17,1"))
            with db.transaction() as con:
                con.execute("UPDATE udid_sessions SET expires_at='2020-01-01T00:00:00+00:00'")
            self.assertIsNone(db.udid_session("token"))
