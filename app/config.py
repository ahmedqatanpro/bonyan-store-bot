from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    vente_reseller_key: str
    vente_api_base: str = "https://ventetelegrambotrailway-production.up.railway.app"
    database_path: str = "./data/store.db"
    admin_ids: str = ""
    catalog_lang: str = "ar"
    poll_interval_seconds: int = 15
    enable_test_purchase: bool = False
    enable_wallet_purchase: bool = False
    payment_provider_token: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def admin_id_set(self) -> set[int]:
        return {int(value.strip()) for value in self.admin_ids.split(",") if value.strip()}

    @property
    def api_base(self) -> str:
        return self.vente_api_base.rstrip("/")
