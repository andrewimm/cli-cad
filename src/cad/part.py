"""The :class:`Part`: a single solid body built from a sequence of features.

Coordinate conventions (see docs/REFERENCE.md):

* Units are millimetres and degrees.
* Right-handed, Z up.  "front" looks at the part from -Y, "right" from +X,
  "top" from +Z.
* ``width`` is along X, ``depth`` along Y, ``height`` along Z.

Every modelling call appends a :class:`Feature` to ``part.features`` (the
feature graph) and returns a :class:`FeatureRef` that can be used to select the
faces/edges that feature created.  Faces created by features receive *named
references* such as ``"base.top"`` or ``"hole1.wall"`` that are carried through
later operations using OCCT's topological history (``Modified`` /
``IsDeleted``), so ``part.faces("base.top")`` keeps working after holes and
fillets are applied.  If a later feature destroys a referenced face, selecting
the name raises ``REFERENCE_LOST`` naming the responsible feature.
"""

from __future__ import annotations

import difflib
import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeCylinder,
    BRepPrimAPI_MakePrism,
    BRepPrimAPI_MakeRevol,
    BRepPrimAPI_MakeSphere,
)
from OCP.collections import List_TopoDS_Shape
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.Standard import Standard_Failure
from OCP.TopoDS import TopoDS_Shape

from . import _occ
from .errors import (
    BOOLEAN_FAILED,
    CHAMFER_FAILED,
    EMPTY_SELECTION,
    FILLET_FAILED,
    INVALID_ARGUMENT,
    INVALID_SHAPE,
    NO_BODY,
    OPERATION_FAILED,
    REFERENCE_LOST,
    SHELL_FAILED,
    UNKNOWN_REFERENCE,
    VALIDATION_FAILED,
    CadError,
    CadWarning,
)
from .profile import Plane, Profile, as_plane
from .selection import EdgeSelection, FaceSelection, _Selection, parse_direction

_DIR_NAMES = {
    (0, 0, 1): "top",
    (0, 0, -1): "bottom",
    (0, -1, 0): "front",
    (0, 1, 0): "back",
    (1, 0, 0): "right",
    (-1, 0, 0): "left",
}
_ALIGN = ("min", "center", "max")
_OPS = ("add", "cut", "intersect")


