"""Which door a request came through: the operator's own machine, or the public site."""

from __future__ import annotations

from fastapi import Request

# Requests that arrive through the public reverse proxy carry this header, set by the proxy itself and
# never taken from the client. Everything that only the operator, reviewers, validators or workers may
# do is refused on that channel, even if a session somehow held the role.
PUBLIC_CHANNEL_HEADER = "x-ramcove-channel"
PUBLIC_DENY = (
    "/v1/worker/",
    "/v1/operator/",
    "/v1/review/",
    "/v1/appeals",
    "/v1/validator/",
    "/v1/demo/reset",
    "/v1/demo/scenario",
    "/v1/demo/register-hotkey",
    "/v1/demo/tick",
    "/v1/auth/demo",
    "/v1/miner/preflight",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def is_public(request: Request) -> bool:
    return request.headers.get(PUBLIC_CHANNEL_HEADER) == "public"
