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
from datetime import datetime, timezone
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

    @staticmethod
    def _pretty_date(value: str | None) -> str:
        if not value:
            return "Pendiente"
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
        except Exception:
            return value

    @staticmethod
    def _warranty(order) -> str:
        base = order["completed_at"] or order["created_at"]
        if not base:
            return "30 días"
        try:
            created = datetime.fromisoformat(str(base).replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            seconds = max(0, int((created.timestamp() + 30 * 86400) - now.timestamp()))
            days, rem = divmod(seconds, 86400)
            hours, rem = divmod(rem, 3600)
            minutes = rem // 60
            return f"{days}d {hours}h {minutes}m"
        except Exception:
            return "30 días"

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
        status_raw = str(order["status"] or "processing")
        status_labels = {
            "completed": "Firmado",
            "processing": "Procesando",
            "submitting": "Registrando",
            "failed": "Revisión requerida",
        }
        status = html.escape(status_labels.get(status_raw, status_raw.title()))
        ready = status_raw == "completed" and bool(order["download_url"])
        udid = html.escape(str(order["udid"] or "Pendiente"))
        device = html.escape(str(order["device"] or "iPhone").replace("iphone", "iPhone").replace("ipad", "iPad"))
        registered = html.escape(self._pretty_date(order["completed_at"] or order["created_at"]))
        warranty = html.escape(self._warranty(order))
        plan = html.escape(f"Plan #{order['plan_id']}")

        actions = (f"""
          <div class="section-title">ARCHIVOS DEL CERTIFICADO</div>
          <button class="action share-file" data-kind="p12"><span>🔐</span><div><b>Compartir P12</b><small>Abrir con tu firmador</small></div><i>›</i></button>
          <button class="action share-file" data-kind="mobileprovision"><span>📲</span><div><b>Compartir MobileProvision</b><small>Perfil de aprovisionamiento</small></div><i>›</i></button>
          <a class="action" href="/certificate/download/{token_safe}"><span>📦</span><div><b>Descargar paquete ZIP</b><small>P12 + MobileProvision</small></div><i>↓</i></a>
          <button id="copy-password" class="action"><span>🔑</span><div><b>Copiar contraseña</b><small>Contraseña del archivo P12</small></div><i>⧉</i></button>
          <div class="section-title">ABRIR CON</div>
          <div class="apps">
            <button class="mini share-file" data-kind="p12">🟩<b>GBox</b></button>
            <button class="mini share-file" data-kind="p12">🪶<b>Feather</b></button>
            <button class="mini share-file" data-kind="p12">🔷<b>Esign</b></button>
            <button class="mini share-file" data-kind="p12">🅺<b>KSign</b></button>
            <button class="mini share-file" data-kind="p12">🔻<b>Scarlet</b></button>
          </div>
        """ if ready else """
          <div class="waiting"><div class="loader"></div><div><b>Preparando certificado</b><small>La página se actualizará cuando los archivos estén listos.</small></div></div>
        """)

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
          const el = document.getElementById('copy-password');
          el.classList.add('copied');
          setTimeout(() => el.classList.remove('copied'), 900);
        }});
        </script>
        """ if ready else "")

        music_data = "AAAAHGZ0eXBNNEEgAAACAE00QSBpc29taXNvMgAAAAhmcmVlAAALWG1kYXTeAgBMYXZjNjEuMTkuMTAxAEIgCMEYOCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHCEQBGCMHN4CAExhdmM2MS4xOS4xMDEAQiAIwRg4IRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcIRAEYIwcAAAKcm1vb3YAAABsbXZoZAAAAAAAAAAAAAAAAAAAA+gAACsdAAEAAAEAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAmddHJhawAAAFx0a2hkAAAAAwAAAAAAAAAAAAAAAQAAAAAAACsdAAAAAAAAAAAAAAABAQAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAJGVkdHMAAAAcZWxzdAAAAAAAAAABAAArHAAABAAAAQAAAAAJFW1kaWEAAAAgbWRoZAAAAAAAAAAAAAAAAAAArEQAB3E5VcQAAAAAADFoZGxyAAAAAAAAAABzb3VuAAAAAAAAAAAAAAAAQ29yZSBNZWRpYSBBdWRpbwAAAAi8bWluZgAAABBzbWhkAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJsIAAAAAEAAAiAc3RibAAAAGpzdHNkAAAAAAAAAAEAAABabXA0YQAAAAAAAAABAAAAAAAAAAAAAgAQAAAAAKxEAAAAAAA2ZXNkcwAAAAADgICAJQABAASAgIAXQBUAAAAAAfQAAAAILgWAgIAFEhBW5QAGgICAAQIAAAAgc3R0cwAAAAAAAAACAAAB3AAABAAAAAABAAABOQAAABxzdHNjAAAAAAAAAAEAAAABAAAB3QAAAAEAAAeIc3RzegAAAAAAAAAAAAAB3QAAABcAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAAAYAAAAGAAAABgAAABRzdGNvAAAAAAAAAAEAAAAsAAAAGnNncGQBAAAAcm9sbAAAAAIAAAAB//8AAAAcc2JncAAAAAByb2xsAAAAAQAAAd0AAAABAAAAYXVkdGEAAABZbWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAsaWxzdAAAACSpdG9vAAAAHGRhdGEAAAABAAAAAExhdmY2MS43LjEwMw=="

        body = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#071225"><title>Randy Certificates</title>
        <style>
        *{{box-sizing:border-box}}html{{min-height:100%;background:#030814}}body{{margin:0;min-height:100vh;color:#f8fbff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:radial-gradient(circle at 12% 8%,#0b4aa066,transparent 36%),radial-gradient(circle at 90% 22%,#006dff55,transparent 33%),linear-gradient(145deg,#020611,#071329 55%,#020814);overflow-x:hidden}}
        body:before,body:after{{content:"";position:fixed;width:320px;height:320px;border-radius:50%;filter:blur(90px);opacity:.32;pointer-events:none;animation:float 9s ease-in-out infinite alternate}}body:before{{background:#1687ff;top:-90px;left:-130px}}body:after{{background:#00d4ff;bottom:-120px;right:-140px;animation-delay:-4s}}@keyframes float{{to{{transform:translate3d(34px,42px,0) scale(1.16)}}}}
        main{{position:relative;z-index:1;max-width:620px;margin:auto;padding:24px 15px 44px}}.glass{{position:relative;overflow:hidden;background:linear-gradient(145deg,rgba(17,35,66,.72),rgba(4,12,28,.62));border:1px solid rgba(125,197,255,.28);border-radius:30px;padding:23px;box-shadow:0 28px 80px #000a,inset 0 1px 0 #ffffff24;backdrop-filter:blur(24px) saturate(135%);-webkit-backdrop-filter:blur(24px) saturate(135%)}}.glass:before{{content:"";position:absolute;inset:0;background:linear-gradient(115deg,#ffffff18,transparent 27%,transparent 68%,#1687ff15);pointer-events:none}}
        .brand{{font-size:12px;letter-spacing:2.5px;color:#a6c9f4;font-weight:800;text-transform:uppercase}}.hero{{margin:17px 0;padding:22px;border-radius:24px;background:linear-gradient(135deg,#0b3478cc,#06162acc);border:1px solid #59a9ff55;box-shadow:inset 0 1px 0 #fff2,0 15px 35px #00152e99}}.eyebrow{{font-size:12px;color:#84c4ff;letter-spacing:1.5px;font-weight:800}}h1{{font-size:34px;line-height:1.05;margin:8px 0 14px;background:linear-gradient(100deg,#fff,#9bd0ff 50%,#48a1ff);-webkit-background-clip:text;color:transparent}}.signed{{display:inline-flex;gap:8px;align-items:center;padding:8px 12px;border-radius:999px;background:#00c87516;border:1px solid #4dffad43;color:#9dffd0;font-weight:800;font-size:13px}}
        .grid{{display:grid;gap:10px;margin:15px 0 4px}}.info{{display:grid;grid-template-columns:42px 1fr;align-items:center;gap:10px;padding:13px 14px;border-radius:18px;background:#07162bb0;border:1px solid #82bbff20;box-shadow:inset 0 1px 0 #fff08}}.icon{{width:38px;height:38px;border-radius:13px;display:grid;place-items:center;background:linear-gradient(145deg,#0a54ad,#0b2046);border:1px solid #5cb2ff55;box-shadow:0 8px 20px #006dff25}}.info small{{display:block;color:#7ea1c9;font-size:11px;text-transform:uppercase;letter-spacing:1.3px;font-weight:700;margin-bottom:2px}}.info b{{font-size:15px;overflow-wrap:anywhere}}
        .password{{margin-top:13px;padding:14px 16px;border-radius:17px;background:#020916b8;border:1px solid #8dc8ff26}}.password small{{display:block;color:#83a8d3;font-size:11px;letter-spacing:1.2px;text-transform:uppercase;margin-bottom:5px}}code{{font-size:16px;color:#d8ecff;overflow-wrap:anywhere}}
        .section-title{{margin:23px 2px 10px;color:#7197c4;font-size:10px;font-weight:900;letter-spacing:1.8px}}button,.action{{font-family:inherit}}.action{{appearance:none;position:relative;display:grid;grid-template-columns:44px 1fr 26px;align-items:center;gap:10px;width:100%;margin-top:9px;border:1px solid #67b7ff33;border-radius:19px;padding:12px 14px;background:linear-gradient(145deg,#0d2b51b8,#07172eb8);color:#fff;text-align:left;text-decoration:none;box-shadow:inset 0 1px 0 #fff10;backdrop-filter:blur(12px)}}.action>span{{width:42px;height:42px;display:grid;place-items:center;border-radius:14px;background:#1687ff1f;border:1px solid #5aaeff35;font-size:20px}}.action b{{display:block;font-size:15px}}.action small{{display:block;color:#84a8d0;margin-top:3px;font-size:11px}}.action i{{font-style:normal;color:#78bfff;font-size:22px;text-align:center}}.action:active{{transform:scale(.985)}}.copied{{border-color:#66ffc4aa!important;background:#0e513e88!important}}
        .apps{{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}}.mini{{border:1px solid #72b9ff31;border-radius:18px;padding:14px 11px;background:#0a1b35b8;color:white;font-size:18px;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:inset 0 1px 0 #fff0d}}.mini:last-child{{grid-column:1/-1}}.mini b{{font-size:14px}}
        .waiting{{margin-top:20px;display:flex;align-items:center;gap:14px;padding:18px;border-radius:20px;background:#0b213fbb;border:1px solid #4ca7ff3d}}.waiting small{{display:block;color:#8db1d9;margin-top:4px}}.loader{{width:28px;height:28px;border-radius:50%;border:3px solid #1687ff33;border-top-color:#56b3ff;animation:spin .8s linear infinite}}@keyframes spin{{to{{transform:rotate(360deg)}}}}
        .music-pill{{position:fixed;z-index:8;right:15px;bottom:calc(16px + env(safe-area-inset-bottom));display:flex;align-items:center;gap:8px;padding:10px 13px;border:1px solid #8dccff4a;border-radius:999px;background:#071a31c7;color:#cfeaff;backdrop-filter:blur(18px);box-shadow:0 12px 30px #0008;font-size:12px;font-weight:800}}.music-dot{{width:8px;height:8px;border-radius:50%;background:#36a3ff;box-shadow:0 0 12px #36a3ff;animation:pulse 1.2s ease-in-out infinite alternate}}@keyframes pulse{{to{{opacity:.3;transform:scale(.65)}}}}
        .foot{{margin:18px 5px 0;color:#6388b2;font-size:11px;line-height:1.5;text-align:center}}@media(min-width:500px){{.grid{{grid-template-columns:1fr 1fr}}}}
        </style></head>
        <body><main><section class="glass"><div class="brand">RANDY SYSTEMS · ENTREGA PRIVADA</div>
        <div class="hero"><div class="eyebrow">CERTIFICADO DIGITAL</div><h1>{name}</h1><div class="signed">✓ {status}</div></div>
        <div class="grid">
          <div class="info"><div class="icon">🆔</div><div><small>UDID</small><b>{udid}</b></div></div>
          <div class="info"><div class="icon">📱</div><div><small>Dispositivo</small><b>{device}</b></div></div>
          <div class="info"><div class="icon">📅</div><div><small>Registrado</small><b>{registered}</b></div></div>
          <div class="info"><div class="icon">🛡️</div><div><small>Garantía</small><b>{warranty}</b></div></div>
          <div class="info"><div class="icon">⚡</div><div><small>Plan</small><b>{plan}</b></div></div>
          <div class="info"><div class="icon">🔵</div><div><small>Estado</small><b>{status}</b></div></div>
        </div>
        <div class="password"><small>Contraseña del P12</small><code>{password}</code></div>
        {actions}
        <div class="foot">Enlace privado generado por Randy Systems. No compartas este enlace con terceros.</div></section></main>
        <div class="music-pill" id="music-pill"><span class="music-dot"></span><span id="music-label">Música automática</span></div>
        <audio id="bg-music" autoplay loop playsinline preload="auto" src="data:audio/mp4;base64,{music_data}"></audio>
        {script}
        <script>
        (() => {{
          const audio = document.getElementById('bg-music');
          const label = document.getElementById('music-label');
          const tryPlay = () => audio.play().then(() => label.textContent='Música activa').catch(() => label.textContent='Toca la pantalla para activar música');
          tryPlay();
          const unlock = () => {{ tryPlay(); document.removeEventListener('pointerdown', unlock); document.removeEventListener('touchstart', unlock); }};
          document.addEventListener('pointerdown', unlock, {{passive:true}});
          document.addEventListener('touchstart', unlock, {{passive:true}});
        }})();
        </script></body></html>""".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; media-src 'self' data:")
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
