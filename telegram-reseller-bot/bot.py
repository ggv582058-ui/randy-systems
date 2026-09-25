from __future__ import annotations

import asyncio
import hashlib
import html
import io
import json
import logging
import os
import re
import secrets
import signal
import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, MessageEntity, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from config import load_settings
from chungchi_api import ChungChiClient, ChungChiError
from database import Database, InsufficientBalance, NotApproved, NotFound, OutOfStock, ProductRestricted, StoreError
from health import start_health_server
from zentry_api import ZentryClient, ZentryError


logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("randy-reseller")
settings = load_settings()
db = Database(settings.database_path)
zentry = ZentryClient(
    settings.zentry_base_url,
    settings.zentry_seller_key,
    settings.zentry_seller_secret,
)
chungchi = ChungChiClient(settings.chungchi_base_url, settings.chungchi_api_key)
_delivery_in_progress: set[int] = set()
_delivery_retry_after: dict[int, float] = {}
_delivery_notice_sent: set[int] = set()


ADMIN_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("📦 Productos"), KeyboardButton("🔑 Añadir keys")],
     [KeyboardButton("📎 Archivos"), KeyboardButton("🎨 Multimedia")],
     [KeyboardButton("➕ Crear socio"), KeyboardButton("👥 Revendedores")],
     [KeyboardButton("💳 Recargas"), KeyboardButton("📢 Anuncios")],
     [KeyboardButton("⚡ API Zentry"), KeyboardButton("🛡️ Control keys")],
     [KeyboardButton("📊 Estadísticas"), KeyboardButton("🌐 Idioma / Language")]],
    resize_keyboard=True,
)
ADMIN_MENU_EN = ReplyKeyboardMarkup(
    [[KeyboardButton("📦 Products"), KeyboardButton("🔑 Add keys")],
     [KeyboardButton("📎 Files"), KeyboardButton("🎨 Media")],
     [KeyboardButton("➕ Create partner"), KeyboardButton("👥 Resellers")],
     [KeyboardButton("💳 Top-ups"), KeyboardButton("📢 Announcements")],
     [KeyboardButton("⚡ Zentry API"), KeyboardButton("🛡️ Key control")],
     [KeyboardButton("📊 Statistics"), KeyboardButton("🌐 Language / Idioma")]],
    resize_keyboard=True,
)
VIP_ADMIN_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("🛡️ Control keys")], [KeyboardButton("🌐 Idioma / Language")]], resize_keyboard=True
)
VIP_ADMIN_MENU_EN = ReplyKeyboardMarkup(
    [[KeyboardButton("🛡️ Key control")], [KeyboardButton("🌐 Language / Idioma")]], resize_keyboard=True
)
USER_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("🍎 Certificado iOS"), KeyboardButton("🔑 Use Key")],
     [KeyboardButton("🔍 Check UDID"), KeyboardButton("⚙️ Settings")],
     [KeyboardButton("🛒 Comprar keys"), KeyboardButton("💳 Recargar saldo")],
     [KeyboardButton("🔑 Mis keys"), KeyboardButton("🔍 Consultar key")],
     [KeyboardButton("👤 Mi cuenta"), KeyboardButton("🧾 Historial")],
     [KeyboardButton("🆘 Soporte"), KeyboardButton("🌐 Idioma / Language")],
    ],
    resize_keyboard=True,
)
USER_MENU_EN = ReplyKeyboardMarkup(
    [[KeyboardButton("🍎 iOS Certificate"), KeyboardButton("🔑 Use Key")],
     [KeyboardButton("🔍 Check UDID"), KeyboardButton("⚙️ Settings")],
     [KeyboardButton("🛒 Buy keys"), KeyboardButton("💳 Add balance")],
     [KeyboardButton("🔑 My keys"), KeyboardButton("🔍 Check key")],
     [KeyboardButton("👤 My account"), KeyboardButton("🧾 History")],
     [KeyboardButton("🆘 Support"), KeyboardButton("🌐 Language / Idioma")]],
    resize_keyboard=True,
)
CERTIFICATE_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("👋 Welcome!")],
     [KeyboardButton("🍎 Certificado iOS")],
     [KeyboardButton("🔍 Check UDID"), KeyboardButton("🔑 Use Key")],
     [KeyboardButton("⚙️ Settings")]],
    resize_keyboard=True,
)
CERTIFICATE_MENU_EN = ReplyKeyboardMarkup(
    [[KeyboardButton("👋 Welcome!")],
     [KeyboardButton("🍎 iOS Certificate")],
     [KeyboardButton("🔍 Check UDID"), KeyboardButton("🔑 Use Key")],
     [KeyboardButton("⚙️ Settings")]],
    resize_keyboard=True,
)
PENDING_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("🔐 Iniciar sesión"), KeyboardButton("📨 Solicitar acceso")],
     [KeyboardButton("🌐 Idioma / Language")]], resize_keyboard=True
)
PENDING_MENU_EN = ReplyKeyboardMarkup(
    [[KeyboardButton("🔐 Sign in"), KeyboardButton("📨 Request access")],
     [KeyboardButton("🌐 Language / Idioma")]], resize_keyboard=True
)


def language_of(user) -> str:
    return user["language"] if user and user["language"] in ("es", "en") else "es"


def is_vip_row(user) -> bool:
    return bool(user and user["role"] == "reseller" and user["tier"] == "vip")


def user_menu(language: str):
    return USER_MENU_EN if language == "en" else USER_MENU


def certificate_menu(language: str):
    return CERTIFICATE_MENU_EN if language == "en" else CERTIFICATE_MENU


def pending_menu(language: str):
    return PENDING_MENU_EN if language == "en" else PENDING_MENU


def admin_menu(user):
    language = language_of(user)
    if user["role"] == "admin":
        return ADMIN_MENU_EN if language == "en" else ADMIN_MENU
    return VIP_ADMIN_MENU_EN if language == "en" else VIP_ADMIN_MENU


def money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def product_name_html(product) -> str:
    return product["name_html"] or html.escape(product["name"])


def custom_emoji_id(message) -> str:
    return next((entity.custom_emoji_id for entity in (message.entities or ())
                 if entity.type == MessageEntity.CUSTOM_EMOJI), "")


def parse_amount(value: str) -> int:
    try:
        amount = Decimal(value.replace("$", "").replace(",", "").strip())
        cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        raise ValueError("Cantidad inválida")
    if cents <= 0 or cents > 10_000_000:
        raise ValueError("Cantidad fuera de rango")
    return cents


def format_date(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


def remaining_time(expires_at: str) -> tuple[str, bool]:
    seconds = int((datetime.fromisoformat(expires_at) - datetime.now(timezone.utc)).total_seconds())
    if seconds <= 0:
        return "Expirada", False
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"{days}d {hours}h {minutes}m", True


async def notify_key_api(sale: dict, user_id: int) -> None:
    if not settings.key_api_url:
        return
    payload = json.dumps({
        "event": "key_purchased",
        "order_id": sale["order_id"],
        "telegram_user_id": user_id,
        "product": sale["product_name"],
        "key": sale["key"],
        "duration_days": sale["duration_days"],
        "expires_at": sale["expires_at"],
    }).encode()

    def post() -> None:
        headers = {"Content-Type": "application/json"}
        if settings.key_api_token:
            headers["Authorization"] = f"Bearer {settings.key_api_token}"
        request = urllib.request.Request(settings.key_api_url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 300:
                raise RuntimeError(f"API respondió {response.status}")

    try:
        await asyncio.to_thread(post)
    except Exception as exc:
        log.warning("No se pudo notificar al API de keys: %s", exc)


def current_user(update: Update):
    tg = update.effective_user
    return db.ensure_user(tg.id, tg.username, tg.full_name, tg.id in settings.admin_ids)


def is_admin(user_id: int) -> bool:
    row = db.user(user_id)
    return bool(row and row["role"] == "admin")


def can_control_keys(user_id: int) -> bool:
    row = db.user(user_id)
    return bool(row and (row["role"] == "admin" or is_vip_row(row)))


def panel(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.application.bot_data.get("panel", "reseller")


def reseller_bot(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data.get("reseller_bot", context.bot)


def admin_bot(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data.get("admin_bot", context.bot)


async def send_home(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str | None = None) -> None:
    user = current_user(update)
    language = language_of(user)
    chat = update.effective_chat
    if panel(context) == "admin":
        if not can_control_keys(update.effective_user.id):
            await chat.send_message("⛔ This bot is private." if language == "en" else "⛔ Este bot es privado.")
            return
        if note:
            text = note
        elif user["role"] == "admin":
            text = (f"🛡️ <b>{html.escape(settings.store_name)}</b>\n━━━━━━━━━━━━━━━━━━\n"
                    + ("⚙️ <b>ADMINISTRATION CENTER</b>\nManage products, partners, balances and announcements."
                       if language == "en" else
                       "⚙️ <b>CENTRO DE ADMINISTRACIÓN</b>\nAdministra productos, socios, saldos y anuncios."))
        else:
            text = (f"💎 <b>{html.escape(settings.store_name)} · VIP</b>\n━━━━━━━━━━━━━━━━━━\n"
                    + ("Limited license controls: check, reset, ban and unban."
                       if language == "en" else
                       "Control limitado de licencias: consultar, resetear, bloquear y desbloquear."))
        await chat.send_message(text, reply_markup=admin_menu(user), parse_mode=ParseMode.HTML)
    elif user["role"] in ("reseller", "admin"):
        rank = "Admin" if user["role"] == "admin" else ("VIP Partner" if is_vip_row(user) and language == "en" else ("Socio VIP" if is_vip_row(user) else ("Regular Partner" if language == "en" else "Socio Regular")))
        text = note or (f"💎 <b>{html.escape(settings.store_name)}</b>\n━━━━━━━━━━━━━━━━━━\n"
                        + (f"👤 Verified: <b>{rank}</b>\n💰 Available balance: <b>{money(user['balance_cents'])}</b>\nChoose an option."
                           if language == "en" else
                           f"👤 Rango: <b>{rank}</b>\n💰 Saldo disponible: <b>{money(user['balance_cents'])}</b>\nSelecciona una opción."))
        await chat.send_message(text, reply_markup=user_menu(language), parse_mode=ParseMode.HTML)
    else:
        if language == "en":
            label = "Your request is waiting for review." if user["requested_access"] else "Request access to become a reseller."
            text = f"🔒 <b>Restricted access</b>\n{label}"
        else:
            label = "Tu solicitud está esperando revisión." if user["requested_access"] else "Solicita acceso para entrar como revendedor."
            text = f"🔒 <b>Acceso restringido</b>\n{label}"
        await chat.send_message(text, reply_markup=pending_menu(language), parse_mode=ParseMode.HTML)


async def choose_language(update: Update) -> None:
    keys = InlineKeyboardMarkup([[
        InlineKeyboardButton("🇲🇽 Español", callback_data="lang:es"),
        InlineKeyboardButton("🇺🇸 English", callback_data="lang:en"),
    ]])
    await update.effective_message.reply_text("🌐 Selecciona tu idioma / Choose your language", reply_markup=keys)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await send_home(update, context)


async def notify_access_request(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    tag = f"@{user['username']}" if user["username"] else "Sin username"
    text = (
        "📨 <b>Nueva solicitud de revendedor</b>\n"
        f"Nombre: {html.escape(user['full_name'])}\nUsuario: {html.escape(tag)}\nID: <code>{user['telegram_id']}</code>"
    )
    keys = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Aprobar", callback_data=f"user:approve:{user['telegram_id']}"),
        InlineKeyboardButton("❌ Rechazar", callback_data=f"user:reject:{user['telegram_id']}"),
    ]])
    for admin_id in set(settings.admin_ids) | set(db.admin_ids()):
        try:
            await admin_bot(context).send_message(admin_id, text, reply_markup=keys, parse_mode=ParseMode.HTML)
        except Exception as exc:
            log.warning("No se notificó al admin %s: %s", admin_id, exc)


async def access_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = current_user(update)
    first = db.request_access(user["telegram_id"])
    if first:
        await notify_access_request(context, db.user(user["telegram_id"]))
        await update.effective_message.reply_text("✅ Solicitud enviada. Un administrador debe aprobarte.", reply_markup=PENDING_MENU)
    else:
        await update.effective_message.reply_text("⏳ Tu solicitud ya está pendiente.", reply_markup=PENDING_MENU)


def product_buttons(prefix: str, active_only: bool = True, user_id: int | None = None,
                    custom_icons: bool = True) -> InlineKeyboardMarkup:
    rows = []
    products = db.products_for_user(user_id, active_only=active_only) if user_id else db.products(active_only=active_only)
    for p in products:
        price = p["effective_price_cents"] if user_id else p["price_cents"]
        rows.append([InlineKeyboardButton(
            f"{p['name']} · {money(price)} · Stock {p['stock']}",
            callback_data=f"{prefix}:{p['id']}",
            icon_custom_emoji_id=p["custom_emoji_id"] if prefix == "buy" and custom_icons and p["custom_emoji_id"] else None,
        )])
    return InlineKeyboardMarkup(rows or [[InlineKeyboardButton("Sin productos", callback_data="noop")]])


async def show_buy(update: Update) -> None:
    try:
        await update.effective_message.reply_text(
            "🛒 <b>Selecciona un producto</b>",
            reply_markup=product_buttons("buy", user_id=update.effective_user.id),
            parse_mode=ParseMode.HTML,
        )
    except BadRequest as exc:
        if "emoji" not in str(exc).lower() and "button" not in str(exc).lower():
            raise
        await update.effective_message.reply_text(
            "🛒 <b>Selecciona un producto</b>",
            reply_markup=product_buttons("buy", user_id=update.effective_user.id, custom_icons=False),
            parse_mode=ParseMode.HTML,
        )
    for product in db.products_for_user(update.effective_user.id)[:10]:
        media = db.product_media(product["id"])
        if not media or not media["photo_data"]:
            continue
        photo = io.BytesIO(media["photo_data"])
        photo.name = media["photo_name"] or "product.jpg"
        try:
            await update.effective_message.reply_photo(
                photo,
                caption=f"💎 <b>{product_name_html(product)}</b>\n💵 {money(product['effective_price_cents'])} · "
                        f"⏳ {product['duration_days']} días · 🔑 Stock {product['stock']}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Ver producto", callback_data=f"buy:{product['id']}")]]),
            )
        except BadRequest as exc:
            if "emoji" not in str(exc).lower():
                log.warning("No se pudo mostrar foto del producto %s: %s", product["id"], exc)
                continue
            photo.seek(0)
            await update.effective_message.reply_photo(
                photo, caption=f"💎 {product['name']} · {money(product['effective_price_cents'])}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Ver producto", callback_data=f"buy:{product['id']}")]]),
            )
        except Exception as exc:
            log.warning("No se pudo mostrar foto del producto %s: %s", product["id"], exc)


