"""Public read routes and hotkey sign-in."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from ..services import auth as auth_svc
from ..services import public, weight_documents
from ..services.context import AppContext, ServiceError
from ..store.db import tx
from .deps import SESSION_COOKIE, get_ctx, require_role, session

router = APIRouter(prefix="/v1", tags=["public"])


class ChallengeIn(BaseModel):
    hotkey: str = Field(min_length=46, max_length=48)


class VerifyIn(BaseModel):
    nonce: str
    signature: str


class DemoSignInIn(BaseModel):
    identity: str


@router.get("/meta")
def meta(ctx: AppContext = Depends(get_ctx)) -> dict:
    return public.meta(ctx)


@router.get("/dashboard")
def dashboard(ctx: AppContext = Depends(get_ctx)) -> dict:
    return public.dashboard(ctx)


@router.get("/overview")
def overview(ctx: AppContext = Depends(get_ctx)) -> dict:
    return public.overview(ctx)


@router.get("/profile")
def profile(ctx: AppContext = Depends(get_ctx)) -> dict:
    return public.profile_detail(ctx)


@router.get("/queue")
def queue(
    kind: str = Query("admitted", pattern="^(admitted|waiting|history)$"),
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    ctx: AppContext = Depends(get_ctx),
) -> dict:
    return public.queue_page(ctx, kind, cursor, limit)


@router.get("/submissions/{submission_id}")
def submission(
    submission_id: str, ctx: AppContext = Depends(get_ctx), sess: dict | None = Depends(session)
) -> dict:
    view = public.submission_view(
        ctx, submission_id, sess["hotkey"] if sess else None, set(sess["roles"]) if sess else set()
    )
    if not view:
        raise ServiceError("not_found", "submission not found", 404)
    return view


@router.get("/status")
def status(ctx: AppContext = Depends(get_ctx)) -> dict:
    return public.status_page(ctx)


@router.get("/question-banks")
def question_banks(ctx: AppContext = Depends(get_ctx)) -> dict:
    """Commitments of the owner's question banks, and the seeds of banks whose period has ended."""
    return public.question_banks(ctx)


@router.get("/champion-code")
def champion_code(ctx: AppContext = Depends(get_ctx)) -> dict:
    """The current champion's patches in order, the engine commit they apply to, and the engine settings."""
    return public.champion_code(ctx)


@router.get("/champions/{version}/artifact")
def champion_artifact(version: int, ctx: AppContext = Depends(get_ctx)) -> Response:
    """A promoted champion's code: manifest.json and patch.diff in a tar.gz."""
    return Response(
        public.champion_artifact(ctx, version),
        media_type="application/gzip",
        headers={"content-disposition": f'attachment; filename="champion-v{version}.tar.gz"'},
    )


@router.get("/weights/latest", tags=["validators"])
def weights_latest(ctx: AppContext = Depends(get_ctx)) -> dict:
    """The owner's signed weight result. Validators check the signature against the pinned signer, map the
    hotkeys to UIDs from their own chain reads, and submit the weights. It is renewed every tempo."""
    with tx(ctx.engine) as conn:
        signed = weight_documents.latest_signed(conn, ctx)
    if signed is None:
        raise ServiceError("no_weight_document", "no signed weight result has been issued yet", 503)
    return signed


@router.get("/weights/signer", tags=["validators"])
def weights_signer(ctx: AppContext = Depends(get_ctx)) -> dict:
    """The key that signs weight results. Validators pin it in their own configuration and must not
    accept a signer they only learned from this response."""
    return {
        "address": ctx.signer.address,
        "scheme": "sr25519",
        "network": ctx.settings.network,
        "netuid": ctx.settings.netuid,
        "simulated_chain": ctx.settings.simulated_chain,
    }


@router.get("/audit")
def audit(cursor: str | None = None, ctx: AppContext = Depends(get_ctx)) -> dict:
    return public.audit_page(ctx, public_only=True, cursor=cursor)


@router.get("/validator/workspace", tags=["validator"])
def validator_workspace(
    ctx: AppContext = Depends(get_ctx), sess: dict = Depends(require_role("validator", "operator"))
) -> dict:
    return public.validator_workspace(ctx, sess["hotkey"])


@router.post("/auth/challenge")
def challenge(body: ChallengeIn, ctx: AppContext = Depends(get_ctx)) -> dict:
    return auth_svc.create_challenge(ctx, body.hotkey)


@router.post("/auth/verify")
def verify(body: VerifyIn, response: Response, ctx: AppContext = Depends(get_ctx)) -> dict:
    token, info = auth_svc.verify_and_open_session(ctx, body.nonce, body.signature)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", max_age=12 * 3600, path="/")
    return info


@router.post("/auth/demo", tags=["demo"])
def demo_sign_in(body: DemoSignInIn, response: Response, ctx: AppContext = Depends(get_ctx)) -> dict:
    token, info = auth_svc.demo_sign_in(ctx, body.identity)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", max_age=12 * 3600, path="/")
    return {**info, "demo": True}


@router.get("/auth/me")
def me(sess: dict | None = Depends(session)) -> dict:
    return {"session": sess}


@router.post("/auth/logout")
def logout(
    response: Response, ctx: AppContext = Depends(get_ctx), sess: dict | None = Depends(session)
) -> dict:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
