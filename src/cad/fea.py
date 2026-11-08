"""Linear static stress analysis (``cad fea``): where a part is most stressed, and by how much.

Pipeline: the part's exact BRep is meshed into tetrahedra by gmsh (in a separate
process, see ``_fea_mesh.py``), loads and supports from a :class:`~cad.Study` are
applied to the mesh faces that came from the referenced BRep faces, and linear
elasticity is solved with quadratic (10-node) tetrahedra in scikit-fem, using
algebraic multigrid (pyamg) for larger meshes.  Stresses are averaged onto the
mesh vertices; hot spots are the separate high-stress regions, each traced back
to the BRep faces (and so the feature) it sits on.

Assumptions (all reported): small deflections, linear elastic isotropic material,
printed parts treated as solid (100 % infill) with a separate strength across
layers.  The optional dependencies are gmsh (GPL), scikit-fem, scipy and pyamg.
"""

from __future__ import annotations

import importlib.util
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import _occ
from .errors import INVALID_ARGUMENT, CadError

FEA_UNAVAILABLE = "FEA_UNAVAILABLE"
MESH_FAILED = "MESH_FAILED"
UNDERCONSTRAINED = "UNDERCONSTRAINED"
SOLVE_FAILED = "SOLVE_FAILED"

PACKAGES = {"gmsh": "gmsh", "skfem": "scikit-fem", "scipy": "scipy", "pyamg": "pyamg"}  # module -> pip name
QUALITY = {  # bbox diagonal / max element size, elements per full circle on curved faces, hot-spot refinement
    "draft": (12, 6, None),  # one pass
    "normal": (24, 8, 0.4),  # second pass with elements this fraction of the size around the hot spots
    "fine": (42, 14, 1 / 4),
}
SOLVER_VERSION = "fea-16"
DIRECT_SOLVE_MAX_DOFS = 8_000
MAX_DOFS = 3_000_000


# --------------------------------------------------------------------------- dependencies


def missing() -> list[str]:
    """pip names of the optional packages that are not installed."""
    return [pip for mod, pip in PACKAGES.items() if importlib.util.find_spec(mod) is None]


def install_hint(names: list[str] | None = None) -> str:
    names = names or list(PACKAGES.values())
    exe = sys.executable
    pkgs = " ".join(names)
    cmd = f"uv pip install --python {exe} {pkgs}" if shutil.which("uv") else f"{exe} -m pip install {pkgs}"
    return (f"install them into cad's Python environment: {cmd}   (from a source checkout: scripts/install.sh --fea). "
            "They are optional because gmsh, the mesher, is GPL-licensed.")


def require() -> None:
    miss = missing()
    if miss:
        raise CadError(FEA_UNAVAILABLE, f"stress analysis needs optional packages that are not installed: {', '.join(miss)}",
                       hint=install_hint(miss), details={"missing": miss, "python": sys.executable})


# --------------------------------------------------------------------------- material


@dataclass
class Mech:
    name: str
    E: float
    nu: float
    strength: float
    layer_strength: float | None
    density: float | None
    assumed: list[str]

    def to_dict(self) -> dict:
        return {"name": self.name, "youngs_modulus_MPa": self.E, "poisson_ratio": self.nu, "yield_strength_MPa": self.strength,
                "layer_strength_MPa": self.layer_strength, "density_g_cm3": self.density, "assumed": self.assumed}


def mechanical(material) -> Mech:
    """Mechanical properties of a part's material, filling gaps from PLA (and saying so)."""
    from .materials import LIBRARY

    pla = LIBRARY["pla"]
    if material is None:
        return Mech("PLA", pla.youngs_modulus, pla.poisson_ratio, pla.yield_strength, pla.layer_strength, pla.density,
                    ["the part has no material: assumed PLA"])
    assumed = []
    vals = {}
    for f, default in (("youngs_modulus", pla.youngs_modulus), ("yield_strength", pla.yield_strength)):
        v = getattr(material, f)
        if v is None:
            assumed.append(f"{f} not given for {material.name}: used PLA's {default} MPa")
            v = default
        vals[f] = v
    nu = material.poisson_ratio if material.poisson_ratio is not None else 0.35
    if material.poisson_ratio is None:
        assumed.append("poisson_ratio not given: used 0.35")
    layer = material.layer_strength
    if layer is None and material.kind == "filament":
        layer = 0.55 * vals["yield_strength"]
        assumed.append(f"layer_strength not given for a filament: used 55 % of yield ({layer:.0f} MPa)")
    return Mech(material.name, float(vals["youngs_modulus"]), float(nu), float(vals["yield_strength"]),
                float(layer) if layer is not None else None, material.density, assumed)


# --------------------------------------------------------------------------- meshing


@dataclass
class TetMesh:
    nodes: np.ndarray  # (N, 3)
    tets: np.ndarray  # (T, 4), or (T, 10) for curved quadratic elements (gmsh node order)
    tris: np.ndarray  # (S, 3) boundary triangles (vertex indices)
    tri_face: np.ndarray  # (S,) BRep face index (in _occ.faces order) of each boundary triangle
    size: float
    seconds: float
    typical_wall: float | None = None  # mm, 25th percentile of sampled wall thickness
    tri_mid: np.ndarray | None = None  # (S, 3, 3) positions of each boundary triangle's edge midpoints 01, 12, 20 (on the surface)


