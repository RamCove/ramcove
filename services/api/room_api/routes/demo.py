"""Demo-only routes: labelled dataset, fixtures, simulated chain actions and scenario seeding.

Every route here refuses to run outside demo mode, so a demonstration dataset can never become
production behaviour.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from room_miner.artifact import pack, sign_artifact
from room_miner.fixtures import FIXTURES, by_name, manifest_for

from ..services import intake, seed
from ..services.auth import demo_keypair
from ..services.context import AppContext, ServiceError
from ..services.control import tick
from ..store.db import tx
from .deps import get_ctx, idempotent, require_role, require_session

router = APIRouter(prefix="/v1/demo", tags=["demo"])


def _require_demo(ctx: AppContext) -> None:
    if not ctx.settings.demo_features:
        raise ServiceError("disabled", "demo routes are disabled in this mode", 403)


class FixtureSubmitIn(BaseModel):
    fixture: str = Field(min_length=3, max_length=80)


@router.get("/identities")
def identities(ctx: AppContext = Depends(get_ctx)) -> dict:
    _require_demo(ctx)
    return {
        "identities": [{"key": d.key, "name": d.name, "roles": list(d.roles)} for d in seed.DEMO_IDENTITIES],
        "note": "Demo identities sign server-side with published development keys. They have no value on any "
        "real network and exist only in demo mode.",
    }


@router.get("/fixtures")
def fixtures(ctx: AppContext = Depends(get_ctx)) -> dict:
    _require_demo(ctx)
    return {
        "fixtures": [
            {
                "name": f["name"],
                "title": f["title"],
                "role": f["role"],
                "mechanism": f.get("mechanism"),
                "method": f.get("method"),
            }
            for f in FIXTURES
            if f["role"] == "challenger"
        ],
        "note": "Trusted repository fixtures. The simulated worker evaluates only these; any other artifact "
        "passes free preflight but cannot be quoted, because no real isolation backend is available.",
    }


@router.post("/submit-fixture")
def submit_fixture(
    body: FixtureSubmitIn,
    ctx: AppContext = Depends(get_ctx),
    sess: dict = Depends(require_session),
    idempotency_key: str | None = Header(None),
) -> dict:
    """SIMULATION: builds the fixture artifact, signs it with the demo identity's key and runs free preflight."""
    _require_demo(ctx)

    def produce() -> dict:
        try:
            fx = by_name(body.fixture)
        except KeyError as e:
            raise ServiceError("unknown_fixture", "unknown fixture", 404) from e
        with tx(ctx.engine) as conn:
            profile = ctx.profile(conn)
            from ..services.queue import current_champion

            champ = current_champion(conn, profile.profile_id)
        kp = demo_keypair(ctx, sess["hotkey"])
        data = pack(
            manifest_for(fx, sess["hotkey"], profile.profile_id, profile.version, champ.version), fx["patch"]
        )
        sig = sign_artifact(kp, data, ctx.settings.network, profile.profile_id, profile.version)
        return intake.preflight(ctx, sess["hotkey"], data, sig)

    return idempotent(ctx, sess["hotkey"], "submit-fixture", idempotency_key, produce)


@router.post("/register-hotkey")
def register_hotkey(ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_session)) -> dict:
    """SIMULATION: registers the signed-in hotkey on the dev chain so it can receive weight."""
    _require_demo(ctx)
    with tx(ctx.engine) as conn:
        chain = ctx.chain(conn)
        uid = chain.store.register(ctx.settings.netuid, sess["hotkey"])
        return {"hotkey": sess["hotkey"], "uid": uid, "simulated": True}


@router.post("/tick")
def manual_tick(ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("operator"))) -> dict:
    _require_demo(ctx)
    return {"result": tick(ctx)}


class ScenarioIn(BaseModel):
    name: str = Field(min_length=3, max_length=40)


@router.get("/scenarios")
def scenarios(ctx: AppContext = Depends(get_ctx)) -> dict:
    _require_demo(ctx)
    from ..services.scenarios import SCENARIOS

    return {"scenarios": [{"name": k, "description": v} for k, v in SCENARIOS.items()]}


@router.post("/scenario")
def run_scenario(
    body: ScenarioIn, ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("operator"))
) -> dict:
    """SIMULATION: drives the real services to produce a labelled demo state."""
    _require_demo(ctx)
    from ..services.scenarios import run

    return run(ctx, body.name)


@router.post("/reset")
def reset(ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("operator"))) -> dict:
    _require_demo(ctx)
    seed.reset_database(ctx)
    return {**seed.seed_base(ctx), "reset": True}
