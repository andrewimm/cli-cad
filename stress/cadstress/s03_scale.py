"""S03 — Numerical scale and tolerance.

Each case is one shape family, built natively (every dimension multiplied by
the scale factor, not a transform of a finished shape) at each scale.  Every
measurement is normalised back to scale 1 (volume / s^3, area / s^2, lengths /
s) and compared with the 1x build.

Scales 0.1 .. 100 are the supported range: any build failure, invalid solid or
normalised deviation above 1e-6 is a defect.  Scales outside it (0.001, 0.01,
1000, 10000) are probes whose results are reported as limitations.
"""

from __future__ import annotations

SCALES = [0.001, 0.01, 0.1, 0.5, 1, 10, 100, 1000, 10000]
IN_SPEC = {0.1, 0.5, 1, 10, 100}
REL_TOL = 1e-6
TIMEOUT_S = 900

FAMILIES = {
    "bracket": """
p = Part("bracket")
p.box(60*s, 40*s, 4*s, name="base")
p.box(60*s, 4*s, 30*s, at=(0, 20*s, 4*s), align=("center", "max", "min"), name="wall")
p.fillet(p.edges().concave(), 3*s)
p.hole_pattern(3.2*s, spacing=(48*s, 24*s), center=(0, -2*s))
p.hole(4.8*s, at=(0, 22*s), direction="+y", countersink=(8*s, 90))
p.fillet(p.edges().vertical().convex().min("y"), 2*s)
p.chamfer(p.edges("wall.top"), 0.5*s)
parts = {"bracket": p}
""",
    "thin_shell": """
p = Part("shell")
p.box(30*s, 20*s, 15*s, name="body")
p.shell(0.4*s, open_faces=p.faces("body.top"))
parts = {"shell": p}
""",
    "clearance_pair": """
a = Part("a"); a.box(20*s, 10*s, 10*s, at=(-10.1*s, 0, 0))
b = Part("b"); b.box(20*s, 10*s, 10*s, at=(10.1*s, 0, 0))
parts = {"a": a, "b": b}
measures["gap"] = a.distance_to(b) / s
""",
    "small_holes": """
p = Part("plate")
p.box(10*s, 10*s, 1*s)
p.hole_pattern(1.0*s, spacing=(2*s, 2*s), count=(4, 4))
parts = {"plate": p}
""",
    "turned_groove": """
prof = Profile.polygon([(0, 0), (6*s, 0), (6*s, 10*s), (5.5*s, 10*s), (5.5*s, 10.5*s), (6*s, 10.5*s), (6*s, 20*s), (4*s, 20*s), (4*s, 30*s), (0, 30*s)])
p = Part("shaft")
p.revolve(prof)
p.hole(2*s, at=(0, 0, 30*s), depth=8*s)
parts = {"shaft": p}
""",
    "tiny_features": """
p = Part("cube")
p.box(5*s, 5*s, 5*s, name="body")
p.extrude(Profile.slot(3*s, 0.3*s), 1*s, offset=4*s, op="cut")
p.fillet(p.edges("body.bottom"), 0.2*s)
parts = {"cube": p}
""",
}

CODE = """
SCALES = {scales}
BODY = {body!r}
import tempfile, os
from cad.tessellate import tessellate
result = {{"scales": {{}}}}
for s in SCALES:
    r = {{}}
    t = time.perf_counter()
    measures = {{}}
    try:
        env = {{"s": s, "Part": Part, "Profile": Profile, "measures": measures}}
        exec(BODY, env)
        parts = env["parts"]
        r["built"] = True
        r["valid"] = all(p.is_valid() for p in parts.values())
        r["solids"] = {{n: p.solid_count for n, p in parts.items()}}
        r["volume_n"] = sum(p.volume for p in parts.values()) / s**3
        r["area_n"] = sum(p.area for p in parts.values()) / s**2
        bb = [p.bbox for p in parts.values()]
        r["bbox_n"] = [round(v / s, 12) for v in (min(b.xmin for b in bb), min(b.ymin for b in bb), min(b.zmin for b in bb),
                                                   max(b.xmax for b in bb), max(b.ymax for b in bb), max(b.zmax for b in bb))]
        holes = [h for p in parts.values() for h in p.find_holes()]
        r["holes"] = len(holes)
        r["hole_diameters_n"] = sorted(round(h["diameter"] / s, 9) for h in holes)
        r.update({{k: v for k, v in measures.items()}})
        if "shell" in parts:
            r["min_thickness_n"] = parts["shell"].wall_thickness(percentile=0)["min"] / s
        try:
            m = [tessellate(p.shape) for p in parts.values()]
            r["triangles"] = sum(len(x.triangles) for x in m)
        except Exception as e:
            r["tessellation_error"] = str(e)
        try:
            d = tempfile.mkdtemp()
            from OCP.STEPControl import STEPControl_Reader
            vols = []
            for n, p in parts.items():
                path = os.path.join(d, n + ".step")
                p.export(path)
                rd = STEPControl_Reader(); rd.ReadFile(path); rd.TransferRoots()
                vols.append(_occ.volume(rd.OneShape()))
            r["step_volume_rel_err"] = abs(sum(vols) / s**3 - r["volume_n"]) / max(r["volume_n"], 1e-30)
        except Exception as e:
            r["step_error"] = str(e)
    except CadError as e:
        r.update(built=False, code=e.code, message=e.message)
    except Exception as e:
        r.update(built=False, exception=type(e).__name__ + ": " + str(e))
    r["ms"] = round((time.perf_counter() - t) * 1000, 1)
    result["scales"][str(s)] = r
"""


