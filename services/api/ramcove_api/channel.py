"""Which door a request came through: the operator's own machine, or the public site."""

from __future__ import annotations

from fastapi import Request

# Requests that arrive through the public reverse proxy carry this header, set by the proxy itself and
# never taken from the client. The public site only reads: miners submit with the command line and
# validators run ramcove-validator, both against an API they are given directly. So that door accepts
# reads alone, and even among reads it refuses sign-in, personal data and every role's workspace.
PUBLIC_CHANNEL_HEADER = "x-ramcove-channel"
PUBLIC_METHODS = ("GET", "HEAD")
PUBLIC_DENY = (
    "/v1/auth/",
    "/v1/miner/",
    "/v1/demo/",
    "/v1/worker/",
    "/v1/operator/",
    "/v1/review/",
    "/v1/appeals",
    "/v1/validator/",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def is_public(request: Request) -> bool:
    return request.headers.get(PUBLIC_CHANNEL_HEADER) == "public"
