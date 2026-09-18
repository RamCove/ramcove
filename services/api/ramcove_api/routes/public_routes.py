"""Public read routes and hotkey sign-in."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from ..services import auth as auth_svc
from ..services import public
from ..services.context import AppContext, ServiceError
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
    from fastapi import Request  # noqa: F401

    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
