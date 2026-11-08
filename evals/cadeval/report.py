"""Aggregate attempts into summary.json / summary.md, and compare two runs."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def _load(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def collect(run_dir: Path) -> list[dict]:
    rows = []
    for g in sorted(run_dir.glob("*/a*/grade.json")):
        d = g.parent
        rows.append({
            "task": d.parent.name,
            "attempt": d.name,
            "grade": _load(g),
            "metrics": _load(d / "metrics.json") or {},
            "feedback": _load(d / "feedback.json"),
            "visual": _load(d / "visual.json"),
            "meta": _load(d / "meta.json") or {},
        })
    return rows


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.mean(xs), 3) if xs else None


def summarize(run_dir: Path) -> dict:
    rows = collect(run_dir)
    by_task: dict[str, list] = defaultdict(list)
    for r in rows:
        by_task[r["task"]].append(r)
    tasks = {}
    for t, rs in sorted(by_task.items()):
        failed_checks = Counter()
        for r in rs:
            for c in r["grade"].get("checks", []):
                if not c["ok"]:
                    failed_checks[c["type"] + (f":{c['part']}" if c.get("part") else "")] += 1
            if not r["grade"].get("built"):
                failed_checks["build:" + r["grade"].get("error", {}).get("code", "?")] += 1
        tasks[t] = {
            "attempts": len(rs),
            "pass_rate": _mean([1.0 if r["grade"]["passed"] else 0.0 for r in rs]),
            "mean_score": _mean([r["grade"]["score"] for r in rs]),
            "self_reported_success": _mean([1.0 if (r["feedback"] or {}).get("success") else 0.0 for r in rs if r["feedback"]]),
            "mean_cad_calls": _mean([r["metrics"].get("cad_calls") for r in rs]),
            "mean_builds": _mean([r["metrics"].get("builds") for r in rs]),
            "mean_failed_builds": _mean([r["metrics"].get("failed_builds") for r in rs]),
            "mean_render_inspections": _mean([r["metrics"].get("render_inspections") for r in rs]),
            "mean_doc_lookups": _mean([r["metrics"].get("doc_lookups") for r in rs]),
            "mean_turns": _mean([r["metrics"].get("turns") for r in rs]),
            "mean_duration_s": _mean([r["metrics"].get("duration_s") for r in rs]),
            "mean_cost_usd": _mean([r["metrics"].get("cost_usd") for r in rs]),
            "failed_checks": dict(failed_checks),
            "visual_overall_match": _mean([((r["visual"] or {}).get("verdict") or {}).get("overall_match") for r in rs]),
        }
    issues = Counter()
    issue_list = []
    errors = Counter()
    suggestions = []
    peeks = 0
    for r in rows:
        for code, n in (r["metrics"].get("errors") or {}).items():
            errors[code] += n
        peeks += r["metrics"].get("implementation_peeks", 0) or 0
        fb = r["feedback"] or {}
        for i in fb.get("issues", []) or []:
            issues[(i.get("category", "other"), i.get("severity", "?"))] += 1
            issue_list.append({"task": r["task"], **i})
        for s in fb.get("suggestions", []) or []:
            suggestions.append({"task": r["task"], "suggestion": s})
    overall = {
        "attempts": len(rows),
        "pass_rate": _mean([1.0 if r["grade"]["passed"] else 0.0 for r in rows]),
        "mean_score": _mean([r["grade"]["score"] for r in rows]),
        "self_reported_success": _mean([1.0 if (r["feedback"] or {}).get("success") else 0.0 for r in rows if r["feedback"]]),
        "overclaimed": sum(1 for r in rows if (r["feedback"] or {}).get("success") and not r["grade"]["passed"]),
        "mean_cad_calls": _mean([r["metrics"].get("cad_calls") for r in rows]),
        "mean_failed_builds": _mean([r["metrics"].get("failed_builds") for r in rows]),
        "mean_turns": _mean([r["metrics"].get("turns") for r in rows]),
        "mean_cost_usd": _mean([r["metrics"].get("cost_usd") for r in rows]),
        "total_cost_usd": round(sum(r["metrics"].get("cost_usd") or 0 for r in rows), 3),
        "implementation_peeks": peeks,
        "feedback_received": sum(1 for r in rows if r["feedback"]),
    }
    return {
        "run": _load(run_dir / "run.json"),
        "overall": overall,
        "tasks": tasks,
        "cad_errors": dict(errors.most_common()),
        "issue_categories": {f"{c}/{s}": n for (c, s), n in issues.most_common()},
        "issues": issue_list,
        "suggestions": suggestions,
    }


def write_report(run_dir: Path) -> dict:
    s = summarize(run_dir)
    (run_dir / "summary.json").write_text(json.dumps(s, indent=2, default=str))
    o = s["overall"]
    lines = [f"# Eval run {run_dir.name}", ""]
    if s["run"]:
        lines.append(f"model `{s['run'].get('model')}`, git `{s['run'].get('git')}`, label `{s['run'].get('label')}`\n")
    lines += [
        f"- attempts: {o['attempts']}, **pass rate {o['pass_rate']}**, mean check score {o['mean_score']}",
        f"- self-reported success {o['self_reported_success']} (over-claimed: {o['overclaimed']})",
        f"- mean cad calls {o['mean_cad_calls']}, mean failed builds {o['mean_failed_builds']}, mean turns {o['mean_turns']}",
        f"- cost: total ${o['total_cost_usd']} (mean ${o['mean_cost_usd']}); implementation peeks: {o['implementation_peeks']}",
        "",
        "| task | pass | score | cad calls | builds (failed) | render views read | doc lookups | turns | failed checks |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for t, d in s["tasks"].items():
        lines.append(f"| {t} | {d['pass_rate']} | {d['mean_score']} | {d['mean_cad_calls']} | {d['mean_builds']} ({d['mean_failed_builds']}) | "
                     f"{d['mean_render_inspections']} | {d['mean_doc_lookups']} | {d['mean_turns']} | {d['failed_checks'] or ''} |")
    rows = collect(run_dir)
    onb = [r for r in rows if "time_to_first_valid_model_s" in r["metrics"] or r["meta"].get("installed")]
    if onb:
        lines += ["", "## Onboarding timeline (seconds from agent start)", "",
                  "| attempt | pass | first cad call | first valid model | first export | agent total | cad cmds | shell cmds | doc lookups | API errors | export ok |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in onb:
            m = r["metrics"]
            lines.append(f"| {r['task']}/{r['attempt']} | {r['grade']['passed']} | {m.get('time_to_first_cad_s')} | "
                         f"{m.get('time_to_first_valid_model_s')} | {m.get('time_to_first_export_s')} | {m.get('duration_s')} | "
                         f"{m.get('cad_calls')} | {m.get('bash_commands')} | {m.get('doc_lookups')} | {m.get('api_errors')} "
                         f"{m.get('errors') or ''} | {m.get('export_succeeded')} |")
    lines += ["", "## cad error codes seen", ""] + [f"- {k}: {v}" for k, v in s["cad_errors"].items()]
    lines += ["", "## Feedback issues", ""] + [f"- [{i['task']}] {i.get('category')}/{i.get('severity')}: {i.get('description')}" for i in s["issues"]]
    lines += ["", "## Suggestions", ""] + [f"- [{x['task']}] {x['suggestion']}" for x in s["suggestions"]]
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n")
    return s


def compare(a: Path, b: Path) -> str:
    sa, sb = summarize(a), summarize(b)
    lines = [f"# Compare {a.name} -> {b.name}", "", "| metric | A | B |", "|---|---|---|"]
    for k in ("attempts", "pass_rate", "mean_score", "mean_cad_calls", "mean_failed_builds", "mean_turns", "mean_cost_usd", "overclaimed"):
        lines.append(f"| {k} | {sa['overall'].get(k)} | {sb['overall'].get(k)} |")
    lines += ["", "| task | pass A | pass B | score A | score B | failed builds A | failed builds B | cad calls A | cad calls B |", "|---|---|---|---|---|---|---|---|---|"]
    regress = []
    for t in sorted(set(sa["tasks"]) | set(sb["tasks"])):
        x, y = sa["tasks"].get(t, {}), sb["tasks"].get(t, {})
        lines.append(f"| {t} | {x.get('pass_rate')} | {y.get('pass_rate')} | {x.get('mean_score')} | {y.get('mean_score')} | "
                     f"{x.get('mean_failed_builds')} | {y.get('mean_failed_builds')} | {x.get('mean_cad_calls')} | {y.get('mean_cad_calls')} |")
        if x and y and (y.get("mean_score") or 0) < (x.get("mean_score") or 0):
            regress.append(t)
    lines += ["", f"regressions (lower mean score): {regress or 'none'}"]
    return "\n".join(lines)
