# Runbook: deployment

**This build has never been deployed.** Public deployment, production databases and GPU rentals need
separate authorization. What follows is the procedure to review before asking for it.

## Components

| Component | Process | Notes |
|---|---|---|
| PostgreSQL | managed or self-hosted 17.x | authoritative; needs backups and PITR |
| API | `ramcove-api` (uvicorn) | stateless; needs the database URL and the artifact store |
| Controller | `ramcove-controller` | exactly one instance; advisory locks make extra instances safe but pointless |
| Workers | `ramcove-worker` on isolation hosts | one whole GPU each; never co-located with the controller |
| Web | `next start` or a static host with a server runtime | proxies to the API; no secrets in the bundle |

## Order of operations

1. Apply migrations: `uv run ramcove-admin migrate` (run once; it is idempotent).
2. Publish the profile version and confirm its rule hash matches what you intend.
3. Start the API, then the controller, then workers.
4. Confirm `/v1/status`: chain observation fresh, workers safe-and-ready, no open incidents.
5. Start the web app and check the banner names the right environment and network.

## Configuration that must be set deliberately

- `RAMCOVE_ENV`: `demo`, `local` or `testnet`. `mainnet` is refused by this build.
- `RAMCOVE_DATABASE_URL`, `RAMCOVE_ARTIFACT_DIR` (or the S3-compatible equivalent when implemented).
- `RAMCOVE_PUBLIC_ORIGIN` — the origin check and the sign-in challenge both use it.
- Worker: `RAMCOVE_WORKER_ID`, `RAMCOVE_WORKER_KEY_URI` (development) or an external signer, and the provider
  variables.

## Before switching intake on

Everything in `docs/integration-readiness.md` for the mode you are entering. In particular: no paid
admissions until at least one worker reports `untrusted_code_isolation: true` from real probes.

## Rollback of a deployment

Redeploy the previous image and run no down-migration unless the release notes say so. Schema changes are
additive where possible; a destructive change needs its own runbook entry and a tested restore first.
