# -*- coding: utf-8 -*-

from __future__ import annotations

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def run_migrations(engine: AsyncEngine) -> None:
    """Idempotent migrations (no Alembic).

    Why:
      - `Base.metadata.create_all()` does NOT add new columns to existing tables.
      - In early-stage projects we can keep it simple with a few `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

    IMPORTANT: If you already have real production data, consider switching to Alembic.
    """

    stmts: list[str] = [
        # ---- users ----
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS inviter_id INTEGER NULL;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(32) NULL;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS locale VARCHAR(8) NULL;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_code VARCHAR(16) NOT NULL DEFAULT 'smart';",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_updated_at TIMESTAMPTZ NULL;",

        # ---- subscriptions ----
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS plan_code VARCHAR(16) NOT NULL DEFAULT 'trial';",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS devices_limit INTEGER NOT NULL DEFAULT 1;",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS trial_used BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ NULL;",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL;",

        # ---- devices ----
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS slot INTEGER NOT NULL DEFAULT 1;",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS label VARCHAR(64) NULL;",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_type VARCHAR(16) NOT NULL DEFAULT 'phone';",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'active';",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS profile_code VARCHAR(16) NOT NULL DEFAULT 'smart';",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS marzban_username VARCHAR(128) NULL;",
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS marzban_user_id VARCHAR(64) NULL;",

        # ---- orders ----
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'subscription';",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS plan_code VARCHAR(16) NULL;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS months INTEGER NULL;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS amount_rub INTEGER NOT NULL DEFAULT 0;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS currency VARCHAR(8) NOT NULL DEFAULT 'RUB';",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(16) NOT NULL DEFAULT 'manual';",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'pending';",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ NULL;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS meta_json TEXT NULL;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS referral_bonus_applied_seconds INTEGER NOT NULL DEFAULT 0;",

        # ---- referral events ----
        "ALTER TABLE referral_events ADD COLUMN IF NOT EXISTS inviter_id INTEGER NULL;",
        "ALTER TABLE referral_events ADD COLUMN IF NOT EXISTS referral_user_id INTEGER NULL;",
        "ALTER TABLE referral_events ADD COLUMN IF NOT EXISTS order_id INTEGER NULL;",
        "ALTER TABLE referral_events ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NULL;",
        "ALTER TABLE referral_events ADD COLUMN IF NOT EXISTS bonus_seconds INTEGER NOT NULL DEFAULT 0;",
        "ALTER TABLE referral_events ADD COLUMN IF NOT EXISTS applied_seconds INTEGER NOT NULL DEFAULT 0;",
        "ALTER TABLE referral_events ADD COLUMN IF NOT EXISTS reversed_at TIMESTAMPTZ NULL;",
        "ALTER TABLE referral_events ADD COLUMN IF NOT EXISTS reversal_reason TEXT NULL;",
        "ALTER TABLE referral_events ADD COLUMN IF NOT EXISTS meta_json TEXT NULL;",

        # ---- indexes (safe) ----
        "CREATE INDEX IF NOT EXISTS ix_users_tg_id ON users (tg_id);",
        "CREATE INDEX IF NOT EXISTS ix_users_referral_code ON users (referral_code);",
        "CREATE INDEX IF NOT EXISTS ix_devices_user_id ON devices (user_id);",
        "CREATE INDEX IF NOT EXISTS ix_orders_user_id ON orders (user_id);",
        "CREATE INDEX IF NOT EXISTS ix_orders_status ON orders (status);",
        "CREATE INDEX IF NOT EXISTS ix_referral_events_inviter_id ON referral_events (inviter_id);",
    ]

    async with engine.begin() as conn:
        for s in stmts:
            try:
                await conn.execute(text(s))
            except Exception as e:
                # Log and continue: if a table doesn't exist yet, create_all will have created it,
                # but if someone changed names manually we prefer not to crash.
                logger.warning(f"Migration statement failed: {s} -> {type(e).__name__}: {e}")

        # Foreign key for inviter_id (idempotent DO block)
        try:
            await conn.execute(text(
                """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'users_inviter_id_fkey'
  ) THEN
    ALTER TABLE users
      ADD CONSTRAINT users_inviter_id_fkey
      FOREIGN KEY (inviter_id) REFERENCES users(id)
      ON DELETE SET NULL;
  END IF;
END $$;
"""
            ))
        except Exception as e:
            logger.warning(f"FK migration failed: {type(e).__name__}: {e}")

        # Foreign key for subscriptions.user_id
        try:
            await conn.execute(text(
                """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'subscriptions_user_id_fkey'
  ) THEN
    ALTER TABLE subscriptions
      ADD CONSTRAINT subscriptions_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES users(id)
      ON DELETE CASCADE;
  END IF;
END $$;
"""
            ))
        except Exception as e:
            logger.warning(f"FK migration failed: {type(e).__name__}: {e}")

        # devices.user_id
        try:
            await conn.execute(text(
                """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'devices_user_id_fkey'
  ) THEN
    ALTER TABLE devices
      ADD CONSTRAINT devices_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES users(id)
      ON DELETE CASCADE;
  END IF;
END $$;
"""
            ))
        except Exception as e:
            logger.warning(f"FK migration failed: {type(e).__name__}: {e}")

        # orders.user_id
        try:
            await conn.execute(text(
                """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'orders_user_id_fkey'
  ) THEN
    ALTER TABLE orders
      ADD CONSTRAINT orders_user_id_fkey
      FOREIGN KEY (user_id) REFERENCES users(id)
      ON DELETE CASCADE;
  END IF;
END $$;
"""
            ))
        except Exception as e:
            logger.warning(f"FK migration failed: {type(e).__name__}: {e}")

        # referral_events -> users/orders
        try:
            await conn.execute(text(
                """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'referral_events_inviter_id_fkey'
  ) THEN
    ALTER TABLE referral_events
      ADD CONSTRAINT referral_events_inviter_id_fkey
      FOREIGN KEY (inviter_id) REFERENCES users(id)
      ON DELETE SET NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'referral_events_referral_user_id_fkey'
  ) THEN
    ALTER TABLE referral_events
      ADD CONSTRAINT referral_events_referral_user_id_fkey
      FOREIGN KEY (referral_user_id) REFERENCES users(id)
      ON DELETE SET NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'referral_events_order_id_fkey'
  ) THEN
    ALTER TABLE referral_events
      ADD CONSTRAINT referral_events_order_id_fkey
      FOREIGN KEY (order_id) REFERENCES orders(id)
      ON DELETE SET NULL;
  END IF;
END $$;
"""
            ))
        except Exception as e:
            logger.warning(f"FK migration failed: {type(e).__name__}: {e}")

    logger.info("Migrations applied (idempotent).")
