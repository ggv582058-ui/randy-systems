from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telegram import Update


log = logging.getLogger("randy-webhook")


class BotHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, event_loop: asyncio.AbstractEventLoop):
        super().__init__(address, handler)
        self.event_loop = event_loop
        self.applications = {}
        self.secrets = {}

    def configure(self, applications: dict, secrets: dict[str, str]) -> None:
        self.applications = applications
        self.secrets = secrets


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/health"):
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"status": "ok", "service": "randy-reseller-bot"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        server: BotHTTPServer = self.server
        app = server.applications.get(self.path)
        secret = server.secrets.get(self.path)
        supplied = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if app is None or secret is None:
            self.send_error(404)
            return
        if not hmac.compare_digest(supplied, secret):
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Tamaño de actualización inválido")
            payload = json.loads(self.rfile.read(length))
            update = Update.de_json(payload, app.bot)
            future = asyncio.run_coroutine_threadsafe(app.process_update(update), server.event_loop)
            future.result(timeout=20)
        except Exception as exc:
            log.exception("No se pudo procesar el webhook: %s", exc)
            self.send_error(500)
            return
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


def start_health_server(event_loop: asyncio.AbstractEventLoop) -> BotHTTPServer:
    port = int(os.getenv("PORT", "10000"))
    server = BotHTTPServer(("0.0.0.0", port), HealthHandler, event_loop)
    thread = threading.Thread(target=server.serve_forever, name="health-server", daemon=True)
    thread.start()
    return server
