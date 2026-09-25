from __future__ import annotations

import asyncio
import hashlib
import html
import os
import sqlite3

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.constants import ParseMode

import bot
from database import InsufficientBalance, NotApproved
from chungchi_api import ChungChiError


def cert_price_key(user_id: int) -> str:
    return f"certificate_special_price:{user_id}"


def certificate_price(user_id: int) -> int:
    raw = bot.db.private_setting(cert_price_key(user_id))
    if raw:
        try:
            value = int(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return bot.settings.chungchi_sell_price_cents


def _install_url(row) -> str:
    base_url = os.getenv("RENDER_EXTERNAL_URL", os.getenv("WEBHOOK_BASE_URL", "")).rstrip("/")
    token = str(row["install_token"] or "")
    if not base_url.startswith("https://") or not token:
        return ""
    return f"{base_url}/certificate/install/{token}"


def _status_label(status: str) -> str:
    labels = {
        "completed": "✅ FIRMADO",
        "processing": "🔵 PROCESANDO",
        "pending": "🟦 PENDIENTE",
        "submitting": "🧬 REGISTRANDO",
        "review": "🛡️ EN REVISIÓN",
        "failed": "🔴 REVISIÓN REQUERIDA",
        "cancelled": "⚫ CANCELADO",
    }
    return labels.get((status or "").lower(), (status or "Pendiente").upper())


async def show_my_certificates(update, context) -> None:
    message = update.effective_message
    user_id = update.effective_user.id
    rows = bot.db.certificate_orders_for_user(user_id, limit=10)
    if not rows:
        await message.reply_text(
            "💠 <b>TU CERTIFICADO</b>\n━━━━━━━━━━━━━━━━━━\n"
            "Todavía no tienes certificados registrados.\n\n"
            "Compra uno desde <b>🍎 Certificado iOS</b> y aparecerá aquí permanentemente.",
            parse_mode=ParseMode.HTML,
            reply_markup=bot.certificate_menu(bot.language_of(bot.current_user(update))),
        )
        return

    await message.reply_text(
        "🤖💠 <b>RANDY CERTIFICATE CORE</b>\n"
        "<code>secure.device.registry = ONLINE</code>\n"
        "Aquí quedan guardados tus certificados comprados.",
        parse_mode=ParseMode.HTML,
    )

    for row in rows[:5]:
        current = bot.db.renew_certificate_link(row["id"], user_id, bot.settings.certificate_link_ttl_hours) or row
        if row["provider_order_code"] and row["status"] not in ("completed", "failed", "cancelled"):
            try:
                await bot.refresh_certificate_order(context.bot, row)
                current = bot.db.certificate_order(row["id"], user_id) or row
            except Exception:
                current = row

        status = _status_label(str(current["status"] or "pending"))
        device = str(current["device"] or "iphone").replace("iphone", "iPhone").replace("ipad", "iPad")
        created = bot.format_date(current["created_at"]) if current["created_at"] else "Pendiente"
        password = html.escape(str(current["p12_password"] or "Pendiente"))
        name = html.escape(str(current["display_name"] or "Randy Certificate"))
        udid = html.escape(str(current["udid"] or "Pendiente"))
        plan = html.escape(str(current["plan_id"] or "—"))
        order_code = html.escape(str(current["provider_order_code"] or "Preparando"))
        url = _install_url(current)
        buttons = None
        if url:
            label = "🌐 Abrir entrega privada" if current["status"] == "completed" else "🌐 Ver estado en la web"
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton(label, url=url)]])

        await message.reply_text(
            "╭─ <b>💎 CERTIFICADO DIGITAL</b>\n"
            f"├ 🤖 Estado: <b>{status}</b>\n"
            f"├ 👤 Nombre: <b>{name}</b>\n"
            f"├ 🆔 UDID: <code>{udid}</code>\n"
            f"├ 📱 Dispositivo: <b>{html.escape(device)}</b>\n"
            f"├ 🧬 Plan: <b>#{plan}</b>\n"
            f"├ 🗓️ Registrado: <b>{html.escape(created)}</b>\n"
            f"├ 🛡️ Garantía: <b>activa según el plan</b>\n"
            f"├ 🔐 P12: <code>{password}</code>\n"
            f"╰ 🛰️ Orden: <code>{order_code}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=buttons,
        )


