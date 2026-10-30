# Public demo: the hosted site and its live backend

The hosted site (https://ramcove.vercel.app) is the web app on Vercel. Everything behind it — the API,
PostgreSQL, the controller and two simulated workers — runs on the operator's host. Visitors see the same
live competition as the local stack. The site only reads: it has no sign-in, and taking part happens
from the command line (`ramcove-miner`, `ramcove-worker`, `ramcove-operator`), each with its own key.

```
browser ──HTTPS──▶ Vercel (Next.js server) ──HTTPS + proxy key──▶ nginx :8788 ──▶ API 127.0.0.1:8787
                                                                                   ├─ PostgreSQL (docker)
                                                                                   ├─ controller
                                                                                   └─ workers w-op-1, w-op-2
operator ──on the host──▶ ramcove-operator, ramcove-admin ────────────────────────▶ API (local door)
           ──SSH tunnel──▶ local site 127.0.0.1:3787 ──────────────────────────────▶ API (local door)
```

## Two doors, one database

| | Public door (hosted site) | Local door (the operator's host) |
|---|---|---|
| Reached through | nginx on port 8788, only with the proxy key | 127.0.0.1 on the host, or an SSH tunnel |
| Methods | `GET` and `HEAD` only; every write is refused | All |
| Sign-in, miner, demo routes | Refused (`local_only`) | Allowed; the command-line tools sign in with their key |
| Operator, review, appeal, validator, worker routes | Refused | Allowed by role |

nginx stamps every request on port 8788 with `X-RamCove-Channel: public` and strips the proxy key before
the API sees it, so a client cannot claim the local door. The rules live in
`services/api/ramcove_api/channel.py` and are covered by `tests/integration/test_public_channel.py`.

The hosted web app reads only on the server side (React Server Components); the browser never talks to
the API, so there is no proxy route to abuse.

`RAMCOVE_DEMO_AUTO_REVIEW_S` (120 s) lets a labelled stand-in reviewer approve passing submissions in the
demo; its recorded reason says it was automatic. Decide within that window to review yourself:
`uv run ramcove-operator --key-uri <reviewer key> reviews`, then `review <id> approve|reject`.

## What runs where

| Piece | Where | Managed by |
|---|---|---|
| API, controller, workers, local site | this repository on the host | systemd units in `infra/systemd/` |
| PostgreSQL | docker compose `infra/docker-compose.yml` | docker, `restart: unless-stopped` |
| nginx site | `infra/nginx/ramcove-api.conf` → `/etc/nginx/sites-available/ramcove-api` | nginx, on the host's Let's Encrypt IP certificate |
| Settings | `/etc/ramcove/ramcove.env` (from `infra/ramcove.env.example`) | root only |
| Proxy key | `/etc/ramcove/proxy.key` and `/etc/nginx/ramcove/proxy-key.conf` | root only, never in git |
| Hosted web app | Vercel team `analyzify360`, project `ramcove` | Vercel |

Vercel project environment (production): `RAMCOVE_API_ORIGIN=https://158.220.118.14:8788`,
`RAMCOVE_PROXY_KEY` (sensitive), `RAMCOVE_PUBLIC_ORIGIN=https://ramcove.vercel.app`. Without
`RAMCOVE_API_ORIGIN` the hosted site falls back to the read-only snapshot preview.

## The IP certificate

Vercel verifies the backend's certificate, so port 8788 needs a publicly trusted certificate for the host's
IP address. Let's Encrypt issues IP certificates only with its short-lived profile (about six days), which
needs Certbot 5 or newer, installed from the Snap Store (`snap install --classic certbot`). nginx's default
site serves the HTTP challenge from `/var/www/html` on port 80:

```bash
sudo certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
  --webroot -w /var/www/html --ip-address <host IP> --required-profile shortlived \
  --deploy-hook "systemctl reload nginx"
```

Certbot's timer (`snap.certbot.renew.timer`) renews it automatically and reloads nginx. Keep port 80 open
for the renewals.

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

## What the demo is

The RamCove subnet running in simulation mode for the public: the chain, the payments, the randomness and
the GPU workers are simulated and every number they produce is labelled. It runs on a single host; the
network deployment adds redundancy and the external security review listed in the readiness report.
