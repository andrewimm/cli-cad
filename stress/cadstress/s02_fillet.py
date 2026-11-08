"""S02 — Fillet robustness.

Each case is a shape plus an edge selection.  The case first finds the largest
feasible radius r_max by bisection over real fillet attempts (assuming
feasibility is monotone in the radius), then attempts fillets at
0.1, 0.5, 1, 2 and 5 mm and at 0.9 r_max / 1.1 r_max.

Expectations per attempt:
* r <= 0.9 r_max: must succeed with a valid single solid whose unrelated named
  faces survive (a failure here is "non-monotonic": a larger radius worked);
* r >= 1.1 r_max: must fail in a controlled way (CadError FILLET_FAILED) with an
  informative error, leaving the part unchanged; a valid success is noted;
* between: ambiguous.
Every case also checks that a selection made before the fillet is rejected as
stale afterwards (invalid edge references must be detected, never reused).
"""

from __future__ import annotations

import json
import math
import random

FIXED_RADII = [0.1, 0.5, 1.0, 2.0, 5.0]
SHAPES = ["box", "bracket", "convex_profile", "star_profile", "plate_holes", "pocket_block"]
SELECTIONS = ["all", "vertical", "top", "convex", "concave", "single", "random_k"]

CODE = """
SHAPE = {shape}
SELECTION = {selection}
RADII = {radii}
SEED = {seed}

import random as _random

def make():
    s = SHAPE
    p = Part("s")
    k = s["kind"]
    if k == "box":
        p.box(*s["size"], name="body")
    elif k == "bracket":
        w, d, t, h, t2 = s["w"], s["d"], s["t"], s["h"], s["t2"]
        p.box(w, d, t, name="base")
        p.box(w, t2, h, at=(0, d / 2, t), align=("center", "max", "min"), name="wall")
        if s.get("holes"):
            p.hole_pattern(s["hole_d"], spacing=(w * 0.6, (d - t2) * 0.5), center=(0, -t2 / 2), name="holes")
    elif k in ("convex_profile", "star_profile"):
        p.extrude(Profile.polygon(s["points"]), s["h"], name="body")
    elif k == "plate_holes":
        p.box(*s["size"], name="body")
        p.hole_pattern(s["hole_d"], spacing=(s["size"][0] * 0.6, s["size"][1] * 0.6), count=(s["nx"], 2), name="holes")
    elif k == "pocket_block":
        p.box(*s["size"], name="body")
        p.box(s["size"][0] * 0.6, s["size"][1] * 0.6, s["size"][2] * 0.5, at=(0, 0, s["size"][2] * 0.5), op="cut", name="pocket")
    return p

def select(p):
    sel = SELECTION
    e = p.edges()
    if sel == "all":
        return e
    if sel == "vertical":
        return e.vertical()
    if sel == "top":
        return p.faces().facing("+z").max("z").edges()
    if sel == "convex":
        return e.convex()
    if sel == "concave":
        return e.concave()
    rng = _random.Random(SEED)
    items = sorted(e.info(), key=lambda i: (i["midpoint"], i["length"]))
    if sel == "single":
        target = items[rng.randrange(len(items))]["midpoint"]
        return e.nearest(target, 1)
    k = max(2, min(len(items) - 1, rng.randint(2, 6)))
    picks = rng.sample(range(len(items)), k)
    out = None
    for i in picks:
        one = e.nearest(items[i]["midpoint"], 1)
        out = one if out is None else (out | one)
    return out

base = make()
edges = select(base)
result = {{"edges": len(edges), "faces_before": len(base.faces()), "volume_before": base.volume, "attempts": []}}
if len(edges) == 0:
    result["skipped"] = "selection is empty for this shape"
else:
    # faces adjacent to the selected edges may legitimately be consumed; every other named face must survive
    adjacent = set()
    edge_set = _occ.ShapeSet(edges.shapes)
    for f in _occ.faces(base.shape):
        if any(e in edge_set for e in _occ.edges(f)):
            adjacent.update(base._names_of(f, "face"))
    protected = sorted(n for n, r in base.references().items() if r["kind"] == "face" and r["status"] == "ok"
                       and n not in adjacent and not any(a.startswith(n + ".") or n.startswith(a + ".") for a in adjacent))
    result["protected_refs"] = protected

    def attempt(r, keep=False):
        p = base.copy()
        sel = select(p)
        t = time.perf_counter()
        out = {{"radius": r}}
        try:
            p.fillet(sel, r)
            out.update(ok=True, valid=p.is_valid(), solids=p.solid_count, volume=p.volume)
            refs = p.references()
            out["lost_refs"] = [n for n in protected if refs.get(n, {{}}).get("status") != "ok"]
            if keep:
                # the pre-fillet selection must now be rejected as stale
                try:
                    p.fillet(sel, r * 0.5)
                    out["stale_selection_detected"] = False
                except CadError as e:
                    out["stale_selection_detected"] = "stale" in e.message
        except CadError as e:
            out.update(ok=False, code=e.code, has_hint=bool(e.hint), message=e.message,
                       failing_edges="failing_edges" in (e.details or {{}}),
                       mentions_radius=("%g" % r) in e.message or str(r) in e.message,
                       unchanged=abs(p.volume - base.volume) <= 1e-9 * max(1.0, base.volume))
        out["ms"] = round((time.perf_counter() - t) * 1000, 2)
        return out

    def feasible(r):
        return attempt(r)["ok"]

    hi = 0.5 * max(base.bbox.size)
    probes = []
    if not feasible(0.01):
        rmax = 0.0
    else:
        lo = 0.01
        for _ in range(12):
            mid = (lo + hi) / 2
            ok = feasible(mid)
            probes.append([round(mid, 4), ok])
            lo, hi = (mid, hi) if ok else (lo, mid)
        rmax = lo
    result["rmax"] = rmax
    result["probes"] = probes
    radii = sorted(set(RADII + ([round(0.9 * rmax, 4), round(1.1 * rmax, 4)] if rmax > 0 else [])))
    for r in radii:
        if r <= 0:
            continue
        result["attempts"].append(attempt(r, keep=True))
"""


