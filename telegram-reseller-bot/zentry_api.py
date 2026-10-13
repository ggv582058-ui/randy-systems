from __future__ import annotations

import json
import re
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
        self.base_url = base_url.strip().rstrip("/")
        # The application panel publishes the Seller API separately from the
        # client activation API. Migrate the old default without changing keys.
        if self.base_url in ("https://api.zentryauth.com", "https://api.zentryauth.com/v1",
                             "https://api.zentryauth.com/seller/v1", "https://zentryauth.com",
                             "https://zentryauth.com/seller/v1"):
            self.base_url = "https://zentryauth.com/api/seller/v1"
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
        # Accept the full Seller base copied from the panel as well as an
        # origin/API base; never duplicate /seller/v1 in a request URL.
        suffix = path[len("/seller/v1"):] if self.base_url.endswith("/seller/v1") and path.startswith("/seller/v1/") else path
        request = urllib.request.Request(
            f"{self.base_url}{suffix}",
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
        if type(duration_days) is not int or not 1 <= duration_days <= 3650:
            raise ZentryError("Duración inválida: indica días enteros entre 1 y 3650")
        result = self._post(
            "/seller/v1/licenses/create",
            {"duration_type": "days", "duration_value": duration_days, "key_prefix": prefix},
        )
        data = result.get("data")
        key = data.strip() if isinstance(data, str) and data.strip() else self._find_license_key(result)
        if not key:
            raise ZentryError("ZentryAuth no devolvió la licencia creada")
        self.verify_license_duration(key, duration_days)
        return key

    @classmethod
    def _duration_days(cls, payload: Any) -> int | None:
        """Read total license duration, never the remaining time or local receipt."""
        if not isinstance(payload, dict):
            return None
        values: list[int] = []
        for field in ("lifetime", "is_lifetime", "isLifetime"):
            if payload.get(field) is True or str(payload.get(field, "")).lower() in ("true", "1"):
                values.append(0)
        for field in ("duration_days", "durationDays"):
            if field in payload:
                value = payload[field]
                if type(value) is int and value > 0:
                    values.append(value)
                elif isinstance(value, str) and value.isdigit() and int(value) > 0:
                    values.append(int(value))
                else:
                    raise ZentryError("La API devolvió una duración inválida; operación detenida")
        for field in ("duration_seconds", "durationSeconds"):
            if field in payload:
                value = payload[field]
                if type(value) is not int or value <= 0 or value % 86400:
                    raise ZentryError("La API devolvió una duración inválida; operación detenida")
                values.append(value // 86400)
        unit = str(payload.get("duration_type", payload.get("durationType", ""))).lower()
        if unit in ("lifetime", "forever", "permanent"):
            values.append(0)
        elif unit:
            amount = payload.get("duration_value", payload.get("durationValue"))
            if isinstance(amount, str) and amount.isdigit():
                amount = int(amount)
            if type(amount) is int and amount > 0 and unit in ("day", "days", "week", "weeks"):
                values.append(amount * (7 if unit.startswith("week") else 1))
        duration = payload.get("duration")
        if isinstance(duration, str):
            duration = duration.strip().lower()
            if duration in ("lifetime", "forever", "permanent", "unlimited"):
                values.append(0)
            else:
                match = re.fullmatch(r"(\d+)\s*(days?|weeks?)", duration)
                if match:
                    values.append(int(match[1]) * (7 if match[2].startswith("week") else 1))
                elif duration:
                    # Month/year labels do not prove an exact number of days.
                    raise ZentryError("La API no confirma la duración exacta en días; operación detenida")
        for field in ("data", "result", "license"):
            if isinstance(payload.get(field), dict):
                nested = cls._duration_days(payload[field])
                if nested is not None:
                    values.append(nested)
        if not values:
            return None
        if len(set(values)) != 1:
            raise ZentryError("La API devolvió duraciones contradictorias; operación detenida")
        return values[0]

    def verify_license_duration(self, license_key: str, expected_days: int) -> None:
        if type(expected_days) is not int or not 1 <= expected_days <= 3650:
            raise ZentryError("Duración del producto inválida; operación detenida")
        result = self.license_info(license_key)
        returned_key = self._find_license_key(result)
        if returned_key and returned_key != license_key:
            raise ZentryError("La API respondió con otra licencia; operación detenida")
        actual_days = self._duration_days(result)
        if actual_days is None:
            raise ZentryError("No se pudo verificar la duración real de la key; operación detenida")
        if actual_days != expected_days:
            actual = "lifetime" if actual_days == 0 else f"{actual_days} días"
            raise ZentryError(f"Duración incorrecta: producto de {expected_days} días, API indica {actual}. No se entregó la key")

    @classmethod
    def _find_license_key(cls, payload: Any) -> str | None:
        """Accept the response shapes used by different Zentry API versions."""
        if isinstance(payload, dict):
            for field in ("license_key", "licenseKey", "key", "license"):
                value = payload.get(field)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            # Prefer common response containers, then inspect any remaining
            # nested objects. Exact field names above prevent returning a
            # message, seller credential, or unrelated ID.
            for field in ("data", "result", "license"):
                if field in payload:
                    found = cls._find_license_key(payload[field])
                    if found:
                        return found
            for value in payload.values():
                if isinstance(value, (dict, list)):
                    found = cls._find_license_key(value)
                    if found:
                        return found
        elif isinstance(payload, list):
            for value in payload:
                found = cls._find_license_key(value)
                if found:
                    return found
        return None

    def reset_hwid(self, license_key: str) -> dict[str, Any]:
        return self._post("/seller/v1/licenses/reset", {"license_key": license_key})

    def ban_license(self, license_key: str) -> dict[str, Any]:
        return self._post("/seller/v1/licenses/ban", {"license_key": license_key})

    def unban_license(self, license_key: str) -> dict[str, Any]:
        return self._post("/seller/v1/licenses/unban", {"license_key": license_key})

    def license_info(self, license_key: str) -> dict[str, Any]:
        return self._post("/seller/v1/licenses/info", {"license_key": license_key})
