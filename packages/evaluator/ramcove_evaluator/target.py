"""Serving targets.

``SimulatedStack`` is a coarse discrete-time model of a memory-bound LLM server. It exists only to
exercise protocol logic with trusted fixtures; its numbers are NOT predictions of H100 behaviour.

``OpenAICompatibleTarget`` sends real requests to an engine exposing the OpenAI-compatible HTTP API
(for example vLLM). It is implemented but has not been run against real hardware in this build.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import httpx

from .taskgen import POSITIONS, Item

# The simulation's own memory scale: cache cost per resident token at 16-bit, in simulated KiB. It keeps the
# fixtures' memory pressure where the protocol tests need it and is not the profile model's real value.
TOKEN_KIB_16BIT = 256
GIB = 1024 * 1024


@dataclass(frozen=True)
class StackParams:
    """Behaviour of a simulated stack. Values for fixtures live in fixtures/trusted_fixtures.json."""

    name: str
    kv_factor: float = 1.0  # bytes per token relative to 16-bit (0.5 = 8-bit)
    usable_factor: float = 1.0  # extra usable cache from allocation improvements
    decode_overhead: float = 1.0  # >1 slows every decode step (e.g. per-access decompression)
    compute_speedup: float = 1.0  # pure compute speedup (does not change memory)
    retention_bonus: float = 0.0  # fraction of idle caches kept without memory growth (0..0.5)
    base_accuracy_bp: int = 9100
    accuracy_loss_bp: dict[str, int] = field(default_factory=dict)
    length_ratio_bp: int = 10_000
    screen_failure: str | None = None
    crash_under_load: bool = False
    exceeds_memory_ceiling: bool = False
    review_flag: str | None = None  # an automatic check that would send a winner to human review


@dataclass
class RequestLog:
    request_id: str
    conv_id: str
    group: str
    band: int
    scheduled_s: float
    status: str  # qualified | unqualified | errored | rejected | timed_out | unfinished
    ttft_ms: int | None
    tpot_ms: int | None
    e2e_ms: int | None
    correct: bool
    output_tokens: int
    recomputed_prefill_tokens: int


@dataclass
class SimServer:
    params: StackParams
    budget_gib: float
    rng: random.Random
    step_s: float = 0.05
    active: list[dict] = field(default_factory=list)
    idle_cache: dict[str, int] = field(default_factory=dict)  # conv_id -> tokens kept resident
    used_tokens: int = 0
    peak_tokens: int = 0

    @property
    def capacity_tokens(self) -> int:
        per_token_kib = TOKEN_KIB_16BIT * self.params.kv_factor
        return int(self.budget_gib * GIB / per_token_kib * self.params.usable_factor)

    def _free(self) -> int:
        return self.capacity_tokens - self.used_tokens - sum(self.idle_cache.values())

    def _evict_for(self, need: int) -> None:
        while self._free() < need and self.idle_cache:
            victim = next(iter(self.idle_cache))
            keep = int(self.idle_cache[victim] * self.params.retention_bonus)
            if keep and self._free() + self.idle_cache[victim] - keep >= need:
                self.idle_cache[victim] = keep
                return
            del self.idle_cache[victim]


def _ms(x: float) -> int:
    return int(round(x * 1000))


def simulate_run(
    params: StackParams,
    requests: list[tuple[float, Item, str, bool]],
    window_s: float,
    drain_s: float,
    budget_gib: float,
    gates,
    seed: int,
    live: dict | None = None,
) -> list[RequestLog]:
    """Open-loop simulation. ``requests``: (scheduled time, item, conv_id, is_followup). Every scheduled request
    is logged with a terminal status, including those never started.

    ``live`` (P-live): {conv_id: (remaining Items, think times)}. The next turn is released only after the
    previous answer completes plus think time; if an answer times out or errors, every remaining turn of
    that conversation is logged as offered and unqualified, so a slow system cannot hide demand."""
    rng = random.Random(seed)
    live = {k: (list(v[0]), list(v[1])) for k, v in (live or {}).items()}
    srv = SimServer(params, budget_gib, rng)
    pending = sorted(requests, key=lambda r: r[0])
    waiting: list[dict] = []
    logs: dict[str, RequestLog] = {}
    t = 0.0
    i = 0
    end = window_s + drain_s
    noise = rng.uniform(0.99, 1.01)  # simulated run-to-run hardware variation

    def _abandon(conv: str) -> None:
        if conv not in live:
            return
        items, _ = live.pop(conv)
        for it in items:
            rid = f"{conv}:{it.item_id}"
            logs[rid] = RequestLog(
                rid, conv, it.group, it.band, t, "unqualified", None, None, None, False, 0, 0
            )

    def _release_next(conv: str) -> None:
        if conv not in live or not live[conv][0]:
            live.pop(conv, None)
            return
        items, thinks = live[conv]
        nxt, think = items.pop(0), thinks.pop(0)
        at = t + think
        if at <= window_s:
            pending.append((at, nxt, conv, True))
            pending.sort(key=lambda r: r[0])

    acc_by_group = {
        g: max(0, params.base_accuracy_bp - params.accuracy_loss_bp.get(g, 0))
        for g in POSITIONS + ["general"]
    }
    while t < end:
        while i < len(pending) and pending[i][0] <= t:
            sched, item, conv, followup = pending[i]
            rid = f"{conv}:{item.item_id}"
            waiting.append({"rid": rid, "item": item, "conv": conv, "sched": sched, "followup": followup})
            logs[rid] = RequestLog(
                rid, conv, item.group, item.band, sched, "unfinished", None, None, None, False, 0, 0
            )
            i += 1
        # admission: first-come, memory permitting
        still = []
        blocked = False  # starvation guard: once an old request cannot fit, later arrivals wait behind it
        for w in waiting:
            if blocked:
                if t - w["sched"] > gates.deadline_ms / 1000:
                    logs[w["rid"]].status = "timed_out"
                    _abandon(w["conv"])
                    continue
                still.append(w)
                continue
            item: Item = w["item"]
            need = item.prompt_tokens + item.output_tokens
            reuse = srv.idle_cache.pop(w["conv"], 0) if w["followup"] else 0
            recompute = max(0, item.prompt_tokens - reuse)
            srv._evict_for(need)
            if srv._free() >= need and not params.exceeds_memory_ceiling:
                srv.used_tokens += need
                srv.peak_tokens = max(srv.peak_tokens, srv.used_tokens + sum(srv.idle_cache.values()))
                prefill_s = recompute * 0.00012 * params.decode_overhead / params.compute_speedup
                w.update(start=t, first_token_at=t + prefill_s, produced=0, need=need, recompute=recompute)
                srv.active.append(w)
            else:
                if reuse:
                    srv.idle_cache[w["conv"]] = reuse
                if t - w["sched"] > gates.deadline_ms / 1000:
                    logs[w["rid"]].status = "timed_out"
                    _abandon(w["conv"])
                    continue
                if t - w["sched"] > 3.0:
                    blocked = True
                still.append(w)
        waiting = still
        # decode one step for all active sequences
        batch = len(srv.active)
        step_time = (0.018 + 0.0022 * batch) * params.decode_overhead / params.compute_speedup * noise
        tokens_this_step = srv.step_s / step_time if step_time > 0 else 0
        done = []
        for a in srv.active:
            if t < a["first_token_at"]:
                continue
            a["produced"] += tokens_this_step
            if params.crash_under_load and batch > 24 and rng.random() < 0.002:
                logs[a["rid"]].status = "errored"
                _abandon(a["conv"])
                done.append(a)
                continue
            if a["produced"] >= a["item"].output_tokens:
                item = a["item"]
                ttft = a["first_token_at"] - a["sched"]
                gen = t - a["first_token_at"]
                tpot = gen / max(1, item.output_tokens)
                e2e = t - a["sched"]
                lg = logs[a["rid"]]
                correct = rng.random() * 10_000 < acc_by_group.get(item.group, params.base_accuracy_bp)
                lg.ttft_ms, lg.tpot_ms, lg.e2e_ms = _ms(ttft), _ms(tpot), _ms(e2e)
                lg.correct = correct
                lg.output_tokens = item.output_tokens * params.length_ratio_bp // 10_000
                lg.recomputed_prefill_tokens = a["recompute"]
                ttft_limit = gates.ttft_base_ms + gates.ttft_per_1k_prompt_ms * item.prompt_tokens / 1000
                e2e_limit = min(
                    gates.deadline_ms, ttft_limit + gates.e2e_per_output_token_ms * item.output_tokens
                )
                ok = lg.ttft_ms <= ttft_limit and lg.tpot_ms <= gates.tpot_mean_ms and lg.e2e_ms <= e2e_limit
                lg.status = "qualified" if ok else "unqualified"
                _release_next(a["conv"])
                done.append(a)
        for a in done:
            srv.active.remove(a)
            srv.used_tokens -= a["need"]
            if logs[a["rid"]].status in ("qualified", "unqualified"):
                srv.idle_cache[a["conv"]] = a["item"].prompt_tokens + a["item"].output_tokens
        t += srv.step_s
    for w in waiting:
        if logs[w["rid"]].status == "unfinished" and w["sched"] > window_s:
            del logs[w["rid"]]  # scheduled after the window: not offered in this run
    return list(logs.values())


class OpenAICompatibleTarget:
    """Real HTTP target. UNVERIFIED on H100 hardware in this build. Timing is measured client-side."""

    def __init__(self, base_url: str, model: str, timeout_s: float = 60.0) -> None:
        self.base_url, self.model = base_url.rstrip("/"), model
        self.client = httpx.Client(timeout=timeout_s)

    def complete(self, prompt: str, max_tokens: int) -> tuple[str | None, int | None, int | None, int]:
        start = time.monotonic()
        first = None
        chunks = []
        with self.client.stream(
            "POST",
            f"{self.base_url}/v1/completions",
            json={
                "model": self.model,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": True,
            },
        ) as r:
            if r.status_code != 200:
                return None, None, None, 0
            for line in r.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                if first is None:
                    first = time.monotonic()
                chunks.append(line)
        end = time.monotonic()
        text = "".join(chunks)
        ttft = int((first - start) * 1000) if first else None
        return text, ttft, int((end - start) * 1000), len(chunks)
