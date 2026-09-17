"""Versioned competition rules.

A ``ProfileVersion`` is immutable once published: its canonical hash is recorded with every quote,
comparison and promotion. All numeric values here are *provisional planning values* from the ROOM
v0.2 whitepaper and review corrections; none is a measured service guarantee.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import record_hash

RULESET_VERSION = "room.rules/1"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelPin(Frozen):
    repo: str
    revision: str
    license: str
    shard_sha256: list[str] = Field(default_factory=list, description="Empty until verified by download")


class EnginePin(Frozen):
    repo: str
    tag: str
    commit: str
    image_digest: str | None = None
    allowed_paths: list[str]
    forbidden_paths: list[str]


class HardwarePin(Frozen):
    gpu: str
    gpu_count: Literal[1] = 1
    cpu_cores: int
    vm_ram_gib: int
    swap: Literal[False] = False
    network: Literal["none"] = "none"
    gpu_ceiling_margin_mib: int
    isolation: str


class ReplacementRule(Frozen):
    """Section 8.2: replace only if exp(L) - 1 > delta, L a one-sided lower bound over paired blocks."""

    delta_ppm: int = Field(description="Margin in parts per million; 50_000 = 5%")
    blocks: int = Field(ge=3, le=30)
    sigma_floor_ppm: int = Field(description="Floor on block log-ratio SD, ppm; 20_000 = 0.02")
    confidence: Literal["one_sided_95"] = "one_sided_95"
    grid_step_ppm: int = 30_000
    grid_min_steps: int = Field(-8, description="Lowest grid rate = base * (1+step)^min")
    grid_max_steps: int = Field(16, description="Highest grid rate = base * (1+step)^max")
    max_runs_per_arm_per_block: int = 6
    triage_allowance_ppm: int = 20_000
    calibrated: bool = Field(False, description="False until a Stage 1 noise study has been published")


class QualityRule(Frozen):
    """Review R1: non-inferiority vs champion AND fixed floors vs a frozen quality reference."""

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
    drift_q4_over_q2_bp: int = 12500


class StageEnvelope(Frozen):
    """Review R3: conservative GPU-hour reservation per stage, in centi-GPU-hours (integers)."""

    screen: int = 35
    full: int = 892
    confirmation_worst: int = 1925
    rebase_allowance: int = 1925
    soak: int = 600
    recalibration_on_promotion: int = 867

    def total(self) -> int:
        return (
            self.screen
            + self.full
            + self.confirmation_worst
            + self.rebase_allowance
            + self.soak
            + self.recalibration_on_promotion
        )


class Deadlines(Frozen):
    """Review R4: bounded paid lifecycle. Durations in seconds."""

    quote_ttl_blocks: int = 100
    invitation_ttl_s: int = 24 * 3600
    screen_start_target_s: int = 24 * 3600
    lease_screen_s: int = 2 * 3600
    lease_full_s: int = 24 * 3600
    lease_block_s: int = 8 * 3600
    max_lease_retries: int = 1
    max_rebases: int = 2
    quorum_wait_s: int = 7 * 24 * 3600
    max_quorum_reschedules: int = 1
    review_s: int = 14 * 24 * 3600
    review_extension_s: int = 14 * 24 * 3600
    registration_grace_s: int = 14 * 24 * 3600
    end_to_end_s: int = 60 * 24 * 3600
    upload_hold_s: int = 72 * 3600
    credit_expiry_s: int = 180 * 24 * 3600


class FeePolicy(Frozen):
    service_cost_usd_cents_per_admission: int = Field(5246, description="Planning estimate, not measured")
    recovery_bp: int = 5000
    round_step_rao: int = 10_000_000
    price_max_age_s: int = 15 * 60
    price_source: str = "coingecko:bittensor:usd"


class Bootstrap(Frozen):
    mode: Literal["local", "testnet_operator", "mainnet"]
    min_independent_validators_for_mainnet: int = 3
    max_stake_share_bp: int = 3333
    quorum_validators_after_sunset: int = 2


class ProfileVersion(Frozen):
    schema_: Literal["room.profile/1"] = Field("room.profile/1", alias="schema")
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
    fees: FeePolicy
    bootstrap: Bootstrap
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
        if self.bootstrap.mode == "mainnet" and not self.measured:
            raise ValueError("mainnet profile versions require measured calibration")
        return self

    def rule_hash(self) -> str:
        return record_hash(self.model_dump(mode="json", by_alias=True))
