"""S05 — Parameter mutation and topology changes, through the real CLI + daemon.

A parametric bracket project is driven with `cad set` through 200 deterministic
parameter combinations: valid configurations, very thin walls, oversized
fillets, holes approaching (and breaking through) outer edges, exactly tangent
features, merging features and features that disappear.

Per combination:
* the build either succeeds (valid single solid, semantic references intact) or
  fails in a controlled way (structured error, exit code 2-4);
* after a failure the active revision is still the last successful one and
  `cad inspect` works;
* the daemon keeps answering; worker restarts and crashes are counted.
At the end, recovery to an earlier revision (`cad checkout`) and back to the
defaults (`cad unset`, which must hit the build cache) is verified.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAD = ROOT / "target" / "release" / "cad"

DEFAULTS = {"width": 60.0, "depth": 40.0, "thickness": 4.0, "wall_height": 30.0, "wall_thickness": 4.0,
            "hole_d": 3.2, "hole_inset": 6.0, "holes_x": 2, "holes_y": 2, "corner_r": 3.0, "root_r": 2.0,
            "rib_count": 2, "rib_thickness": 3.0}

MODEL = '''"""Parametric bracket used by the S05 mutation stress test."""
from cad import Parameter, Part, Profile

W = Parameter("width", 60.0)
D = Parameter("depth", 40.0)
T = Parameter("thickness", 4.0)
H = Parameter("wall_height", 30.0)
WT = Parameter("wall_thickness", 4.0)
HD = Parameter("hole_d", 3.2)
INSET = Parameter("hole_inset", 6.0)
NX = Parameter("holes_x", 2)
NY = Parameter("holes_y", 2)
CR = Parameter("corner_r", 3.0)
RR = Parameter("root_r", 2.0)
RIBS = Parameter("rib_count", 2)
RT = Parameter("rib_thickness", 3.0)


def build():
    p = Part("bracket")
    p.box(W, D, T, name="base")
    p.box(W, WT, H, at=(0, D / 2, T), align=("center", "max", "min"), name="wall")
    y_wall = D / 2 - WT
    leg = 0.6 * min(H, D - WT)
    for i in range(int(RIBS)):
        x = -W / 2 + (i + 1) * W / (int(RIBS) + 1)
        rib = Profile.polygon([(y_wall, T), (y_wall - leg, T), (y_wall, T + leg)])
        p.extrude(rib, RT, plane="YZ", offset=x, symmetric=True, name=f"rib{i}")
    if RR > 0:
        p.fillet(p.edges().concave().parallel_to("x").min("z"), RR, name="root")
    if CR > 0:
        p.fillet(p.edges("base.front").vertical(), CR, name="corners")
    nx, ny = int(NX), int(NY)
    usable_y = D - WT
    sx = (W - 2 * INSET) / (nx - 1) if nx > 1 else 0
    sy = (usable_y - 2 * INSET) / (ny - 1) if ny > 1 else 0
    if nx > 0 and ny > 0:
        p.hole_pattern(HD, spacing=(sx, sy), count=(nx, ny), center=(0, -D / 2 + usable_y / 2), name="mount")
    p.hole(HD * 1.5, at=(0, T + H / 2), direction="+y", name="wall_hole")
    p.tag("mounting_surface", p.faces("base.bottom"))
    p.tag("wall_face", p.faces("wall.front"))
    return p
'''

CATEGORY_COUNTS = {"valid": 80, "thin_walls": 20, "oversized_fillets": 20, "holes_near_edges": 20,
                   "tangent_features": 20, "merging_features": 20, "disappearing_features": 20}


def _combo(r: random.Random, cat: str) -> dict:
    c = dict(DEFAULTS)
    c["width"] = round(r.uniform(30, 120), 2)
    c["depth"] = round(r.uniform(25, 80), 2)
    c["thickness"] = round(r.uniform(2, 10), 2)
    c["wall_height"] = round(r.uniform(10, 60), 2)
    c["wall_thickness"] = round(r.uniform(2, 8), 2)
    c["hole_d"] = round(r.uniform(2, 6), 2)
    c["hole_inset"] = round(r.uniform(c["hole_d"] + 2, 10), 2)
    c["holes_x"] = r.randint(1, 4)
    c["holes_y"] = r.randint(1, 3)
    c["corner_r"] = round(r.uniform(0.5, 4), 2)
    c["root_r"] = round(r.uniform(0.5, 3), 2)
    c["rib_count"] = r.randint(0, 3)
    c["rib_thickness"] = round(r.uniform(2, 5), 2)
    if cat == "thin_walls":
        key = r.choice(["thickness", "wall_thickness", "rib_thickness"])
        c[key] = round(10 ** r.uniform(-2, -0.5), 4)
    elif cat == "oversized_fillets":
        key = r.choice(["corner_r", "root_r"])
        c[key] = round(r.uniform(1.0, 3.0) * (c["depth"] / 2 if key == "corner_r" else c["wall_height"]), 2)
    elif cat == "holes_near_edges":
        c["hole_inset"] = round(c["hole_d"] / 2 * r.uniform(0.3, 1.2), 3)  # hole may break through the edge
    elif cat == "tangent_features":
        k = r.choice(["hole_edge", "corner_equals_half", "rib_edge"])
        if k == "hole_edge":
            c["hole_inset"] = c["hole_d"] / 2  # hole exactly tangent to the outer edge
        elif k == "corner_equals_half":
            c["corner_r"] = min(c["depth"], c["width"]) / 2  # corner fillet radius equals half the plate
        else:
            c["rib_count"] = 1
            c["rib_thickness"] = c["width"]  # a rib as wide as the plate: faces coincide with the sides
    elif cat == "merging_features":
        c["holes_x"] = r.randint(3, 6)
        c["hole_inset"] = round(r.uniform(2, 4), 2)
        c["hole_d"] = round((c["width"] - 2 * c["hole_inset"]) / (c["holes_x"] - 1) * r.uniform(1.0, 1.5), 3)  # pitch <= diameter
    elif cat == "disappearing_features":
        k = r.choice(["no_ribs", "no_holes", "no_fillets", "tiny_wall"])
        if k == "no_ribs":
            c["rib_count"] = 0
        elif k == "no_holes":
            c["holes_x"] = 0
        elif k == "no_fillets":
            c["corner_r"] = 0.0
            c["root_r"] = 0.0
        else:
            c["wall_height"] = round(10 ** r.uniform(-3, -1), 5)
    return c


def generate(n: int = 200, seed: int = 1) -> list[dict]:
    total = sum(CATEGORY_COUNTS.values())
    plan = []
    for cat, k in CATEGORY_COUNTS.items():
        plan += [cat] * max(1, round(k * n / total))
    rng = random.Random(seed)
    rng.shuffle(plan)
    return [{"id": f"S05-{seed}-{i:03d}", "category": cat, "expect": "valid" if cat == "valid" else "ambiguous",
             "params": _combo(random.Random(f"{seed}-{i}"), cat)} for i, cat in enumerate(plan[:n])]


def run(out: Path, n: int = 200, seed: int = 1, workers: int = 1) -> dict:
    from .harness import environment, write_outputs

    out.mkdir(parents=True, exist_ok=True)
    proj = out / "project"
    proj.mkdir(exist_ok=True)
    (proj / "cad.toml").write_text('[project]\nname = "s05_bracket"\nentry = "model.py"\n')
    (proj / "model.py").write_text(MODEL)
    env = dict(os.environ)
    for k in list(env):
        if k.startswith("CLAUDE") or k == "AI_AGENT":
            env.pop(k)
    env.update(CAD_STATE_DIR=str(out / "state"), CAD_RUNTIME_DIR=str(out / "rt"),
               CAD_PYTHON=str(ROOT / ".venv" / "bin" / "python"))

    def cad(*args, timeout=600):
        t = time.perf_counter()
        try:
            p = subprocess.run([str(CAD), *args, "--json"], cwd=proj, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"exit": "timeout", "ms": round((time.perf_counter() - t) * 1000, 1)}
        try:
            body = json.loads(p.stdout) if p.stdout.strip() else {}
        except json.JSONDecodeError:
            body = {"raw": p.stdout[-500:]}
        return {"exit": p.returncode, "body": body, "stderr": p.stderr[-500:], "ms": round((time.perf_counter() - t) * 1000, 1)}

    def worker_pid():
        st = cad("daemon", "status")
        try:
            ws = [w for w in st["body"]["result"]["workers"] if w["session"].endswith("project")]
            return ws[0]["pid"] if ws else None
        except Exception:
            return None

    cases = generate(n, seed)
    base = cad("build")
    assert base["exit"] == 0, f"default bracket must build: {base}"
    last_good = base["body"]["result"]["revision"]
    first_good = last_good
    pid0 = worker_pid()
    outcomes = {}
    t_start = time.time()
    for i, c in enumerate(cases):
        args = ["set", *[f"{k}={v}" for k, v in c["params"].items()]]
        r = cad(*args)
        o = {"status": "ran", "set": {"exit": r["exit"], "ms": r["ms"]}}
        body = r.get("body") or {}
        if r["exit"] == 0:
            b = body["result"]["build"]
            o["revision"] = b["revision"]
            o["cached"] = b["cached"]
            o["warnings"] = [w.get("code") for w in b.get("warnings", [])]
            part = b["parts"].get("bracket", {})
            o["valid"] = part.get("valid")
            o["solids"] = part.get("solids")
            m = cad("measure", "bracket.mounting_surface")
            ent = ((m.get("body") or {}).get("result") or {}).get("entities", [])
            o["mounting_surface"] = {"exit": m["exit"], "count": len(ent), "normals": [e["normal"] for e in ent]}
            q = cad("measure", "bracket.wall_face")
            o["wall_face_exit"] = q["exit"]
            last_good = b["revision"]
        else:
            err = body.get("error") or {}
            o["error"] = {"code": err.get("code"), "has_hint": bool(err.get("hint")), "feature": err.get("feature"),
                          "message": (err.get("message") or "")[:200]}
        st = cad("status")
        o["daemon_ok"] = st["exit"] == 0
        head = ((st.get("body") or {}).get("result") or {}).get("head")
        o["head"] = head
        o["head_is_last_good"] = head == last_good
        if r["exit"] != 0:
            ins = cad("inspect")
            o["inspect_after_failure"] = {"exit": ins["exit"], "revision": ((ins.get("body") or {}).get("result") or {}).get("revision")}
        pid = worker_pid()
        o["worker_pid"] = pid
        o["worker_restarted"] = pid != pid0
        pid0 = pid
        outcomes[c["id"]] = o
        if (i + 1) % 20 == 0:
            print(f"[S05] {i + 1}/{len(cases)}", flush=True)
    # recovery
    rec = {}
    co = cad("checkout", str(first_good))
    rec["checkout_first"] = co["exit"] == 0 and co["body"]["result"]["head"] == first_good
    ins = cad("inspect")
    rec["inspect_after_checkout"] = ins["exit"] == 0 and ins["body"]["result"]["revision"] == first_good
    un = cad("unset", *DEFAULTS.keys())
    ub = ((un.get("body") or {}).get("result") or {}).get("build") or {}
    rec["defaults_rebuild_cached"] = un["exit"] == 0 and ub.get("cached") is True and ub.get("revision") == first_good
    ds = cad("daemon", "status")
    rec["daemon_alive_at_end"] = ds["exit"] == 0
    rec["revisions"] = len(((cad("revisions").get("body") or {}).get("result") or {}).get("revisions", []))
    cad("daemon", "stop")
    summary = write_outputs(out, "S05", [dict(c, code="") for c in cases], outcomes, judge,
                            meta={"seed": seed, "workers": 1, "wall_s": round(time.time() - t_start, 1), "recovery": rec,
                                  "analysis": analyze(cases, outcomes)})
    return summary


def judge(case: dict, o: dict) -> dict:
    kinds = []
    if not o.get("daemon_ok"):
        kinds.append("daemon_unavailable")
    if o.get("worker_restarted"):
        kinds.append("worker_restarted")
    ex = o["set"]["exit"]
    if ex in (1, 6, 7, 8, "timeout"):
        kinds.append(f"exit_{ex}")
    if ex == 0:
        notes = []
        if not o.get("valid"):
            kinds.append("accepted_invalid_geometry")
        elif o.get("solids") != 1:
            # a configuration that severs the part is the input's fault, but it must be reported
            if any(w in ("BODY_SPLIT", "DISCONNECTED_BODIES") for w in o.get("warnings", [])):
                notes.append("split_reported")
            else:
                kinds.append("silently_disconnected_solids")
        ms = o.get("mounting_surface") or {}
        # the tagged face may be split into pieces by later cuts; every piece must still be the downward face
        if not ms.get("count") or any(n != [0.0, 0.0, -1.0] for n in ms.get("normals", [])):
            kinds.append("mounting_surface_reference_unstable")
        if o.get("wall_face_exit") != 0:
            kinds.append("wall_face_reference_unstable")
        if not o.get("head_is_last_good"):
            kinds.append("head_not_new_revision")
        if kinds:
            return {"class": "defect", "kinds": kinds}
        return {"class": "controlled" if notes else "pass", "kinds": notes}
    err = o.get("error") or {}
    if not err.get("code"):
        kinds.append("unstructured_failure")
    elif not err.get("has_hint") and err.get("code") not in ("PARAMETER_OUT_OF_RANGE",):
        kinds.append("error_without_hint")
    if not o.get("head_is_last_good"):
        kinds.append("failed_build_moved_head")
    ins = o.get("inspect_after_failure") or {}
    if ins.get("exit") != 0:
        kinds.append("inspect_broken_after_failure")
    if case["expect"] == "valid":
        kinds.append(f"failed_on_valid_input:{err.get('code')}")
    hard = [k for k in kinds if k != "error_without_hint"]
    if hard:
        return {"class": "defect", "kinds": kinds}
    return {"class": "controlled", "kinds": kinds}


def analyze(cases, outcomes) -> dict:
    from collections import Counter, defaultdict

    by = defaultdict(Counter)
    errors = Counter()
    ms = []
    for c in cases:
        o = outcomes[c["id"]]
        by[c["category"]]["ok" if o["set"]["exit"] == 0 else "failed"] += 1
        if o.get("error"):
            errors[(c["category"], o["error"]["code"])] += 1
        ms.append(o["set"]["ms"])
    ms.sort()
    return {"outcomes_by_category": {k: dict(v) for k, v in by.items()},
            "error_codes": {f"{a}:{b}": n for (a, b), n in errors.most_common()},
            "set_and_build_ms": {"median": ms[len(ms) // 2], "p95": ms[int(len(ms) * 0.95)], "max": ms[-1]}}
