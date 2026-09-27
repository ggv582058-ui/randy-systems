from __future__ import annotations

import asyncio
import html
import io
import json
import os
import re
import time
import zipfile

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

import bot
import health

log = bot.log
SIGN_URL = "https://chungchi.store/sign/?lang=en"

_busy = set()
_retry_after = {}


def _safe(value):
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", value or "certificate").strip(" ._")[:80] or "certificate"


def _components(data):
    p12 = mobile = None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                low = name.lower()
                if p12 is None and low.endswith((".p12", ".pfx")):
                    p12 = (name.rsplit("/", 1)[-1], z.read(name))
                elif mobile is None and low.endswith((".mobileprovision", ".provisionprofile")):
                    mobile = (name.rsplit("/", 1)[-1], z.read(name))
                if p12 and mobile:
                    break
    except Exception as exc:
        log.warning("No se pudieron extraer componentes: %s", exc)
    return p12, mobile


async def deliver(tg_bot, order):
    if order["status"] != "completed" or not order["download_url"]:
        return
    oid = int(order["id"])
    if oid in _busy or time.monotonic() < _retry_after.get(oid, 0):
        return
    _busy.add(oid)
    base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
    web = f"{base}/certificate/install/{order['install_token']}" if base.startswith("https://") else ""
    rows = []
    if web:
        rows = list(bot.certificate_file_buttons(order).inline_keyboard)
    rows.append([InlineKeyboardButton("✍️ Firmar IPA online", url=SIGN_URL)])
    markup = InlineKeyboardMarkup(rows)
    try:
        data = await asyncio.to_thread(bot.chungchi.download, order["download_url"])
        name = _safe(str(order["display_name"] or "certificate"))
        stream = io.BytesIO(data)
        stream.name = f"{name}.zip"
        await tg_bot.send_document(order["user_id"], stream, caption=(
            "✅ <b>CERTIFICADO LISTO</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"📦 Nombre: <b>{html.escape(str(order['display_name']))}</b>\n"
            f"🆔 UDID: <code>{html.escape(str(order['udid']))}</code>\n"
            f"🔐 Contraseña P12: <code>{html.escape(str(order['p12_password']))}</code>\n"
            "📥 ZIP completo enviado. También intento enviarte P12 y MobileProvision por separado.\n\n"
            "✍️ Para firmar una IPA, toca <b>Firmar IPA online</b>, sube este ZIP y usa tu contraseña P12."
        ), reply_markup=markup, parse_mode=ParseMode.HTML)
        p12, mobile = _components(data)
        if p12:
            s = io.BytesIO(p12[1]); s.name = p12[0]
            try: await tg_bot.send_document(order["user_id"], s, caption="🔐 Archivo P12")
            except Exception as exc: log.warning("P12 no enviado %s: %s", oid, exc)
        if mobile:
            s = io.BytesIO(mobile[1]); s.name = mobile[0]
            try: await tg_bot.send_document(order["user_id"], s, caption="📲 MobileProvision")
            except Exception as exc: log.warning("MobileProvision no enviado %s: %s", oid, exc)
        bot.db.mark_certificate_delivered(oid)
        _retry_after.pop(oid, None)
    except Exception as exc:
        log.warning("Entrega ZIP falló %s: %s", oid, exc)
        _retry_after[oid] = time.monotonic() + 60
        try:
            await tg_bot.send_message(order["user_id"], "⚠️ El certificado está listo, pero Telegram no recibió el ZIP. Usa la web privada mientras lo reintento automáticamente.", reply_markup=markup)
        except Exception:
            pass
    finally:
        _busy.discard(oid)