def _shape(r: random.Random, kind: str) -> dict:
    if kind == "box":
        return {"kind": "box", "size": [round(r.uniform(4, 60), 2) for _ in range(3)]}
    if kind == "bracket":
        t = round(r.uniform(2, 8), 2)
        return {"kind": "bracket", "w": round(r.uniform(20, 80), 2), "d": round(r.uniform(15, 50), 2), "t": t,
                "h": round(r.uniform(10, 50), 2), "t2": round(r.uniform(2, 8), 2), "holes": r.random() < 0.5,
                "hole_d": round(r.uniform(2, 5), 2)}
    if kind == "convex_profile":
        n = r.randint(3, 9)
        rad = r.uniform(10, 40)
        angs = sorted(r.uniform(0, 2 * math.pi) for _ in range(n))
        pts = [[round(rad * r.uniform(0.85, 1.0) * math.cos(a), 3), round(rad * r.uniform(0.85, 1.0) * math.sin(a), 3)] for a in angs]
        # keep vertices well separated
        pts = [p for i, p in enumerate(pts) if i == 0 or math.dist(p, pts[i - 1]) > 2.0]
        if len(pts) < 3:
            pts = [[rad, 0], [-rad / 2, rad * 0.8], [-rad / 2, -rad * 0.8]]
        return {"kind": "convex_profile", "points": pts, "h": round(r.uniform(3, 30), 2)}
    if kind == "star_profile":
        n = r.randint(4, 8)
        ro, ri = r.uniform(15, 40), r.uniform(0.35, 0.75)
        pts = []
        for i in range(2 * n):
            a = math.pi * i / n
            rr = ro if i % 2 == 0 else ro * ri
            pts.append([round(rr * math.cos(a), 3), round(rr * math.sin(a), 3)])
        return {"kind": "star_profile", "points": pts, "h": round(r.uniform(3, 30), 2)}
    if kind == "plate_holes":
        return {"kind": "plate_holes", "size": [round(r.uniform(30, 90), 2), round(r.uniform(20, 60), 2), round(r.uniform(2, 10), 2)],
                "hole_d": round(r.uniform(2, 6), 2), "nx": r.randint(2, 4)}
    return {"kind": "pocket_block", "size": [round(r.uniform(20, 70), 2), round(r.uniform(20, 70), 2), round(r.uniform(6, 30), 2)]}


