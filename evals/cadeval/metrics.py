"""Derive usage metrics from an attempt's cad call log and agent transcript."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

DOC_COMMANDS = {"docs", "help", "capabilities", "examples", "schema", "--help", "-h"}
PEEK = re.compile(r"(site-packages/cad|/src/cad/|clicd/src|cli-cad/src|cad/part\.py|cad/engine\.py)")


def _cmd(argv: list[str]) -> str:
    for a in argv:
        if not a.startswith("-") or a in ("--help", "-h", "--version"):
            return a
    return ""


def attempt_metrics(d: Path) -> dict:
    m: dict = {}
    calls = []
    p = d / "cad_calls.jsonl"
    if p.exists():
        calls = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    cmds = Counter(_cmd(c["argv"]) for c in calls)
    m["cad_calls"] = len(calls)
    m["cad_commands"] = dict(cmds)
    m["builds"] = cmds.get("build", 0) + cmds.get("run", 0) + cmds.get("set", 0)
    m["failed_builds"] = sum(1 for c in calls if _cmd(c["argv"]) in ("build", "run", "set") and c["exit"] != 0)
    m["renders"] = cmds.get("render", 0) + sum(1 for c in calls if _cmd(c["argv"]) == "run" and "--render" in c["argv"])
    m["doc_lookups"] = sum(v for k, v in cmds.items() if k in DOC_COMMANDS)
    m["errors"] = dict(Counter(c["error"] for c in calls if c.get("error")))
    m["cad_failures"] = sum(1 for c in calls if c["exit"] != 0)
    m["cad_time_s"] = round(sum(c["ms"] for c in calls) / 1000, 2)
    m["first_successful_build_index"] = next((i for i, c in enumerate(calls) if _cmd(c["argv"]) in ("build", "run") and c["exit"] == 0), None)

    t = d / "transcript.jsonl"
    tools: Counter = Counter()
    png_reads = 0
    peeks = []
    doc_reads = 0
    if t.exists():
        for line in t.read_text().splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant":
                for c in ev.get("message", {}).get("content", []):
                    if c.get("type") != "tool_use":
                        continue
                    tools[c["name"]] += 1
                    inp = json.dumps(c.get("input", {}))
                    if c["name"] == "Read" and str(c["input"].get("file_path", "")).endswith(".png"):
                        png_reads += 1
                    if PEEK.search(inp):
                        peeks.append(inp[:200])
                    if "REFERENCE.md" in inp:
                        doc_reads += 1
            elif ev.get("type") == "result":
                m["turns"] = ev.get("num_turns")
                m["duration_s"] = round((ev.get("duration_ms") or 0) / 1000, 1)
                m["cost_usd"] = ev.get("total_cost_usd")
                u = ev.get("usage") or {}
                m["tokens"] = {k: u.get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
                m["agent_result_error"] = ev.get("is_error")
                m["stop_reason"] = ev.get("subtype") or ev.get("stop_reason")
    m["tool_calls"] = dict(tools)
    m["bash_commands"] = tools.get("Bash", 0)
    # onboarding timeline, relative to the agent's start
    started = None
    mp = d / "meta.json"
    if mp.exists():
        started = json.loads(mp.read_text()).get("started")
    if started and calls:
        def first(pred):
            hit = next((c for c in calls if pred(c)), None)
            return round(hit["t"] - started, 1) if hit else None
        m["time_to_first_cad_s"] = first(lambda c: True)
        m["time_to_first_valid_model_s"] = first(lambda c: c.get("valid_model"))
        m["time_to_first_export_s"] = first(lambda c: c["exit"] == 0 and (
            _cmd(c["argv"]) == "export" or (_cmd(c["argv"]) == "run" and "--export" in c["argv"])))
    m["export_succeeded"] = any(c["exit"] == 0 and (_cmd(c["argv"]) == "export" or (_cmd(c["argv"]) == "run" and "--export" in c["argv"]))
                                for c in calls)
    m["api_errors"] = m["cad_failures"]
    m["render_inspections"] = png_reads
    m["implementation_peeks"] = len(peeks)
    m["peek_examples"] = peeks[:5]
    m["doc_lookups"] += doc_reads
    return m
