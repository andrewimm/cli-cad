"""Declarative task definitions (evals/tasks/*.toml)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

EVALS = Path(__file__).resolve().parents[1]
TASK_DIR = EVALS / "tasks"
SOLUTION_DIR = EVALS / "solutions"


@dataclass
class Task:
    id: str
    title: str
    category: str
    split: str
    prompt: str
    checks: list[dict]
    setup_dir: Path | None = None
    limits: dict = field(default_factory=dict)
    path: Path | None = None
    selftest_commands: list[list[str]] = field(default_factory=list)
    grade_overrides: dict = field(default_factory=dict)
    install: str = "dev"                     # "isolated": run against a fresh install (wheel + binaries), not the repo
    prompt_style: str = "standard"           # "minimal": only say that a `cad` CLI is installed
    feedback_questions: dict = field(default_factory=dict)

    @property
    def solution(self) -> Path | None:
        d = SOLUTION_DIR / self.id
        if (d / "cad.toml").exists():
            return d
        f = SOLUTION_DIR / f"{self.id}.py"
        return f if f.exists() else None


def load_task(path: Path) -> Task:
    raw = tomllib.loads(path.read_text())
    setup = raw.get("setup_dir")
    return Task(
        id=raw["id"],
        title=raw.get("title", raw["id"]),
        category=raw.get("category", "general"),
        split=raw.get("split", "dev"),
        prompt=raw["prompt"].strip(),
        checks=raw.get("checks", []),
        setup_dir=(path.parent / setup) if setup else None,
        limits=raw.get("limits", {}),
        path=path,
        selftest_commands=[c.split() for c in raw.get("selftest_commands", [])],
        grade_overrides=raw.get("grade_overrides", {}),
        install=raw.get("install", "dev"),
        prompt_style=raw.get("prompt_style", "standard"),
        feedback_questions=raw.get("feedback_questions", {}),
    )


def load_tasks(split: str | None = None, ids: list[str] | None = None) -> list[Task]:
    tasks = [load_task(p) for p in sorted(TASK_DIR.glob("*.toml"))]
    if ids:
        missing = set(ids) - {t.id for t in tasks}
        if missing:
            raise SystemExit(f"unknown task(s): {sorted(missing)}")
        tasks = [t for t in tasks if t.id in ids]
    if split and split != "all":
        tasks = [t for t in tasks if t.split == split]
    return tasks
