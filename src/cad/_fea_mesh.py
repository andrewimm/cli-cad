"""Tetrahedral meshing with gmsh, run as a separate process by cad.fea.

    python -I _fea_mesh.py IN.brep OUT.npz OPTIONS.json

This file is executed by path (not imported as part of the cad package) so gmsh,
which bundles its own Open CASCADE, never shares a process with OCP; gmsh is GPL
and an optional install.  Output: vertex coordinates, linear tetrahedra and, per
gmsh surface, its boundary triangles plus exact centre of mass and area (used to
match surfaces to the part's faces).  With ``order`` 2 the tetrahedra have 10
nodes, the edge nodes placed on the curved surfaces (gmsh order: vertices, then
edges 01 12 02 03 23 13); triangles are reported by their 3 corner vertices plus their edge
nodes (01, 12, 20) on the curved surface, used to draw curved faces smoothly.
"""

import json
import sys
import time

import numpy as np


def main(brep: str, out: str, options: str) -> None:
    import gmsh

    opts = json.loads(options if options.startswith("{") else open(options).read())
    t0 = time.time()
    gmsh.initialize(["-noenv"], readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)  # deterministic meshes
        gmsh.option.setNumber("Geometry.OCCFixDegenerated", 0)
        gmsh.option.setNumber("Geometry.OCCFixSmallEdges", 0)
        gmsh.option.setNumber("Geometry.OCCFixSmallFaces", 0)
        gmsh.option.setNumber("Geometry.OCCSewFaces", 0)
        gmsh.model.occ.importShapes(brep, highestDimOnly=True)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", opts["size_max"])
        gmsh.option.setNumber("Mesh.MeshSizeMin", opts["size_min"])
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", opts["curvature"])
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
        gmsh.option.setNumber("Mesh.Algorithm", 6)  # Frontal-Delaunay surfaces
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)  # Delaunay volumes
        gmsh.option.setNumber("Mesh.Optimize", 1)
        balls = []
        for x, y, z, radius, size in opts.get("refine", []):  # finer elements around hot spots
            f = gmsh.model.mesh.field.add("Ball")
            for k, v in (("XCenter", x), ("YCenter", y), ("ZCenter", z), ("Radius", radius), ("Thickness", radius),
                         ("VIn", size), ("VOut", opts["size_max"])):
                gmsh.model.mesh.field.setNumber(f, k, v)
            balls.append(f)
        if balls:
            fmin = gmsh.model.mesh.field.add("Min")
            gmsh.model.mesh.field.setNumbers(fmin, "FieldsList", balls)
            gmsh.model.mesh.field.setAsBackgroundMesh(fmin)
        gmsh.model.mesh.generate(3)
        order = int(opts.get("order", 1))
        if order == 2:
            gmsh.option.setNumber("Mesh.HighOrderOptimize", 2)
            gmsh.model.mesh.setOrder(2)
        tet_type, tri_type, nper = (11, 9, 10) if order == 2 else (4, 2, 4)
        tags, coords, _ = gmsh.model.mesh.getNodes()
        types, _, enodes = gmsh.model.mesh.getElements(3)
        if tet_type not in list(types):
            raise RuntimeError("gmsh produced no tetrahedra (is the part a closed solid?)")
        tets = np.asarray(enodes[list(types).index(tet_type)], dtype=np.int64).reshape(-1, nper)
        stags, tris, owner, com, area = [], [], [], [], []
        for _, tag in gmsh.model.getEntities(2):
            t, _, en = gmsh.model.mesh.getElements(2, tag)
            if tri_type not in list(t):
                continue
            tri = np.asarray(en[list(t).index(tri_type)], dtype=np.int64).reshape(-1, 6 if order == 2 else 3)
            stags.append(tag)
            tris.append(tri if order == 2 else np.concatenate([tri, tri[:, [0, 1, 2]]], axis=1))  # always 6 columns
            owner.append(np.full(len(tri), len(stags) - 1))
            com.append(gmsh.model.occ.getCenterOfMass(2, tag))
            area.append(gmsh.model.occ.getMass(2, tag))
    finally:
        gmsh.finalize()
    tags = np.asarray(tags, dtype=np.int64)
    order = np.argsort(tags)
    tags = tags[order]
    xyz = np.asarray(coords, dtype=float).reshape(-1, 3)[order]

    def idx(a):
        return np.searchsorted(tags, a)

    tri6 = idx(np.concatenate(tris))
    np.savez(out, nodes=xyz, tets=idx(tets), tris=tri6[:, :3], tri_mid=tri6[:, 3:], tri_surface=np.concatenate(owner),
             surface_com=np.asarray(com, dtype=float), surface_area=np.asarray(area, dtype=float))
    print(json.dumps({"nodes": int(len(xyz)), "tets": int(len(tets)), "seconds": round(time.time() - t0, 3)}))


if __name__ == "__main__":
    try:
        main(*sys.argv[1:4])
    except Exception as e:  # reported to the parent as JSON on stderr
        sys.stderr.write(json.dumps({"error": f"{type(e).__name__}: {e}"}) + "\n")
        sys.exit(2)
