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

from cad import CadError, Part, _occ
from cad.project import read_overlay
from cad.runner import run_script

from .tasks import Task

AXES = {"x": 0, "y": 1, "z": 2}


def load_submission(path: Path, overrides: dict | None = None) -> tuple[dict[str, Part], dict]:
    """Build a project directory (cad.toml) or a single script; returns (parts, info).

    ``overrides`` are applied on top of the project's params.toml (for parameter checks).
    """
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
    params = {**params, **(overrides or {})}
    info["script"] = str(script)
    info["params"] = params
    t = time.perf_counter()
    out = run_script(script, params)
    info["build_ms"] = round((time.perf_counter() - t) * 1000, 1)
    refs = [n for n, p in out.parts.items() if getattr(p, "reference", False)]
    if refs:
        info["reference_parts_ignored"] = refs  # design-around envelopes are not deliverables
    return {n: p for n, p in out.parts.items() if n not in refs}, info


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


class Context:
    """What a check can see: the built parts, the submission, and rebuilds with overrides."""

    def __init__(self, submission: Path, parts: dict[str, Part], overrides: dict | None = None):
        self.submission = Path(submission)
        self.parts = parts
        self.overrides = overrides or {}
        self._cache: dict[str, dict[str, Part]] = {}

    @property
    def workspace(self) -> Path:
        return self.submission if self.submission.is_dir() else self.submission.parent

    def rebuild(self, overrides: dict) -> "Context":
        import json

        merged = {**self.overrides, **overrides}
        key = json.dumps(merged, sort_keys=True)
        if key not in self._cache:
            self._cache[key] = load_submission(self.submission, merged)[0]
        ctx = Context(self.submission, self._cache[key], merged)
        ctx._cache = self._cache
        return ctx


def _obstacles(ctx: "Context", check: dict, exclude: str | None = None) -> list:
    from .geom_checks import make_solid

    obs = [p.shape for n, p in ctx.parts.items() if n != exclude]
    obs += [make_solid(s) for s in check.get("obstacles", [])]
    return obs


