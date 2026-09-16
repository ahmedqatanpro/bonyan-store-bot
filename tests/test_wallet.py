import pytest

from app.db import StoreDB


@pytest.mark.asyncio
async def test_wallet_credit_and_atomic_debit(tmp_path):
    db = StoreDB(str(tmp_path / "store.db"))
    await db.init()
    await db.upsert_user(10, "customer", "Customer")
    assert await db.credit_wallet(10, 150, "payment:1") == 150
    assert await db.debit_wallet(10, 50, "order:1") == 100
    assert await db.wallet_balance_cents(10) == 100
    with pytest.raises(ValueError, match="INSUFFICIENT_BALANCE"):
        await db.debit_wallet(10, 101, "order:2")
    assert await db.wallet_balance_cents(10) == 100


@pytest.mark.asyncio
async def test_sale_price_is_separate_from_provider_price(tmp_path):
    db = StoreDB(str(tmp_path / "store.db"))
    await db.init()
    await db.replace_products([{"id": 1, "name": "Service", "price_usd": 1.0, "delivery_type": "activation"}])
    assert await db.set_sale_price(1, 1.5)
    row = await db.product(1)
    assert row["price_usd"] == 1.0
    assert row["sale_price_usd"] == 1.5
