"""Versioned synthetic task generation with known answers (``ramcove.taskgen/1``).

A seed deterministically produces conversations with planted facts, distractors and graded
questions. The seed manifest records generator version, seed and item hashes so results can be
replayed. Grading is exact / numeric / set match only.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from ramcove_protocol.canonical import record_hash

GENERATOR_VERSION = "ramcove.taskgen/1"
BANDS = [(0, 2000, 25), (2000, 8000, 45), (8000, 24000, 25), (24000, 32000, 5)]
POSITIONS = ["position_early", "position_middle", "position_late"]
MEAN_TURNS = 2.57  # used for requests/s <-> conversations/s conversion; published in the profile workload


@dataclass(frozen=True)
class Item:
    item_id: str
    group: str
    band: int
    prompt_tokens: int
    output_tokens: int
    kind: str  # exact | numeric | set
    answer: str


@dataclass(frozen=True)
class Conversation:
    conv_id: str
    turns: tuple[Item, ...]
    think_s: tuple[float, ...]


def _rng(seed: str, label: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{seed}:{label}".encode()).hexdigest()[:16], 16))


def _band(r: random.Random) -> int:
    x = r.uniform(0, 100)
    acc = 0
    for i, (_, _, w) in enumerate(BANDS):
        acc += w
        if x <= acc:
            return i
    return len(BANDS) - 1


def make_item(seed: str, idx: int, group: str | None = None) -> Item:
    r = _rng(seed, f"item:{idx}")
    band = _band(r)
    lo, hi, _ = BANDS[band]
    kind = r.choice(["exact", "numeric", "set"])
    fact = r.randrange(10_000, 99_999)
    answer = {
        "exact": f"code-{fact}",
        "numeric": str(fact % 997),
        "set": ",".join(sorted({str(fact % 7), str(fact % 11)})),
    }[kind]
    grp = group or r.choice(POSITIONS)
    return Item(
        f"it-{hashlib.sha256(f'{seed}:{idx}'.encode()).hexdigest()[:12]}",
        grp,
        band,
        r.randint(max(lo, 64), hi),
        r.randint(60, 400),
        kind,
        answer,
    )


def offline_suite(seed: str, n_long: int, n_general: int) -> list[Item]:
    items = [make_item(seed, i, POSITIONS[i % 3]) for i in range(n_long)]
    items += [make_item(seed, n_long + i, "general") for i in range(n_general)]
    return items


def conversations(seed: str, count: int) -> list[Conversation]:
    out = []
    for c in range(count):
        r = _rng(seed, f"conv:{c}")
        n_turns = min(6, max(1, int(r.expovariate(1 / MEAN_TURNS)) + 1))
        turns = tuple(make_item(seed, 1_000_000 + c * 10 + t) for t in range(n_turns))
        think = tuple(round(r.lognormvariate(3.4, 0.6), 3) for _ in range(n_turns))
        out.append(Conversation(f"cv-{c}", turns, think))
    return out


def grade(item: Item, response: str | None) -> bool:
    if response is None:
        return False
    s = response.strip()
    if item.kind == "set":
        return set(s.split(",")) == set(item.answer.split(","))
    return s == item.answer


def seed_manifest(seed: str, items: list[Item], beacon_round: int | None, simulated_beacon: bool) -> dict:
    return {
        "schema": "ramcove.seed_manifest/1",
        "generator": GENERATOR_VERSION,
        "seed": seed,
        "beacon_round": beacon_round,
        "beacon_simulated": simulated_beacon,
        "item_count": len(items),
        "items_hash": record_hash([[i.item_id, i.group, i.band, i.answer] for i in items]),
    }