def run_check(check: dict, parts_or_ctx) -> dict:
    ctx = parts_or_ctx if isinstance(parts_or_ctx, Context) else Context(Path("."), parts_or_ctx)
    parts = ctx.parts
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
            req = check.get("required_names", [])
            n = len(parts)
            ok = (("count" not in check or n == check["count"]) and n >= check.get("min", 0) and n <= check.get("max", 10**9)
                  and (not names or sorted(names) == sorted(parts)) and all(r in parts for r in req))
            res.update(ok=ok, actual=sorted(parts),
                       expected={k: check[k] for k in ("count", "min", "max", "names", "required_names") if k in check})
        elif t == "valid":
            bad = {n: p.solid_count for n, p in parts.items() if not p.is_valid() or p.solid_count != check.get("solids", 1)}
            res.update(ok=not bad, actual=bad or "all valid, single solid")
        elif t == "no_voids":
            # an internal cavity is an extra (inner) shell inside a solid
            bad = {}
            for n, p in parts.items():
                for i, so in enumerate(_occ.solids(p.shape)):
                    k = len(_occ.shells(so))
                    if k != 1:
                        bad[f"{n}[{i}]"] = k
            res.update(ok=not bad, actual=bad or "no internal voids")
        elif t == "bbox":
            p = _pick(parts, check.get("part"))
            bb = p.bbox
            ok = True
            if "size" in check:
                ok = all(abs(a - b) <= tol for a, b in zip(bb.size, check["size"]))
            for i, ax in enumerate("xyz"):
                if f"min_{ax}" in check:
                    ok = ok and abs(bb.min[i] - check[f"min_{ax}"]) <= tol
            if "min" in check:
                ok = ok and all(abs(a - b) <= tol for a, b in zip(bb.min, check["min"]))
            res.update(ok=ok, actual={"size": [round(v, 4) for v in bb.size], "min": [round(v, 4) for v in bb.min]},
                       expected={k: v for k, v in check.items() if k in ("size", "min", "min_x", "min_y", "min_z")})
        elif t == "volume":
            p = _pick(parts, check.get("part"))
            v = p.volume
            ok = abs(v - check["expected"]) <= check.get("rel_tol", 0.01) * check["expected"]
            res.update(ok=ok, actual=round(v, 2), expected=check["expected"])
        elif t == "holes":
            p = _pick(parts, check.get("part"))
            ax = AXES[check["axis"]]
            others = [i for i in range(3) if i != ax]
            if "diameter_range" in check:
                lo_d, hi_d = check["diameter_range"]
                dia_ok = lambda h: lo_d - 1e-6 <= h["diameter"] <= hi_d + 1e-6  # noqa: E731
            else:
                dia_ok = lambda h: abs(h["diameter"] - check["diameter"]) <= max(tol, 0.01)  # noqa: E731
            cands = [h for h in p.find_holes() if dia_ok(h) and abs(abs(h["axis"][ax]) - 1) < 1e-6]
            missing = []
            for pos in check.get("positions", []):
                hit = [h for h in cands if math.dist([h["position"][i] for i in others], pos) <= tol]
                if check.get("depth") is not None:
                    hit = [h for h in hit if abs(h["depth"] - check["depth"]) <= max(tol, 0.05)]
                if not hit:
                    missing.append(pos)
            ok = not missing and (not check.get("exact_count") or len(cands) == len(check["positions"]))
            if "min_count" in check:
                ok = ok and len(cands) >= check["min_count"]
            blocked = []
            if check.get("access") and cands:
                from .geom_checks import hole_access_volume

                acc = check["access"]
                obs = _obstacles(ctx, acc)  # every part (including this one) plus reference obstacles
                for h in cands:
                    v = hole_access_volume(h, acc["direction"], acc["diameter"], acc.get("length", 200), obs)
                    if v > 1e-3:
                        blocked.append({"position": h["position"], "blocked_volume": round(v, 3)})
                ok = ok and not blocked
            res.update(ok=ok, missing=missing, blocked=blocked,
                       found=[{k: h[k] for k in ("diameter", "axis", "position", "depth")} for h in cands],
                       expected={k: check[k] for k in ("diameter", "diameter_range", "axis", "positions", "min_count") if k in check})
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
        elif t == "clearance":
            # minimum distance between part pairs (and no overlap)
            pairs = check.get("pairs") or [[a, b] for i, a in enumerate(sorted(parts)) for b in sorted(parts)[i + 1:]]
            worst = []
            for a, b in pairs:
                pa, pb = _pick(parts, a), _pick(parts, b)
                d = pa.distance_to(pb)
                inter = pa.interference(pb) if d < 1e-9 else 0.0
                worst.append({"pair": [a, b], "distance": round(d, 4), "interference": round(inter, 4)})
            ok = all(w["distance"] >= check["min_distance"] - 1e-6 for w in worst)
            res.update(ok=ok, actual=worst, expected={"min_distance": check["min_distance"]})
        elif t == "keepout":
            # reference solids (component envelopes, shaft paths) that no part may enter
            from .geom_checks import common_volume, make_solid

            targets = _parts_for(check, parts)
            hits = []
            for i, spec in enumerate(check["solids"]):
                zone = make_solid(spec)
                for p in targets:
                    v = common_volume(zone, p.shape)
                    if v > check.get("max_volume", 1e-3):
                        hits.append({"zone": spec.get("label", i), "part": p.name, "volume": round(v, 4)})
            res.update(ok=not hits, intrusions=hits)
        elif t == "contact":
            # some part must touch (be within max_distance of) a reference solid, e.g. support a component
            from .geom_checks import make_solid

            zone = make_solid(check["solid"])
            ds = {p.name: round(_occ.distance(p.shape, zone)[0], 4) for p in _parts_for(check, parts)}
            res.update(ok=min(ds.values()) <= check.get("max_distance", 0.05), actual=ds)
        elif t == "min_thickness":
            from .geom_checks import thickness_samples

            pct = check.get("percentile", 2.0)
            per_part = {}
            for p in _parts_for(check, parts):
                samples = thickness_samples(p, check.get("samples_per_face", 5))
                ts = sorted(s_[0] for s_ in samples)
                k = min(len(ts) - 1, max(0, int(len(ts) * pct / 100.0)))
                per_part[p.name] = {
                    "value": round(ts[k], 4) if ts else 0.0,
                    "samples": len(ts),
                    "thinnest": [{"thickness": round(a, 3), "point": [round(c, 3) for c in b]} for a, b, _ in sorted(samples)[:3]],
                }
            ok = all(v["value"] >= check["min"] - 1e-6 and v["samples"] for v in per_part.values())
            res.update(ok=ok, actual=per_part, expected={"min": check["min"], "percentile": pct})
        elif t == "export":
            from .geom_checks import export_report

            reps = {p.name: export_report(p, check.get("formats", ["step", "stl"]), check.get("stl_tolerance", 0.01))
                    for p in _parts_for(check, parts)}
            ok = all(r["ok"] for rep in reps.values() for r in rep.values())
            res.update(ok=ok, actual=reps)
        elif t == "fits_build_volume":
            from .geom_checks import fits

            sizes = {p.name: [round(v, 3) for v in p.bbox.size] for p in _parts_for(check, parts)}
            bad = {n: sz for n, sz in sizes.items() if not fits(sz, check["size"])}
            res.update(ok=not bad, actual=sizes, too_large=bad, expected=check["size"])
        elif t in ("param_rebuild", "param_sweep"):
            # rebuild with parameter overrides and re-run nested checks
            if t == "param_rebuild":
                runs = [check["overrides"]]
            else:
                runs = [{check["parameter"]: v} for v in check["values"]]
            failures, n = [], 0
            for ov in runs:
                try:
                    sub = ctx.rebuild(ov)
                except CadError as e:
                    failures.append({"overrides": ov, "build_error": e.to_dict()})
                    continue
                for c in check["checks"]:
                    n += 1
                    r = run_check(c, sub)
                    if not r["ok"]:
                        failures.append({"overrides": ov, **r})
            res.update(ok=not failures, nested_checks=n, failures=failures[:10])
        elif t == "file":
            f = ctx.workspace / check["path"]
            text = f.read_text(errors="ignore") if f.is_file() else ""
            missing_words = [w for w in check.get("must_mention", []) if w.lower() not in text.lower()]
            ok = f.is_file() and len(text.strip()) >= check.get("min_chars", 1) and not missing_words
            res.update(ok=ok, exists=f.is_file(), chars=len(text.strip()), missing_mentions=missing_words)
        elif t == "rendered_configurations":
            # count distinct parameter values among revisions the agent actually rendered
            import json as _json

            param = check["parameter"]
            seen: dict = {}
            for meta in ctx.workspace.rglob("*.json"):
                if ".cad" in meta.parts:
                    continue
                try:
                    m = _json.loads(meta.read_text())
                except Exception:
                    continue
                rev = (m.get("model") or {}).get("revision") if isinstance(m, dict) else None
                if rev is None:
                    continue
                man = ctx.workspace / ".cad" / "revisions" / str(rev) / "manifest.json"
                if not man.exists():
                    continue
                pv = _json.loads(man.read_text()).get("parameters", {}).get(param, {}).get("value")
                if pv is not None:
                    seen.setdefault(pv, []).append(str(meta.relative_to(ctx.workspace)))
            res.update(ok=len(seen) >= check["min_distinct"], actual=sorted(seen), expected={"min_distinct": check["min_distinct"]})
        elif t == "stl_artifact":
            # the agent must have exported a printable STL of its final model into the workspace
            from .geom_checks import stl_report

            found = []
            for f in sorted(ctx.workspace.rglob("*.stl")):
                if ".cad" in f.parts:
                    continue
                rep = stl_report(f)
                watertight = rep["triangles"] > 0 and rep["boundary_edges"] == 0 and rep["non_manifold_edges"] == 0 \
                    and rep["inconsistent_orientation_edges"] == 0 and rep["signed_volume"] > 0
                matches = []
                for n, p in parts.items():
                    bb = p.bbox
                    if rep["bbox_min"] and max(abs(a - b) for a, b in zip(rep["bbox_min"] + rep["bbox_max"], list(bb.min) + list(bb.max))) <= check.get("bbox_tol", 0.1):
                        matches.append(n)
                found.append({"file": str(f.relative_to(ctx.workspace)), "watertight": watertight, "matches_parts": matches,
                              "triangles": rep["triangles"], "signed_volume": rep["signed_volume"]})
            ok = any(x["watertight"] and x["matches_parts"] for x in found)
            res.update(ok=ok, files=found, note=check.get("note", "a watertight STL matching the final model exists in the workspace"))
        elif t == "plate":
            # orientation-agnostic plate: two bbox dimensions match `footprint`, the third is the thickness,
            # with `holes` through-holes along the thickness axis
            p = _pick(parts, check.get("part"))
            size = list(p.bbox.size)
            ax = min(range(3), key=lambda i: size[i])
            others = sorted(size[i] for i in range(3) if i != ax)
            fp = sorted(check["footprint"])
            fp_ok = all(abs(a - b) <= tol for a, b in zip(others, fp))
            th = size[ax]
            th_ok = check.get("thickness_min", 0) <= th <= check.get("thickness_max", 1e9)
            holes = [h for h in p.find_holes() if abs(abs(h["axis"][ax]) - 1) < 1e-6 and abs(h["depth"] - th) <= max(tol, 0.01)]
            n_ok = len(holes) == check["holes"] if check.get("exact") else len(holes) >= check["holes"]
            res.update(ok=fp_ok and th_ok and n_ok, actual={"footprint": [round(v, 4) for v in others], "thickness": round(th, 4),
                                                         "through_holes": len(holes), "hole_diameters": sorted({round(h["diameter"], 3) for h in holes})},
                       expected={k: check[k] for k in ("footprint", "holes", "thickness_min", "thickness_max") if k in check})
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
        parts, info = load_submission(submission, task.grade_overrides)
    except CadError as e:
        out.update(built=False, passed=False, score=0.0, error=e.to_dict(), checks=[])
        return out
    except Exception as e:
        out.update(built=False, passed=False, score=0.0, error={"code": "GRADER_ERROR", "message": str(e),
                                                                  "traceback": traceback.format_exc()[-2000:]}, checks=[])
        return out
    out["build"] = info
    ctx = Context(Path(submission), parts, task.grade_overrides)
    results = [run_check(c, ctx) for c in task.checks]
    n_ok = sum(1 for r in results if r["ok"])
    out.update(built=True, checks=results, passed=n_ok == len(results), score=round(n_ok / max(1, len(results)), 4),
               parts={n: p.summary() for n, p in parts.items()})
    if render_dir is not None:
        try:
            from cad.renderer import render_views

            out["renders"] = [r["path"] for r in render_views(parts, ["iso", "front", "top", "right", "iso_back", "iso_bottom"],
                                                              render_dir, size=(800, 600), prefix=task.id)]
        except Exception as e:
            out["render_error"] = str(e)
    return out
