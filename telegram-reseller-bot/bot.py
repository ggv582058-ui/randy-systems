from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import os
import signal
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from config import load_settings
from database import Database, InsufficientBalance, NotApproved, NotFound, OutOfStock, StoreError
from health import start_health_server


logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("randy-reseller")
settings = load_settings()
db = Database(settings.database_path)


ADMIN_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("📦 Productos"), KeyboardButton("🔑 Añadir keys")],
     [KeyboardButton("👥 Revendedores"), KeyboardButton("💳 Recargas")],
     [KeyboardButton("📊 Estadísticas"), KeyboardButton("👤 Vista revendedor")]],
    resize_keyboard=True,
)
USER_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("🛒 Comprar keys"), KeyboardButton("💳 Recargar saldo")],
     [KeyboardButton("👤 Mi cuenta"), KeyboardButton("🧾 Historial")],
     [KeyboardButton("🆘 Soporte")]],
    resize_keyboard=True,
)
PENDING_MENU = ReplyKeyboardMarkup([[KeyboardButton("📨 Solicitar acceso")]], resize_keyboard=True)


def money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def parse_amount(value: str) -> int:
    try:
        amount = Decimal(value.replace("$", "").replace(",", "").strip())
        cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        raise ValueError("Cantidad inválida")
    if cents <= 0 or cents > 10_000_000:
        raise ValueError("Cantidad fuera de rango")
    return cents


def current_user(update: Update):
    tg = update.effective_user
    return db.ensure_user(tg.id, tg.username, tg.full_name, tg.id in settings.admin_ids)


def is_admin(user_id: int) -> bool:
    row = db.user(user_id)
    return bool(row and row["role"] == "admin" and user_id in settings.admin_ids)