def page(self, token):
    server = self.server
    order = server.certificate_lookup(token) if server.certificate_lookup else None
    if not order:
        self.send_error(404, "Enlace inválido o expirado")
        return
    st = str(order["status"] or "processing").lower()
    labels = {"completed":"Firmado","processing":"Procesando","pending":"Pendiente","review":"En revisión","submitting":"Registrando","failed":"Revisión requerida","cancelled":"Cancelado"}
    status = labels.get(st, st.title())
    ready = st == "completed" and bool(order["download_url"])
    esc = lambda v: html.escape(str(v if v not in (None, "") else "Pendiente"))
    try: registered = health.HealthHandler._pretty_date(order["completed_at"] or order["created_at"])
    except Exception: registered = esc(order["created_at"])
    try: warranty = health.HealthHandler._warranty(order)
    except Exception: warranty = "según el plan"
    token_safe = html.escape(token, quote=True)
    password = esc(order["p12_password"])
    refresh = '<meta http-equiv="refresh" content="20">' if not ready else ""
    music = '<audio id="bgm" autoplay loop playsinline src="/certificate/music"></audio>'
    if ready:
        actions = f'''<section class="panel"><div class="eyebrow">ENTREGA DEL CERTIFICADO</div>
<a class="action primary" href="/certificate/download/{token_safe}">📦 <span><b>Descargar ZIP completo</b><small>P12 + MobileProvision</small></span> ↓</a>
<div class="grid"><a class="action" href="/certificate/component/{token_safe}/p12">🔐 <span><b>P12</b><small>Descargar</small></span></a><a class="action" href="/certificate/component/{token_safe}/mobileprovision">📲 <span><b>MobileProvision</b><small>Descargar</small></span></a></div>
<a class="action sign" href="{SIGN_URL}" target="_blank" rel="noopener">✍️ <span><b>Firmar IPA online</b><small>Sube el ZIP y usa la contraseña P12</small></span> ↗</a>
<button class="action" id="copy">🔑 <span><b>Copiar contraseña P12</b><small>{password}</small></span> ⧉</button></section>'''
    else:
        actions = '<section class="panel waiting"><div class="spin"></div><div><b>Preparando certificado</b><small>Se actualizará solo. No necesitas volver a comprar.</small></div></section>'
    password_js = json.dumps(str(order["p12_password"] or ""))
    body = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">{refresh}<title>Randy Certificate</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0%,#0b3b8b88,transparent 35%),linear-gradient(#02050d,#071935);color:#f5f9ff;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display",Arial,sans-serif;min-height:100vh}}.wrap{{max-width:720px;margin:auto;padding:12px 12px 42px}}.hero,.panel{{border:1px solid #4a9cff55;background:#061631d9;box-shadow:0 18px 50px #001a55aa;backdrop-filter:blur(18px)}}.hero{{position:relative;overflow:hidden;border-radius:26px}}.banner{{width:100%;display:block;aspect-ratio:1.08/1;object-fit:cover}}.fade{{position:absolute;inset:auto 0 0;height:48%;background:linear-gradient(transparent,#020713)}}.brand{{position:absolute;left:20px;right:20px;bottom:16px}}.brand h1{{margin:0;font-size:28px}}.brand p{{margin:5px 0 0;color:#9ac7ff;font-size:11px;letter-spacing:1.5px}}.music{{position:absolute;right:14px;top:14px;border:1px solid #ffffff33;background:#020914aa;color:#fff;border-radius:999px;padding:10px 13px}}.panel{{margin-top:12px;padding:16px;border-radius:22px}}.eyebrow{{color:#83b9ff;font-size:11px;letter-spacing:2px;font-weight:800;margin-bottom:10px}}.info{{display:grid;grid-template-columns:1fr 1fr;gap:9px}}.item{{padding:13px;border:1px solid #4f9fff33;border-radius:17px;background:#04132ecc}}.item small{{display:block;color:#7fa9d9;font-size:10px;letter-spacing:1.2px;margin-bottom:4px}}.item b{{font-size:14px;word-break:break-word}}.status{{color:#55c9ff}}.action{{display:flex;align-items:center;gap:10px;width:100%;margin-top:9px;padding:14px;border-radius:17px;border:1px solid #4f9fff44;background:#061b3f;color:#fff;text-decoration:none;font:inherit;text-align:left}}.action span{{display:flex;flex-direction:column;flex:1}}.action small{{color:#8fb2dc;margin-top:2px}}.primary{{background:linear-gradient(135deg,#096cff,#00a8ff)}}.sign{{background:linear-gradient(135deg,#5f34ff,#087cff)}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:9px}}.waiting{{display:flex;align-items:center;gap:12px}}.waiting small{{display:block;color:#8fb0d6;margin-top:4px}}.spin{{width:25px;height:25px;border-radius:50%;border:3px solid #2c74bb55;border-top-color:#23a8ff;animation:s .8s linear infinite}}@keyframes s{{to{{transform:rotate(360deg)}}}}@media(max-width:520px){{.info,.grid{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap"><section class="hero"><img class="banner" src="/certificate/cover/{token_safe}" alt="Randy Mod"><div class="fade"></div><button id="music" class="music">♫</button><div class="brand"><h1>💎 Randy Certificate</h1><p>PRIVATE DIGITAL DELIVERY // RANDY MOD</p></div></section><section class="panel"><div class="eyebrow">CERTIFICADO DIGITAL</div><div class="info"><div class="item"><small>ESTADO</small><b class="status">{html.escape(status)}</b></div><div class="item"><small>NOMBRE</small><b>{esc(order["display_name"])}</b></div><div class="item"><small>UDID</small><b>{esc(order["udid"])}</b></div><div class="item"><small>DISPOSITIVO</small><b>{esc(str(order["device"] or "iPhone").replace("iphone","iPhone").replace("ipad","iPad"))}</b></div><div class="item"><small>REGISTRADO</small><b>{esc(registered)}</b></div><div class="item"><small>GARANTÍA</small><b>{esc(warranty)}</b></div><div class="item"><small>PLAN</small><b>{esc(f"Plan #{order['plan_id']}")}</b></div><div class="item"><small>CONTRASEÑA P12</small><b>{password}</b></div></div></section>{actions}</div>{music}<script>const a=document.getElementById('bgm'),m=document.getElementById('music');if(a){{a.volume=.72;const p=()=>a.play().catch(()=>{{}});p();document.addEventListener('touchstart',p,{{once:true}});document.addEventListener('pointerdown',p,{{once:true}});m?.addEventListener('click',(e)=>{{e.stopPropagation();if(a.paused)a.play();else a.pause()}})}}document.getElementById('copy')?.addEventListener('click',async()=>{{try{{await navigator.clipboard.writeText({password_js})}}catch(e){{}}}});</script></body></html>'''.encode()
    self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Cache-Control","private, no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)


bot.deliver_certificate = deliver
health.HealthHandler._certificate_page = page
log.info("Premium certificate web + ZIP/component delivery loaded")
