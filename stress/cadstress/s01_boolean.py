"""S01 — Boolean robustness.

Pairs of solids with controlled overlap: fully overlapping, partially
overlapping, face-touching, edge-touching, nearly tangent, small intersection
volume and nearly coincident faces.  Each case runs union, cut (A - B) and
intersect through the public Part API.

Expected values:
* axis-aligned box pairs: exact analytic volumes for all three operations;
* everything else: the Boolean identities
  V(A u B) + V(A n B) = V(A) + V(B)   and   V(A - B) = V(A) - V(A n B).
Touching configurations have an empty intersection, so ``intersect`` must fail
in a controlled way (``NO_BODY``) or return (numerically) nothing.

Input classes: ``valid`` (a definite answer exists, the operation must succeed
with it), ``ambiguous`` (gaps/overlaps near the kernel tolerance: any
controlled outcome is acceptable, but never a crash, an invalid solid or a
volume outside the perturbation bound).
"""

from __future__ import annotations

import json
import math
import random

OPS = ("union", "cut", "intersect")
CATEGORY_COUNTS = {
    "full_overlap": 120,
    "partial_overlap": 220,
    "face_touch": 130,
    "edge_touch": 110,
    "nearly_tangent": 140,
    "small_intersection": 140,
    "nearly_coincident": 140,
}

CODE = """
SPEC_A = {a}
SPEC_B = {b}
OPS = {ops}

def mk(spec, name):
    p = Part(name)
    k = spec["kind"]
    if k == "box":
        p.box(*spec["size"], at=spec["at"], align="center")
    elif k == "cyl":
        p.cylinder(spec["d"], spec["h"], at=spec["at"], axis=spec["axis"], align="center")
    elif k == "sphere":
        p.sphere(spec["d"], at=spec["at"])
    if spec.get("rot"):
        p.rotate(spec["rot"][0], axis=spec["rot"][1], center=spec["at"])
    return p

A = mk(SPEC_A, "A")
B = mk(SPEC_B, "B")
result = {{"VA": A.volume, "VB": B.volume, "ops": {{}}}}
for op in OPS:
    r = {{}}
    t = time.perf_counter()
    try:
        P = A.copy()
        f = getattr(P, op)(B)
        r.update(ok=True, volume=P.volume, valid=P.is_valid(), solids=P.solid_count,
                 shells=sum(len(_occ.shells(s)) for s in _occ.solids(P.shape)),
                 warnings=[w.code for w in f.warnings])
    except CadError as e:
        r.update(ok=False, code=e.code, message=e.message, hint=e.hint)
    r["ms"] = round((time.perf_counter() - t) * 1000, 3)
    result["ops"][op] = r
"""


def _box(rng, lo=3.0, hi=60.0):
    return [round(rng.uniform(lo, hi), 3) for _ in range(3)]


def _inter_1d(c1, s1, c2, s2):
    lo = max(c1 - s1 / 2, c2 - s2 / 2)
    hi = min(c1 + s1 / 2, c2 + s2 / 2)
    return max(0.0, hi - lo)


def _analytic_boxes(a, b):
    va = math.prod(a["size"])
    vb = math.prod(b["size"])
    vi = math.prod(_inter_1d(a["at"][i], a["size"][i], b["at"][i], b["size"][i]) for i in range(3))
    return {"union": va + vb - vi, "cut": va - vi, "intersect": vi}


def generate(n: int = 1000, seed: int = 1) -> list[dict]:
    rng = random.Random(seed)
    total = sum(CATEGORY_COUNTS.values())
    plan = []
    for cat, k in CATEGORY_COUNTS.items():
        plan += [cat] * max(1, round(k * n / total))
    plan = plan[:n]
    cases = []
    for i, cat in enumerate(plan):
        r = random.Random(f"{seed}-{i}")
        a, b, expect, info = GEN[cat](r)
        params = {"A": a, "B": b, **info}
        analytic = _analytic_boxes(a, b) if a["kind"] == b["kind"] == "box" and not a.get("rot") and not b.get("rot") else None
        cases.append({
            "id": f"S01-{seed}-{i:04d}",
            "suite": "S01",
            "category": cat,
            "expect": expect,
            "params": {**params, "analytic": analytic},
            "code": CODE.format(a=repr(a), b=repr(b), ops=json.dumps(list(OPS))),
            "timeout_s": 60,
        })
    return cases