def mesh_sizes(part, quality: str) -> dict:
    if quality not in QUALITY:
        raise CadError(INVALID_ARGUMENT, f"unknown quality {quality!r}", hint=f"use one of {', '.join(QUALITY)}")
    n, curv, _ = QUALITY[quality]
    lo, hi = _occ.bbox(part.shape)
    diag = math.dist(lo, hi)
    h = diag / n
    thin, refine, typical_wall = None, [], None
    try:
        from .analysis import thickness_samples

        samples = sorted(thickness_samples(part, 5), key=lambda x: x["thickness"])
    except Exception:  # thickness sampling is a refinement, never a blocker
        samples = []
    if samples:
        # about one quadratic element through typical walls everywhere, and through the thinnest
        # spots (ligaments beside holes, thin ribs) only locally
        typical = samples[len(samples) // 4]["thickness"]
        typical_wall = typical
        thin = samples[0]["thickness"]
        h = min(h, max(typical, diag / 200))
        for smp in samples:
            t = smp["thickness"]
            if t >= 0.8 * h or len(refine) >= 24:
                break
            if all(math.dist(smp["point"], r[:3]) > 3 * max(t, r[4]) for r in refine):
                refine.append([*smp["point"], 3 * t, max(t, diag / 400)])
    return {"size_max": h, "size_min": max(h / 10, diag / 1000), "curvature": curv, "diag": diag, "thinnest_wall": thin,
            "order": 2, "refine": refine, "typical_wall": typical_wall}


def mesh_part(part, quality: str = "normal", *, refine: list | None = None, timeout: float = 600) -> TetMesh:
    """``refine``: [(x, y, z, radius, size)] balls of smaller elements."""
    require()
    from OCP.BRepTools import BRepTools

    sizes = mesh_sizes(part, quality)
    sizes["refine"] = sizes["refine"] + [[float(c) for c in r] for r in refine or []]
    if sizes["refine"]:
        sizes["size_min"] = min(sizes["size_min"], min(r[4] for r in sizes["refine"]))
    script = Path(__file__).with_name("_fea_mesh.py")
    with tempfile.TemporaryDirectory(prefix="cad-fea-") as td:
        brep, out = Path(td) / "part.brep", Path(td) / "mesh.npz"
        BRepTools.Write_s(part.shape, str(brep))
        t0 = time.perf_counter()
        try:
            r = subprocess.run([sys.executable, "-I", str(script), str(brep), str(out), json.dumps(sizes)],
                               capture_output=True, text=True, timeout=timeout, cwd=td)
        except subprocess.TimeoutExpired:
            raise CadError(MESH_FAILED, f"meshing took longer than {timeout:.0f} s",
                           hint="try --quality draft, or simplify tiny features (text, threads) that need very small elements") from None
        if r.returncode != 0 or not out.exists():
            msg = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"exit code {r.returncode}"
            try:
                msg = json.loads(msg)["error"]
            except (ValueError, KeyError, TypeError):
                pass
            raise CadError(MESH_FAILED, f"gmsh could not mesh part '{part.name}': {msg}",
                           hint="check `cad validate`; tiny slivers or self-touching faces stop meshing. --quality draft can help")
        d = np.load(out)
        nodes, tets, tris, owner = d["nodes"], d["tets"], d["tris"], d["tri_surface"]
        tri_mid = nodes[d["tri_mid"]] if "tri_mid" in d.files else None
        com, area = d["surface_com"], d["surface_area"]
    face_of_surface = _match_surfaces(part.shape, com, area, sizes["diag"])
    return TetMesh(nodes, tets, tris, face_of_surface[owner], sizes["size_max"], time.perf_counter() - t0, sizes["typical_wall"],
                   tri_mid)


def _match_surfaces(shape, com: np.ndarray, area: np.ndarray, diag: float) -> np.ndarray:
    """gmsh surface -> BRep face index, by exact centre of mass and area."""
    faces = _occ.faces(shape)
    fc = np.array([_occ.face_centroid(f) for f in faces])
    fa = np.array([_occ.area(f) for f in faces])
    out = np.empty(len(com), dtype=np.int64)
    for i, (c, a) in enumerate(zip(com, area)):
        score = np.linalg.norm(fc - c, axis=1) / diag + np.abs(fa - a) / max(a, 1e-12)
        j = int(np.argmin(score))
        if score[j] > 1e-3:
            raise CadError(MESH_FAILED, "the mesher changed the part's faces (could not match them back)",
                           hint="the part may have a defect gmsh repaired; check `cad validate`")
        out[i] = j
    if len(set(out.tolist())) != len(out):
        raise CadError(MESH_FAILED, "two mesh surfaces matched the same face of the part")
    return out


# --------------------------------------------------------------------------- solving


@dataclass
class Solution:
    report: dict
    arrays: dict  # for rendering: see save()

    def save(self, path: Path) -> None:
        np.savez_compressed(path, **self.arrays)


def analyse(part, spec: dict, quality: str = "normal", *, base_mesh: TetMesh | None = None) -> tuple[Solution, TetMesh]:
    """Solve a study; for normal / fine quality solve again with finer elements around the hot spots,
    which sharpens the peaks and shows whether they have converged (a peak that keeps rising sits on a
    sharp inside corner).  Returns the final solution and the first-pass mesh (reusable by other studies
    of the same part)."""
    if quality not in QUALITY:
        raise CadError(INVALID_ARGUMENT, f"unknown quality {quality!r}", hint=f"use one of {', '.join(QUALITY)}")
    base = base_mesh if base_mesh is not None else mesh_part(part, quality)
    first = solve(part, spec, quality=quality, mesh=base)
    factor = QUALITY[quality][2]
    if factor is None:
        first.report["convergence"] = {"passes": 1, "note": "draft: one mesh pass; peaks can read 5-15 % low"}
        return first, base
    r1 = first.report
    lo, hi = _occ.bbox(part.shape)
    diag = math.dist(lo, hi)
    radius = max(2 * base.size, 0.02 * diag)
    balls = []
    for h in r1["hotspots"][:3]:  # finer around each hot spot, finer still on small fillets and holes
        radii = [] if h.get("at_support") else [f["radius"] for f in h["faces"] if f.get("radius")]
        size = max(min([base.size * factor] + [0.4 * r for r in radii]), diag / 500)
        balls.append((*h["at"], max(3 * size, min(radius, 8 * size)), size))
    if not any(np.allclose(b[:3], r1["max_von_mises_at"]) for b in balls):
        balls.append((*r1["max_von_mises_at"], radius, base.size * factor))
    pts = [b[:3] for b in balls]
    fine_mesh = mesh_part(part, quality, refine=balls)
    second = solve(part, spec, quality=quality, mesh=fine_mesh)
    r2 = second.report
    V1, vm1 = first.arrays["vertices"], first.arrays["von_mises"]

    def before(point) -> float:
        d = np.linalg.norm(V1 - np.asarray(point), axis=1)
        return float(vm1[d <= max(base.size, d.min() + 1e-9)].max())

    peak_change = (r2["max_von_mises_MPa"] - r1["max_von_mises_MPa"]) / max(r2["max_von_mises_MPa"], 1e-12)
    for h in r2["hotspots"]:
        b = before(h["at"])
        h["change_on_refinement_pct"] = round(100 * (h["von_mises_MPa"] - b) / max(h["von_mises_MPa"], 1e-12), 1)
    _convergence_warnings(r2)
    for w in r2["warnings"]:
        if w["code"] == "STRESS_SINGULARITY":
            h = next(x for x in r2["hotspots"] if x["id"] == w["hotspot"])
            w["message"] += f" (it rose {h['change_on_refinement_pct']:g} % with a finer mesh)"
    r2["convergence"] = {"passes": 2, "peak_change_pct": round(100 * peak_change, 1),
                         "first_pass_peak_MPa": r1["max_von_mises_MPa"],
                         "refined_element_size_mm": round(min(b[4] for b in balls), 4),
                         "refined_around": [[round(c, 3) for c in p] for p in pts]}
    r2["seconds"]["first_pass"] = r1["seconds"]["total"]
    r2["seconds"]["total"] = round(r1["seconds"]["total"] + r2["seconds"]["total"], 3)
    r2["mesh"]["first_pass_tetrahedra"] = r1["mesh"]["tetrahedra"]
    return second, base


def _convergence_warnings(r: dict) -> None:
    for h in r["hotspots"]:
        ch = h.get("change_on_refinement_pct", 0)
        if ch <= 12:
            continue
        if h.get("at_support") or h.get("sharp_edge"):
            continue  # PEAK_AT_SUPPORT / STRESS_SINGULARITY already explain it
        else:
            r["warnings"].append({"code": "MESH_COARSE", "hotspot": h["id"],
                                  "message": f"hotspot {h['id']} changed {ch:g} % when the mesh was refined, so it has not settled",
                                  "hint": "re-run with --quality fine before trusting the peak"})


def solve(part, spec: dict, *, quality: str = "normal", mesh: TetMesh | None = None) -> Solution:
    """Solve one study (the dict from Study.resolve) on ``part``."""
    require()
    import scipy.sparse.linalg as sla
    from skfem import Basis, ElementTetP2, ElementVector, FacetBasis, LinearForm, MeshTet, asm, condense
    from skfem.models.elasticity import lame_parameters, linear_elasticity

    t_start = time.perf_counter()
    mat = mechanical(part.material)
    warnings: list[dict] = []
    tm = mesh if mesh is not None else mesh_part(part, quality)
    t_mesh = tm.seconds
    m, tris = _skfem_mesh(tm)
    # loads are integrated on the straight-sided version of the mesh (same vertices, same dof numbering):
    # inverting the curved mapping at surface points can fail on strongly curved elements
    mflat = MeshTet(np.ascontiguousarray(m.p[:, :int(m.t.max()) + 1]), np.ascontiguousarray(m.t)) if tm.tets.shape[1] == 10 else m
    e = ElementVector(ElementTetP2())
    ib = Basis(m, e, intorder=2)
    if ib.N > MAX_DOFS:
        raise CadError(SOLVE_FAILED, f"the mesh is too large to solve ({ib.N} unknowns)", hint="use --quality draft")
    facet_of_tri = _facets_of_triangles(m, tris)
    nface = len(_occ.faces(part.shape))
    facets_by_face = [facet_of_tri[tm.tri_face == f] for f in range(nface)]
    lo, hi = _occ.bbox(part.shape)
    diag = math.dist(lo, hi)

    t0 = time.perf_counter()
    lam, mu = lame_parameters(mat.E, mat.nu)
    K = asm(linear_elasticity(lam, mu), ib)
    f = np.zeros(ib.N)
    fixed: list[np.ndarray] = []
    loads_out = []
    fixed_sets = []
    support_facets: list[np.ndarray] = []
    loaded_facets: list[np.ndarray] = []
    for ld in spec["loads"]:
        kind = ld["type"]
        info = {"type": kind, **({"faces": ld["faces"]} if "faces" in ld else {})}
        if kind == "gravity":
            if not mat.density:
                raise CadError(INVALID_ARGUMENT, "gravity() needs the material's density", hint="give the Material a density")
            acc = np.array(ld["direction"]) * ld["g"] * 9810.0 * mat.density * 1e-9  # N/mm^3
            f += asm(LinearForm(lambda v, w, a=acc: a[0] * v[0] + a[1] * v[1] + a[2] * v[2]), ib)
            info["total_N"] = round(float(part.volume * mat.density * 1e-3 * 9.81e-3 * ld["g"]), 4)
            loads_out.append(info)
            continue
        fac = np.unique(np.concatenate([facets_by_face[i] for i in ld["face_indices"]]))
        if "region" in ld:
            ctr = m.p[:, m.facets[:, fac]].mean(axis=1)  # (3, n) facet centroids
            keep = np.linalg.norm(ctr.T - np.asarray(ld["region"]["center"]), axis=1) <= ld["region"]["radius"]
            fac = fac[keep]
            if len(fac) == 0:
                raise CadError(INVALID_ARGUMENT, f"{kind}({ld['faces']!r}, at={ld['region']['center']}, radius={ld['region']['radius']}): "
                               "no part of those faces lies within the radius", hint="check at= is on the face, or enlarge radius")
        if len(fac) == 0:
            raise CadError(SOLVE_FAILED, f"{kind}({ld['faces']!r}) has no mesh faces")
        shared = _shared_names(part, ld)
        if shared and "region" not in ld:
            warnings.append({"code": "LOAD_FACE_SHARED", "message": f"{kind}({ld['faces']!r}) acts on a face that is also "
                             f"{', '.join(shared[:4])} (coplanar faces merge into one when bodies are joined)",
                             "hint": f"the load covers the whole merged face; to load only part of it add at=(x, y, z), radius=r to {kind}()"})
        fb = FacetBasis(mflat, e, facets=fac, intorder=3)
        area = float(_integrate(fb, lambda w: 1.0 + 0 * w.x[0]))
        info["area_mm2"] = round(area, 3)
        info["centroid"] = [round(_integrate(fb, lambda w, k=k: w.x[k]) / area, 4) + 0.0 for k in range(3)]
        if kind == "fixed":
            comps = [f"u^{'xyz'.index(c) + 1}" for c in ld.get("directions", "xyz")]
            dofs = ib.get_dofs(fac).all(comps)
            fixed.append(dofs)
            fixed_sets.append((info, dofs, ld))
            support_facets.append(fac)
            info["directions"] = ld.get("directions", "xyz")
            loads_out.append(info)
            continue
        if kind == "force":
            t = np.array(ld["direction"]) * ld["newtons"] / area
            f += asm(LinearForm(lambda v, w, t=t: t[0] * v[0] + t[1] * v[1] + t[2] * v[2]), fb)
            info["total_N"] = ld["newtons"]
            info["direction"] = ld["direction"]
        elif kind == "pressure":
            p = ld["mpa"]
            f += asm(LinearForm(lambda v, w, p=p: -p * (w.n[0] * v[0] + w.n[1] * v[1] + w.n[2] * v[2])), fb)
            info["total_N"] = round(p * area, 4)
        elif kind == "bearing":
            d = np.array(ld["direction"])

            def cos_push(w, d=d):
                return np.maximum(0.0, -(w.n[0] * d[0] + w.n[1] * d[1] + w.n[2] * d[2]))

            denom = float(_integrate(fb, lambda w: cos_push(w) ** 2))
            if denom < 0.02 * area:  # a pin pushing sideways on a full bore gives area / 4
                raise CadError(INVALID_ARGUMENT, f"bearing({ld['faces']!r}): those faces do not face against direction "
                               f"{ld['direction']} (is it along the hole's axis?)",
                               hint="a bearing load is a pin pushing sideways on a hole wall: use a direction across the hole; "
                                    "for a push along the axis use force() on the face the pin's head or shoulder presses")
            p0 = ld["newtons"] / denom
            # the cosine distribution on a faceted bore leaves a small sideways resultant: cancel it with a uniform
            # traction so the pin's net force is exactly the requested one
            net = [_integrate(fb, lambda w, k=k: -p0 * cos_push(w) * w.n[k]) for k in range(3)]
            fix = (np.array(d) * ld["newtons"] - np.array(net)) / area
            f += asm(LinearForm(lambda v, w, p0=p0, fix=fix: -p0 * cos_push(w) * (w.n[0] * v[0] + w.n[1] * v[1] + w.n[2] * v[2])
                                + fix[0] * v[0] + fix[1] * v[1] + fix[2] * v[2]), fb)
            info["total_N"] = ld["newtons"]
            info["direction"] = ld["direction"]
            info["peak_pressure_MPa"] = round(p0, 4)
        elif kind == "torque":
            a, c = _torque_axis(part, ld)
            info["axis"], info["center"] = [round(x, 6) for x in a], [round(x, 4) for x in c]

            def rperp(w, a=a, c=c):
                r = [w.x[k] - c[k] for k in range(3)]
                ra = r[0] * a[0] + r[1] * a[1] + r[2] * a[2]
                return [r[k] - ra * a[k] for k in range(3)]

            j = float(_integrate(fb, lambda w: sum(x * x for x in rperp(w))))
            if j < 1e-12:
                raise CadError(INVALID_ARGUMENT, f"torque({ld['faces']!r}): the faces lie on the axis", hint="give axis= and center=")
            k = ld["newton_metres"] * 1000.0 / j

            def tq(v, w, a=a, k=k):
                r = rperp(w)
                t = [k * (a[1] * r[2] - a[2] * r[1]), k * (a[2] * r[0] - a[0] * r[2]), k * (a[0] * r[1] - a[1] * r[0])]
                return t[0] * v[0] + t[1] * v[1] + t[2] * v[2]

            net = []
            for comp_k in range(3):
                def tk(w, comp_k=comp_k, a=a, k=k):
                    r = rperp(w)
                    return k * [a[1] * r[2] - a[2] * r[1], a[2] * r[0] - a[0] * r[2], a[0] * r[1] - a[1] * r[0]][comp_k]
                net.append(_integrate(fb, tk))
            fix = -np.array(net) / area  # a pure twist: no net force

            def tq_fixed(v, w, fix=fix):
                return tq(v, w) + fix[0] * v[0] + fix[1] * v[1] + fix[2] * v[2]

            f += asm(LinearForm(tq_fixed), fb)
            info["total_Nm"] = ld["newton_metres"]
        info["_facets"] = fac
        loaded_facets.append(fac)
        loads_out.append(info)
    if not fixed:
        raise CadError(UNDERCONSTRAINED, f"study '{spec['name']}' holds the part nowhere",
                       hint="add study.fixed(faces) where the part is bolted, clamped or resting")
    if not any(ld["type"] != "fixed" for ld in spec["loads"]):
        raise CadError(INVALID_ARGUMENT, f"study '{spec['name']}' has supports but no loads",
                       hint="add force(), bearing(), torque(), pressure() or gravity()")
    D = np.unique(np.concatenate(fixed))
    comp, B = _rigid_modes(ib)
    free_motion = _free_rigid_motions(B[D])
    if free_motion:
        raise CadError(UNDERCONSTRAINED, f"study '{spec['name']}': the supports let the part {' and '.join(free_motion)} freely",
                       hint="fix more faces, or all directions of a face (fixed() without directions=)",
                       details={"free_motions": free_motion})
    t_asm = time.perf_counter() - t0

    t0 = time.perf_counter()
    Kc, fc, _, I = condense(K, f, D=D)
    method = "direct"
    if len(I) <= DIRECT_SOLVE_MAX_DOFS:
        uc = sla.spsolve(Kc.tocsc(), fc)
        iters = None
    else:
        import pyamg

        method = "cg+amg"
        ml = pyamg.smoothed_aggregation_solver(Kc.tocsr(), B=B[I], symmetry="hermitian", strength="symmetric", max_coarse=500,
                                              coarse_solver="splu")
        count = [0]
        uc, code = sla.cg(Kc, fc, M=ml.aspreconditioner(), rtol=1e-8, maxiter=2000,
                          callback=lambda _: count.__setitem__(0, count[0] + 1))
        iters = count[0]
        if code != 0:
            raise CadError(SOLVE_FAILED, f"the solver did not converge ({iters} iterations)",
                           hint="the part may be nearly free to move, or the mesh has bad elements; try --quality draft or fine")
    u = np.zeros(ib.N)
    u[I] = uc
    if not np.all(np.isfinite(u)):
        raise CadError(SOLVE_FAILED, "the solution is not finite", hint="check that supports hold the part")
    t_solve = time.perf_counter() - t0

    # ---------------------------------------------------------------- results at vertices
    t0 = time.perf_counter()
    nv = int(m.t.max()) + 1  # corner vertices (a quadratic mesh's p also holds its edge nodes)
    P = m.p[:, :nv]
    U = np.stack([u[ib.nodal_dofs[k]] for k in range(3)], axis=1)  # (nv, 3)
    sig = _vertex_stress(m, e, u, lam, mu)  # (nv, 3, 3) averaged; also peak unaveraged
    sig_avg, _ = sig
    vm = _von_mises(sig_avg)
    build = np.array([-c for c in part.print_down]) if part.print_down else np.array([0.0, 0.0, 1.0])
    layer = np.einsum("i,nij,j->n", build, sig_avg, build)
    principal = np.linalg.eigvalsh(sig_avg)[:, -1]
    reactions = []
    R = K @ u - f
    for info, dofs, ld in fixed_sets:
        rc = [float(R[dofs[comp[dofs] == k]].sum()) for k in range(3)]
        info["reaction_N"] = [round(x, 4) for x in rc]
        reactions.append(rc)

    surf_v = np.unique(tris)
    on_surface = np.zeros(nv, dtype=bool)
    on_surface[surf_v] = True
    imax = int(np.argmax(vm))
    disp = np.linalg.norm(U, axis=1)
    idmax = int(np.argmax(disp))
    sf_strength = mat.strength / max(float(vm.max()), 1e-12)
    layer_max = float(max(layer.max(), 0.0))
    sf_layer = (mat.layer_strength / layer_max) if (mat.layer_strength and layer_max > 1e-12) else None
    sf = min(sf_strength, sf_layer) if sf_layer is not None else sf_strength
    target = float(spec.get("target", 2.0))

    for info in loads_out:
        fac = info.pop("_facets", None)
        if fac is None or "direction" not in info:
            continue
        vs = np.unique(m.facets[:, fac])
        info["moves_mm"] = round(float((U[vs] @ np.array(info["direction"])).mean()), 5)
        if abs(info["moves_mm"]) > 1e-12:
            info["stiffness_N_per_mm"] = round(info["total_N"] / info["moves_mm"], 3)

    vertex_faces = _vertex_faces(tris, tm.tri_face)
    support_v = np.unique(m.facets[:, np.concatenate(support_facets)])
    loaded_v = np.unique(m.facets[:, np.concatenate(loaded_facets)]) if loaded_facets else np.zeros(0, dtype=np.int64)
    sharp = _sharp_concave_edges(part.shape)
    reach = max(0.6 * tm.size, 0.01 * diag)
    hotspots = _hotspots(part, P.T, vm, layer, on_surface, vertex_faces, support_v, loaded_v, diag, sharp, reach)

    # ---------------------------------------------------------------- warnings
    if mat.assumed:
        warnings.append({"code": "MATERIAL_ASSUMED", "message": "; ".join(mat.assumed),
                         "hint": "set the part's material (Part(..., material='PETG')) or give Material(...) youngs_modulus and yield_strength"})
    if mat.E < 200:
        warnings.append({"code": "NONLINEAR_MATERIAL", "message": f"{mat.name} is rubbery; linear analysis only gives a rough idea",
                         "hint": "treat stresses and deflections as indications, not numbers"})
    if disp.max() > 0.05 * diag:
        warnings.append({"code": "LARGE_DEFLECTION", "message": f"the part deflects {disp.max():.2f} mm ({100 * disp.max() / diag:.1f} % of its size); "
                         "linear analysis gets less accurate past a few percent", "hint": "stiffen the part; trust the trend more than the number"})
    singular = [h for h in hotspots if h.get("sharp_edge") and not h.get("at_support")]
    edges_seen: list = []
    for h in singular:
        e = h["edge"]["_edge"]
        if any(e.IsSame(x) for x in edges_seen):
            continue
        edges_seen.append(e)
        same = [x["id"] for x in singular if x["edge"]["_edge"].IsSame(e)]
        between = " and ".join("/".join(n) for n in h["edge"]["between"])
        warnings.append({"code": "STRESS_SINGULARITY", "hotspot": h["id"], "hotspots": same,
                         "message": f"hotspot{'s' if len(same) > 1 else ''} {', '.join(map(str, same))} "
                         f"{'are' if len(same) > 1 else 'is'} at a sharp inside edge (between {between}): stress there grows "
                         "without limit as the mesh is refined, so the number is not meaningful",
                         "hint": h["suggestions"][0]})
    rest = rest_layer = None
    exclude = max(tm.typical_wall or 0.0, 0.03 * diag)  # Saint-Venant: idealised supports disturb about a wall thickness
    near_support = np.zeros(nv, dtype=bool)
    if any(h.get("at_support") for h in hotspots) and len(support_v):
        tree_pts = P.T[support_v]
        for chunk in np.array_split(np.arange(nv), max(1, nv // 4000)):
            d = np.min(np.linalg.norm(P.T[chunk][:, None, :] - tree_pts[None, :, :], axis=2), axis=1)
            near_support[chunk] = d <= exclude
    near_edge = np.zeros(nv, dtype=bool)
    for e in edges_seen:
        pts = _sample_edge(e)
        near_edge |= np.min(np.linalg.norm(P.T[:, None, :] - pts[None, :, :], axis=2), axis=1) <= exclude
    if (near_support | near_edge).any() and not (near_support | near_edge).all():
        far = ~(near_support | near_edge)
        rest = float(vm[far].max())
        rest_layer = float(max(layer[far].max(), 0.0))
    for h in hotspots:
        h.get("edge", {}).pop("_edge", None)

    # the verdict: an ideal clamp inflates stress at its edge without limit, so judge the part away from fixed
    # faces; a sharp inside corner is a real weakness (it needs a fillet), so it keeps the part from passing
    def factor(mask):
        v = float(vm[mask].max())
        lay = float(max(layer[mask].max(), 0.0))
        f_s = mat.strength / max(v, 1e-12)
        f_l = mat.layer_strength / lay if (mat.layer_strength and lay > 1e-12) else None
        return (min(f_s, f_l) if f_l is not None else f_s), f_s, f_l, v, lay

    judged_mask = ~near_support if near_support.any() and not near_support.all() else np.ones(nv, dtype=bool)
    sf_j, sf_j_strength, sf_j_layer, vm_j, layer_j = factor(judged_mask)
    judged_where = (f"away from the fixed faces (ignoring {exclude:.3g} mm around them, where the ideal clamp inflates stress)"
                    if near_support.any() and not near_support.all() else "everywhere")
    if sf_j_layer is not None and sf_j_layer < sf_j_strength and sf_j_layer < target:
        warnings.append({"code": "LAYER_TENSION", "message": f"stress pulling the print layers apart ({layer_j:.1f} MPa) limits the part: "
                         f"layer safety factor {sf_j_layer:.2f} vs {sf_j_strength:.2f} along the layers",
                         "hint": "print it in another orientation (part.print_on(...)) so the load runs along the layers, or thicken it"})
    if sf_j < target:
        h = next((x for x in hotspots if not (x.get("at_support") and near_support.any())), None)
        where = f" at hotspot {h['id']} ({_where(h)})" if h else ""
        warnings.insert(0, {"code": "LOW_SAFETY_FACTOR", "message": f"safety factor {sf_j:.2f} is below the target {target:g}{where}",
                            "hint": "add material or round the inside corner at the hot spot (see hotspots[].suggestions), then re-run"})
    singular_ids = [h["id"] for h in singular]
    ok = sf_j >= target and not singular_ids
    if sf_j >= target and singular_ids:
        elsewhere = (f"; away from it the safety factor is about "
                     f"{min(mat.strength / max(rest, 1e-12), mat.layer_strength / rest_layer if (mat.layer_strength and rest_layer > 1e-12) else 1e9):.3g}"
                     if rest is not None else "")
        verdict = f"BELOW TARGET until the sharp inside corner at hotspot {singular_ids[0]} is rounded{elsewhere}"
    elif ok:
        verdict = f"OK: safety factor {sf_j:.3g} >= {target:g}, judged {judged_where}"
    else:
        verdict = f"BELOW TARGET: safety factor {sf_j:.3g} < {target:g}, judged {judged_where}"
    at_sup = [h["id"] for h in hotspots if h.get("at_support")]
    if at_sup:
        warnings.append({"code": "PEAK_AT_SUPPORT", "hotspot": at_sup[0], "hotspots": at_sup,
                         "message": f"hotspot{'s' if len(at_sup) > 1 else ''} {', '.join(map(str, at_sup))} "
                         f"{'are' if len(at_sup) > 1 else 'is'} on a fixed face, where an ideal clamp exaggerates stress: "
                         f"the verdict is judged away from the fixed faces (peak there {vm_j:.3g} MPa)",
                         "hint": "if the real support is a screw head or a clamp face, fix that face instead of the hole for a more "
                                 "realistic peak"})
    assumptions = ["linear elastic, small deflections", "isotropic material, strength along the layers = yield_strength"]
    if part.material is None or part.material.kind == "filament":
        assumptions.append("printed solid (100 % infill) near the hot spots: use more walls / infill there")
        assumptions.append(f"layers stacked along {_dir_label(build)} (from print_on, else +Z)")
    t_post = time.perf_counter() - t0

    report = {
        "study": spec["name"],
        "part": spec["part"],
        "description": spec.get("description"),
        "material": mat.to_dict(),
        "ok": bool(ok),
        "verdict": verdict,
        "safety_factor": round(sf_j, 3),
        "judged": judged_where,
        "peak_safety_factor": round(sf, 3),
        "target": target,
        "max_von_mises_MPa": round(float(vm.max()), 4),
        "max_von_mises_at": [round(float(c), 3) for c in P[:, imax]],
        "max_principal_MPa": round(float(principal.max()), 4),
        **({"away_from_supports_and_sharp_edges": {
            "max_von_mises_MPa": round(rest, 4),
            "safety_factor": round(min(mat.strength / max(rest, 1e-12),
                                       mat.layer_strength / rest_layer if (mat.layer_strength and rest_layer > 1e-12) else 1e9), 3),
            "note": f"ignoring {exclude:.3g} mm around fixed faces and sharp inside edges: roughly what the part would reach "
                    "with its sharp inside corners rounded"}} if rest is not None else {}),
        "mass_g": round(part.mass(), 3) if mat.density else None,
        "max_displacement_mm": round(float(disp.max()), 5),
        "max_displacement_at": [round(float(c), 3) for c in P[:, idmax]],
        "strength": {"along_layers_safety_factor": round(sf_j_strength, 3),
                     "across_layers_safety_factor": round(sf_j_layer, 3) if sf_j_layer is not None else None,
                     "max_tension_across_layers_MPa": round(layer_j, 4) if mat.layer_strength else None,
                     "build_direction": [round(float(c), 6) for c in build]},
        "loads": loads_out,
        "hotspots": hotspots,
        "warnings": warnings,
        "assumptions": assumptions,
        "mesh": {"quality": quality, "element_size_mm": round(tm.size, 4), "nodes": int(nv), "tetrahedra": int(m.t.shape[1]),
                 "unknowns": int(ib.N), "solver": method, "iterations": iters},
        "seconds": {"mesh": round(t_mesh, 3), "assemble": round(t_asm, 3), "solve": round(t_solve, 3), "post": round(t_post, 3),
                    "total": round(time.perf_counter() - t_start + (0 if mesh is None else t_mesh), 3)},
        "solver_version": SOLVER_VERSION,
    }
    out_tris, flipped = _outward(m, tris)
    arrays = {"vertices": P.T.astype(np.float64), "tris": out_tris, "tri_face": tm.tri_face,
              "displacement": U, "von_mises": vm, "layer": layer, "principal": principal,
              "safety": np.where(vm > 1e-12, mat.strength / np.maximum(vm, 1e-12), 1e9)}
    if tm.tri_mid is not None:  # edge midpoints follow the triangle's winding (a flip swaps edges 01 and 20)
        mid = tm.tri_mid.copy()
        mid[flipped] = mid[flipped][:, [2, 1, 0]]
        arrays["tri_mid"] = mid
    if mat.layer_strength:
        arrays["safety"] = np.minimum(arrays["safety"], np.where(layer > 1e-12, mat.layer_strength / np.maximum(layer, 1e-12), 1e9))
    return Solution(report, arrays)


GMSH_TO_SKFEM_TET10 = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]  # skfem edges: 01 12 02 03 13 23


def _skfem_mesh(tm: TetMesh):
    """(skfem mesh, boundary triangles as indices of its vertices)."""
    from skfem import MeshTet, MeshTet2

    if tm.tets.shape[1] == 4:
        return MeshTet(np.ascontiguousarray(tm.nodes.T), np.ascontiguousarray(tm.tets.T)), tm.tris
    t = np.ascontiguousarray(tm.tets[:, GMSH_TO_SKFEM_TET10].T)
    m = MeshTet2(np.ascontiguousarray(tm.nodes.T), t)
    uniq = np.unique(t[:4])  # MeshTet2 renumbers the vertices in this order
    return m, np.searchsorted(uniq, tm.tris)


def _shared_names(part, ld: dict) -> list[str]:
    """Other features' names on the faces a load was given by reference name (merged coplanar faces)."""
    label = ld.get("faces")
    if not isinstance(label, str) or "(" in label:
        return []
    feat = label.split(".", 1)[0]
    faces = _occ.faces(part.shape)
    names = {n for i in ld["face_indices"] for n in part._names_of(faces[i], "face")}
    return sorted(n for n in names if n.split(".", 1)[0] != feat)


def _integrate(fb, fn) -> float:
    from skfem import Functional

    return float(Functional(lambda w: fn(w)).assemble(fb))


def _facets_of_triangles(m, tris: np.ndarray) -> np.ndarray:
    """skfem facet index of each boundary triangle (given as vertex triples)."""
    n = np.int64(m.p.shape[1])
    fa = np.sort(m.facets.T, axis=1).astype(np.int64)
    tr = np.sort(tris, axis=1).astype(np.int64)
    kf = (fa[:, 0] * n + fa[:, 1]) * n + fa[:, 2]
    kt = (tr[:, 0] * n + tr[:, 1]) * n + tr[:, 2]
    order = np.argsort(kf)
    pos = np.searchsorted(kf[order], kt)
    pos = np.clip(pos, 0, len(order) - 1)
    hit = order[pos]
    if not np.all(kf[hit] == kt):
        raise CadError(MESH_FAILED, "surface triangles do not match the volume mesh")
    return hit


def _outward(m, tris: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Boundary triangles wound so their normals point out of the part, and which ones were flipped."""
    p = m.p.T
    fac = _facets_of_triangles(m, tris)
    tet = m.f2t[0, fac]
    tv = m.t[:, tet].T  # (S, 4)
    apex = np.array([np.setdiff1d(t, tri, assume_unique=False)[0] for t, tri in zip(tv, tris)])
    a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    nrm = np.cross(b - a, c - a)
    inward = np.einsum("ij,ij->i", nrm, p[apex] - a) > 0
    out = tris.copy()
    out[inward] = out[inward][:, [0, 2, 1]]
    return out, inward


def _rigid_modes(ib) -> tuple[np.ndarray, np.ndarray]:
    """(component of each dof, the 6 rigid-body modes as an (N, 6) array)."""
    comp = np.zeros(ib.N, dtype=np.int64)
    for k in range(3):
        for dofs in (ib.nodal_dofs, ib.edge_dofs, ib.facet_dofs, ib.interior_dofs):
            if dofs is not None and dofs.size:
                comp[dofs[k]] = k
    x, y, z = ib.doflocs
    B = np.zeros((ib.N, 6))
    for k in range(3):
        B[comp == k, k] = 1.0
    c0, c1, c2 = comp == 0, comp == 1, comp == 2
    B[c0, 3], B[c1, 3] = -y[c0], x[c1]  # about z
    B[c1, 4], B[c2, 4] = -z[c1], y[c2]  # about x
    B[c2, 5], B[c0, 5] = -x[c2], z[c0]  # about y
    return comp, B


def _free_rigid_motions(BD: np.ndarray) -> list[str]:
    """Rigid motions the constrained dofs do not stop (empty list = held)."""
    if BD.shape[0] == 0:
        return ["move"]
    scale = np.abs(BD[:, 3:]).max() or 1.0
    Bn = BD.copy()
    Bn[:, 3:] /= scale
    s, vt = np.linalg.svd(Bn, full_matrices=True)[1:]
    s = np.concatenate([s, np.zeros(6 - len(s))])
    free = vt[s < 1e-8 * max(s.max(), 1e-30)]  # orthonormal basis of the unrestrained motions
    if len(free) == 0:
        return []
    names = ["slide along x", "slide along y", "slide along z", "turn about z", "turn about x", "turn about y"]
    out = [n for i, n in enumerate(names) if np.linalg.norm(free @ np.eye(6)[i]) > 1 - 1e-6]
    return out or ["move (a combined slide and turn)"]


def _vertex_stress(m, e, u, lam, mu) -> tuple[np.ndarray, float]:
    """Stress tensors averaged onto vertices (volume-weighted), and the largest unaveraged von Mises."""
    from skfem import Basis
    from skfem.helpers import sym_grad

    X = np.array([[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]])  # reference vertices
    vb = Basis(m, e, quadrature=(X, np.full(4, 1 / 24)))
    eps = np.asarray(sym_grad(vb.interpolate(u)))  # (3, 3, nel, 4)
    tr = np.einsum("ii...->...", eps)
    sig = 2 * mu * eps + lam * tr[None, None] * np.eye(3)[:, :, None, None]
    s = np.moveaxis(sig, (0, 1), (-2, -1))  # (nel, 4, 3, 3)
    raw_vm = _von_mises(s.reshape(-1, 3, 3)).max()
    vol = np.abs(vb.dx.sum(axis=1))  # element volumes
    nv = int(m.t.max()) + 1
    acc = np.zeros((nv, 3, 3))
    wsum = np.zeros(nv)
    for k in range(4):
        np.add.at(acc, m.t[k], s[:, k] * vol[:, None, None])
        np.add.at(wsum, m.t[k], vol)
    return acc / np.maximum(wsum, 1e-30)[:, None, None], float(raw_vm)


def _von_mises(s: np.ndarray) -> np.ndarray:
    sxx, syy, szz = s[:, 0, 0], s[:, 1, 1], s[:, 2, 2]
    sxy, syz, sxz = s[:, 0, 1], s[:, 1, 2], s[:, 0, 2]
    return np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * (sxy ** 2 + syz ** 2 + sxz ** 2))


def _vertex_faces(tris: np.ndarray, tri_face: np.ndarray) -> dict[int, set]:
    out: dict[int, set] = {}
    for tri, fi in zip(tris, tri_face):
        for v in tri:
            out.setdefault(int(v), set()).add(int(fi))
    return out


def _hotspots(part, P, vm, layer, on_surface, vertex_faces, support_v, loaded_v, diag, sharp, reach, *,
              limit: int = 5, threshold: float = 0.5) -> list[dict]:
    """Separate high-stress regions on the surface, highest first."""
    faces = _occ.faces(part.shape)
    peak = float(vm.max())
    cand = np.nonzero(on_surface & (vm >= threshold * peak))[0]
    cand = cand[np.argsort(-vm[cand], kind="stable")]
    radius = 0.08 * diag
    taken = np.zeros(len(P), dtype=bool)
    out = []
    for v in cand:
        if taken[v]:
            continue
        near = np.linalg.norm(P[cand] - P[v], axis=1) < radius
        taken[cand[near]] = True
        fis = sorted(vertex_faces.get(int(v), ()))
        finfo = []
        for fi in fis[:3]:
            names = part._names_of(faces[fi], "face")
            d = {"index": fi, "type": _occ.surface_type(faces[fi]), "names": names}
            ci = _occ.cylinder_info(faces[fi]) if d["type"] == "cylinder" else None
            if ci:
                d["radius"] = round(ci["radius"], 4)
            finfo.append(d)
        # the features of the most specific face (merged coplanar faces carry many features' names)
        per_face = [{n.split(".", 1)[0] for n in f["names"]} for f in finfo if f["names"]]
        fewest = min((len(x) for x in per_face), default=0)
        features = sorted(set().union(*[x for x in per_face if len(x) == fewest])) if per_face else []
        h = {"id": len(out) + 1, "von_mises_MPa": round(float(vm[v]), 4), "fraction_of_peak": round(float(vm[v]) / peak, 3),
             "at": [round(float(c), 3) for c in P[v]], "faces": finfo, "features": features,
             "tension_across_layers_MPa": round(float(max(layer[v], 0.0)), 4)}
        if len(support_v) and np.linalg.norm(P[support_v] - P[v], axis=1).min() <= reach:
            h["at_support"] = True
        if len(loaded_v) and np.linalg.norm(P[loaded_v] - P[v], axis=1).min() <= reach:
            h["at_load"] = True
        corner = _nearest_sharp_edge(part, sharp, P[v], reach)
        if corner:
            h["sharp_edge"] = "concave"
            h["edge"] = corner
        h["suggestions"] = _suggest(part, finfo, features, corner)
        out.append(h)
        if len(out) >= limit:
            break
    return out


def _sharp_concave_edges(shape) -> list[tuple]:
    from .analysis import sharp_inside_edges

    return sharp_inside_edges(shape)


def _sample_edge(e, n: int = 40) -> np.ndarray:
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    c = BRepAdaptor_Curve(e)
    t0, t1 = c.FirstParameter(), c.LastParameter()
    pts = []
    for i in range(n + 1):
        q = c.Value(t0 + (t1 - t0) * i / n)
        pts.append((q.X(), q.Y(), q.Z()))
    return np.array(pts)


def _nearest_sharp_edge(part, sharp: list, point, reach: float) -> dict | None:
    if not sharp:
        return None
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt

    vx = BRepBuilderAPI_MakeVertex(gp_Pnt(*[float(c) for c in point])).Vertex()
    best = None
    for e, fa, fb in sharp:
        d = _occ.distance(vx, e)[0]
        if d <= reach and (best is None or d < best[0]):
            best = (d, e, fa, fb)
    if best is None:
        return None
    d, e, fa, fb = best
    c = [round(x, 4) + 0.0 for x in _occ.edge_centroid(e)]
    return {"_edge": e, "centroid": c, "length": round(_occ.length(e), 4), "distance_mm": round(d, 4),
            "between": [part._names_of(fa, "face") or ["(unnamed face)"], part._names_of(fb, "face") or ["(unnamed face)"]]}


def _suggest(part, finfo: list[dict], features: list[str], corner: dict | None) -> list[str]:
    tips = []
    by_id = {f.id: f for f in part.features}
    fillets = [fid for fid in features if fid in by_id and by_id[fid].type == "fillet"]
    for fid in fillets:
        r = by_id[fid].params.get("radius")
        tips.append(f"enlarge fillet '{fid}' (radius {r}) to spread the stress")
    if not fillets:
        if corner:
            c = ", ".join(f"{x:g}" for x in corner["centroid"])
            tips.append(f"round the sharp inside edge: {part.name}.fillet({part.name}.edges().concave().nearest(({c})), 2)")
        if any(f["type"] == "cylinder" for f in finfo):
            tips.append("a hole wall: move the hole away from the edge, add material around it (a boss), or enlarge the part there")
    tips.append("thicken the section that carries the load here (bending stress falls with thickness squared)")
    return tips


def _torque_axis(part, ld) -> tuple[list[float], list[float]]:
    faces = _occ.faces(part.shape)
    sel = [faces[i] for i in ld["face_indices"]]
    if "axis" in ld:
        a = np.array(ld["axis"], dtype=float)
        a /= np.linalg.norm(a)
        if "center" in ld:
            return a.tolist(), list(ld["center"])
        areas = np.array([_occ.area(f) for f in sel])
        c = (np.array([_occ.face_centroid(f) for f in sel]) * areas[:, None]).sum(0) / areas.sum()
        cyl = _occ.cylinder_info(sel[0]) if _occ.surface_type(sel[0]) == "cylinder" else None
        if cyl:
            c = np.array(cyl["axis_point"])
        return a.tolist(), list(ld.get("center", c.tolist()))
    infos = [_occ.cylinder_info(f) if _occ.surface_type(f) == "cylinder" else None for f in sel]
    if not infos or any(i is None for i in infos):
        raise CadError(INVALID_ARGUMENT, f"torque({ld['faces']!r}): give axis= (the faces are not a cylinder to take it from)")
    a = np.array(infos[0]["axis"], dtype=float)
    a /= np.linalg.norm(a)
    c = ld.get("center", list(infos[0]["axis_point"]))
    return a.tolist(), list(c)


def _where(h: dict) -> str:
    names = list(dict.fromkeys(n for f in h["faces"] for n in f["names"] if n.split(".", 1)[0] in h["features"]))
    return ", ".join(names[:2]) if names else f"faces {[f['index'] for f in h['faces']]}"


def _dir_label(v) -> str:
    for i, ax in enumerate("xyz"):
        if abs(abs(v[i]) - 1) < 1e-9:
            return ("+" if v[i] > 0 else "-") + ax.upper()
    return str([round(float(c), 3) for c in v])