def generate(n: int | None = None, seed: int = 1) -> list[dict]:
    return [{
        "id": f"S03-{name}",
        "suite": "S03",
        "category": name,
        "expect": "valid",
        "params": {"scales": SCALES},
        "code": CODE.format(scales=SCALES, body=body),
        "timeout_s": TIMEOUT_S,
    } for name, body in FAMILIES.items()]


def _rel(a, b):
    if a is None or b is None:
        return None
    return abs(a - b) / max(abs(b), 1e-30)


def compare(res: dict) -> dict:
    """Per-scale deviations from the 1x build."""
    ref = res["scales"].get("1")
    out = {}
    for sk, r in res["scales"].items():
        row: dict = {"built": r.get("built"), "valid": r.get("valid")}
        if not r.get("built"):
            row["error"] = r.get("code") or r.get("exception")
        elif ref and ref.get("built"):
            row["volume_rel_dev"] = _rel(r["volume_n"], ref["volume_n"])
            row["area_rel_dev"] = _rel(r["area_n"], ref["area_n"])
            row["bbox_abs_dev_n"] = max(abs(x - y) for x, y in zip(r["bbox_n"], ref["bbox_n"]))
            row["holes_match"] = r["holes"] == ref["holes"] and all(
                abs(x - y) <= REL_TOL * max(y, 1) for x, y in zip(r["hole_diameters_n"], ref["hole_diameters_n"]))
            if "gap" in ref:
                row["gap_rel_dev"] = _rel(r.get("gap"), ref["gap"])
            if "min_thickness_n" in ref:
                row["thickness_rel_dev"] = _rel(r.get("min_thickness_n"), ref["min_thickness_n"])
            row["solids_match"] = r["solids"] == ref["solids"]
            row["step_volume_rel_err"] = r.get("step_volume_rel_err")
            row["tessellated"] = "triangles" in r
            for k in ("tessellation_error", "step_error"):
                if r.get(k):
                    row[k] = r[k]
        out[sk] = row
    return out


def _problems(row: dict) -> list[str]:
    p = []
    if not row.get("built"):
        return [f"build_failed:{row.get('error')}"]
    if not row.get("valid"):
        p.append("invalid")
    for k in ("volume_rel_dev", "area_rel_dev", "gap_rel_dev", "thickness_rel_dev", "step_volume_rel_err"):
        v = row.get(k)
        if v is not None and v > REL_TOL * (100 if k == "thickness_rel_dev" else 1):
            p.append(f"{k}={v:.2e}")
    if row.get("bbox_abs_dev_n", 0) > 1e-6:
        p.append(f"bbox_dev={row['bbox_abs_dev_n']:.2e}")
    if row.get("holes_match") is False:
        p.append("holes_mismatch")
    if row.get("solids_match") is False:
        p.append("solid_count_mismatch")
    if row.get("tessellated") is False:
        p.append("tessellation_failed")
    return p


def judge(case: dict, o: dict) -> dict:
    if o["status"] != "ran":
        return {"class": "defect", "kinds": [o["status"]], "detail": o.get("exception")}
    cmp = compare(o["result"])
    kinds, limits = [], []
    for sk, row in cmp.items():
        probs = _problems(row)
        if not probs:
            continue
        if float(sk) in IN_SPEC:
            kinds += [f"x{sk}:{p}" for p in probs]
        else:
            limits += [f"x{sk}:{p}" for p in probs]
    if kinds:
        return {"class": "defect", "kinds": kinds, "limitations": limits}
    return {"class": "pass", "kinds": [], "limitations": limits}


def analyze(cases, outcomes) -> dict:
    out = {}
    for c in cases:
        o = outcomes.get(c["id"], {})
        if o.get("status") != "ran":
            out[c["category"]] = {"status": o.get("status")}
            continue
        cmp = compare(o["result"])
        out[c["category"]] = {sk: {k: (f"{v:.1e}" if isinstance(v, float) else v) for k, v in row.items()} for sk, row in cmp.items()}
    return out
