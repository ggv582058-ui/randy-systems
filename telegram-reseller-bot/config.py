from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _admin_ids(value: str) -> frozenset[int]:
    ids: set[int] = set()
    for raw in value.split(","):
        raw = raw.strip()
        if raw:
            ids.add(int(raw))
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_bot_token: str
    admin_ids: frozenset[int]
    database_path: Path
    store_name: str
    support_username: str
    key_api_url: str
    key_api_token: str
    zentry_base_url: str
    zentry_seller_key: str
    zentry_seller_secret: str
    zentry_key_prefix: str


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    admin_token = os.getenv("ADMIN_BOT_TOKEN", "").strip()
    admins = _admin_ids(os.getenv("ADMIN_IDS", ""))
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN")
    if not admin_token:
        raise RuntimeError("Falta ADMIN_BOT_TOKEN")
    if not admins:
        raise RuntimeError("Falta ADMIN_IDS (IDs separados por comas)")

    db_path = Path(os.getenv("DATABASE_PATH", "data/reseller.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        bot_token=token,
        admin_bot_token=admin_token,
        admin_ids=admins,
        database_path=db_path,
        store_name=os.getenv("STORE_NAME", "RANDY RESELLER SYSTEMS").strip(),
        support_username=os.getenv("SUPPORT_USERNAME", "@Randy_zt").strip(),
        key_api_url=os.getenv("KEY_API_URL", "").strip(),
        key_api_token=os.getenv("KEY_API_TOKEN", "").strip(),
        zentry_base_url=os.getenv("ZENTRY_BASE_URL", "https://api.zentryauth.com").strip().rstrip("/"),
        zentry_seller_key=os.getenv("ZENTRY_SELLER_KEY", "").strip(),
        zentry_seller_secret=os.getenv("ZENTRY_SELLER_SECRET", "").strip(),
        zentry_key_prefix=os.getenv("ZENTRY_KEY_PREFIX", "RANDY").strip() or "RANDY",
    )
