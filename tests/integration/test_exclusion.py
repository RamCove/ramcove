"""Section 9.6: an excluded hotkey is refused in the free checks, so it is never charged.

Exclusion is an operator remedy for copying and spam. It is published in the audit log with its reason,
and it is reversible.
"""

from __future__ import annotations

import pytest
from ramcove_api.store.db import tx
from ramcove_api.store.schema import settings as settings_t
from sqlalchemy import insert, update

from .helpers import hotkey, make_ctx, submit_fixture

pytestmark = pytest.mark.db


@pytest.fixture
def ctx(tmp_path):
    return make_ctx(tmp_path)


def _exclude(ctx, key: str, reason: str) -> None:
    hk, _ = hotkey(key)
    with tx(ctx.engine) as conn:
        conn.execute(
            insert(settings_t).values(
                key="excluded_hotkeys",
                value={"hotkeys": {hk: reason}},
                updated_by="operator",
                reason=reason,
            )
        )


def test_an_excluded_hotkey_is_refused_at_the_free_checks(ctx):
    _exclude(ctx, "miner-cyd", "repeated cosmetic copies of another miner's patch")
    out = submit_fixture(ctx, "miner-cyd", "fragmentation-aware-allocator")
    assert not out["ok"]
    codes = {e["code"] for e in out["errors"]}
    assert "hotkey_excluded" in codes
    assert any("cosmetic copies" in e["message"] for e in out["errors"])
    assert out["free"] is True

    # everyone else is unaffected
    assert submit_fixture(ctx, "miner-ada", "kv8-conversation-retention")["ok"]


def test_reinstating_a_hotkey_lets_it_submit_again(ctx):
    _exclude(ctx, "miner-cyd", "spam")
    assert not submit_fixture(ctx, "miner-cyd", "fragmentation-aware-allocator")["ok"]
    hk, _ = hotkey("miner-cyd")
    with tx(ctx.engine) as conn:
        assert (ctx.setting(conn, "excluded_hotkeys") or {})["hotkeys"][hk] == "spam"
        conn.execute(
            update(settings_t).where(settings_t.c.key == "excluded_hotkeys").values(value={"hotkeys": {}})
        )
    assert submit_fixture(ctx, "miner-cyd", "fragmentation-aware-allocator", variant=1)["ok"]
