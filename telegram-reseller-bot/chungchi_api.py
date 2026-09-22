from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable


class ChungChiError(RuntimeError):
    """Safe, user-facing error returned by the certificate provider."""

    def __init__(self, message: str, status: int | None = None, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class ChungChiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 25,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = "".join(api_key.split())
        self.timeout = timeout
        self._opener = opener

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise ChungChiError("Falta CHUNGCHI_API_KEY en Render")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "Accept": "application/json",
                "Accept-Language": "en",
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "RandyResellerBot/2.0",
            },
            method=method,
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            message, code = self._error(raw)
            if not message:
                message = {
                    401: "API Key de ChungChi inválida",
                    402: "Saldo insuficiente en ChungChi",
                    403: "ChungChi rechazó la solicitud",
                    404: "Pedido o plan no encontrado",
                    422: "Datos del certificado inválidos",
                    429: "ChungChi está recibiendo demasiadas solicitudes",
                }.get(exc.code, f"ChungChi respondió HTTP {exc.code}")
            raise ChungChiError(message, exc.code, code) from None
        except urllib.error.URLError:
            raise ChungChiError("No se pudo conectar con ChungChi") from None
        except TimeoutError:
            raise ChungChiError("ChungChi tardó demasiado en responder") from None
        except (ValueError, UnicodeError):
            raise ChungChiError("La API Key de ChungChi contiene caracteres inválidos") from None

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            raise ChungChiError("ChungChi devolvió una respuesta inválida") from None
        if not isinstance(result, dict):
            raise ChungChiError("ChungChi devolvió una respuesta inválida")
        if result.get("error"):
            message, code = self._error(raw)
            raise ChungChiError(message or "ChungChi rechazó la operación", code=code)
        return result

    @staticmethod
    def _error(raw: str) -> tuple[str, str]:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return "", ""
        error = payload.get("error", payload) if isinstance(payload, dict) else {}
        if not isinstance(error, dict):
            return str(error)[:300], ""
        return str(error.get("message") or "")[:300], str(error.get("code") or "")[:100]

    @staticmethod
    def _data(result: dict[str, Any], key: str | None = None) -> Any:
        data = result.get("data", result)
        if key and isinstance(data, dict):
            return data.get(key, data)
        return data

    def plans(self) -> list[dict[str, Any]]:
        data = self._data(self._request("GET", "/api/v1/plans"), "plans")
        return data if isinstance(data, list) else []

    def balance(self) -> dict[str, Any]:
        data = self._data(self._request("GET", "/api/v1/balance"))
        return data if isinstance(data, dict) else {}

    def create_order(self, plan_id: int, udid: str, device: str, p12_password: str) -> dict[str, Any]:
        result = self._request("POST", "/api/v1/orders", {
            "plan_id": plan_id,
            "udid": udid,
            "device": device,
            "p12_password": p12_password,
        })
        order = self._data(result, "order")
        if not isinstance(order, dict) or not order.get("order_code"):
            raise ChungChiError("ChungChi no devolvió el código del pedido")
        return order

    def order(self, order_code: str) -> dict[str, Any]:
        result = self._request("GET", f"/api/v1/orders/{order_code}")
        order = self._data(result, "order")
        if not isinstance(order, dict):
            raise ChungChiError("ChungChi no devolvió los datos del pedido")
        return order

    def orders_by_udid(self, udid: str) -> list[dict[str, Any]]:
        result = self._request("GET", f"/api/v1/devices/{udid}/orders")
        data = self._data(result, "orders")
        return data if isinstance(data, list) else []

    def configure_webhook(self, url: str) -> dict[str, Any]:
        data = self._data(self._request("PUT", "/api/v1/webhook", {"url": url}))
        return data if isinstance(data, dict) else {}

    def download(self, url: str, max_bytes: int = 20 * 1024 * 1024) -> bytes:
        if not url.startswith(f"{self.base_url}/"):
            raise ChungChiError("ChungChi devolvió un enlace de descarga no válido")
        request = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "RandyResellerBot/2.0",
        })
        try:
            with self._opener(request, timeout=self.timeout) as response:
                data = response.read(max_bytes + 1)
        except (urllib.error.URLError, TimeoutError):
            raise ChungChiError("No se pudo descargar el certificado") from None
        if len(data) > max_bytes:
            raise ChungChiError("El paquete del certificado supera 20 MB")
        return data
