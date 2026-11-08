# S01 case S01-1-0222 (partial_overlap, input: valid)
# verdict: {'class': 'defect', 'kinds': ['intersect:failed_on_valid_input:NO_BODY', 'union:unexpected_solid_count']}
# run: uv run python /Users/andrew/dev/github/clicd/stress-runs/S01-seed1-20261107-182715/failures/S01-1-0222/repro.py
import math, time
from cad import CadError, Part, Profile, Plane, _occ

SPEC_A = {"kind": "box", "size": [48.818, 39.208, 32.286], "at": [0, 0, 0]}
SPEC_B = {"kind": "cyl", "d": 5.097, "h": 62.042, "axis": "y", "at": [6.007, 16.627, 18.786]}
OPS = ["union", "cut", "intersect"]

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
result = {"VA": A.volume, "VB": B.volume, "ops": {}}
for op in OPS:
    r = {}
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

print(result)
