"""Fee quotes (Section 11.3, review R10): a flat fee in TAO. Accepted quotes never change.

The TAO price no longer sets the fee. A recent price from the published source is used only to show what the
fee is worth in US dollars; without one the quote still goes out, without a dollar figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .money import RAO_PER_TAO
from .rules import FeePolicy


@dataclass(frozen=True)
class PriceObservation:
    source: str
    usd_micros_per_tao: int  # $227.92 -> 227_920_000
    observed_at: datetime
    simulated: bool


@dataclass(frozen=True)
class FeeComputation:
    fee_rao: int
    fee_usd_cents_at_price: int | None  # None when no recent price from the published source is available
    service_cost_usd_cents: int
    price: PriceObservation | None


def usable_price(policy: FeePolicy, price: PriceObservation | None, now: datetime) -> PriceObservation | None:
    """A price is shown only if it is recent, positive and from the published source (or labelled simulated)."""
    if price is None or price.usd_micros_per_tao <= 0:
        return None
    if price.source != policy.price_source and not price.simulated:
        return None
    if now - price.observed_at > timedelta(seconds=policy.price_max_age_s):
        return None
    return price


def compute_fee(policy: FeePolicy, price: PriceObservation | None, now: datetime) -> FeeComputation:
    shown = usable_price(policy, price, now)
    usd = policy.flat_fee_rao * shown.usd_micros_per_tao // (RAO_PER_TAO * 10_000) if shown else None
    return FeeComputation(policy.flat_fee_rao, usd, policy.service_cost_usd_cents_per_admission, shown)
