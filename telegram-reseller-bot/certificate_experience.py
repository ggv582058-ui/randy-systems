from __future__ import annotations

import asyncio
import html
import io
import json
import os
import re
import time
import zipfile
from PIL import Image, ImageOps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

import bot
import health
from app_signing import SigningError, sign_ipa

log = bot.log
APPS = {"gbox": "GBox", "esign": "ESign"}
APP_SOURCES = {
    "gbox": ("📦 Descargar GBox v6.1.2 · requiere firma", "https://cdn.gbox.run/d/apps/GBox_v6.1.2.ipa"),
    "esign": ("📖 Ver descarga y guía ESign", "https://github.com/qbap/Esign-IPA-Installer"),
}

_busy = set()
_retry_after = {}
_signing = set()


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
                if z.getinfo(name).file_size > 12 * 1024 * 1024:
                    continue
                if p12 is None and low.endswith((".p12", ".pfx")):
                    p12 = (name.rsplit("/", 1)[-1], z.read(name))
                elif mobile is None and low.endswith((".mobileprovision", ".provisionprofile")):
                    mobile = (name.rsplit("/", 1)[-1], z.read(name))
                if p12 and mobile:
                    break
    except Exception as exc:
        log.warning("No se pudieron extraer componentes: %s", exc)
    return p12, mobile


def delivery_menu(order):
    order_id = int(order["id"])
    rows = [[InlineKeyboardButton("📥 Obtener certificado", callback_data=f"certapp:files:{order_id}")],
            [InlineKeyboardButton("🟩 GBox", callback_data=f"certapp:gbox:{order_id}"),
             InlineKeyboardButton("🔷 ESign", callback_data=f"certapp:esign:{order_id}")]]
    base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
    if base.startswith("https://"):
        rows.append([InlineKeyboardButton("🌐 Abrir mi página privada", url=f"{base}/certificate/install/{order['install_token']}")])
    return InlineKeyboardMarkup(rows)


async def send_files(tg_bot, order):
    data = await asyncio.to_thread(bot.chungchi.download, order["download_url"])
    if len(data) > 45 * 1024 * 1024 or not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("Paquete ZIP no disponible")
    name = _safe(str(order["display_name"] or "certificate"))
    stream = io.BytesIO(data)
    stream.name = f"{name}.zip"
    await tg_bot.send_document(order["user_id"], stream,
        caption="📦 <b>Tu certificado · ZIP completo</b>\nGuarda estos archivos solo en tu dispositivo.",
        parse_mode=ParseMode.HTML)
    p12, mobile = _components(data)
    for kind, component, caption in (("p12", p12, "🔐 Certificado P12"),
                                     ("mobileprovision", mobile, "📲 MobileProvision")):
        if component:
            stream = io.BytesIO(component[1])
            stream.name = component[0]
            logo = bot.db.certificate_logo(kind)
            thumbnail = None
            if logo:
                try:
                    with Image.open(io.BytesIO(logo)) as image:
                        preview = ImageOps.fit(image.convert("RGB"), (256, 256))
                        thumb = io.BytesIO()
                        preview.save(thumb, format="JPEG", quality=82)
                        thumb.seek(0)
                        thumb.name = "logo.jpg"
                        thumbnail = thumb
                except Exception:
                    log.warning("Logo inválido para %s", kind)
            await tg_bot.send_document(order["user_id"], stream, caption=caption, thumbnail=thumbnail)
    await tg_bot.send_message(order["user_id"],
        f"🔑 Contraseña P12: <code>{html.escape(str(order['p12_password']))}</code>\n"
        "Elige GBox o ESign para ver cómo usar tus archivos.",
        parse_mode=ParseMode.HTML, reply_markup=delivery_menu(order))


