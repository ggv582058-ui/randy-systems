from __future__ import annotations

import asyncio
import html
import hmac
import io
import json
import logging
import os
import plistlib
import threading
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from telegram import Update
from app_signing import app_open_url


log = logging.getLogger("randy-webhook")


def _installer_style() -> str:
    """Shared Randy branding for the Telegram mini app and Safari handoff."""
    return """
*{box-sizing:border-box}html{background:#030916;color-scheme:dark}body{margin:0;min-height:100vh;color:#e9f5ff;font:15px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:radial-gradient(ellipse at 5% 12%,#095fc336,transparent 48%),radial-gradient(ellipse at 98% 75%,#044ea62b,transparent 50%),#030916;overflow-x:hidden}
body:before{content:'';position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(#559fff06 1px,transparent 1px),linear-gradient(90deg,#559fff06 1px,transparent 1px);background-size:42px 42px;mask-image:linear-gradient(#000,transparent)}
.code-rain{position:fixed;inset:0;overflow:hidden;pointer-events:none;user-select:none;color:#4c9bff;opacity:.13;font:11px/2.7 ui-monospace,SFMono-Regular,Consolas,monospace;z-index:0}.code-rain span{position:absolute;top:-180px;width:140px;white-space:pre-line;animation:code-drift 27s linear infinite}.code-rain span:nth-child(1){left:2%}.code-rain span:nth-child(2){right:1%;animation-delay:-13s}.code-rain span:nth-child(3){left:43%;animation-delay:-7s;opacity:.45}@keyframes code-drift{to{transform:translateY(110vh)}}
main{position:relative;max-width:460px;margin:auto;padding:23px 20px calc(26px + env(safe-area-inset-bottom));min-height:100vh;text-align:center}header{display:flex;align-items:center;justify-content:space-between;text-align:left;margin-bottom:20px}.brand{font-size:15px;font-weight:850;letter-spacing:1.8px}.brand small{display:block;color:#6996c5;font:9px/2 ui-monospace,monospace;letter-spacing:2px}.secure{color:#8bdcff;background:#08315087;border:1px solid #2876a84d;padding:7px 9px;border-radius:8px;font:9px ui-monospace,monospace;letter-spacing:1px}.secure:before{content:'●';color:#6bd9ff;margin-right:5px}
.brand-art{position:relative;width:100%;aspect-ratio:1.8;overflow:hidden;border-radius:22px;border:1px solid #51a9ff60;background:#06162d;box-shadow:0 15px 55px #006eff16}.brand-art img{width:100%;height:100%;object-fit:cover;object-position:50% 39%;animation:art-drift 12s ease-in-out infinite alternate}.brand-art:after{content:'';position:absolute;inset:0;background:linear-gradient(0deg,#03132988,transparent 40%);pointer-events:none}.art-caption{position:absolute;z-index:1;left:15px;bottom:13px;color:#b1d9ff;font:9px ui-monospace,monospace;letter-spacing:2px}@keyframes art-drift{to{transform:scale(1.045)}}
.app-panel{position:relative;margin:18px 0 16px;padding:25px 21px 23px;border:1px solid #438bd342;border-radius:24px;background:linear-gradient(135deg,#122c4bba,#071328e8);box-shadow:inset 0 1px 0 #c4e5ff14,0 24px 55px #0005;backdrop-filter:blur(18px)}.panel-label{display:flex;justify-content:space-between;align-items:center;color:#699ac9;font:9px ui-monospace,monospace;letter-spacing:1.3px}.panel-label b{color:#8fccff;font-weight:500}.orb{position:relative;margin:24px auto 15px;width:90px;height:90px;padding:6px;border-radius:25px;background:linear-gradient(140deg,#2e83d5,#0b2853);box-shadow:0 0 0 7px #409aff0c,0 14px 42px #1384ff29}.orb:after{content:'';position:absolute;inset:-12px;border:1px solid #64b6ff25;border-radius:33px}.orb img{width:100%;height:100%;object-fit:cover;border-radius:20px}.orb .fallback{display:grid;place-items:center;height:100%;font-size:30px;font-weight:800;color:white}
h1{font-size:32px;letter-spacing:-1px;margin:10px 0 5px}.version{font-size:12px;color:#90b4d7}.badge{display:inline-flex;align-items:center;gap:6px;margin:15px 0 3px;font:9px ui-monospace,monospace;letter-spacing:1px;color:#91d2ff}.badge:before{content:'●';font-size:8px;color:#5ac5ff}.hint{font-size:13px;line-height:1.65;color:#97b2cf;margin:14px 0 18px}.install,.button{position:relative;display:flex;align-items:center;justify-content:center;gap:10px;min-height:56px;width:100%;border:1px solid #76bdff70;border-radius:15px;background:linear-gradient(110deg,#136bdf,#2199f3);box-shadow:0 9px 28px #087af331,inset 0 1px 0 #bce9ff35;color:#fff;font:750 16px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;text-decoration:none;cursor:pointer;transition:transform .2s,filter .2s}.install:hover,.button:hover{filter:brightness(1.1)}.install:active,.button:active{transform:scale(.98)}.install span{position:absolute;right:18px}.install:focus-visible,.button:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid #b5e5ff;outline-offset:4px}.waiting{padding:16px;background:#102a47;border:1px solid #6d9ac849;border-radius:14px;line-height:1.6;color:#bfdbf7}.workflow{display:flex;justify-content:center;gap:18px;color:#6890b6;font:9px ui-monospace,monospace;margin-top:19px}.workflow span:first-child{color:#afd9ff}.workflow b{color:#389eff;font-weight:500;margin-right:4px}
.video-guide{margin:16px 0;padding:15px;border:1px solid #377abd35;border-radius:18px;background:#0a1a2db8;text-align:left}.video-guide summary{cursor:pointer;list-style:none;font-size:12px;font-weight:700;color:#c7e3ff;display:flex;justify-content:space-between}.video-guide summary:after{content:'+';color:#63b5ff}.video-guide[open] summary:after{content:'−'}video{display:block;margin-top:14px;width:100%;max-height:220px;border-radius:12px;background:#06142a}.web{display:block;color:#81baf0;font-size:12px;text-decoration:none;margin:20px 0}.foot{color:#537899;font:9px/1.8 ui-monospace,monospace;letter-spacing:1px;margin-top:18px}.note{padding:15px 16px;border:1px solid #438bd334;border-radius:16px;background:#0a1a2dcc;text-align:left;color:#97b2cf;font-size:12px;line-height:1.7}.secondary{color:#6e92b5;font-size:11px;line-height:1.7}.button{margin:14px 0}#installed{background:#10345b;color:#b8ddff;border-color:#427bae80;box-shadow:none}#open-app.button{background:linear-gradient(110deg,#0c72e6,#36afff)}[hidden]{display:none!important}
@media(prefers-reduced-motion:reduce){.code-rain span,.brand-art img{animation:none}.install,.button{transition:none}}@media(max-width:350px){main{padding-left:14px;padding-right:14px}.app-panel{padding:22px 16px}.secure{font-size:8px}.brand{font-size:13px}}
"""


