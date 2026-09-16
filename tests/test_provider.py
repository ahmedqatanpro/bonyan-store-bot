import json

import httpx
import pytest

from app.provider import ProviderClient, ProviderError


@pytest.mark.asyncio
async def test_create_order_sends_idempotency_key(monkeypatch):
    client = ProviderClient("https://example.test", "secret-not-used")
    requests = []

    async def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, json={"success": True, "order": {"id": 7, "status": "COMPLETED"}})

    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test", headers={"X-Reseller-Key": "secret-not-used"})
    result = await client.create_order(12, 1, "telegram_user_1", "idem-1")
    assert result["order"]["id"] == 7
    assert requests[0].headers["X-Reseller-Key"] == "secret-not-used"
    assert json.loads(requests[0].content)["idempotency_key"] == "idem-1"
    await client.close()


@pytest.mark.asyncio
async def test_rate_limit_error_is_explicit():
    client = ProviderClient("https://example.test", "key")

    async def handler(request):
        return httpx.Response(429, headers={"Retry-After": "2"}, json={"code": "RATE_LIMITED", "message": "slow down"})

    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test")
    with pytest.raises(ProviderError) as error:
        await client.me()
    assert error.value.code == "RATE_LIMITED"
    assert error.value.retry_after == 2
    await client.close()
