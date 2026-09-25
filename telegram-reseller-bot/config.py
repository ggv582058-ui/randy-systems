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


def _compact_secret(value: str) -> str:
    """Remove accidental line wrapping when secrets are pasted from mobile."""
    return "".join(value.split())


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_bot_token: str
    admin_ids: frozenset[int]
    database_path: Path
    store_name: str
    support_username: str
    zelle_number: str
    zelle_holder: str
    key_api_url: str
    key_api_token: str
    zentry_base_url: str
    zentry_seller_key: str
    zentry_seller_secret: str
    zentry_key_prefix: str
    chungchi_base_url: str
    chungchi_api_key: str
    chungchi_plan_id: int
    chungchi_sell_price_cents: int
    chungchi_webhook_secret: str
    certificate_link_ttl_hours: int


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
    # Render starts the app from telegram-reseller-bot/, while the persistent
    # disk is mounted at /opt/render/project/src/data.  Resolve relative DB
    # paths from the project root so deployments never fall back to ephemeral
    # storage inside the source directory.
    if os.getenv("RENDER") and not db_path.is_absolute():
        db_path = Path("/opt/render/project/src") / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        bot_token=token,
        admin_bot_token=admin_token,
        admin_ids=admins,
        database_path=db_path,
        store_name=os.getenv("STORE_NAME", "RANDY RESELLER SYSTEMS").strip(),
        support_username=os.getenv("SUPPORT_USERNAME", "@Randy_zt").strip(),
        zelle_number=os.getenv("ZELLE_NUMBER", "").strip(),
        zelle_holder=os.getenv("ZELLE_HOLDER", "").strip(),
        key_api_url=os.getenv("KEY_API_URL", "").strip(),
        key_api_token=os.getenv("KEY_API_TOKEN", "").strip(),
        zentry_base_url=os.getenv("ZENTRY_BASE_URL", "https://api.zentryauth.com").strip().rstrip("/"),
        zentry_seller_key=_compact_secret(os.getenv("ZENTRY_SELLER_KEY", "")),
        zentry_seller_secret=_compact_secret(os.getenv("ZENTRY_SELLER_SECRET", "")),
        zentry_key_prefix=os.getenv("ZENTRY_KEY_PREFIX", "RANDY").strip() or "RANDY",
        chungchi_base_url=os.getenv("CHUNGCHI_BASE_URL", "https://chungchi.store").strip().rstrip("/"),
        chungchi_api_key=_compact_secret(os.getenv("CHUNGCHI_API_KEY", "")),
        chungchi_plan_id=int(os.getenv("CHUNGCHI_PLAN_ID", "23")),
        chungchi_sell_price_cents=int(os.getenv("CHUNGCHI_SELL_PRICE_CENTS", "350")),
        chungchi_webhook_secret=_compact_secret(os.getenv("CHUNGCHI_WEBHOOK_SECRET", "")),
        certificate_link_ttl_hours=max(1, int(os.getenv("CERTIFICATE_LINK_TTL_HOURS", "24"))),
    )
