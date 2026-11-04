"""Versioned competition rules.

A ``ProfileVersion`` is immutable once published: its canonical hash is recorded with every
admission, comparison and promotion. The numeric values are *provisional planning values* until a
calibration on the profile's hardware replaces them in a new version; none is a measured service guarantee.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import record_hash

RULESET_VERSION = "ramcove.rules/1"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelPin(Frozen):
    repo: str
    revision: str
    license: str
    shard_sha256: list[str] = Field(default_factory=list, description="Empty until verified by download")
    # how the model is served is part of the contract: a stack may not change what the answers are
    mode: Literal["non-thinking"] = "non-thinking"
    input: Literal["text"] = "text"
    max_model_len: int = 32768
    decoding: Literal["greedy"] = "greedy"


class EnginePin(Frozen):
    repo: str
    tag: str
    commit: str
    image_digest: str | None = None
    allowed_paths: list[str]
    forbidden_paths: list[str]
    torch: str | None = None
    cuda: str | None = None
    python_lock_sha256: str | None = Field(None, description="Empty until the build image is pinned")
    args_sha256: str | None = Field(
        None, description="Hash of the tuned baseline's engine arguments (config/engine_args/…json)"
    )


class HardwarePin(Frozen):
    gpu: str
    gpu_count: Literal[1] = 1
    cpu_cores: int
    vm_ram_gib: int
    swap: Literal[False] = False
    network: Literal["none"] = "none"
    gpu_ceiling_margin_mib: int
    isolation: str
    driver: str | None = Field(None, description="Pinned before submissions open")
    firmware: str | None = Field(None, description="Pinned before submissions open")
    power_limit: str = "SXM default, checked every run"
    tight_ceiling_share_bp: int = Field(
        2500, description="The memory-evidence budget: the ceiling less this share of the champion's cache"
    )


class EvaluatorPin(Frozen):
    version: str
    weights_version_key: int


class ReplacementRule(Frozen):
    """The challenger is measured once against the champion's fixed score.

    A first reading at or above ``clear_win_ppm`` wins at once; one at or below ``delta_ppm`` loses; one in
    between gets exactly one more reading, and the average of the two must exceed the margin.
    """

    delta_ppm: int = Field(description="Margin in parts per million; 50_000 = 5%")
    clear_win_ppm: int = Field(
        90_000, description="A first reading at or above this gain needs no second one"
    )
    grid_step_ppm: int = 30_000
    grid_min_steps: int = Field(-8, description="Lowest grid rate = base * (1+step)^min")
    grid_max_steps: int = Field(16, description="Highest grid rate = base * (1+step)^max")
    calibrated: bool = Field(
        False, description="False until a noise study on the profile's hardware has been published"
    )


class QualityRule(Frozen):
    """Non-inferiority vs champion AND fixed floors vs a frozen quality reference."""

    reference_id: str = Field(description="Frozen quality-reference implementation for this profile version")
    vs_champion_margin_bp: int = Field(200, description="Lower bound must exceed -2.00 points")
    vs_champion_stratum_margin_bp: int = 300
    vs_reference_margin_bp: int = Field(
        300, description="Lower bound vs fixed reference must exceed -3.00 points"
    )
    absolute_min_accuracy_bp: dict[str, int] = Field(
        description="Per task group absolute floor, basis points"
    )
    length_ratio_vs_reference_bp: int = Field(
        9000, description="Median and p10 length >= 90% of fixed reference"
    )


class LatencyGates(Frozen):
    ttft_base_ms: int = 1000
    ttft_per_1k_prompt_ms: int = 100
    tpot_mean_ms: int = 100
    stall_ms: int = 2000
    e2e_per_output_token_ms: int = 150
    deadline_ms: int = 60_000
    attainment_bp: int = 9500
    band_attainment_bp: int = 9000
    max_error_bp: int = 50
    drift_q4_over_q2_bp: int = Field(
        14000,
        description="p90 end-to-end in the last quarter over the second quarter. An 8-minute window leaves "
        "about 60 requests per quarter, and at 1.25 the band fires on sample noise in 3 runs in 20 well "
        "below capacity; 1.40 fires in 1 and still catches half the runs at 1.5x capacity, where attainment "
        "catches the rest.",
    )
    stability_floor_bp: int = Field(
        5000,
        description="Drift and burst recovery fail only when the later p90 end-to-end is also at least this "
        "share of the requests' own limits. They are ratios, and a stack with memory to spare answers so fast "
        "before a burst that a harmless absolute rise becomes a large ratio: without this floor a stack 30% "
        "better than the champion failed as often as the champion did at every load.",
    )
    burst_recovery_bp: int = Field(
        13500,
        description="After a burst, p90 end-to-end must return to this share of the pre-burst level. An "
        "8-minute window leaves about 30 requests on each side of the comparison, and at 1.20 that band "
        "fires on sample noise in one run in five well below capacity; at 1.35 it fires in one in twenty "
        "and still catches every run at 1.5x capacity.",
    )


class StageEnvelope(Frozen):
    """GPU time booked for an admission, in centi-GPU-hours (integers): screening plus one evaluation
    (quality, up to two capacity readings and the GPU check). A winner's extra checks and the new champion's
    calibration draw on the published reserve instead of being booked in advance."""

    screen: int = 17
    evaluation: int = 224
    winner_checks: int = 357
    recalibration_on_promotion: int = 651
    champion_answers_per_bank: int = 75

    def total(self) -> int:
        return self.screen + self.evaluation


class Deadlines(Frozen):
    """Bounded lifecycle. Durations in seconds."""

    invitation_ttl_s: int = 24 * 3600
    screen_start_target_s: int = 24 * 3600
    lease_screen_s: int = 2 * 3600
    lease_full_s: int = 24 * 3600
    lease_reproduce_s: int = 8 * 3600
    max_lease_retries: int = 1
    quorum_wait_s: int = 7 * 24 * 3600
    max_quorum_reschedules: int = 1
    review_s: int = 14 * 24 * 3600
    review_extension_s: int = 14 * 24 * 3600
    registration_grace_s: int = 14 * 24 * 3600
    second_reading_delay_s: int = Field(
        7200,
        description="A second reading's beacon round is this long after the first reading's, so its traffic "
        "is fresh and cannot be known when the first reading starts",
    )
    beacon_min_delay_s: int = Field(
        1800,
        description="A reading's beacon round must be at least this far after its anchor is finalized, so "
        "nobody can know the traffic before the artifact and its admission are frozen",
    )
    upload_hold_s: int = 72 * 3600


class Deployment(Frozen):
    """Where this profile version runs. Evaluation is owner-operated: other validators set weights from the
    owner's signed results (``ramcove_protocol.weight_document``) and run no evaluation."""

    mode: Literal["local", "testnet_operator", "mainnet"]
    reproduce_winners: bool = Field(
        False,
        description="Repeat a winner's reading once on a worker of another evaluation group before promotion. "
        "Off by default; turning it on needs a second evaluation group.",
    )


