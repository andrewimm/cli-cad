"""Launch independent coding agents on tasks and collect everything they do.

Each attempt gets:
  <run>/<task>/<attempt>/workspace/   the agent's working directory (TASK.md + any setup files)
  <run>/<task>/<attempt>/bin/cad      logging shim in front of the real `cad` (every call -> cad_calls.jsonl)
  transcript.jsonl                    raw agent event stream (Claude Code stream-json)
  feedback.json                       structured feedback the agent was asked to write
  grade.json, renders/                independent deterministic grading of the workspace
  metrics.json                        derived usage metrics
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .grade import grade
from .metrics import attempt_metrics
from .tasks import EVALS, Task

REPO = EVALS.parent
CAD_BIN = REPO / "target" / "release" / "cad"

FEEDBACK_INSTRUCTIONS = """
When you are finished (or if you give up), write a file named feedback.json in the current directory:

{
  "task": "<task id>",
  "success": true | false,              // your own judgement
  "issues": [
    {"category": "api_missing | api_confusing | error_unhelpful | docs_unclear | render_missing | query_missing | geometry_failure | workaround | other",
     "description": "...", "severity": "low | medium | high"}
  ],
  "suggestions": ["..."],
  "answers": {
    "difficult_operations": "Which operations were difficult or confusing?",
    "missing_apis": "Which APIs were missing?",
    "unhelpful_errors": "Which error messages were unhelpful?",
    "unclear_docs": "Which parts of the documentation were unclear?",
    "workarounds": "What workarounds did you need?",
    "missing_queries": "Which additional geometry queries would have helped?",
    "missing_rendering": "Which rendering capabilities were missing?",
    "would_help": "What would have made the task easier or more reliable?"
  }
}
Replace each question in "answers" with your answer. Be specific and candid; this feedback is used to improve the tool.
"""

AGENT_PROMPT = """You are an engineer using a command-line CAD tool called `cad` (Python scripts -> exact solid models).
Your job: complete the design request in TASK.md in the current directory.

