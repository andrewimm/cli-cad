"""3MF export (3D Manufacturing Format) with materials.

Layouts:

* ``objects`` (default): one mesh object per part, each a separate build item at its
  modelled position, each tied to its material through a ``<basematerials>`` slot.
  Slicers load them as separate objects (e.g. a box and its lid).
* ``multimaterial``: all parts merged into ONE object whose triangles carry their
  part's material (per-triangle ``pid``/``p1``).  PrusaSlicer/OrcaSlicer extruder
  assignments are written too (``Metadata/Slic3r_PE_model.config``: one volume per
  part, extruder = material slot + 1), so the parts load as volumes of one object,
  in place, ready for a multi-material printer.

Meshes are welded (shared vertices), outward oriented and checked to be closed
two-manifolds before writing, as the 3MF core specification requires.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from .errors import EXPORT_FAILED, INVALID_ARGUMENT, CadError

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MODES = ("objects", "multimaterial")

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
  <Default Extension="config" ContentType="application/vnd.ms-package.3dmanufacturing-config+xml"/>
</Types>
"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def welded_mesh(shape, tolerance: float = 0.01, angular: float = 0.2) -> tuple[np.ndarray, np.ndarray]:
    """(vertices, triangles) with shared vertices, outward triangle winding."""
    from .tessellate import tessellate

    m = tessellate(shape, tolerance, angular)
    if len(m.triangles) == 0:
        raise CadError(EXPORT_FAILED, "tessellation produced no triangles")
    q = np.round(m.vertices / 1e-6).astype(np.int64)
    _, first, inverse = np.unique(q, axis=0, return_index=True, return_inverse=True)
    verts = m.vertices[first]
    tris = inverse.reshape(-1)[m.triangles]
    keep = (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])
    return verts, tris[keep]


def manifold_report(verts: np.ndarray, tris: np.ndarray) -> dict:
    directed = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    _, ucount = np.unique(np.sort(directed, axis=1), axis=0, return_counts=True)
    _, dcount = np.unique(directed, axis=0, return_counts=True)
    v = verts[tris]
    volume = float(np.sum(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2]))) / 6.0)
    return {"open_edges": int(np.sum(ucount == 1)), "non_manifold_edges": int(np.sum(ucount > 2)),
            "flipped_edges": int(np.sum(dcount > 1)), "volume": volume,
            "closed": bool(np.all(ucount == 2) and np.all(dcount == 1) and volume > 0)}


def _color(c: str | None, fallback: str) -> str:
    return ((c or fallback).upper() + "FF") if (c or fallback).startswith("#") else "#808080FF"


def _mesh_xml(verts, tris, tri_attr: str = "") -> str:
    vs = "".join(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in verts)
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"{tri_attr}/>' for a, b, c in tris)
    return f"<mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh>"


def export_3mf(parts: dict, path: str | os.PathLike, *, mode: str = "objects", tolerance: float = 0.01,
               angular_tolerance: float = 0.2, title: str | None = None, check_overlap: bool = True) -> dict:
    """Write ``parts`` ({name: Part}) to one .3mf file.  Returns a report (materials, objects, warnings)."""
    from . import __version__
    from .materials import Material
    from .renderer import PALETTE

    if mode not in MODES:
        raise CadError(INVALID_ARGUMENT, f"unknown 3MF mode {mode!r}", hint=f"use one of {MODES}")
    if not parts:
        raise CadError(INVALID_ARGUMENT, "nothing to export")
    # material slots, in first-use order; parts without a material get a per-part default slot
    slots: list[Material] = []
    slot_of: dict[str, int] = {}
    for i, (name, p) in enumerate(parts.items()):
        mat = p.material or Material(f"{name} (no material)", color=_hex(p.color, PALETTE[i % len(PALETTE)]))
        key = (mat.name, mat.color)
        idx = next((k for k, m in enumerate(slots) if (m.name, m.color) == key), None)
        if idx is None:
            slots.append(mat)
            idx = len(slots) - 1
        slot_of[name] = idx
    meshes = {}
    report = {"mode": mode, "objects": [], "materials": [], "warnings": []}
    for name, p in parts.items():
        v, t = welded_mesh(p.shape, tolerance, angular_tolerance)
        mr = manifold_report(v, t)
        if not mr["closed"]:
            raise CadError(EXPORT_FAILED, f"mesh of part '{name}' is not a closed manifold "
                           f"({mr['open_edges']} open, {mr['non_manifold_edges']} non-manifold edges)",
                           hint="check the part with assert_valid(); try a smaller --tolerance")
        meshes[name] = (v, t)
        report["objects"].append({"part": name, "material": slots[slot_of[name]].name, "triangles": int(len(t)),
                                  "vertices": int(len(v)), "volume_mm3": round(mr["volume"], 3)})
    if check_overlap and len(parts) > 1:
        names = list(parts)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ov = parts[a].interference(parts[b])
                if ov > 1e-6:
                    report["warnings"].append({"code": "MATERIAL_OVERLAP" if mode == "multimaterial" else "PARTS_OVERLAP",
                                               "message": f"parts '{a}' and '{b}' overlap by {ov:.3f} mm3"
                                               + ("; two materials claim the same volume" if mode == "multimaterial" else ""),
                                               "parts": [a, b], "volume_mm3": round(ov, 4)})
    for k, m in enumerate(slots):
        report["materials"].append({"slot": k, "name": m.name, "color": _color(m.color, "#808080")[:7],
                                    "density": m.density, "kind": m.kind, "extruder": k + 1,
                                    "parts": [n for n, s in slot_of.items() if s == k]})
    base = "".join(f"<base name={quoteattr(m.name)} displaycolor=\"{_color(m.color, '#808080')}\"/>" for m in slots)
    meta = [f'<metadata name="Application">cad {escape(__version__)}</metadata>']
    if title:
        meta.append(f"<metadata name=\"Title\">{escape(title)}</metadata>")
    objects, items, config = [], [], ""
    if mode == "objects":
        for oid, (name, (v, t)) in enumerate(meshes.items(), start=2):
            objects.append(f'<object id="{oid}" type="model" name={quoteattr(name)} pid="1" pindex="{slot_of[name]}">'
                           + _mesh_xml(v, t) + "</object>")
            items.append(f'<item objectid="{oid}"/>')
    else:
        allv, allt, ranges, offset, tri_count = [], [], [], 0, 0
        tri_xml = []
        for name, (v, t) in meshes.items():
            allv.append(v)
            tt = t + offset
            tri_xml.append("".join(f'<triangle v1="{a}" v2="{b}" v3="{c}" pid="1" p1="{slot_of[name]}"/>' for a, b, c in tt))
            ranges.append((name, tri_count, tri_count + len(t) - 1))
            offset += len(v)
            tri_count += len(t)
        V = np.concatenate(allv)
        vs = "".join(f'<vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in V)
        objects.append(f'<object id="2" type="model" name={quoteattr(title or "assembly")} pid="1" pindex="0">'
                       f"<mesh><vertices>{vs}</vertices><triangles>{''.join(tri_xml)}</triangles></mesh></object>")
        items.append('<item objectid="2"/>')
        vols = "".join(
            f'  <volume firstid="{a}" lastid="{b}">\n'
            f'   <metadata type="volume" key="name" value={quoteattr(n)}/>\n'
            f'   <metadata type="volume" key="extruder" value="{slot_of[n] + 1}"/>\n'
            f"  </volume>\n" for n, a, b in ranges)
        config = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n <object id="2" instances_count="1">\n'
                  f'  <metadata type="object" key="name" value={quoteattr(title or "assembly")}/>\n{vols} </object>\n</config>\n')
    model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="{CORE_NS}">'
             + "".join(meta) + f'<resources><basematerials id="1">{base}</basematerials>' + "".join(objects)
             + "</resources><build>" + "".join(items) + "</build></model>\n")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", model)
        if config:
            z.writestr("Metadata/Slic3r_PE_model.config", config)
    os.replace(tmp, p)
    report["path"] = str(p)
    report["bytes"] = p.stat().st_size
    return report


def _hex(color, fallback) -> str:
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        return color
    if isinstance(color, (tuple, list)) and len(color) == 3:
        vals = [float(c) * (255 if max(color) <= 1 else 1) for c in color]
        return "#" + "".join(f"{int(round(c)):02x}" for c in vals)
    r, g, b = fallback
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
