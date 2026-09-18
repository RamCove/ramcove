"""Fee quotes from a published formula (Section 11.3, review R10). Accepted quotes never change."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .money import RAO_PER_TAO, round_up_rao
from .rules import FeePolicy


@dataclass(frozen=True)
class PriceObservation:
    source: str
    usd_micros_per_tao: int  # $227.92 -> 227_920_000
    observed_at: datetime
    simulated: bool


class StalePriceError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeeComputation:
    fee_rao: int
    target_usd_cents: int
    fee_usd_cents_at_price: int
    subsidy_usd_cents: int
    service_cost_usd_cents: int
    price: PriceObservation


def compute_fee(policy: FeePolicy, price: PriceObservation, now: datetime) -> FeeComputation:
    if price.source != policy.price_source and not price.simulated:
        raise StalePriceError(
            f"price source {price.source} is not the published source {policy.price_source}"
        )
    if now - price.observed_at > timedelta(seconds=policy.price_max_age_s):
        raise StalePriceError("price observation is too old; new quotes are refused until it refreshes")
    if price.usd_micros_per_tao <= 0:
        raise StalePriceError("invalid price")
    target_cents = policy.service_cost_usd_cents_per_admission * policy.recovery_bp // 10_000
    # rao = (cents / 100) / (micros / 1e6) * 1e9 = cents * 1e13 / micros
    exact = Decimal(target_cents) * Decimal(RAO_PER_TAO) * Decimal(10_000) / Decimal(price.usd_micros_per_tao)
    fee = round_up_rao(exact, policy.round_step_rao)
    fee_cents = fee * price.usd_micros_per_tao // (RAO_PER_TAO * 10_000)
    return FeeComputation(
        fee,
        target_cents,
        fee_cents,
        policy.service_cost_usd_cents_per_admission - fee_cents,
        policy.service_cost_usd_cents_per_admission,
        price,
    )