# --------------------------------------------------------------------------- value types


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box in millimetres."""

    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def min(self) -> tuple[float, float, float]:
        return (self.xmin, self.ymin, self.zmin)

    @property
    def max(self) -> tuple[float, float, float]:
        return (self.xmax, self.ymax, self.zmax)

    @property
    def size(self) -> tuple[float, float, float]:
        return (self.xmax - self.xmin, self.ymax - self.ymin, self.zmax - self.zmin)

    @property
    def width(self) -> float:
        """Extent along X."""
        return self.xmax - self.xmin

    @property
    def depth(self) -> float:
        """Extent along Y."""
        return self.ymax - self.ymin

    @property
    def height(self) -> float:
        """Extent along Z."""
        return self.zmax - self.zmin

    @property
    def center(self) -> tuple[float, float, float]:
        return ((self.xmin + self.xmax) / 2, (self.ymin + self.ymax) / 2, (self.zmin + self.zmax) / 2)

    @property
    def diagonal(self) -> float:
        return math.sqrt(sum(s * s for s in self.size))

    def to_dict(self, nd: int = 6) -> dict:
        r = lambda v: [round(c, nd) + 0.0 for c in v]  # noqa: E731
        return {"min": r(self.min), "max": r(self.max), "size": r(self.size), "center": r(self.center)}


@dataclass
class Feature:
    """One node of the feature graph."""

    id: str
    type: str
    params: dict
    depends_on: list[str] = field(default_factory=list)
    selections: list[dict] = field(default_factory=list)
    outputs: dict[str, int] = field(default_factory=dict)
    status: str = "pending"
    warnings: list[CadWarning] = field(default_factory=list)
    error: dict | None = None
    metrics: dict = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "params": self.params,
            "depends_on": self.depends_on,
            "selections": self.selections,
            "outputs": self.outputs,
            "status": self.status,
            "warnings": [w.to_dict() for w in self.warnings],
            "error": self.error,
            "metrics": self.metrics,
            "duration_ms": round(self.duration_ms, 3),
        }


class FeatureRef:
    """Handle returned by modelling operations."""

    def __init__(self, part: "Part", feature: Feature):
        self._part = part
        self.feature = feature

    @property
    def id(self) -> str:
        return self.feature.id

    def faces(self, role: str | None = None) -> FaceSelection:
        """Faces created by this feature, optionally a single role (e.g. 'top', 'wall')."""
        if role:
            return self._part.faces(f"{self.id}.{role}")
        return self._part.faces().created_by(self.id)

    def edges(self) -> EdgeSelection:
        return self._part.faces().created_by(self.id).edges()

    @property
    def refs(self) -> list[str]:
        return sorted(n for n in self._part._refs if n.split(".", 1)[0] == self.id)

    @property
    def warnings(self) -> list[CadWarning]:
        return self.feature.warnings

    def __repr__(self) -> str:
        return f"<FeatureRef {self.id} ({self.feature.type})>"


def _jsonable(v: Any) -> Any:
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    if isinstance(v, float):
        return round(v, 9)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, Profile):
        return v.description
    if isinstance(v, Plane):
        return v.describe()
    if isinstance(v, _Selection):
        return {"selection": v.description, "count": len(v)}
    if isinstance(v, Part):
        return {"part": v.name}
    return repr(v)


def _axis_dir(axis: str | Sequence[float]) -> tuple[float, float, float]:
    return parse_direction(axis)


def _dir_name(n) -> str | None:
    for k, name in _DIR_NAMES.items():
        if sum(a * b for a, b in zip(k, n)) > 1 - 1e-6:
            return name
    return None


def _wrap_occ(fid: str, what: str, code: str, exc: Exception, hint: str | None = None) -> CadError:
    msg = str(exc) or type(exc).__name__
    return CadError(code, f"{what} failed in the geometry kernel: {msg}", feature=fid, hint=hint)


# --------------------------------------------------------------------------- Part


class Part:
    """A single solid body built from features.  See module docs for conventions."""

    def __init__(self, name: str = "part", *, color: str | Sequence[float] | None = None):
        if not isinstance(name, str) or not name:
            raise CadError(INVALID_ARGUMENT, "Part name must be a non-empty string")
        self.name = name
        self.color = color
        self._shape: TopoDS_Shape | None = None
        self._refs: dict[str, list[TopoDS_Shape]] = {}
        self._ref_kind: dict[str, str] = {}
        self._ref_origin: dict[str, str] = {}
        self._ref_lost: dict[str, str] = {}
        self.features: list[Feature] = []
        self._counters: dict[str, int] = {}

    # ================================================================== state access
    @property
    def shape(self) -> TopoDS_Shape:
        """The underlying OCCT shape (raises ``NO_BODY`` if nothing was built yet)."""
        if self._shape is None:
            raise CadError(NO_BODY, f"part '{self.name}' has no geometry yet", hint="start with box(), cylinder(), extrude() or revolve()")
        return self._shape

    @property
    def has_body(self) -> bool:
        return self._shape is not None

    def faces(self, name: str | None = None) -> FaceSelection:
        """All faces, or the faces of named reference ``name`` (e.g. 'base.top')."""
        if name is None:
            return FaceSelection(self, _occ.faces(self.shape), "faces()")
        return FaceSelection(self, self._resolve_ref(name, "face"), f"faces({name!r})")

    def edges(self, name: str | None = None) -> EdgeSelection:
        """All edges, or the edges of named reference ``name``."""
        if name is None:
            return EdgeSelection(self, _occ.edges(self.shape), "edges()")
        if self._ref_kind.get(name) == "face":
            return self.faces(name).edges()
        return EdgeSelection(self, self._resolve_ref(name, "edge"), f"edges({name!r})")

    def references(self) -> dict[str, dict]:
        """Every named reference with its kind, entity count and status."""
        out = {}
        for n in sorted(set(self._refs) | set(self._ref_lost)):
            if n in self._ref_lost:
                out[n] = {"kind": self._ref_kind.get(n), "count": 0, "status": "lost", "lost_in": self._ref_lost[n]}
            else:
                out[n] = {"kind": self._ref_kind[n], "count": len(self._refs[n]), "status": "ok", "created_by": self._ref_origin.get(n)}
        return out

    def _resolve_ref(self, name: str, kind: str) -> list:
        if name in self._ref_lost:
            raise CadError(
                REFERENCE_LOST,
                f"reference '{name}' no longer exists: it was consumed by feature '{self._ref_lost[name]}'",
                hint="select the geometry with a predicate (e.g. faces().facing('+z').max('z')) or name it again after that feature",
                details={"reference": name, "lost_in": self._ref_lost[name]},
            )
        if name not in self._refs:
            # a bare feature id selects everything that feature created ("lip" -> lip.side, lip.start, ...)
            group = [n for n in self._refs if n.startswith(name + ".") and self._ref_kind[n] == kind]
            if group:
                return _dedupe(s for n in group for s in self._refs[n])
            matches = difflib.get_close_matches(name, list(self._refs), n=5, cutoff=0.4)
            raise CadError(
                UNKNOWN_REFERENCE,
                f"part '{self.name}' has no reference named '{name}'",
                hint=(f"did you mean: {', '.join(matches)}?" if matches else "list names with part.references()"),
                details={"available": sorted(self._refs)[:50]},
            )
        if self._ref_kind[name] != kind:
            raise CadError(INVALID_ARGUMENT, f"reference '{name}' holds {self._ref_kind[name]}s, not {kind}s")
        return list(self._refs[name])

    def _names_of(self, shape, kind: str) -> list[str]:
        return sorted(n for n, ss in self._refs.items() if self._ref_kind[n] == kind and any(shape.IsSame(s) for s in ss))

    def tag(self, name: str, selection: _Selection, *, replace: bool = False) -> "Part":
        """Give a selection a semantic name that survives later features.

        ``part.tag("mounting_surface", part.faces().facing("-z"))`` then
        ``part.faces("mounting_surface")``.
        """
        if not isinstance(selection, _Selection):
            raise CadError(INVALID_ARGUMENT, "name() expects a face or edge selection")
        if not selection:
            raise CadError(EMPTY_SELECTION, f"cannot name an empty selection ({selection.description})")
        if name in self._refs and not replace:
            raise CadError(INVALID_ARGUMENT, f"reference '{name}' already exists", hint="pass replace=True to overwrite")
        self._check_current(selection, f"tag:{name}")
        self._refs[name] = list(selection.shapes)
        self._ref_kind[name] = selection.kind
        self._ref_origin[name] = "user"
        self._ref_lost.pop(name, None)
        return self

    # ================================================================== feature plumbing
    def _new_id(self, ftype: str, name: str | None) -> str:
        if name is not None:
            if not isinstance(name, str) or not name or "." in name:
                raise CadError(INVALID_ARGUMENT, f"feature name {name!r} must be a non-empty string without '.'")
            if any(f.id == name for f in self.features if f.status == "ok"):
                raise CadError(INVALID_ARGUMENT, f"feature name '{name}' is already used in part '{self.name}'")
            return name
        n = self._counters.get(ftype, 0) + 1
        while any(f.id == f"{ftype}{n}" for f in self.features):
            n += 1
        self._counters[ftype] = n
        return f"{ftype}{n}"

    def _run(self, ftype: str, name: str | None, params: dict, fn) -> FeatureRef:
        fid = self._new_id(ftype, name)
        feat = Feature(fid, ftype, _jsonable(params))
        prev = next((f.id for f in reversed(self.features) if f.status == "ok"), None)
        if prev and self._shape is not None:
            feat.depends_on.append(prev)
        t0 = time.perf_counter()
        try:
            fn(feat)
            feat.status = "ok"
        except CadError as e:
            e.feature = e.feature or fid
            feat.status = "failed"
            feat.error = e.to_dict()
            feat.duration_ms = (time.perf_counter() - t0) * 1000
            self.features.append(feat)
            raise
        except Standard_Failure as e:
            err = _wrap_occ(fid, ftype, OPERATION_FAILED, e)
            feat.status, feat.error = "failed", err.to_dict()
            self.features.append(feat)
            raise err from e
        feat.duration_ms = (time.perf_counter() - t0) * 1000
        if self._shape is not None:
            feat.metrics = {
                "volume": round(_occ.volume(self._shape), 6),
                "solids": len(_occ.solids(self._shape)),
                "faces": len(_occ.faces(self._shape)),
            }
        self.features.append(feat)
        return FeatureRef(self, feat)

    def _check_current(self, sel: _Selection, fid: str) -> None:
        if sel._part is not self:
            raise CadError(INVALID_ARGUMENT, f"selection {sel.description} belongs to part '{sel._part.name}', not '{self.name}'", feature=fid)
        current = _occ.ShapeSet(_occ.faces(self.shape) if sel.kind == "face" else _occ.edges(self.shape))
        stale = [s for s in sel.shapes if s not in current]
        if stale:
            raise CadError(
                INVALID_ARGUMENT,
                f"selection {sel.description} is stale: {len(stale)} {sel.kind}(s) no longer exist in the part",
                feature=fid,
                hint="selections capture the geometry at the time they are made; re-select after modifying the part",
            )

    def _record_selection(self, feat: Feature, role: str, sel: _Selection) -> None:
        origins = set()
        if sel.kind == "edge":  # an edge depends on the features that made its adjacent faces
            efmap = _occ.edge_face_map(self.shape)
            named = [(f, "face") for e in sel.shapes for f in _occ.faces_of_edge(efmap, e)]
        else:
            named = [(s, sel.kind) for s in sel.shapes]
        for s, kind in named:
            for n in self._names_of(s, kind):
                o = n.split(".", 1)[0]
                if self._ref_origin.get(n) != "user" and o != feat.id:
                    origins.add(o)
        feat.selections.append({"role": role, "selection": sel.description, "kind": sel.kind, "count": len(sel)})
        for o in sorted(origins):
            if o not in feat.depends_on:
                feat.depends_on.append(o)

    def _commit(
        self,
        feat: Feature,
        new_shape: TopoDS_Shape,
        history=None,
        new_refs: dict[str, tuple[str, list]] | None = None,
        new_faces_role: str | None = None,
    ) -> None:
        """Publish ``new_shape`` and carry named references through ``history``."""
        if not _occ.is_valid(new_shape):
            fixed = _occ.fix_shape(new_shape)
            if not _occ.is_valid(fixed):
                raise CadError(
                    INVALID_SHAPE,
                    "the operation produced an invalid solid",
                    feature=feat.id,
                    hint="check for zero-thickness walls, coincident faces or self-intersecting profiles",
                )
            new_shape, history = fixed, None
        present = {"face": _occ.ShapeSet(_occ.faces(new_shape)), "edge": _occ.ShapeSet(_occ.edges(new_shape))}

        def remap(s, kind):
            if history is not None:
                try:
                    if history.IsDeleted(s):
                        return []
                    mods = [present[kind].get(m) for m in history.Modified(s)]
                    mods = [m for m in mods if m is not None]
                    if mods:
                        return mods
                except Standard_Failure:
                    pass
            same = present[kind].get(s)
            return [same] if same is not None else []

        refs: dict[str, list] = {}
        images = _occ.ShapeSet()
        for n, shapes in self._refs.items():
            kind = self._ref_kind[n]
            out: list = []
            for s in shapes:
                out.extend(remap(s, kind))
            if out:
                refs[n] = _dedupe(out)
                for s in refs[n]:
                    images.add(s)
            else:
                self._ref_lost[n] = feat.id
        for n, (kind, shapes) in (new_refs or {}).items():
            out = []
            for s in shapes:
                out.extend(remap(s, kind))
            if out:
                refs[n] = _dedupe(out)
                self._ref_kind[n] = kind
                self._ref_origin[n] = feat.id
                self._ref_lost.pop(n, None)
                for s in refs[n]:
                    images.add(s)
        if new_faces_role and self._shape is not None:
            for f in _occ.faces(self._shape):
                for m in remap(f, "face"):
                    images.add(m)
            fresh = [f for f in _occ.faces(new_shape) if f not in images]
            # also exclude the images of tool references created by this feature
            if fresh:
                n = f"{feat.id}.{new_faces_role}"
                refs[n] = fresh
                self._ref_kind[n], self._ref_origin[n] = "face", feat.id
        for n in list(self._ref_kind):
            if n not in refs and n not in self._ref_lost:
                self._ref_lost[n] = feat.id
        self._refs = refs
        self._shape = new_shape
        feat.outputs = {n: len(v) for n, v in refs.items() if self._ref_origin.get(n) == feat.id}

    def _body_op(self, feat: Feature, tool: TopoDS_Shape, tool_refs: dict, op: str) -> None:
        if op not in _OPS:
            raise CadError(INVALID_ARGUMENT, f"op must be one of {_OPS}, got {op!r}", feature=feat.id)
        if self._shape is None:
            if op != "add":
                raise CadError(NO_BODY, f"cannot '{op}' before the part has a body", feature=feat.id, hint="create the base body first with op='add'")
            self._commit(feat, tool, None, tool_refs)
            return
        before_vol = _occ.volume(self._shape)
        before_solids = len(_occ.solids(self._shape))
        alg = {"add": BRepAlgoAPI_Fuse, "cut": BRepAlgoAPI_Cut, "intersect": BRepAlgoAPI_Common}[op](self._shape, tool)
        if not alg.IsDone():
            raise CadError(BOOLEAN_FAILED, f"boolean {op} failed", feature=feat.id, hint="avoid tangent or coincident faces; offset the tool slightly")
        if op == "add":
            alg.SimplifyResult()
        result = alg.Shape()
        if not _occ.solids(result):
            raise CadError(
                NO_BODY if op != "add" else BOOLEAN_FAILED,
                f"{op} left no solid material",
                feature=feat.id,
                hint="the tool fully contains the body (cut) or does not overlap it (intersect)",
            )
        self._commit(feat, result, alg, tool_refs)
        after_vol = _occ.volume(self._shape)
        tol = 1e-6 * max(before_vol, 1.0)
        if op == "cut" and before_vol - after_vol <= tol:
            feat.warnings.append(
                CadWarning(
                    "CUT_NO_EFFECT",
                    "the cut removed no material; the tool does not overlap the body",
                    feat.id,
                    {"tool_bbox": BBox(*_occ.bbox(tool)[0], *_occ.bbox(tool)[1]).to_dict(4), "body_bbox": self.bbox.to_dict(4)},
                )
            )
        if op == "add" and after_vol - before_vol <= tol:
            feat.warnings.append(CadWarning("ADD_NO_EFFECT", "the added solid lies entirely inside the existing body", feat.id))
        solids_now = len(_occ.solids(self._shape))
        if op == "add" and solids_now > before_solids:
            feat.warnings.append(
                CadWarning(
                    "DISCONNECTED_BODIES",
                    f"the part now has {solids_now} separate solids; the added geometry does not touch the body",
                    feat.id,
                    {"solids": solids_now},
                )
            )

    # ================================================================== primitives
    def box(
        self,
        width: float,
        depth: float,
        height: float,
        *,
        at: Sequence[float] = (0, 0, 0),
        align: str | Sequence[str] = ("center", "center", "min"),
        op: str = "add",
        name: str | None = None,
    ) -> FeatureRef:
        """Box of ``width`` (X) x ``depth`` (Y) x ``height`` (Z).

        ``align`` says where ``at`` sits on the box per axis: 'min', 'center' or
        'max'.  The default ``("center", "center", "min")`` centres the box on
        ``at`` in X/Y and puts its bottom face at ``at``'s Z.

        Named faces: ``<id>.top/bottom/front/back/left/right``.
        """
        _pos(width=width, depth=depth, height=height)
        al = _parse_align(align)
        at3 = _occ.vec(at)
        size = (width, depth, height)
        lo = [at3[i] - {"min": 0, "center": size[i] / 2, "max": size[i]}[al[i]] for i in range(3)]

        def build(feat):
            tool = BRepPrimAPI_MakeBox(gp_Pnt(*lo), width, depth, height).Shape()
            self._body_op(feat, tool, _direction_refs(feat.id, tool), op)

        return self._run("box", name, dict(width=width, depth=depth, height=height, at=at3, align=al, op=op), build)

    def cylinder(
        self,
        diameter: float,
        height: float,
        *,
        at: Sequence[float] = (0, 0, 0),
        axis: str | Sequence[float] = "z",
        align: str = "min",
        op: str = "add",
        name: str | None = None,
    ) -> FeatureRef:
        """Cylinder whose axis passes through ``at`` along ``axis``.

        ``align`` positions ``at`` along the axis: 'min' (the start cap is at
        ``at``), 'center', or 'max'.  Named faces: ``<id>.side``, ``<id>.start``,
        ``<id>.end`` (plus direction names such as ``<id>.top`` when axis-aligned).
        """
        _pos(diameter=diameter, height=height)
        d = _axis_dir(axis)
        at3 = _occ.vec(at)
        shift = {"min": 0.0, "center": height / 2, "max": height}.get(align)
        if shift is None:
            raise CadError(INVALID_ARGUMENT, f"align must be one of {_ALIGN}, got {align!r}")
        base = tuple(a - shift * c for a, c in zip(at3, d))

        def build(feat):
            tool = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*base), gp_Dir(*d)), diameter / 2, height).Shape()
            self._body_op(feat, tool, _axial_refs(feat.id, tool, d), op)

        return self._run("cylinder", name, dict(diameter=diameter, height=height, at=at3, axis=d, align=align, op=op), build)

    def sphere(self, diameter: float, *, at: Sequence[float] = (0, 0, 0), op: str = "add", name: str | None = None) -> FeatureRef:
        """Sphere centred at ``at``.  Named faces: ``<id>.surface``."""
        _pos(diameter=diameter)
        at3 = _occ.vec(at)

        def build(feat):
            tool = BRepPrimAPI_MakeSphere(gp_Pnt(*at3), diameter / 2).Shape()
            self._body_op(feat, tool, {f"{feat.id}.surface": ("face", _occ.faces(tool))}, op)

        return self._run("sphere", name, dict(diameter=diameter, at=at3, op=op), build)

    def extrude(
        self,
        profile: Profile,
        distance: float,
        *,
        plane: str | Plane = "XY",
        offset: float = 0.0,
        symmetric: bool = False,
        through: bool = False,
        op: str = "add",
        name: str | None = None,
    ) -> FeatureRef:
        """Extrude a 2D ``profile`` drawn on ``plane`` along the plane normal.

        Negative ``distance`` extrudes against the normal.  ``symmetric=True``
        extrudes ``distance/2`` to each side.  ``offset`` moves the sketch plane
        along its normal first.  Use ``op='cut'`` for pockets and cut-outs;
        ``through=True`` extends the extrusion through the whole part in both
        directions (``distance`` is then ignored).

        Named faces: ``<id>.start`` (on the sketch plane), ``<id>.end``,
        ``<id>.side`` (plus direction names like ``<id>.top`` when axis-aligned).
        """
        if not isinstance(profile, Profile):
            raise CadError(INVALID_ARGUMENT, "extrude() expects a Profile (e.g. Profile.rect(10, 20))")
        if not isinstance(distance, (int, float)) or distance == 0:
            raise CadError(INVALID_ARGUMENT, f"extrude distance must be a non-zero number, got {distance!r}")
        pl = as_plane(plane, offset)
        n = pl.normal

        def build(feat):
            face = profile.placed(pl)
            dist = distance
            if through:
                lo, hi = _occ.bbox(self.shape)
                span = 2 * math.dist(lo, hi) + 2 * math.dist(pl.origin, ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2))
                dist = span
            if symmetric or through:
                t = gp_Trsf()
                t.SetTranslation(gp_Vec(*[-c * abs(dist) / 2 for c in n]))
                face = BRepBuilderAPI_Transform(face, t, True).Shape()
                dist = abs(dist)
            prism = BRepPrimAPI_MakePrism(face, gp_Vec(*[c * dist for c in n]))
            prism.Build()
            if not prism.IsDone():
                raise CadError(OPERATION_FAILED, "extrusion failed", feature=feat.id)
            tool = prism.Shape()
            d = n if dist > 0 else tuple(-c for c in n)
            self._body_op(feat, tool, _axial_refs(feat.id, tool, d, start_point=pl.origin), op)

        return self._run(
            "extrude", name, dict(profile=profile, distance=distance, plane=pl, symmetric=symmetric, through=through, op=op), build
        )

    def revolve(
        self,
        profile: Profile,
        angle: float = 360.0,
        *,
        plane: str | Plane = "XZ",
        axis: str = "v",
        op: str = "add",
        name: str | None = None,
    ) -> FeatureRef:
        """Revolve a 2D ``profile`` about an axis of its sketch plane.

        ``axis='v'`` revolves about the plane's v axis through its origin (for
        the default 'XZ' plane that is the world Z axis, so a profile drawn at
        u>0 becomes a shaft/turned part around Z).  ``axis='u'`` uses the u axis.
        Named faces: ``<id>.surface``.
        """
        pl = as_plane(plane)
        if axis not in ("u", "v"):
            raise CadError(INVALID_ARGUMENT, "revolve axis must be 'u' or 'v' (an axis of the sketch plane)")
        if not 0 < abs(angle) <= 360:
            raise CadError(INVALID_ARGUMENT, f"revolve angle must be in (0, 360], got {angle}")
        direction = pl.u if axis == "u" else pl.v

        def build(feat):
            face = profile.placed(pl)
            rev = BRepPrimAPI_MakeRevol(face, gp_Ax1(gp_Pnt(*pl.origin), gp_Dir(*direction)), math.radians(angle), True)
            rev.Build()
            if not rev.IsDone():
                raise CadError(OPERATION_FAILED, "revolve failed", feature=feat.id, hint="the profile must not cross the revolve axis")
            tool = rev.Shape()
            refs = {f"{feat.id}.surface": ("face", _occ.faces(tool))}
            refs.update({k: v for k, v in _direction_refs(feat.id, tool).items()})
            self._body_op(feat, tool, refs, op)

        return self._run("revolve", name, dict(profile=profile, angle=angle, plane=pl, axis=axis, op=op), build)

    # ================================================================== holes
    def hole(
        self,
        diameter: float,
        at: Sequence[float],
        *,
        depth: float | None = None,
        direction: str | Sequence[float] = "-z",
        counterbore: tuple[float, float] | None = None,
        countersink: tuple[float, float] | float | None = None,
        name: str | None = None,
    ) -> FeatureRef:
        """Drill one round hole.

        The hole travels along ``direction`` (default ``'-z'``: drilled down from
        the top).  ``at`` is either a 3D start point, or a 2D point in the two
        axes perpendicular to an axis-aligned ``direction`` (for ±Z: (x, y); ±Y:
        (x, z); ±X: (y, z)) — the hole then starts at the bounding-box face of
        the part that it enters.  ``depth=None`` drills through everything.

        ``counterbore=(diameter, depth)`` and ``countersink=(diameter, angle_deg)``
        (angle defaults to 90) add the usual fastener recesses at the entry.

        Named faces: ``<id>.wall`` (plus ``<id>.floor`` for blind holes,
        ``<id>.counterbore``, ``<id>.countersink``).
        """
        return self._holes("hole", name, diameter, [at], depth, direction, counterbore, countersink, {})

    def holes(
        self,
        diameter: float,
        positions: Sequence[Sequence[float]],
        *,
        depth: float | None = None,
        direction: str | Sequence[float] = "-z",
        counterbore: tuple[float, float] | None = None,
        countersink: tuple[float, float] | float | None = None,
        name: str | None = None,
    ) -> FeatureRef:
        """Drill identical holes at several ``positions`` (same rules as :meth:`hole`).

        Named faces: ``<id>.wall`` (all holes) and ``<id>.wall.<i>`` per hole.
        """
        return self._holes("holes", name, diameter, list(positions), depth, direction, counterbore, countersink, {})

    def hole_pattern(
        self,
        diameter: float,
        *,
        spacing: Sequence[float],
        count: Sequence[int] = (2, 2),
        center: Sequence[float] = (0, 0),
        depth: float | None = None,
        direction: str | Sequence[float] = "-z",
        counterbore: tuple[float, float] | None = None,
        countersink: tuple[float, float] | float | None = None,
        name: str | None = None,
    ) -> FeatureRef:
        """Rectangular grid of holes centred on ``center``.

        ``spacing=(sx, sy)`` is the centre-to-centre distance and
        ``count=(nx, ny)`` the number of holes along each in-plane axis.  For
        the default downward direction the grid lies in X/Y, so
        ``spacing=(48, 28), count=(2, 2)`` puts holes at (±24, ±14).
        """
        if len(spacing) != 2 or len(count) != 2:
            raise CadError(INVALID_ARGUMENT, "spacing and count must be 2-tuples: (sx, sy), (nx, ny)")
        nx, ny = int(count[0]), int(count[1])
        if nx < 1 or ny < 1:
            raise CadError(INVALID_ARGUMENT, "count values must be >= 1")
        cx, cy = center[0], center[1]
        pts = [
            (cx + (i - (nx - 1) / 2) * spacing[0], cy + (j - (ny - 1) / 2) * spacing[1])
            for j in range(ny)
            for i in range(nx)
        ]
        extra = {"spacing": list(spacing), "count": [nx, ny], "center": list(center)}
        return self._holes("hole_pattern", name, diameter, pts, depth, direction, counterbore, countersink, extra)

    def bolt_circle(
        self,
        diameter: float,
        *,
        circle_diameter: float,
        count: int,
        center: Sequence[float] = (0, 0),
        start_angle: float = 0.0,
        depth: float | None = None,
        direction: str | Sequence[float] = "-z",
        counterbore: tuple[float, float] | None = None,
        countersink: tuple[float, float] | float | None = None,
        name: str | None = None,
    ) -> FeatureRef:
        """``count`` holes evenly spaced on a circle of ``circle_diameter`` (the PCD).

        The first hole sits at ``start_angle`` degrees measured from the first
        in-plane axis (+X for vertical holes) counter-clockwise.
        """
        _pos(circle_diameter=circle_diameter)
        if count < 1:
            raise CadError(INVALID_ARGUMENT, "count must be >= 1")
        r = circle_diameter / 2
        pts = [
            (center[0] + r * math.cos(math.radians(start_angle + 360 * i / count)),
             center[1] + r * math.sin(math.radians(start_angle + 360 * i / count)))
            for i in range(count)
        ]
        extra = {"circle_diameter": circle_diameter, "count": count, "center": list(center), "start_angle": start_angle}
        return self._holes("bolt_circle", name, diameter, pts, depth, direction, counterbore, countersink, extra)

    def _holes(self, ftype, name, diameter, positions, depth, direction, counterbore, countersink, extra) -> FeatureRef:
        _pos(diameter=diameter)
        if depth is not None:
            _pos(depth=depth)
        if not positions:
            raise CadError(INVALID_ARGUMENT, "no hole positions given")
        d = _axis_dir(direction)
        if counterbore is not None:
            if len(counterbore) != 2:
                raise CadError(INVALID_ARGUMENT, "counterbore must be (diameter, depth)")
            _pos(counterbore_diameter=counterbore[0], counterbore_depth=counterbore[1])
            if counterbore[0] <= diameter:
                raise CadError(INVALID_ARGUMENT, "counterbore diameter must exceed the hole diameter")
        if countersink is not None:
            cs = (countersink, 90.0) if isinstance(countersink, (int, float)) else tuple(countersink)
            if cs[0] <= diameter:
                raise CadError(INVALID_ARGUMENT, "countersink diameter must exceed the hole diameter")
            if not 0 < cs[1] < 180:
                raise CadError(INVALID_ARGUMENT, "countersink angle must be between 0 and 180 degrees")
            countersink = cs
        params = dict(diameter=diameter, positions=positions, depth=depth, direction=d, counterbore=counterbore, countersink=countersink, **extra)

        def build(feat):
            body = self.shape
            lo, hi = _occ.bbox(body)
            diag = math.dist(lo, hi)
            starts = [self._hole_start(p, d, lo, hi, feat.id) for p in positions]
            margin = 1.0 + 1e-3 * diag
            tools, refs_wall, refs_floor, refs_cb, refs_cs = [], [], [], [], []
            for start in starts:
                length = (depth if depth is not None else _extent_along(lo, hi, start, d) + margin)
                back = tuple(s - margin * c for s, c in zip(start, d))
                cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*back), gp_Dir(*d)), diameter / 2, length + margin).Shape()
                pieces = [cyl]
                walls = [f for f in _occ.faces(cyl) if _occ.surface_type(f) == "cylinder"]
                floors = [f for f in _occ.faces(cyl) if _occ.surface_type(f) == "plane"
                          and sum(a * b for a, b in zip(_occ.face_normal(f), d)) > 0.5] if depth is not None else []
                cb_faces, cs_faces = [], []
                if counterbore is not None:
                    cbd, cbh = counterbore
                    cb = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*back), gp_Dir(*d)), cbd / 2, cbh + margin).Shape()
                    cb_faces = _occ.faces(cb)
                    pieces.append(cb)
                if countersink is not None:
                    csd, ang = countersink
                    h = (csd - diameter) / 2 / math.tan(math.radians(ang / 2))
                    cone = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(*start), gp_Dir(*d)), csd / 2, diameter / 2, h).Shape()
                    cap = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*back), gp_Dir(*d)), csd / 2, margin).Shape()
                    cs_faces = [f for f in _occ.faces(cone) if _occ.surface_type(f) == "cone"]
                    pieces += [cone, cap]
                tools.append(pieces)
                refs_wall.append(walls)
                refs_floor.append(floors)
                refs_cb.append(cb_faces)
                refs_cs.append(cs_faces)
            flat_tools = [p for ps in tools for p in ps]
            alg = BRepAlgoAPI_Cut()
            args, tl = List_TopoDS_Shape(), List_TopoDS_Shape()
            args.Append(body)
            for t in flat_tools:
                tl.Append(t)
            alg.SetArguments(args)
            alg.SetTools(tl)
            alg.Build()
            if not alg.IsDone():
                raise CadError(BOOLEAN_FAILED, "hole cut failed", feature=feat.id)
            fid = feat.id
            refs = {f"{fid}.wall": ("face", [f for w in refs_wall for f in w])}
            if len(positions) > 1:
                for i, w in enumerate(refs_wall):
                    refs[f"{fid}.wall.{i}"] = ("face", w)
            if depth is not None:
                refs[f"{fid}.floor"] = ("face", [f for w in refs_floor for f in w])
            if counterbore is not None:
                refs[f"{fid}.counterbore"] = ("face", [f for w in refs_cb for f in w if _occ.surface_type(f) == "cylinder"])
                refs[f"{fid}.counterbore_floor"] = ("face", [f for w in refs_cb for f in w if _occ.surface_type(f) == "plane"])
            if countersink is not None:
                refs[f"{fid}.countersink"] = ("face", [f for w in refs_cs for f in w])
            before = _occ.volume(body)
            self._commit(feat, alg.Shape(), alg, refs)
            removed = before - _occ.volume(self._shape)
            if removed <= 1e-9 * max(before, 1):
                feat.warnings.append(CadWarning("CUT_NO_EFFECT", "no hole intersects the part", fid, {"positions": _jsonable(positions)}))
            for kind, key in (("counterbore", f"{fid}.counterbore"), ("countersink", f"{fid}.countersink")):
                if (counterbore if kind == "counterbore" else countersink) is not None and key not in self._refs:
                    feat.warnings.append(CadWarning(
                        "RECESS_NO_EFFECT", f"the {kind} did not cut any material: its start point is outside the part",
                        fid, {"starts": _jsonable(starts)}))
            if len(positions) > 1:
                missing = [i for i in range(len(positions)) if f"{fid}.wall.{i}" not in self._refs]
                if missing:
                    feat.warnings.append(
                        CadWarning(
                            "HOLE_MISSED",
                            f"{len(missing)} of {len(positions)} holes do not intersect the part",
                            fid,
                            {"missed_positions": _jsonable([positions[i] for i in missing])},
                        )
                    )

        return self._run(ftype, name, params, build)

    def _hole_start(self, p, d, lo, hi, fid):
        """Start point of a hole.  3D points are used as given; 2D points start where the
        drilling line first enters the actual material (falling back to the bbox face)."""
        if len(p) == 3:
            return _occ.vec(p)
        if len(p) != 2:
            raise CadError(INVALID_ARGUMENT, f"hole position must be (a, b) or (x, y, z), got {p!r}", feature=fid)
        axis = max(range(3), key=lambda i: abs(d[i]))
        if abs(abs(d[axis]) - 1) > 1e-9:
            raise CadError(INVALID_ARGUMENT, "2D hole positions require an axis-aligned direction; pass a 3D start point", feature=fid)
        others = [i for i in range(3) if i != axis]
        pt = [0.0, 0.0, 0.0]
        pt[others[0]], pt[others[1]] = float(p[0]), float(p[1])
        pt[axis] = hi[axis] if d[axis] < 0 else lo[axis]
        t = _occ.first_hit(self.shape, pt, d)
        if t is not None:
            pt = [c + t * dc for c, dc in zip(pt, d)]
        return tuple(pt)

    # ================================================================== dress-up features
    def fillet(self, edges: EdgeSelection, radius: float, *, name: str | None = None) -> FeatureRef:
        """Round the selected edges with ``radius``.  Named faces: ``<id>.faces``."""
        return self._dressup("fillet", name, edges, radius)

    def chamfer(self, edges: EdgeSelection, distance: float, *, name: str | None = None) -> FeatureRef:
        """Bevel the selected edges by ``distance`` (symmetric).  Named faces: ``<id>.faces``."""
        return self._dressup("chamfer", name, edges, distance)

    def _dressup(self, ftype, name, edges, size) -> FeatureRef:
        if not isinstance(edges, EdgeSelection):
            raise CadError(INVALID_ARGUMENT, f"{ftype}() expects an edge selection such as part.edges().vertical()")
        _pos(**{"radius" if ftype == "fillet" else "distance": size})
        key = "radius" if ftype == "fillet" else "distance"

        def build(feat):
            if not edges:
                raise CadError(EMPTY_SELECTION, f"{ftype} selection {edges.description} matched no edges", feature=feat.id,
                               hint="print part.edges().info() to see candidate edges")
            self._check_current(edges, feat.id)
            self._record_selection(feat, "edges", edges)
            mk = self._make_dressup(ftype, edges.shapes, size)
            ok = False
            try:
                mk.Build()
                ok = mk.IsDone()
            except Standard_Failure:
                ok = False
            if not ok:
                bad = []
                for e in edges.shapes:
                    t = self._make_dressup(ftype, [e], size)
                    try:
                        t.Build()
                        good = t.IsDone()
                    except Standard_Failure:
                        good = False
                    if not good:
                        bad.append(edges._info(e))
                max_hint = self._dressup_limit(edges.shapes)
                if bad:
                    hint = (f"try a {key} below ~{max_hint:.3g} mm (the shortest edge adjacent to the selection); "
                            "large radii cannot fit next to short edges or thin walls")
                else:
                    hint = ("the edges interfere with each other or with earlier fillets: apply them in separate "
                            f"{ftype}() calls, change the order, or narrow the selection")
                raise CadError(
                    FILLET_FAILED if ftype == "fillet" else CHAMFER_FAILED,
                    f"{ftype} of {len(edges)} edge(s) with {key} {size} failed"
                    + (f"; {len(bad)} edge(s) fail even individually" if bad else "; each edge succeeds alone but not together"),
                    feature=feat.id,
                    hint=hint,
                    details={"failing_edges": bad[:10]},
                )
            refs = {}
            gen = []
            for e in edges.shapes:
                try:
                    gen.extend(list(mk.Generated(e)))
                except Standard_Failure:
                    pass
            if gen:
                refs[f"{feat.id}.faces"] = ("face", gen)
            self._commit(feat, mk.Shape(), mk, refs, new_faces_role=None if gen else "faces")

        return self._run(ftype, name, {key: size, "edges": edges}, build)

    def _make_dressup(self, ftype, edge_list, size):
        if ftype == "fillet":
            mk = BRepFilletAPI_MakeFillet(self.shape)
            for e in edge_list:
                mk.Add(size, e)
        else:
            mk = BRepFilletAPI_MakeChamfer(self.shape)
            for e in edge_list:
                mk.Add(size, e)
        return mk

    def _dressup_limit(self, edge_list) -> float:
        efmap = _occ.edge_face_map(self.shape)
        shortest = math.inf
        for e in edge_list:
            for f in _occ.faces_of_edge(efmap, e):
                for fe in _occ.edges(f):
                    if not fe.IsSame(e):
                        shortest = min(shortest, _occ.length(fe))
        return shortest if shortest < math.inf else 0.0

    def shell(self, thickness: float, *, open_faces: FaceSelection | None = None, name: str | None = None) -> FeatureRef:
        """Hollow the part leaving walls of ``thickness`` (material removed inward).

        ``open_faces`` are removed to leave the shell open (e.g. the top face of
        an enclosure).  Named faces: ``<id>.inner``.
        """
        _pos(thickness=thickness)

        def build(feat):
            removed = List_TopoDS_Shape()
            if open_faces is not None:
                if not isinstance(open_faces, FaceSelection):
                    raise CadError(INVALID_ARGUMENT, "open_faces must be a face selection", feature=feat.id)
                if not open_faces:
                    raise CadError(EMPTY_SELECTION, f"open_faces {open_faces.description} matched no faces", feature=feat.id)
                self._check_current(open_faces, feat.id)
                self._record_selection(feat, "open_faces", open_faces)
                for f in open_faces.shapes:
                    removed.Append(f)
            mk = BRepOffsetAPI_MakeThickSolid()
            try:
                mk.MakeThickSolidByJoin(self.shape, removed, -thickness, 1e-4)
                mk.Build()
                ok = mk.IsDone()
            except Standard_Failure:
                ok = False
            if not ok:
                bb = self.bbox
                raise CadError(
                    SHELL_FAILED,
                    f"shell with thickness {thickness} failed",
                    feature=feat.id,
                    hint=f"thickness must be well below half the smallest dimension ({min(bb.size) / 2:.3g} mm) and "
                         "smaller than any fillet radius; shell before adding fillets or small features",
                )
            self._commit(feat, mk.Shape(), mk, {}, new_faces_role="inner")

        return self._run("shell", name, {"thickness": thickness, "open_faces": open_faces}, build)

    # ================================================================== combining parts
    def union(self, other: "Part", *, name: str | None = None) -> FeatureRef:
        """Fuse another part's body into this one (its references are kept as ``<id>.<ref>``)."""
        return self._combine("union", "add", other, name)

    def cut(self, other: "Part", *, name: str | None = None) -> FeatureRef:
        """Subtract another part's body from this one."""
        return self._combine("cut", "cut", other, name)

    def intersect(self, other: "Part", *, name: str | None = None) -> FeatureRef:
        """Keep only the volume shared with another part."""
        return self._combine("intersect", "intersect", other, name)

    def _combine(self, ftype, op, other, name) -> FeatureRef:
        if not isinstance(other, Part):
            raise CadError(INVALID_ARGUMENT, f"{ftype}() expects a Part")

        def build(feat):
            tool = other.shape
            refs = {f"{feat.id}.{n}": (other._ref_kind[n], shapes) for n, shapes in other._refs.items()}
            refs[f"{feat.id}.{other.name}"] = ("face", _occ.faces(tool))
            self._body_op(feat, tool, refs, op)

        return self._run(ftype, name, {"other": other}, build)

    # ================================================================== transforms
    def translate(self, offset: Sequence[float], *, name: str | None = None) -> FeatureRef:
        """Move the whole body by ``offset`` (x, y, z)."""
        o = _occ.vec(offset)
        t = gp_Trsf()
        t.SetTranslation(gp_Vec(*o))
        return self._transform("translate", name, t, {"offset": o})

    def rotate(self, angle: float, *, axis: str | Sequence[float] = "z", center: Sequence[float] = (0, 0, 0), name: str | None = None) -> FeatureRef:
        """Rotate the body by ``angle`` degrees about ``axis`` through ``center`` (right-hand rule)."""
        d = _axis_dir(axis)
        t = gp_Trsf()
        t.SetRotation(gp_Ax1(gp_Pnt(*_occ.vec(center)), gp_Dir(*d)), math.radians(angle))
        return self._transform("rotate", name, t, {"angle": angle, "axis": d, "center": _occ.vec(center)})

    def mirror(self, plane: str | Plane = "YZ", *, keep_original: bool = True, name: str | None = None) -> FeatureRef:
        """Mirror the body across ``plane``.  With ``keep_original`` the mirror image is fused in."""
        pl = as_plane(plane)
        t = gp_Trsf()
        t.SetMirror(gp_Ax2(gp_Pnt(*pl.origin), gp_Dir(*pl.normal)))
        if not keep_original:
            return self._transform("mirror", name, t, {"plane": pl, "keep_original": False})

        def build(feat):
            mk = BRepBuilderAPI_Transform(self.shape, t, True)
            self._body_op(feat, mk.Shape(), {}, "add")

        return self._run("mirror", name, {"plane": pl, "keep_original": True}, build)

    def _transform(self, ftype, name, trsf, params) -> FeatureRef:
        def build(feat):
            mk = BRepBuilderAPI_Transform(self.shape, trsf, True)
            self._commit(feat, mk.Shape(), mk, {})

        return self._run(ftype, name, params, build)

    # ================================================================== queries
    @property
    def bbox(self) -> BBox:
        """Tight axis-aligned bounding box."""
        lo, hi = _occ.bbox(self.shape)
        return BBox(*lo, *hi)

    @property
    def volume(self) -> float:
        """Volume in mm^3."""
        return _occ.volume(self.shape)

    @property
    def area(self) -> float:
        """Total surface area in mm^2."""
        return _occ.area(self.shape)

    @property
    def center_of_mass(self) -> tuple[float, float, float]:
        """Centroid of the solid volume (uniform density)."""
        return _occ.center_of_mass(self.shape)

    @property
    def solid_count(self) -> int:
        return len(_occ.solids(self.shape))

    def mass(self, density_g_cm3: float) -> float:
        """Mass in grams for a material density in g/cm^3 (PLA ~1.24, PETG ~1.27, Al ~2.70)."""
        return self.volume / 1000.0 * density_g_cm3

    def is_valid(self) -> bool:
        """True if the BRep passes OCCT's validity checker."""
        return self._shape is not None and _occ.is_valid(self._shape)

    def assert_valid(self, *, solids: int | None = 1) -> "Part":
        """Raise ``VALIDATION_FAILED`` unless the shape is valid and has ``solids`` solids."""
        if self._shape is None:
            raise CadError(NO_BODY, f"part '{self.name}' has no geometry")
        problems = []
        if not _occ.is_valid(self._shape):
            problems.append("BRep validity check failed")
        n = self.solid_count
        if solids is not None and n != solids:
            problems.append(f"expected {solids} solid(s), found {n}")
        if self.volume <= 0:
            problems.append("volume is not positive")
        if problems:
            raise CadError(
                VALIDATION_FAILED,
                f"part '{self.name}' is not valid: " + "; ".join(problems),
                hint="disconnected solids usually mean an added feature does not touch the body"
                if any("solid" in p for p in problems) else None,
                details={"problems": problems, "solids": n},
            )
        return self

    def distance_to(self, other: "Part") -> float:
        """Minimum distance between the two bodies (0 if they touch or overlap)."""
        return _occ.distance(self.shape, other.shape)[0]

    def interference(self, other: "Part") -> float:
        """Volume (mm^3) shared with ``other``; 0 means no collision."""
        common = BRepAlgoAPI_Common(self.shape, other.shape)
        if not common.IsDone():
            raise CadError(BOOLEAN_FAILED, "interference check failed")
        return _occ.volume(common.Shape())

    def find_holes(self) -> list[dict]:
        """Round holes found in the body: diameter, axis, entry point, depth.

        Hole walls split across several faces are merged.  This inspects the
        actual geometry, so it also verifies holes made by any means.
        """
        groups: list[dict] = []
        for f in _occ.faces(self.shape):
            info = _occ.cylinder_info(f)
            if not info or not info["concave"]:
                continue
            a = info["axis"]
            # canonical axis sense: largest component positive
            k = max(range(3), key=lambda i: abs(a[i]))
            if a[k] < 0:
                a = tuple(-c for c in a)
            p = info["axis_point"]
            # project the axis point to the plane through the origin perpendicular to the axis
            t = sum(pi * ai for pi, ai in zip(p, a))
            foot = tuple(pi - t * ai for pi, ai in zip(p, a))
            for g in groups:
                if abs(g["diameter"] - info["diameter"]) < 1e-6 and sum(x * y for x, y in zip(g["axis"], a)) > 1 - 1e-9 \
                        and math.dist(g["_foot"], foot) < 1e-6:
                    g["_faces"].append(f)
                    break
            else:
                groups.append({"diameter": info["diameter"], "axis": a, "_foot": foot, "_faces": [], "_angle": 0.0})
                g = groups[-1]
                g["_faces"].append(f)
            g["_angle"] = g.get("_angle", 0.0) + info["angle"]
        out = []
        for g in groups:
            if g["_angle"] < 2 * math.pi - 1e-3:  # partial cylinders are fillets/slots, not holes
                continue
            a = g["axis"]
            lo, hi = math.inf, -math.inf
            for f in g["_faces"]:
                for v in _occ.vertices(f):
                    from OCP.BRep import BRep_Tool

                    q = BRep_Tool.Pnt_s(v)
                    t = q.X() * a[0] + q.Y() * a[1] + q.Z() * a[2]
                    lo, hi = min(lo, t), max(hi, t)
            ctr_lo = tuple(fc + lo * ac for fc, ac in zip(g["_foot"], a))
            names = sorted({n for f in g["_faces"] for n in self._names_of(f, "face")})
            out.append({
                "diameter": round(g["diameter"], 6),
                "axis": [round(c, 6) + 0.0 for c in a],
                "position": [round(c, 4) + 0.0 for c in ctr_lo],
                "depth": round(hi - lo, 4),
                "names": names,
            })
        out.sort(key=lambda h: (h["diameter"], h["position"]))
        return out

    def summary(self) -> dict:
        """JSON-friendly geometric summary used by ``cad inspect``."""
        if self._shape is None:
            return {"name": self.name, "has_body": False, "features": len(self.features)}
        return {
            "name": self.name,
            "has_body": True,
            "valid": self.is_valid(),
            "solids": self.solid_count,
            "faces": len(_occ.faces(self._shape)),
            "edges": len(_occ.edges(self._shape)),
            "volume": round(self.volume, 6),
            "area": round(self.area, 6),
            "center_of_mass": [round(c, 6) + 0.0 for c in self.center_of_mass],
            "bbox": self.bbox.to_dict(),
            "holes": len(self.find_holes()),
            "features": len(self.features),
            "warnings": [w.to_dict() for f in self.features for w in f.warnings],
        }

    def feature_graph(self) -> dict:
        """The feature graph: features, dependencies and named references."""
        return {
            "part": self.name,
            "features": [f.to_dict() for f in self.features],
            "references": self.references(),
        }

    @property
    def warnings(self) -> list[CadWarning]:
        return [w for f in self.features for w in f.warnings]

    # ================================================================== output
    def export(self, path: str, **kwargs) -> str:
        """Write STEP (.step/.stp), STL (.stl) or BREP (.brep) depending on the extension."""
        from .export import export_shape

        return export_shape(self.shape, path, name=self.name, **kwargs)

    def copy(self, name: str | None = None) -> "Part":
        """Independent copy (geometry is shared immutably, history is copied)."""
        import copy as _copy

        p = Part(name or self.name, color=self.color)
        p._shape = self._shape
        p._refs = {k: list(v) for k, v in self._refs.items()}
        p._ref_kind = dict(self._ref_kind)
        p._ref_origin = dict(self._ref_origin)
        p._ref_lost = dict(self._ref_lost)
        p.features = _copy.deepcopy(self.features)
        p._counters = dict(self._counters)
        return p

    # ================================================================== persistence
    def _persisted_refs(self) -> dict:
        """Named references as indices into faces()/edges() order (for revision storage)."""
        if self._shape is None:
            return {}
        index = {"face": _occ.faces(self._shape), "edge": _occ.edges(self._shape)}
        lookup = {k: {} for k in index}
        for k, items in index.items():
            for i, s in enumerate(items):
                lookup[k].setdefault(hash(s), []).append((i, s))
        out = {}
        for n, shapes in self._refs.items():
            kind = self._ref_kind[n]
            idx = []
            for s in shapes:
                for i, o in lookup[kind].get(hash(s), ()):
                    if o.IsSame(s):
                        idx.append(i)
                        break
            out[n] = {"kind": kind, "indices": idx, "origin": self._ref_origin.get(n)}
        return {"refs": out, "lost": dict(self._ref_lost)}

    @classmethod
    def _rehydrate(cls, name: str, shape: TopoDS_Shape, color=None, refs: dict | None = None, features: list[dict] | None = None) -> "Part":
        """Rebuild a queryable Part from stored geometry (no script re-execution)."""
        p = cls(name, color=color)
        p._shape = shape
        refs = refs or {}
        index = {"face": _occ.faces(shape), "edge": _occ.edges(shape)}
        for n, r in refs.get("refs", {}).items():
            items = index[r["kind"]]
            p._refs[n] = [items[i] for i in r["indices"] if 0 <= i < len(items)]
            p._ref_kind[n] = r["kind"]
            p._ref_origin[n] = r.get("origin")
        p._ref_lost = dict(refs.get("lost", {}))
        for fd in features or []:
            f = Feature(fd["id"], fd["type"], fd.get("params", {}), fd.get("depends_on", []), fd.get("selections", []),
                        fd.get("outputs", {}), fd.get("status", "ok"),
                        [CadWarning(w["code"], w["message"], w.get("feature"), w.get("details", {})) for w in fd.get("warnings", [])],
                        fd.get("error"), fd.get("metrics", {}), fd.get("duration_ms", 0.0))
            p.features.append(f)
        return p

    def __repr__(self) -> str:
        if self._shape is None:
            return f"<Part {self.name!r} (empty)>"
        s = self.bbox.size
        return f"<Part {self.name!r} {s[0]:.3g}x{s[1]:.3g}x{s[2]:.3g} mm, {len(self.features)} features>"


