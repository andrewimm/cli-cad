# S02 case S02-1-0009 (star_profile/vertical, input: mixed)
# verdict: {'class': 'defect', 'kinds': ['solid_count_changed', 'stale_selection_accepted']}
# run: uv run python /Users/andrew/dev/github/clicd/stress-runs/S02-seed1-20261107-183202/failures/S02-1-0009/repro.py
import math, time
from cad import CadError, Part, Profile, Plane, _occ

SHAPE = {'kind': 'star_profile', 'points': [[25.787, 0.0], [9.561, 3.96], [18.234, 18.234], [3.96, 9.561], [0.0, 25.787], [-3.96, 9.561], [-18.234, 18.234], [-9.561, 3.96], [-25.787, 0.0], [-9.561, -3.96], [-18.234, -18.234], [-3.96, -9.561], [-0.0, -25.787], [3.96, -9.561], [18.234, -18.234], [9.561, -3.96]], 'h': 10.9}
SELECTION = 'vertical'
RADII = [0.1, 0.5, 1.0, 2.0, 5.0]
SEED = 9

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
result = {"edges": len(edges), "faces_before": len(base.faces()), "volume_before": base.volume, "attempts": []}
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
        out = {"radius": r}
        try:
            p.fillet(sel, r)
            out.update(ok=True, valid=p.is_valid(), solids=p.solid_count, volume=p.volume)
            refs = p.references()
            out["lost_refs"] = [n for n in protected if refs.get(n, {}).get("status") != "ok"]
            if keep:
                # the pre-fillet selection must now be rejected as stale
                try:
                    p.fillet(sel, r * 0.5)
                    out["stale_selection_detected"] = False
                except CadError as e:
                    out["stale_selection_detected"] = "stale" in e.message
        except CadError as e:
            out.update(ok=False, code=e.code, has_hint=bool(e.hint), message=e.message,
                       failing_edges="failing_edges" in (e.details or {}),
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

print(result)