async def show_products_admin(update: Update) -> None:
    products = db.products(active_only=False)
    lines = ["📦 <b>Catálogo</b>"]
    rows = [[InlineKeyboardButton("➕ Crear producto", callback_data="product:new")]]
    for p in products:
        status = "✅" if p["active"] else "⛔"
        lines.append(
            f"{status} ID {p['id']} · {html.escape(p['name'])} · {money(p['price_cents'])} · "
            f"{p['duration_days']} días · Stock {p['stock']}"
        )
        rows.append([InlineKeyboardButton(
            f"{'Desactivar' if p['active'] else 'Activar'} · {p['name']}", callback_data=f"product:toggle:{p['id']}"
        ), InlineKeyboardButton("✏️ Editar", callback_data=f"product:edit:{p['id']}")])
    await update.effective_message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML)


async def show_resellers(update: Update) -> None:
    pending = db.pending_users()
    approved = db.approved_users()
    lines = [f"👥 <b>Revendedores</b>\nPendientes: {len(pending)} · Aprobados: {len(approved)}"]
    rows = []
    for u in pending:
        label = f"{u['full_name']} ({u['telegram_id']})"
        rows.append([
            InlineKeyboardButton(f"✅ {label}", callback_data=f"user:approve:{u['telegram_id']}"),
            InlineKeyboardButton("❌", callback_data=f"user:reject:{u['telegram_id']}"),
        ])
    for u in approved:
        tag = f"@{u['username']}" if u["username"] else u["full_name"]
        lines.append(f"• {html.escape(tag)} · {money(u['balance_cents'])}")
        rows.append([InlineKeyboardButton(f"⚙️ Administrar {tag}", callback_data=f"partner:manage:{u['telegram_id']}")])
    await update.effective_message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows) if rows else None, parse_mode=ParseMode.HTML
    )


async def show_partner_manager(message, target: int) -> None:
    partner = db.reseller(target)
    if not partner:
        await message.reply_text("❌ Socio no encontrado.")
        return
    tag = f"@{partner['username']}" if partner["username"] else partner["full_name"]
    login = partner["login"] or "Cuenta aprobada manualmente"
    keys = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Agregar saldo", callback_data=f"partner:add:{target}"),
         InlineKeyboardButton("➖ Quitar saldo", callback_data=f"partner:subtract:{target}")],
        [InlineKeyboardButton("💲 Precio especial", callback_data=f"partner:prices:{target}")],
        [InlineKeyboardButton("🔐 Límites de compra", callback_data=f"partner:limits:{target}")],
        [InlineKeyboardButton("💎 Hacer VIP", callback_data=f"partner:tier-vip:{target}"),
         InlineKeyboardButton("👤 Hacer Regular", callback_data=f"partner:tier-regular:{target}")],
        [InlineKeyboardButton("⚠️ Enviar advertencia", callback_data=f"partner:warn:{target}")],
        [InlineKeyboardButton("🚫 Revocar acceso", callback_data=f"user:revoke:{target}")],
    ])
    await message.reply_text(
        f"⚙️ <b>Administrar socio</b>\nNombre: {html.escape(tag)}\n"
        f"Usuario de acceso: <code>{html.escape(login)}</code>\nID: <code>{target}</code>\n"
        f"Rango: <b>{'VIP' if partner['tier'] == 'vip' else 'Regular'}</b>\n"
        f"Saldo: <b>{money(partner['balance_cents'])}</b>",
        reply_markup=keys,
        parse_mode=ParseMode.HTML,
    )


async def show_topups(update: Update) -> None:
    rows = db.pending_topups()
    if not rows:
        await update.effective_message.reply_text("✅ No hay recargas pendientes.")
        return
    for item in rows:
        tag = f"@{item['username']}" if item["username"] else item["full_name"]
        text = f"💳 <b>Recarga #{item['id']}</b>\nUsuario: {html.escape(tag)}\nCantidad: <b>{money(item['amount_cents'])}</b>"
        keys = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Aprobar", callback_data=f"topup:approve:{item['id']}"),
            InlineKeyboardButton("❌ Rechazar", callback_data=f"topup:reject:{item['id']}"),
        ]])
        if item["proof_type"] == "photo":
            if item["proof_blob"]:
                await update.effective_chat.send_photo(io.BytesIO(item["proof_blob"]), caption=text, reply_markup=keys, parse_mode=ParseMode.HTML)
            else:
                await update.effective_chat.send_message(text + "\n⚠️ Comprobante antiguo no disponible.", reply_markup=keys, parse_mode=ParseMode.HTML)
        elif item["proof_type"] == "document":
            if item["proof_blob"]:
                stream = io.BytesIO(item["proof_blob"])
                stream.name = item["proof_name"] or "comprobante"
                await update.effective_chat.send_document(stream, caption=text, reply_markup=keys, parse_mode=ParseMode.HTML)
            else:
                await update.effective_chat.send_message(text + "\n⚠️ Comprobante antiguo no disponible.", reply_markup=keys, parse_mode=ParseMode.HTML)
        else:
            await update.effective_chat.send_message(text + f"\nReferencia: <code>{html.escape(item['proof_value'])}</code>", reply_markup=keys, parse_mode=ParseMode.HTML)


async def show_account(update: Update) -> None:
    u = current_user(update)
    language = language_of(u)
    tag = f"@{u['username']}" if u["username"] else "Sin username"
    rank = "Admin" if u["role"] == "admin" else ("VIP" if is_vip_row(u) else "Regular")
    await update.effective_message.reply_text(
        (f"👤 <b>My account</b>\nID: <code>{u['telegram_id']}</code>\nUser: {html.escape(tag)}\nRank: <b>{rank}</b>\nBalance: <b>{money(u['balance_cents'])}</b>"
         if language == "en" else
         f"👤 <b>Mi cuenta</b>\nID: <code>{u['telegram_id']}</code>\nUsuario: {html.escape(tag)}\nRango: <b>{rank}</b>\nSaldo: <b>{money(u['balance_cents'])}</b>"),
        parse_mode=ParseMode.HTML,
    )


async def show_history(update: Update) -> None:
    language = language_of(current_user(update))
    rows = db.history(update.effective_user.id)
    if not rows:
        await update.effective_message.reply_text("🧾 You do not have any transactions yet." if language == "en" else "🧾 Todavía no tienes movimientos.")
        return
    lines = ["🧾 <b>Recent transactions</b>" if language == "en" else "🧾 <b>Últimos movimientos</b>"]
    for row in rows:
        sign = "+" if row["amount_cents"] > 0 else ""
        lines.append(f"• {row['kind']} · {sign}{money(row['amount_cents'])} · Saldo {money(row['balance_after_cents'])}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def show_my_keys(update: Update) -> None:
    language = language_of(current_user(update))
    rows = db.user_keys(update.effective_user.id)
    if not rows:
        text = "🔑 <b>My keys</b>\nYou have not purchased any keys yet." if language == "en" else "🔑 <b>Mis keys</b>\nTodavía no has comprado ninguna key."
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML)
        return
    for row in rows:
        await send_key_status(update.effective_message, row, language)


def new_certificate_key() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "CERT-" + "-".join(groups)


def valid_udid(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Fa-f0-9-]{20,50}", value.strip()))


def safe_certificate_name(value: str) -> str:
    clean = "".join(c for c in value.strip() if c.isalnum() or c in "-_ ").strip()
    return clean[:40]


async def show_certificate_offer(update: Update) -> None:
    if not chungchi.configured:
        await update.effective_message.reply_text(
            "⚠️ Certificados temporalmente no disponibles. Falta configurar el API en Render."
        )
        return
    try:
        plans, balance = await asyncio.gather(
            asyncio.to_thread(chungchi.plans), asyncio.to_thread(chungchi.balance)
        )
    except ChungChiError as exc:
        await update.effective_message.reply_text(f"⚠️ No pude verificar ChungChi: {html.escape(str(exc))}", parse_mode=ParseMode.HTML)
        return
    plan = next((p for p in plans if int(p.get("id", -1)) == settings.chungchi_plan_id), None)
    if not plan:
        await update.effective_message.reply_text("⚠️ El plan configurado no está disponible en ChungChi.")
        return
    provider_balance = float(balance.get("wallet", 0) or 0)
    provider_cost = float(plan.get("amount", 0) or 0)
    if provider_balance < provider_cost:
        await update.effective_message.reply_text("⚠️ Certificados agotados temporalmente. Contacta al soporte.")
        return
    keys = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Comprar", callback_data="cert:confirm"),
        InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
    ]])
    await update.effective_message.reply_text(
        "🍎 <b>CERTIFICADO iOS</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"💵 Precio: <b>{money(settings.chungchi_sell_price_cents)}</b>\n"
        f"📅 Validez: <b>{html.escape(str(plan.get('validity') or '12 meses'))}</b>\n"
        f"🛡️ Garantía: <b>{html.escape(str(plan.get('warranty') or 'según el plan'))}</b>\n"
        "📦 Incluye <code>.p12</code>, contraseña y <code>.mobileprovision</code>.\n\n"
        "El costo se descontará de tu saldo del bot.",
        reply_markup=keys,
        parse_mode=ParseMode.HTML,
    )


