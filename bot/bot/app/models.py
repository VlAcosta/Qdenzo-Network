# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    is_banned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')

    inviter_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    referral_code: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)
    locale: Mapped[str | None] = mapped_column(String(8), nullable=True)
    profile_code: Mapped[str] = mapped_column(String(16), nullable=False, server_default="'smart'")
    profile_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


    inviter: Mapped['User | None'] = relationship('User', remote_side=[id], backref='invitees')

    subscription: Mapped['Subscription | None'] = relationship('Subscription', back_populates='user', uselist=False)
    devices: Mapped[list['Device']] = relationship('Device', back_populates='user')
    orders: Mapped[list['Order']] = relationship('Order', back_populates='user')

    last_device_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_device_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_device_label: Mapped[str | None] = mapped_column(String(64), nullable=True)



class Subscription(Base):
    __tablename__ = 'subscriptions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)

    plan_code: Mapped[str] = mapped_column(String(16), nullable=False, server_default='trial')
    devices_limit: Mapped[int] = mapped_column(Integer, nullable=False, server_default='1')
    trial_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default='false')

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped['User'] = relationship('User', back_populates='subscription')


class Device(Base):
    __tablename__ = 'devices'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    slot: Mapped[int] = mapped_column(Integer, nullable=False, server_default='1')
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default='phone')
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default='active')  # active/disabled/deleted

    profile_code: Mapped[str] = mapped_column(String(16), nullable=False, server_default="'smart'")

    marzban_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    marzban_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped['User'] = relationship('User', back_populates='devices')


class Order(Base):
    __tablename__ = 'orders'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default='subscription')
    plan_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    months: Mapped[int | None] = mapped_column(Integer, nullable=True)

    amount_rub: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default='RUB')
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False, server_default='manual')
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default='pending')  # pending/paid/canceled/refunded

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    referral_bonus_applied_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')

    user: Mapped['User'] = relationship('User', back_populates='orders')


class ReferralEvent(Base):
    __tablename__ = 'referral_events'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inviter_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    referral_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey('orders.id', ondelete='SET NULL'), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bonus_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    applied_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')

    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    inviter: Mapped['User | None'] = relationship('User', foreign_keys=[inviter_id])
    referral_user: Mapped['User | None'] = relationship('User', foreign_keys=[referral_user_id])
    order: Mapped['Order | None'] = relationship('Order')


class ReferralWindow(Base):
    """Tracks inviter's current 30-day window to enforce the 15-day monthly cap."""

    __tablename__ = 'referral_windows'

    inviter_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)

    window_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    window_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    applied_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    inviter: Mapped['User'] = relationship('User')