def generate(n: int = 500, seed: int = 1) -> list[dict]:
    """``n`` is the target number of fillet attempts (each case makes ~5-7)."""
    rng = random.Random(seed)
    cases = []
    i = 0
    attempts = 0
    while attempts < n:
        kind = SHAPES[i % len(SHAPES)]
        sel = SELECTIONS[(i // len(SHAPES)) % len(SELECTIONS)]
        if sel == "concave" and kind in ("box", "convex_profile", "plate_holes"):
            sel = "random_k"
        r = random.Random(f"{seed}-{i}")
        shape = _shape(r, kind)
        cases.append({
            "id": f"S02-{seed}-{i:04d}",
            "suite": "S02",
            "category": f"{kind}/{sel}",
            "expect": "mixed",
            "params": {"shape": shape, "selection": sel},
            "code": CODE.format(shape=repr(shape), selection=repr(sel), radii=json.dumps(FIXED_RADII), seed=i),
            "timeout_s": 300,
        })
        attempts += len(FIXED_RADII) + 2
        i += 1
    return cases


def classify_attempt(a: dict, rmax: float) -> tuple[str, list[str]]:
    r = a["radius"]
    kinds = []
    if rmax > 0 and r <= 0.9 * rmax + 1e-9:
        want = "success"
    elif r >= 1.1 * rmax - 1e-9:
        want = "failure"
    else:
        want = "either"
    if a["ok"]:
        if not a["valid"]:
            kinds.append("invalid_result")
        if a["solids"] != 1:
            kinds.append("solid_count_changed")
        if a.get("lost_refs"):
            kinds.append("unexpected_face_disappearance")
        if a.get("stale_selection_detected") is False:
            kinds.append("stale_selection_accepted")
        if kinds:
            return "defect", kinds
        return ("pass", []) if want != "failure" else ("pass", ["succeeded_above_rmax"])
    # failure
    quality = int(a.get("code") == "FILLET_FAILED") + int(bool(a.get("has_hint"))) + int(bool(a.get("failing_edges"))) \
        + int(bool(a.get("mentions_radius")))
    if not a.get("unchanged", True):
        kinds.append("part_changed_by_failed_fillet")
    if quality < 3:
        kinds.append(f"poor_error_quality:{quality}")
    if want == "success":
        kinds.append("non_monotonic_failure")
        return "defect", kinds
    return ("controlled" if not any(k.startswith("part_changed") for k in kinds) else "defect"), kinds


def judge(case: dict, o: dict) -> dict:
    if o["status"] in ("crash", "timeout", "missing"):
        return {"class": "defect", "kinds": [o["status"]]}
    if o["status"] == "exception":
        return {"class": "defect", "kinds": ["uncaught_exception"], "detail": o.get("exception")}
    res = o["result"]
    if res.get("skipped"):
        return {"class": "skipped", "kinds": [], "notes": [res["skipped"]]}
    rmax = res["rmax"]
    kinds = []
    classes = []
    for a in res["attempts"]:
        cls, k = classify_attempt(a, rmax)
        classes.append(cls)
        kinds += [f"r={a['radius']}:{x}" if x.startswith("non_monotonic") else x for x in k]
    if rmax == 0:
        kinds.append("unfilletable_selection")
    flat = sorted(set(k.split(":", 1)[1] if k.startswith("r=") else k for k in kinds))
    if "defect" in classes:
        return {"class": "defect", "kinds": flat}
    if rmax == 0:
        return {"class": "controlled", "kinds": flat}
    return {"class": "pass" if all(c == "pass" for c in classes) else "controlled", "kinds": flat}


def analyze(cases: list[dict], outcomes: dict) -> dict:
    """Per-attempt statistics across all cases (the unit the suite is sized in)."""
    from collections import Counter, defaultdict

    by_r = defaultdict(Counter)
    quality = Counter()
    total = 0
    ms = []
    rmax_zero = 0
    for c in cases:
        o = outcomes.get(c["id"], {})
        res = o.get("result") or {}
        if o.get("status") != "ran" or res.get("skipped"):
            continue
        rmax = res["rmax"]
        rmax_zero += rmax == 0
        for a in res["attempts"]:
            total += 1
            ms.append(a["ms"])
            r = a["radius"]
            bucket = f"{r:g} mm" if r in FIXED_RADII else ("0.9 rmax" if rmax and abs(r - 0.9 * rmax) < 1e-3 else "1.1 rmax")
            cls, kinds = classify_attempt(a, rmax)
            by_r[bucket]["attempts"] += 1
            by_r[bucket]["succeeded"] += a["ok"]
            by_r[bucket]["valid"] += bool(a.get("valid"))
            by_r[bucket][cls] += 1
            if not a["ok"]:
                q = int(a.get("code") == "FILLET_FAILED") + int(bool(a.get("has_hint"))) + int(bool(a.get("failing_edges"))) + int(bool(a.get("mentions_radius")))
                quality[q] += 1
    ms.sort()
    return {
        "fillet_attempts": total,
        "selections_with_no_feasible_radius": rmax_zero,
        "by_radius": {k: dict(v) for k, v in sorted(by_r.items())},
        "error_quality_score_distribution(0-4)": dict(sorted(quality.items())),
        "attempt_ms": {"median": ms[len(ms) // 2] if ms else None, "p95": ms[int(0.95 * len(ms))] if ms else None, "max": ms[-1] if ms else None},
    }


def minimize(case: dict, outcome: dict) -> dict | None:
    """Reduce to the single radius that misbehaved."""
    res = outcome.get("result") or {}
    for a in res.get("attempts", []):
        cls, _ = classify_attempt(a, res.get("rmax", 0))
        if cls == "defect":
            code = case["code"].replace(f"RADII = {json.dumps(FIXED_RADII)}", f"RADII = {json.dumps([a['radius']])}")
            return {"code": code, "note": f"radius {a['radius']} only (bisection still runs to establish rmax)"}
    return None