async def begin_certificate_key(update: Update, context: ContextTypes.DEFAULT_TYPE, key_code: str | None = None) -> None:
    if key_code:
        row = db.certificate_key(update.effective_user.id, key_code)
        if not row or row["status"] != "available":
            await update.effective_message.reply_text("❌ Esa key no existe, no te pertenece o ya fue utilizada.")
            return
        context.user_data["flow"] = {"name": "certificate_udid", "certificate_key": row["key_code"]}
        await update.effective_message.reply_text(
            "📱 Envía el <b>UDID</b> del iPhone o iPad.", parse_mode=ParseMode.HTML,
            reply_markup=certificate_menu(language_of(current_user(update)))
        )
        return
    context.user_data["flow"] = {"name": "certificate_key"}
    await update.effective_message.reply_text(
        "🔑 Envía tu key de certificado:", reply_markup=certificate_menu(language_of(current_user(update)))
    )


async def begin_udid_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["flow"] = {"name": "certificate_lookup_udid"}
    await update.effective_message.reply_text(
        "🔍 Envía el UDID que deseas consultar:", reply_markup=certificate_menu(language_of(current_user(update)))
    )


async def show_certificate_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, language: str) -> None:
    context.user_data.pop("flow", None)
    context.user_data.pop("certificate_pending", None)
    if language == "en":
        message = (
            "👋 <b>Welcome to Randy Certificates</b>\n━━━━━━━━━━━━━━━━━━\n"
            "🍎 <b>iOS Certificate:</b> buy a certificate key.\n"
            "🔑 <b>Use Key:</b> enter an unused key and your device UDID.\n"
            "🔍 <b>Check UDID:</b> see the status of your orders.\n\n"
            "Choose an option below to get started."
        )
    else:
        message = (
            "👋 <b>Bienvenido a Randy Certificates</b>\n━━━━━━━━━━━━━━━━━━\n"
            "🍎 <b>Certificado iOS:</b> compra tu key.\n"
            "🔑 <b>Use Key:</b> ingresa una key sin usar y el UDID de tu dispositivo.\n"
            "🔍 <b>Check UDID:</b> consulta el estado de tus pedidos.\n\n"
            "Elige una opción de abajo para comenzar."
        )
    await update.effective_message.reply_text(
        message, parse_mode=ParseMode.HTML, reply_markup=certificate_menu(language)
    )


def certificate_status_text(order) -> str:
    labels = {
        "submitting": "Enviando", "pending": "Procesando", "processing": "Procesando",
        "review": "Verificación", "completed": "Completado", "failed": "Fallido", "cancelled": "Cancelado",
    }
    label = labels.get(order["status"], order["status"])
    return (
        f"🍎 <b>Certificado #{order['id']}</b>\n"
        f"UDID: <code>{html.escape(order['udid'])}</code>\n"
        f"Estado: <b>{html.escape(label)}</b>\n"
        f"Pedido: <code>{html.escape(order['provider_order_code'] or 'pendiente')}</code>"
    )


async def deliver_certificate(bot, order) -> None:
    if order["status"] != "completed" or not order["download_url"]:
        return
    order_id = order["id"]
    if order_id in _delivery_in_progress or time.monotonic() < _delivery_retry_after.get(order_id, 0):
        return
    _delivery_in_progress.add(order_id)
    base_url = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
    install_url = f"{base_url}/certificate/install/{order['install_token']}"
    keys = InlineKeyboardMarkup([[InlineKeyboardButton("📲 Instalar certificado", url=install_url)]])
    try:
        data = await asyncio.to_thread(chungchi.download, order["download_url"])
        stream = io.BytesIO(data)
        stream.name = f"{safe_certificate_name(order['display_name']) or 'certificate'}.zip"
        await bot.send_document(
            order["user_id"], stream,
            caption=(
                "✅ <b>CERTIFICADO LISTO</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"📦 Nombre: <b>{html.escape(order['display_name'])}</b>\n"
                f"🔐 Contraseña P12: <code>{html.escape(order['p12_password'])}</code>\n"
                f"🧾 Pedido: <code>{html.escape(order['provider_order_code'] or '')}</code>"
            ),
            reply_markup=keys,
            parse_mode=ParseMode.HTML,
        )
        db.mark_certificate_delivered(order["id"])
        _delivery_retry_after.pop(order_id, None)
    except Exception as exc:
        log.warning("No se pudo enviar el ZIP del certificado %s: %s", order["id"], exc)
        _delivery_retry_after[order_id] = time.monotonic() + 90
        if order_id not in _delivery_notice_sent:
            _delivery_notice_sent.add(order_id)
            try:
                await bot.send_message(
                    order["user_id"],
                    "✅ Tu certificado está listo. Usa el enlace privado mientras reintento enviarte el ZIP.",
                    reply_markup=keys,
                )
            except Exception:
                log.warning("No se pudo notificar la entrega alternativa del pedido %s", order_id)
    finally:
        _delivery_in_progress.discard(order_id)


async def submit_certificate_order(message, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    flow = context.user_data.get("certificate_pending")
    if not flow:
        await message.reply_text("La solicitud expiró. Pulsa 🔑 Use Key para comenzar de nuevo.")
        return
    install_token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=settings.certificate_link_ttl_hours)).isoformat(timespec="seconds")
    try:
        local = db.create_certificate_order(
            user_id, flow["certificate_key"], settings.chungchi_plan_id,
            flow["udid"], flow["device"], flow["p12_password"], flow["display_name"],
            install_token, expires,
        )
    except StoreError as exc:
        await message.reply_text(f"❌ {html.escape(str(exc))}", parse_mode=ParseMode.HTML)
        return
    context.user_data.pop("certificate_pending", None)
    base_url = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
    status_link = f"{base_url}/certificate/install/{install_token}"
    status_buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Ver estado privado", url=status_link)]]) if base_url.startswith("https://") else None
    status_message = await message.reply_text(
        "⏳ Registrando el pedido con ChungChi. Puedes ver el estado aquí mientras se prepara.",
        reply_markup=status_buttons,
    )
    try:
        provider = await asyncio.to_thread(
            chungchi.create_order, settings.chungchi_plan_id, flow["udid"], flow["device"], flow["p12_password"]
        )
        order = db.attach_provider_order(local["id"], provider)
    except ChungChiError as exc:
        release = exc.status is not None and exc.status < 500 and exc.status != 429
        db.mark_certificate_error(local["id"], str(exc), release)
        if release:
            await status_message.edit_text(f"❌ {html.escape(str(exc))}\nTu key no fue consumida.", parse_mode=ParseMode.HTML)
        else:
            await status_message.edit_text("⚠️ ChungChi no confirmó el pedido. Lo dejé en verificación para evitar un cobro duplicado.")
        return
    await status_message.edit_text(certificate_status_text(order), parse_mode=ParseMode.HTML, reply_markup=status_buttons)
    if order["status"] == "completed":
        await deliver_certificate(context.bot, order)


async def refresh_certificate_order(bot, row) -> None:
    if not row["provider_order_code"]:
        return
    try:
        provider = await asyncio.to_thread(chungchi.order, row["provider_order_code"])
    except ChungChiError as exc:
        log.warning("No se actualizó certificado %s: %s", row["id"], exc)
        return
    updated = db.update_certificate_order(row["provider_order_code"], provider)
    if updated and updated["status"] == "completed" and not updated["delivered_at"]:
        await deliver_certificate(bot, updated)


async def send_key_status(message, row, language: str) -> None:
    if not row["expires_at"]:
        status, active = ("No tracking (old purchase)" if language == "en" else "Sin seguimiento (compra antigua)"), False
    else:
        status, active = remaining_time(row["expires_at"])
    icon = "🟢" if active else "🔴"
    if language == "en":
        text = ("🔐 <b>DIGITAL LICENSE</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"📦 Product: <b>{html.escape(row['name'])}</b>\n"
                f"🔑 Key: <code>{html.escape(row['secret_value'])}</code>\n"
                f"🧾 Reference: <code>#{row['id']}</code>\n"
                f"📅 Purchase date: {format_date(row['created_at'])}\n"
                f"⏳ Duration: {row['duration_days'] or '?'} days\n"
                f"{icon} Time remaining: <b>{status}</b>"
                + (f"\n⌛ Expires: {format_date(row['expires_at'])}" if row["expires_at"] else ""))
    else:
        text = ("🔐 <b>LICENCIA DIGITAL</b>\n━━━━━━━━━━━━━━━━━━\n"
                f"📦 Producto: <b>{html.escape(row['name'])}</b>\n"
                f"🔑 Key: <code>{html.escape(row['secret_value'])}</code>\n"
                f"🧾 Referencia: <code>#{row['id']}</code>\n"
                f"📅 Fecha de compra: {format_date(row['created_at'])}\n"
                f"⏳ Duración: {row['duration_days'] or '?'} días\n"
                f"{icon} Tiempo restante: <b>{status}</b>"
                + (f"\n⌛ Vence: {format_date(row['expires_at'])}" if row["expires_at"] else ""))
    await message.reply_text(text, parse_mode=ParseMode.HTML)


async def begin_key_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    language = language_of(current_user(update))
    context.user_data["flow"] = {"name": "lookup_own_key"}
    await update.effective_message.reply_text(
        "🔍 Send the key to view its purchase date, history and time remaining."
        if language == "en" else
        "🔍 Escribe la key para ver su fecha de compra, historial y tiempo restante."
    )


async def show_stats(update: Update) -> None:
    s = db.stats()
    await update.effective_message.reply_text(
        "📊 <b>Estadísticas</b>\n"
        f"Revendedores: {s['resellers']}\nSolicitudes: {s['pending_users']}\nKeys disponibles: {s['available_keys']}\n"
        f"Ventas: {s['orders']}\nTotal vendido: {money(s['revenue_cents'])}\nRecargas pendientes: {s['pending_topups']}",
        parse_mode=ParseMode.HTML,
    )


async def begin_topup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["flow"] = {"name": "topup_amount"}
    await update.effective_message.reply_text("💳 Escribe la cantidad que deseas recargar. Ejemplo: <code>25.00</code>", parse_mode=ParseMode.HTML)


async def begin_add_keys(update: Update) -> None:
    await update.effective_message.reply_text("🔑 Selecciona el producto:", reply_markup=product_buttons("addkeys", active_only=False))


async def begin_product_file(update: Update) -> None:
    await update.effective_message.reply_text("📎 Selecciona el producto:", reply_markup=product_buttons("addfile", active_only=False))


async def begin_product_media(update: Update) -> None:
    await update.effective_message.reply_text(
        "🎨 <b>Multimedia del producto</b>\nSelecciona el producto para agregar foto o sticker animado:",
        reply_markup=product_buttons("media", active_only=False),
        parse_mode=ParseMode.HTML,
    )


async def begin_zentry_generate(update: Update) -> None:
    if not zentry.configured:
        await update.effective_message.reply_text(
            "⚠️ <b>ZentryAuth todavía no está conectado.</b>\n"
            "Guarda <code>ZENTRY_SELLER_KEY</code> y <code>ZENTRY_SELLER_SECRET</code> en Render. "
            "Nunca los envíes por Telegram ni por este chat.",
            parse_mode=ParseMode.HTML,
        )
        return
    await update.effective_message.reply_text(
        "⚡ <b>Generar keys en ZentryAuth</b>\nSelecciona el producto; se usará su duración configurada:",
        reply_markup=product_buttons("zentrygen", active_only=False),
        parse_mode=ParseMode.HTML,
    )


