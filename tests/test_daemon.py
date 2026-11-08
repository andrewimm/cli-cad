"""Integration tests for the Rust client + daemon (skipped if not built: `cargo build --release`)."""
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CAD = ROOT / "target" / "release" / "cad"
pytestmark = pytest.mark.skipif(not CAD.exists(), reason="cad binary not built")


@pytest.fixture
def env(tmp_path):
    e = dict(os.environ)
    e["CAD_STATE_DIR"] = str(tmp_path / "state")
    e["CAD_RUNTIME_DIR"] = str(tmp_path / "rt")
    e["CAD_PYTHON"] = str(ROOT / ".venv" / "bin" / "python")
    yield e
    subprocess.run([CAD, "daemon", "stop"], env=e, capture_output=True)


def cad(args, cwd, env, check=True):
    p = subprocess.run([str(CAD), *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    if check and p.returncode != 0:
        raise AssertionError(f"cad {args} -> {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


def test_daemon_session_and_recovery(tmp_path, env):
    cad(["examples", "copy", "plate_with_holes", "proj"], tmp_path, env)
    proj = tmp_path / "proj"
    r = json.loads(cad(["build", "--json"], proj, env).stdout)
    assert r["ok"] and r["result"]["revision"] == 1
    # warm commands are served by the same worker
    t = time.perf_counter()
    r = json.loads(cad(["inspect", "--json"], proj, env).stdout)
    warm = time.perf_counter() - t
    assert r["result"]["parts"]["plate"]["valid"]
    assert warm < 1.0
    st = json.loads(cad(["daemon", "status", "--json"], proj, env).stdout)["result"]
    w = [w for w in st["workers"] if w["session"].endswith("proj")][0]
    assert w["requests"] >= 2
    # kill the worker: the next command transparently gets a new one with the same revision
    os.kill(w["pid"], signal.SIGKILL)
    time.sleep(0.2)
    r = json.loads(cad(["inspect", "--json"], proj, env).stdout)
    assert r["result"]["revision"] == 1
    st = json.loads(cad(["daemon", "status", "--json"], proj, env).stdout)["result"]
    w2 = [w for w in st["workers"] if w["session"].endswith("proj")][0]
    assert w2["pid"] != w["pid"] and w2["restarts"] == 1


def test_standalone_matches_daemon(tmp_path, env):
    cad(["examples", "copy", "shaft_coupler", "proj"], tmp_path, env)
    proj = tmp_path / "proj"
    cad(["build"], proj, env)
    a = json.loads(cad(["inspect", "--json"], proj, env).stdout)["result"]["parts"]
    b = json.loads(cad(["--no-daemon", "inspect", "--json"], proj, env).stdout)["result"]["parts"]
    assert a == b


def test_error_exit_codes_through_daemon(tmp_path, env):
    p = cad(["inspect", "--json"], tmp_path, env, check=False)
    assert p.returncode == 5 and json.loads(p.stdout)["error"]["code"] == "NO_PROJECT"


def test_falls_back_to_standalone_when_daemon_cannot_start(tmp_path, env):
    # a runtime dir that cannot be created stands in for a sandbox that forbids the daemon's socket
    env = dict(env, CAD_RUNTIME_DIR="/dev/null/cad-runtime")
    p = cad(["capabilities", "--json"], tmp_path, env, check=False)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["ok"]
    assert "running standalone" in p.stderr
    env["CAD_REQUIRE_DAEMON"] = "1"
    p = cad(["capabilities", "--json"], tmp_path, env, check=False)
    assert p.returncode == 8 and json.loads(p.stdout)["error"]["code"] == "DAEMON_UNAVAILABLE"
