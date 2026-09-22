"""Live progress from a running stage.

A long stage says where it is while it runs, so the queue and the public dashboard can show "2,300 of
4,000 questions answered" instead of only "evaluating". Events carry numbers, not sentences: the wording
belongs to whoever displays them, and a dropped event changes nothing but the display.
"""

from __future__ import annotations

from collections.abc import Callable

Reporter = Callable[[dict], None]


def send(on_progress: Reporter | None, step: str, **fields: object) -> None:
    if on_progress is not None:
        on_progress({"step": step, **fields})