async def show_certificate_offer(update):
    if not bot.chungchi.configured:
        await update.effective_message.reply_text(
            "⚠️ Certificados temporalmente no disponibles. Falta configurar el API en Render."
        )
        return
    loading = await update.effective_message.reply_text("🔄 Consultando disponibilidad del certificado…")
    try:
        plans, balance = await asyncio.gather(
            asyncio.to_thread(bot.chungchi.plans), asyncio.to_thread(bot.chungchi.balance)
        )
    except ChungChiError as exc:
        await loading.edit_text(
            f"⚠️ No pude verificar ChungChi: {html.escape(str(exc))}", parse_mode=ParseMode.HTML
        )
        return
    plan = next((p for p in plans if int(p.get("id", -1)) == bot.settings.chungchi_plan_id), None)
    if not plan:
        await loading.edit_text("⚠️ El plan configurado no está disponible en ChungChi.")
        return
    provider_balance = float(balance.get("wallet", 0) or 0)
    provider_cost = float(plan.get("amount", 0) or 0)
    if provider_balance < provider_cost:
        await loading.edit_text("⚠️ Certificados agotados temporalmente. Contacta al soporte.")
        return
    price = certificate_price(update.effective_user.id)
    keys = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Comprar certificado", callback_data="cert:confirm"),
        InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
    ]])
    await loading.edit_text(
        "🤖🍎 <b>RANDY CERTIFICATE SYSTEM</b>\n"
        "<code>secure.purchase.module = READY</code>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💵 Precio: <b>{bot.money(price)}</b>\n"
        f"📅 Validez: <b>{html.escape(str(plan.get('validity') or '12 meses'))}</b>\n"
        f"🛡️ Garantía: <b>{html.escape(str(plan.get('warranty') or 'según el plan'))}</b>\n"
        "📦 Incluye <code>.p12</code> + <code>.mobileprovision</code> + entrega web privada.\n\n"
        "🔵 Después del pago registrarás tu <b>UDID</b> y podrás consultar el certificado siempre desde <b>💠 Tu certificado</b>.\n\n"
        "El costo se descontará de tu saldo del bot.",
        reply_markup=keys,
        parse_mode=ParseMode.HTML,
    )


_original_callback = bot.callback
_original_handle_flow = bot.handle_flow
_original_handle_text_menu = bot.handle_text_menu