async def begin_zentry_control(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not zentry.configured:
        await begin_zentry_generate(update)
        return
    context.user_data["flow"] = {"name": "zentry_control_key"}
    await update.effective_message.reply_text("🛡️ Envía la key que deseas consultar o administrar:")


async def run_key_command(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    user = current_user(update)
    language = language_of(user)
    if not can_control_keys(user["telegram_id"]):
        await update.effective_message.reply_text(
            "⛔ Only Admin or VIP partners can use this command."
            if language == "en" else "⛔ Este comando es solo para Admin o Socio VIP."
        )
        return
    if not context.args:
        await update.effective_message.reply_text(f"Uso: /{action} KEY")
        return
    license_key = context.args[0].strip()
    operations = {
        "reset": zentry.reset_hwid,
        "bankey": zentry.ban_license,
        "unbankey": zentry.unban_license,
        "keyinfo": zentry.license_info,
    }
    try:
        result = await asyncio.to_thread(operations[action], license_key)
    except ZentryError as exc:
        await update.effective_message.reply_text(f"❌ {html.escape(str(exc))}", parse_mode=ParseMode.HTML)
        return
    if action == "keyinfo":
        data_result = result.get("data", result)
        pretty = json.dumps(data_result, ensure_ascii=False, indent=2, default=str)[:3500]
        await update.effective_message.reply_text(
            f"🔎 <b>{'License status' if language == 'en' else 'Estado de la licencia'}</b>\n"
            f"<pre>{html.escape(pretty)}</pre>", parse_mode=ParseMode.HTML,
        )
    else:
        label = {"reset": "Reset HWID", "bankey": "Key bloqueada", "unbankey": "Key desbloqueada"}[action]
        await update.effective_message.reply_text(f"✅ {label}")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_key_command(update, context, "reset")


async def ban_key_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_key_command(update, context, "bankey")


async def unban_key_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_key_command(update, context, "unbankey")


async def key_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await run_key_command(update, context, "keyinfo")


async def handle_text_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = current_user(update)
    text = (update.effective_message.text or "").strip()
    admin_panel = panel(context) == "admin"
    if admin_panel and not can_control_keys(update.effective_user.id):
        await update.effective_message.reply_text("⛔ Este bot es privado.")
        return
    if text == "🌐 Idioma / Language":
        await choose_language(update)
        return
    if text in ("📨 Solicitar acceso", "📨 Request access"):
        if admin_panel:
            await send_home(update, context)
            return
        await access_request(update, context)
        return
    if not admin_panel and text in ("🔐 Iniciar sesión", "🔐 Sign in"):
        context.user_data["flow"] = {"name": "partner_login"}
        await update.effective_message.reply_text("👤 Escribe el usuario que te dio el Admin:")
        return
    # Certificate menu buttons must be processed before handle_flow. Otherwise
    # an active UDID/key prompt consumes them as input and the menu seems broken.
    if not admin_panel and user["role"] in ("reseller", "admin"):
        if text == "👋 Welcome!":
            await show_certificate_welcome(update, context, language_of(user))
            return
        if text in ("🍎 Certificado iOS", "🍎 iOS Certificate"):
            context.user_data.pop("flow", None)
            context.user_data.pop("certificate_pending", None)
            await show_certificate_offer(update)
            return
        if text == "🔑 Use Key":
            context.user_data.pop("certificate_pending", None)
            await begin_certificate_key(update, context)
            return
        if text == "🔍 Check UDID":
            context.user_data.pop("certificate_pending", None)
            await begin_udid_lookup(update, context)
            return
        if text == "⚙️ Settings":
            context.user_data.pop("flow", None)
            keys = InlineKeyboardMarkup([[
                InlineKeyboardButton("🌐 Idioma", callback_data="certsettings:language"),
                InlineKeyboardButton("👤 Mi cuenta", callback_data="certsettings:account"),
            ]])
            await update.effective_message.reply_text(
                "⚙️ <b>Settings</b>", reply_markup=keys, parse_mode=ParseMode.HTML
            )
            return
    if await handle_flow(update, context):
        return
    if user["role"] not in ("reseller", "admin"):
        await send_home(update, context)
        return

    if not admin_panel and text in ("🛒 Comprar keys", "🛒 Buy keys"):
        await show_buy(update)
    elif not admin_panel and text in ("💳 Recargar saldo", "💳 Add balance"):
        await begin_topup(update, context)
    elif not admin_panel and text in ("🔑 Mis keys", "🔑 My keys"):
        await show_my_keys(update)
    elif not admin_panel and text in ("🔍 Consultar key", "🔍 Check key"):
        await begin_key_lookup(update, context)
    elif not admin_panel and text in ("👤 Mi cuenta", "👤 My account"):
        await show_account(update)
    elif not admin_panel and text in ("🧾 Historial", "🧾 History"):
        await show_history(update)
    elif not admin_panel and text in ("🆘 Soporte", "🆘 Support"):
        label = "Support" if language_of(user) == "en" else "Soporte"
        await update.effective_message.reply_text(f"🆘 {label}: {settings.support_username}")
    elif admin_panel and can_control_keys(user["telegram_id"]) and text in ("🛡️ Control keys", "🛡️ Key control"):
        await begin_zentry_control(update, context)
    elif admin_panel and user["role"] == "admin" and text in ("📦 Productos", "📦 Products"):
        await show_products_admin(update)
    elif admin_panel and user["role"] == "admin" and text in ("🔑 Añadir keys", "🔑 Add keys"):
        await begin_add_keys(update)
    elif admin_panel and user["role"] == "admin" and text in ("📎 Archivos", "📎 Files"):
        await begin_product_file(update)
    elif admin_panel and user["role"] == "admin" and text in ("🎨 Multimedia", "🎨 Media"):
        await update.effective_message.reply_text(
            "🎨 <b>Fotos del catálogo</b>\nElige dónde quieres cambiar la foto:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 Foto de producto", callback_data="media:products")],
                [InlineKeyboardButton("🍎 Portada del certificado", callback_data="certcover:upload")],
            ]),
        )
    elif admin_panel and user["role"] == "admin" and text in ("⚡ API Zentry", "⚡ Zentry API"):
        await begin_zentry_generate(update)
    elif admin_panel and user["role"] == "admin" and text in ("➕ Crear socio", "➕ Create partner"):
        context.user_data["flow"] = {"name": "partner_create_login"}
        await update.effective_message.reply_text("👤 Escribe el usuario para el socio:")
    elif admin_panel and user["role"] == "admin" and text in ("📢 Anuncios", "📢 Announcements"):
        current = db.daily_announcement()
        status = (f"{'🟢 Activo' if current['enabled'] else '⏸️ Pausado'} · {current['send_time']} (Nueva York)"
                  if current else "Sin anuncio diario")
        await update.effective_message.reply_text(
            f"📢 <b>Anuncios a vendedores</b>\n{status}\n\nEl anuncio diario admite texto, emojis y emoticones.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Enviar ahora", callback_data="announcement:now")],
                [InlineKeyboardButton("🗓️ Programar diario", callback_data="announcement:daily")],
                [InlineKeyboardButton("⏸️ Pausar diario", callback_data="announcement:pause")],
            ]),
        )
    elif admin_panel and user["role"] == "admin" and text in ("👥 Revendedores", "👥 Resellers"):
        await show_resellers(update)
    elif admin_panel and user["role"] == "admin" and text in ("💳 Recargas", "💳 Top-ups"):
        await show_topups(update)
    elif admin_panel and user["role"] == "admin" and text in ("📊 Estadísticas", "📊 Statistics"):
        await show_stats(update)
    elif admin_panel and user["role"] == "admin" and text == "👤 Vista revendedor":
        await update.effective_message.reply_text("La vista del revendedor está en el bot de ventas.")
    else:
        await send_home(update, context)


