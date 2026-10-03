"""Consistent Developer typography for Telegram's visible bot text.

Telegram does not expose a custom font. Unicode mathematical sans bold italic
characters provide the selected style while keeping credentials and links plain.
"""

from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ExtBot


_TOKEN = re.compile(
    r"(https?://\S+|www\.\S+|@[\w]+|/[A-Za-z][\w-]*|"
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|&(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z]+);|"
    r"\b(?=[A-Za-z0-9-]{8,}\b)(?=[A-Za-z0-9-]*\d)[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b)"
)
_HTML_PART = re.compile(r"(<[^>]+>)")
_HTML_NAME = re.compile(r"</?\s*([A-Za-z][\w-]*)")


def _letters(value: str) -> str:
    output = []
    for char in value:
        number = ord(char)
        if 65 <= number <= 90:
            output.append(chr(0x1D63C + number - 65))
        elif 97 <= number <= 122:
            output.append(chr(0x1D656 + number - 97))
        else:
            output.append(char)
    return "".join(output)


def developer_text(value: str) -> str:
    """Style prose, leaving HTML, code, URLs, handles and license keys intact."""
    if not isinstance(value, str) or not value:
        return value
    in_code = 0
    chunks = []
    for part in _HTML_PART.split(value):
        if part.startswith("<") and part.endswith(">"):
            match = _HTML_NAME.match(part)
            if match and match.group(1).lower() in ("code", "pre"):
                in_code += -1 if part.startswith("</") else 1
            chunks.append(part)
        elif in_code:
            chunks.append(part)
        else:
            chunks.append("".join(token if _TOKEN.fullmatch(token) else _letters(token)
                                  for token in _TOKEN.split(part) if token))
    return "".join(chunks)


def _within_limit(value: str, original: str, limit: int) -> str:
    return value if len(value.encode("utf-16-le")) // 2 <= limit else original


_KEYBOARD_FIELDS = ("request_contact", "request_location", "request_poll", "web_app", "request_chat",
                    "request_users", "style", "icon_custom_emoji_id", "request_managed_bot", "api_kwargs")
_INLINE_FIELDS = ("url", "callback_data", "switch_inline_query", "switch_inline_query_current_chat",
                  "callback_game", "pay", "login_url", "web_app", "switch_inline_query_chosen_chat",
                  "copy_text", "style", "icon_custom_emoji_id", "api_kwargs")


def _button_fields(button, names):
    return {name: value for name in names if (value := getattr(button, name, None)) is not None}


def style_markup(markup):
    if isinstance(markup, ReplyKeyboardMarkup):
        rows = []
        for row in markup.keyboard:
            buttons = []
            for button in row:
                original = button.text
                text = _within_limit(developer_text(original), original, 64)
                buttons.append(KeyboardButton(text, **_button_fields(button, _KEYBOARD_FIELDS)))
            rows.append(buttons)
        options = {key: value for key, value in markup.to_dict().items() if key != "keyboard"}
        return ReplyKeyboardMarkup(rows, **options)
    if isinstance(markup, InlineKeyboardMarkup):
        rows = []
        for row in markup.inline_keyboard:
            buttons = []
            for button in row:
                original = button.text
                text = _within_limit(developer_text(original), original, 64)
                buttons.append(InlineKeyboardButton(text, **_button_fields(button, _INLINE_FIELDS)))
            rows.append(buttons)
        return InlineKeyboardMarkup(rows)
    return markup


class DeveloperBot(ExtBot):
    async def _post(self, endpoint, data=None, **kwargs):
        if data and endpoint.lower() in {
            "sendmessage", "editmessagetext", "sendphoto", "sendvideo", "sendanimation",
            "senddocument", "sendaudio", "sendvoice", "editmessagecaption",
            "answercallbackquery", "copymessage", "editmessagereplymarkup", "sendsticker",
        }:
            data = dict(data)
            for field, limit in (("text", 200 if endpoint.lower() == "answercallbackquery" else 4096),
                                 ("caption", 1024)):
                if isinstance(data.get(field), str):
                    original = data[field]
                    data[field] = _within_limit(developer_text(original), original, limit)
            if data.get("reply_markup"):
                data["reply_markup"] = style_markup(data["reply_markup"])
        return await super()._post(endpoint, data, **kwargs)
