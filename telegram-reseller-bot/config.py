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
    admin_ids: frozenset[int]
    database_path: Path
    store_name: str
    support_username: str


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    admins = _admin_ids(os.getenv("ADMIN_IDS", ""))
    if not token:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN")
    if not admins:
        raise RuntimeError("Falta ADMIN_IDS (IDs separados por comas)")

    db_path = Path(os.getenv("DATABASE_PATH", "data/reseller.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        bot_token=token,
        admin_ids=admins,
        database_path=db_path,
        store_name=os.getenv("STORE_NAME", "RANDY RESELLER SYSTEMS").strip(),
        support_username=os.getenv("SUPPORT_USERNAME", "@Randy_zt").strip(),
    )
