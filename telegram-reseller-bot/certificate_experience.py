from __future__ import annotations

import asyncio
import html
import io
import os
import re
import time
import urllib.request
import zipfile
from PIL import Image, ImageOps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

import bot
from app_signing import SigningError, ipa_info, sign_ipa
from certificate_card import certificate_card

log = bot.log
APPS = {"gbox": "GBox", "esign": "ESign"}
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
        preview = io.BytesIO(certificate_card(order, bot.db.certificate_logo("gbox")))
        preview.name = "tu-certificado.jpg"
        await tg_bot.send_photo(order["user_id"], preview,
            caption="✅ <b>Tu certificado está listo.</b> Descarga tus archivos o elige GBox o ESign para instalar.",
            parse_mode=ParseMode.HTML, reply_markup=delivery_menu(order))
        bot.db.mark_certificate_delivered(order_id)
        _retry_after.pop(order_id, None)
    except Exception as exc:
        log.warning("No se pudo avisar del certificado %s: %s", order_id, exc)
        _retry_after[order_id] = time.monotonic() + 60
    finally:
        _busy.discard(order_id)


bot.deliver_certificate = deliver
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
        if key in _signing:
            await query.answer("La firma ya está en curso", show_alert=True)
            return
        _signing.add(key)
        await query.answer("Preparando firma privada…")
        status_message = await query.message.reply_text(f"⏳ Firmando {APPS[kind]} para tu dispositivo. Puede tardar unos minutos.")
        try:
            source = bot.db.certificate_ipa(kind)
            if not source and kind == "gbox":
                await status_message.edit_text("⏳ Descargando GBox oficial para preparar tu instalación…")
                def load_gbox():
                    request = urllib.request.Request("https://cdn.gbox.run/d/apps/GBox_v6.1.2.ipa",
                                                     headers={"User-Agent": "RandyCertificates/1.0"})
                    with urllib.request.urlopen(request, timeout=35) as response:
                        payload = response.read(19 * 1024 * 1024 + 1)
                    bundle_id, version = ipa_info(payload)
                    bot.db.set_certificate_ipa("gbox", payload, bundle_id, version)
                await asyncio.to_thread(load_gbox)
                source = bot.db.certificate_ipa(kind)
                await status_message.edit_text("⏳ GBox cargada. Firmando para tu dispositivo…")
            if not source:
                raise SigningError("ESign aún no está cargada. Pide al administrador que suba su IPA como documento.")
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
    install_button = (InlineKeyboardButton("📲 Instalar desde Safari", url=f"{base}/certificate/install/{order['install_token']}")
                      if bot.db.signed_certificate_app(order_id, action) else
                      InlineKeyboardButton(f"⚡ Preparar instalación de {name}", callback_data=f"certapp:sign_{action}:{order_id}"))
    other = "esign" if action == "gbox" else "gbox"
    rows = [[install_button],
            [InlineKeyboardButton("📥 Obtener certificado", callback_data=f"certapp:files:{order_id}")],
            [InlineKeyboardButton(f"🔄 Ver {APPS[other]}", callback_data=f"certapp:{other}:{order_id}")]]
    if base.startswith("https://"):
        rows.append([InlineKeyboardButton("🌐 Mi certificado y archivos", url=f"{base}/certificate/install/{order['install_token']}")])
    markup = InlineKeyboardMarkup(rows)
    caption = (f"<b>{name} · tu certificado</b>\n"
               "Toca Preparar instalación para firmar la app con tu certificado. "
               "Después abre tu página privada en Safari y toca Instalar.\n"
               "🔐 Guarda tus archivos y tu enlace en privado.")
    logo = bot.db.certificate_logo(action)
    picture = io.BytesIO(certificate_card(order, logo, name))
    picture.name = "tu-certificado.jpg"
    await query.message.reply_photo(picture, caption=caption,
                                    parse_mode=ParseMode.HTML, reply_markup=markup)


bot.callback = certificate_callback
_original_file_buttons = bot.certificate_file_buttons


def certificate_buttons_for_existing_order(order):
    if order["status"] == "completed" and order["download_url"]:
        return delivery_menu(order)
    return _original_file_buttons(order)


bot.certificate_file_buttons = certificate_buttons_for_existing_order
log.info("Premium certificate web + ZIP/component delivery loaded")
