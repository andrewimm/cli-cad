"""Deterministic geometry grading.

The grader rebuilds the submitted model itself (it never trusts the agent's
claims), then evaluates each declarative check from the task file.
"""

from __future__ import annotations

import math
import time
import tomllib
import traceback
from pathlib import Path
from typing import Any

from cad import CadError, Part
from cad.project import read_overlay
from cad.runner import run_script

from .tasks import Task

AXES = {"x": 0, "y": 1, "z": 2}


def load_submission(path: Path) -> tuple[dict[str, Part], dict]:
    """Build a project directory (cad.toml) or a single script; returns (parts, info)."""
    path = Path(path)
    info: dict[str, Any] = {}
    if path.is_dir():
        cfg = path / "cad.toml"
        if cfg.exists():
            entry = tomllib.loads(cfg.read_text()).get("project", {}).get("entry", "model.py")
        else:
            cands = [p for p in path.glob("*.py")]
            if len(cands) != 1:
                raise CadError("NO_MODEL", f"no cad.toml and {len(cands)} .py files in {path}")
            entry = cands[0].name
        script = path / entry
        params = read_overlay(path)
    else:
        script, params = path, {}
    info["script"] = str(script)
    info["params"] = params
    t = time.perf_counter()
    out = run_script(script, params)
    info["build_ms"] = round((time.perf_counter() - t) * 1000, 1)
    return out.parts, info


def _pick(parts: dict[str, Part], name: str | None) -> Part:
    if name:
        if name not in parts:
            raise KeyError(f"part {name!r} not found (have {sorted(parts)})")
        return parts[name]
    if len(parts) != 1:
        raise KeyError(f"check needs a part name; submission has {sorted(parts)}")
    return next(iter(parts.values()))


def _classify(part: Part, p) -> str:
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON

    c = BRepClass3d_SolidClassifier(part.shape, gp_Pnt(*map(float, p)), 1e-6)
    st = c.State()
    return "in" if st == TopAbs_IN else "on" if st == TopAbs_ON else "out"


def _parts_for(check, parts):
    if check.get("part"):
        return [(_pick(parts, check["part"]))]
    return list(parts.values())


def run_check(check: dict, parts: dict[str, Part]) -> dict:
    t = check["type"]
    tol = float(check.get("tol", 1e-3))
    res: dict[str, Any] = {"type": t}
    if check.get("part"):
        res["part"] = check["part"]
    if check.get("note"):
        res["note"] = check["note"]
    try:
        if t == "part_count":
            names = check.get("names")
            ok = len(parts) == check["count"] and (not names or sorted(names) == sorted(parts))
            res.update(ok=ok, actual=sorted(parts), expected={"count": check["count"], "names": names})
        elif t == "valid":
            bad = {n: p.solid_count for n, p in parts.items() if not p.is_valid() or p.solid_count != check.get("solids", 1)}
            res.update(ok=not bad, actual=bad or "all valid, single solid")
        elif t == "bbox":
            p = _pick(parts, check.get("part"))
            bb = p.bbox
            ok = all(abs(a - b) <= tol for a, b in zip(bb.size, check["size"]))
            if "min" in check:
                ok = ok and all(abs(a - b) <= tol for a, b in zip(bb.min, check["min"]))
            res.update(ok=ok, actual={"size": [round(v, 4) for v in bb.size], "min": [round(v, 4) for v in bb.min]},
                       expected={k: check[k] for k in ("size", "min") if k in check})
        elif t == "volume":
            p = _pick(parts, check.get("part"))
            v = p.volume
            ok = abs(v - check["expected"]) <= check.get("rel_tol", 0.01) * check["expected"]
            res.update(ok=ok, actual=round(v, 2), expected=check["expected"])
        elif t == "holes":
            p = _pick(parts, check.get("part"))
            ax = AXES[check["axis"]]
            others = [i for i in range(3) if i != ax]
            cands = [h for h in p.find_holes() if abs(h["diameter"] - check["diameter"]) <= max(tol, 0.01)
                     and abs(abs(h["axis"][ax]) - 1) < 1e-6]
            missing = []
            for pos in check["positions"]:
                hit = [h for h in cands if math.dist([h["position"][i] for i in others], pos) <= tol]
                if check.get("depth") is not None:
                    hit = [h for h in hit if abs(h["depth"] - check["depth"]) <= max(tol, 0.05)]
                if not hit:
                    missing.append(pos)
            ok = not missing and (not check.get("exact_count") or len(cands) == len(check["positions"]))
            res.update(ok=ok, missing=missing, found=[{k: h[k] for k in ("diameter", "axis", "position", "depth")} for h in cands],
                       expected={k: check[k] for k in ("diameter", "axis", "positions") if k in check})
        elif t in ("points_inside", "points_outside"):
            want = "in" if t == "points_inside" else "out"
            fails = []
            for pt in check["points"]:
                states = [_classify(p, pt) for p in _parts_for(check, parts)]
                state = "in" if "in" in states else ("on" if "on" in states else "out")
                if state != want:
                    fails.append({"point": pt, "state": state})
            res.update(ok=not fails, failures=fails)
        elif t == "interference":
            a, b = _pick(parts, check["a"]), _pick(parts, check["b"])
            v = a.interference(b)
            res.update(ok=v <= check.get("max_volume", 0.001), actual=round(v, 4))
        elif t == "python":
            env: dict[str, Any] = {"parts": parts, "math": math}
            exec(check["code"], env)
            ok, msg = env["check"](parts)
            res.update(ok=bool(ok), message=msg)
        else:
            res.update(ok=False, error=f"unknown check type {t}")
    except Exception as e:  # a check that cannot run counts as failed
        res.update(ok=False, error=f"{type(e).__name__}: {e}")
    return res


def grade(task: Task, submission: Path, render_dir: Path | None = None) -> dict:
    out: dict[str, Any] = {"task": task.id, "submission": str(submission)}
    try:
        parts, info = load_submission(submission)
    except CadError as e:
        out.update(built=False, passed=False, score=0.0, error=e.to_dict(), checks=[])
        return out
    except Exception as e:
        out.update(built=False, passed=False, score=0.0, error={"code": "GRADER_ERROR", "message": str(e),
                                                                  "traceback": traceback.format_exc()[-2000:]}, checks=[])
        return out
    out["build"] = info
    results = [run_check(c, parts) for c in task.checks]
    n_ok = sum(1 for r in results if r["ok"])
    out.update(built=True, checks=results, passed=n_ok == len(results), score=round(n_ok / max(1, len(results)), 4),
               parts={n: p.summary() for n, p in parts.items()})
    if render_dir is not None:
        try:
            from cad.renderer import render_views

            out["renders"] = [r["path"] for r in render_views(parts, ["iso", "front", "top", "right", "iso_back"],
                                                              render_dir, size=(800, 600), prefix=task.id)]
        except Exception as e:
            out["render_error"] = str(e)
    return out
