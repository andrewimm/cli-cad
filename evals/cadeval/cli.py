"""cadeval command line.

  list                         tasks and splits
  selftest                     grade the reference solutions (validates the validators)
  prepare TASK DIR             create a workspace for a manual / external-agent attempt
  grade TASK DIR [--render]    grade a workspace or script
  run [--tasks a,b] [--split dev] [--attempts N] [--model M] [--visual] [--label L]
                               launch independent agents (Claude Code CLI) and grade them
  report RUN_DIR               (re)build summary.json / summary.md
  compare RUN_A RUN_B          compare two runs (baseline vs candidate)
  perf [--iterations N]        daemon vs standalone performance eval
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .tasks import EVALS, load_task, load_tasks


def prepared_solution(task) -> Path:
    """The reference solution, after running the task's selftest_commands in a scratch copy.

    Some checks grade workspace artifacts (e.g. renders an agent must produce); the
    commands recreate them without committing generated files.
    """
    import os
    import shutil
    import tempfile

    if not task.selftest_commands:
        return task.solution
    from cad.cli import main as cad_main
    from cad.engine import Engine

    tmp = Path(tempfile.mkdtemp(prefix=f"selftest-{task.id}-"))
    ws = tmp / "ws"
    shutil.copytree(task.solution, ws, ignore=shutil.ignore_patterns(".cad", "renders", "out"))
    old = os.environ.get("CAD_STATE_DIR")
    os.environ["CAD_STATE_DIR"] = str(tmp / "state")
    try:
        engine = Engine()
        for cmd in task.selftest_commands:
            code, out, err = cad_main(cmd, ws, engine)
            if code != 0:
                raise SystemExit(f"selftest command {' '.join(cmd)} failed for {task.id}: {err or out}")
    finally:
        if old is None:
            os.environ.pop("CAD_STATE_DIR", None)
        else:
            os.environ["CAD_STATE_DIR"] = old
    return ws


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="cadeval", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("selftest")
    s.add_argument("--render", action="store_true")
    s = sub.add_parser("prepare")
    s.add_argument("task")
    s.add_argument("dir")
    s = sub.add_parser("grade")
    s.add_argument("task")
    s.add_argument("path")
    s.add_argument("--render", metavar="DIR")
    s = sub.add_parser("run")
    s.add_argument("--tasks")
    s.add_argument("--split", default="dev", choices=["dev", "heldout", "all"])
    s.add_argument("--attempts", type=int, default=1)
    s.add_argument("--model", default="sonnet")
    s.add_argument("--max-turns", type=int, default=60)
    s.add_argument("--timeout", type=int, default=1800)
    s.add_argument("--budget-usd", type=float)
    s.add_argument("--parallel", type=int, default=2)
    s.add_argument("--visual", action="store_true", help="vision-model review of renders")
    s.add_argument("--label", default="")
    s.add_argument("--out", help="run directory (default eval-runs/<timestamp>-<label>)")
    s = sub.add_parser("report")
    s.add_argument("run_dir")
    s = sub.add_parser("compare")
    s.add_argument("a")
    s.add_argument("b")
    s = sub.add_parser("perf")
    s.add_argument("--iterations", type=int, default=5)
    s.add_argument("--out", default=str(EVALS.parent / "eval-runs" / "perf.json"))
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for t in load_tasks("all"):
            print(f"{t.id:<18} {t.split:<8} {t.category:<13} {len(t.checks)} checks  {t.title}")
    elif a.cmd == "selftest":
        from .grade import grade

        bad = 0
        for t in load_tasks("all"):
            if not t.solution:
                print(f"{t.id:<18} NO REFERENCE SOLUTION")
                bad += 1
                continue
            rd = EVALS.parent / "eval-runs" / "selftest" / t.id if a.render else None
            g = grade(t, prepared_solution(t), rd)
            status = "PASS" if g["passed"] else "FAIL"
            print(f"{t.id:<18} {status}  score={g['score']}")
            for c in g.get("checks", []):
                if not c["ok"]:
                    print("    ", json.dumps(c, default=str)[:400])
            if not g.get("built"):
                print("    ", g.get("error"))
            bad += not g["passed"]
        sys.exit(1 if bad else 0)
    elif a.cmd == "prepare":
        from .run import prepare

        t = load_task(EVALS / "tasks" / f"{a.task}.toml")
        d = Path(a.dir).resolve()
        ws, prompt = prepare(t, d)
        (ws / "AGENT_PROMPT.md").write_text(prompt)
        print(f"workspace: {ws}\nput {d / 'bin'} first on PATH so cad calls are logged; prompt in AGENT_PROMPT.md")
    elif a.cmd == "grade":
        from .grade import grade

        t = load_task(EVALS / "tasks" / f"{a.task}.toml")
        g = grade(t, Path(a.path), Path(a.render) if a.render else None)
        print(json.dumps(g, indent=2, default=str))
        sys.exit(0 if g["passed"] else 1)
    elif a.cmd == "run":
        from .run import run_batch

        ids = a.tasks.split(",") if a.tasks else None
        tasks = load_tasks(None if ids else a.split, ids)
        out = Path(a.out) if a.out else EVALS.parent / "eval-runs" / f"{time.strftime('%Y%m%d-%H%M%S')}{'-' + a.label if a.label else ''}"
        run_batch(tasks, out, attempts=a.attempts, model=a.model, max_turns=a.max_turns, timeout_s=a.timeout,
                  budget_usd=a.budget_usd, visual=a.visual, parallel=a.parallel, label=a.label)
        print((out / "summary.md").read_text())
    elif a.cmd == "report":
        from .report import write_report

        write_report(Path(a.run_dir))
        print((Path(a.run_dir) / "summary.md").read_text())
    elif a.cmd == "compare":
        from .report import compare

        print(compare(Path(a.a), Path(a.b)))
    elif a.cmd == "perf":
        from .perf import run_perf

        r = run_perf(a.iterations)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(r, indent=2))
        print(json.dumps(r, indent=2))