async def deliver(tg_bot, order):
    if order["status"] != "completed" or not order["download_url"]:
        return
    order_id = int(order["id"])
    if order_id in _busy or time.monotonic() < _retry_after.get(order_id, 0):
        return
    _busy.add(order_id)
    try:
        await tg_bot.send_message(order["user_id"],
            "✅ <b>CERTIFICADO LISTO</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"📱 Dispositivo: <b>{html.escape(str(order['device']))}</b>\n"
            f"🆔 UDID: <code>{html.escape(str(order['udid']))}</code>\n\n"
            "Toca <b>Obtener certificado</b> para recibir P12 y MobileProvision aquí mismo. "
            "También puedes abrir tu página privada.",
            parse_mode=ParseMode.HTML, reply_markup=delivery_menu(order))
        bot.db.mark_certificate_delivered(order_id)
        _retry_after.pop(order_id, None)
    except Exception as exc:
        log.warning("No se pudo avisar del certificado %s: %s", order_id, exc)
        _retry_after[order_id] = time.monotonic() + 60
    finally:
        _busy.discard(order_id)


def page(self, token):
    server = self.server
    order = server.certificate_lookup(token) if server.certificate_lookup else None
    if not order:
        self.send_error(404, "Enlace inválido o expirado")
        return
    ready = order["status"] == "completed" and bool(order["download_url"])
    esc = lambda value: html.escape(str(value or "—"), quote=True)
    labels = {"completed": "LISTO PARA USAR", "processing": "PREPARANDO", "pending": "PREPARANDO",
              "submitting": "REGISTRANDO", "review": "EN REVISIÓN", "failed": "REVISIÓN NECESARIA"}
    status = labels.get(str(order["status"]), "EN PROCESO")
    token_safe = html.escape(token, quote=True)
    if ready:
        actions = '''<section class="glass files" id="files"><div class="section-kicker">02 / ARCHIVOS PERSONALES</div>
        <h2>Tu kit de certificado</h2><p>Baja el paquete completo o cada archivo por separado. Si el navegador de Telegram no lo guarda, usa el botón del bot «Obtener certificado» o abre este enlace en Safari.</p>
        <a class="download major" href="/certificate/download/__TOKEN__"><span class="ico">↓</span><span><b>Descargar ZIP completo</b><small>P12 + MobileProvision</small></span><span>↗</span></a>
        <div class="file-grid"><a class="download" href="/certificate/component/__TOKEN__/p12"><span class="ico">⌁</span><span><b>Certificado P12</b><small>Identidad de firma</small></span></a>
        <a class="download" href="/certificate/component/__TOKEN__/mobileprovision"><span class="ico">▣</span><span><b>MobileProvision</b><small>Perfil del dispositivo</small></span></a></div>
        <button class="secret" id="copy-password" type="button"><span>🔑 Contraseña P12</span><span id="secret-label">Tocar para copiar · ••••••••</span></button>
        </section><section class="glass" id="apps"><div class="section-kicker">03 / TU APP</div><h2>Elige cómo firmar</h2>
        <p>Importa los archivos en tu app de firma. Elige una para ver los pasos.</p>
        <div class="app-grid"><button class="app selected" data-app="GBox"><span>▣</span>GBox</button><button class="app" data-app="ESign"><span>✍</span>ESign</button></div>
        <div class="guide"><div class="guide-title">PASOS PARA <b id="selected-app">GBox</b></div>
        <div class="step"><em>01</em><span>Descarga el P12 y el MobileProvision de esta página.</span></div>
        <div class="step"><em>02</em><span>Abre <b class="app-name">GBox</b> y busca la opción de importar certificados.</span></div>
        <div class="step"><em>03</em><span>Importa ambos archivos y usa la contraseña P12 que copiaste arriba.</span></div>
        <div class="step"><em>04</em><span>Selecciona tu IPA en <b class="app-name">GBox</b> y sigue sus instrucciones de firma.</span></div></div></section>'''.replace("__TOKEN__", token_safe)
    else:
        actions = '<section class="glass pending"><div class="spinner"></div><div><b>Estamos preparando tus archivos</b><p>Esta página se actualizará sola. Puedes volver con el mismo enlace privado.</p></div></section>'
    template = '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#030d20"><title>Randy Mod · Certificado</title>__REFRESH__<style>
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#030a18;color:#f0f7ff;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-x:hidden}body:before{content:"";position:fixed;inset:0;background:radial-gradient(circle at 0 25%,#1169da48,transparent 38%),radial-gradient(circle at 100% 72%,#7139ee38,transparent 38%);pointer-events:none}.droplets{position:fixed;inset:0;pointer-events:none;overflow:hidden}.droplets i{position:absolute;width:12px;height:24px;border:1px solid #9bddff80;border-radius:70% 15% 70% 15%;box-shadow:inset 2px 2px 6px #b9e9ff88,0 0 14px #37a7ff70;transform:rotate(24deg);animation:float 9s linear infinite}.droplets i:nth-child(1){left:9%;top:105%;animation-delay:-1s}.droplets i:nth-child(2){left:28%;top:105%;animation-delay:-5s}.droplets i:nth-child(3){left:72%;top:105%;animation-delay:-3s}.droplets i:nth-child(4){left:92%;top:105%;animation-delay:-7s}@keyframes float{to{top:-8%;transform:translateX(38px) rotate(34deg)}}.wrap{position:relative;width:min(100%,790px);margin:auto;padding:14px 14px 72px}.hero{position:relative;min-height:430px;border:1px solid #92cfff6b;border-radius:34px;overflow:hidden;background:#0b244c;box-shadow:0 20px 65px #005bf03b}.hero img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}.hero:after{content:"";position:absolute;inset:0;background:linear-gradient(0deg,#031025 2%,#03102522 62%,#03102555)}.hero-content{position:absolute;z-index:2;left:24px;right:24px;bottom:25px}.eyebrow,.section-kicker{color:#9dd9ff;letter-spacing:2.6px;font:700 11px ui-monospace,SFMono-Regular,monospace}.hero h1{font-size:clamp(31px,7vw,57px);letter-spacing:-2px;line-height:1.02;margin:11px 0}.hero p{color:#bdd8f4;margin:0 0 20px}.badge{display:inline-flex;gap:8px;align-items:center;padding:9px 13px;border:1px solid #80d2ff77;border-radius:100px;background:#1264c966;font-size:12px;letter-spacing:1px}.badge:before{content:"";width:7px;height:7px;border-radius:50%;background:#38f4b4;box-shadow:0 0 13px #38f4b4}.glass{margin-top:14px;padding:23px;border:1px solid #77bfff42;border-radius:27px;background:linear-gradient(130deg,#163965a8,#091935d9);box-shadow:inset 0 1px #d9f3ff30,0 16px 40px #020a2280;backdrop-filter:blur(20px)}h2{margin:9px 0;font-size:25px;letter-spacing:-.7px}.glass p{color:#aac3e2;font-size:14px;line-height:1.5;margin:7px 0 17px}.details{display:grid;grid-template-columns:1fr 1fr;gap:9px}.detail{padding:14px;background:#071b37bb;border:1px solid #80bdff26;border-radius:17px;min-width:0}.detail small{display:block;color:#8cb7de;font-size:11px;letter-spacing:.8px;margin-bottom:7px}.detail strong{display:block;font-size:14px;overflow-wrap:anywhere}.download{display:flex;align-items:center;gap:13px;text-decoration:none;color:white;padding:15px;border:1px solid #7fc9ff50;border-radius:17px;background:#0a2950;margin-top:10px;transition:transform .2s,background .2s}.download:hover,.app:hover{transform:translateY(-2px);background:#15477d}.download.major{background:linear-gradient(115deg,#075ec9,#147fee);box-shadow:0 10px 27px #0076ff3b}.download>span:nth-child(2){flex:1}.download b,.download small{display:block}.download small{color:#bfddff;font-size:12px;margin-top:3px}.ico{font-size:25px}.file-grid,.app-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.secret{width:100%;display:flex;justify-content:space-between;gap:12px;margin-top:12px;padding:15px;color:#e1f2ff;background:#071a35;border:1px solid #468bcc77;border-radius:16px;font:inherit;text-align:left}.secret span:last-child{font-size:12px;color:#89b6e2}.app-grid{grid-template-columns:repeat(3,1fr)}.app{border:1px solid #75bcff69;border-radius:18px;background:#0a2751;color:#f5faff;padding:20px 5px;font-weight:700;font-size:13px;font-family:inherit;cursor:pointer;transition:transform .2s,background .2s}.app span{display:block;font-size:30px;margin-bottom:8px;color:#61c4ff}.app.selected{background:linear-gradient(150deg,#075ad5,#1f8ffd);border-color:#bce7ff}.guide{margin-top:17px;border-radius:20px;background:#06182e;padding:17px}.guide-title{font:700 12px ui-monospace,SFMono-Regular,monospace;color:#96d6ff;letter-spacing:1px}.step{display:flex;gap:15px;align-items:flex-start;margin-top:16px;font-size:14px;line-height:1.4;color:#d5eaff}.step em{font:700 14px ui-monospace,SFMono-Regular,monospace;color:#56c6ff}.pending{display:flex;align-items:center;gap:18px}.spinner{width:29px;height:29px;border-radius:50%;border:3px solid #508ce67a;border-top-color:#76d8ff;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.footer{display:flex;align-items:center;justify-content:space-between;margin:25px 5px;color:#7ca7d1;font-size:12px}.music{border:1px solid #6aaafa72;border-radius:100px;background:#15395d;color:white;padding:10px 13px}.hint{font-size:12px;color:#8db9e0;margin:8px 4px}@media(max-width:500px){.hero{min-height:390px}.glass{padding:19px}.file-grid{grid-template-columns:1fr}.app-grid{grid-template-columns:repeat(2,1fr)}.details{grid-template-columns:1fr 1fr}.secret{flex-direction:column}.hero-content{left:20px;right:20px}}@media(prefers-reduced-motion:reduce){.droplets i{animation:none}}
    </style></head><body><div class="droplets"><i></i><i></i><i></i><i></i></div><main class="wrap"><section class="hero"><img src="/certificate/cover/__TOKEN__" alt="Portada Randy Mod"><div class="hero-content"><div class="eyebrow">RANDY MOD / ENTREGA PRIVADA</div><h1>Tu certificado,<br>listo para usar.</h1><p>Archivos, guía y acceso desde un solo lugar.</p><div class="badge">__STATUS__</div></div></section>
    <section class="glass"><div class="section-kicker">01 / INFORMACIÓN</div><h2>Datos del certificado</h2><div class="details"><div class="detail"><small>NOMBRE</small><strong>__NAME__</strong></div><div class="detail"><small>DISPOSITIVO</small><strong>__DEVICE__</strong></div><div class="detail"><small>UDID</small><strong>__UDID__</strong></div><div class="detail"><small>REGISTRADO</small><strong>__DATE__</strong></div><div class="detail"><small>GARANTÍA RESTANTE</small><strong>__WARRANTY__</strong></div><div class="detail"><small>PLAN</small><strong>#__PLAN__</strong></div></div></section>__ACTIONS__
    <section class="glass"><div class="section-kicker">04 / GUÍA RÁPIDA</div><h2>Míralo en 16 segundos</h2><p>Descarga los archivos, impórtalos en tu app y luego selecciona tu IPA.</p><video controls playsinline preload="metadata" style="display:block;width:100%;border-radius:18px;background:#04132a" src="/certificate/tutorial"></video></section>
    <p class="hint">La firma ocurre dentro de la app que elijas. Esta página entrega tus archivos y te guía para importarlos.</p><footer class="footer"><span>© 2026 RANDY MOD</span><button class="music" id="music" type="button">♫ Activar música</button></footer></main><audio id="bgm" loop playsinline src="/certificate/music"></audio>
    <script>const a=document.getElementById('bgm'),m=document.getElementById('music');const play=()=>a.play().then(()=>m.textContent='♫ Pausar música').catch(()=>m.textContent='♫ Toca para activar música');play();document.addEventListener('pointerdown',e=>{if(a.paused&&!e.target.closest('#music'))play()},{once:true});m.addEventListener('click',()=>a.paused?play():(a.pause(),m.textContent='♫ Activar música'));document.querySelectorAll('.app').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.app').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');document.getElementById('selected-app').textContent=b.dataset.app;document.querySelectorAll('.app-name').forEach(x=>x.textContent=b.dataset.app)}));document.getElementById('copy-password')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(__PASSWORD__);document.getElementById('secret-label').textContent='✓ Contraseña copiada'}catch(e){document.getElementById('secret-label').textContent='No se pudo copiar'}});</script></body></html>'''
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(str(order["completed_at"] or order["created_at"]).replace("Z", "+00:00"))
        date = dt.astimezone(timezone.utc).strftime("%d %b %Y")
    except Exception:
        date = "Pendiente"
    body = (template.replace("__TOKEN__", token_safe)
            .replace("__REFRESH__", '' if ready else '<meta http-equiv="refresh" content="20">')
            .replace("__STATUS__", esc(status)).replace("__NAME__", esc(order["display_name"]))
            .replace("__DEVICE__", esc(order["device"])) .replace("__UDID__", esc(order["udid"]))
            .replace("__DATE__", esc(date)).replace("__WARRANTY__", esc(health.HealthHandler._warranty(order)))
            .replace("__PLAN__", esc(order["plan_id"])) .replace("__ACTIONS__", actions)
            .replace("__PASSWORD__", json.dumps(str(order["p12_password"] or "")).replace("<", "\\u003c"))).encode()
    self.send_response(200)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Cache-Control", "private, no-store")
    self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; media-src 'self'")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)


bot.deliver_certificate = deliver
health.HealthHandler._certificate_page = page
_original_callback = bot.callback


async def certificate_callback(update, context):
    query = update.callback_query
    data = query.data or ""
    if not data.startswith("certapp:"):
        return await _original_callback(update, context)
    parts = data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await query.answer("Opción inválida", show_alert=True)
        return
    action, order_id = parts[1], int(parts[2])
    order = bot.db.certificate_order(order_id, query.from_user.id)
    if not order or order["status"] != "completed" or not order["download_url"]:
        await query.answer("Certificado no disponible en tu cuenta", show_alert=True)
        return
    order = bot.db.renew_certificate_link(order_id, query.from_user.id, bot.settings.certificate_link_ttl_hours)
    base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
    if action.startswith("sign_") and action[5:] in APPS:
        kind = action[5:]
        key = (order_id, kind)
        if not base.startswith("https://"):
            await query.answer("Enlace privado HTTPS no configurado", show_alert=True)
            return
        if bot.db.signed_certificate_app(order_id, kind):
            await query.answer("Ya está preparada")
            await query.message.reply_text("✅ Ya puedes abrir tu página privada y tocar Instalar.",
                                           reply_markup=InlineKeyboardMarkup([[
                                               InlineKeyboardButton("🌐 Abrir en Safari · Instalar", url=f"{base}/certificate/install/{order['install_token']}")]]))
            return
        source = bot.db.certificate_ipa(kind)
        if not source:
            await query.answer("La IPA todavía no está cargada. Avisa al administrador.", show_alert=True)
            return
        if key in _signing:
            await query.answer("La firma ya está en curso", show_alert=True)
            return
        _signing.add(key)
        await query.answer("Preparando firma privada…")
        status_message = await query.message.reply_text(f"⏳ Firmando {APPS[kind]} para tu dispositivo. Puede tardar unos minutos.")
        try:
            certificate = await asyncio.to_thread(bot.chungchi.download, order["download_url"])
            signed, bundle_id, version = await asyncio.to_thread(
                sign_ipa, source["ipa"], certificate, order["p12_password"], order["udid"],
                bot.settings.database_path.parent / "signing-cache")
            await asyncio.to_thread(bot.db.set_signed_certificate_app, order_id, kind, signed, bundle_id, version)
            await status_message.edit_text(
                f"✅ <b>{APPS[kind]} v{html.escape(version)} lista para instalar</b>\n"
                "Abre la página privada en Safari y toca <b>Instalar</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🌐 Abrir en Safari · Instalar", url=f"{base}/certificate/install/{order['install_token']}")]]))
        except SigningError as exc:
            await status_message.edit_text(f"⚠️ No se pudo preparar {APPS[kind]}: {exc}")
        except Exception:
            log.exception("Fallo firmando aplicación %s para pedido %s", kind, order_id)
            await status_message.edit_text("⚠️ Error temporal al preparar la IPA. Intenta otra vez más tarde.")
        finally:
            _signing.discard(key)
        return
    if action == "choose":
        await query.answer()
        rows = [[InlineKeyboardButton(name, callback_data=f"certapp:{key}:{order_id}")]
                for key, name in APPS.items()]
        if base.startswith("https://"):
            rows.append([InlineKeyboardButton("🎬 Ver guía en video", url=f"{base}/certificate/tutorial")])
        await query.message.reply_text(
            "📱 <b>Elige dónde usar tu certificado</b>\n"
            "Te mostraré los archivos y pasos para importarlo en esa app.",
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return
    if action == "files":
        await query.answer("Preparando tus archivos…")
        try:
            await send_files(context.bot, order)
        except Exception as exc:
            log.warning("Archivos no enviados en certificado %s: %s", order_id, exc)
            markup = bot.certificate_file_buttons(order)
            await query.message.reply_text(
                "⚠️ No pude enviarte los archivos por Telegram. Abre tu enlace privado y toca Descargar ZIP; "
                "si estás en el navegador integrado, usa Compartir → Abrir en Safari.", reply_markup=markup)
            return
        return
    if action not in APPS:
        await query.answer("Opción inválida", show_alert=True)
        return
    name = APPS[action]
    source_label, source_url = APP_SOURCES[action]
    existing = bot.certificate_file_buttons(order)
    install_button = (InlineKeyboardButton("📲 Instalar desde Safari", url=f"{base}/certificate/install/{order['install_token']}")
                      if bot.db.signed_certificate_app(order_id, action) else
                      InlineKeyboardButton(f"⚡ Preparar instalación de {name}", callback_data=f"certapp:sign_{action}:{order_id}"))
    markup = InlineKeyboardMarkup([[install_button], [InlineKeyboardButton(source_label, url=source_url)]] +
                                  [list(row) for row in existing.inline_keyboard])
    caption = (
        f"📲 <b>{name} · tu certificado</b>\n\n"
        "1. Toca Obtener certificado y guarda tu P12 y MobileProvision.\n"
        f"2. Abre {name} e importa el certificado y el perfil.\n"
        "3. Escribe la contraseña P12 que recibiste en el mensaje privado.\n"
        "4. Selecciona tu IPA dentro de la app y sigue sus pasos para firmar.\n\n"
        "Toca Preparar instalación para firmar esta IPA con tu certificado; después abre el enlace en Safari.\n"
        "🔐 Los archivos son personales. Comparte el enlace solo contigo."
    )
    logo = bot.db.certificate_logo(action)
    if logo:
        picture = io.BytesIO(logo)
        picture.name = f"{action}-logo.jpg"
        await query.message.reply_photo(picture, caption=caption,
                                        parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await query.message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=markup)


bot.callback = certificate_callback
_original_file_buttons = bot.certificate_file_buttons


def certificate_buttons_for_existing_order(order):
    if order["status"] == "completed" and order["download_url"]:
        return delivery_menu(order)
    return _original_file_buttons(order)


bot.certificate_file_buttons = certificate_buttons_for_existing_order
log.info("Premium certificate web + ZIP/component delivery loaded")
