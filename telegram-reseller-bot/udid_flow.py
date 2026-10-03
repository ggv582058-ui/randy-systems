"""Short-lived, private iOS Profile Service sessions for the reseller bot."""
import asyncio
import html
import hmac
import logging
import json
import os
import plistlib
import re
import subprocess
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger(__name__)


def profile(base, token):
    return plistlib.dumps({"PayloadType": "Profile Service", "PayloadVersion": 1,
        "PayloadUUID": str(uuid.uuid4()), "PayloadIdentifier": "com.randymod.udid",
        "PayloadOrganization": "Randy Mod", "PayloadDisplayName": "Randy Mod · Obtener UDID",
        "PayloadDescription": "Devuelve el UDID y modelo a tu sesión privada de Randy Mod. No configura MDM, VPN ni certificados.",
        "PayloadContent": {"URL": f"{base}/udid/callback/{token}", "Challenge": token,
                           "DeviceAttributes": ["UDID", "PRODUCT"]}})


def device_response(raw, token):
    # iOS sends a CMS-signed plist. Signature integrity is checked, but this is
    # an identification convenience, not trusted device authentication.
    decoded = subprocess.run(["openssl", "cms", "-verify", "-inform", "DER", "-noverify"],
                             input=raw, capture_output=True, timeout=5)
    if decoded.returncode:
        raise ValueError("Respuesta de iOS inválida")
    try:
        values = plistlib.loads(decoded.stdout)
    except Exception as exc:
        raise ValueError("Datos de iOS inválidos") from exc
    if not isinstance(values, dict) or not hmac.compare_digest(str(values.get("CHALLENGE", "")), token):
        raise ValueError("Sesión incorrecta")
    udid = str(values.get("UDID", "")).upper()
    if not re.fullmatch(r"(?:[0-9A-F]{40}|[0-9A-F]{8}-[0-9A-F]{16})", udid):
        raise ValueError("UDID inválido")
    return udid, str(values.get("PRODUCT", "iPhone / iPad"))[:80]


