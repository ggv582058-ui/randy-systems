from __future__ import annotations

import asyncio
import html
import hmac
import io
import json
import logging
import os
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from telegram import Update


log = logging.getLogger("randy-webhook")


class BotHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, event_loop: asyncio.AbstractEventLoop):
        super().__init__(address, handler)
        self.event_loop = event_loop
        self.applications = {}
        self.secrets = {}
        self.certificate_lookup = None
        self.certificate_download = None
        self.certificate_webhook = None

    def configure(self, applications: dict, secrets: dict[str, str]) -> None:
        self.applications = applications
        self.secrets = secrets

    def configure_certificates(self, lookup, download, webhook) -> None:
        self.certificate_lookup = lookup
        self.certificate_download = download
        self.certificate_webhook = webhook


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/certificate/install/"):
            self._certificate_page(path.rsplit("/", 1)[-1])
            return
        if path.startswith("/certificate/download/"):
            self._certificate_file(path.rsplit("/", 1)[-1])
            return
        if path.startswith("/certificate/component/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                self._certificate_component(parts[2], parts[3])
                return
        if path not in ("/", "/health"):
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"status": "ok", "service": "randy-reseller-bot"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _certificate_page(self, token: str) -> None:
        server: BotHTTPServer = self.server
        order = server.certificate_lookup(token) if server.certificate_lookup else None
        if not order:
            self.send_error(404, "Enlace inválido o expirado")
            return
        name = html.escape(order["display_name"])
        password = html.escape(order["p12_password"])
        password_js = json.dumps(order["p12_password"])
        token_safe = html.escape(token, quote=True)
        status = html.escape(order["status"])
        ready = order["status"] == "completed" and bool(order["download_url"])
        actions = (f"""
          <p class="step"><b>1.</b> Importa primero el certificado P12:</p>
          <button class="share-file" data-kind="p12">🔐 Compartir P12 con tu firmador</button>
          <p class="step"><b>2.</b> Después importa el perfil:</p>
          <button class="share-file" data-kind="mobileprovision">📱 Compartir MobileProvision</button>
          <a class="button secondary" href="/certificate/download/{token_safe}">⬇️ Descargar paquete ZIP</a>
          <button id="copy-password" class="secondary">🔐 Copiar contraseña</button>
        """ if ready else "<p class='waiting'>⏳ El certificado todavía se está preparando. Actualiza esta página en unos minutos.</p>")
        script = (f"""
        <script>
        async function shareFile(kind) {{
          const response = await fetch('/certificate/component/{token_safe}/' + kind);
          if (!response.ok) {{ alert('No encontré ese archivo dentro del paquete'); return; }}
          const blob = await response.blob();
          const extension = kind === 'p12' ? 'p12' : 'mobileprovision';
          const file = new File([blob], '{name}.' + extension, {{type:blob.type}});
          if (navigator.canShare && navigator.canShare({{files:[file]}})) {{
            await navigator.share({{files:[file], title:'Certificado {name}'}});
          }} else {{ window.location.href='/certificate/component/{token_safe}/' + kind; }}
        }}
        document.querySelectorAll('.share-file').forEach(button => {{
          button.addEventListener('click', () => shareFile(button.dataset.kind));
        }});
        document.getElementById('copy-password')?.addEventListener('click', async () => {{
          await navigator.clipboard.writeText({password_js});
        }});
        </script>
        """ if ready else "")
        body = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>Randy Certificates</title>
        <style>body{{margin:0;background:#070b17;color:#fff;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}
        main{{max-width:560px;margin:auto;padding:34px 20px}}.card{{background:#121a2c;border:1px solid #263452;border-radius:24px;padding:24px;box-shadow:0 20px 55px #0008}}
        h1{{color:#55a4ff}}.tag{{color:#9eb3d8}}code{{display:block;background:#080d19;padding:14px;border-radius:14px;overflow-wrap:anywhere}}
        button,.button{{box-sizing:border-box;display:block;width:100%;margin-top:12px;border:0;border-radius:15px;padding:15px;background:#1687ff;color:white;font-size:17px;font-weight:700;text-align:center;text-decoration:none}}
        .secondary{{background:#25334e}}.step{{margin:20px 0 4px;color:#c8d8f2}}.apps{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:22px}}.app{{background:#0b1120;border-radius:14px;padding:12px;text-align:center;color:#bcd2f5}}.waiting{{color:#ffd36b}}</style></head>
        <body><main><div class="card"><div class="tag">RANDY SYSTEMS · ENTREGA PRIVADA</div><h1>{name}</h1>
        <p>Estado: <b>{status}</b></p><p>Contraseña del P12:</p><code>{password}</code>{actions}
        <div class="apps"><div class="app">Feather</div><div class="app">GBox</div><div class="app">Scarlet</div><div class="app">Archivos</div></div>
        <p class="tag">Al abrirse la hoja de iPhone, selecciona Feather, GBox o Scarlet. Si no aparece, elige Guardar en Archivos y luego impórtalo desde la app.</p></div></main>{script}</body></html>""".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _certificate_file(self, token: str) -> None:
        server: BotHTTPServer = self.server
        order = server.certificate_lookup(token) if server.certificate_lookup else None
        if not order or order["status"] != "completed" or not order["download_url"]:
            self.send_error(404, "Certificado no disponible")
            return
        try:
            data = server.certificate_download(order)
        except Exception:
            log.exception("No se pudo descargar el certificado %s", order["id"])
            self.send_error(502, "No se pudo descargar el certificado")
            return
        filename = "".join(c for c in order["display_name"] if c.isalnum() or c in "-_ ").strip() or "certificate"
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}.zip"')
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _certificate_component(self, token: str, kind: str) -> None:
        extension = {"p12": ".p12", "mobileprovision": ".mobileprovision"}.get(kind)
        if not extension:
            self.send_error(404, "Archivo no válido")
            return
        server: BotHTTPServer = self.server
        order = server.certificate_lookup(token) if server.certificate_lookup else None
        if not order or order["status"] != "completed" or not order["download_url"]:
            self.send_error(404, "Certificado no disponible")
            return
        try:
            package = server.certificate_download(order)
            with zipfile.ZipFile(io.BytesIO(package)) as archive:
                matches = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(extension)]
                if not matches:
                    raise FileNotFoundError(extension)
                item = min(matches, key=lambda entry: len(entry.filename))
                if item.file_size > 10 * 1024 * 1024:
                    raise ValueError("Archivo demasiado grande")
                data = archive.read(item)
        except (zipfile.BadZipFile, FileNotFoundError, ValueError):
            self.send_error(404, "Archivo no encontrado en el paquete")
            return
        except Exception:
            log.exception("No se pudo extraer %s del certificado %s", kind, order["id"])
            self.send_error(502, "No se pudo preparar el archivo")
            return
        filename = "".join(c for c in order["display_name"] if c.isalnum() or c in "-_ ").strip() or "certificate"
        content_type = "application/x-pkcs12" if kind == "p12" else "application/x-apple-aspen-config"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}{extension}"')
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        server: BotHTTPServer = self.server
        path = urlsplit(self.path).path
        if path == "/chungchi/webhook":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1_000_000:
                    raise ValueError("Tamaño inválido")
                raw = self.rfile.read(length)
                if not server.certificate_webhook or not server.certificate_webhook(raw, self.headers):
                    self.send_error(401)
                    return
            except Exception:
                log.exception("Webhook ChungChi inválido")
                self.send_error(400)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"received":true}')
            return
        app = server.applications.get(path)
        secret = server.secrets.get(path)
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