class QuestionBankRule(Frozen):
    """The owner platform's secret question bank, rotated on a fixed schedule.

    Periods start at ``epoch`` plus whole multiples of ``period_days``. The next bank's commitment is published
    at least ``commit_ahead_s`` before its period starts, and a bank's seed is revealed when its period ends.
    """

    period_days: int = Field(7, ge=1)
    epoch: str = Field("2026-09-21T00:00:00Z", description="First period start, UTC")
    commit_ahead_s: int = 24 * 3600
    screening_long: int = 150
    screening_general: int = 50
    offline_long: int = 3200
    offline_general: int = 800


class ProfileVersion(Frozen):
    schema_: Literal["ramcove.profile/1"] = Field("ramcove.profile/1", alias="schema")
    profile_id: str
    version: str
    title: str
    model: ModelPin
    engine: EnginePin
    hardware: HardwarePin
    workloads: list[str]
    replacement: ReplacementRule
    quality: QualityRule
    latency: LatencyGates
    envelope: StageEnvelope
    deadlines: Deadlines
    deployment: Deployment
    question_bank: QuestionBankRule = Field(default_factory=QuestionBankRule)
    evaluator: EvaluatorPin = Field(
        default_factory=lambda: EvaluatorPin(version="0.1.0", weights_version_key=100)
    )
    plive_rate_bp: int = Field(
        9000, description="P-live runs at this share of confirmed capacity (provisional)"
    )
    archive_max_bytes: int = 20 * 1024 * 1024
    archive_max_unpacked_bytes: int = 80 * 1024 * 1024
    archive_max_entries: int = 2000
    allowed_licenses: list[str] = Field(default_factory=lambda: ["Apache-2.0", "MIT", "BSD-3-Clause"])
    measured: bool = Field(False, description="True only after real-hardware calibration is published")
    no_winner_writer_verified: bool = Field(False, description="True only after testnet shows the mechanism")

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _consistency(self) -> ProfileVersion:
        if self.deployment.mode == "mainnet" and not self.measured:
            raise ValueError("mainnet profile versions require measured calibration")
        return self

    def rule_hash(self) -> str:
        return record_hash(self.model_dump(mode="json", by_alias=True))
