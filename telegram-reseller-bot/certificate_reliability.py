from __future__ import annotations

import asyncio
import hmac
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit

from telegram import Update

import bot
import health


log = bot.log
_original_submit_certificate_order = bot.submit_certificate_order
_original_callback = bot.callback
_original_health_post = health.HealthHandler.do_POST


# ChungChi can take longer than Telegram's webhook window. The provider request already
# runs in a worker thread, so allowing a little more time here does not block the bot.
try:
    bot.chungchi.timeout = max(int(getattr(bot.chungchi, "timeout", 25)), 45)
except Exception:
    pass


def _provider_plan_id(item: dict) -> int | None:
    value = item.get("plan_id")
    if value is None and isinstance(item.get("plan"), dict):
        value = item["plan"].get("id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _provider_created(item: dict) -> datetime | None:
    for key in ("created_at", "createdAt", "registered_at", "registeredAt"):
        value = item.get(key)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _local_created(row) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


async def recover_unlinked_order(row):
    """Recover an order when ChungChi accepted it but the create response timed out."""
    if row["provider_order_code"]:
        return row
    try:
        provider_orders = await asyncio.to_thread(bot.chungchi.orders_by_udid, row["udid"])
    except Exception as exc:
        log.warning("No se pudo recuperar pedido ChungChi #%s por UDID: %s", row["id"], exc)
        return None

    local_created = _local_created(row)
    candidates: list[dict] = []
    for item in provider_orders:
        if not isinstance(item, dict):
            continue
        code = str(item.get("order_code") or "").strip()
        if not code or bot.db.certificate_order_by_code(code):
            continue
        plan_id = _provider_plan_id(item)
        if plan_id is not None and plan_id != int(row["plan_id"]):
            continue
        provider_created = _provider_created(item)
        if local_created and provider_created:
            # A timed-out create should be close to our local order. This guard keeps us
            # from attaching an unrelated historical certificate on the same UDID.
            if abs((provider_created - local_created).total_seconds()) > 45 * 60:
                continue
        candidates.append(item)

    if not candidates:
        return None

    # Prefer the newest provider result. Only attach automatically when the match is
    # unambiguous, or when the newest item carries a timestamp close to this purchase.
    candidates.sort(
        key=lambda item: (_provider_created(item) or datetime.min.replace(tzinfo=timezone.utc), str(item.get("order_code") or "")),
        reverse=True,
    )
    candidate = candidates[0]
    if len(candidates) > 1 and _provider_created(candidate) is None:
        log.warning("Recuperación ambigua para certificado #%s; hay %s pedidos posibles", row["id"], len(candidates))
        return None

    try:
        attached = bot.db.attach_provider_order(row["id"], candidate)
        log.info("Pedido ChungChi recuperado: local=%s provider=%s status=%s", row["id"], attached["provider_order_code"], attached["status"])
        return attached
    except Exception as exc:
        log.warning("No se pudo vincular pedido recuperado #%s: %s", row["id"], exc)
        return None


async def reliable_submit_certificate_order(message, context, user_id: int) -> None:
    await _original_submit_certificate_order(message, context, user_id)
    rows = bot.db.certificate_orders_for_user(user_id, limit=1)
    if not rows:
        return
    row = rows[0]
    if row["status"] == "review" and not row["provider_order_code"]:
        recovered = await recover_unlinked_order(row)
        if not recovered:
            return
        try:
            await message.reply_text(
                "🔄 <b>Pedido recuperado</b>\nTu certificado ya está vinculado y seguiré revisándolo automáticamente.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        if recovered["status"] == "completed" and recovered["download_url"] and not recovered["delivered_at"]:
            await bot.deliver_certificate(context.bot, recovered)


async def reliable_certificate_poll_loop(tg_bot, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        if bot.chungchi.configured:
            # Normal linked orders.
            for row in bot.db.pending_certificate_orders():
                await bot.refresh_certificate_order(tg_bot, row)

            # Ambiguous create responses used to become permanent "Review" rows because
            # they had no provider_order_code and therefore never entered the normal poll.
            try:
                with bot.db.connect() as con:
                    unlinked = con.execute(
                        """SELECT * FROM certificate_orders
                           WHERE provider_order_code IS NULL AND status='review'
                           ORDER BY updated_at LIMIT 20"""
                    ).fetchall()
            except Exception as exc:
                log.warning("No se pudieron leer certificados en revisión: %s", exc)
                unlinked = []

            for row in unlinked:
                recovered = await recover_unlinked_order(row)
                if recovered and recovered["status"] == "completed" and recovered["download_url"] and not recovered["delivered_at"]:
                    await bot.deliver_certificate(tg_bot, recovered)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=45)
        except asyncio.TimeoutError:
            pass


async def reliable_callback(update, context):
    # A manual resend action can be used later by any UI without changing delivery logic.
    query = update.callback_query
    data = query.data if query else ""
    if query and data.startswith("certzip:"):
        try:
            order_id = int(data.split(":", 1)[1])
        except ValueError:
            await query.answer("Solicitud inválida", show_alert=True)
            return
        row = bot.db.certificate_order(order_id, query.from_user.id)
        if not row or row["status"] != "completed" or not row["download_url"]:
            await query.answer("El ZIP todavía no está listo", show_alert=True)
            return
        try:
            await query.answer("Reenviando ZIP…")
        except Exception:
            pass
        # Clearing delivered_at is intentionally unnecessary. deliver_certificate retries
        # based on the row supplied here and only marks delivery after send_document works.
        await bot.deliver_certificate(context.bot, row)
        return
    return await _original_callback(update, context)


def fast_telegram_webhook_post(self) -> None:
    """Acknowledge Telegram immediately so slow provider work is never retried."""
    server = self.server
    path = urlsplit(self.path).path
    if path in ("/chungchi/webhook", "/maintenance/import-esign"):
        return _original_health_post(self)

    app = server.applications.get(path)
    secret = server.secrets.get(path)
    supplied = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if app is None or secret is None:
        self.send_error(404)
        return
    if not hmac.compare_digest(supplied, secret):
        self.send_error(403)
        return
    try:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("Tamaño de actualización inválido")
        payload = json.loads(self.rfile.read(length))
        update = Update.de_json(payload, app.bot)
        future = asyncio.run_coroutine_threadsafe(app.process_update(update), server.event_loop)

        def report_result(done_future):
            try:
                done_future.result()
            except Exception:
                health.log.exception("Actualización de Telegram falló después del ACK")

        future.add_done_callback(report_result)
    except Exception as exc:
        health.log.exception("No se pudo aceptar el webhook: %s", exc)
        self.send_error(400)
        return

    # Telegram only needs an ACK. Waiting for ChungChi here caused a 20-second timeout,
    # Telegram retried the same callback, and the retry then failed as "query too old".
    self.send_response(200)
    self.send_header("Content-Length", "0")
    self.end_headers()


bot.submit_certificate_order = reliable_submit_certificate_order
bot.certificate_poll_loop = reliable_certificate_poll_loop
bot.callback = reliable_callback
health.HealthHandler.do_POST = fast_telegram_webhook_post
log.info("Certificate reliability hotfix loaded")
