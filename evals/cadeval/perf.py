"""Performance eval: daemon-backed vs standalone execution.

Measures cold start, warm latency per command, build / render (cached and
uncached) / query latency, cache hit counters, worker memory, and worker
crash-recovery time, plus a representative agent workflow end to end.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from .run import CAD_BIN, REPO, _SESSION_VARS


def _env(tmp: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SESSION_VARS}
    env.update(CAD_STATE_DIR=str(tmp / "state"), CAD_RUNTIME_DIR=str(tmp / "rt"),
               CAD_PYTHON=str(REPO / ".venv" / "bin" / "python"))
    return env


def _t(args, cwd, env) -> tuple[float, subprocess.CompletedProcess]:
    t = time.perf_counter()
    p = subprocess.run([str(CAD_BIN), *args], cwd=cwd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"cad {args} failed: {p.stderr}")
    return (time.perf_counter() - t) * 1000, p


def _med(xs):
    return round(statistics.median(xs), 1)


WORKFLOW = [
    ["build"], ["inspect"], ["render", "--views", "iso,front"], ["measure", "--bbox"],
    ["query", "edges().concave()"], ["set", "wall_height", "40"], ["render", "--views", "iso,front"],
    ["render", "--views", "az=210,el=30"], ["measure", "--holes"], ["unset", "wall_height"], ["render", "--views", "iso"],
]


def run_perf(iterations: int = 5) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="cadperf"))
    env = _env(tmp)
    res: dict = {"iterations": iterations, "machine": os.uname().machine}
    subprocess.run([str(CAD_BIN), "examples", "copy", "mounting_bracket", "proj", "--no-daemon"], cwd=tmp, env=env, capture_output=True)
    proj = tmp / "proj"

    # --- standalone
    sa: dict[str, list] = {}
    _t(["--no-daemon", "build"], proj, env)
    for _ in range(iterations):
        for name, args in [("inspect", ["inspect"]), ("measure", ["measure", "--volume"]), ("build_cached", ["build"]),
                           ("render_cached", ["render", "--views", "iso"]), ("query", ["query", "faces().holes()"])]:
            sa.setdefault(name, []).append(_t(["--no-daemon", *args], proj, env)[0])
    res["standalone_ms"] = {k: _med(v) for k, v in sa.items()}

    # --- daemon cold start (daemon + worker spawn + first command)
    subprocess.run([str(CAD_BIN), "daemon", "stop"], env=env, capture_output=True)
    res["daemon_cold_start_ms"] = round(_t(["inspect"], proj, env)[0], 1)
    dm: dict[str, list] = {}
    for _ in range(iterations):
        for name, args in [("inspect", ["inspect"]), ("measure", ["measure", "--volume"]), ("build_cached", ["build"]),
                           ("render_cached", ["render", "--views", "iso"]), ("query", ["query", "faces().holes()"]),
                           ("status", ["status"])]:
            dm.setdefault(name, []).append(_t(args, proj, env)[0])
    res["daemon_warm_ms"] = {k: _med(v) for k, v in dm.items()}

    # full (forced) build and uncached render, warm daemon
    res["daemon_full_build_ms"] = _med([_t(["build", "--force"], proj, env)[0] for _ in range(max(2, iterations // 2))])
    unc = []
    for i in range(iterations):
        unc.append(_t(["render", "--views", f"az={17 * i + 3},el=25"], proj, env)[0])
    res["daemon_uncached_render_ms_per_view"] = _med(unc)
    res["standalone_uncached_render_ms_per_view"] = _med([
        _t(["--no-daemon", "render", "--views", f"az={11 * i + 200},el=40"], proj, env)[0] for i in range(max(2, iterations // 2))])

    st = json.loads(_t(["daemon", "status", "--json"], proj, env)[1].stdout)["result"]
    w = [x for x in st["workers"] if x["session"].endswith("proj")][0]
    res["worker_max_rss_mb"] = round((w.get("max_rss_kb") or 0) / 1024, 1)
    res["cache_stats"] = w.get("stats")

    # crash recovery: kill the worker, time the next command
    os.kill(w["pid"], signal.SIGKILL)
    time.sleep(0.1)
    res["worker_recovery_ms"] = round(_t(["inspect"], proj, env)[0], 1)

    # representative agent workflow
    def workflow(prefix):
        shutil.rmtree(proj / ".cad", ignore_errors=True)
        t = time.perf_counter()
        for args in WORKFLOW:
            _t([*prefix, *args], proj, env)
        return round((time.perf_counter() - t) * 1000, 1)

    res["workflow_steps"] = [" ".join(a) for a in WORKFLOW]
    res["workflow_standalone_ms"] = workflow(["--no-daemon"])
    res["workflow_daemon_ms"] = workflow([])
    res["workflow_speedup"] = round(res["workflow_standalone_ms"] / res["workflow_daemon_ms"], 2)
    subprocess.run([str(CAD_BIN), "daemon", "stop"], env=env, capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return res
