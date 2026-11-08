"""Crash-isolated, deterministic stress-test harness.

A *case* is a dict with an ``id``, the suite name, the input classification
(``expect``: "valid" | "ambiguous" | "infeasible") and ``code``: a
self-contained Python snippet that sets ``result`` (a dict of measurements).
Because the code is the case, the reproduction of any failure is exactly the
code that failed.

Cases run in worker processes.  Each worker reports ``start`` before and
``done`` after every case; if a worker dies (a kernel segfault) or exceeds the
per-case timeout, the case in flight is recorded as ``crash`` / ``timeout`` and a
fresh worker continues with the remaining cases.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import platform
import queue
import resource
import sys
import time
import traceback
from pathlib import Path
from typing import Callable

PRELUDE = """\
import math, time
from cad import CadError, Part, Profile, Plane, _occ
"""


def _run_one(case: dict) -> dict:
    """Execute one case in this process; never raises."""
    env: dict = {}
    t0 = time.perf_counter()
    try:
        exec(compile(PRELUDE + case["code"], f"<case {case['id']}>", "exec"), env)
        res = env.get("result", {})
        out = {"status": "ran", "result": res}
    except Exception as e:  # the case code itself is expected to catch CadError where meaningful
        out = {"status": "exception", "exception": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-3000:]}
    out["wall_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return out


def _worker(cases: list[dict], q) -> None:
    sys.setrecursionlimit(10000)
    for case in cases:
        q.put(("start", case["id"], time.time()))
        out = _run_one(case)
        out["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
        q.put(("done", case["id"], out))


def run_cases(cases: list[dict], *, workers: int = 4, timeout_s: float = 120.0, fresh_process: bool = False,
              progress: Callable[[int, int], None] | None = None) -> dict[str, dict]:
    """Run cases across worker processes; returns {case_id: outcome}.

    ``fresh_process=True`` runs every case in its own process (clean peak-memory numbers).
    """
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    pending = list(cases)
    by_id = {c["id"]: c for c in cases}
    results: dict[str, dict] = {}
    chunk = 1 if fresh_process else max(1, min(40, len(cases) // (workers * 4) or 1))
    active: dict[int, dict] = {}  # pid -> {"proc", "cases", "current", "started"}
    startup_failures = [0]

    def spawn():
        batch, rest = pending[:chunk], pending[chunk:]
        pending[:] = rest
        p = ctx.Process(target=_worker, args=(batch, q), daemon=True)
        p.start()
        active[p.pid] = {"proc": p, "cases": [c["id"] for c in batch], "current": None, "started": None}

    while pending and len(active) < workers:
        spawn()
    pid_of_case = {}
    while active:
        try:
            msg = q.get(timeout=0.5)
        except queue.Empty:
            msg = None
        if msg:
            kind, cid, payload = msg
            for pid, w in active.items():
                if cid in w["cases"]:
                    pid_of_case[cid] = pid
                    if kind == "start":
                        w["current"], w["started"] = cid, time.time()
                    else:
                        results[cid] = payload
                        w["current"] = None
                    break
            if progress and kind == "done":
                progress(len(results), len(cases))
        now = time.time()
        for pid, w in list(active.items()):
            p = w["proc"]
            cur = w["current"]
            timed_out = cur is not None and now - w["started"] > by_id[cur].get("timeout_s", timeout_s)
            if timed_out:
                p.kill()
                p.join()
            if not p.is_alive():
                # drain any messages already queued by this worker before judging
                try:
                    while True:
                        kind, cid, payload = q.get_nowait()
                        if kind == "done":
                            results[cid] = payload
                            if w["current"] == cid:
                                w["current"] = None
                        elif kind == "start":
                            w["current"], w["started"] = cid, time.time()
                except queue.Empty:
                    pass
                cur = w["current"]
                if cur is not None and cur not in results:
                    results[cur] = {"status": "timeout" if timed_out else "crash",
                                    "exitcode": p.exitcode, "wall_ms": round((now - (w["started"] or now)) * 1000, 1)}
                # cases of this worker that never started go back to the queue
                unstarted = [c for c in w["cases"] if c not in results and c != cur]
                ran_any = any(c in results for c in w["cases"])
                if not ran_any and cur is None and p.exitcode != 0:
                    startup_failures[0] += 1
                if startup_failures[0] >= 3:  # workers cannot start at all: stop instead of respawning forever
                    for c in unstarted + [x["id"] for x in pending]:
                        results[c] = {"status": "crash", "exitcode": p.exitcode,
                                      "note": "worker process failed to start (run the harness via `python -m cadstress`)"}
                    pending.clear()
                    unstarted = []
                pending[:0] = [by_id[c] for c in unstarted]
                del active[pid]
                while pending and len(active) < workers:
                    spawn()
    return results


def environment() -> dict:
    import cad

    try:
        from importlib.metadata import version

        ocp = version("cadquery-ocp")
    except Exception:
        ocp = "?"
    return {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
            "cpus": os.cpu_count(), "cad": cad.__version__, "ocp": ocp}


def write_outputs(out_dir: Path, suite: str, cases: list[dict], outcomes: dict[str, dict],
                  judge: Callable[[dict, dict], dict], minimize: Callable[[dict, dict], dict | None] | None = None,
                  meta: dict | None = None) -> dict:
    """Judge every outcome, write results.jsonl, failing repros and the summary."""
    from collections import Counter, defaultdict

    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in cases:
        o = outcomes.get(c["id"], {"status": "missing"})
        verdict = judge(c, o)
        rows.append({"id": c["id"], "category": c.get("category"), "expect": c.get("expect"), "params": c.get("params"),
                     "outcome": o, "verdict": verdict})
    with open(out_dir / "results.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")
    defects = [r for r in rows if r["verdict"]["class"] == "defect"]
    fail_dir = out_dir / "failures"
    for r in defects:
        c = next(x for x in cases if x["id"] == r["id"])
        d = fail_dir / r["id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "case.json").write_text(json.dumps({k: v for k, v in r.items()}, indent=2, default=str))
        repro = PRELUDE + c["code"] + "\nprint(result)\n"
        (d / "repro.py").write_text(f"# {suite} case {c['id']} ({c.get('category')}, input: {c.get('expect')})\n"
                                    f"# verdict: {r['verdict']}\n# run: uv run python {d / 'repro.py'}\n" + repro)
        if minimize:
            m = minimize(c, r["outcome"])
            if m:
                (d / "minimal_repro.py").write_text(f"# minimal reproduction of {c['id']}: {m.get('note', '')}\n"
                                                    + PRELUDE + m["code"] + "\nprint(result)\n")
    by_cat: dict = defaultdict(Counter)
    kinds = Counter()
    for r in rows:
        by_cat[r["category"]][r["verdict"]["class"]] += 1
        for k in r["verdict"].get("kinds", []):
            kinds[(r["verdict"]["class"], k)] += 1
    summary = {
        "suite": suite,
        "cases": len(rows),
        "classes": dict(Counter(r["verdict"]["class"] for r in rows)),
        "by_category": {k: dict(v) for k, v in sorted(by_cat.items())},
        "kinds": {f"{c}:{k}": n for (c, k), n in kinds.most_common()},
        "defect_ids": [r["id"] for r in defects][:200],
        "env": environment(),
        **(meta or {}),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
