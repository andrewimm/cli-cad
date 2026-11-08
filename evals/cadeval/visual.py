"""Vision-model review of renders (complements, never replaces, geometric checks).

Provider: any CLI agent that can read images; the default is Claude Code in
print mode (`claude -p`), restricted to the Read tool.  Without a provider the
harness simply skips visual review — it never invents a verdict.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .tasks import Task

PROMPT = """You are reviewing renders of a CAD model against its design request. Be strict and specific.

Design request:
---
{prompt}
---

Rendered views (orthographic; each image is annotated with its view name, screen axes and a scale bar; Z is up, front view looks from -Y):
{images}

Open every image with the Read tool, then reply with ONLY a JSON object:
{{"overall_match": 1-5, "shape_ok": bool, "features_present": [..], "missing_features": [..],
  "unexpected_features": [..], "proportions_ok": bool, "placement_issues": [..],
  "interference_or_implausibility": [..], "notes": "..."}}
"""


def visual_review(task: Task, images: list[str], out_dir: Path, agent_cmd: str = "claude", model: str = "sonnet") -> dict:
    if not shutil.which(agent_cmd):
        return {"skipped": f"{agent_cmd} not available"}
    imgs = [i for i in images if not i.endswith("_sheet.png")]
    work = out_dir / "visual_review"
    work.mkdir(parents=True, exist_ok=True)
    local = []
    for i in imgs:
        dst = work / Path(i).name
        shutil.copy(i, dst)
        local.append(dst.name)
    from .run import _SESSION_VARS

    env = {k: v for k, v in os.environ.items() if k not in _SESSION_VARS}
    prompt = PROMPT.format(prompt=task.prompt, images="\n".join(f"- {n}" for n in local))
    p = subprocess.run([agent_cmd, "-p", prompt, "--output-format", "json", "--model", model, "--max-turns", "12",
                        "--no-session-persistence", "--allowedTools", "Read"],
                       cwd=work, env=env, capture_output=True, text=True, timeout=600)
    try:
        res = json.loads(p.stdout)
        text = res.get("result", "")
        mt = re.search(r"\{.*\}", text, re.S)
        verdict = json.loads(mt.group(0)) if mt else {"unparsed": text}
        return {"provider": agent_cmd, "model": model, "verdict": verdict, "cost_usd": res.get("total_cost_usd")}
    except (json.JSONDecodeError, AttributeError) as e:
        return {"provider": agent_cmd, "error": f"could not parse reviewer output: {e}", "raw": p.stdout[-2000:], "stderr": p.stderr[-1000:]}
