"""Markdown summaries for stress runs."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path


def _timing_table(out_dir: Path) -> list[str]:
    """Per-category timing (median / p95 / max of case wall time)."""
    per = defaultdict(list)
    p = out_dir / "results.jsonl"
    if not p.exists():
        return []
    for line in p.read_text().splitlines():
        r = json.loads(line)
        if "wall_ms" in r["outcome"]:
            per[r["category"]].append(r["outcome"]["wall_ms"])
    if not per:
        return []
    lines = ["", "| category | cases | median ms | p95 ms | max ms |", "|---|---|---|---|---|"]
    for cat, xs in sorted(per.items()):
        xs.sort()
        p95 = xs[min(len(xs) - 1, int(0.95 * len(xs)))]
        lines.append(f"| {cat} | {len(xs)} | {statistics.median(xs):.1f} | {p95:.1f} | {xs[-1]:.1f} |")
    return lines


def write_markdown(out_dir: Path, s: dict) -> None:
    lines = [f"# {s['suite']} stress run", ""]
    env = s.get("env", {})
    lines.append(f"seed {s.get('seed')}, {s.get('cases')} cases, {s.get('workers')} workers, {s.get('wall_s')} s; "
                 f"cad {env.get('cad')}, OCP {env.get('ocp')}, {env.get('platform')}")
    lines += ["", "**Outcome classes:** " + ", ".join(f"{k} {v}" for k, v in sorted(s.get("classes", {}).items())), ""]
    if s.get("by_category"):
        classes = sorted({c for v in s["by_category"].values() for c in v})
        lines += ["| category | " + " | ".join(classes) + " |", "|---|" + "---|" * len(classes)]
        for cat, v in s["by_category"].items():
            lines.append(f"| {cat} | " + " | ".join(str(v.get(c, 0)) for c in classes) + " |")
    if s.get("kinds"):
        lines += ["", "**Findings by kind:**", ""] + [f"- {k}: {v}" for k, v in s["kinds"].items()]
    lines += _timing_table(out_dir)
    if s.get("analysis"):
        lines += ["", "## Analysis", "", "```json", json.dumps(s["analysis"], indent=2, default=str)[:12000], "```"]
    if s.get("defect_ids"):
        lines += ["", f"Defect reproductions: `failures/<id>/repro.py` (and `minimal_repro.py` where reduced) for "
                  f"{len(s['defect_ids'])} case(s), e.g. {', '.join(s['defect_ids'][:8])}"]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")
