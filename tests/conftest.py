import json
import pathlib

import pytest
from room_protocol.rules import ProfileVersion

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def profile() -> ProfileVersion:
    return ProfileVersion.model_validate(
        json.loads((ROOT / "config/profiles/room-p1@1.0.0.json").read_text())
    )
