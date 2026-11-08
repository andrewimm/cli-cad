"""S04 — Repeated features: scaling characterisation.

Plates with N = 10, 100, 500, 1000 holes (one pattern call, or one call per
hole), cylindrical bosses and ribs.  Each case runs in a fresh process so peak
RSS belongs to that case alone.  Construction time is split into the phases the
feature graph records (tool construction, boolean, validation, reference
tracking, measurement); tessellation, rendering and STEP export are timed
separately.  Feature counts and analytic volumes are verified.
"""

from __future__ import annotations

import math

COUNTS = [10, 100, 500, 1000]
KINDS = ["holes_pattern", "holes_individual", "bosses", "bosses_batch", "ribs", "ribs_batch"]
FRESH_PROCESS = True
TIMEOUT_S = 1500

CODE = """
KIND = {kind!r}
N = {n}
import math, tempfile, os, gc
from collections import defaultdict
from cad.tessellate import tessellate
from cad import renderer as R

pitch, d, t, boss_h = 6.0, 3.0, 4.0, 5.0
nx = math.ceil(math.sqrt(N)); ny = math.ceil(N / nx)
result = {{"kind": KIND, "n": N}}
t0 = time.perf_counter()
p = Part("plate")
if KIND in ("ribs", "ribs_batch"):
    W, D = N * 3.0 + 6, 40.0
    p.box(W, D, t)
    rib_at = [(-W / 2 + 3 + 0.5 + i * 3.0, 0, t) for i in range(N)]
    if KIND == "ribs":
        for a in rib_at:
            p.box(1.0, D - 4, 6.0, at=a, align=("center", "center", "min"))
    else:
        p.box(1.0, D - 4, 6.0, at=rib_at, align=("center", "center", "min"))
    expected = W * D * t + N * 1.0 * (D - 4) * 6.0
else:
    W, D = nx * pitch + pitch, ny * pitch + pitch
    p.box(W, D, t)
    pts = [(-W / 2 + pitch + i * pitch, -D / 2 + pitch + j * pitch) for j in range(ny) for i in range(nx)][:N]
    if KIND == "holes_pattern":
        p.holes(d, pts)
        expected = W * D * t - N * math.pi * (d / 2) ** 2 * t
    elif KIND == "holes_individual":
        for x, y in pts:
            p.hole(d, at=(x, y))
        expected = W * D * t - N * math.pi * (d / 2) ** 2 * t
    elif KIND == "bosses":
        for x, y in pts:
            p.cylinder(d, boss_h, at=(x, y, t))
        expected = W * D * t + N * math.pi * (d / 2) ** 2 * boss_h
    else:
        p.cylinder(d, boss_h, at=[(x, y, t) for x, y in pts])
        expected = W * D * t + N * math.pi * (d / 2) ** 2 * boss_h
result["construct_s"] = time.perf_counter() - t0
phases = defaultdict(float)
for f in p.features:
    for k, v in f.phases_ms.items():
        phases[k] += v / 1000
result["phases_s"] = dict(phases)
result["features"] = len(p.features)
result["volume_rel_err"] = abs(p.volume - expected) / expected
result["valid"] = p.is_valid()
result["solids"] = p.solid_count
if KIND.startswith("holes"):
    result["found"] = len(p.find_holes())
elif KIND.startswith("bosses"):
    result["found"] = len([1 for i in p.faces().cylindrical().info() if not i.get("concave")])
else:
    result["found"] = len(p.faces().facing("+x")) - 1
result["faces"] = len(p.faces())
t1 = time.perf_counter(); mesh = tessellate(p.shape); result["tessellate_s"] = time.perf_counter() - t1
result["triangles"] = len(mesh.triangles)
t1 = time.perf_counter()
scene = [R.SceneItem("plate", mesh, (0.62, 0.69, 0.78), _occ.bbox(p.shape))]
img, meta = R.render_one(scene, R.parse_view("iso"), size=(800, 600))
result["render_s"] = time.perf_counter() - t1
t1 = time.perf_counter(); path = os.path.join(tempfile.mkdtemp(), "p.step"); p.export(path); result["step_s"] = time.perf_counter() - t1
result["step_mb"] = os.path.getsize(path) / 1e6
"""


def generate(n: int | None = None, seed: int = 1) -> list[dict]:
    return [{"id": f"S04-{k}-{c}", "suite": "S04", "category": k, "expect": "valid", "params": {"kind": k, "n": c},
             "code": CODE.format(kind=k, n=c), "timeout_s": TIMEOUT_S} for c in COUNTS for k in KINDS]


def judge(case: dict, o: dict) -> dict:
    if o["status"] in ("crash", "missing"):
        return {"class": "defect", "kinds": [o["status"]]}
    if o["status"] == "timeout":
        return {"class": "limitation", "kinds": [f"timeout>{TIMEOUT_S}s"]}
    if o["status"] == "exception":
        return {"class": "defect", "kinds": ["uncaught_exception"], "detail": o.get("exception")}
    r = o["result"]
    kinds = []
    if not r["valid"] or r["solids"] != 1:
        kinds.append("invalid_result")
    if r["volume_rel_err"] > 1e-6:
        kinds.append("volume_mismatch")
    if r["found"] != case["params"]["n"]:
        kinds.append(f"feature_count:{r['found']}!={case['params']['n']}")
    return {"class": "defect" if kinds else "pass", "kinds": kinds}


def analyze(cases, outcomes) -> dict:
    rows = {}
    for c in cases:
        o = outcomes.get(c["id"], {})
        key = f"{c['params']['kind']}@{c['params']['n']}"
        if o.get("status") != "ran":
            rows[key] = {"status": o.get("status"), "wall_s": round(o.get("wall_ms", 0) / 1000, 1)}
            continue
        r = o["result"]
        rows[key] = {
            "construct_s": round(r["construct_s"], 2),
            **{f"{k}_s": round(v, 2) for k, v in sorted(r["phases_s"].items())},
            "tessellate_s": round(r["tessellate_s"], 2),
            "render_s": round(r["render_s"], 2),
            "step_s": round(r["step_s"], 2),
            "peak_rss_mb": o.get("max_rss_mb"),
            "faces": r["faces"],
            "triangles": r["triangles"],
            "found": r["found"],
            "volume_rel_err": f"{r['volume_rel_err']:.1e}",
        }
    # growth exponents between successive N for construction time (t ~ N^k)
    growth = {}
    for k in KINDS:
        pts = [(n, rows.get(f"{k}@{n}", {}).get("construct_s")) for n in COUNTS]
        pts = [(n, t) for n, t in pts if t]
        if len(pts) >= 2:
            (n1, t1), (n2, t2) = pts[-2], pts[-1]
            growth[k] = round(math.log(t2 / t1) / math.log(n2 / n1), 2) if t1 > 0 else None
    return {"rows": rows, "construct_time_growth_exponent_last_step": growth}
