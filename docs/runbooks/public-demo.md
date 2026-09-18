# Public demo: the hosted site and its live backend

The hosted site (https://ramcove.vercel.app) is the web app on Vercel. Everything behind it — the API,
PostgreSQL, the controller and two simulated workers — runs on the operator's host. Visitors see the same
live competition as the operator's own console, and can take part as guest miners.

```
browser ──HTTPS──▶ Vercel (Next.js server) ──HTTPS + proxy key──▶ nginx :8788 ──▶ API 127.0.0.1:8787
                                                                                   ├─ PostgreSQL (docker)
                                                                                   ├─ controller
                                                                                   └─ workers w-op-1, w-op-2
operator ──SSH tunnel──▶ web console 127.0.0.1:3787 ──────────────────────────────▶ API (local door)
```

## Two doors, one database

| | Public door (hosted site) | Local door (operator's console) |
|---|---|---|
| Reached through | nginx on port 8788, only with the proxy key | 127.0.0.1 on the host, over an SSH tunnel |
| Sign-in | A fresh **guest miner** per visitor | Any demo identity, including operator and reviewers |
| Operator, review, appeal, validator, worker routes | Refused (`local_only`) | Allowed by role |
| Demo reset and scenarios | Refused | Allowed |
| Uploading your own artifact | Refused; submissions use the published fixtures | Allowed |

nginx stamps every request on port 8788 with `X-RamCove-Channel: public` and strips the proxy key before
the API sees it, so a client cannot claim the local door. The rules live in
`services/api/ramcove_api/channel.py` and are covered by `tests/integration/test_public_channel.py`.

Guest miners are new sr25519 identities the server holds and signs for, registered on the development
chain and paying only with simulated funds. Creation is limited per hour across everyone
(`RAMCOVE_GUEST_LIMIT_PER_HOUR`) and to five per visitor per hour.

No person reviews on the public site, so `RAMCOVE_DEMO_AUTO_REVIEW_S` (120 s) lets a labelled stand-in
reviewer approve passing submissions; its recorded reason says it was automatic. Review from the local
console within that window to decide yourself.

## What runs where

| Piece | Where | Managed by |
|---|---|---|
| API, controller, workers, local web console | this repository on the host | systemd units in `infra/systemd/` |
| PostgreSQL | docker compose `infra/docker-compose.yml` | docker, `restart: unless-stopped` |
| nginx site | `infra/nginx/ramcove-api.conf` → `/etc/nginx/sites-available/ramcove-api` | nginx, on the host's existing IP certificate |
| Settings | `/etc/ramcove/ramcove.env` (from `infra/ramcove.env.example`) | root only |
| Proxy key | `/etc/ramcove/proxy.key` and `/etc/nginx/ramcove/proxy-key.conf` | root only, never in git |
| Hosted web app | Vercel team `analyzify360`, project `ramcove` | Vercel |

Vercel project environment (production): `RAMCOVE_API_ORIGIN=https://169.58.173.136:8788`,
`RAMCOVE_PROXY_KEY` (sensitive), `RAMCOVE_PUBLIC_ORIGIN=https://ramcove.vercel.app`. Without
`RAMCOVE_API_ORIGIN` the hosted site falls back to the read-only snapshot preview.

## Everyday operations

```bash
systemctl status ramcove-api ramcove-controller ramcove-worker-1 ramcove-worker-2 ramcove-web
journalctl -u ramcove-api -f
sudo systemctl restart ramcove-api          # after pulling new code: also rebuild the web app
cd apps/web && npm run build && sudo systemctl restart ramcove-web
```

Reset the live demo to a clean state (local door only): `uv run ramcove-admin reset` and, optionally,
`uv run ramcove-admin scenario busy`. The running services pick the new state up by themselves.

## Rotating the proxy key

```bash
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/ramcove/proxy.key'
sudo sh -c 'umask 077; printf "if (\$http_x_ramcove_proxy_key != \"%s\") {\n    return 403;\n}\n" "$(cat /etc/ramcove/proxy.key)" > /etc/nginx/ramcove/proxy-key.conf'
sudo nginx -t && sudo systemctl reload nginx
# then set RAMCOVE_PROXY_KEY on the Vercel project to the new value and redeploy
```

Always run `nginx -t` on its own and reload only if it succeeds: the host serves other sites.

## Taking the public backend offline

`sudo rm /etc/nginx/sites-enabled/ramcove-api && sudo nginx -t && sudo systemctl reload nginx` closes the
door; the hosted site then shows that the API is unreachable. Removing `RAMCOVE_API_ORIGIN` from the Vercel
project and redeploying switches it to the read-only snapshot instead.

## What this is not

A public demonstration of a simulation. The chain, the payments, the randomness and the GPU measurement
are all simulated and labelled; no real tokens move. It is not a production deployment, has had no
external security review, and runs on a single host with no redundancy.