def _installer_brand(token: str) -> str:
    return f'''<div class="code-rain" aria-hidden="true"><span>const randy = true;
certificate.ready();
app.install();
await device.open();
// RANDY SYSTEMS
export default randy;
certificate.ready();
app.install();</span><span>interface Device {{
  certificate: Ready;
  app: Signed;
}}
// PRIVATE ACCESS
device.connect();
app.launch();</span><span>01001010 00101001
// RANDY MOD
app.ready = true;
certificate.load();</span></div><main><header><div class="brand">RANDY MOD<small>PRIVATE APP EXPERIENCE</small></div><div class="secure">PRIVATE</div></header><div class="brand-art"><img src="/certificate/cover/{token}" alt="Randy Mod" fetchpriority="high"><span class="art-caption">RANDY SYSTEMS / iOS</span></div>'''


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
        self.certificate_cover = None
        self.certificate_logo = None
        self.certificate_signed_lookup = None
        self.certificate_ipa_save = None
        self.udid_service = None

    def configure(self, applications: dict, secrets: dict[str, str]) -> None:
        self.applications = applications
        self.secrets = secrets

    def configure_certificates(self, lookup, download, webhook, cover=None, logo=None, signed_lookup=None, ipa_save=None) -> None:
        self.certificate_lookup = lookup
        self.certificate_download = download
        self.certificate_webhook = webhook
        self.certificate_cover = cover
        self.certificate_logo = logo
        self.certificate_signed_lookup = signed_lookup
        self.certificate_ipa_save = ipa_save


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if self.server.udid_service and self.server.udid_service.handle_get(self, path):
            return
        if path == "/brand/cover":
            data = (Path(__file__).parent / "randy-mod-cover.jpg").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/certificate/tutorial":
            data = (Path(__file__).parent / "certificate-tutorial.mp4").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/certificate/music":
            data = (Path(__file__).parent / "certificate-ambient.m4a").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mp4")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith("/certificate/app/") or path.startswith("/certificate/manifest/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                self._certificate_signed_file(parts[2], parts[3], parts[1] == "manifest")
                return
        if path.startswith("/certificate/install/"):
            focus = parse_qs(urlsplit(self.path).query).get("app", [""])[0]
            self._certificate_page(path.rsplit("/", 1)[-1], focus if focus in ("gbox", "esign") else "")
            return
        if path.startswith("/certificate/mini/"):
            focus = parse_qs(urlsplit(self.path).query).get("app", ["gbox"])[0]
            self._certificate_mini(path.rsplit("/", 1)[-1], focus)
            return
        if path.startswith("/certificate/launch/"):
            focus = parse_qs(urlsplit(self.path).query).get("app", ["gbox"])[0]
            self._certificate_launch(path.rsplit("/", 1)[-1], focus)
            return
        if path.startswith("/certificate/cover/"):
            self._certificate_cover(path.rsplit("/", 1)[-1])
            return
        if path.startswith("/certificate/logo/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                self._certificate_logo(parts[2], parts[3])
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

    def _certificate_mini(self, token: str, kind: str) -> None:
        if kind not in ("gbox", "esign"):
            self.send_error(404)
            return
        server: BotHTTPServer = self.server
        order = server.certificate_lookup(token) if server.certificate_lookup else None
        if not order or order["status"] != "completed":
            self.send_error(404, "Enlace privado inválido o expirado")
            return
        signed = bool(server.certificate_signed_lookup and server.certificate_signed_lookup(order["id"], kind))
        base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
        safe_token = html.escape(token, quote=True)
        name = "GBox" if kind == "gbox" else "ESign"
        launch_url = f"{base}/certificate/launch/{safe_token}?app={kind}"
        main_button = (f'<button id="install" class="install" type="button">Instalar {name} <span>↗</span></button>'
                       if signed and base.startswith("https://") else
                       f'<div class="waiting">La firma de la app aún no está lista. Vuelve al bot y toca <b>Preparar {name}</b>.</div>')
        body = f'''<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#030916"><title>{name} · Randy Mod</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script><style>{_installer_style()}</style>
</head><body>{_installer_brand(safe_token)}
<section class="app-panel"><div class="panel-label"><span>APP / {'01' if kind == 'gbox' else '02'}</span><b>iOS · PRIVATE</b></div>
<div class="orb"><img src="/certificate/logo/{safe_token}/{kind}" alt="Logo {name}" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="fallback" hidden>{'G' if kind == 'gbox' else 'E'}</span></div>
<h1>{name}</h1><div class="version">Tu app. Tu certificado. Tu dispositivo.</div><div class="badge">{'FIRMA LISTA · TU EQUIPO' if signed else 'CERTIFICADO RECIBIDO'}</div>
<p class="hint">Instala {name} con tu certificado y abre la app cuando iOS termine.</p>
{main_button}<div class="workflow" aria-label="Pasos de instalación"><span><b>01</b> INSTALAR</span><span><b>02</b> CONFIRMAR</span><span><b>03</b> ABRIR</span></div></section>
<details class="video-guide"><summary>Guía rápida de instalación</summary><video controls playsinline preload="none" poster="/certificate/cover/{safe_token}"><source src="/certificate/tutorial" type="video/mp4">Tu navegador no admite video.</video><p class="secondary">Después de instalar, importa tus archivos P12 y MobileProvision en {name} con la contraseña que recibiste en Telegram.</p></details>
<a class="web" href="/certificate/install/{safe_token}?app={kind}">Ver mi certificado y archivos ↗</a>
<div class="foot">RANDY MOD © 2026 · PRIVATE ACCESS</div>
</main><script>
const app=window.Telegram?.WebApp;app?.ready();app?.expand();
try{{app?.setHeaderColor?.('#030916');app?.setBackgroundColor?.('#030916');}}catch(e){{}}
document.getElementById('install')?.addEventListener('click',()=>{{const link={json.dumps(launch_url)};if(app?.openLink)app.openLink(link,{{try_instant_view:false}});else window.open(link,'_blank');}});
</script></body></html>'''.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Security-Policy", "default-src 'self' https://telegram.org data:; style-src 'unsafe-inline'; script-src 'self' 'unsafe-inline' https://telegram.org; img-src 'self' data:; media-src 'self'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _certificate_launch(self, token: str, kind: str) -> None:
        if kind not in ("gbox", "esign"):
            self.send_error(404)
            return
        server: BotHTTPServer = self.server
        order = server.certificate_lookup(token) if server.certificate_lookup else None
        signed = server.certificate_signed_lookup(order["id"], kind) if order and server.certificate_signed_lookup else None
        if not order or order["status"] != "completed" or not signed:
            self.send_error(404, "App firmada no disponible o enlace vencido")
            return
        base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
        if not base.startswith("https://"):
            self.send_error(503, "HTTPS no configurado")
            return
        safe_token = html.escape(token, quote=True)
        name = "GBox" if kind == "gbox" else "ESign"
        manifest = f"{base}/certificate/manifest/{token}/{kind}.plist"
        install_url = html.escape("itms-services://?action=download-manifest&url=" + quote(manifest, safe=""), quote=True)
        open_url = app_open_url(signed["ipa"], kind)
        open_control = (f'<a id="open-app" class="button" href="{html.escape(open_url, quote=True)}" hidden>Abrir {name}</a>'
                        if open_url else f'<p id="open-app" hidden>Cuando termine, abre {name} desde la pantalla de inicio.</p>')
        after_install = (f'<button id="installed" class="button" type="button" hidden>Ya terminó de instalar</button>'
                         + open_control + '<p id="install-note" hidden>Espera a que iOS termine la instalación. Esta página no puede comprobar si la app está instalada.</p>')
        body = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#030916"><title>Instalar {name} · Randy Mod</title><style>{_installer_style()}</style></head><body>{_installer_brand(safe_token)}
<section class="app-panel"><div class="panel-label"><span>INSTALL / iOS</span><b>FIRMA PRIVADA</b></div><div class="orb"><img src="/certificate/logo/{safe_token}/{kind}" alt="Logo {name}" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="fallback" hidden>{'G' if kind == 'gbox' else 'E'}</span></div><h1>{name}</h1><div class="version">Continúa en tu dispositivo</div><div class="badge">FIRMA LISTA · TU EQUIPO</div><p class="hint">Toca instalar y confirma el aviso de iOS. Cuando termine, continúa para abrir {name}.</p><a id="install-app" class="button" href="{install_url}">Instalar {name} ↗</a>{after_install}<div class="workflow"><span><b>01</b> INSTALAR</span><span><b>02</b> CONFIRMAR</span><span><b>03</b> ABRIR</span></div></section><div class="note">Si no aparece el aviso, abre esta página en <b>Safari</b> con el menú Compartir y toca «Instalar {name}» otra vez. Usa el iPhone o iPad de tu certificado.</div><div class="foot">RANDY MOD © 2026 · PRIVATE ACCESS</div></main><script>document.getElementById('install-app').addEventListener('click',()=>{{document.getElementById('installed').hidden=false;document.getElementById('install-note').hidden=false;}});document.getElementById('installed').addEventListener('click',()=>{{document.getElementById('open-app').hidden=false;document.getElementById('installed').hidden=true;}});</script></body></html>'''.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Security-Policy", "default-src 'self' data:; style-src 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _certificate_page(self, token: str, focus: str = "") -> None:
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
        install_actions = ""
        if ready and server.certificate_signed_lookup:
            for kind, label in sorted((("gbox", "GBox"), ("esign", "ESign")),
                                      key=lambda item: item[0] != focus):
                if server.certificate_signed_lookup(order["id"], kind):
                    # URLs from Render's configured public host cannot be replaced
                    # by an untrusted Host header.
                    public_base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
                    manifest = f"{public_base}/certificate/manifest/{token_safe}/{kind}.plist"
                    if public_base.startswith("https://"):
                        install_url = "itms-services://?action=download-manifest&url=" + quote(manifest, safe="")
                        icon = f'/certificate/logo/{token_safe}/{kind}'
                        install_actions += (f'<a class="action install-action" href="{html.escape(install_url, quote=True)}">'
                                            f'<span><img class="app-logo" src="{icon}" alt=""></span>'
                                            f'<div><b>Instalar {label}</b><small>Toca aquí desde Safari</small></div><i>↗</i></a>')

        actions = (f"""
          <div class="section-title">ARCHIVOS DEL CERTIFICADO</div>
          <button class="action share-file" data-kind="p12"><span><img class="file-logo" src="/certificate/logo/{token_safe}/p12" alt="" onerror="this.replaceWith(document.createTextNode('🔐'))"></span><div><b>Compartir P12</b><small>Abrir con tu firmador</small></div><i>›</i></button>
          <button class="action share-file" data-kind="mobileprovision"><span><img class="file-logo" src="/certificate/logo/{token_safe}/mobileprovision" alt="" onerror="this.replaceWith(document.createTextNode('📲'))"></span><div><b>Compartir MobileProvision</b><small>Perfil de aprovisionamiento</small></div><i>›</i></button>
          <a class="action" href="/certificate/download/{token_safe}"><span>📦</span><div><b>Descargar paquete ZIP</b><small>P12 + MobileProvision</small></div><i>↓</i></a>
          <button id="copy-password" class="action"><span>🔑</span><div><b>Copiar contraseña</b><small>Contraseña del archivo P12</small></div><i>⧉</i></button>
          <div class="section-title">IMPORTAR CERTIFICADO EN</div>
          <div class="apps">
            <button class="mini share-file" data-kind="p12"><img class="app-logo" src="/certificate/logo/{token_safe}/gbox" alt="" onerror="this.style.display='none'"><b>GBox · Importar P12</b></button>
            <button class="mini share-file" data-kind="p12"><img class="app-logo" src="/certificate/logo/{token_safe}/esign" alt="" onerror="this.style.display='none'"><b>ESign · Importar P12</b></button>
          </div>
          <div class="source-links"><a href="https://cdn.gbox.run/d/apps/GBox_v6.1.2.ipa" rel="noopener noreferrer" target="_blank">Descargar IPA GBox · requiere firma ↗</a><a href="https://github.com/qbap/Esign-IPA-Installer" rel="noopener noreferrer" target="_blank">Guía y descarga ESign ↗</a></div>
        """ if ready else """
          <div class="waiting"><div class="loader"></div><div><b>Preparando certificado</b><small>Tiempo transcurrido: <span id="wait-time">consultando…</span></small><small>Espera unos minutos. Te avisaré en Telegram; la revisión depende del proveedor.</small></div></div>
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
        """ if ready else f"""<script>
        const started=Date.parse({json.dumps(str(order['created_at']))});
        function updateWait() {{const seconds=Math.max(0,Math.floor((Date.now()-started)/1000));document.getElementById('wait-time').textContent=Math.floor(seconds/60)+' min '+(seconds%60)+' s';}}
        updateWait();setInterval(updateWait,1000);setTimeout(()=>location.reload(),20000);
        </script>""")


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
        .apps{{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}}.mini{{border:1px solid #72b9ff31;border-radius:18px;padding:14px 11px;background:#0a1b35b8;color:white;font-size:18px;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:inset 0 1px 0 #fff0d}}.mini b{{font-size:13px}}.app-logo,.file-logo{{width:28px;height:28px;object-fit:cover;border-radius:8px;flex:none}}.install-action{{padding:18px 14px;border-color:#73e1ffa0;background:linear-gradient(110deg,#1260cb,#197bd8);box-shadow:0 12px 32px #1267db55}}.install-action b{{font-size:18px}}.install-action .app-logo{{width:35px;height:35px}}.source-links{{display:flex;flex-wrap:wrap;gap:10px;margin:13px 2px 0}}.source-links a{{color:#8dcaff;font-size:12px;text-decoration:none;font-weight:750}}.source-links a:hover{{text-decoration:underline}}
        .waiting{{margin-top:20px;display:flex;align-items:center;gap:14px;padding:18px;border-radius:20px;background:#0b213fbb;border:1px solid #4ca7ff3d}}.waiting small{{display:block;color:#8db1d9;margin-top:4px}}.loader{{width:28px;height:28px;border-radius:50%;border:3px solid #1687ff33;border-top-color:#56b3ff;animation:spin .8s linear infinite}}@keyframes spin{{to{{transform:rotate(360deg)}}}}
        .music-pill{{position:fixed;z-index:8;right:15px;bottom:calc(16px + env(safe-area-inset-bottom));display:flex;align-items:center;gap:8px;padding:10px 13px;border:1px solid #8dccff4a;border-radius:999px;background:#071a31c7;color:#cfeaff;backdrop-filter:blur(18px);box-shadow:0 12px 30px #0008;font-size:12px;font-weight:800}}.music-dot{{width:8px;height:8px;border-radius:50%;background:#36a3ff;box-shadow:0 0 12px #36a3ff;animation:pulse 1.2s ease-in-out infinite alternate}}@keyframes pulse{{to{{opacity:.3;transform:scale(.65)}}}}
        .foot{{margin:18px 5px 0;color:#6388b2;font-size:11px;line-height:1.5;text-align:center}}@media(min-width:500px){{.grid{{grid-template-columns:1fr 1fr}}}}
        </style></head>
        <body><main><section class="glass"><div class="brand">RANDY SYSTEMS · ENTREGA PRIVADA</div>
        <div class="hero" style="background-image:linear-gradient(0deg,#031025ed,#06152a55),url('/certificate/cover/{token_safe}');background-position:center;background-size:cover;min-height:220px;display:flex;flex-direction:column;justify-content:flex-end"><div class="eyebrow">CERTIFICADO DIGITAL</div><h1>{name}</h1><div class="signed">✓ {status}</div></div>
        <div class="section-title">INSTALACIÓN EN SAFARI</div>
        {install_actions if install_actions else '<div class="waiting"><div>📲</div><div><b>Prepara GBox o ESign desde tu bot</b><small>En Telegram toca Preparar instalación. Regresa aquí cuando esté lista la app firmada.</small></div></div>' if ready else ''}
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
        <button class="music-pill" id="music-pill" type="button" aria-label="Activar o pausar música"><span class="music-dot"></span><span id="music-label">Música automática</span></button>
        <audio id="bg-music" autoplay loop playsinline preload="auto" src="/certificate/music"></audio>
        {script}
        <script>
        (() => {{
          const audio = document.getElementById('bg-music');
          const label = document.getElementById('music-label');
          const pill = document.getElementById('music-pill');
          const tryPlay = () => audio.play().then(() => label.textContent='Música activa').catch(() => label.textContent='Toca la pantalla para activar música');
          tryPlay();
          pill.addEventListener('click', (event) => {{ event.stopPropagation(); if (audio.paused) tryPlay(); else {{ audio.pause(); label.textContent='Música pausada'; }} }});
          const unlock = () => {{ if (audio.paused && label.textContent !== 'Música pausada') tryPlay(); document.removeEventListener('pointerdown', unlock); document.removeEventListener('touchstart', unlock); }};
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

    def _certificate_cover(self, token: str) -> None:
        server: BotHTTPServer = self.server
        if not server.certificate_lookup or not server.certificate_lookup(token):
            self.send_error(404, "Enlace inválido o expirado")
            return
        data = server.certificate_cover() if server.certificate_cover else None
        if not data:
            data = (Path(__file__).parent / "randy-mod-cover.jpg").read_bytes()
        # Telegram compresses photos to JPEG; documents may be PNG.
        content_type = "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _certificate_logo(self, token: str, kind: str) -> None:
        server: BotHTTPServer = self.server
        if not server.certificate_lookup or not server.certificate_lookup(token):
            self.send_error(404, "Enlace inválido o expirado")
            return
        data = server.certificate_logo(kind) if server.certificate_logo else None
        if not data:
            self.send_error(404, "Logo no disponible")
            return
        content_type = "image/png" if data.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _certificate_signed_file(self, token: str, filename: str, manifest: bool) -> None:
        kind, ext = (filename.rsplit(".", 1) if "." in filename else ("", ""))
        if kind not in ("gbox", "esign") or ext != ("plist" if manifest else "ipa"):
            self.send_error(404, "Aplicación no encontrada")
            return
        server: BotHTTPServer = self.server
        order = server.certificate_lookup(token) if server.certificate_lookup else None
        if not order or order["status"] != "completed" or not server.certificate_signed_lookup:
            self.send_error(404, "Enlace privado vencido")
            return
        app = server.certificate_signed_lookup(order["id"], kind)
        if not app:
            self.send_error(404, "La IPA aún no está firmada")
            return
        if manifest:
            base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
            if not base.startswith("https://"):
                self.send_error(503, "HTTPS no configurado")
                return
            body = plistlib.dumps({"items": [{"assets": [{"kind": "software-package",
                "url": f"{base}/certificate/app/{token}/{kind}.ipa"}],
                "metadata": {"bundle-identifier": app["bundle_id"],
                             "bundle-version": app["version"], "kind": "software",
                             "title": "GBox" if kind == "gbox" else "ESign"}}]})
            content_type = "application/xml"
        else:
            body = app["ipa"]
            content_type = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

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
        if server.udid_service and server.udid_service.handle_post(self, path):
            return
        if path == "/maintenance/import-esign":
            secret = os.getenv("IPA_IMPORT_SECRET", "")
            supplied = self.headers.get("X-IPA-Import-Secret", "")
            if not secret or len(secret) < 48 or not hmac.compare_digest(secret, supplied):
                self.send_error(404)
                return
            if not server.certificate_ipa_save:
                self.send_error(503)
                return
            try:
                from app_signing import ipa_info
                length = int(self.headers.get("Content-Length", "0"))
                if not 1024 <= length <= 19 * 1024 * 1024:
                    raise ValueError("Tamaño inválido")
                payload = self.rfile.read(length)
                bundle_id, version = ipa_info(payload)
                if bundle_id != "p3.xyz.yyyue.esign" or version != "5.0.2":
                    raise ValueError("Aplicación inesperada")
                server.certificate_ipa_save("esign", payload, bundle_id, version)
            except (ValueError, OSError):
                self.send_error(400, "IPA inválida")
                return
            body = json.dumps({"status": "ok", "app": "esign", "version": version}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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