# ----------------------------------------------------------------------------- generators


def g_full(r):
    a = {"kind": "box", "size": _box(r, 10, 60), "at": [0, 0, 0]}
    m = 0.5
    inner = [max(0.5, s - 2 * m) for s in a["size"]]
    kind = r.choice(["box", "cyl", "sphere"])
    if kind == "box":
        size = [round(r.uniform(0.3, 0.95) * s, 3) for s in inner]
        room = [(i - s) / 2 for i, s in zip(inner, size)]
        b = {"kind": "box", "size": size, "at": [round(r.uniform(-q, q), 3) for q in room]}
    elif kind == "sphere":
        d = round(r.uniform(0.3, 0.95) * min(inner), 3)
        room = [(i - d) / 2 for i in inner]
        b = {"kind": "sphere", "d": d, "at": [round(r.uniform(-q, q), 3) for q in room]}
    else:
        ax = r.choice("xyz")
        i = "xyz".index(ax)
        others = [inner[j] for j in range(3) if j != i]
        d = round(r.uniform(0.3, 0.95) * min(others), 3)
        h = round(r.uniform(0.3, 0.95) * inner[i], 3)
        ext = [d] * 3
        ext[i] = h
        room = [(inn - e) / 2 for inn, e in zip(inner, ext)]
        b = {"kind": "cyl", "d": d, "h": h, "axis": ax, "at": [round(r.uniform(-q, q), 3) for q in room]}
    return a, b, "valid", {"note": "B strictly inside A (cut leaves an internal void)"}


def g_partial(r):
    """B's centre lies strictly inside A and B protrudes through A's face j; B is smaller
    than A along another axis, so neither contains the other."""
    a = {"kind": "box", "size": _box(r, 8, 50), "at": [0, 0, 0]}
    j = r.randrange(3)
    k = r.choice([x for x in range(3) if x != j])
    at = [round(r.uniform(-0.3, 0.3) * s, 3) for s in a["size"]]
    at[j] = round(r.choice([-1, 1]) * a["size"][j] / 2 * r.uniform(0.5, 0.9), 3)
    reach = a["size"][j] / 2 - abs(at[j])          # distance from B's centre to A's face j
    kind = r.choice(["box", "box", "rbox", "cyl", "cyl", "sphere"])
    if kind in ("box", "rbox"):
        size = _box(r, 4, 40)
        size[j] = round(2 * reach + r.uniform(1, 20), 3)
        size[k] = round(min(size[k], a["size"][k] * 0.8), 3)
        b = {"kind": "box", "size": size, "at": at}
        if kind == "rbox":
            b["rot"] = [round(r.uniform(5, 85), 2), "xyz"[k]]  # rotation keeps B's centre inside A
    elif kind == "cyl":
        axis = j if r.random() < 0.5 else k
        d = round(min(r.uniform(3, 30), a["size"][k] * 0.8), 3)
        h = round(2 * reach + r.uniform(1, 40), 3) if axis == j else round(r.uniform(5, 80), 3)
        if axis != j:
            d = round(max(d, 2 * reach + 1), 3)
        b = {"kind": "cyl", "d": d, "h": h, "axis": "xyz"[axis], "at": at}
    else:
        d = round(2 * reach + r.uniform(1, 20), 3)
        b = {"kind": "sphere", "d": d, "at": at}
        if d >= math.dist([0, 0, 0], a["size"]):  # a sphere this large could swallow A
            b["d"] = round(2 * reach + 1, 3)
    return a, b, "valid", {"note": "B centred inside A, protruding through one face"}


def g_face_touch(r):
    a = {"kind": "box", "size": _box(r, 5, 50), "at": [0, 0, 0]}
    sb = _box(r, 3, 40)
    j = r.randrange(3)
    side = r.choice([-1, 1])
    at = [0.0, 0.0, 0.0]
    at[j] = side * (a["size"][j] + sb[j]) / 2  # exactly coincident faces
    for k in range(3):
        if k != j:  # lateral offset so the faces overlap only partly, but still share area
            lim = (a["size"][k] + sb[k]) / 2 * 0.8
            at[k] = round(r.uniform(-lim, lim), 3)
    b = {"kind": "box", "size": sb, "at": at}
    return a, b, "valid", {"note": "faces coincide exactly; intersection is empty"}


