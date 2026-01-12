# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanOption:
    code: str            # trial/start/pro/family
    months: int          # 0 for trial
    duration_days: int   # fixed, we use 30 days/month
    price_rub: int       # 0 for trial
    devices_limit: int
    name: str


# Month = 30 days (as requested)
DAYS_PER_MONTH = 30

# Trial duration in hours
TRIAL_HOURS = 48


PLAN_OPTIONS: list[PlanOption] = [
    # Trial (48 hours)
    PlanOption(code='trial', months=0, duration_days=2, price_rub=0, devices_limit=1, name='Trial (48h)'),

    # Start (3 devices)
    PlanOption(code='start', months=1, duration_days=1 * DAYS_PER_MONTH, price_rub=249, devices_limit=3, name='Start'),
    PlanOption(code='start', months=3, duration_days=3 * DAYS_PER_MONTH, price_rub=499, devices_limit=3, name='Start'),
    PlanOption(code='start', months=6, duration_days=6 * DAYS_PER_MONTH, price_rub=999, devices_limit=3, name='Start'),
    PlanOption(code='start', months=12, duration_days=12 * DAYS_PER_MONTH, price_rub=1999, devices_limit=3, name='Start'),

    # Pro (5 devices)
    PlanOption(code='pro', months=1, duration_days=1 * DAYS_PER_MONTH, price_rub=399, devices_limit=5, name='Pro'),
    PlanOption(code='pro', months=3, duration_days=3 * DAYS_PER_MONTH, price_rub=899, devices_limit=5, name='Pro'),
    PlanOption(code='pro', months=6, duration_days=6 * DAYS_PER_MONTH, price_rub=1399, devices_limit=5, name='Pro'),
    PlanOption(code='pro', months=12, duration_days=12 * DAYS_PER_MONTH, price_rub=2499, devices_limit=5, name='Pro'),

    # Family (10 devices)
    PlanOption(code='family', months=3, duration_days=3 * DAYS_PER_MONTH, price_rub=1099, devices_limit=10, name='Family'),
    PlanOption(code='family', months=6, duration_days=6 * DAYS_PER_MONTH, price_rub=1599, devices_limit=10, name='Family'),
    PlanOption(code='family', months=12, duration_days=12 * DAYS_PER_MONTH, price_rub=2999, devices_limit=10, name='Family'),
]


def plan_options(*, include_trial: bool = True) -> list[PlanOption]:
    """Return plan options for keyboards/handlers.

    Some parts of the project import `plan_options()` as a function, while the
    catalog stores the data in the `PLAN_OPTIONS` constant. Exposing this helper
    keeps the public API stable.
    """
    if include_trial:
        return list(PLAN_OPTIONS)
    return [p for p in PLAN_OPTIONS if p.code != "trial"]


def get_plan_option(code: str, months: int) -> PlanOption:
    for p in PLAN_OPTIONS:
        if p.code == code and p.months == months:
            return p
    raise KeyError(f"Unknown plan option: {code} {months}m")


def list_paid_plans() -> list[str]:
    return ['start', 'pro', 'family']


def list_plan_options_by_code(code: str) -> list[PlanOption]:
    return [p for p in PLAN_OPTIONS if p.code == code]


def plan_title(code: str) -> str:
    return {
        'trial': 'Trial',
        'start': 'Start',
        'pro': 'Pro',
        'family': 'Family',
    }.get(code, code)


# Referral bonus matrix (seconds) per your latest rules.
# Inviter plan: if none or trial -> treat as 'start'.

HOUR = 3600
DAY = 24 * HOUR


def referral_bonus_seconds(inviter_plan: str | None, ref_plan: str, ref_months: int) -> int:
    ip = inviter_plan or 'start'
    if ip == 'trial':
        ip = 'start'

    # Normalize categories
    if ref_plan == 'start' and ref_months == 1:
        return {'start': 1 * DAY, 'pro': 12 * HOUR, 'family': 3 * HOUR}[ip]
    if ref_plan == 'start' and ref_months == 3:
        return {'start': 36 * HOUR, 'pro': 12 * HOUR, 'family': 6 * HOUR}[ip]
    if ref_plan == 'start' and ref_months in (6, 12):
        return {'start': 3 * DAY, 'pro': 2 * DAY, 'family': 1 * DAY}[ip]

    if ref_plan == 'pro' and ref_months in (1, 3):
        return {'start': 2 * DAY, 'pro': 1 * DAY, 'family': 12 * HOUR}[ip]
    if ref_plan == 'pro' and ref_months in (6, 12):
        return {'start': 3 * DAY, 'pro': 2 * DAY, 'family': 1 * DAY}[ip]

    if ref_plan == 'family' and ref_months in (3, 6):
        return {'start': 5 * DAY, 'pro': 3 * DAY, 'family': 2 * DAY}[ip]
    if ref_plan == 'family' and ref_months == 12:
        # Note: you wrote "If referra... Pro 12" at the bottom, but context implies Family 12.
        return {'start': 7 * DAY, 'pro': 5 * DAY, 'family': 3 * DAY}[ip]

    return 0


REFERRAL_WINDOW_DAYS = 30
REFERRAL_MAX_BONUS_PER_WINDOW_SECONDS = 15 * DAY
