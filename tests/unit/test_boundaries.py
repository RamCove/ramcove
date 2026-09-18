"""The protocol core must stay pure: no HTTP, no database, no chain SDK, no filesystem side effects.

This is the boundary docs/adr/0001-monorepo-and-boundaries.md sets. It is checked by reading the imports, so it cannot drift quietly.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "packages/protocol/ramcove_protocol"
EVALUATOR = ROOT / "packages/evaluator/ramcove_evaluator"

FORBIDDEN_IN_PROTOCOL = {
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "substrateinterface",
    "scalecodec",
    "httpx",
    "requests",
    "ramcove_api",
    "ramcove_chain",
    "ramcove_evaluator",
    "ramcove_worker",
    "ramcove_miner",
}
FORBIDDEN_IN_EVALUATOR = {
    "fastapi",
    "starlette",
    "uvicorn",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "substrateinterface",
    "ramcove_api",
    "ramcove_worker",
}


def top_level_imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_protocol_has_no_infrastructure_imports():
    offenders = {}
    for path in PROTOCOL.rglob("*.py"):
        bad = top_level_imports(path) & FORBIDDEN_IN_PROTOCOL
        if bad:
            offenders[path.name] = sorted(bad)
    assert offenders == {}, offenders


def test_evaluator_depends_only_on_the_protocol():
    offenders = {}
    for path in EVALUATOR.rglob("*.py"):
        bad = top_level_imports(path) & FORBIDDEN_IN_EVALUATOR
        if bad:
            offenders[path.name] = sorted(bad)
    assert offenders == {}, offenders


def test_protocol_modules_do_not_touch_the_filesystem():
    """Rules must come from a passed-in profile version, never from an ambient file.

    ``tarfile.open(fileobj=...)`` is allowed: preflight parses an in-memory buffer, not a path.
    """
    offenders = {}
    for path in PROTOCOL.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        bad = set()
        bad |= top_level_imports(path) & {"pathlib", "os", "shutil", "tempfile", "glob", "subprocess"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                bad.add("open()")
        if bad:
            offenders[path.name] = sorted(bad)
    assert offenders == {}, offenders