def g_edge_touch(r):
    a = {"kind": "box", "size": _box(r, 5, 50), "at": [0, 0, 0]}
    sb = _box(r, 3, 40)
    j, k = r.sample(range(3), 2)
    at = [0.0, 0.0, 0.0]
    at[j] = r.choice([-1, 1]) * (a["size"][j] + sb[j]) / 2
    at[k] = r.choice([-1, 1]) * (a["size"][k] + sb[k]) / 2
    m = 3 - j - k
    lim = (a["size"][m] + sb[m]) / 2 * 0.8
    at[m] = round(r.uniform(-lim, lim), 3)
    b = {"kind": "box", "size": sb, "at": at}
    return a, b, "ambiguous", {"note": "solids share only an edge segment (union may be one non-manifold solid or two)"}


def _eps(r, lo_exp, hi_exp):
    return r.choice([-1, 1]) * 10 ** r.uniform(lo_exp, hi_exp)


def g_tangent(r):
    a = {"kind": "box", "size": _box(r, 10, 50), "at": [0, 0, 0]}
    j = r.randrange(3)  # face normal axis
    ax_choices = [x for x in range(3) if x != j]
    ax = r.choice(ax_choices)
    d = round(r.uniform(2, 20), 3)
    eps = _eps(r, -8, -2)  # + gap, - overlap depth
    at = [0.0, 0.0, 0.0]
    side = r.choice([-1, 1])
    at[j] = side * (a["size"][j] / 2 + d / 2 + eps)
    other = 3 - j - ax
    at[other] = round(r.uniform(-0.3, 0.3) * a["size"][other], 3)
    b = {"kind": "cyl", "d": d, "h": round(a["size"][ax] * r.uniform(0.5, 1.5), 3), "axis": "xyz"[ax], "at": at}
    expect = "ambiguous" if abs(eps) < 1e-5 else "valid"
    return a, b, expect, {"eps": eps, "note": "cylinder tangent to a face, offset by eps (+gap / -overlap)"}


def g_small(r):
    a = {"kind": "box", "size": _box(r, 5, 50), "at": [0, 0, 0]}
    sb = _box(r, 3, 40)
    j = r.randrange(3)
    delta = 10 ** r.uniform(-5, -1)  # overlap depth
    at = [0.0, 0.0, 0.0]
    at[j] = r.choice([-1, 1]) * ((a["size"][j] + sb[j]) / 2 - delta)
    for k in range(3):
        if k != j:
            lim = (a["size"][k] + sb[k]) / 2 * 0.7
            at[k] = round(r.uniform(-lim, lim), 3)
    b = {"kind": "box", "size": sb, "at": at}
    return a, b, "valid", {"delta": delta, "note": "overlap depth delta along one axis"}


def g_coincident(r):
    a = {"kind": "box", "size": _box(r, 5, 50), "at": [0, 0, 0]}
    j = r.randrange(3)
    eps = _eps(r, -9, -4)
    sb = [round(s * r.uniform(0.3, 0.9), 3) for s in a["size"]]
    sb[j] = round(a["size"][j] * r.uniform(0.3, 0.7), 3)
    at = [round(r.uniform(-0.1, 0.1) * s, 3) for s in a["size"]]
    side = r.choice([-1, 1])
    # B's outer face sits eps outside (+) or inside (-) A's face
    at[j] = side * (a["size"][j] / 2 + eps - sb[j] / 2)
    b = {"kind": "box", "size": sb, "at": at}
    expect = "ambiguous" if abs(eps) < 1e-6 else "valid"
    return a, b, expect, {"eps": eps, "note": "B's face nearly coincides with A's face (offset eps)"}


GEN = {
    "full_overlap": g_full,
    "partial_overlap": g_partial,
    "face_touch": g_face_touch,
    "edge_touch": g_edge_touch,
    "nearly_tangent": g_tangent,
    "small_intersection": g_small,
    "nearly_coincident": g_coincident,
}

# ----------------------------------------------------------------------------- judging


def _slack(case, va, vb) -> float:
    """Volume tolerance: relative round-off plus the perturbation an ambiguous input allows."""
    p = case["params"]
    tol = 1e-6 * (va + vb) + 1e-9
    if "eps" in p:
        a = p["A"]["size"]
        tol += abs(p["eps"]) * 2 * max(a[0] * a[1], a[1] * a[2], a[0] * a[2]) * 2
    return tol


