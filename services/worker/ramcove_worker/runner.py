"""Stage execution for a leased job. Pure orchestration; the provider decides what may run."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ramcove_evaluator import pipeline
from ramcove_evaluator.bank import build_bank
from ramcove_evaluator.target import StackParams
from ramcove_protocol.rules import ProfileVersion

from .isolation import IsolationProvider, IsolationUnavailable


def _params(d: dict[str, Any]) -> StackParams:
    return StackParams(**d)


def execute(
    payload: dict[str, Any],
    provider: IsolationProvider,
    profile: ProfileVersion,
    fetch_artifact: Callable[[str], bytes],
    on_progress: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    try:
        champ = payload["champion"]
        champ_bytes = fetch_artifact(champ["artifact_sha256"]) if champ.get("artifact_sha256") else None
        champion = _params(provider.resolve_stack(champ_bytes))
        stage = payload["stage"]
        # the owner's question bank for this period: every job in the period uses the same questions
        if not (payload.get("bank") or {}).get("seed"):
            return {"infra_failure": "no question bank was issued for this period"}
        bank = build_bank(payload["bank"]["bank_id"], payload["bank"]["seed"], profile.question_bank)
        if stage == "calibration":
            start = (payload.get("start_milli_rps") or 500) / 1000
            return pipeline.calibrate(
                champion,
                profile,
                f"calibration:{payload['job_id']}",
                base_rps=start,
                bank=bank,
                on_progress=on_progress,
            )
        candidate = _params(provider.resolve_stack(fetch_artifact(payload["artifact_sha256"])))
        calibration = payload.get("calibration") or {}
        if stage == "screen":
            return pipeline.screen(
                candidate, champion, profile, payload["seed"], bank, calibration, on_progress
            )
        if not calibration.get("capacity_milli_rps"):
            return {"infra_failure": "worker has no valid champion calibration"}
        if stage in ("full", "reproduce"):
            run = pipeline.evaluate if stage == "full" else pipeline.reproduce
            out = run(candidate, champion, profile, payload["seed"], calibration, bank, on_progress)
            out["comparison_id"] = payload["comparison_id"]
            return out
        return {"infra_failure": f"unknown stage {stage}"}
    except IsolationUnavailable as e:
        return {"infra_failure": f"isolation unavailable: {e}"}
    except pipeline.CalibrationMissing as e:
        return {"infra_failure": str(e)}


def result_json(result: dict[str, Any]) -> str:
    return json.dumps(result, sort_keys=True, default=list)
