from __future__ import annotations

import asyncio
import hashlib
import html
import sqlite3

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
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


async def show_certificate_offer(update):
    if not bot.chungchi.configured:
        await update.effective_message.reply_text(
            "⚠️ Certificados temporalmente no disponibles. Falta configurar el API en Render."
        )
        return
    try:
        plans, balance = await asyncio.gather(
            asyncio.to_thread(bot.chungchi.plans), asyncio.to_thread(bot.chungchi.balance)
        )
    except ChungChiError as exc:
        await update.effective_message.reply_text(
            f"⚠️ No pude verificar ChungChi: {html.escape(str(exc))}", parse_mode=ParseMode.HTML
        )
        return
    plan = next((p for p in plans if int(p.get("id", -1)) == bot.settings.chungchi_plan_id), None)
    if not plan:
        await update.effective_message.reply_text("⚠️ El plan configurado no está disponible en ChungChi.")
        return
    provider_balance = float(balance.get("wallet", 0) or 0)
    provider_cost = float(plan.get("amount", 0) or 0)
    if provider_balance < provider_cost:
        await update.effective_message.reply_text("⚠️ Certificados agotados temporalmente. Contacta al soporte.")
        return
    price = certificate_price(update.effective_user.id)
    keys = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Comprar", callback_data="cert:confirm"),
        InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
    ]])
    await update.effective_message.reply_text(
        "🍎 <b>CERTIFICADO iOS</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"💵 Precio: <b>{bot.money(price)}</b>\n"
        f"📅 Validez: <b>{html.escape(str(plan.get('validity') or '12 meses'))}</b>\n"
        f"🛡️ Garantía: <b>{html.escape(str(plan.get('warranty') or 'según el plan'))}</b>\n"
        "📦 Incluye <code>.p12</code>, contraseña y <code>.mobileprovision</code>.\n\n"
        "El costo se descontará de tu saldo del bot.",
        reply_markup=keys,
        parse_mode=ParseMode.HTML,
    )


_original_callback = bot.callback
_original_handle_flow = bot.handle_flow


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
            "🎉 <b>PAGO CONFIRMADO</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"🔑 Key: <code>{issued['key_code']}</code>\n"
            f"💵 Precio aplicado: <b>{bot.money(price)}</b>\n"
            f"💰 Saldo restante: <b>{bot.money(issued['balance_cents'])}</b>\n\n"
            "La key se activó para iniciar tu certificado.",
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
        try:
            await bot.reseller_bot(context).send_message(
                target, f"🍎 Tienes un precio especial para Certificado iOS: {bot.money(price)}"
            )
        except Exception:
            pass
        return True
    return await _original_handle_flow(update, context)


bot.show_certificate_offer = show_certificate_offer
bot.callback = callback
bot.handle_flow = handle_flow


if __name__ == "__main__":
    bot.main()