def judge(case: dict, o: dict) -> dict:
    cat = case["category"]
    expect = case["expect"]
    if o["status"] in ("crash", "timeout", "missing"):
        return {"class": "defect", "kinds": [o["status"]]}
    if o["status"] == "exception":
        return {"class": "defect", "kinds": ["uncaught_exception"], "detail": o.get("exception")}
    res = o["result"]
    va, vb = res["VA"], res["VB"]
    ops = res["ops"]
    tol = _slack(case, va, vb)
    kinds, notes = [], []
    analytic = case["params"].get("analytic")
    # touching pairs share no volume; a tangent cylinder with a positive gap does not touch at all.
    # (nearly coincident pairs overlap heavily by construction: only one face nearly coincides)
    empty_expected = cat in ("face_touch", "edge_touch") or (cat == "nearly_tangent" and case["params"]["eps"] > 0)

    def vol(op):
        r = ops[op]
        if r["ok"]:
            return r["volume"]
        if r.get("code") == "NO_BODY":
            return 0.0
        return None

    for op, r in ops.items():
        if r["ok"]:
            if not r["valid"]:
                kinds.append(f"{op}:invalid_result")
        else:
            code = r.get("code")
            controlled_empty = code == "NO_BODY" and (op == "intersect" or (op == "cut" and False))
            if op == "intersect" and code == "NO_BODY" and (empty_expected or expect == "ambiguous"):
                continue
            if expect == "ambiguous":
                notes.append(f"{op}:controlled_error:{code}")
                continue
            kinds.append(f"{op}:failed_on_valid_input:{code}")
            if not r.get("hint"):
                kinds.append(f"{op}:error_without_hint")
    vu, vc, vi = vol("union"), vol("cut"), vol("intersect")
    if analytic:
        for op, v in (("union", vu), ("cut", vc), ("intersect", vi)):
            if v is not None and abs(v - analytic[op]) > tol:
                kinds.append(f"{op}:wrong_volume")
    if vu is not None and vi is not None and abs(vu + vi - va - vb) > tol:
        kinds.append("identity:union+intersect")
    if vc is not None and vi is not None and abs(vc - (va - vi)) > tol:
        kinds.append("identity:cut")
    # topology expectations
    u = ops["union"]
    if u["ok"]:
        if cat in ("full_overlap", "partial_overlap", "face_touch", "small_intersection") and u["solids"] != 1:
            kinds.append("union:unexpected_solid_count")
        if cat == "edge_touch" and u["solids"] not in (1, 2):
            kinds.append("union:unexpected_solid_count")
        if cat in ("nearly_tangent", "nearly_coincident") and expect == "valid":
            want = (2 if case["params"]["eps"] > 0 else 1) if cat == "nearly_tangent" else 1
            if want and u["solids"] != want:
                kinds.append("union:unexpected_solid_count")
    c = ops["cut"]
    if c["ok"] and cat == "full_overlap" and c["shells"] != 2:
        kinds.append("cut:expected_internal_void")
    i = ops["intersect"]
    if i["ok"] and empty_expected and expect == "valid" and i["volume"] > tol:
        kinds.append("intersect:nonempty_for_touching")
    if expect == "ambiguous":
        # only hard failures count for ambiguous inputs
        hard = [k for k in kinds if k.endswith("invalid_result") or k.startswith("identity") or k.endswith("wrong_volume")]
        if hard:
            return {"class": "defect", "kinds": hard, "notes": notes}
        return {"class": "pass" if not notes else "controlled", "kinds": [], "notes": notes}
    if kinds:
        return {"class": "defect", "kinds": kinds}
    return {"class": "pass", "kinds": []}


def minimize(case: dict, outcome: dict) -> dict | None:
    """Reduce to the first failing operation only."""
    res = outcome.get("result") or {}
    ops = res.get("ops") or {}
    bad = [op for op, r in ops.items() if not r.get("ok") or not r.get("valid", True)]
    op = bad[0] if bad else None
    if not op:
        return None
    code = case["code"].replace(f"OPS = {json.dumps(list(OPS))}", f"OPS = {json.dumps([op])}")
    return {"code": code, "note": f"only the {op} operation"}
