"""Compact certificate preview with the app logo embedded in the card."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def _font(size: int, bold: bool = False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)


def _short(value, limit=28):
    value = str(value or "—")
    return value if len(value) <= limit else value[:limit - 1] + "…"


def file_icon(kind: str) -> bytes:
    """Bundled thumbnail for a P12 or provisioning document in Telegram."""
    green = kind == "p12"
    picture = Image.new("RGB", (320, 320), "#0a241d" if green else "#101e37")
    draw = ImageDraw.Draw(picture)
    accent = "#45e0a0" if green else "#75afff"
    fill = "#14523d" if green else "#1c416d"
    draw.rounded_rectangle((27, 27, 293, 293), radius=61, fill=fill, outline=accent, width=5)
    draw.rounded_rectangle((79, 59, 241, 254), radius=21, fill="#effff7" if green else "#eff6ff")
    draw.polygon(((200, 59), (241, 100), (200, 100)), fill="#a4d9bf" if green else "#a7c5ed")
    draw.line((106, 130, 211, 130), fill=fill, width=8)
    draw.line((106, 153, 193, 153), fill=fill, width=8)
    draw.rounded_rectangle((90, 178, 230, 230), radius=13, fill="#087b51" if green else "#2e6cb5")
    draw.text((160, 204), "P12" if green else "PROFILE", anchor="mm", font=_font(27 if green else 17, True), fill="white")
    output = io.BytesIO()
    picture.save(output, format="JPEG", quality=91, optimize=True)
    return output.getvalue()


def certificate_card(order, logo: bytes | None = None, app: str | None = None) -> bytes:
    """Return a small JPEG that fits naturally inside a Telegram photo message."""
    width, height = 960, 650
    picture = Image.new("RGB", (width, height), "#060e1e")
    draw = ImageDraw.Draw(picture)
    for y in range(height):
        draw.line((0, y, width, y), fill=(6 + y // 95, 14 + y // 45, 30 + y // 18))
    draw.rounded_rectangle((22, 22, 938, 628), radius=42, fill="#0d1e38", outline="#386ca7", width=2)
    draw.rounded_rectangle((48, 47, 912, 182), radius=30, fill="#12345f")
    draw.rounded_rectangle((69, 66, 167, 164), radius=24, fill="#07192d")
    if logo:
        try:
            with Image.open(io.BytesIO(logo)) as source:
                icon = ImageOps.fit(source.convert("RGB"), (90, 90))
                mask = Image.new("L", (90, 90), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, 89, 89), radius=19, fill=255)
                picture.paste(icon, (73, 70), mask)
        except (OSError, ValueError):
            logo = None
    if not logo:
        draw.text((107, 82), "R", anchor="mt", font=_font(60, True), fill="#68baff")
    draw.text((190, 73), "RANDY SYSTEMS  /  CERTIFICADOS", font=_font(19, True), fill="#80b9f6")
    draw.text((190, 107), app or "Tu certificado", font=_font(40, True), fill="white")
    status = "LISTO" if order["status"] == "completed" else "EN PROCESO"
    draw.rounded_rectangle((702, 102, 885, 150), radius=24, fill="#0c5d52" if status == "LISTO" else "#665012")
    draw.text((794, 127), status, anchor="mm", font=_font(19, True), fill="#c8fff0" if status == "LISTO" else "#ffe7a3")

    name = _short(order["display_name"], 36)
    device = _short(order["device"] or "iPhone", 32)
    udid = _short(order["udid"], 42)
    try:
        date = datetime.fromisoformat(str(order["completed_at"] or order["created_at"]).replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%d %b %Y")
    except (ValueError, TypeError):
        date = "Pendiente"
    fields = [("NOMBRE", name), ("DISPOSITIVO", device), ("UDID", udid), ("REGISTRADO", date)]
    for idx, (label, value) in enumerate(fields):
        y = 211 + idx * 95
        draw.text((76, y), label, font=_font(19, True), fill="#78a7d7")
        draw.text((76, y + 30), value, font=_font(27 if label == "UDID" else 30, label != "UDID"), fill="#f1f8ff")
        if idx < 3:
            draw.line((76, y + 80, 882, y + 80), fill="#244363", width=2)
    draw.text((76, 600), "Entrega privada  ·  GBox / ESign", font=_font(17), fill="#8cb7e4")
    output = io.BytesIO()
    picture.save(output, format="JPEG", quality=86, optimize=True)
    return output.getvalue()


def app_tile(logo: bytes | None, name: str = "GBox") -> bytes:
    """Small app listing with a real logo, like a Telegram app preview."""
    green = name == "GBox"
    picture = Image.new("RGB", (960, 245), "#061a15" if green else "#06152a")
    draw = ImageDraw.Draw(picture)
    draw.rounded_rectangle((16, 15, 943, 229), radius=38, fill="#0d4435" if green else "#0e2446", outline="#3ce3a0" if green else "#3379b7", width=3)
    draw.rounded_rectangle((43, 39, 209, 205), radius=34, fill="#006d4a" if green else "#21497a")
    if logo:
        try:
            with Image.open(io.BytesIO(logo)) as source:
                icon = ImageOps.fit(source.convert("RGB"), (146, 146))
                mask = Image.new("L", (146, 146), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, 145, 145), radius=28, fill=255)
                picture.paste(icon, (53, 49), mask)
        except (OSError, ValueError):
            logo = None
    if not logo:
        draw.text((126, 121), name[0], anchor="mm", font=_font(85, True), fill="#99daff")
    draw.text((246, 59), "RANDY MOD  /  INSTALACIÓN PRIVADA", font=_font(19, True), fill="#93ffce" if green else "#8dbdec")
    draw.text((244, 94), name, font=_font(54, True), fill="#ffffff")
    draw.text((246, 164), "Tu app · tu certificado", font=_font(25), fill="#cdf8e4" if green else "#c4dcf5")
    output = io.BytesIO()
    picture.save(output, format="JPEG", quality=86, optimize=True)
    return output.getvalue()