class UDIDService:
    def __init__(self, db, bot, loop):
        self.db, self.bot, self.loop = db, bot, loop

    def handle_get(self, handler, path):
        if not path.startswith(("/udid/",)):
            return False
        parts = path.strip("/").split("/")
        token = parts[-1]
        row = self.db.udid_session(token)
        if not row or len(parts) not in (2, 3):
            handler.send_error(404, "Sesión expirada. Obtén otro enlace en Telegram.")
            return True
        base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
        if len(parts) == 3 and parts[1] == "profile":
            if not base.startswith("https://"):
                handler.send_error(503)
                return True
            payload = profile(base, token)
            handler.send_response(200)
            handler.send_header("Content-Type", "application/x-apple-aspen-config")
            # Safari handles this MIME type as a profile, not a generic attachment.
        elif len(parts) == 2:
            udid = html.escape(row["udid"] or "")
            username = getattr(self.bot, "username", None) or "XxResellerbot"
            back = f"https://t.me/{username}?start=udid_{token}"
            native_back = f"tg://resolve?domain={username}&start=udid_{token}"
            navigation = f'''<script src="https://telegram.org/js/telegram-web-app.js"></script><script>
const tg=window.Telegram&&window.Telegram.WebApp;
if(tg&&tg.initData){{tg.ready();tg.expand();}}
function getProfile(event){{
  if(tg&&tg.initData){{
    event.preventDefault();
    tg.openLink(new URL('/udid/{token}?safari=1',location.origin).href,{{try_browser:'safari'}});
    document.getElementById('next-step').hidden=false;
  }}
}}
function returnToBot(event){{
  if(tg&&tg.initData){{event.preventDefault();tg.openTelegramLink({json.dumps(back)});tg.close();}}
}}
const captured={str(bool(udid)).lower()};
if(!captured&&!(tg&&tg.initData)&&new URLSearchParams(location.search).get('safari')==='1'){{
  let downloaded=false;
  try{{downloaded=sessionStorage.getItem('downloaded:{token}')==='1';sessionStorage.setItem('downloaded:{token}','1');}}catch(error){{}}
  if(!downloaded)setTimeout(()=>{{location.href='/udid/profile/{token}';}},1200);
}}
if(captured&&!(tg&&tg.initData)){{
  let tried=false;
  try{{tried=sessionStorage.getItem('returned:{token}')==='1';sessionStorage.setItem('returned:{token}','1');}}catch(error){{}}
  if(!tried)setTimeout(()=>{{location.href={json.dumps(native_back)};}},700);
}}
</script>'''
            result = (f'<h2>Tu UDID está listo</h2><p>Equipo: {html.escape(row["model"] or "iPhone / iPad")}</p><code id="udid">{udid}</code><button onclick="navigator.clipboard.writeText(document.getElementById(\'udid\').textContent)">Copiar UDID</button><a class="button" onclick="returnToBot(event)" href="{back}">Continuar en Telegram ↗</a><p>Tu UDID se guarda en tu sesión. Puedes quitar el perfil de Ajustes.</p>'
                      if udid else f'<h1>Tu equipo.<br>Tu certificado.</h1><p>Obtén el UDID de este iPhone o iPad para registrar tu certificado.</p><a class="button" onclick="getProfile(event)" href="/udid/profile/{token}">Obtener mi UDID ↗</a><p id="next-step" hidden>En Safari, toca Permitir. Después abre Ajustes → Perfil descargado → Instalar.</p><ol><li>Toca Obtener mi UDID y permite la descarga en Safari.</li><li>Ajustes → Perfil descargado → Instalar.</li><li>Vuelve aquí. El UDID también llegará a Telegram.</li></ol><p class="small">El perfil solicita UDID y modelo. Se vinculan a tu cuenta durante 30 minutos. No configura administración remota. Puedes quitarlo después.</p>')
            payload = f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Randy Mod · UDID</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(ellipse at 50% 15%,#0c4d8566,transparent 60%),#030b18;color:#edf8ff;font:16px system-ui}}main{{max-width:640px;margin:auto;padding:24px;position:relative;z-index:1}}.brand{{text-shadow:0 0 18px #3fa9ff;letter-spacing:3px;color:#78baff;font-size:12px;font-weight:800}}.art{{height:210px;margin:22px 0;border-radius:28px;overflow:hidden;position:relative;background:#0a2038}}.art img{{width:100%;height:100%;object-fit:cover;animation:float 8s ease-in-out infinite alternate}}.art:after{{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,#071a3b66)}}@keyframes float{{to{{transform:scale(1.07) translateY(-4px)}}}}h1{{font-size:38px;line-height:1.05}}p,li{{color:#b9cce1;line-height:1.6}}li{{margin:12px 0}}a.button,button{{display:block;width:100%;padding:18px;border:0;border-radius:17px;background:#48b4ff;color:#041e35;font-size:17px;font-weight:800;text-align:center;text-decoration:none}}code{{display:block;overflow-wrap:anywhere;padding:22px;background:#11283f;border-radius:18px;margin:20px 0}}.small{{font-size:12px}}.art{{box-shadow:0 0 40px #008cfa44;border:1px solid #459ffb66}}body:before{{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(#2486c911 1px,transparent 1px),linear-gradient(90deg,#2486c911 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(transparent,#000)}}.code-side{{position:fixed;top:0;bottom:0;width:70px;overflow:hidden;pointer-events:none;color:#36a8ff;opacity:.22;font:11px/2.3 monospace;white-space:pre-wrap;overflow-wrap:anywhere}}.code-side.left{{left:0}}.code-side.right{{right:0}}.code-side span{{display:block;animation:code-stream 30s linear infinite}}@keyframes code-stream{{from{{transform:translateY(15vh)}}to{{transform:translateY(-60vh)}}}}@media(prefers-reduced-motion:reduce){{.art img,.code-side span{{animation:none}}}}</style><div class="code-side left" aria-hidden="true"><span>const randy = {{
 device: 'iOS',
 udid: 'ready',
 style: 'robotic'
}};
// RANDY MOD
await connect();
0101 0011
private.session
// DEVICE ID
const randy = {{
 theme: 'blue'
}};
await connect();</span></div><div class="code-side right" aria-hidden="true"><span>// RANDY SYSTEMS
async device() {{
 return profile;
}}
0101 0110
UDID.capture()
// DEVICE ID
private.session
async device() {{
 return profile;
}}
0101 0110</span></div><main><div class="brand">UDID BY RANDY MOD</div><div class="art"><img src="/brand/cover" alt="Randy Mod"></div>{result}</main>{navigation}</html>'''.encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            handler.send_error(404)
            return True
        handler.send_header("Cache-Control", "private, no-store")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
        return True

    def handle_post(self, handler, path):
        if not path.startswith("/udid/callback/"):
            return False
        token = path.rsplit("/", 1)[-1]
        row = self.db.udid_session(token)
        if not row:
            handler.send_error(404)
            return True
        try:
            length = int(handler.headers.get("Content-Length", "0"))
            if not 1 <= length <= 65536:
                raise ValueError("Respuesta demasiado grande")
            udid, model = device_response(handler.rfile.read(length), token)
            fresh = self.db.complete_udid_session(token, udid, model)
            if not fresh and row["udid"] != udid:
                raise ValueError("La sesión ya fue utilizada")
        except (ValueError, OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException) as exc:
            log.warning("UDID callback rejected: %s", type(exc).__name__)
            handler.send_error(400, "No pude leer el UDID. Solicita otro enlace en el bot.")
            return True
        if fresh:
            async def notify():
                try:
                    await self.bot.send_message(row["user_id"], f"✅ Tu UDID está listo\nEquipo: {html.escape(model)}\n<code>{udid}</code>\nToca Continuar para usarlo en tu registro o consulta.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Continuar con este UDID", callback_data=f"udid:use:{token}")]]))
                except Exception:
                    # Result remains available in the private page if Telegram fails.
                    pass
            asyncio.run_coroutine_threadsafe(notify(), self.loop)
        # Profile Service uses 301 to hand control back from Settings to Safari.
        base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
        handler.send_response(301)
        handler.send_header("Location", f"{base}/udid/{token}")
        handler.send_header("Content-Length", "0")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        return True
