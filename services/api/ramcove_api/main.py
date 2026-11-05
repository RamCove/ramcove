"""RamCove API. Every private route checks the session and role on the server."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .channel import PUBLIC_DENY, PUBLIC_METHODS, is_public
from .config import load_settings
from .routes import demo, miner, public_routes, validator_routes, worker_routes
from .services.context import AppContext, ArtifactStore, ServiceError
from .signing import ServiceSigner
from .store.db import is_contention, make_engine, new_id

log = logging.getLogger("ramcove.api")
SESSION_COOKIE = "ramcove_session"


def build_context() -> AppContext:
    settings = load_settings()
    return AppContext(
        make_engine(settings.database_url),
        settings,
        ServiceSigner(settings),
        ArtifactStore(settings.artifact_dir),
    )


def create_app(ctx: AppContext | None = None) -> FastAPI:
    ctx = ctx or build_context()
    app = FastAPI(
        title="RamCove API",
        version="0.1.0",
        description="The RamCove subnet's intake, queue and public API. In simulation mode the chain, beacon "
        "and GPU workers are simulated, and every number they produce is labelled.",
        openapi_tags=[
            {"name": "public"},
            {"name": "miner"},
            {"name": "validator"},
            {"name": "worker"},
            {"name": "demo"},
        ],
    )
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ctx.settings.public_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "content-type",
            "x-ramcove-worker",
            "x-ramcove-hotkey",
            "x-ramcove-timestamp",
            "x-ramcove-signature",
            "idempotency-key",
        ],
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if is_public(request) and (request.method not in PUBLIC_METHODS or path.startswith(PUBLIC_DENY)):
            return JSONResponse(
                {
                    "error": {
                        "code": "local_only",
                        "message": "The public site is read-only. Miners and validators use their own tools.",
                    }
                },
                status_code=403,
            )
        if request.method == "POST" and not path.startswith("/v1/worker/"):
            origin = request.headers.get("origin")
            if origin and origin not in ctx.settings.allowed_origins:
                return JSONResponse(
                    {"error": {"code": "bad_origin", "message": "cross-site request refused"}},
                    status_code=403,
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        if is_contention(exc):
            # Lost a lock race even after retrying. Nothing was committed, so say so plainly and invite a
            # retry instead of reporting an internal fault.
            return JSONResponse(
                {
                    "error": {
                        "code": "busy",
                        "message": "Many requests arrived at once and nothing was changed. Please try again.",
                    }
                },
                status_code=503,
                headers={"Retry-After": "2"},
            )
        ref = new_id("err")
        log.exception("unhandled error ref=%s path=%s", ref, request.url.path)
        return JSONResponse(
            {
                "error": {
                    "code": "internal",
                    "message": "Something went wrong on our side. Quote this reference to support.",
                    "reference": ref,
                }
            },
            status_code=500,
        )

    for router in (
        public_routes.router,
        miner.router,
        worker_routes.router,
        validator_routes.router,
        demo.router,
    ):
        app.include_router(router)
    return app


def run() -> None:
    import uvicorn

    uvicorn.run(
        create_app(), host="127.0.0.1", port=int(os.environ.get("RAMCOVE_API_PORT", "8787")), log_level="info"
    )
