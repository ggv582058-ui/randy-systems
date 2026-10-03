"""Shared emoji decoration without changing Telegram entity offsets or actions."""
import html
import re
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup, InlineKeyboardButton, KeyboardButton

# Stable keys let new messages use the same admin preferences automatically.
SYMBOLS = {
    "success": ("✅", "Confirmado"), "error": ("❌", "Error / cancelar"),
    "warning": ("⚠️", "Advertencia"), "wait": ("⏳", "Espera"),
    "id": ("🆔", "UDID / identificación"), "phone": ("📱", "Dispositivo"),
    "lock": ("🔐", "Contraseña"), "edit": ("✏️", "Editar"),
    "pencil": ("📝", "Texto"), "apple": ("🍎", "iOS"),
    "key": ("🔑", "Key"), "search": ("🔍", "Consultar"),
    "diamond": ("💎", "VIP / entrega"), "money": ("💰", "Recargar"),
    "balance": ("💵", "Saldo"), "dollars": ("💲", "Precio"),
    "wallet": ("💳", "Pago"), "package": ("📦", "Producto"),
    "cart": ("🛒", "Comprar"), "globe": ("🌐", "Página web"),
    "world": ("🌎", "Idioma"), "settings": ("⚙️", "Configuración"),
    "user": ("👤", "Cuenta"), "users": ("👥", "Socios"),
    "announcement": ("📢", "Anuncios"), "megaphone": ("📣", "Avisos"),
    "photo": ("📷", "Fotos"), "video": ("🎬", "Videos"),
    "media": ("🎨", "Multimedia"), "file": ("📄", "Archivo"),
    "download": ("📥", "Descargar"), "upload": ("📤", "Enviar"),
    "return": ("↩️", "Volver"), "back": ("⬅️", "Atrás"),
    "support": ("🆘", "Soporte"), "chat": ("💬", "Mensajes"),
    "time": ("⏱️", "Contador"), "calendar": ("📅", "Fecha"),
    "star": ("⭐", "Destacado"), "rocket": ("🚀", "Iniciar"),
    "fire": ("🔥", "Novedad"), "lightning": ("⚡", "Preparar"),
    "welcome": ("👋", "Bienvenida"), "eye": ("👁️", "Vista previa"),
    "clipboard": ("📋", "Instrucciones"), "receipt": ("🧾", "Referencia"),
    "gift": ("🎁", "Promoción"), "crown": ("👑", "Admin"),
}
GLOBAL_SLOTS = {"global_" + key: f"{symbol} {label} · general" for key, (symbol, label) in SYMBOLS.items()}
_PATTERN = re.compile("|".join(re.escape(symbol) for symbol, _ in SYMBOLS.values()))
_KEYS = {symbol: "global_" + key for key, (symbol, _) in SYMBOLS.items()}
resolve_icon = lambda slot: None


def decorate_html(text):
    protected = 0
    result = []
    for part in re.split(r"(<[^>]*>)", text):
        if part.startswith("<"):
            if re.match(r"<(?:tg-emoji|code|pre)\b", part):
                protected += 1
            elif re.match(r"</(?:tg-emoji|code|pre)\s*>", part):
                protected = max(0, protected - 1)
            result.append(part)
        elif protected:
            result.append(part)
        else:
            def replace(match):
                symbol = match.group()
                emoji_id = resolve_icon(_KEYS[symbol])
                return f'<tg-emoji emoji-id="{emoji_id}">{symbol}</tg-emoji>' if emoji_id else symbol
            result.append(_PATTERN.sub(replace, part))
    return "".join(result)


def rebuild_markup(markup, data):
    if isinstance(markup, InlineKeyboardMarkup):
        return InlineKeyboardMarkup([[InlineKeyboardButton.de_json(button, None) for button in row]
                                    for row in data["inline_keyboard"]])
    return ReplyKeyboardMarkup([[KeyboardButton.de_json(button, None) for button in row]
                                for row in data["keyboard"]],
                               **{key: value for key, value in data.items() if key != "keyboard"})


def decorate_markup(markup):
    if not isinstance(markup, (InlineKeyboardMarkup, ReplyKeyboardMarkup)):
        return markup
    data = markup.to_dict()
    rows = data.get("inline_keyboard", data.get("keyboard"))
    for row in rows:
        for button in row:
            if button.get("icon_custom_emoji_id"):
                continue
            match = _PATTERN.match(button["text"])
            if match and (emoji_id := resolve_icon(_KEYS[match.group()])):
                button["icon_custom_emoji_id"] = emoji_id
                button["text"] = button["text"][match.end():].lstrip() or match.group()
    return rebuild_markup(markup, data)


def decorate_data(data):
    data = dict(data)
    for field, entity_field in (("text", "entities"), ("caption", "caption_entities")):
        if isinstance(data.get(field), str) and not data.get(entity_field):
            mode = str(data.get("parse_mode") or "").lower()
            if mode in ("", "html"):
                original = data[field]
                decorated = decorate_html(original if mode else html.escape(original))
                if '<tg-emoji ' in decorated and decorated != original:
                    data[field] = decorated
                    data["parse_mode"] = "HTML"
    if data.get("reply_markup"):
        data["reply_markup"] = decorate_markup(data["reply_markup"])
    return data


def without_custom_icons(data):
    data = dict(data)
    for field in ("text", "caption"):
        if isinstance(data.get(field), str):
            data[field] = re.sub(r'<tg-emoji[^>]*>(.*?)</tg-emoji>', r'\1', data[field])
    markup = data.get("reply_markup")
    if isinstance(markup, (InlineKeyboardMarkup, ReplyKeyboardMarkup)):
        raw = markup.to_dict()
        for row in raw.get("inline_keyboard", raw.get("keyboard")):
            for button in row:
                button.pop("icon_custom_emoji_id", None)
        data["reply_markup"] = rebuild_markup(markup, raw)
    return data
