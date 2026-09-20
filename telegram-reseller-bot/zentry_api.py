from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable


class ZentryError(RuntimeError):
    """A safe, user-facing ZentryAuth API error."""


class ZentryClient:
    def __init__(
        self,
        base_url: str,
        seller_key: str,
        seller_secret: str,
        timeout: int = 20,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # Mobile copy/paste can insert newlines into long credentials. Seller
        # credentials never contain whitespace, so normalize them before they
        # become HTTP headers.
        self.seller_key = "".join(seller_key.split())
        self.seller_secret = "".join(seller_secret.split())
        self.timeout = timeout
        self._opener = opener

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.seller_key and self.seller_secret)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise ZentryError("Faltan ZENTRY_SELLER_KEY y ZENTRY_SELLER_SECRET en Render")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Seller-Key": self.seller_key,
                "X-Seller-Secret": self.seller_secret,
                "User-Agent": "RandyResellerBot/1.0",
            },
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            message = self._error_message(raw) or f"ZentryAuth respondió HTTP {exc.code}"
            raise ZentryError(message) from None
        except urllib.error.URLError:
            raise ZentryError("No se pudo conectar con ZentryAuth") from None
        except TimeoutError:
            raise ZentryError("ZentryAuth tardó demasiado en responder") from None
        except (ValueError, UnicodeError):
            # Never propagate urllib's raw invalid-header error because it can
            # include the credential value in the traceback.
            raise ZentryError("Las credenciales Seller contienen caracteres inválidos") from None

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            raise ZentryError("ZentryAuth devolvió una respuesta inválida") from None
        if not isinstance(result, dict):
            raise ZentryError("ZentryAuth devolvió una respuesta inválida")
        if result.get("success") is False:
            raise ZentryError(self._error_message(raw) or "ZentryAuth rechazó la operación")
        return result

    @staticmethod
    def _error_message(raw: str) -> str:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        value = payload.get("message") or payload.get("error") or payload.get("code")
        return str(value)[:300] if value else ""

    def create_license(self, duration_days: int, prefix: str = "RANDY") -> str:
        result = self._post(
            "/seller/v1/licenses/create",
            {"duration_type": "days", "duration_value": duration_days, "key_prefix": prefix},
        )
        data = result.get("data") or {}
        key = data.get("license_key") if isinstance(data, dict) else None
        if not key:
            raise ZentryError("ZentryAuth no devolvió la licencia creada")
        return str(key)

    def reset_hwid(self, license_key: str) -> dict[str, Any]:
        return self._post("/seller/v1/licenses/reset", {"license_key": license_key})

    def ban_license(self, license_key: str) -> dict[str, Any]:
        return self._post("/seller/v1/licenses/ban", {"license_key": license_key})

    def unban_license(self, license_key: str) -> dict[str, Any]:
        return self._post("/seller/v1/licenses/unban", {"license_key": license_key})

    def license_info(self, license_key: str) -> dict[str, Any]:
        return self._post("/seller/v1/licenses/info", {"license_key": license_key})
