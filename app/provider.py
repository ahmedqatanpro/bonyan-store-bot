from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


class ProviderError(RuntimeError):
    def __init__(self, message: str, code: str = "PROVIDER_ERROR", retry_after: float | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


@dataclass(slots=True)
class ProviderClient:
    base_url: str
    api_key: str
    timeout: float = 20.0
    _client: httpx.AsyncClient = field(init=False, repr=False)
    _lock: asyncio.Lock = field(init=False, repr=False)
    _next_allowed: float = field(init=False, repr=False, default=0.0)
    etag: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout,
            headers={"X-Reseller-Key": self.api_key, "Accept": "application/json"},
        )
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0
        self.etag = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any] | None:
        async with self._lock:
            delay = self._next_allowed - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            response = await self._client.request(method, path, **kwargs)
            if response.status_code == 429:
                retry = float(response.headers.get("Retry-After", "5"))
                self._next_allowed = time.monotonic() + retry
                raise ProviderError("تم تجاوز حد الطلبات من المزود", "RATE_LIMITED", retry)
            if response.status_code >= 500:
                raise ProviderError("المزود غير متاح مؤقتًا", "PROVIDER_UNAVAILABLE", 5)
            if response.status_code >= 400:
                try:
                    body = response.json()
                    message = body.get("message", "فشل طلب المزود")
                    code = body.get("code", "PROVIDER_REJECTED")
                except ValueError:
                    message, code = "فشل طلب المزود", "PROVIDER_REJECTED"
                raise ProviderError(message, code)
            if response.status_code == 304:
                return None
            return response.json()

    async def me(self) -> dict[str, Any]:
        return await self._request("GET", "/api/reseller/me") or {}

    async def products(self, lang: str = "ar") -> tuple[list[dict[str, Any]], str | None]:
        headers = {"If-None-Match": self.etag} if self.etag else {}
        response = await self._client.get("/api/reseller/products", params={"lang": lang}, headers=headers)
        if response.status_code == 304:
            return [], self.etag
        if response.status_code >= 400:
            raise ProviderError("تعذر تحميل الخدمات", "CATALOG_UNAVAILABLE")
        self.etag = response.headers.get("ETag", self.etag)
        return response.json().get("products", []), self.etag

    async def quote(self, product_id: int, quantity: int = 1) -> dict[str, Any]:
        return await self._request("POST", "/api/reseller/quote", json={"product_id": product_id, "quantity": quantity}) or {}

    async def create_order(self, product_id: int, quantity: int, customer_reference: str, idempotency_key: str, activation_identifier: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "product_id": product_id,
            "quantity": quantity,
            "customer_reference": customer_reference[:120],
            "idempotency_key": idempotency_key[:120],
        }
        if activation_identifier:
            payload["activation_identifier"] = activation_identifier[:500]
        return await self._request("POST", "/api/reseller/orders", json=payload) or {}

    async def order(self, order_id: int) -> dict[str, Any]:
        return await self._request("GET", f"/api/reseller/orders/{order_id}") or {}

    async def submit_activation(self, order_id: int, activation_identifier: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/reseller/orders/{order_id}/activation-identifier", json={"activation_identifier": activation_identifier[:500]}) or {}
