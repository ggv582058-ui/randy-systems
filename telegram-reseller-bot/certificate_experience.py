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

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaDocument, WebAppInfo
from telegram.constants import ParseMode
from telegram.error import BadRequest

import bot
from app_signing import SigningError, ipa_info, sign_ipa
from certificate_card import app_tile, file_icon

log = bot.log
APPS = {"gbox": "GBox", "esign": "ESign"}
STATUS_ICONS = (
    ("✅ Estado:", "5931409969613116639", "✅ Estado:"),
    ("👤 Nombre:", "5942826671290715541", "👤 Nombre:"),
    ("🆔 UDID:", "5877540355187937244", "🆔 UDID:"),
    ("📅 Registrado:", "5967782394080530708", "📅 Registrado:"),
    ("🛡️ Garantía estimada:", "5778139491810155937", "🛡️ Garantía estimada:"),
    ("⚡ Plan:", "5278343321624787703", "⚡ Plan:"),
    ("📱 Equipo:", "5776375003280838798", "📱 Equipo:"),
)
_busy = set()
_retry_after = {}
_signing = set()


def _safe(value):
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", value or "certificate").strip(" ._")[:80] or "certificate"


async def send_status(tg_bot, order, reply_markup=None):
    plain = bot.certificate_status_text(order)
    decorated = plain
    for original, emoji_id, replacement in STATUS_ICONS:
        symbol, label = replacement.split(" ", 1)
        decorated = decorated.replace(original, f'<tg-emoji emoji-id="{emoji_id}">{symbol}</tg-emoji> {label}')
    try:
        await tg_bot.send_message(order["user_id"], decorated, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    except Exception as exc:
        if decorated == plain or not any(word in str(exc).lower() for word in ("emoji", "entity", "parse")):
            raise
        await tg_bot.send_message(order["user_id"], plain, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


def install_page(base: str, order, kind: str) -> str:
    return f"{base}/certificate/install/{order['install_token']}?app={kind}"


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
    return InlineKeyboardMarkup([[bot.emoji_button("Obtener certificado", "get_certificate",
        callback_data=f"certapp:replay:{order_id}")]])


def app_menu(order, kind="gbox"):
    base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
    order_id = int(order["id"])
    signed = bot.db.signed_certificate_app(order_id, kind)
    rows = []
    if signed and base.startswith("https://"):
        rows.append([bot.emoji_button(f"Abrir {APPS[kind]}", f"open_{kind}",
                                         web_app=WebAppInfo(f"{base}/certificate/mini/{order['install_token']}?app={kind}"))])
    else:
        rows.append([bot.emoji_button(f"Preparar {APPS[kind]}", f"prepare_{kind}", callback_data=f"certapp:sign_{kind}:{order_id}")])
    if base.startswith("https://"):
        rows.append([bot.emoji_button("Mi certificado en la web", "web_certificate",
                                      url=f"{base}/certificate/install/{order['install_token']}")])
    return InlineKeyboardMarkup(rows)


async def send_files(tg_bot, order):
    data = await asyncio.to_thread(bot.chungchi.download, order["download_url"])
    if len(data) > 45 * 1024 * 1024 or not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError("Paquete ZIP no disponible")
    p12, mobile = _components(data)
    if not p12 or not mobile:
        raise ValueError("El proveedor todavía no entregó P12 y MobileProvision")
    documents = []
    client_name = bot.safe_certificate_name(str(order["display_name"] or "Certificado")) or "Certificado"
    for kind, component, caption in (("p12", p12, f"P12 · {client_name}"),
                                     ("mobileprovision", mobile, f"Perfil · {client_name}")):
        stream = io.BytesIO(component[1])
        stream.name = f"{client_name}.{'p12' if kind == 'p12' else 'mobileprovision'}"
        logo = bot.db.certificate_logo(kind) or file_icon(kind)
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
        documents.append(InputMediaDocument(stream, caption=bot.developer_text(caption), thumbnail=thumbnail))
    await tg_bot.send_media_group(order["user_id"], documents)
    await tg_bot.send_message(order["user_id"],
        f"Contraseña P12: <code>{html.escape(str(order['p12_password']))}</code>\n"
        "Guarda estos dos archivos en privado.", parse_mode=ParseMode.HTML)


async def send_app_choice(tg_bot, order, kind="gbox"):
    name = APPS[kind]
    picture = io.BytesIO(app_tile(bot.db.certificate_logo(kind), name))
    picture.name = f"{kind}-app.jpg"
    signed = bot.db.signed_certificate_app(int(order["id"]), kind)
    instruction = ("Tu app ya está firmada. Toca Abrir para seguir con la instalación."
                   if signed else f"Toca Preparar {name}; después aparecerá Abrir {name}.")
    await tg_bot.send_photo(order["user_id"], picture,
        caption=f"<b>{name}</b> · {instruction}",
        reply_markup=app_menu(order, kind), parse_mode=ParseMode.HTML)


def app_selector_menu(order, custom_icons=True):
    order_id = int(order["id"])
    base = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
    rows = [[InlineKeyboardButton(
        "GBox" if custom_icons and bot.certificate_emoji("gbox") else "🟩 GBox",
        callback_data=f"certapp:gbox:{order_id}",
        icon_custom_emoji_id=bot.certificate_emoji("gbox") if custom_icons else None,
        style="primary" if custom_icons else None,
    ), InlineKeyboardButton(
        "ESign" if custom_icons and bot.certificate_emoji("esign") else "🔷 ESign",
        callback_data=f"certapp:esign:{order_id}",
        icon_custom_emoji_id=bot.certificate_emoji("esign") if custom_icons else None,
        style="primary" if custom_icons else None,
    )]]
    if base.startswith("https://"):
        rows.append([bot.emoji_button("🌐 Mi certificado en la web", "web_certificate",
                                      url=f"{base}/certificate/install/{order['install_token']}")])
    return InlineKeyboardMarkup(rows)


async def send_app_selector(tg_bot, order):
    text = ("<b>Aplicaciones para tu certificado</b>\n"
            "Elige GBox o ESign para preparar la instalación en tu dispositivo.")
    try:
        await tg_bot.send_message(order["user_id"], text, parse_mode=ParseMode.HTML,
                                  reply_markup=app_selector_menu(order))
    except BadRequest as exc:
        if not any(word in str(exc).lower() for word in ("emoji", "button", "style")):
            raise
        await tg_bot.send_message(order["user_id"], text, parse_mode=ParseMode.HTML,
                                  reply_markup=app_selector_menu(order, custom_icons=False))


async def deliver(tg_bot, order):
    if order["status"] != "completed" or not order["download_url"]:
        return
    order_id = int(order["id"])
    if order_id in _busy or time.monotonic() < _retry_after.get(order_id, 0):
        return
    _busy.add(order_id)
    try:
        await send_status(tg_bot, order, reply_markup=delivery_menu(order))
        bot.db.mark_certificate_delivered(order_id)
        _retry_after.pop(order_id, None)
    except Exception as exc:
        log.warning("No se pudo avisar del certificado %s: %s", order_id, exc)
        _retry_after[order_id] = time.monotonic() + 60
    finally:
        _busy.discard(order_id)


bot.deliver_certificate = deliver
bot.send_certificate_status = send_status
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
            await query.message.reply_text(f"✅ {APPS[kind]} está lista para instalar.", reply_markup=app_menu(order, kind))
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
                f"Abre {APPS[kind]} desde Telegram; si iOS lo solicita, continúa en Safari.",
                parse_mode=ParseMode.HTML,
                reply_markup=app_menu(order, kind))
            try:
                await query.message.edit_reply_markup(reply_markup=app_menu(order, kind))
            except Exception:
                log.info("No se pudo actualizar el botón de instalación del pedido %s", order_id)
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
        await send_app_selector(context.bot, order)
        return
    if action == "replay":
        await query.answer("Enviando tu certificado…")
        try:
            await send_files(context.bot, order)
            await send_app_selector(context.bot, order)
        except Exception as exc:
            log.warning("No se pudo reenviar la entrega completa del pedido %s: %s", order_id, exc)
            await query.message.reply_text("No pude reenviar los archivos. Abre tu página privada para descargarlos.",
                                           reply_markup=delivery_menu(order))
        return
    if action in ("import_gbox", "import_esign"):
        kind = action.split("_", 1)[1]
        await query.answer("Enviando P12 y perfil…")
        try:
            await send_files(context.bot, order)
            await context.bot.send_message(order["user_id"],
                f"Abre los archivos P12 y MobileProvision desde Telegram y compártelos con {APPS[kind]} "
                "si aparece en Compartir. También puedes guardarlos en Archivos e importarlos desde la app. "
                "Usa la contraseña P12 que acabo de enviarte.")
        except Exception as exc:
            log.warning("No se pudieron reenviar archivos para %s en pedido %s: %s", kind, order_id, exc)
            await query.message.reply_text("No pude reenviar los archivos. Prueba de nuevo o abre tu página privada.")
        return
    if action == "files":
        await query.answer("Preparando tus archivos…")
        try:
            await send_files(context.bot, order)
            await send_app_selector(context.bot, order)
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
    await send_app_choice(context.bot, order, action)


bot.callback = certificate_callback
_original_file_buttons = bot.certificate_file_buttons


def certificate_buttons_for_existing_order(order):
    if order["status"] == "completed" and order["download_url"]:
        return delivery_menu(order)
    return _original_file_buttons(order)


bot.certificate_file_buttons = certificate_buttons_for_existing_order
log.info("Premium certificate web + ZIP/component delivery loaded")