async def callback(update, context):
    query = update.callback_query
    if not query:
        return await _original_callback(update, context)
    data = query.data or ""
    user = bot.current_user(update)
    admin_panel = bot.panel(context) == "admin"

    if data.startswith("partner:") and data.split(":")[1] == "prices":
        if not admin_panel or not bot.is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        parts = data.split(":")
        target = int(parts[2])
        await query.answer()
        prices = bot.db.reseller_prices(target)
        rows = []
        lines = ["💲 <b>Precio especial del socio</b>"]
        for p in prices:
            current = p["reseller_price_cents"]
            lines.append(
                f"• {html.escape(p['name'])}: {bot.money(current) if current else 'normal ' + bot.money(p['regular_price_cents'])}"
            )
            rows.append([InlineKeyboardButton(p["name"], callback_data=f"partnerprice:{target}:{p['id']}")])
        special = bot.db.private_setting(cert_price_key(target))
        special_cents = int(special) if special and str(special).isdigit() else None
        lines.append(
            f"• 🍎 Certificado iOS: {bot.money(special_cents) if special_cents else 'normal ' + bot.money(bot.settings.chungchi_sell_price_cents)}"
        )
        rows.append([InlineKeyboardButton("🍎 Certificado iOS", callback_data=f"certpartnerprice:{target}")])
        await query.message.reply_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML
        )
        return

    if data.startswith("certpartnerprice:"):
        if not admin_panel or not bot.is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        target = int(data.split(":", 1)[1])
        if not bot.db.reseller(target):
            await query.answer("Socio no encontrado", show_alert=True)
            return
        await query.answer()
        context.user_data["flow"] = {"name": "certificate_partner_price", "target": target}
        await query.message.reply_text(
            "🍎💲 Escribe el precio especial del Certificado iOS para este socio. Ejemplo: <code>3.50</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "cert:confirm":
        if admin_panel or user["role"] not in ("reseller", "admin"):
            await query.answer("Acceso no autorizado", show_alert=True)
            return
        await query.answer("Verificando disponibilidad…")
        try:
            plans, balance = await asyncio.gather(
                asyncio.to_thread(bot.chungchi.plans), asyncio.to_thread(bot.chungchi.balance)
            )
            plan = next((p for p in plans if int(p.get("id", -1)) == bot.settings.chungchi_plan_id), None)
            if not plan or float(balance.get("wallet", 0) or 0) < float(plan.get("amount", 0) or 0):
                raise ChungChiError("Certificados agotados temporalmente")
            digest = hashlib.sha256(
                f"{query.from_user.id}:{query.message.chat_id}:{query.message.message_id}:{bot.settings.bot_token}".encode()
            ).hexdigest().upper()
            key_code = f"CERT-{digest[:4]}-{digest[4:8]}-{digest[8:12]}"
            price = certificate_price(query.from_user.id)
            issued = bot.db.buy_certificate_key(query.from_user.id, key_code, price)
        except sqlite3.IntegrityError:
            await query.answer("Esta compra ya fue procesada", show_alert=True)
            return
        except (ChungChiError, InsufficientBalance, NotApproved) as exc:
            await query.message.reply_text(f"❌ {html.escape(str(exc))}", parse_mode=ParseMode.HTML)
            return
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "🤖✅ <b>PAGO CONFIRMADO</b>\n"
            "<code>certificate.payment = ACCEPTED</code>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🔑 Key: <code>{issued['key_code']}</code>\n"
            f"💵 Precio aplicado: <b>{bot.money(price)}</b>\n"
            f"💰 Saldo restante: <b>{bot.money(issued['balance_cents'])}</b>\n\n"
            "📲 Ahora registra tu UDID. Cuando el certificado esté listo quedará guardado en <b>💠 Tu certificado</b> y tendrás tu web privada de entrega.",
            reply_markup=bot.certificate_menu(bot.language_of(user)),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["flow"] = {"name": "certificate_udid", "certificate_key": issued["key_code"]}
        await query.message.reply_text("📱 Envía el UDID del iPhone o iPad:")
        return

    return await _original_callback(update, context)


async def handle_flow(update, context):
    flow = context.user_data.get("flow")
    if flow and flow.get("name") == "certificate_partner_price":
        if bot.panel(context) != "admin" or not bot.is_admin(update.effective_user.id):
            context.user_data.pop("flow", None)
            await update.effective_message.reply_text("⛔ Solo el administrador puede cambiar este precio.")
            return True
        text = (update.effective_message.text or "").strip()
        try:
            price = bot.parse_amount(text)
        except ValueError as exc:
            await update.effective_message.reply_text(f"❌ {exc}")
            return True
        target = int(flow["target"])
        if not bot.db.reseller(target):
            context.user_data.pop("flow", None)
            await update.effective_message.reply_text("❌ Socio no encontrado.")
            return True
        bot.db.set_private_setting(cert_price_key(target), str(price))
        context.user_data.pop("flow", None)
        await update.effective_message.reply_text(
            f"✅ 🍎 Precio especial de Certificado iOS para este socio: <b>{bot.money(price)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=bot.ADMIN_MENU,
        )
        return True
    return await _original_handle_flow(update, context)


async def handle_text_menu(update, context):
    if bot.panel(context) != "admin":
        text = (update.effective_message.text or "").strip()
        user = bot.current_user(update)
        if user and user["role"] in ("reseller", "admin") and text in (
            "💠 Tu certificado", "💠 My certificate"
        ):
            context.user_data.pop("flow", None)
            context.user_data.pop("certificate_pending", None)
            await show_my_certificates(update, context)
            return
    return await _original_handle_text_menu(update, context)


bot.USER_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("🍎 Certificado iOS"), KeyboardButton("🔑 Use Key")],
     [KeyboardButton("💠 Tu certificado"), KeyboardButton("🔍 Check UDID")],
     [KeyboardButton("⚙️ Settings")],
     [KeyboardButton("🛒 Comprar keys"), KeyboardButton("💳 Recargar saldo")],
     [KeyboardButton("🔑 Mis keys"), KeyboardButton("🔍 Consultar key")],
     [KeyboardButton("👤 Mi cuenta"), KeyboardButton("🧾 Historial")],
     [KeyboardButton("🆘 Soporte"), KeyboardButton("🌐 Idioma / Language")]],
    resize_keyboard=True,
)
bot.USER_MENU_EN = ReplyKeyboardMarkup(
    [[KeyboardButton("🍎 iOS Certificate"), KeyboardButton("🔑 Use Key")],
     [KeyboardButton("💠 My certificate"), KeyboardButton("🔍 Check UDID")],
     [KeyboardButton("⚙️ Settings")],
     [KeyboardButton("🛒 Buy keys"), KeyboardButton("💳 Add balance")],
     [KeyboardButton("🔑 My keys"), KeyboardButton("🔍 Check key")],
     [KeyboardButton("👤 My account"), KeyboardButton("🧾 History")],
     [KeyboardButton("🆘 Support"), KeyboardButton("🌐 Language / Idioma")]],
    resize_keyboard=True,
)
bot.CERTIFICATE_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("👋 Welcome!")],
     [KeyboardButton("🍎 Certificado iOS"), KeyboardButton("💠 Tu certificado")],
     [KeyboardButton("🔍 Check UDID"), KeyboardButton("🔑 Use Key")],
     [KeyboardButton("⚙️ Settings")]],
    resize_keyboard=True,
)
bot.CERTIFICATE_MENU_EN = ReplyKeyboardMarkup(
    [[KeyboardButton("👋 Welcome!")],
     [KeyboardButton("🍎 iOS Certificate"), KeyboardButton("💠 My certificate")],
     [KeyboardButton("🔍 Check UDID"), KeyboardButton("🔑 Use Key")],
     [KeyboardButton("⚙️ Settings")]],
    resize_keyboard=True,
)

bot.show_certificate_offer = show_certificate_offer
bot.callback = callback
bot.handle_flow = handle_flow
bot.handle_text_menu = handle_text_menu


if __name__ == "__main__":
    bot.main()
