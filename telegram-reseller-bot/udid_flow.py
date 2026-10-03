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
            navigation = f'''<script>
const getTG=()=>window.Telegram&&window.Telegram.WebApp;
const miniApp=!!(getTG()&&getTG().initData)||new URLSearchParams(location.hash.slice(1)).has('tgWebAppData');
function readyMiniApp(){{const tg=getTG();if(tg&&tg.initData){{tg.ready();}}}}
if(miniApp&&!getTG()){{
 const sdk=document.createElement('script');sdk.src='https://telegram.org/js/telegram-web-app.js';sdk.async=true;sdk.onload=readyMiniApp;document.head.appendChild(sdk);
}}else{{readyMiniApp();}}
function getProfile(event){{
  const tg=getTG();
  if(miniApp){{
    event.preventDefault();
    if(!tg||!tg.initData){{const note=document.getElementById('next-step');note.hidden=false;note.textContent='Preparando Safari… vuelve a tocar el botón en un instante.';return;}}
    tg.openLink(new URL('/udid/{token}?safari=1',location.origin).href,{{try_browser:'safari'}});
    tg.close();
  }}
}}
function returnToBot(event){{
  const tg=getTG();
  if(tg&&tg.initData){{event.preventDefault();tg.openTelegramLink({json.dumps(back)});tg.close();}}
}}
function openSupport(event){{
 const tg=getTG();
 if(tg&&tg.initData){{event.preventDefault();tg.openTelegramLink('https://t.me/randy_zt1');tg.close();}}
}}
function copyUDID(){{
 const value=document.getElementById('udid').textContent;
 navigator.clipboard.writeText(value).then(()=>{{document.getElementById('copy').textContent='UDID copiado ✓';}}).catch(()=>{{document.getElementById('copy').textContent='Mantén pulsado el UDID para copiar';}});
}}
document.addEventListener('visibilitychange',()=>{{document.documentElement.classList.toggle('paused',document.hidden);}});
const captured={str(bool(udid)).lower()};
if(!captured&&!miniApp&&new URLSearchParams(location.search).get('safari')==='1'){{
  let downloaded=false;
  try{{downloaded=sessionStorage.getItem('downloaded:{token}')==='1';sessionStorage.setItem('downloaded:{token}','1');}}catch(error){{}}
  if(!downloaded)setTimeout(()=>{{location.href='/udid/profile/{token}';}},400);
}}
if(captured&&!miniApp){{
  let tried=false;
  try{{tried=sessionStorage.getItem('returned:{token}')==='1';sessionStorage.setItem('returned:{token}','1');}}catch(error){{}}
  if(!tried)setTimeout(()=>{{location.href={json.dumps(native_back)};}},250);
}}
</script>'''
            result = (f'<h2>Tu UDID está listo</h2><p>Equipo: {html.escape(row["model"] or "iPhone / iPad")}</p><code id="udid">{udid}</code><button id="copy" class="secondary" onclick="copyUDID()">Copiar UDID</button><a class="button" onclick="returnToBot(event)" href="{back}">Continuar en Telegram ↗</a><p>Tu UDID se guarda en tu sesión. Puedes quitar el perfil de Ajustes.</p>'
                      if udid else f'<h1>Tu equipo.<br>Tu certificado.</h1><p>Obtén el UDID de este iPhone o iPad para registrar tu certificado.</p><a class="button" onclick="getProfile(event)" href="/udid/profile/{token}">Obtener mi UDID ↗</a><p id="next-step" hidden>En Safari, toca Permitir. Después abre Ajustes → Perfil descargado → Instalar.</p><ol><li>Toca Obtener mi UDID y permite la descarga en Safari.</li><li>Ajustes → Perfil descargado → Instalar.</li><li>Vuelve aquí. El UDID también llegará a Telegram.</li></ol><p class="small">El perfil solicita UDID y modelo. Se vinculan a tu cuenta durante 30 minutos. No configura administración remota. Puedes quitarlo después.</p>')
            payload = f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="format-detection" content="telephone=no"><title>Randy Mod · UDID</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(ellipse at 50% 15%,#0c4d8566,transparent 60%),#030b18;color:#edf8ff;font:16px system-ui}}main{{max-width:640px;margin:auto;padding:24px;position:relative;z-index:1}}.brand{{text-shadow:0 0 18px #3fa9ff;letter-spacing:3px;color:#78baff;font-size:12px;font-weight:800}}.art{{height:210px;margin:22px 0;border-radius:28px;overflow:hidden;position:relative;background:#0a2038}}.art img{{width:100%;height:100%;object-fit:cover;animation:float 12s ease-in-out infinite alternate;will-change:transform}}.art:after{{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,#071a3b66)}}@keyframes float{{to{{transform:scale(1.07) translateY(-4px)}}}}h1{{font-size:38px;line-height:1.05}}p,li{{color:#b9cce1;line-height:1.6}}li{{margin:12px 0}}a.button,button{{display:block;width:100%;position:relative;overflow:hidden;margin:12px 0;padding:18px;border:1px solid #a6e2ff77;border-radius:20px;background:linear-gradient(135deg,#61baff55,#126da844 50%,#12477966);color:#effaff;box-shadow:inset 0 1px 0 #ffffff66,inset 0 -1px 0 #174b8188,0 12px 28px #0004;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);touch-action:manipulation;transition:transform .15s;font-size:17px;font-weight:800;text-align:center;text-decoration:none}}a.button:before,button:before{{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(115deg,#fff2,transparent 40%,transparent 65%,#ffffff10)}}a.button:active,button:active{{transform:scale(.985)}}button.secondary{{background:linear-gradient(135deg,#6388ac22,#0d264955);border-color:#8bbbe744}}code{{display:block;overflow-wrap:anywhere;padding:22px;background:linear-gradient(140deg,#214c7655,#081d3588);border:1px solid #79b9e54d;border-radius:18px;margin:20px 0}}.small{{font-size:12px}}.art{{box-shadow:0 16px 40px #0005,0 0 24px #008cfa28;border:1px solid #459ffb66}}body:before{{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(#2486c911 1px,transparent 1px),linear-gradient(90deg,#2486c911 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(transparent,#000)}}.code-side{{position:fixed;top:0;bottom:0;width:70px;overflow:hidden;pointer-events:none;color:#36a8ff;opacity:.22;font:11px/2.3 monospace;white-space:pre-wrap;overflow-wrap:anywhere}}.code-side.left{{left:0}}.code-side.right{{right:0}}.code-side span{{display:block;animation:code-stream 40s linear infinite;will-change:transform}}@keyframes code-stream{{from{{transform:translateY(15vh)}}to{{transform:translateY(-60vh)}}}}.art:before{{content:"";position:absolute;z-index:1;inset:0;pointer-events:none;background:radial-gradient(ellipse at 28% 85%,#0acbff55,transparent 60%),radial-gradient(ellipse at 85% 8%,#256aff44,transparent 50%);opacity:.38;animation:shirt-aura 9s ease-in-out infinite alternate;will-change:opacity}}@keyframes shirt-aura{{to{{opacity:.78;transform:scale(1.035)}}}}.contact{{display:flex;align-items:center;gap:14px;position:relative;margin:32px 0 8px;padding:18px;border:1px solid #88ceff55;border-radius:22px;background:linear-gradient(125deg,#549ae52b,#0b1d3866);box-shadow:inset 0 1px 0 #ffffff30,0 12px 32px #0003;color:#e2f4ff;text-decoration:none;touch-action:manipulation}}.contact-icon{{display:grid;place-items:center;flex:none;width:42px;height:42px;border:1px solid #8bd2ff55;border-radius:14px;background:#2987cf33}}.contact svg{{width:23px;height:23px;fill:#c9edff}}.contact small{{display:block;color:#83b6e0;font-size:10px;letter-spacing:2px;font-weight:800;margin-bottom:4px}}.contact strong{{font-size:17px}}.contact-arrow{{margin-left:auto;color:#7bcaff;font-size:22px}}.contact-dot{{display:inline-block;margin-right:7px;width:6px;height:6px;border-radius:50%;background:#52c8ff;animation:contact-pulse 4s ease-in-out infinite alternate}}@keyframes contact-pulse{{to{{opacity:.35}}}}.signature{{text-align:center;color:#6290b7;font:10px monospace;letter-spacing:2px;padding:12px 0 18px}}.paused .art:before,.paused .contact-dot,.paused .art img,.paused .code-side span{{animation-play-state:paused}}@media(prefers-reduced-motion:reduce){{.art img,.art:before,.contact-dot,.code-side span{{animation:none}}}}</style><div class="code-side left" aria-hidden="true"><span>const randy = {{
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
0101 0110</span></div><main><div class="brand">UDID BY RANDY MOD</div><div class="art"><img src="/brand/cover" alt="Randy Mod"></div>{result}<footer><a class="contact" href="https://t.me/randy_zt1" onclick="openSupport(event)"><span class="contact-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21.7 3.1 18.5 20c-.2 1.2-.9 1.5-1.8.9l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1 .5l.4-5 9.2-8.3c.4-.4-.1-.6-.6-.3L6 13.7l-4.9-1.5c-1.1-.3-1.1-1.1.2-1.6L20.5 3c.9-.3 1.6.2 1.2 1.1Z"/></svg></span><span><small><i class="contact-dot"></i>TELEGRAM / RANDY MOD</small><strong>@randy_zt1</strong></span><span class="contact-arrow">↗</span></a><div class="signature">RANDY SYSTEMS · PRIVATE DEVICE ID</div></footer></main>{navigation}</html>'''.encode()
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
