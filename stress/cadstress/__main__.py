"""cadstress — geometry stress tests that drive the cad API directly (no agent).

    uv run python -m cadstress run S01 [--cases 1000] [--seed 1] [--workers 8]
    uv run python -m cadstress run all
    uv run python -m cadstress report <run_dir>

Run from the repository root with PYTHONPATH=stress (or `cd stress`).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITES = {
    "S01": ("s01_boolean", 1000),
    "S02": ("s02_fillet", 500),
    "S03": ("s03_scale", None),
    "S04": ("s04_repeated", None),
    "S05": ("s05_mutation", 200),
}


def run_suite(name: str, n: int | None, seed: int, workers: int, out_root: Path) -> Path:
    from .harness import run_cases, write_outputs
    from .report import write_markdown

    mod = importlib.import_module(f".{SUITES[name][0]}", __package__)
    n = n or SUITES[name][1]
    out = out_root / f"{name}-seed{seed}-{time.strftime('%Y%m%d-%H%M%S')}"
    t0 = time.time()
    if hasattr(mod, "run"):  # suites with their own driver (e.g. S05 drives the daemon)
        summary = mod.run(out, n=n, seed=seed, workers=workers)
    else:
        cases = mod.generate(n, seed) if n else mod.generate(seed=seed)
        print(f"[{name}] {len(cases)} cases, {workers} workers -> {out}", flush=True)
        last = [0.0]

        def progress(done, total):
            if time.time() - last[0] > 5 or done == total:
                last[0] = time.time()
                print(f"[{name}] {done}/{total}", flush=True)

        outcomes = run_cases(cases, workers=workers, progress=progress, fresh_process=getattr(mod, "FRESH_PROCESS", False),
                             timeout_s=getattr(mod, "TIMEOUT_S", 120))
        summary = write_outputs(out, name, cases, outcomes, mod.judge, getattr(mod, "minimize", None),
                                meta={"seed": seed, "workers": workers, "wall_s": round(time.time() - t0, 1)})
        if hasattr(mod, "analyze"):
            summary["analysis"] = mod.analyze(cases, outcomes)
            (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    write_markdown(out, summary)
    print((out / "summary.md").read_text())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cadstress")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("suite", help="S01..S05 or all")
    r.add_argument("--cases", type=int)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--out", default=str(ROOT / "stress-runs"))
    rp = sub.add_parser("report")
    rp.add_argument("run_dir")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        names = list(SUITES) if a.suite == "all" else [a.suite.upper()]
        for nme in names:
            if nme not in SUITES:
                sys.exit(f"unknown suite {nme}")
            run_suite(nme, a.cases, a.seed, a.workers, Path(a.out))
    else:
        from .report import write_markdown

        d = Path(a.run_dir)
        write_markdown(d, json.loads((d / "summary.json").read_text()))
        print((d / "summary.md").read_text())


if __name__ == "__main__":
    main()
