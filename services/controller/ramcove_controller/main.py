"""Controller loop: advances the simulated chain, verifies payments, expires leases, settles promotions.

Runs as its own process. Safe to restart: every step is transactional and resumes from durable state.
"""

from __future__ import annotations

import logging
import os
import signal
import time

from ramcove_api.main import build_context
from ramcove_api.services.control import tick

log = logging.getLogger("ramcove.controller")
_stop = False


def _handle(signum, _frame):  # noqa: ANN001
    global _stop
    _stop = True
    log.info("signal %s received; finishing the current tick and stopping", signum)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    ctx = build_context()
    interval = float(os.environ.get("RAMCOVE_CONTROLLER_INTERVAL_S", "2"))
    log.info(
        "controller started env=%s network=%s simulated=%s",
        ctx.settings.env,
        ctx.settings.network,
        ctx.settings.simulated_chain,
    )
    while not _stop:
        started = time.monotonic()
        try:
            out = tick(ctx)
            interesting = {k: v for k, v in out.items() if v not in (0, [], None)}
            if interesting:
                log.info("tick %s", interesting)
        except Exception:  # noqa: BLE001 - keep the loop alive; the error is logged with a traceback
            log.exception("tick failed; retrying after the interval")
        time.sleep(max(0.0, interval - (time.monotonic() - started)))
    log.info("controller stopped")


if __name__ == "__main__":
    run()
