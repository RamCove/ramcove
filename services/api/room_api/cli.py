"""Local administration: migrate, seed, reset, export the OpenAPI document, run a controller tick."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from .config import ROOT, load_settings
from .main import build_context, create_app
from .services import seed as seed_svc
from .services.control import tick


def _alembic(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "services/api/migrations"))
    os.environ["ROOM_MIGRATE_URL"] = url
    return cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="room-admin", description="ROOM local administration")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations")
    sub.add_parser("seed", help="seed the labelled demo dataset (demo mode only)")
    sub.add_parser("reset", help="drop, migrate and reseed the demo dataset (demo mode only)")
    sub.add_parser("tick", help="run one controller tick")
    p_openapi = sub.add_parser("openapi", help="write the OpenAPI document")
    p_openapi.add_argument("--out", default=str(ROOT / "var/openapi.json"))
    args = parser.parse_args(argv)

    if args.cmd == "openapi":
        spec = create_app(build_context()).openapi()
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
        print(f"wrote {out} ({len(spec['paths'])} paths)")
        return 0

    settings = load_settings()
    if args.cmd == "migrate":
        command.upgrade(_alembic(settings.database_url), "head")
        print("database is at head")
        return 0

    ctx = build_context()
    if args.cmd == "seed":
        print(seed_svc.seed_base(ctx))
    elif args.cmd == "reset":
        seed_svc.reset_database(ctx)
        print(seed_svc.seed_base(ctx))
    elif args.cmd == "tick":
        print(tick(ctx))
    return 0


if __name__ == "__main__":
    sys.exit(main())
