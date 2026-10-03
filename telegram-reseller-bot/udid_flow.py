"""Short-lived, private iOS Profile Service sessions for the reseller bot."""
import asyncio
import html
import hmac
import os
import plistlib
import re
import subprocess
import uuid


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
            handler.send_header("Content-Disposition", 'attachment; filename="Randy-UDID.mobileconfig"')
        elif len(parts) == 2:
            udid = html.escape(row["udid"] or "")
            result = (f'<h2>Tu UDID está listo</h2><code id="udid">{udid}</code><button onclick="navigator.clipboard.writeText(document.getElementById(\'udid\').textContent)">Copiar UDID</button><p>Cópialo y vuelve al chat para continuar. Puedes quitar el perfil de Ajustes.</p>'
                      if udid else f'<h1>Tu equipo.<br>Tu certificado.</h1><p>Obtén el UDID de este iPhone o iPad para registrar tu certificado.</p><a class="button" href="/udid/profile/{token}">Obtener mi UDID ↗</a><ol><li>Abre esta página en Safari.</li><li>Descarga el perfil y permite la descarga.</li><li>Ajustes → Perfil descargado → Instalar.</li><li>Vuelve aquí. El UDID también llegará a Telegram.</li></ol><p class="small">El perfil solicita UDID y modelo. Se vinculan a tu cuenta durante 30 minutos. No configura administración remota. Puedes quitarlo después.</p>')
            payload = f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Randy Mod · UDID</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#050f1a;color:#edf8ff;font:16px system-ui}}main{{max-width:640px;margin:auto;padding:24px}}.brand{{letter-spacing:3px;color:#78baff;font-size:12px;font-weight:800}}.art{{height:210px;margin:22px 0;border-radius:28px;overflow:hidden;position:relative;background:#0a2038}}.art img{{width:100%;height:100%;object-fit:cover;animation:float 8s ease-in-out infinite alternate}}.art:after{{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,#071a3b66)}}@keyframes float{{to{{transform:scale(1.07) translateY(-4px)}}}}h1{{font-size:38px;line-height:1.05}}p,li{{color:#b9cce1;line-height:1.6}}li{{margin:12px 0}}a.button,button{{display:block;width:100%;padding:18px;border:0;border-radius:17px;background:#48b4ff;color:#041e35;font-size:17px;font-weight:800;text-align:center;text-decoration:none}}code{{display:block;overflow-wrap:anywhere;padding:22px;background:#11283f;border-radius:18px;margin:20px 0}}.small{{font-size:12px}}@media(prefers-reduced-motion:reduce){{.art img{{animation:none}}}}</style><main><div class="brand">RANDY MOD / DEVICE ID</div><div class="art"><img src="/brand/cover" alt="Randy Mod"></div>{result}</main></html>'''.encode()
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
        except (ValueError, OSError, subprocess.TimeoutExpired, plistlib.InvalidFileException):
            handler.send_error(400, "No pude leer el UDID. Solicita otro enlace en el bot.")
            return True
        if fresh:
            async def notify():
                try:
                    await self.bot.send_message(row["user_id"], f"✅ Tu UDID está listo\nEquipo: {html.escape(model)}\n<code>{udid}</code>\nCópialo y envíalo al registro de tu certificado.", parse_mode="HTML")
                except Exception:
                    # Result remains available in the private page if Telegram fails.
                    pass
            asyncio.run_coroutine_threadsafe(notify(), self.loop)
        handler.send_response(303)
        handler.send_header("Location", f"/udid/{token}")
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        return True