# --------------------------------------------------------------------------- helpers


def _dedupe(shapes: Iterable) -> list:
    seen = _occ.ShapeSet()
    out = []
    for s in shapes:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _pos(**kw):
    for k, v in kw.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
            raise CadError(INVALID_ARGUMENT, f"{k} must be a positive number (mm), got {v!r}")


def _parse_align(align) -> tuple[str, str, str]:
    if isinstance(align, str):
        align = (align, align, align)
    al = tuple(align)
    if len(al) != 3 or any(a not in _ALIGN for a in al):
        raise CadError(INVALID_ARGUMENT, f"align must be one of {_ALIGN} or a 3-tuple of them, got {align!r}")
    return al  # type: ignore[return-value]


def _extent_along(lo, hi, start, d) -> float:
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    return max(sum((c[i] - start[i]) * d[i] for i in range(3)) for c in corners)


def _direction_refs(fid: str, tool) -> dict:
    refs: dict[str, tuple[str, list]] = {}
    for f in _occ.faces(tool):
        if _occ.surface_type(f) != "plane":
            continue
        nm = _dir_name(_occ.face_normal(f))
        if nm:
            refs.setdefault(f"{fid}.{nm}", ("face", []))[1].append(f)
    return refs


def _axial_refs(fid: str, tool, d, start_point=None) -> dict:
    refs = _direction_refs(fid, tool)
    start, end, side = [], [], []
    for f in _occ.faces(tool):
        if _occ.surface_type(f) == "plane":
            dot = sum(a * b for a, b in zip(_occ.face_normal(f), d))
            if dot < -1 + 1e-6:
                start.append(f)
                continue
            if dot > 1 - 1e-6:
                end.append(f)
                continue
        side.append(f)
    for role, fs in (("start", start), ("end", end), ("side", side)):
        if fs:
            refs[f"{fid}.{role}"] = ("face", fs)
    return refs
