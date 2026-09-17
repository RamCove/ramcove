"""ROOM API. Every private route checks the session and role on the server."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import load_settings
from .routes import demo, miner, operator, public_routes, review_routes, worker_routes
from .services.context import AppContext, ArtifactStore, ServiceError
from .signing import ServiceSigner
from .store.db import make_engine, new_id

log = logging.getLogger("room.api")
SESSION_COOKIE = "room_session"


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
        title="ROOM API",
        version="0.1.0",
        description="Local development build of the ROOM subnet platform. Chain, beacon, workers and "
        "payments are simulated and labelled.",
        openapi_tags=[
            {"name": "public"},
            {"name": "miner"},
            {"name": "validator"},
            {"name": "review"},
            {"name": "operator"},
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
            "x-room-worker",
            "x-room-timestamp",
            "x-room-signature",
            "idempotency-key",
        ],
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method == "POST" and not request.url.path.startswith("/v1/worker/"):
            origin = request.headers.get("origin")
            if origin and origin != ctx.settings.public_origin:
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
        review_routes.router,
        operator.router,
        worker_routes.router,
        demo.router,
    ):
        app.include_router(router)
    return app


def run() -> None:
    import uvicorn

    uvicorn.run(
        create_app(), host="127.0.0.1", port=int(os.environ.get("ROOM_API_PORT", "8787")), log_level="info"
    )