Rules:
- Work only in the current directory. Deliver a cad project here: `cad.toml` + the model script, buildable with `cad build`.
- Learn the tool from its own documentation: `cad docs`, `cad --help`, `cad help <command>`, `cad capabilities`, `cad examples list` / `cad examples show <name>`.
- Do not read the source code of the cad package or its installation; use only the documentation, help and examples.
- Verify your design: check numbers with `cad inspect` / `cad measure` / `cad query`, and look at renders (`cad render`, then open the PNG files) before you finish.
{feedback}
"""

SHIM = r'''#!/usr/bin/env python3
import json, os, re, subprocess, sys, time
t = time.time()
p = subprocess.run([{real!r}] + sys.argv[1:], capture_output=True)
sys.stdout.buffer.write(p.stdout); sys.stdout.flush()
sys.stderr.buffer.write(p.stderr); sys.stderr.flush()
err = None
m = re.search(rb'error \[([A-Z_]+)\]', p.stderr) or re.search(rb'"code": "([A-Z_]+)"', p.stdout if p.returncode else b"")
if m: err = m.group(1).decode()
with open({log!r}, "a") as f:
    f.write(json.dumps({{"t": t, "argv": sys.argv[1:], "exit": p.returncode, "error": err,
                        "ms": round((time.time() - t) * 1000, 1), "cwd": os.getcwd()}}) + "\n")
sys.exit(p.returncode)
'''

_SESSION_VARS = ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
                 "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_PID",
                 "AI_AGENT", "CLAUDE_EFFORT", "CLAUDE_CODE_EXECPATH"]


def prepare(task: Task, attempt_dir: Path, with_feedback: bool = True) -> tuple[Path, str]:
    """Create the controlled workspace; returns (workspace, prompt)."""
    ws = attempt_dir / "workspace"
    if ws.exists():
        shutil.rmtree(ws)
    if task.setup_dir:
        shutil.copytree(task.setup_dir, ws)
    else:
        ws.mkdir(parents=True)
    (ws / "TASK.md").write_text(f"# {task.title}\n\nTask id: `{task.id}`\n\n{task.prompt}\n")
    bindir = attempt_dir / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    shim = bindir / "cad"
    shim.write_text(SHIM.format(real=str(CAD_BIN), log=str(attempt_dir / "cad_calls.jsonl")))
    shim.chmod(0o755)
    fb = FEEDBACK_INSTRUCTIONS.replace("<task id>", task.id) if with_feedback else ""
    return ws, AGENT_PROMPT.format(feedback=fb)


def agent_env(attempt_dir: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SESSION_VARS}
    env["PATH"] = f"{attempt_dir / 'bin'}:{env.get('PATH', '')}"
    # isolate daemon + state per attempt so attempts cannot see each other
    env["CAD_STATE_DIR"] = str(attempt_dir / "cadstate")
    env["CAD_RUNTIME_DIR"] = str(attempt_dir / "rt")
    env["CAD_PYTHON"] = str(REPO / ".venv" / "bin" / "python")
    env["CAD_DAEMON_IDLE_SECS"] = "120"
    return env


def run_attempt(task: Task, attempt_dir: Path, *, model: str, max_turns: int, timeout_s: int,
                budget_usd: float | None, visual: bool, agent_cmd: str = "claude") -> dict:
    attempt_dir.mkdir(parents=True, exist_ok=True)
    ws, prompt = prepare(task, attempt_dir)
    env = agent_env(attempt_dir)
    cmd = [agent_cmd, "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--max-turns", str(task.limits.get("max_turns", max_turns)), "--model", model,
           "--no-session-persistence",
           "--allowedTools", "Bash(cad:*)", "Bash(ls:*)", "Bash(cat:*)", "Read", "Write", "Edit", "Glob", "Grep"]
    if budget_usd:
        cmd += ["--max-budget-usd", str(budget_usd)]
    meta = {"task": task.id, "model": model, "agent": agent_cmd, "max_turns": max_turns, "started": time.time(),
            "cad_bin": str(CAD_BIN)}
    t0 = time.time()
    with open(attempt_dir / "transcript.jsonl", "w") as tr, open(attempt_dir / "agent_stderr.log", "w") as er:
        try:
            p = subprocess.run(cmd, cwd=ws, env=env, stdout=tr, stderr=er, timeout=task.limits.get("timeout_s", timeout_s))
            meta["agent_exit"] = p.returncode
        except subprocess.TimeoutExpired:
            meta["agent_exit"] = "timeout"
    meta["wall_s"] = round(time.time() - t0, 1)
    subprocess.run([str(CAD_BIN), "daemon", "stop"], env=env, capture_output=True)
    fb_path = ws / "feedback.json"
    if fb_path.exists():
        try:
            fb = json.loads(fb_path.read_text())
            (attempt_dir / "feedback.json").write_text(json.dumps(fb, indent=2))
            meta["feedback"] = "ok"
        except json.JSONDecodeError as e:
            meta["feedback"] = f"invalid json: {e}"
            shutil.copy(fb_path, attempt_dir / "feedback.raw.txt")
    else:
        meta["feedback"] = "missing"
    g = grade(task, ws, attempt_dir / "renders")
    (attempt_dir / "grade.json").write_text(json.dumps(g, indent=2, default=str))
    m = attempt_metrics(attempt_dir)
    (attempt_dir / "metrics.json").write_text(json.dumps(m, indent=2))
    if visual and g.get("renders"):
        from .visual import visual_review

        v = visual_review(task, g["renders"], attempt_dir, agent_cmd=agent_cmd)
        (attempt_dir / "visual.json").write_text(json.dumps(v, indent=2))
    (attempt_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    return {"task": task.id, "passed": g["passed"], "score": g["score"], "metrics": m, "meta": meta}


def run_batch(tasks: list[Task], run_dir: Path, *, attempts: int, model: str, max_turns: int, timeout_s: int,
              budget_usd: float | None, visual: bool, parallel: int = 1, label: str = "") -> Path:
    from concurrent.futures import ThreadPoolExecutor

    if not CAD_BIN.exists():
        sys.exit(f"{CAD_BIN} not found: run `cargo build --release` first")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "label": label, "model": model, "attempts": attempts, "tasks": [t.id for t in tasks],
        "git": _git_rev(), "started": time.time()}, indent=2))
    jobs = [(t, run_dir / t.id / f"a{i + 1}") for t in tasks for i in range(attempts)]

    def go(job):
        t, d = job
        print(f"[cadeval] start {t.id} {d.name}", flush=True)
        r = run_attempt(t, d, model=model, max_turns=max_turns, timeout_s=timeout_s, budget_usd=budget_usd, visual=visual)
        print(f"[cadeval] done  {t.id} {d.name}: passed={r['passed']} score={r['score']} "
              f"cad_calls={r['metrics'].get('cad_calls')} turns={r['metrics'].get('turns')}", flush=True)
        return r

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as ex:
        list(ex.map(go, jobs))
    from .report import write_report

    write_report(run_dir)
    return run_dir


def _git_rev() -> str:
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"