async def handle_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    flow = context.user_data.get("flow")
    if not flow:
        return False
    message = update.effective_message
    text = (message.text or "").strip()

    if flow["name"] == "certificate_key":
        row = db.certificate_key(message.from_user.id, text)
        if not row or row["status"] != "available":
            await message.reply_text("❌ Key inválida, usada o perteneciente a otra cuenta.")
            return True
        flow["name"], flow["certificate_key"] = "certificate_udid", row["key_code"]
        await message.reply_text("📱 Envía el UDID del iPhone o iPad:")
        return True

    if flow["name"] == "certificate_udid":
        if not valid_udid(text):
            await message.reply_text("❌ UDID inválido. Debe contener únicamente letras A-F, números y guiones.")
            return True
        flow["udid"] = text.upper()
        flow["name"] = "certificate_device"
        keys = InlineKeyboardMarkup([[
            InlineKeyboardButton("📱 iPhone", callback_data="certdevice:iphone"),
            InlineKeyboardButton("▣ iPad", callback_data="certdevice:ipad"),
        ]])
        await message.reply_text("Selecciona el tipo de dispositivo:", reply_markup=keys)
        return True

    if flow["name"] == "certificate_device":
        await message.reply_text("Usa los botones para seleccionar iPhone o iPad.")
        return True

    if flow["name"] == "certificate_password":
        if not 1 <= len(text) <= 64:
            await message.reply_text("❌ La contraseña debe tener entre 1 y 64 caracteres.")
            return True
        flow["p12_password"] = text
        flow["name"] = "certificate_name"
        await message.reply_text("✏️ Escribe el nombre que deseas para el archivo del certificado:")
        return True

    if flow["name"] == "certificate_name":
        display_name = safe_certificate_name(text)
        if not display_name:
            await message.reply_text("❌ Escribe un nombre válido usando letras, números, espacios, guion o guion bajo.")
            return True
        flow["display_name"] = display_name
        context.user_data["certificate_pending"] = dict(flow)
        context.user_data.pop("flow", None)
        keys = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Crear certificado", callback_data="cert:create"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]])
        await message.reply_text(
            "🍎 <b>Confirma los datos</b>\n"
            f"UDID: <code>{html.escape(flow['udid'])}</code>\n"
            f"Dispositivo: <b>{html.escape(flow['device'])}</b>\n"
            f"Nombre: <b>{html.escape(display_name)}</b>\n"
            f"Contraseña P12: <code>{html.escape(flow['p12_password'])}</code>",
            reply_markup=keys,
            parse_mode=ParseMode.HTML,
        )
        return True

    if flow["name"] == "certificate_lookup_udid":
        if not valid_udid(text):
            await message.reply_text("❌ UDID inválido.")
            return True
        rows = db.certificate_orders_for_user(message.from_user.id, text.upper())
        context.user_data.pop("flow", None)
        if not rows:
            await message.reply_text(
                "🔍 No encontré certificados tuyos para ese UDID.",
                reply_markup=certificate_menu(language_of(current_user(update))),
            )
            return True
        for row in rows[:5]:
            row = db.renew_certificate_link(row["id"], message.from_user.id, settings.certificate_link_ttl_hours)
            if row["provider_order_code"] and row["status"] not in ("completed", "failed", "cancelled"):
                await refresh_certificate_order(context.bot, row)
                row = db.certificate_order(row["id"], message.from_user.id)
            buttons = None
            if row["status"] == "completed":
                base_url = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
                buttons = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📲 Instalar certificado", url=f"{base_url}/certificate/install/{row['install_token']}")
                ]])
            await message.reply_text(certificate_status_text(row), reply_markup=buttons, parse_mode=ParseMode.HTML)
        return True

    if flow["name"] == "partner_login":
        flow["name"], flow["login"] = "partner_password", text
        await message.reply_text("🔑 Escribe tu contraseña:")
        return True

    if flow["name"] == "lookup_own_key":
        language = language_of(current_user(update))
        if len(text) < 4 or len(text) > 200:
            await message.reply_text("❌ Invalid key." if language == "en" else "❌ La key no parece válida.")
            return True
        row = db.user_key(message.from_user.id, text)
        context.user_data.pop("flow", None)
        if row:
            await send_key_status(message, row, language)
            return True
        if zentry.configured:
            try:
                result = await asyncio.to_thread(zentry.license_info, text)
                data_result = result.get("data", result)
                pretty = json.dumps(data_result, ensure_ascii=False, indent=2, default=str)[:3000]
                title = "🔎 <b>License status</b>" if language == "en" else "🔎 <b>Estado de la licencia</b>"
                await message.reply_text(f"{title}\n<pre>{html.escape(pretty)}</pre>", parse_mode=ParseMode.HTML)
            except ZentryError:
                await message.reply_text("❌ Key not found in your history." if language == "en" else "❌ La key no aparece en tu historial.")
        else:
            await message.reply_text("❌ Key not found in your history." if language == "en" else "❌ La key no aparece en tu historial.")
        return True

    if flow["name"] == "zentry_generate_quantity":
        try:
            quantity = int(text)
            if quantity < 1 or quantity > 100:
                raise ValueError
        except ValueError:
            await message.reply_text("❌ Escribe una cantidad entre 1 y 100.")
            return True
        product = db.product(flow["product_id"])
        if not product:
            context.user_data.pop("flow", None)
            await message.reply_text("❌ Producto no encontrado.", reply_markup=ADMIN_MENU)
            return True
        context.user_data.pop("flow", None)
        keys = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"✅ Generar {quantity} keys", callback_data=f"zentryconfirm:{product['id']}:{quantity}"
            ),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]])
        await message.reply_text(
            "⚡ <b>Confirmar generación</b>\n"
            f"Producto: <b>{html.escape(product['name'])}</b>\n"
            f"Cantidad: <b>{quantity}</b>\nDuración: <b>{product['duration_days']} días</b>",
            reply_markup=keys,
            parse_mode=ParseMode.HTML,
        )
        return True

    if flow["name"] == "zentry_control_key":
        if len(text) < 4 or len(text) > 200:
            await message.reply_text("❌ La key no parece válida. Inténtalo otra vez.")
            return True
        context.user_data.pop("flow", None)
        context.user_data["zentry_control_key"] = text
        actions = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔎 Consultar", callback_data="zentryctl:info")],
            [InlineKeyboardButton("♻️ Reset HWID", callback_data="zentryctl:reset")],
            [InlineKeyboardButton("🚫 Bloquear", callback_data="zentryctl:ban"),
             InlineKeyboardButton("✅ Desbloquear", callback_data="zentryctl:unban")],
        ])
        await message.reply_text(
            f"🛡️ <b>Control de licencia</b>\nKey: <code>{html.escape(text)}</code>",
            reply_markup=actions,
            parse_mode=ParseMode.HTML,
        )
        return True
    if flow["name"] == "partner_password":
        ok = db.activate_partner(flow["login"], text, message.from_user.id)
        context.user_data.pop("flow", None)
        if not ok:
            await message.reply_text("❌ Usuario o contraseña incorrectos, o la cuenta ya fue vinculada.", reply_markup=PENDING_MENU)
        else:
            linked = db.user(message.from_user.id)
            if linked["role"] == "admin":
                await message.reply_text(
                    "✅ Cuenta vinculada con rol <b>Administrador</b>.\nYa puedes abrir el bot privado de administración.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=USER_MENU,
                )
            else:
                await message.reply_text("✅ Cuenta vinculada. Ya eres socio comprador.", reply_markup=USER_MENU)
        return True
    if flow["name"] == "partner_create_login":
        flow["name"], flow["login"] = "partner_create_password", text
        await message.reply_text("🔑 Escribe una contraseña de mínimo 6 caracteres:")
        return True
    if flow["name"] == "partner_create_password":
        if len(text) < 6:
            await message.reply_text("❌ La contraseña debe tener mínimo 6 caracteres.")
            return True
        flow["name"], flow["password"] = "partner_create_role", text
        keys = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛡️ Administrador", callback_data="newrole:admin")],
            [InlineKeyboardButton("💎 Socio VIP", callback_data="newrole:vip"),
             InlineKeyboardButton("👤 Socio Regular", callback_data="newrole:regular")],
        ])
        await message.reply_text("👤 <b>Elige el rol de la nueva cuenta:</b>", reply_markup=keys, parse_mode=ParseMode.HTML)
        return True
    if flow["name"] == "partner_create_balance":
        try:
            initial_balance = 0 if text in ("0", "0.00", "$0") else parse_amount(text)
            db.create_partner(
                flow["login"], flow["password"], initial_balance,
                flow["target_role"], flow.get("target_tier", "regular"),
            )
        except (ValueError, sqlite3.IntegrityError) as exc:
            await message.reply_text(f"❌ {exc}")
            return True
        login = flow["login"]
        password = flow["password"]
        context.user_data.pop("flow", None)
        await message.reply_text(
            "✅ <b>Socio creado</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"Usuario: <code>{html.escape(login)}</code>\n"
            f"Contraseña: <code>{html.escape(password)}</code>\n"
            f"Rango: <b>{'Administrador' if flow['target_role'] == 'admin' else ('Socio VIP' if flow.get('target_tier') == 'vip' else 'Socio Regular')}</b>\n"
            f"Saldo al vincularse: <b>{money(initial_balance)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ADMIN_MENU,
        )
        return True
    if flow["name"] == "broadcast":
        sent = failed = 0
        payload = None
        kind = "text"
        caption = message.caption or ""
        filename = None
        if message.photo:
            kind = "photo"
            tg_file = await context.bot.get_file(message.photo[-1].file_id)
            payload = bytes(await tg_file.download_as_bytearray())
        elif message.animation:
            kind = "animation"
            filename = message.animation.file_name or "anuncio.gif"
            tg_file = await context.bot.get_file(message.animation.file_id)
            payload = bytes(await tg_file.download_as_bytearray())
        elif message.video:
            kind = "video"
            filename = message.video.file_name or "anuncio.mp4"
            tg_file = await context.bot.get_file(message.video.file_id)
            payload = bytes(await tg_file.download_as_bytearray())
        elif message.sticker:
            kind = "sticker"
            filename = "anuncio.tgs" if message.sticker.is_animated else ("anuncio.webm" if message.sticker.is_video else "anuncio.webp")
            tg_file = await context.bot.get_file(message.sticker.file_id)
            payload = bytes(await tg_file.download_as_bytearray())
        elif message.document:
            kind = "document"
            filename = message.document.file_name or "anuncio"
            tg_file = await context.bot.get_file(message.document.file_id)
            payload = bytes(await tg_file.download_as_bytearray())
        elif not text:
            await message.reply_text("❌ Envía texto, una foto o un documento.")
            return True
        for target in db.reseller_ids():
            try:
                if kind == "photo":
                    await reseller_bot(context).send_photo(target, io.BytesIO(payload), caption=caption)
                elif kind == "animation":
                    stream = io.BytesIO(payload)
                    stream.name = filename
                    await reseller_bot(context).send_animation(target, stream, caption=caption)
                elif kind == "video":
                    stream = io.BytesIO(payload)
                    stream.name = filename
                    await reseller_bot(context).send_video(target, stream, caption=caption)
                elif kind == "sticker":
                    stream = io.BytesIO(payload)
                    stream.name = filename
                    await reseller_bot(context).send_sticker(target, stream)
                elif kind == "document":
                    stream = io.BytesIO(payload)
                    stream.name = filename
                    await reseller_bot(context).send_document(target, stream, caption=caption)
                else:
                    await reseller_bot(context).send_message(target, text)
                sent += 1
            except Exception:
                failed += 1
        context.user_data.pop("flow", None)
        await message.reply_text(
            f"📢 <b>Reporte del anuncio</b>\n✅ Entregados: {sent}\n❌ No entregados: {failed}",
            parse_mode=ParseMode.HTML,
            reply_markup=ADMIN_MENU,
        )
        return True
    if flow["name"] == "product_file":
        if not message.document:
            await message.reply_text("❌ Envía el archivo como documento.")
            return True
        if message.document.file_size and message.document.file_size > 20 * 1024 * 1024:
            await message.reply_text("❌ El archivo no puede superar 20 MB.")
            return True
        tg_file = await context.bot.get_file(message.document.file_id)
        file_data = bytes(await tg_file.download_as_bytearray())
        db.set_product_file(
            flow["product_id"], message.document.file_id,
            message.document.file_name or "producto", file_data,
        )
        context.user_data.pop("flow", None)
        await message.reply_text("✅ Archivo vinculado al producto.", reply_markup=ADMIN_MENU)
        return True

    if flow["name"] == "product_photo":
        if not message.photo and not (message.document and message.document.mime_type in ("image/jpeg", "image/png")):
            await message.reply_text("❌ Envía una foto o un archivo JPG/PNG.")
            return True
        photo_info = message.photo[-1] if message.photo else message.document
        if photo_info.file_size and photo_info.file_size > 10 * 1024 * 1024:
            await message.reply_text("❌ La imagen no puede superar 10 MB.")
            return True
        tg_file = await context.bot.get_file(photo_info.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        filename = "product.png" if message.document and message.document.mime_type == "image/png" else "product.jpg"
        db.set_product_photo(flow["product_id"], data, filename)
        context.user_data.pop("flow", None)
        await message.reply_text("✅ Portada guardada. Ya aparece en 🛒 Comprar keys y al abrir el producto.", reply_markup=ADMIN_MENU)
        return True

    if flow["name"] == "certificate_cover_photo":
        if not message.photo and not (message.document and message.document.mime_type in ("image/jpeg", "image/png")):
            await message.reply_text("❌ Envía una foto o un archivo JPG/PNG.")
            return True
        photo_info = message.photo[-1] if message.photo else message.document
        if photo_info.file_size and photo_info.file_size > 10 * 1024 * 1024:
            await message.reply_text("❌ La imagen no puede superar 10 MB.")
            return True
        tg_file = await context.bot.get_file(photo_info.file_id)
        db.set_certificate_offer_photo(bytes(await tg_file.download_as_bytearray()))
        context.user_data.pop("flow", None)
        await message.reply_text("✅ Foto del certificado guardada. Aparecerá al tocar 🍎 Certificado iOS.", reply_markup=ADMIN_MENU)
        return True

    if flow["name"] == "product_sticker":
        if not message.sticker:
            await message.reply_text("❌ Envía un sticker de Telegram; puede ser animado 3D.")
            return True
        tg_file = await context.bot.get_file(message.sticker.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        name = "product.tgs" if message.sticker.is_animated else ("product.webm" if message.sticker.is_video else "product.webp")
        db.set_product_sticker(flow["product_id"], data, name)
        context.user_data.pop("flow", None)
        await message.reply_text("✅ Sticker guardado para el producto.", reply_markup=ADMIN_MENU)
        return True

    if flow["name"] in ("partner_balance_add", "partner_balance_subtract"):
        try:
            amount = parse_amount(text)
            if flow["name"] == "partner_balance_subtract":
                amount = -amount
            balance = db.adjust_balance(flow["target"], amount, message.from_user.id)
        except (ValueError, InsufficientBalance, NotFound) as exc:
            await message.reply_text(f"❌ {exc}")
            return True
        target = flow["target"]
        context.user_data.pop("flow", None)
        action = "agregó" if amount > 0 else "retiró"
        await message.reply_text(
            f"✅ Se {action} {money(abs(amount))}. Nuevo saldo: {money(balance)}", reply_markup=ADMIN_MENU
        )
        try:
            await reseller_bot(context).send_message(
                target, f"💰 El administrador actualizó tu saldo.\nMovimiento: {'+' if amount > 0 else '-'}{money(abs(amount))}\nSaldo actual: {money(balance)}"
            )
        except Exception:
            pass
        return True

    if flow["name"] == "partner_warning":
        if not text:
            await message.reply_text("❌ Escribe el mensaje de advertencia.")
            return True
        target = flow["target"]
        try:
            await reseller_bot(context).send_message(target, f"⚠️ ADVERTENCIA DEL ADMIN\n\n{text}")
        except Exception:
            await message.reply_text("❌ No se pudo entregar. El socio debe iniciar el bot de revendedores.")
            return True
        context.user_data.pop("flow", None)
        await message.reply_text("✅ Advertencia enviada al socio.", reply_markup=ADMIN_MENU)
        return True

    if flow["name"] == "partner_price":
        try:
            price = parse_amount(text)
            db.set_reseller_price(flow["target"], flow["product_id"], price)
        except (ValueError, NotFound) as exc:
            await message.reply_text(f"❌ {exc}")
            return True
        target = flow["target"]
        product = db.product(flow["product_id"])
        context.user_data.pop("flow", None)
        await message.reply_text(
            f"✅ Precio para este socio: {html.escape(product['name'])} = {money(price)}", reply_markup=ADMIN_MENU
        )
        try:
            await reseller_bot(context).send_message(target, f"💲 Tienes un precio especial en {product['name']}: {money(price)}")
        except Exception:
            pass
        return True

    if flow["name"] == "topup_amount":
        try:
            flow["amount_cents"] = parse_amount(text)
        except ValueError:
            await message.reply_text("❌ Cantidad inválida. Ejemplo: 25.00")
            return True
        flow["name"] = "topup_proof"
        await message.reply_text("📎 Envía una captura/documento del pago o escribe la referencia.")
        return True

    if flow["name"] == "topup_proof":
        proof_blob = None
        proof_name = None
        if message.photo:
            proof_type, proof = "photo", message.photo[-1].file_id
            tg_file = await context.bot.get_file(proof)
            proof_blob = bytes(await tg_file.download_as_bytearray())
            proof_name = "comprobante.jpg"
        elif message.document:
            proof_type, proof = "document", message.document.file_id
            tg_file = await context.bot.get_file(proof)
            proof_blob = bytes(await tg_file.download_as_bytearray())
            proof_name = message.document.file_name or "comprobante"
        elif text:
            proof_type, proof = "text", text[:500]
        else:
            await message.reply_text("❌ Envía una imagen, documento o referencia escrita.")
            return True
        topup_id = db.create_topup(
            message.from_user.id, flow["amount_cents"], proof_type, proof, proof_blob, proof_name
        )
        context.user_data.pop("flow", None)
        await message.reply_text(f"✅ Recarga #{topup_id} enviada. Espera la aprobación del Admin.", reply_markup=USER_MENU)
        item = db.topup(topup_id)
        keys = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Aprobar", callback_data=f"topup:approve:{topup_id}"),
            InlineKeyboardButton("❌ Rechazar", callback_data=f"topup:reject:{topup_id}"),
        ]])
        caption = f"💳 <b>Nueva recarga #{topup_id}</b>\nUsuario: <code>{item['user_id']}</code>\nCantidad: <b>{money(item['amount_cents'])}</b>"
        for admin_id in set(settings.admin_ids) | set(db.admin_ids()):
            try:
                if proof_type == "photo":
                    await admin_bot(context).send_photo(admin_id, io.BytesIO(proof_blob), caption=caption, reply_markup=keys, parse_mode=ParseMode.HTML)
                elif proof_type == "document":
                    stream = io.BytesIO(proof_blob)
                    stream.name = proof_name
                    await admin_bot(context).send_document(admin_id, stream, caption=caption, reply_markup=keys, parse_mode=ParseMode.HTML)
                else:
                    await admin_bot(context).send_message(admin_id, caption + f"\nReferencia: <code>{html.escape(proof)}</code>", reply_markup=keys, parse_mode=ParseMode.HTML)
            except Exception as exc:
                log.warning("No se notificó recarga al admin %s: %s", admin_id, exc)
        return True

    if flow["name"] == "daily_announcement_text":
        if not text or len(text) > 4000:
            await message.reply_text("❌ Escribe un mensaje de hasta 4000 caracteres.")
            return True
        flow["body"] = text
        flow["name"] = "daily_announcement_time"
        await message.reply_text("🕒 ¿A qué hora todos los días? Escribe HH:MM, hora de Nueva York. Ejemplo: 10:30")
        return True

    if flow["name"] == "daily_announcement_time":
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", text):
            await message.reply_text("❌ Hora inválida. Usa HH:MM, por ejemplo 10:30.")
            return True
        now = datetime.now(ZoneInfo("America/New_York"))
        db.set_daily_announcement(flow["body"], text, now.date().isoformat() if now.strftime("%H:%M") >= text else None)
        context.user_data.pop("flow", None)
        await message.reply_text(f"✅ Anuncio diario guardado para las {text} (Nueva York).", reply_markup=ADMIN_MENU)
        return True

    if flow["name"] == "product_edit":
        product_id, field = flow["product_id"], flow["field"]
        if not db.product(product_id):
            context.user_data.pop("flow", None)
            await message.reply_text("❌ Producto no encontrado.")
            return True
        try:
            if field == "price_cents":
                value = parse_amount(text)
            elif field == "duration_days":
                value = int(text)
            elif field == "name":
                value = text.strip()
                if not 2 <= len(value) <= 100:
                    raise ValueError("El nombre debe tener de 2 a 100 caracteres")
            else:
                value = "" if text == "-" else text[:1500 if field == "instructions" else 500]
            if field == "name":
                saved = db.update_product_name(product_id, value, message.text_html or html.escape(value), custom_emoji_id(message))
            else:
                saved = db.update_product(product_id, field, value)
            if not saved:
                raise ValueError("Producto no encontrado")
        except (ValueError, TypeError) as exc:
            await message.reply_text(f"❌ {html.escape(str(exc))}. Inténtalo otra vez.")
            return True
        context.user_data.pop("flow", None)
        await message.reply_text("✅ Producto actualizado sin borrar sus keys, archivos ni precios por socio. Reabre 🛒 Comprar keys para ver la lista nueva.", reply_markup=ADMIN_MENU)
        return True

    if flow["name"] == "product_name":
        if not 2 <= len(text) <= 100:
            await message.reply_text("Escribe un nombre de 2 a 100 caracteres.")
            return True
        flow["name"], flow["product_name"] = "product_price", text
        flow["product_name_html"] = message.text_html or html.escape(text)
        flow["custom_emoji_id"] = custom_emoji_id(message)
        await message.reply_text("💵 Escribe el precio de venta. Ejemplo: 14.99")
        return True

    if flow["name"] == "product_price":
        try:
            flow["price_cents"] = parse_amount(text)
        except ValueError:
            await message.reply_text("❌ Precio inválido. Ejemplo: 14.99")
            return True
        flow["name"] = "product_duration"
        await message.reply_text("⏳ Escribe la duración de la key en días. Ejemplos: <code>1</code>, <code>7</code>, <code>31</code>, <code>365</code>.", parse_mode=ParseMode.HTML)
        return True

    if flow["name"] == "product_duration":
        try:
            days = int(text)
            if days < 1 or days > 3650:
                raise ValueError
        except ValueError:
            await message.reply_text("❌ Duración inválida. Escribe solamente el número de días.")
            return True
        flow["duration_days"] = days
        flow["name"] = "product_description"
        await message.reply_text("📝 Escribe una descripción corta o envía <code>-</code> para omitirla.", parse_mode=ParseMode.HTML)
        return True

    if flow["name"] == "product_description":
        flow["description"] = "" if text == "-" else text[:500]
        flow["name"] = "product_instructions"
        await message.reply_text(
            "📋 Escribe las instrucciones que recibirá el comprador. Ejemplo: cómo activar la key y usar la IPA. Envía <code>-</code> para usar un mensaje básico.",
            parse_mode=ParseMode.HTML,
        )
        return True

    if flow["name"] == "product_instructions":
        instructions = "Activa tu key siguiendo las instrucciones incluidas con el archivo." if text == "-" else text[:1500]
        product_id = db.create_product(
            flow["product_name"], flow["price_cents"], flow["description"], flow["duration_days"], instructions,
            flow.get("product_name_html", ""), flow.get("custom_emoji_id", ""),
        )
        context.user_data.pop("flow", None)
        await message.reply_text(
            f"✅ Producto #{product_id} creado con duración de {flow['duration_days']} días.\n"
            "Ahora puedes agregar sus keys, archivo, foto y sticker animado.",
            reply_markup=ADMIN_MENU,
        )
        return True

    if flow["name"] == "add_keys":
        values = [line.strip() for line in text.splitlines()]
        added, duplicates = db.add_keys(flow["product_id"], values)
        context.user_data.pop("flow", None)
        await message.reply_text(f"✅ Keys añadidas: {added}\nDuplicadas/omitidas: {duplicates}", reply_markup=ADMIN_MENU)
        return True

    return False


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = current_user(update)
    data = query.data or ""
    admin_panel = panel(context) == "admin"
    if data == "noop":
        await query.answer()
        return

    if data.startswith("lang:"):
        language = data.split(":", 1)[1]
        db.set_language(query.from_user.id, language)
        await query.answer("Language saved" if language == "en" else "Idioma guardado")
        await query.edit_message_reply_markup(reply_markup=None)
        await send_home(update, context)
        return

    if data.startswith("certsettings:"):
        await query.answer()
        if data.endswith(":language"):
            await choose_language(update)
        else:
            await show_account(update)
        return

    if data == "cert:confirm":
        if admin_panel or user["role"] not in ("reseller", "admin"):
            await query.answer("Acceso no autorizado", show_alert=True)
            return
        await query.answer("Verificando disponibilidad…")
        try:
            plans, balance = await asyncio.gather(
                asyncio.to_thread(chungchi.plans), asyncio.to_thread(chungchi.balance)
            )
            plan = next((p for p in plans if int(p.get("id", -1)) == settings.chungchi_plan_id), None)
            if not plan or float(balance.get("wallet", 0) or 0) < float(plan.get("amount", 0) or 0):
                raise ChungChiError("Certificados agotados temporalmente")
            digest = hashlib.sha256(
                f"{query.from_user.id}:{query.message.chat_id}:{query.message.message_id}:{settings.bot_token}".encode()
            ).hexdigest().upper()
            key_code = f"CERT-{digest[:4]}-{digest[4:8]}-{digest[8:12]}"
            issued = db.buy_certificate_key(query.from_user.id, key_code, settings.chungchi_sell_price_cents)
        except sqlite3.IntegrityError:
            await query.answer("Esta compra ya fue procesada", show_alert=True)
            return
        except (ChungChiError, InsufficientBalance, NotApproved) as exc:
            await query.message.reply_text(f"❌ {html.escape(str(exc))}", parse_mode=ParseMode.HTML)
            return
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "🎉 <b>PAGO CONFIRMADO</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"🔑 Key: <code>{issued['key_code']}</code>\n"
            f"💰 Saldo restante: <b>{money(issued['balance_cents'])}</b>\n\n"
            "La key se activó para iniciar tu certificado.",
            reply_markup=certificate_menu(language_of(user)),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["flow"] = {"name": "certificate_udid", "certificate_key": issued["key_code"]}
        await query.message.reply_text("📱 Envía el UDID del iPhone o iPad:")
        return

    if data.startswith("certdevice:"):
        flow = context.user_data.get("flow")
        device = data.split(":", 1)[1]
        if not flow or flow.get("name") != "certificate_device" or device not in ("iphone", "ipad"):
            await query.answer("La solicitud expiró", show_alert=True)
            return
        flow["device"] = device
        flow["name"] = "certificate_password"
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "🔐 Escribe la contraseña que deseas para el archivo <code>.p12</code>.\n"
            "Puedes escribir <code>1</code> para usar la contraseña sencilla.",
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "cert:create":
        if admin_panel:
            await query.answer("Usa el bot de ventas", show_alert=True)
            return
        await query.answer("Creando pedido…")
        await query.edit_message_reply_markup(reply_markup=None)
        await submit_certificate_order(query.message, context, query.from_user.id)
        return

    if data.startswith("newrole:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        flow = context.user_data.get("flow")
        if not flow or flow.get("name") != "partner_create_role":
            await query.answer("Esta creación ya terminó", show_alert=True)
            return
        selected = data.split(":", 1)[1]
        if selected not in ("admin", "vip", "regular"):
            await query.answer("Rol inválido", show_alert=True)
            return
        flow["name"] = "partner_create_balance"
        flow["target_role"] = "admin" if selected == "admin" else "reseller"
        flow["target_tier"] = "vip" if selected == "vip" else "regular"
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "💰 Escribe el saldo inicial. Usa <code>0</code> si no tendrá saldo.", parse_mode=ParseMode.HTML
        )
        return

    if data.startswith("partner:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        parts = data.split(":")
        action, target = parts[1], int(parts[2])
        if action == "manage":
            await query.answer()
            await show_partner_manager(query.message, target)
        elif action in ("add", "subtract"):
            await query.answer()
            context.user_data["flow"] = {
                "name": "partner_balance_add" if action == "add" else "partner_balance_subtract",
                "target": target,
            }
            await query.message.reply_text(
                f"💰 Escribe cuánto quieres {'agregar' if action == 'add' else 'quitar'}. Ejemplo: <code>25.00</code>",
                parse_mode=ParseMode.HTML,
            )
        elif action in ("tier-vip", "tier-regular"):
            tier = "vip" if action == "tier-vip" else "regular"
            changed = db.set_tier(target, tier)
            await query.answer("Rango actualizado" if changed else "Socio no encontrado", show_alert=True)
            if changed:
                await query.message.reply_text(f"✅ El socio ahora tiene rango <b>{tier.upper()}</b>.", parse_mode=ParseMode.HTML)
                try:
                    await reseller_bot(context).send_message(target, f"💎 Tu rango cambió a {tier.upper()}.")
                except Exception:
                    pass
            return
        elif action == "warn":
            await query.answer()
            context.user_data["flow"] = {"name": "partner_warning", "target": target}
            await query.message.reply_text("⚠️ Escribe la advertencia privada para este socio:")
        elif action == "prices":
            await query.answer()
            prices = db.reseller_prices(target)
            rows = []
            lines = ["💲 <b>Precio especial del socio</b>"]
            for p in prices:
                current = p["reseller_price_cents"]
                lines.append(
                    f"• {html.escape(p['name'])}: {money(current) if current else 'normal ' + money(p['regular_price_cents'])}"
                )
                rows.append([InlineKeyboardButton(p["name"], callback_data=f"partnerprice:{target}:{p['id']}")])
            await query.message.reply_text(
                "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows) if rows else None, parse_mode=ParseMode.HTML
            )
        elif action == "limits":
            await query.answer()
            access = db.product_access(target)
            rows = [[InlineKeyboardButton(
                f"{'✅ Permitido' if p['allowed'] else '🚫 Bloqueado'} · {p['name']}",
                callback_data=f"access:{target}:{p['id']}",
            )] for p in access]
            await query.message.reply_text(
                "🔐 <b>Límites de compra</b>\nToca un producto para permitirlo o bloquearlo.",
                reply_markup=InlineKeyboardMarkup(rows) if rows else None,
                parse_mode=ParseMode.HTML,
            )
        return

    if data.startswith("access:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        _, raw_target, raw_product = data.split(":")
        allowed = db.toggle_product_access(int(raw_target), int(raw_product))
        await query.answer("Producto permitido" if allowed else "Producto bloqueado", show_alert=True)
        product = db.product(int(raw_product))
        await query.message.reply_text(
            f"{'✅' if allowed else '🚫'} {html.escape(product['name'])}: "
            f"{'el socio puede comprarlo' if allowed else 'el socio no puede comprarlo'}.",
            parse_mode=ParseMode.HTML,
        )
        return

    if data.startswith("partnerprice:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        _, raw_target, raw_product = data.split(":")
        await query.answer()
        context.user_data["flow"] = {
            "name": "partner_price", "target": int(raw_target), "product_id": int(raw_product)
        }
        await query.message.reply_text("💲 Escribe el precio especial para este socio. Ejemplo: <code>20.00</code>", parse_mode=ParseMode.HTML)
        return

    if data.startswith("user:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        _, action, raw_id = data.split(":")
        target = int(raw_id)
        role = {"approve": "reseller", "reject": "rejected", "revoke": "rejected"}[action]
        await query.answer()
        if db.set_role(target, role):
            label = "aprobado" if role == "reseller" else "sin acceso"
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ Usuario {target}: {label}.")
            try:
                await reseller_bot(context).send_message(target, "✅ Tu cuenta fue aprobada como revendedor." if role == "reseller" else "❌ Tu acceso de revendedor no fue aprobado.", reply_markup=USER_MENU if role == "reseller" else PENDING_MENU)
            except Exception:
                pass
        return

    if data in ("media:products", "certcover:upload"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        await query.answer()
        if data == "media:products":
            await begin_product_media(update)
        else:
            context.user_data["flow"] = {"name": "certificate_cover_photo"}
            await query.message.reply_text("🍎 Envía la portada del certificado como foto o archivo JPG/PNG.")
        return

    if data.startswith("product:photo:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        product_id = int(data.rsplit(":", 1)[1])
        if not db.product(product_id):
            await query.answer("Producto no encontrado", show_alert=True)
            return
        await query.answer()
        context.user_data["flow"] = {"name": "product_photo", "product_id": product_id}
        await query.message.reply_text(f"📷 Envía la nueva portada del producto #{product_id} como foto o JPG/PNG.")
        return

    if data.startswith("announcement:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        await query.answer()
        action = data.split(":", 1)[1]
        if action == "pause":
            db.pause_daily_announcement()
            await query.message.reply_text("⏸️ Anuncio diario pausado.")
        elif action == "daily":
            context.user_data["flow"] = {"name": "daily_announcement_text"}
            await query.message.reply_text("🗓️ Envía el texto diario. Puedes incluir emojis y emoticones como :) o :D")
        elif action == "now":
            context.user_data["flow"] = {"name": "broadcast"}
            await query.message.reply_text("📤 Envía el mensaje, foto o archivo para todos los socios ahora.")
        return

    if data.startswith("product:editfield:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        _, _, raw_id, field = data.split(":")
        product = db.product(int(raw_id))
        labels = {"name": "nombre y emojis", "price_cents": "precio (ej. 14.99)",
                  "duration_days": "duración en días", "description": "descripción",
                  "instructions": "instrucciones de entrega"}
        if not product or field not in labels:
            await query.answer("Producto no encontrado", show_alert=True)
            return
        await query.answer()
        context.user_data["flow"] = {"name": "product_edit", "product_id": product["id"], "field": field}
        await query.message.reply_text(f"✏️ Envía el nuevo valor de {labels[field]} para #{product['id']}. Usa - para vaciar descripción o instrucciones.")
        return

    if data.startswith("product:edit:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        product_id = int(data.rsplit(":", 1)[1])
        product = db.product(product_id)
        if not product:
            await query.answer("Producto no encontrado", show_alert=True)
            return
        await query.answer()
        fields = (("📦 Nombre / emojis", "name"), ("📷 Foto", "photo"), ("💵 Precio", "price_cents"),
                  ("⏳ Duración", "duration_days"), ("📝 Descripción", "description"),
                  ("📋 Instrucciones", "instructions"))
        await query.message.reply_text(
            f"✏️ <b>Editar #{product_id}</b> · {html.escape(product['name'])}\nSelecciona un campo:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=f"product:photo:{product_id}" if field == "photo" else f"product:editfield:{product_id}:{field}")]
                                             for label, field in fields]),
        )
        return

    if data == "product:new":
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        await query.answer()
        context.user_data["flow"] = {"name": "product_name"}
        await query.message.reply_text("📦 Ingresa el nombre del producto:")
        return

    if data.startswith("product:toggle:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        await query.answer()
        product_id = int(data.rsplit(":", 1)[1])
        product = db.product(product_id)
        if product:
            db.set_product_active(product_id, not bool(product["active"]))
            await query.message.reply_text("✅ Estado del producto actualizado.")
        return

    if data.startswith("addkeys:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        await query.answer()
        product_id = int(data.split(":")[1])
        context.user_data["flow"] = {"name": "add_keys", "product_id": product_id}
        await query.message.reply_text("🔑 Envía las keys, <b>una por línea</b>.", parse_mode=ParseMode.HTML)
        return

    if data.startswith("zentrygen:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        product_id = int(data.split(":", 1)[1])
        product = db.product(product_id)
        if not product:
            await query.answer("Producto no encontrado", show_alert=True)
            return
        await query.answer()
        context.user_data["flow"] = {"name": "zentry_generate_quantity", "product_id": product_id}
        await query.message.reply_text(
            f"⚡ ¿Cuántas keys de <b>{html.escape(product['name'])}</b> quieres generar?\n"
            "Escribe una cantidad entre <b>1 y 100</b>.",
            parse_mode=ParseMode.HTML,
        )
        return

    if data.startswith("zentryconfirm:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        _, raw_product, raw_quantity = data.split(":")
        product = db.product(int(raw_product))
        quantity = int(raw_quantity)
        if not product or quantity < 1 or quantity > 100:
            await query.answer("Solicitud inválida", show_alert=True)
            return
        await query.answer("Generando keys…")
        await query.edit_message_reply_markup(reply_markup=None)
        status_message = await query.message.reply_text(
            f"⏳ Generando {quantity} keys de {product['duration_days']} días en ZentryAuth…"
        )
        generated: list[str] = []
        failure = ""
        for _ in range(quantity):
            try:
                key = await asyncio.to_thread(
                    zentry.create_license, int(product["duration_days"]), settings.zentry_key_prefix
                )
                generated.append(key)
            except ZentryError as exc:
                failure = str(exc)
                break
        added = duplicates = 0
        if generated:
            added, duplicates = db.add_keys(int(product["id"]), generated)
        result = (
            "⚡ <b>Generación terminada</b>\n"
            f"✅ Creadas en ZentryAuth: <b>{len(generated)}</b>\n"
            f"📦 Guardadas en el inventario: <b>{added}</b>\n"
            f"♻️ Duplicadas omitidas: <b>{duplicates}</b>"
        )
        if failure:
            result += f"\n⚠️ Se detuvo por: {html.escape(failure)}"
        await status_message.edit_text(result, parse_mode=ParseMode.HTML)
        return

    if data.startswith("zentryctl:"):
        if not admin_panel or not can_control_keys(query.from_user.id):
            await query.answer("Solo Admin o Socio VIP", show_alert=True)
            return
        license_key = context.user_data.get("zentry_control_key")
        if not license_key:
            await query.answer("Vuelve a enviar la key", show_alert=True)
            return
        action = data.split(":", 1)[1]
        operations = {
            "info": ("Consultar", zentry.license_info),
            "reset": ("Reset HWID", zentry.reset_hwid),
            "ban": ("Bloquear", zentry.ban_license),
            "unban": ("Desbloquear", zentry.unban_license),
        }
        if action not in operations:
            await query.answer("Acción inválida", show_alert=True)
            return
        label, operation = operations[action]
        await query.answer(f"{label}…")
        try:
            result = await asyncio.to_thread(operation, license_key)
        except ZentryError as exc:
            await query.message.reply_text(f"❌ {html.escape(str(exc))}", parse_mode=ParseMode.HTML)
            return
        if action == "info":
            data_result = result.get("data", result)
            pretty = json.dumps(data_result, ensure_ascii=False, indent=2, default=str)[:3500]
            await query.message.reply_text(
                f"🔎 <b>Estado de la licencia</b>\n<pre>{html.escape(pretty)}</pre>",
                parse_mode=ParseMode.HTML,
            )
        else:
            message = result.get("message") or f"{label} completado"
            await query.message.reply_text(f"✅ {html.escape(str(message))}", parse_mode=ParseMode.HTML)
        return

    if data.startswith("addfile:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        await query.answer()
        product_id = int(data.split(":")[1])
        context.user_data["flow"] = {"name": "product_file", "product_id": product_id}
        await query.message.reply_text("📎 Envía el archivo como documento.")
        return

    if data.startswith("media:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        product_id = int(data.split(":")[1])
        await query.answer()
        keys = InlineKeyboardMarkup([[
            InlineKeyboardButton("🖼️ Agregar foto", callback_data=f"media-photo:{product_id}"),
            InlineKeyboardButton("✨ Sticker 3D", callback_data=f"media-sticker:{product_id}"),
        ]])
        await query.message.reply_text("🎨 Selecciona el tipo de multimedia:", reply_markup=keys)
        return

    if data.startswith("media-photo:") or data.startswith("media-sticker:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        product_id = int(data.rsplit(":", 1)[1])
        is_photo = data.startswith("media-photo:")
        context.user_data["flow"] = {"name": "product_photo" if is_photo else "product_sticker", "product_id": product_id}
        await query.answer()
        await query.message.reply_text(
            "🖼️ Envía la foto del producto." if is_photo else "✨ Envía el sticker de Telegram; puede ser animado o 3D."
        )
        return

    if data.startswith("buy:"):
        if admin_panel:
            await query.answer("Usa el bot de revendedores", show_alert=True)
            return
        if user["role"] not in ("reseller", "admin"):
            await query.answer("Acceso no autorizado", show_alert=True)
            return
        product_id = int(data.split(":")[1])
        p = db.product_for_user(product_id, query.from_user.id)
        if not p or not p["active"] or not p["allowed"]:
            await query.answer("Producto no disponible", show_alert=True)
            return
        await query.answer()
        keys = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirmar compra", callback_data=f"confirm:{product_id}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]])
        caption = (
            "💎 <b>PRODUCTO DIGITAL</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>{product_name_html(p)}</b>\n"
            f"💵 Precio socio: <b>{money(p['effective_price_cents'])}</b>\n"
            f"⏳ Duración: <b>{p['duration_days']} días</b>\n"
            f"🔑 Stock disponible: <b>{p['stock']}</b>\n"
            f"📝 {html.escape(p['description']) if p['description'] else 'Entrega automática inmediata'}\n\n"
            "¿Confirmar compra?"
        )
        media = db.product_media(product_id)
        if media and media["sticker_data"]:
            try:
                sticker = io.BytesIO(media["sticker_data"])
                sticker.name = media["sticker_name"] or "product.webp"
                await query.message.reply_sticker(sticker)
            except Exception as exc:
                log.warning("No se pudo mostrar sticker del producto %s: %s", product_id, exc)
        if media and media["photo_data"]:
            photo = io.BytesIO(media["photo_data"])
            photo.name = media["photo_name"] or "product.jpg"
            try:
                await query.message.reply_photo(photo, caption=caption, reply_markup=keys, parse_mode=ParseMode.HTML)
            except BadRequest as exc:
                if "emoji" not in str(exc).lower():
                    raise
                photo.seek(0)
                await query.message.reply_photo(photo, caption=caption.replace(product_name_html(p), html.escape(p["name"])),
                                                reply_markup=keys, parse_mode=ParseMode.HTML)
        else:
            try:
                await query.message.reply_text(caption, reply_markup=keys, parse_mode=ParseMode.HTML)
            except BadRequest as exc:
                if "emoji" not in str(exc).lower():
                    raise
                await query.message.reply_text(caption.replace(product_name_html(p), html.escape(p["name"])),
                                               reply_markup=keys, parse_mode=ParseMode.HTML)
        return

    if data.startswith("confirm:"):
        if admin_panel:
            await query.answer("Usa el bot de revendedores", show_alert=True)
            return
        product_id = int(data.split(":")[1])
        try:
            sale = db.purchase(query.from_user.id, product_id)
        except (InsufficientBalance, OutOfStock, NotApproved, NotFound, ProductRestricted) as exc:
            await query.answer(str(exc), show_alert=True)
            return
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "🎉 <b>¡GRACIAS POR TU COMPRA!</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📦 Producto: <b>{html.escape(sale['product_name'])}</b>\n"
            f"🔑 Tu key: <code>{html.escape(sale['key'])}</code>\n"
            f"🧾 Referencia: <code>#{sale['order_id']}</code>\n"
            f"⏳ Duración: <b>{sale['duration_days']} días</b>\n"
            f"⌛ Vence: <b>{format_date(sale['expires_at'])}</b>\n"
            f"💰 Saldo restante: <b>{money(sale['balance_cents'])}</b>\n\n"
            f"📋 <b>Activación</b>\n{html.escape(sale['instructions'])}\n\n"
            "Puedes revisar el tiempo restante cuando quieras en <b>🔑 Mis keys</b>.",
            parse_mode=ParseMode.HTML,
        )
        if sale["file"]:
            try:
                stream = io.BytesIO(sale["file"]["file_data"])
                stream.name = sale["file"]["file_name"]
                await query.message.reply_document(stream, caption="📎 Archivo del producto")
            except Exception:
                await query.message.reply_text("⚠️ La key fue entregada, pero el archivo necesita que el Admin lo vuelva a subir.")
        await notify_key_api(sale, query.from_user.id)
        return

    if data == "cancel":
        await query.answer()
        context.user_data.pop("flow", None)
        context.user_data.pop("certificate_pending", None)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Compra cancelada.")
        return

    if data.startswith("topup:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        _, action, raw_id = data.split(":")
        topup_id = int(raw_id)
        if action == "approve":
            changed, row = db.approve_topup(topup_id, query.from_user.id)
            message = "✅ Recarga aprobada."
        else:
            changed, row = db.reject_topup(topup_id, query.from_user.id)
            message = "❌ Recarga rechazada."
        if not changed or not row:
            await query.answer("Ya fue procesada", show_alert=True)
            return
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(message)
        try:
            await reseller_bot(context).send_message(row["user_id"], f"{message}\nCantidad: {money(row['amount_cents'])}")
        except Exception:
            pass
        return

    await query.answer()


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await send_home(update, context, "Operación cancelada.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Error procesando actualización", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ Ocurrió un error. Intenta nuevamente.")


def build_application(token: str, panel_name: str) -> Application:
    app: Application = ApplicationBuilder().token(token).build()
    app.bot_data["panel"] = panel_name
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("bankey", ban_key_command))
    app.add_handler(CommandHandler("unbankey", unban_key_command))
    app.add_handler(CommandHandler("keyinfo", key_info_command))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_text_menu))
    app.add_error_handler(error_handler)
    return app


def find_provider_order(payload):
    if isinstance(payload, dict):
        if payload.get("order_code"):
            return payload
        for value in payload.values():
            found = find_provider_order(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = find_provider_order(value)
            if found:
                return found
    return None


async def process_certificate_webhook(bot, payload: dict) -> None:
    provider = find_provider_order(payload)
    if not provider:
        log.warning("Webhook ChungChi sin order_code")
        return
    order = db.update_certificate_order(str(provider["order_code"]), provider)
    if not order:
        log.warning("Webhook ChungChi para pedido desconocido: %s", provider["order_code"])
        return
    if order["status"] == "completed" and not order["delivered_at"]:
        await deliver_certificate(bot, order)
    elif order["status"] in ("failed", "cancelled"):
        await bot.send_message(
            order["user_id"],
            f"⚠️ El pedido <code>{html.escape(order['provider_order_code'])}</code> terminó como "
            f"<b>{html.escape(order['status'])}</b>. Tu key quedó disponible para reintentar.",
            parse_mode=ParseMode.HTML,
        )


async def certificate_poll_loop(bot, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        if chungchi.configured:
            rows = db.pending_certificate_orders(limit=20)
            semaphore = asyncio.Semaphore(4)

            async def refresh(row):
                async with semaphore:
                    await refresh_certificate_order(bot, row)

            results = await asyncio.gather(*(refresh(row) for row in rows), return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    log.error("No se pudo consultar un certificado pendiente: %s", result)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass


async def daily_announcement_loop(bot, stop_event: asyncio.Event) -> None:
    new_york = ZoneInfo("America/New_York")
    while not stop_event.is_set():
        now = datetime.now(new_york)
        body = db.claim_daily_announcement(now.date().isoformat(), now.strftime("%H:%M"))
        if body:
            sent = failed = 0
            for target in db.reseller_ids():
                try:
                    await bot.send_message(target, body)
                    sent += 1
                except Exception as exc:
                    failed += 1
                    log.warning("Anuncio diario no entregado a %s: %s", target, exc)
            log.info("Anuncio diario: %s entregados, %s fallidos", sent, failed)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass


async def run_bots() -> None:
    db.initialize()
    server = start_health_server(asyncio.get_running_loop())
    reseller_app = build_application(settings.bot_token, "reseller")
    admin_app = build_application(settings.admin_bot_token, "admin")
    apps = (reseller_app, admin_app)
    initialized = []
    started = []
    stop_event = asyncio.Event()
    poll_task = None
    announcement_task = None
    loop = asyncio.get_running_loop()
    for signame in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signame, stop_event.set)
        except NotImplementedError:
            pass

    try:
        for app in apps:
            for attempt in range(1, 6):
                try:
                    await app.initialize()
                    initialized.append(app)
                    break
                except Exception:
                    if attempt == 5:
                        raise
                    log.warning("Telegram no respondió al inicializar; reintento %s/5", attempt, exc_info=True)
                    await asyncio.sleep(attempt * 2)
        reseller_app.bot_data["admin_bot"] = admin_app.bot
        reseller_app.bot_data["reseller_bot"] = reseller_app.bot
        admin_app.bot_data["admin_bot"] = admin_app.bot
        admin_app.bot_data["reseller_bot"] = reseller_app.bot
        for app in apps:
            await app.start()
            started.append(app)

        paths = {
            "/telegram/reseller": reseller_app,
            "/telegram/admin": admin_app,
        }
        secrets = {
            "/telegram/reseller": hashlib.sha256(settings.bot_token.encode()).hexdigest(),
            "/telegram/admin": hashlib.sha256(settings.admin_bot_token.encode()).hexdigest(),
        }
        server.configure(paths, secrets)
        base_url = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
        if not base_url.startswith("https://"):
            raise RuntimeError("Falta RENDER_EXTERNAL_URL o WEBHOOK_BASE_URL con HTTPS")
        for path, app in paths.items():
            for attempt in range(1, 6):
                try:
                    await app.bot.set_webhook(
                        url=f"{base_url}{path}",
                        secret_token=secrets[path],
                        allowed_updates=Update.ALL_TYPES,
                        drop_pending_updates=False,
                    )
                    break
                except Exception:
                    if attempt == 5:
                        raise
                    log.warning("No se pudo registrar webhook; reintento %s/5", attempt, exc_info=True)
                    await asyncio.sleep(attempt * 2)
        webhook_secret = settings.chungchi_webhook_secret or db.private_setting("chungchi_webhook_secret")
        if chungchi.configured and not webhook_secret:
            try:
                webhook = await asyncio.to_thread(chungchi.configure_webhook, f"{base_url}/chungchi/webhook")
                webhook_secret = str(webhook.get("secret") or "")
                if webhook_secret:
                    db.set_private_setting("chungchi_webhook_secret", webhook_secret)
                else:
                    log.warning("ChungChi no devolvió el secreto del webhook")
            except ChungChiError as exc:
                log.warning("No se pudo configurar webhook ChungChi (HTTP %s, código %s): %s. Se usará consulta periódica.",
                            exc.status, exc.code or "sin código", exc)

        def certificate_lookup(token: str):
            row = db.install_order(token)
            if not row:
                return None
            try:
                if datetime.fromisoformat(row["install_expires_at"]) < datetime.now(timezone.utc):
                    return None
            except ValueError:
                return None
            return row

        def certificate_download(order):
            return chungchi.download(order["download_url"])

        def certificate_webhook(raw: bytes, headers) -> bool:
            if not webhook_secret:
                return False
            timestamp = headers.get("X-Webhook-Timestamp", "")
            supplied = headers.get("X-Webhook-Signature", "")
            if not timestamp or not supplied:
                return False
            expected = "v1=" + hmac.new(
                webhook_secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, supplied):
                return False
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return False
            asyncio.run_coroutine_threadsafe(
                process_certificate_webhook(reseller_app.bot, payload), server.event_loop
            )
            return True

        server.configure_certificates(certificate_lookup, certificate_download, certificate_webhook)
        poll_task = asyncio.create_task(certificate_poll_loop(reseller_app.bot, stop_event))
        announcement_task = asyncio.create_task(daily_announcement_loop(reseller_app.bot, stop_event))
        log.info("Bots iniciados por webhook: revendedores + admin (%s)", settings.store_name)
        await stop_event.wait()
    finally:
        if announcement_task:
            announcement_task.cancel()
            try:
                await announcement_task
            except asyncio.CancelledError:
                pass
        if poll_task:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
        for app in reversed(started):
            if app.running:
                await app.stop()
        for app in reversed(initialized):
            await app.shutdown()
        await asyncio.to_thread(server.shutdown)
        server.server_close()


def main() -> None:
    asyncio.run(run_bots())


if __name__ == "__main__":
    main()
