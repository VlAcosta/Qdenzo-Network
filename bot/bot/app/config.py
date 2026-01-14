# -*- coding: utf-8 -*-

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # Telegram
    bot_token: str = Field(..., alias='BOT_TOKEN')
    admin_ids: str = Field('', alias='ADMIN_IDS')
    brand_name: str = Field('Qdenzo Network', alias='BRAND_NAME')
    support_username: str = Field('@qdenzo_support', alias='SUPPORT_USERNAME')
    lang: str = Field('ru', alias='LANG')

    start_photo: str | None = Field(None, alias='START_PHOTO')

    # DB
    database_url: str = Field(..., alias='DATABASE_URL')
    redis_url: str | None = Field('redis://redis:6379/0', alias='REDIS_URL')

    # Marzban
    marzban_base_url: str = Field(..., alias='MARZBAN_BASE_URL')
    marzban_username: str = Field(..., alias='MARZBAN_USERNAME')
    marzban_password: str = Field(..., alias='MARZBAN_PASSWORD')
    marzban_verify_ssl: bool = Field(True, alias='MARZBAN_VERIFY_SSL')
    marzban_api_prefix: str = Field('/api', alias='MARZBAN_API_PREFIX')
    marzban_inbound_tag: str = Field('vless-reality', alias='VLESS_INBOUND_TAG')
    marzban_proxy_type: str = Field('vless', alias='PROXY_TYPE')

    # How to provide config links to users:
    # - auto: prefer Marzban user 'links', fallback to subscription_url, fallback to manual builder
    # - link: use first link from Marzban user
    # - subscription: use Marzban user subscription_url
    marzban_link_mode: Literal['auto', 'link', 'subscription'] = Field('auto', alias='MARZBAN_LINK_MODE')

    # If Marzban doesn't return ready links, we can build a Reality URI ourselves
    reality_host: str | None = Field(None, alias='REALITY_HOST')
    reality_port: int = Field(443, alias='REALITY_PORT')
    reality_sni: str = Field('www.cloudflare.com', alias='REALITY_SNI')
    reality_public_key: str | None = Field(None, alias='REALITY_PUBLIC_KEY')
    reality_short_id: str | None = Field(None, alias='REALITY_SHORT_ID')
    reality_fp: str = Field('chrome', alias='REALITY_FP')
    reality_flow: str = Field('xtls-rprx-vision', alias='REALITY_FLOW')

    # Traffic limits (GB). You can tune this in .env without touching code.
    traffic_limit_trial_gb: int = Field(20, alias='TRAFFIC_LIMIT_TRIAL_GB')
    traffic_limit_start_gb: int = Field(500, alias='TRAFFIC_LIMIT_START_GB')
    traffic_limit_pro_gb: int = Field(1000, alias='TRAFFIC_LIMIT_PRO_GB')
    traffic_limit_family_gb: int = Field(2000, alias='TRAFFIC_LIMIT_FAMILY_GB')


    # Payments
    payment_manual_enabled: bool = Field(True, alias='PAYMENT_MANUAL_ENABLED')
    manual_payment_text: str = Field(
        'Оплата в тестовом режиме.\n\nНапишите в поддержку и приложите чек/скрин оплаты.',
        alias='MANUAL_PAYMENT_TEXT'
    )

    public_base_url: str | None = Field(None, alias='PUBLIC_BASE_URL')

    webhook_host: str = Field('0.0.0.0', alias='WEBHOOK_HOST')
    webhook_port: int = Field(8080, alias='WEBHOOK_PORT')

    # External payment links (optional)
    yookassa_pay_url: str | None = Field(None, alias='YOOKASSA_PAY_URL')
    crypto_pay_url: str | None = Field(None, alias='CRYPTO_PAY_URL')

    # YooKassa
    yookassa_shop_id: str | None = Field(None, alias='YOOKASSA_SHOP_ID')
    yookassa_secret_key: str | None = Field(None, alias='YOOKASSA_SECRET_KEY')
    yookassa_return_url: str | None = Field(None, alias='YOOKASSA_RETURN_URL')
    yookassa_webhook_path_secret: str | None = Field(None, alias='YOOKASSA_WEBHOOK_PATH_SECRET')

    # CryptoPay
    cryptopay_token: str | None = Field(None, alias='CRYPTOPAY_TOKEN')
    cryptopay_asset: str = Field('TON', alias='CRYPTOPAY_ASSET')
    cryptopay_webhook_path_secret: str | None = Field(None, alias='CRYPTOPAY_WEBHOOK_PATH_SECRET')
    cryptopay_webhook_secret: str | None = Field(None, alias='CRYPTOPAY_WEBHOOK_SECRET')
    cryptopay_invoice_expires_in: int | None = Field(None, alias='CRYPTOPAY_INVOICE_EXPIRES_IN')

    # YooKassa API (optional)
    yookassa_shop_id: str | None = Field(None, alias='YOOKASSA_SHOP_ID')
    yookassa_secret_key: str | None = Field(None, alias='YOOKASSA_SECRET_KEY')
    yookassa_return_url: str | None = Field(None, alias='YOOKASSA_RETURN_URL')
    yookassa_webhook_path_secret: str | None = Field(None, alias='YOOKASSA_WEBHOOK_PATH_SECRET')


    # Telegram payments (provider token) - optional
    tg_provider_token: str | None = Field(None, alias='TG_PROVIDER_TOKEN')

    # Telegram Stars (XTR) - optional
    tg_stars_enabled: bool = Field(False, alias='TG_STARS_ENABLED')

    # Referral system
    referral_window_days: int = Field(30, alias='REFERRAL_WINDOW_DAYS')
    referral_cap_days: int = Field(15, alias='REFERRAL_CAP_DAYS')

    # Trial
    trial_hours: int = Field(48, alias='TRIAL_HOURS')

    # Housekeeping
    log_level: str = Field('INFO', alias='LOG_LEVEL')

    @property
    def start_photo_path(self) -> Path | None:
        if not self.start_photo:
            return None
        p = Path(self.start_photo)
        if not p.is_absolute():
            p = BASE_DIR / self.start_photo
        return p

    @property
    def admin_id_list(self) -> List[int]:
        ids: List[int] = []
        for part in (self.admin_ids or '').replace(';', ',').split(','):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                continue
        return ids
    
    payment_stars_enabled: bool = Field(True, alias="PAYMENT_STARS_ENABLED")
    stars_per_rub: float = Field(1.0, alias="STARS_PER_RUB")

    # Happ / Happ-Proxy
    happ_url: str | None = Field(None, alias="HAPP_URL")
    happ_redirect_base: str | None = Field(None, alias="HAPP_REDIRECT_BASE")
    happ_proxy_api_base: str | None = Field(None, alias="HAPP_PROXY_API_BASE")
    happ_proxy_provider_code: str | None = Field(None, alias="HAPP_PROXY_PROVIDER_CODE")
    happ_proxy_auth_key: str | None = Field(None, alias="HAPP_PROXY_AUTH_KEY")

    # Traffic collection
    traffic_collect_enabled: bool = Field(False, alias="TRAFFIC_COLLECT_ENABLED")
    traffic_collect_interval_seconds: int = Field(3600, alias="TRAFFIC_COLLECT_INTERVAL_SECONDS")

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