def panel(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.application.bot_data.get("panel", "reseller")


def reseller_bot(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data.get("reseller_bot", context.bot)


def admin_bot(context: ContextTypes.DEFAULT_TYPE):
    return context.application.bot_data.get("admin_bot", context.bot)


async def send_home(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str | None = None) -> None:
    user = current_user(update)
    chat = update.effective_chat
    if panel(context) == "admin":
        if update.effective_user.id not in settings.admin_ids:
            await chat.send_message("⛔ Este bot es privado y exclusivo para el administrador.")
            return
        text = note or f"🛡️ <b>{html.escape(settings.store_name)}</b>\nPanel de administrador"
        await chat.send_message(text, reply_markup=ADMIN_MENU, parse_mode=ParseMode.HTML)
    elif user["role"] in ("reseller", "admin"):
        text = note or f"💎 <b>{html.escape(settings.store_name)}</b>\nSaldo: <b>{money(user['balance_cents'])}</b>"
        await chat.send_message(text, reply_markup=USER_MENU, parse_mode=ParseMode.HTML)
    else:
        label = "Tu solicitud está esperando revisión." if user["requested_access"] else "Solicita acceso para entrar como revendedor."
        await chat.send_message(f"🔒 <b>Acceso restringido</b>\n{label}", reply_markup=PENDING_MENU, parse_mode=ParseMode.HTML)


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
    for admin_id in settings.admin_ids:
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


def product_buttons(prefix: str, active_only: bool = True) -> InlineKeyboardMarkup:
    rows = []
    for p in db.products(active_only=active_only):
        rows.append([InlineKeyboardButton(
            f"{p['name']} · {money(p['price_cents'])} · Stock {p['stock']}",
            callback_data=f"{prefix}:{p['id']}",
        )])
    return InlineKeyboardMarkup(rows or [[InlineKeyboardButton("Sin productos", callback_data="noop")]])


async def show_buy(update: Update) -> None:
    await update.effective_message.reply_text("🛒 <b>Selecciona un producto</b>", reply_markup=product_buttons("buy"), parse_mode=ParseMode.HTML)


async def show_products_admin(update: Update) -> None:
    products = db.products(active_only=False)
    lines = ["📦 <b>Catálogo</b>"]
    rows = [[InlineKeyboardButton("➕ Crear producto", callback_data="product:new")]]
    for p in products:
        status = "✅" if p["active"] else "⛔"
        lines.append(f"{status} ID {p['id']} · {html.escape(p['name'])} · {money(p['price_cents'])} · Stock {p['stock']}")
        rows.append([InlineKeyboardButton(
            f"{'Desactivar' if p['active'] else 'Activar'} · {p['name']}", callback_data=f"product:toggle:{p['id']}"
        )])
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
        rows.append([InlineKeyboardButton(f"🚫 Revocar {tag}", callback_data=f"user:revoke:{u['telegram_id']}")])
    await update.effective_message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(rows) if rows else None, parse_mode=ParseMode.HTML
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
            await update.effective_chat.send_photo(item["proof_value"], caption=text, reply_markup=keys, parse_mode=ParseMode.HTML)
        elif item["proof_type"] == "document":
            await update.effective_chat.send_document(item["proof_value"], caption=text, reply_markup=keys, parse_mode=ParseMode.HTML)
        else:
            await update.effective_chat.send_message(text + f"\nReferencia: <code>{html.escape(item['proof_value'])}</code>", reply_markup=keys, parse_mode=ParseMode.HTML)


async def show_account(update: Update) -> None:
    u = current_user(update)
    tag = f"@{u['username']}" if u["username"] else "Sin username"
    await update.effective_message.reply_text(
        f"👤 <b>Mi cuenta</b>\nID: <code>{u['telegram_id']}</code>\nUsuario: {html.escape(tag)}\nRol: {u['role']}\nSaldo: <b>{money(u['balance_cents'])}</b>",
        parse_mode=ParseMode.HTML,
    )


async def show_history(update: Update) -> None:
    rows = db.history(update.effective_user.id)
    if not rows:
        await update.effective_message.reply_text("🧾 Todavía no tienes movimientos.")
        return
    lines = ["🧾 <b>Últimos movimientos</b>"]
    for row in rows:
        sign = "+" if row["amount_cents"] > 0 else ""
        lines.append(f"• {row['kind']} · {sign}{money(row['amount_cents'])} · Saldo {money(row['balance_after_cents'])}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


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


async def handle_text_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = current_user(update)
    text = (update.effective_message.text or "").strip()
    admin_panel = panel(context) == "admin"
    if admin_panel and update.effective_user.id not in settings.admin_ids:
        await update.effective_message.reply_text("⛔ Este bot es privado y exclusivo para el administrador.")
        return
    if text == "📨 Solicitar acceso":
        if admin_panel:
            await send_home(update, context)
            return
        await access_request(update, context)
        return
    if user["role"] not in ("reseller", "admin"):
        await send_home(update, context)
        return

    if await handle_flow(update, context):
        return

    if not admin_panel and text == "🛒 Comprar keys":
        await show_buy(update)
    elif not admin_panel and text == "💳 Recargar saldo":
        await begin_topup(update, context)
    elif not admin_panel and text == "👤 Mi cuenta":
        await show_account(update)
    elif not admin_panel and text == "🧾 Historial":
        await show_history(update)
    elif not admin_panel and text == "🆘 Soporte":
        await update.effective_message.reply_text(f"🆘 Soporte: {settings.support_username}")
    elif admin_panel and user["role"] == "admin" and text == "📦 Productos":
        await show_products_admin(update)
    elif admin_panel and user["role"] == "admin" and text == "🔑 Añadir keys":
        await begin_add_keys(update)
    elif admin_panel and user["role"] == "admin" and text == "👥 Revendedores":
        await show_resellers(update)
    elif admin_panel and user["role"] == "admin" and text == "💳 Recargas":
        await show_topups(update)
    elif admin_panel and user["role"] == "admin" and text == "📊 Estadísticas":
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
        if message.photo:
            proof_type, proof = "photo", message.photo[-1].file_id
        elif message.document:
            proof_type, proof = "document", message.document.file_id
        elif text:
            proof_type, proof = "text", text[:500]
        else:
            await message.reply_text("❌ Envía una imagen, documento o referencia escrita.")
            return True
        topup_id = db.create_topup(message.from_user.id, flow["amount_cents"], proof_type, proof)
        context.user_data.pop("flow", None)
        await message.reply_text(f"✅ Recarga #{topup_id} enviada. Espera la aprobación del Admin.", reply_markup=USER_MENU)
        item = db.topup(topup_id)
        keys = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Aprobar", callback_data=f"topup:approve:{topup_id}"),
            InlineKeyboardButton("❌ Rechazar", callback_data=f"topup:reject:{topup_id}"),
        ]])
        caption = f"💳 <b>Nueva recarga #{topup_id}</b>\nUsuario: <code>{item['user_id']}</code>\nCantidad: <b>{money(item['amount_cents'])}</b>"
        for admin_id in settings.admin_ids:
            try:
                if proof_type == "photo":
                    await admin_bot(context).send_photo(admin_id, proof, caption=caption, reply_markup=keys, parse_mode=ParseMode.HTML)
                elif proof_type == "document":
                    await admin_bot(context).send_document(admin_id, proof, caption=caption, reply_markup=keys, parse_mode=ParseMode.HTML)
                else:
                    await admin_bot(context).send_message(admin_id, caption + f"\nReferencia: <code>{html.escape(proof)}</code>", reply_markup=keys, parse_mode=ParseMode.HTML)
            except Exception as exc:
                log.warning("No se notificó recarga al admin %s: %s", admin_id, exc)
        return True

    if flow["name"] == "product_name":
        if len(text) < 2:
            await message.reply_text("Escribe un nombre válido.")
            return True
        flow["name"], flow["product_name"] = "product_price", text[:100]
        await message.reply_text("💵 Escribe el precio de venta. Ejemplo: 14.99")
        return True

    if flow["name"] == "product_price":
        try:
            flow["price_cents"] = parse_amount(text)
        except ValueError:
            await message.reply_text("❌ Precio inválido. Ejemplo: 14.99")
            return True
        flow["name"] = "product_description"
        await message.reply_text("📝 Escribe una descripción corta o envía <code>-</code> para omitirla.", parse_mode=ParseMode.HTML)
        return True

    if flow["name"] == "product_description":
        desc = "" if text == "-" else text[:500]
        product_id = db.create_product(flow["product_name"], flow["price_cents"], desc)
        context.user_data.pop("flow", None)
        await message.reply_text(f"✅ Producto #{product_id} creado.", reply_markup=ADMIN_MENU)
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
    await query.answer()
    user = current_user(update)
    data = query.data or ""
    admin_panel = panel(context) == "admin"
    if data == "noop":
        return

    if data.startswith("user:"):
        if not admin_panel or not is_admin(query.from_user.id):
            await query.answer("Solo Admin", show_alert=True)
            return
        _, action, raw_id = data.split(":")
        target = int(raw_id)
        role = {"approve": "reseller", "reject": "rejected", "revoke": "rejected"}[action]
        if db.set_role(target, role):
            label = "aprobado" if role == "reseller" else "sin acceso"
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ Usuario {target}: {label}.")
            try:
                await reseller_bot(context).send_message(target, "✅ Tu cuenta fue aprobada como revendedor." if role == "reseller" else "❌ Tu acceso de revendedor no fue aprobado.", reply_markup=USER_MENU if role == "reseller" else PENDING_MENU)
            except Exception:
                pass
        return

    if data == "product:new":
        if not admin_panel or not is_admin(query.from_user.id):
            return
        context.user_data["flow"] = {"name": "product_name"}
        await query.message.reply_text("📦 Ingresa el nombre del producto:")
        return

    if data.startswith("product:toggle:"):
        if not admin_panel or not is_admin(query.from_user.id):
            return
        product_id = int(data.rsplit(":", 1)[1])
        product = db.product(product_id)
        if product:
            db.set_product_active(product_id, not bool(product["active"]))
            await query.message.reply_text("✅ Estado del producto actualizado.")
        return

    if data.startswith("addkeys:"):
        if not admin_panel or not is_admin(query.from_user.id):
            return
        product_id = int(data.split(":")[1])
        context.user_data["flow"] = {"name": "add_keys", "product_id": product_id}
        await query.message.reply_text("🔑 Envía las keys, <b>una por línea</b>.", parse_mode=ParseMode.HTML)
        return

    if data.startswith("buy:"):
        if admin_panel:
            await query.answer("Usa el bot de revendedores", show_alert=True)
            return
        if user["role"] not in ("reseller", "admin"):
            return
        product_id = int(data.split(":")[1])
        p = db.product(product_id)
        if not p or not p["active"]:
            await query.answer("Producto no disponible", show_alert=True)
            return
        keys = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirmar compra", callback_data=f"confirm:{product_id}"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ]])
        await query.message.reply_text(
            f"<b>{html.escape(p['name'])}</b>\nPrecio: {money(p['price_cents'])}\nStock: {p['stock']}\n\n¿Confirmar compra?",
            reply_markup=keys, parse_mode=ParseMode.HTML,
        )
        return

    if data.startswith("confirm:"):
        if admin_panel:
            return
        product_id = int(data.split(":")[1])
        try:
            sale = db.purchase(query.from_user.id, product_id)
        except (InsufficientBalance, OutOfStock, NotApproved, NotFound) as exc:
            await query.answer(str(exc), show_alert=True)
            return
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "✅ <b>Compra completada</b>\n"
            f"Orden: #{sale['order_id']}\nProducto: {html.escape(sale['product_name'])}\n"
            f"Key: <code>{html.escape(sale['key'])}</code>\nSaldo restante: <b>{money(sale['balance_cents'])}</b>\n\n"
            "Guarda esta key en un lugar seguro.",
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "cancel":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Compra cancelada.")
        return

    if data.startswith("topup:"):
        if not admin_panel or not is_admin(query.from_user.id):
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
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(message)
        try:
            await reseller_bot(context).send_message(row["user_id"], f"{message}\nCantidad: {money(row['amount_cents'])}")
        except Exception:
            pass


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
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_text_menu))
    app.add_error_handler(error_handler)
    return app


async def run_bots() -> None:
    db.initialize()
    server = start_health_server(asyncio.get_running_loop())
    reseller_app = build_application(settings.bot_token, "reseller")
    admin_app = build_application(settings.admin_bot_token, "admin")
    apps = (reseller_app, admin_app)
    initialized = []
    started = []
    stop_event = asyncio.Event()
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
        log.info("Bots iniciados por webhook: revendedores + admin (%s)", settings.store_name)
        await stop_event.wait()
    finally:
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
