import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CAD_STATE_DIR", str(tmp_path / "state"))
    yield


@pytest.fixture
def bracket():
    from cad import Part

    p = Part("bracket")
    p.box(60, 40, 4, name="base")
    p.box(60, 4, 30, at=(0, 20, 4), align=("center", "max", "min"), name="wall")
    return p
