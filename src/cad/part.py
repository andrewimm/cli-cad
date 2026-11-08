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

import contextlib
import difflib
import math
from pathlib import Path
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
from OCP.gp import gp_Ax3, gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
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
    phases_ms: dict = field(default_factory=dict)  # where the time went: tools, boolean, validate, references, measure
    param_sources: dict = field(default_factory=dict)  # setting ("radius", "at[0]") -> Parameter name that set it

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
            "phases_ms": {k: round(v, 3) for k, v in self.phases_ms.items()},
            **({"param_sources": self.param_sources} if self.param_sources else {}),
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


@contextlib.contextmanager
def _phase(feat: Feature, name: str):
    """Accumulate wall time spent in one phase of a feature (reported in the feature graph)."""
    t = time.perf_counter()
    try:
        yield
    finally:
        feat.phases_ms[name] = feat.phases_ms.get(name, 0.0) + (time.perf_counter() - t) * 1000


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


def _param_sources(params: dict) -> dict:
    """{"radius": "fillet_r", "at[1]": "y"}: settings given straight from a Parameter."""
    from .params import source_of

    out = {}
    for k, v in params.items():
        if source_of(v):
            out[k] = source_of(v)
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                if source_of(x):
                    out[f"{k}[{i}]"] = source_of(x)
    return out


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

    def __init__(self, name: str = "part", *, color: str | Sequence[float] | None = None, reference: bool = False,
                 material=None):
        """``material`` is a built-in name ("PLA", "PETG", "TPU", ...) or a :class:`~cad.Material`;
        it sets mass, the default render colour and the material slot in 3MF exports.
        ``reference=True`` marks a body you design *around* (a servo, a PCB, a bearing):
        it is rendered and measured against, but never exported."""
        from .materials import resolve

        if not isinstance(name, str) or not name:
            raise CadError(INVALID_ARGUMENT, "Part name must be a non-empty string")
        self.name = name
        self.color = color
        self.material = resolve(material)
        self.reference = bool(reference)
        self.print_down: tuple[float, float, float] | None = None  # outward normal of the face that goes on the bed
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
        feat = Feature(fid, ftype, _jsonable(params), param_sources=_param_sources(params))
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
        if self._shape is not None:
            with _phase(feat, "measure"):
                feat.metrics = {**feat.metrics,
                    "volume": round(_occ.volume_fast(self._shape), 6),
                    "solids": len(_occ.solids(self._shape)),
                    "faces": len(_occ.faces(self._shape)),
                }
        feat.duration_ms = (time.perf_counter() - t0) * 1000
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
        if self._shape is not None and _occ.solids(self._shape) and not _occ.solids(new_shape):
            code = {"fillet": FILLET_FAILED, "chamfer": CHAMFER_FAILED, "shell": SHELL_FAILED}.get(feat.type, OPERATION_FAILED)
            raise CadError(code, f"{feat.type} produced no solid body (the result is empty or only surfaces)",
                           feature=feat.id, hint="the size is probably too large: it consumes whole faces of the part")
        with _phase(feat, "validate"):
            valid = _occ.is_valid(new_shape)
        if not valid:
            fixed = _occ.fix_shape(new_shape)
            if not _occ.is_valid(fixed):
                raise CadError(
                    INVALID_SHAPE,
                    "the operation produced an invalid solid",
                    feature=feat.id,
                    hint="check for zero-thickness walls, coincident faces or self-intersecting profiles",
                )
            new_shape, history = fixed, None
        t_refs = time.perf_counter()
        present = {"face": _occ.ShapeSet(_occ.faces(new_shape)), "edge": _occ.ShapeSet(_occ.edges(new_shape))}

        def remap(s, kind):
            if history is not None:
                try:
                    if history.IsDeleted(s):
                        return []
                    mods = [present[kind].get(m) for m in _occ.shape_list(history.Modified(s))]
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
        feat.phases_ms["references"] = feat.phases_ms.get("references", 0.0) + (time.perf_counter() - t_refs) * 1000
        feat.outputs = {n: len(v) for n, v in refs.items() if self._ref_origin.get(n) == feat.id}

    @staticmethod
    def _boolean(op: str, args: list, tools: list):
        """One boolean with list arguments (many tools in a single kernel call)."""
        alg = {"add": BRepAlgoAPI_Fuse, "cut": BRepAlgoAPI_Cut, "intersect": BRepAlgoAPI_Common}[op]()
        la, lt = List_TopoDS_Shape(), List_TopoDS_Shape()
        for a in args:
            la.Append(a)
        for t in tools:
            lt.Append(t)
        alg.SetArguments(la)
        alg.SetTools(lt)
        alg.Build()
        return alg

    def _body_op(self, feat: Feature, tool, tool_refs: dict, op: str) -> None:
        """Combine one tool shape, or a list of tool shapes in a single boolean, with the body."""
        if op not in _OPS:
            raise CadError(INVALID_ARGUMENT, f"op must be one of {_OPS}, got {op!r}", feature=feat.id)
        tools = list(tool) if isinstance(tool, (list, tuple)) else [tool]
        if len(tools) > 1 and op == "intersect":
            raise CadError(INVALID_ARGUMENT, "op='intersect' takes a single position", feature=feat.id)
        if self._shape is None:
            if op != "add":
                raise CadError(NO_BODY, f"cannot '{op}' before the part has a body", feature=feat.id, hint="create the base body first with op='add'")
            if len(tools) == 1:
                self._commit(feat, tools[0], None, tool_refs)
                return
            first, tools = tools[0], tools[1:]
            self._shape = first  # the first instance is the body the others fuse into
        tool = tools[0] if len(tools) == 1 else _occ.compound(tools)
        before_vol = _occ.volume_fast(self._shape)
        before_solids = len(_occ.solids(self._shape))
        with _phase(feat, "boolean"):
            if len(tools) == 1:
                alg = {"add": BRepAlgoAPI_Fuse, "cut": BRepAlgoAPI_Cut, "intersect": BRepAlgoAPI_Common}[op](self._shape, tools[0])
            else:
                alg = self._boolean(op, [self._shape], tools)
        if not alg.IsDone():
            raise CadError(BOOLEAN_FAILED, f"boolean {op} failed", feature=feat.id, hint="avoid tangent or coincident faces; offset the tool slightly")
        if op == "add":
            # merge coplanar/co-cylindrical faces for clean topology, but never at the cost of validity:
            # unifying edges+faces corrupts some curved results (e.g. box fused with a sphere, found by S01)
            with _phase(feat, "simplify"):
                alg.SimplifyResult()
            if not _occ.is_valid(alg.Shape()):
                alg = BRepAlgoAPI_Fuse(self._shape, tools[0]) if len(tools) == 1 else self._boolean("add", [self._shape], tools)
                if not alg.IsDone():
                    raise CadError(BOOLEAN_FAILED, "boolean add failed", feature=feat.id)
        result = alg.Shape()
        if not _occ.solids(result):
            raise CadError(
                NO_BODY if op != "add" else BOOLEAN_FAILED,
                f"{op} left no solid material",
                feature=feat.id,
                hint="the tool fully contains the body (cut) or does not overlap it (intersect)",
            )
        self._commit(feat, result, alg, tool_refs)
        after_vol = _occ.volume_fast(self._shape)
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
        if op != "add" and solids_now > before_solids:
            feat.warnings.append(_split_warning(feat.id, op, before_solids, solids_now))
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
        points = _positions(at)
        size = (width, depth, height)

        def build(feat):
            tools, refs = [], {}
            for p in points:
                lo = [p[i] - {"min": 0, "center": size[i] / 2, "max": size[i]}[al[i]] for i in range(3)]
                tool = BRepPrimAPI_MakeBox(gp_Pnt(*lo), width, depth, height).Shape()
                tools.append(tool)
                _merge_refs(refs, _direction_refs(feat.id, tool))
            self._body_op(feat, tools if len(tools) > 1 else tools[0], refs, op)

        return self._run("box", name, dict(width=width, depth=depth, height=height, at=points if len(points) > 1 else points[0],
                                           align=al, op=op), build)

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
        points = _positions(at)
        shift = {"min": 0.0, "center": height / 2, "max": height}.get(align)
        if shift is None:
            raise CadError(INVALID_ARGUMENT, f"align must be one of {_ALIGN}, got {align!r}")

        def build(feat):
            tools, refs = [], {}
            for p in points:
                base = tuple(a - shift * c for a, c in zip(p, d))
                tool = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*base), gp_Dir(*d)), diameter / 2, height).Shape()
                tools.append(tool)
                _merge_refs(refs, _axial_refs(feat.id, tool, d))
            self._body_op(feat, tools if len(tools) > 1 else tools[0], refs, op)

        return self._run("cylinder", name, dict(diameter=diameter, height=height, at=points if len(points) > 1 else points[0],
                                                axis=d, align=align, op=op), build)

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

    # ================================================================== import
    @classmethod
    def from_file(cls, path: str, name: str | None = None, *, solid=None, reference: bool = False, material=None,
                  color=None, scale: float = 1.0, align=None, at: Sequence[float] | None = None,
                  max_triangles: int | None = None) -> "Part":
        """A part made from a STEP / IGES / BREP / STL file (see :meth:`import_file`).

        ``reference=True`` for a component you design around (a servo, a PCB): it renders
        and takes part in ``cad clearance`` but is never exported.  The part's colour
        defaults to the file's colour.
        """
        p = cls(name or Path(path).stem, reference=reference, material=material, color=color)
        p.import_file(path, solid=solid, scale=scale, align=align, at=at, max_triangles=max_triangles)
        return p

    def import_file(self, path: str, *, solid=None, scale: float = 1.0, align=None, at: Sequence[float] | None = None,
                    op: str = "add", name: str | None = None, max_triangles: int | None = None) -> FeatureRef:
        """Add (or cut / intersect) the solids of a STEP, IGES, BREP or STL file.

        Paths are relative to the project directory.  STEP/IGES units are converted to
        mm; STL/BREP are taken as mm (``scale=25.4`` for inches).  ``solid`` picks bodies
        by name (exact, else substring), index, or a list of either (`cad info <file>`
        lists them).  ``align`` = per-axis "min" | "center" | "max" (e.g.
        ``("center", "center", "min")``) moves the imported bounding box onto the origin;
        ``at`` then offsets it.  As the first feature the bodies are kept exactly as in
        the file (several solids stay separate); later imports are booleans with the body.
        Named faces: ``<id>`` (all), ``<id>.top`` ... ``<id>.<body name>``.
        """
        from . import importer

        if not isinstance(scale, (int, float)) or scale <= 0:
            raise CadError(INVALID_ARGUMENT, f"scale must be positive, got {scale!r}")
        align = _import_align(align)

        def build(feat):
            bodies, info = importer.read(path, max_triangles=max_triangles or importer.MAX_TRIANGLES)
            chosen = importer.select(bodies, solid, path)
            trsf = gp_Trsf()
            if scale != 1:
                trsf.SetScaleFactor(scale)
            shapes = [BRepBuilderAPI_Transform(b.shape, trsf, True).Shape() if scale != 1 else b.shape for b in chosen]
            lo, hi = _occ.bbox(_occ.compound(shapes))
            move = [0.0, 0.0, 0.0]
            for i, a in enumerate(align or (None, None, None)):
                if a is not None:
                    move[i] = -{"min": lo[i], "center": (lo[i] + hi[i]) / 2, "max": hi[i]}[a]
            if at is not None:
                move = [m + v for m, v in zip(move, _occ.vec(at))]
            if any(abs(m) > 0 for m in move):
                t = gp_Trsf()
                t.SetTranslation(gp_Vec(*move))
                shapes = [BRepBuilderAPI_Transform(sh, t, True).Shape() for sh in shapes]
            refs = _direction_refs(feat.id, _occ.compound(shapes))
            for b, sh in zip(chosen, shapes):
                key = f"{feat.id}.{_ref_safe(b.name)}"
                if key not in refs:
                    refs[key] = ("face", _occ.faces(sh))
            if self._shape is None and op == "add":
                self._commit(feat, shapes[0] if len(shapes) == 1 else _occ.compound(shapes), None, refs)
            else:
                self._body_op(feat, shapes, refs, op)
            if self.color is None and chosen[0].color and all(b.color == chosen[0].color for b in chosen):
                self.color = chosen[0].color
            feat.metrics["import"] = {"file": str(path), "format": info["format"], "sha256": info["sha256"][:16],
                                      "bodies": [b.name for b in chosen], "units_in_file": info.get("units_in_file"),
                                      "moved_by": [round(m, 6) for m in move]}
            if info.get("format") == "stl":
                feat.metrics["import"]["triangles"] = info.get("triangles")

        params = {"path": str(path), "solid": solid, "scale": scale, "align": align, "at": at, "op": op}
        return self._run("import", name, params, build)

    # ================================================================== loft / sweep / draft
    def loft(self, sections: Sequence, *, ruled: bool = False, op: str = "add", name: str | None = None) -> FeatureRef:
        """A solid blended through 2D ``sections``, in order.

        Each section is ``(profile, z)`` (the profile on the XY plane at height z), or
        ``(profile, plane)`` with any :class:`Plane` / plane name.  ``ruled=True`` joins
        neighbouring sections with straight (ruled) faces instead of a smooth blend.
        Sections must not cross each other; holes in the profiles are lofted too when every
        section has the same number of them.  Named faces: ``<id>.start``, ``<id>.end``, ``<id>.side``.
        """
        from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
        from OCP.BRepTools import BRepTools

        if len(sections) < 2:
            raise CadError(INVALID_ARGUMENT, "a loft needs at least 2 sections")
        placed = []
        for i, sec in enumerate(sections):
            if not (isinstance(sec, (list, tuple)) and len(sec) == 2 and isinstance(sec[0], Profile)):
                raise CadError(INVALID_ARGUMENT, f"loft section {i} must be (Profile, z) or (Profile, plane)")
            prof, where = sec
            pl = as_plane("XY").offset(float(where)) if isinstance(where, (int, float)) else as_plane(where)
            faces = _occ.faces(prof.placed(pl))
            if len(faces) != 1:
                raise CadError(INVALID_ARGUMENT, f"loft section {i} has {len(faces)} separate regions; each section must be one outline")
            placed.append(faces[0])
        outers = [BRepTools.OuterWire_s(f) for f in placed]
        inners = [[w for w in _occ.wires(f) if not w.IsSame(BRepTools.OuterWire_s(f))] for f in placed]

        def thru(wires):
            ts = BRepOffsetAPI_ThruSections(True, ruled)
            ts.CheckCompatibility(True)
            for w in wires:
                ts.AddWire(w)
            ts.Build()
            if not ts.IsDone():
                return None
            return ts.Shape()

        def build(feat):
            solid = thru(outers)
            if solid is None or not _occ.is_valid(solid) or not _occ.solids(solid):
                raise CadError("LOFT_FAILED", "the loft could not be built into a valid solid", feature=feat.id,
                               hint="sections must not cross or touch each other and should be ordered along the loft; "
                                    "very different shapes (e.g. a star to a circle) may twist: try ruled=True or more sections")
            holes = []
            if any(inners):
                if len({len(x) for x in inners}) != 1:
                    raise CadError("LOFT_FAILED", "every section must have the same number of holes to loft them",
                                   feature=feat.id, details={"holes_per_section": [len(x) for x in inners]})
                for k in range(len(inners[0])):
                    h = thru([x[k] for x in inners])
                    if h is None:
                        raise CadError("LOFT_FAILED", f"could not loft hole {k + 1}", feature=feat.id)
                    holes.append(h)
            if holes:
                from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

                for h in holes:
                    solid = BRepAlgoAPI_Cut(solid, h).Shape()
            if _occ.volume_fast(solid) < 0:
                solid.Reverse()
            refs = _sweep_refs(feat.id, solid, placed[0], placed[-1])
            self._body_op(feat, solid, refs, op)
            feat.metrics["loft"] = {"sections": len(placed), "ruled": ruled, "volume": round(_occ.volume(solid), 4)}

        return self._run("loft", name, {"sections": [{"profile": p.description, "at": w if isinstance(w, (int, float)) else str(w)}
                                                      for p, w in sections], "ruled": ruled, "op": op}, build)

    def sweep(self, profile: Profile, path, *, op: str = "add", twist: float = 0.0, name: str | None = None) -> FeatureRef:
        """Drag ``profile`` along ``path`` (a :class:`cad.paths.Path`: polyline with bend radius,
        spline, arc, helix).

        The profile is drawn in the plane perpendicular to the path at its start, centred on
        the start point: u is world X and v world Y for a path starting along +Z; for a path
        starting horizontally v is world +Z (as on the YZ / XZ planes).  A profile with holes
        (``Profile.circle(10) - Profile.circle(7)``) sweeps a hollow tube.  The bend radius must
        exceed the profile's radius or the solid would cut through itself (SWEEP_FAILED).
        Named faces: ``<id>.start``, ``<id>.end``, ``<id>.side``.
        """
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
        from OCP.BRepTools import BRepTools

        from .paths import Path as SweepPath

        if not isinstance(path, SweepPath):
            raise CadError(INVALID_ARGUMENT, "sweep path must be a cad.paths.Path", hint="from cad import Path; Path.polyline([...], radius=10)")
        start, tangent = path.start()
        up = (0.0, 0.0, 1.0) if abs(tangent[2]) < 0.9 else (0.0, 1.0, 0.0)
        dot = sum(a * b for a, b in zip(up, tangent))
        v = _occ.vec([a - dot * b for a, b in zip(up, tangent)])
        vn = math.sqrt(sum(c * c for c in v))
        v = tuple(c / vn for c in v)
        u = (v[1] * tangent[2] - v[2] * tangent[1], v[2] * tangent[0] - v[0] * tangent[2], v[0] * tangent[1] - v[1] * tangent[0])
        pl = Plane(start, tangent, u)
        face = _occ.faces(profile.placed(pl))
        if len(face) != 1:
            raise CadError(INVALID_ARGUMENT, "the sweep profile must be one outline (optionally with holes)")
        face = face[0]
        prof_r = _max_dist_on_wire(BRepTools.OuterWire_s(face), start)

        def pipe(wire):
            mk = BRepOffsetAPI_MakePipeShell(path.wire)
            mk.SetMode(False)  # corrected Frenet: no flipping on straight segments
            mk.Add(wire, False, False)
            mk.Build()
            if not mk.IsDone():
                return None
            mk.MakeSolid()
            return mk.Shape()

        def build(feat):
            bend = path.min_bend_radius()
            if bend < prof_r * 0.98:  # the kernel may still call this "valid", but it cuts through itself
                raise CadError("SWEEP_FAILED", f"the path bends with radius {bend:.3g} mm, tighter than the profile's "
                               f"{prof_r:.3g} mm reach from the path: the solid would cut through itself", feature=feat.id,
                               hint=f"use a bend radius above {prof_r:.3g} mm (polyline radius=, a wider arc / spline) "
                                    "or a smaller profile", details={"min_bend_radius": round(bend, 4), "profile_radius": round(prof_r, 4)})
            outer = BRepTools.OuterWire_s(face)
            solid = pipe(outer)
            if solid is None or not _occ.is_valid(solid) or not _occ.solids(solid):
                hint = ("the path bends tighter than the profile is wide: increase the bend radius (polyline radius=) "
                        f"above ~{prof_r:.3g} mm or use a smaller profile" if bend < prof_r * 1.02
                        else "check that the profile is perpendicular to the path at its start and the path does not cross itself")
                raise CadError("SWEEP_FAILED", "the sweep could not be built into a valid solid", feature=feat.id, hint=hint,
                               details={"min_bend_radius": round(bend, 4) if bend != math.inf else None, "profile_radius": round(prof_r, 4)})
            if _occ.volume_fast(solid) < 0:
                solid.Reverse()
            for w in _occ.wires(face):
                if w.IsSame(outer):
                    continue
                hole = pipe(w)
                if hole is not None:
                    if _occ.volume_fast(hole) < 0:
                        hole.Reverse()
                    solid = BRepAlgoAPI_Cut(solid, hole).Shape()
            if bend < prof_r * 1.02:
                feat.warnings.append(CadWarning("SWEEP_TIGHT_BEND", f"the path bends with radius {bend:.3g} mm, about the profile's "
                                                f"radius {prof_r:.3g} mm: the inside of the bend is pinched", feat.id))
            refs = _sweep_refs(feat.id, solid, face, None)
            self._body_op(feat, solid, refs, op)
            feat.metrics["sweep"] = {"path": path.description.get("type"), "path_length": round(path.length, 4),
                                     "min_bend_radius": round(bend, 4) if bend != math.inf else None,
                                     "profile_radius": round(prof_r, 4), "volume": round(_occ.volume(solid), 4)}

        return self._run("sweep", name, {"profile": profile.description, "path": path.description, "op": op}, build)

    def draft(self, angle: float, *, faces=None, pull: str | Sequence[float] = "+z", neutral: float | None = None,
              name: str | None = None) -> FeatureRef:
        """Taper walls by ``angle`` degrees so the part releases from a mould (or slides out of a
        print bed / sleeve) when pulled along ``pull``.

        ``faces`` defaults to every flat or curved wall parallel to ``pull``; ``neutral`` is the
        height along ``pull`` where the walls keep their size (default: the bottom of the part),
        so walls lean inward going toward ``pull``.  Typical: 1-3 degrees.  Named faces: ``<id>.faces``.
        """
        from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
        from OCP.gp import gp_Pln

        if not 0 < abs(angle) < 45:
            raise CadError(INVALID_ARGUMENT, "draft angle must be between 0 and 45 degrees")
        d = _axis_dir(pull)

        def build(feat):
            if faces is None:
                cand = [f for f in _occ.faces(self.shape) if _is_wall(f, d)]
            else:
                if not isinstance(faces, FaceSelection):
                    raise CadError(INVALID_ARGUMENT, "draft(faces=) needs a face selection")
                self._check_current(faces, feat.id)
                self._record_selection(feat, "faces", faces)
                cand = faces.shapes
            if not cand:
                raise CadError(EMPTY_SELECTION, f"no walls parallel to {pull} to draft", feature=feat.id)
            lo, hi = _occ.bbox(self.shape)
            corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
            h0 = min(sum(a * b for a, b in zip(c, d)) for c in corners) if neutral is None else neutral
            origin = tuple(c * h0 for c in d)
            mk = BRepOffsetAPI_DraftAngle(self.shape)
            bad = []
            for f in cand:
                mk.Add(f, gp_Dir(*d), math.radians(angle), gp_Pln(gp_Pnt(*origin), gp_Dir(*d)))
                if not mk.AddDone():
                    bad.append(f)
                    mk.Remove(f)
            mk.Build()
            if not mk.IsDone() or not _occ.is_valid(mk.Shape()):
                raise CadError("DRAFT_FAILED", "the draft could not be applied", feature=feat.id,
                               hint="draft walls before filleting their edges, and draft fewer faces at a time")
            gen = []
            for f in cand:
                if f in bad:
                    continue
                try:
                    gen.extend(_occ.shape_list(mk.Modified(f)))
                except Standard_Failure:
                    pass
            refs = {f"{feat.id}.faces": ("face", gen)} if gen else {}
            self._commit(feat, mk.Shape(), mk, refs)
            feat.metrics["draft"] = {"angle": angle, "faces": len(cand) - len(bad), "pull": _jsonable(d), "neutral": round(h0, 6)}
            if bad:
                feat.warnings.append(CadWarning("DRAFT_SKIPPED", f"{len(bad)} face(s) could not be drafted and were left as they are",
                                                feat.id, {"hint": "usually faces next to fillets; draft first, then fillet"}))

        return self._run("draft", name, {"angle": angle, "pull": pull, "neutral": neutral, "faces": faces}, build)

    # ================================================================== threads
    def thread(self, size: str, *, length: float, at: Sequence[float] = (0, 0, 0), direction: str | Sequence[float] = "+z",
               pitch: float | None = None, name: str | None = None) -> FeatureRef:
        """A threaded rod (external ISO metric thread) from ``at`` along ``direction``.

        ``size`` "M8" (coarse pitch), "M8x1" or "M40x3"; ``length`` mm.  Fused into the part
        (or the first body).  Prints best with the axis vertical (Z); below ~M6 printed
        threads are weak, prefer a screw.  Named faces: ``<id>.thread``, ``<id>.end``.
        """
        from . import threads

        d, p = threads.parse(size, pitch)
        _pos(length=length)

        def build(feat):
            rod = threads.bolt_tools(d, p, length)
            if rod is None or not _occ.is_valid(rod):
                raise CadError(OPERATION_FAILED, f"could not build a valid M{d:g}x{p:g} thread", feature=feat.id)
            rod = BRepBuilderAPI_Transform(rod, _frame_trsf(_occ.vec(at), _axis_dir(direction)), True).Shape()
            if not _occ.is_valid(rod):
                raise CadError(OPERATION_FAILED, f"could not build a valid M{d:g}x{p:g} thread", feature=feat.id)
            refs = {f"{feat.id}.thread": ("face", [f for f in _occ.faces(rod) if _occ.surface_type(f) != "plane"]),
                    f"{feat.id}.end": ("face", [f for f in _occ.faces(rod) if _occ.surface_type(f) == "plane"])}
            self._body_op(feat, rod, refs, "add")
            feat.metrics["thread"] = {**threads.external_profile(d, p), "length": length, "turns": round(length / p, 2)}
            self._thread_warnings(feat, d, p, _axis_dir(direction))

        return self._run("thread", name, {"size": size, "pitch": p, "length": length, "at": at, "direction": direction}, build)

    def threaded_hole(self, size: str, at: Sequence[float], *, depth: float | None = None, direction: str | Sequence[float] = "-z",
                      clearance: float = 0.3, pitch: float | None = None, name: str | None = None) -> FeatureRef:
        """A hole with an internal ISO metric thread (placement rules as :meth:`hole`).

        ``clearance`` (mm, radial, default 0.3) is how far the thread is moved outward so a bolt
        of the same size turns in it; the flanks get about half of it as play.  0.3 suits a
        printed bolt, 0.15-0.2 a metal one.  ``depth=None``
        threads through.  Below ~M6 use ``screw_hole(kind="insert")`` instead.
        Named faces: ``<id>.thread``.
        """
        from . import threads

        d, p = threads.parse(size, pitch)
        if not 0 <= clearance <= 1:
            raise CadError(INVALID_ARGUMENT, "clearance must be between 0 and 1 mm")
        dvec = _axis_dir(direction)

        def build(feat):
            lo, hi = _occ.bbox(self.shape)
            start = self._hole_start(at, dvec, lo, hi, feat.id)
            ahead = _extent_along(lo, hi, start, dvec)
            if ahead <= 1e-6:
                raise CadError("HOLE_MISSED", f"the threaded hole at {_jsonable(at)} points away from the part", feature=feat.id)
            back = 1.0 if len(at) == 2 else 0.01
            length = depth if depth is not None else ahead + 1.0
            tool, info = threads.hole_tools(d, p, -back, length, clearance)
            if tool is None:
                raise CadError(OPERATION_FAILED, f"could not build a valid M{d:g}x{p:g} thread", feature=feat.id)
            tool = BRepBuilderAPI_Transform(tool, _frame_trsf(start, dvec), True).Shape()
            if not _occ.is_valid(tool):
                raise CadError(OPERATION_FAILED, f"could not build a valid M{d:g}x{p:g} thread", feature=feat.id,
                               hint="try a different clearance or pitch")
            refs = {f"{feat.id}.thread": ("face", [f for f in _occ.faces(tool) if _occ.surface_type(f) != "plane"])}
            if depth is not None:
                refs[f"{feat.id}.floor"] = ("face", [f for f in _occ.faces(tool) if _occ.surface_type(f) == "plane"
                                                      and sum(a * b for a, b in zip(_occ.face_normal(f), dvec)) > 0.5])
            self._body_op(feat, tool, refs, "cut")
            feat.metrics["thread"] = {**threads.external_profile(d, p), **info, "clearance": clearance,
                                      "depth": round(length, 4), "start": _jsonable(start)}
            self._thread_warnings(feat, d, p, dvec)

        return self._run("threaded_hole", name, {"size": size, "pitch": p, "at": at, "depth": depth, "direction": direction,
                                                 "clearance": clearance}, build)

    def _thread_warnings(self, feat, d, p, axis) -> None:
        if d < 6:
            feat.warnings.append(CadWarning("THREAD_TOO_FINE", f"printed M{d:g} threads are weak and often fuse shut on FDM",
                                            feat.id, {"hint": "use a heat-set insert (screw_hole(kind='insert')) or a "
                                                              "self-tapping pilot hole (kind='tap') instead"}))
        if abs(axis[2]) < 0.9:
            feat.warnings.append(CadWarning("THREAD_ORIENTATION", "the thread axis is not vertical: the flanks facing down "
                                            "print as overhangs and the thread comes out rough or oval", feat.id,
                                            {"hint": "orient the part so the thread axis is along Z"}))

    # ================================================================== snap fits
    def snap_hook(self, *, on, length: float, thickness: float, width: float, catch: float = 1.0,
                  hook: str | Sequence[float] | None = None, at: Sequence[float] | None = None,
                  lead_in_angle: float = 30.0, retention_angle: float = 90.0, name: str | None = None) -> FeatureRef:
        """A cantilever snap-fit hook standing on a flat face.

        The beam grows out of ``on`` (one planar face) along its normal for ``length`` mm
        (root to the catch), ``thickness`` mm thick in the bending direction and ``width`` mm
        wide; at its tip a hook sticks out ``catch`` mm toward ``hook`` (a direction in the
        face, e.g. "+x"; default the face's "up").  ``at`` = (u, v) from the face centre or a
        3D point: the beam's outer face (the hook side) passes through it.
        ``lead_in_angle`` (from the beam axis; 25-35 slides on easily) and
        ``retention_angle`` (90 = permanent, ~45 = can be pulled apart) shape the hook.

        Metrics: peak strain vs the material's allowable strain, deflection force, and the
        catch face position; warnings SNAP_STRAIN_HIGH and SNAP_LAYER_ORIENTATION (a beam
        printed upright breaks along its layers).  Named faces: ``<id>.catch`` (the face that
        holds), ``<id>.lead_in``, ``<id>.beam``.  The mating part needs a ledge or window the
        catch face hooks behind: put it at the catch position, ``catch`` mm deep.
        """
        from .snapfit import analyse

        _pos(length=length, thickness=thickness, width=width, catch=catch)
        if not 5 <= lead_in_angle <= 60:
            raise CadError(INVALID_ARGUMENT, "lead_in_angle must be 5-60 degrees (from the beam axis)")
        if not 20 <= retention_angle <= 90:
            raise CadError(INVALID_ARGUMENT, "retention_angle must be 20-90 degrees (90 = square, permanent)")

        def build(feat):
            if isinstance(on, FaceSelection):
                self._check_current(on, feat.id)
                self._record_selection(feat, "on", on)
            pl = Plane.from_face(on, at=at if at is not None and len(at) == 2 else None)
            n = pl.normal
            if hook is None:
                h = pl.v
            else:
                hv = _axis_dir(hook)
                dot = sum(a * b for a, b in zip(hv, n))
                h = tuple(a - dot * b for a, b in zip(hv, n))
                hn = math.sqrt(sum(c * c for c in h))
                if hn < 1e-6:
                    raise CadError(INVALID_ARGUMENT, "hook direction is along the face normal; give a direction within the face",
                                   feature=feat.id)
                h = tuple(c / hn for c in h)
            origin = pl.origin
            if at is not None and len(at) == 3:
                p3 = _occ.vec(at)
                dist = sum((a - b) * c for a, b, c in zip(p3, origin, n))
                origin = tuple(a - dist * c for a, c in zip(p3, n))
            w = (n[1] * h[2] - n[2] * h[1], n[2] * h[0] - n[0] * h[2], n[0] * h[1] - n[1] * h[0])
            eps = 0.01  # sink the root into the face so the beam fuses
            z_r = length
            lead = catch / math.tan(math.radians(lead_in_angle))
            land = min(0.4, 0.3 * catch + 0.1)
            ret = 0.0 if retention_angle >= 90 else catch / math.tan(math.radians(retention_angle))
            pts2 = [(-thickness, -eps), (0, -eps), (0, z_r - ret), (catch, z_r), (catch, z_r + land), (0, z_r + land + lead),
                    (-thickness, z_r + land + lead)]
            # profile plane spanned by h (x) and n (z), extruded along w by width, centred
            prof_pl = Plane(tuple(o - w_ * width / 2 for o, w_ in zip(origin, w)), w, h)
            # Plane(origin, normal, u): u = h, v = normal x u ... check v aligns with n
            vv = prof_pl.v
            sign = 1.0 if sum(a * b for a, b in zip(vv, n)) > 0 else -1.0
            face = Profile.polygon([(x, sign * z) for x, z in pts2]).placed(prof_pl)
            tool = BRepPrimAPI_MakePrism(face, gp_Vec(*[c * width for c in w])).Shape()
            refs = {}
            catch_faces, lead_faces, beam_faces = [], [], []
            for f in _occ.faces(tool):
                if _occ.surface_type(f) != "plane":
                    continue
                fn = _occ.face_normal(f)
                dn, dh = sum(a * b for a, b in zip(fn, n)), sum(a * b for a, b in zip(fn, h))
                c = _occ.face_centroid(f)
                height = sum((a - b) * nn for a, b, nn in zip(c, origin, n))
                if dn < -1e-6 and dh > -1e-6 and height > z_r * 0.5 and height <= z_r + 1e-6:
                    catch_faces.append(f)
                elif dn > 1e-6 and dh > 1e-6:
                    lead_faces.append(f)
                elif abs(dn) < 1e-6:
                    beam_faces.append(f)
            for role, fs in (("catch", catch_faces), ("lead_in", lead_faces), ("beam", beam_faces)):
                if fs:
                    refs[f"{feat.id}.{role}"] = ("face", fs)
            self._body_op(feat, tool, refs, "add")
            upright = abs(n[2]) > 0.7
            a = analyse(length, thickness, width, catch, self.material, upright=upright)
            catch_pt = tuple(o + z_r * nn for o, nn in zip(origin, n))
            a.update(catch_face_at=_jsonable(catch_pt), hook_direction=_jsonable(h), beam_axis=_jsonable(n),
                     total_height=round(z_r + land + lead, 4))
            feat.metrics["snap"] = a
            if not a["ok"]:
                feat.warnings.append(CadWarning(
                    "SNAP_STRAIN_HIGH", f"the hook bends to {a['strain_pct']}% strain; {a['material']} allows ~{a['allowable_strain_pct']}% "
                    + ("(halved: printed upright) " if upright else "")
                    + "for repeated snapping, so it will crack or take a set", feat.id,
                    {"hint": f"lengthen the beam to >= {a['min_length_for_material']} mm, make it thinner, or reduce catch",
                     **a}))
            if upright and a["ok"]:
                feat.warnings.append(CadWarning(
                    "SNAP_LAYER_ORIENTATION", "the beam stands upright (along Z): printed this way it bends across its "
                    f"layer lines, so strain was checked against half the usual limit ({a['strain_pct']}% of "
                    f"{a['allowable_strain_pct']}%: ok)", feat.id,
                    {"hint": "fine if the part must print this way; laying the beam flat (axis along X or Y) is stronger"}))

        params = {"on": on, "length": length, "thickness": thickness, "width": width, "catch": catch, "hook": hook, "at": at,
                  "lead_in_angle": lead_in_angle, "retention_angle": retention_angle}
        return self._run("snap_hook", name, params, build)

    # ================================================================== text
    def emboss(self, text: str, *, on, size: float, height: float = 0.6, at: Sequence[float] | None = None,
               up: Sequence[float] | None = None, angle: float = 0.0, font: str | None = None, bold: bool = False,
               italic: bool = False, align=("center", "center"), name: str | None = None) -> FeatureRef:
        """Raised text on a flat face.

        ``on`` is a selection with exactly one planar face (or a :class:`Plane`); the text
        reads normally when viewed from outside that face, upright on vertical faces.
        ``size`` is the capital letter height (mm), ``height`` how far it stands proud.
        ``at`` moves the text: (u, v) from the face centre, or a 3D point.  Named faces:
        ``<id>.end`` (letter tops) and ``<id>.side``.
        """
        return self._text_feature("emboss", name, text, on, size, height, at, up, angle, font, bold, italic, align)

    def engrave(self, text: str, *, on, size: float, depth: float = 0.6, at: Sequence[float] | None = None,
                up: Sequence[float] | None = None, angle: float = 0.0, font: str | None = None, bold: bool = False,
                italic: bool = False, align=("center", "center"), name: str | None = None) -> FeatureRef:
        """Text cut into a flat face, ``depth`` mm deep (same placement rules as :meth:`emboss`).
        Named faces: ``<id>.floor`` (letter bottoms) and ``<id>.side``."""
        return self._text_feature("engrave", name, text, on, size, depth, at, up, angle, font, bold, italic, align)

    def _text_feature(self, ftype, name, text, on, size, amount, at, up, angle, font, bold, italic, align) -> FeatureRef:
        from .text import stroke_width

        _pos(**{"height" if ftype == "emboss" else "depth": amount})
        prof = Profile.text(text, size, font=font, bold=bold, italic=italic, align=align, angle=angle)

        def build(feat):
            if isinstance(on, Plane):
                pl = on if at is None else Plane(on.to_world((*at, 0)) if len(at) == 2 else _occ.vec(at), on.normal, on.u)
                face = None
            elif isinstance(on, FaceSelection):
                self._check_current(on, feat.id)
                self._record_selection(feat, "on", on)
                pl = Plane.from_face(on, at=at, up=up)
                face = max(on.shapes, key=_occ.area)
            else:
                raise CadError(INVALID_ARGUMENT, f"{ftype}(on=...) needs a face selection or a Plane", feature=feat.id,
                               hint="e.g. on=part.faces('base.top') or on=part.faces().facing('+y').max('y')")
            eps = 0.01  # overlap the face (emboss) / start above it (engrave) so the boolean is clean
            n = pl.normal
            if ftype == "emboss":
                base = prof.placed(pl.offset(-eps))
                vec = [c * (amount + eps) for c in n]
                op, d = "add", n
            else:
                base = prof.placed(pl.offset(eps))
                vec = [-c * (amount + eps) for c in n]
                op, d = "cut", tuple(-c for c in n)
            prism = BRepPrimAPI_MakePrism(base, gp_Vec(*vec))
            prism.Build()
            if not prism.IsDone():
                raise CadError(OPERATION_FAILED, f"{ftype} failed to build the letter solids", feature=feat.id)
            tool = prism.Shape()
            refs = _axial_refs(feat.id, tool, d)
            if ftype == "engrave" and f"{feat.id}.end" in refs:
                refs[f"{feat.id}.floor"] = refs.pop(f"{feat.id}.end")
            if face is not None:
                outside = self._points_off_face(face, prof.placed(pl))
                if outside:
                    feat.warnings.append(CadWarning("TEXT_OFF_FACE", f"the text extends past the edge of the face ({outside} of 4 corners)",
                                                    feat.id, {"text_size_mm": [prof.description["width"], prof.description["height"]]}))
            stroke = stroke_width(size, font, bold, italic)
            if stroke < 0.4:
                feat.warnings.append(CadWarning("TEXT_STROKES_THIN", f"strokes are about {stroke:.2f} mm wide; under ~0.4 mm is too fine "
                                                "for FDM printing", feat.id,
                                                {"stroke_mm": round(stroke, 3), "hint": "increase size, use bold=True or a heavier font"}))
            self._body_op(feat, tool, refs, op)
            feat.metrics["text"] = {**{k: prof.description[k] for k in ("font", "width", "height", "glyph_faces")},
                                    "stroke_mm": round(stroke, 3)}

        params = {"text": text, "size": size, ("height" if ftype == "emboss" else "depth"): amount, "font": prof.description["font"],
                  "bold": bold, "italic": italic, "align": align, "angle": angle, "at": at, "on": on}
        return self._run(ftype, name, params, build)

    @staticmethod
    def _points_off_face(face, placed_text) -> int:
        """How many corners of the text's bounding rectangle fall outside ``face``."""
        from OCP.BRepClass import BRepClass_FaceClassifier
        from OCP.gp import gp_Pnt
        from OCP.TopAbs import TopAbs_OUT

        lo, hi = _occ.bbox(placed_text)
        # corners of the (planar) text box; at least 4 distinct points on the face plane
        corners = {(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])}
        out = 0
        checked = 0
        for c in corners:
            st = BRepClass_FaceClassifier(face, gp_Pnt(*c), 1e-3).State()
            checked += 1
            out += st == TopAbs_OUT
        return min(4, round(out * 4 / max(checked, 1)))

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

    def screw_hole(self, size: str, at, *, kind: str = "clearance", depth: float | None = None,
                   direction: str | Sequence[float] = "-z", name: str | None = None) -> FeatureRef:
        """A hole sized for a metric screw (M2 .. M8), from the built-in fastener table.

        ``kind``:
          - ``"clearance"``  the screw passes through (ISO 273 medium fit)
          - ``"counterbore"`` clearance hole with a recess so a socket head sits below the surface
          - ``"countersunk"`` clearance hole with a 90-degree countersink for a flat head, flush
          - ``"tap"``        undersized pilot hole the screw cuts its own thread into (plastic)
          - ``"insert"``     pocket for a heat-set threaded insert (blind: insert length + 0.5 mm,
                             with a lead-in chamfer); needs >= 1.5 mm of wall around it
          - ``"nut"``        clearance hole with a hex pocket for a nut at the far side, where the
                             drill line leaves the material
        ``at`` is one position or a list (same rules as :meth:`hole`).  The feature's metrics give
        the dimensions used, the material thickness along each hole and, for nuts and
        counterbores, a standard screw length that fits.  `cad docs fasteners` lists the table.
        """
        from .fasteners import ALLOWANCE, KINDS, lookup, screw_length

        f = lookup(size)
        if kind not in KINDS:
            raise CadError(INVALID_ARGUMENT, f"unknown screw hole kind {kind!r}", hint=f"use one of {', '.join(KINDS)}")
        positions = [at] if isinstance(at, (list, tuple)) and at and isinstance(at[0], (int, float)) else list(at)
        diameter, cb, cs, nut = f.clearance, None, None, None
        if kind == "counterbore":
            extra_d = 0.6 if f.d < 3 else ALLOWANCE["counterbore_d"]
            cb = (round(f.head_d + extra_d, 3), round(f.head_h + ALLOWANCE["counterbore_h"], 3))
        elif kind == "countersunk":
            cs = (round(f.csk_head_d + ALLOWANCE["countersink_d"], 3), 90.0)
        elif kind == "tap":
            diameter = f.tap
        elif kind == "insert":
            diameter = f.insert_d
            depth = depth if depth is not None else round(f.insert_len + ALLOWANCE["insert_extra_depth"], 3)
            cs = (round(f.insert_d + ALLOWANCE["insert_lead_in"], 3), 90.0)
        elif kind == "nut":
            if depth is not None:
                raise CadError(INVALID_ARGUMENT, "a nut trap goes where the hole leaves the material: leave depth=None")
            nut = (round(f.nut_af + ALLOWANCE["nut_af"], 3), round(f.nut_h + ALLOWANCE["nut_h"], 3))

        def report(feat, starts, exits):
            thick = [round(math.dist(s0, e0), 4) if e0 is not None else None for s0, e0 in zip(starts, exits)]
            info = {"size": f.size, "kind": kind, "hole_diameter": diameter, "depth": depth, "material_thickness": thick}
            if cb:
                info["counterbore"] = {"diameter": cb[0], "depth": cb[1]}
            if cs:
                info["countersink" if kind != "insert" else "lead_in"] = {"diameter": cs[0], "angle": 90}
            if nut:
                info["nut_pocket"] = {"across_flats": nut[0], "depth": nut[1]}
            if kind == "insert":
                info["insert"] = {"hole": f.insert_d, "length": f.insert_len,
                                  "screw_engagement_max": f.insert_len}
            t0 = next((t for t in thick if t), None)
            if t0 and kind in ("nut", "counterbore", "countersunk", "clearance") and depth is None:
                grip = t0 - (cb[1] if cb else 0.0)
                if kind == "nut":
                    L = screw_length(grip - 0.5 * f.nut_h)  # at least half the nut engaged
                    info["screw_length"] = L
                    info["screw_protrudes_mm"] = round(L - grip, 2) if L else None
                else:
                    info["material_grip"] = round(grip, 3)
            recess = cb[1] if cb else ((cs[0] - diameter) / 2 if cs and kind == "countersunk" else 0.0)
            if recess and t0 is not None and t0 - recess < 0.8:
                feat.warnings.append(CadWarning(
                    "RECESS_TOO_DEEP", f"the {kind} is {recess:.2f} mm deep in {t0} mm of material, leaving "
                    f"{max(t0 - recess, 0):.2f} mm: a knife edge that breaks or will not print", feat.id,
                    {"hint": f"make the material at least {recess + 1.2:.1f} mm thick here, or use kind='clearance' "
                             "with a pan-head screw"}))
            if kind == "insert" and t0 is not None and depth is not None and t0 < depth + 1.0:
                feat.warnings.append(CadWarning("INSERT_TOO_DEEP", f"the {f.size} insert pocket ({depth} mm) is too deep for the "
                                                f"material ({t0} mm): it breaks through or leaves under 1 mm of floor", feat.id,
                                                {"hint": "use a thicker boss or a shorter insert"}))
            feat.metrics["fastener"] = info

        return self._holes("screw_hole", name, diameter, positions, depth, direction, cb, cs, {"size": f.size, "kind": kind},
                           nut=nut, on_built=report)

    def _holes(self, ftype, name, diameter, positions, depth, direction, counterbore, countersink, extra,
               nut: tuple[float, float] | None = None, on_built=None) -> FeatureRef:
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
            t_tools = time.perf_counter()
            tools, refs_wall, refs_floor, refs_cb, refs_cs, refs_nut, exits = [], [], [], [], [], [], []
            for pos, start in zip(positions, starts):
                ahead = _extent_along(lo, hi, start, d)
                if ahead <= 1e-6:
                    opposite = "".join(("-" if c > 0 else "+") + "xyz"[i] for i, c in enumerate(d) if abs(abs(c) - 1) < 1e-9) or "the opposite direction"
                    raise CadError(
                        "HOLE_MISSED",
                        f"the hole at {_jsonable(pos)} drills along {_jsonable(d)}, but the whole part lies behind its start point",
                        feature=feat.id,
                        hint=f"drill toward the part (direction={opposite!r}) or move the start point to the other side",
                        details={"start": _jsonable(start), "direction": _jsonable(d), "part_bbox": {"min": _jsonable(lo), "max": _jsonable(hi)}},
                    )
                # an explicit 3D start is honoured exactly; a start found on the surface backs off to cut cleanly
                back_off = 0.01 if len(pos) == 3 else margin
                length = (depth if depth is not None else ahead + margin)
                back = tuple(s - back_off * c for s, c in zip(start, d))
                cyl = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*back), gp_Dir(*d)), diameter / 2, length + back_off).Shape()
                pieces = [cyl]
                walls = [f for f in _occ.faces(cyl) if _occ.surface_type(f) == "cylinder"]
                floors = [f for f in _occ.faces(cyl) if _occ.surface_type(f) == "plane"
                          and sum(a * b for a, b in zip(_occ.face_normal(f), d)) > 0.5] if depth is not None else []
                cb_faces, cs_faces = [], []
                if counterbore is not None:
                    cbd, cbh = counterbore
                    cb = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*back), gp_Dir(*d)), cbd / 2, cbh + back_off).Shape()
                    cb_faces = _occ.faces(cb)
                    pieces.append(cb)
                if countersink is not None:
                    csd, ang = countersink
                    h = (csd - diameter) / 2 / math.tan(math.radians(ang / 2))
                    cone = BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(*start), gp_Dir(*d)), csd / 2, diameter / 2, h).Shape()
                    cap = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*back), gp_Dir(*d)), csd / 2, back_off).Shape()
                    cs_faces = [f for f in _occ.faces(cone) if _occ.surface_type(f) == "cone"]
                    pieces += [cone, cap]
                # where the drill line leaves the material (for nut traps and screw lengths)
                far = tuple(st + (ahead + margin) * c for st, c in zip(start, d))
                t_back = _occ.first_hit(body, far, tuple(-c for c in d))
                exit_pt = tuple(f - t_back * c for f, c in zip(far, d)) if t_back is not None else None
                exits.append(exit_pt)
                nut_faces = []
                if nut is not None and exit_pt is not None:
                    af, nh = nut
                    up = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
                    u = _occ.vec([a - sum(x * y for x, y in zip(up, d)) * b for a, b in zip(up, d)])
                    outside = tuple(e + back_off * c for e, c in zip(exit_pt, d))
                    hexf = Profile.regular_polygon(6, across_flats=af).placed(Plane(outside, tuple(-c for c in d), u))
                    hexp = BRepPrimAPI_MakePrism(hexf, gp_Vec(*[-c * (nh + back_off) for c in d])).Shape()
                    nut_faces = _occ.faces(hexp)
                    pieces.append(hexp)
                tools.append(pieces)
                refs_nut.append(nut_faces)
                refs_wall.append(walls)
                refs_floor.append(floors)
                refs_cb.append(cb_faces)
                refs_cs.append(cs_faces)
            flat_tools = [p for ps in tools for p in ps]
            feat.phases_ms["tools"] = (time.perf_counter() - t_tools) * 1000
            if depth is None:  # a through hole that also runs through other, separate material behind
                several = []
                for pos, start in zip(positions, starts):
                    spans = _occ.material_spans(body, start, d)
                    if len(spans) > 1:
                        several.append({"position": _jsonable(pos), "material_spans_mm": [[round(a, 3), round(b, 3)] for a, b in spans]})
                if several:
                    feat.warnings.append(CadWarning(
                        "HOLE_THROUGH_SEVERAL", f"{len(several)} through hole(s) pass through {len(several[0]['material_spans_mm'])} "
                        "separate pieces of material along their line (e.g. a plate and something behind it)", feat.id,
                        {"holes": several[:6], "hint": "a 2D position starts where the line first meets material, which may not "
                                                       "be the piece you meant: give a 3D start point on the face to drill and "
                                                       "depth= that piece's thickness (spans along the line, from the start, are "
                                                       "in material_spans_mm); ignore if drilling through all of them is intended"}))
            alg = BRepAlgoAPI_Cut()
            args, tl = List_TopoDS_Shape(), List_TopoDS_Shape()
            args.Append(body)
            for t in flat_tools:
                tl.Append(t)
            alg.SetArguments(args)
            alg.SetTools(tl)
            with _phase(feat, "boolean"):
                alg.Build()
            if not alg.IsDone():
                raise CadError(BOOLEAN_FAILED, "hole cut failed", feature=feat.id,
                               hint="a hole tangent to or ending exactly on another face can defeat the kernel: "
                                    "shift the start point or depth by a small amount", details={"starts": _jsonable(starts)})
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
            if nut is not None:
                refs[f"{fid}.nut"] = ("face", [f for w in refs_nut for f in w])
            before = _occ.volume_fast(body)
            before_solids = len(_occ.solids(body))
            self._commit(feat, alg.Shape(), alg, refs)
            if len(_occ.solids(self._shape)) > before_solids:
                feat.warnings.append(_split_warning(fid, "hole", before_solids, len(_occ.solids(self._shape))))
            removed = before - _occ.volume_fast(self._shape)
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
            if on_built is not None:
                on_built(feat, starts, exits)

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

    def bottom_chamfer(self, size: float = 0.5, *, holes: bool = True, name: str | None = None) -> FeatureRef:
        """Chamfer the edges of the faces that sit on the print bed, against "elephant's foot"
        (the squashed first layers bulge outward by ~0.2-0.5 mm).

        The bed face is the lowest flat face, or the face given to :meth:`print_on` if that was
        called first.  Chamfers the outer outline; with ``holes=True`` also the edges of holes
        and cut-outs in those faces (they shrink for the same reason).  0.4-0.6 mm is typical.
        """
        from OCP.BRepTools import BRepTools

        _pos(distance=size)
        down = _occ.vec(self.print_down) if self.print_down else (0.0, 0.0, -1.0)

        def extent(f):  # how far the face lies along `down`
            lo_f, hi_f = _occ.bbox(f)
            corners = [(x, y, z) for x in (lo_f[0], hi_f[0]) for y in (lo_f[1], hi_f[1]) for z in (lo_f[2], hi_f[2])]
            return max(sum(a * b for a, b in zip(c, down)) for c in corners)

        flats = [f for f in _occ.faces(self.shape) if _occ.surface_type(f) == "plane"
                 and sum(a * b for a, b in zip(_occ.face_normal(f), down)) > 1 - 1e-6]
        far = max((extent(f) for f in flats), default=None)
        lowest = max(sum(a * b for a, b in zip(c, down)) for c in (self.bbox.min, self.bbox.max))  # exact for axis directions
        bed = [f for f in flats if abs(extent(f) - far) < 1e-6] if flats else []
        if not bed or far < lowest - 1e-6:  # no flat face, or something sticks out below it
            raise CadError(EMPTY_SELECTION, "the part has no flat face on the bed (at its lowest Z)",
                           hint="orient the part for printing so a flat face is at the bottom, or call print_on(face) first")
        efmap = _occ.edge_face_map(self.shape)
        chosen, seen = [], _occ.ShapeSet([])
        for f in bed:
            wires = [BRepTools.OuterWire_s(f)] if not holes else _occ.wires(f)
            for w in wires:
                for e in _occ.edges(w):
                    if e in seen:
                        continue
                    seen.add(e)
                    adj = _occ.faces_of_edge(efmap, e)
                    other = [g for g in adj if not g.IsSame(f)]
                    if other and _occ.edge_convexity(e, f, other[0]) < -1e-6:  # convex
                        chosen.append(e)
        skipped = []
        ok, _ = self._dressup_result_ok(self._make_dressup("chamfer", chosen, size)) if chosen else (False, "")
        if chosen and not ok:  # leave out edges that cannot take the chamfer (e.g. next to a countersink)
            good = []
            for e in chosen:
                (good if self._dressup_result_ok(self._make_dressup("chamfer", [e], size))[0] else skipped).append(e)
            chosen = good
        sel = EdgeSelection(self, chosen, "bed face edges" + (f" (print_on {_jsonable(down)})" if self.print_down else f" (z={-far:g})"))
        ref = self._dressup("bottom_chamfer", name, sel, size)
        if skipped:
            ref.feature.warnings.append(CadWarning(
                "CHAMFER_SKIPPED", f"{len(skipped)} bottom edge(s) cannot take a {size} mm chamfer and were left sharp",
                ref.feature.id, {"edges": [sel._info(e) for e in skipped][:6],
                                 "hint": "usually a hole whose countersink or counterbore almost reaches the bed; "
                                         "a smaller size may fit"}))
        return ref

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
            with _phase(feat, "kernel"):
                ok, why = self._dressup_result_ok(mk)
            if not ok:
                bad, tangent = [], []
                efmap = _occ.edge_face_map(self.shape)
                for e in edges.shapes:
                    good, _ = self._dressup_result_ok(self._make_dressup(ftype, [e], size))
                    if not good:
                        info = edges._info(e)
                        fs = _occ.faces_of_edge(efmap, e)
                        if len(fs) == 2:
                            turn = math.degrees(math.asin(min(1.0, abs(_occ.edge_convexity(e, fs[0], fs[1])))))
                            info["turn_deg"] = round(turn, 2)
                            if turn < 15:
                                tangent.append(info)
                        bad.append(info)
                max_hint = self._dressup_limit(edges.shapes)
                if tangent:
                    worst = min(t["turn_deg"] for t in tangent)
                    hint = (f"{len(tangent)} failing edge(s) are nearly tangent: the faces there turn by only {worst:g} degrees, so "
                            f"there is almost no corner to round and the kernel cannot {ftype} it at any size. Leave them out "
                            f"(edges().concave(min_angle=15)), or draw the outline so it blends smoothly in the first place "
                            "(e.g. Profile.tapered_slot for a link between two round ends)")
                elif bad:
                    lim, names = self._dressup_limit_detail([e for e in edges.shapes if any(
                        edges._info(e)["midpoint"] == b["midpoint"] for b in bad)] or edges.shapes)
                    where = f" ({', '.join(names[:2])})" if names else ""
                    hint = (f"try a {key} below ~{lim:.3g} mm: a face next to the failing edges{where} is only that narrow, "
                            "and a round cannot be wider than the faces it blends. A narrow strip like that usually means "
                            "two bodies barely overlap (a beam slightly wider than the boss it meets): make them line up, "
                            "or build the outline in one piece (e.g. Profile.tapered_slot)")
                else:
                    hint = ("the edges interfere with each other or with earlier fillets: apply them in separate "
                            f"{ftype}() calls, change the order, or narrow the selection")
                raise CadError(
                    FILLET_FAILED if ftype == "fillet" else CHAMFER_FAILED,
                    f"{ftype} of {len(edges)} edge(s) with {key} {size} failed ({why})"
                    + (f"; {len(bad)} edge(s) fail even individually" if bad else "; each edge succeeds alone but not together"),
                    feature=feat.id,
                    hint=hint,
                    details={"failing_edges": bad[:10]},
                )
            refs = {}
            gen = []
            for e in edges.shapes:
                try:
                    gen.extend(_occ.shape_list(mk.Generated(e)))
                except Standard_Failure:
                    pass
            if gen:
                refs[f"{feat.id}.faces"] = ("face", gen)
            self._commit(feat, mk.Shape(), mk, refs, new_faces_role=None if gen else "faces")

        return self._run(ftype, name, {key: size, "edges": edges}, build)

    def _dressup_result_ok(self, mk) -> tuple[bool, str]:
        """Build a fillet/chamfer and check it yields a valid solid (not just IsDone)."""
        try:
            mk.Build()
            if not mk.IsDone():
                return False, "the kernel could not build it"
            shape = mk.Shape()
        except Standard_Failure:
            return False, "the kernel raised an error"
        if not _occ.solids(shape):
            return False, "it would leave no solid"
        if len(_occ.solids(shape)) != len(_occ.solids(self.shape)):
            return False, "it would split or merge solids (the rounded surfaces overlap each other)"
        if not _occ.is_valid(shape):
            return False, "it would produce an invalid solid"
        return True, ""

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
        return self._dressup_limit_detail(edge_list)[0]

    def _dressup_limit_detail(self, edge_list) -> tuple[float, list[str]]:
        """(length of the shortest edge next to the selection, names of the face it bounds)."""
        efmap = _occ.edge_face_map(self.shape)
        shortest, names = math.inf, []
        for e in edge_list:
            for f in _occ.faces_of_edge(efmap, e):
                for fe in _occ.edges(f):
                    if not fe.IsSame(e) and _occ.length(fe) < shortest:
                        shortest, names = _occ.length(fe), self._names_of(f, "face")
        return (shortest if shortest < math.inf else 0.0), names

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
            from OCP.BRepOffset import BRepOffset_Mode
            from OCP.GeomAbs import GeomAbs_JoinType

            # the offset algorithm is sensitive to tolerance and join type on freeform (lofted, swept)
            # surfaces: try the precise default first, then settings that rescue those shapes
            attempts = [(1e-4, GeomAbs_JoinType.GeomAbs_Arc), (1e-4, GeomAbs_JoinType.GeomAbs_Intersection),
                        (1e-3, GeomAbs_JoinType.GeomAbs_Arc), (1e-2, GeomAbs_JoinType.GeomAbs_Arc),
                        (1e-3, GeomAbs_JoinType.GeomAbs_Intersection), (1e-2, GeomAbs_JoinType.GeomAbs_Intersection)]
            before = _occ.volume_fast(self.shape)
            ok, mk, used = False, None, None
            for tol, join in attempts:
                mk = BRepOffsetAPI_MakeThickSolid()
                try:
                    mk.MakeThickSolidByJoin(self.shape, removed, -thickness, tol, BRepOffset_Mode.BRepOffset_Skin, False, False, join)
                    mk.Build()
                    ok = mk.IsDone() and _occ.is_valid(mk.Shape()) and bool(_occ.solids(mk.Shape())) \
                        and 0 < _occ.volume_fast(mk.Shape()) < before
                except Standard_Failure:
                    ok = False
                if ok:
                    used = {"tolerance": tol, "join": "arc" if join == GeomAbs_JoinType.GeomAbs_Arc else "intersection"}
                    break
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
            feat.metrics["shell"] = used

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

    def mass(self, density_g_cm3: float | None = None) -> float:
        """Mass in grams: from the part's material, or an explicit density in g/cm^3."""
        if density_g_cm3 is None:
            if self.material is None or self.material.density is None:
                raise CadError(INVALID_ARGUMENT, f"part '{self.name}' has no material density",
                               hint="give the part a material (Part(..., material='PETG')) or pass a density in g/cm^3")
            density_g_cm3 = self.material.density
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

    def wall_thickness(self, percentile: float = 2.0, samples_per_face: int = 5) -> dict:
        """Sampled local wall thickness: ``min``, a low percentile, and the thinnest spots.

        Rays are cast inward from points on every face; thin walls, floors and the
        ligament between a hole and an edge all appear as small values.
        """
        from .analysis import thickness_report

        return thickness_report(self, percentile, samples_per_face)

    def assert_min_thickness(self, minimum: float, *, percentile: float = 2.0) -> "Part":
        """Raise ``VALIDATION_FAILED`` if the wall thickness (at ``percentile``) is below ``minimum``."""
        rep = self.wall_thickness(percentile)
        value = rep.get(f"p{percentile:g}", 0.0)
        if value < minimum - 1e-6:
            raise CadError(
                VALIDATION_FAILED,
                f"part '{self.name}' has walls thinner than {minimum} mm (p{percentile:g} = {value} mm)",
                hint="thicken the wall or move the feature: see details.thinnest for locations "
                     "(a hole too close to an edge leaves a thin ligament)",
                details={"thinnest": rep["thinnest"]},
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
            entry = {
                "diameter": round(g["diameter"], 6),
                "axis": [round(c, 6) + 0.0 for c in a],
                "position": [round(c, 4) + 0.0 for c in ctr_lo],
                "depth": round(hi - lo, 4),
                "names": names,
            }
            entry.update(self._hole_recesses(g, a, lo, hi, groups))
            out.append(entry)
        out.sort(key=lambda h: (h["diameter"], h["position"]))
        return out

    def _hole_recesses(self, g, a, lo, hi, groups) -> dict:
        """Countersink (coaxial cone) / counterbore (wider coaxial hole) at either end of a hole."""
        from OCP.BRep import BRep_Tool

        out = {}
        for f in _occ.faces(self.shape):
            if _occ.surface_type(f) != "cone":
                continue
            from OCP.BRepAdaptor import BRepAdaptor_Surface

            cone = BRepAdaptor_Surface(f).Cone()
            ax = cone.Axis().Direction()
            cd = (ax.X(), ax.Y(), ax.Z())
            if abs(abs(sum(x * y for x, y in zip(cd, a))) - 1) > 1e-6:
                continue
            loc = cone.Location()
            p = (loc.X(), loc.Y(), loc.Z())
            t = sum(pi * ai for pi, ai in zip(p, a))
            if math.dist(tuple(pi - t * ai for pi, ai in zip(p, a)), g["_foot"]) > 1e-5:
                continue
            ts, rs = [], []
            for v in _occ.vertices(f):
                q = BRep_Tool.Pnt_s(v)
                qq = (q.X(), q.Y(), q.Z())
                tq = sum(x * y for x, y in zip(qq, a))
                ts.append(tq)
                rs.append(math.dist(tuple(x - tq * y for x, y in zip(qq, a)), g["_foot"]))
            if not ts or min(abs(min(ts) - hi), abs(max(ts) - lo), abs(min(ts) - lo), abs(max(ts) - hi)) > 1e-4:
                continue
            out["countersink"] = {"diameter": round(2 * max(rs), 4), "angle": round(abs(2 * math.degrees(cone.SemiAngle())), 3)}
        for o in groups:
            if o is g or o["diameter"] <= g["diameter"] + 1e-6 or sum(x * y for x, y in zip(o["axis"], a)) < 1 - 1e-9 \
                    or math.dist(o["_foot"], g["_foot"]) > 1e-6:
                continue
            olo, ohi = math.inf, -math.inf
            for f in o["_faces"]:
                for v in _occ.vertices(f):
                    q = BRep_Tool.Pnt_s(v)
                    tq = q.X() * a[0] + q.Y() * a[1] + q.Z() * a[2]
                    olo, ohi = min(olo, tq), max(ohi, tq)
            if abs(olo - hi) < 1e-4 or abs(ohi - lo) < 1e-4:
                out["counterbore"] = {"diameter": round(o["diameter"], 4), "depth": round(ohi - olo, 4)}
        return out

    def summary(self) -> dict:
        """JSON-friendly geometric summary used by ``cad inspect``."""
        if self._shape is None:
            return {"name": self.name, "has_body": False, "features": len(self.features)}
        mat = self.material
        return {
            "name": self.name,
            "has_body": True,
            "reference": self.reference,
            "print_down": list(self.print_down) if self.print_down else None,
            "material": mat.name if mat else None,
            "mass_g": round(self.mass(), 3) if mat and mat.density else None,
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
        """Write STEP (.step/.stp), STL (.stl), 3MF (.3mf, with the part's material) or BREP (.brep)."""
        if str(path).lower().endswith(".3mf"):
            from .threemf import export_3mf

            return export_3mf({self.name: self}, path, title=self.name, **kwargs)["path"]
        from .export import export_shape

        return export_shape(self.shape, path, name=self.name, **kwargs)

    def copy(self, name: str | None = None) -> "Part":
        """Independent copy (geometry is shared immutably, history is copied)."""
        import copy as _copy

        p = Part(name or self.name, color=self.color, reference=self.reference, material=self.material)
        p.print_down = self.print_down
        p._shape = self._shape
        p._refs = {k: list(v) for k, v in self._refs.items()}
        p._ref_kind = dict(self._ref_kind)
        p._ref_origin = dict(self._ref_origin)
        p._ref_lost = dict(self._ref_lost)
        p.features = _copy.deepcopy(self.features)
        p._counters = dict(self._counters)
        return p

    # ================================================================== print orientation
    def print_on(self, face) -> "Part":
        """Print this part lying on ``face`` (a flat face selection, or a direction like "+z").

        The model keeps its assembled pose; `cad slice` and STL / 3MF exports rotate the part so
        this face is on the bed.  E.g. a lid modelled closed: ``lid.print_on(lid.faces("plate.top"))``.
        """
        if isinstance(face, str) or (isinstance(face, (list, tuple)) and len(face) == 3 and isinstance(face[0], (int, float))):
            self.print_down = tuple(_axis_dir(face))
            return self
        shapes = getattr(face, "shapes", None)
        if not shapes or any(_occ.surface_type(f) != "plane" for f in shapes):
            raise CadError(INVALID_ARGUMENT, "print_on() needs a flat face selection (or a direction such as '+z')")
        f = max(shapes, key=_occ.area)
        self.print_down = tuple(round(c, 12) for c in _occ.face_normal(f))
        return self

    def print_shape(self) -> TopoDS_Shape:
        """The shape as it will be printed: rotated so ``print_down`` points to -Z, resting on Z = 0."""
        shape = self.shape
        if self.print_down is None:
            return shape
        n = _occ.vec(self.print_down)
        target = (0.0, 0.0, -1.0)
        dot = sum(a * b for a, b in zip(n, target))
        t = gp_Trsf()
        if dot < 1 - 1e-12:
            if dot < -1 + 1e-12:
                t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), math.pi)
            else:
                axis = (n[1] * target[2] - n[2] * target[1], n[2] * target[0] - n[0] * target[2], n[0] * target[1] - n[1] * target[0])
                t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*axis)), math.acos(max(-1.0, min(1.0, dot))))
        rotated = BRepBuilderAPI_Transform(shape, t, True).Shape()
        lo, _ = _occ.bbox(rotated)
        t2 = gp_Trsf()
        t2.SetTranslation(gp_Vec(0, 0, -lo[2]))
        return BRepBuilderAPI_Transform(rotated, t2, True).Shape()

    def as_printed(self) -> "Part":
        """A copy positioned for printing (see :meth:`print_on`); itself if no orientation is set."""
        if self.print_down is None:
            return self
        p = Part._rehydrate(self.name, self.print_shape(), self.color, None, None, self.reference,
                            self.material.to_dict() if self.material else None)
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
    def _rehydrate(cls, name: str, shape: TopoDS_Shape, color=None, refs: dict | None = None, features: list[dict] | None = None,
                   reference: bool = False, material: dict | None = None, print_down=None) -> "Part":
        """Rebuild a queryable Part from stored geometry (no script re-execution)."""
        from .materials import Material

        p = cls(name, color=color, reference=reference, material=Material(**material) if material else None)
        p.print_down = tuple(print_down) if print_down else None
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
            f.param_sources = dict(fd.get("param_sources", {}))
            p.features.append(f)
        return p

    def __repr__(self) -> str:
        if self._shape is None:
            return f"<Part {self.name!r} (empty)>"
        s = self.bbox.size
        return f"<Part {self.name!r} {s[0]:.3g}x{s[1]:.3g}x{s[2]:.3g} mm, {len(self.features)} features>"


# --------------------------------------------------------------------------- helpers


def _split_warning(fid: str, op: str, before: int, after: int) -> CadWarning:
    return CadWarning(
        "BODY_SPLIT",
        f"the {op} split the part into {after} separate solids (was {before}); merged or overlapping cuts "
        "can sever thin bridges of material",
        fid,
        {"solids_before": before, "solids_after": after},
    )


def _positions(at) -> list:
    """``at`` is one point or a list of points (many instances in one feature, one boolean)."""
    if isinstance(at, (list, tuple)) and at and isinstance(at[0], (list, tuple)):
        pts = [_occ.vec(p) for p in at]
        if not pts:
            raise CadError(INVALID_ARGUMENT, "at= is an empty list of positions")
        return pts
    return [_occ.vec(at)]


def _merge_refs(into: dict, refs: dict) -> None:
    for n, (kind, shapes) in refs.items():
        into.setdefault(n, (kind, []))[1].extend(shapes)


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


def _max_dist_on_wire(wire, point, samples: int = 48) -> float:
    """Largest distance from ``point`` to the wire (sampled along each edge)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve

    best = 0.0
    for e in _occ.edges(wire):
        c = BRepAdaptor_Curve(e)
        a, b = c.FirstParameter(), c.LastParameter()
        for i in range(samples + 1):
            q = c.Value(a + (b - a) * i / samples)
            best = max(best, math.dist(point, (q.X(), q.Y(), q.Z())))
    return best


def _is_wall(face, d) -> bool:
    """A face whose surface runs parallel to direction ``d`` (a vertical wall when d is Z)."""
    st = _occ.surface_type(face)
    if st == "plane":
        return abs(sum(a * b for a, b in zip(_occ.face_normal(face), d))) < 1e-6
    if st == "cylinder":
        inf = _occ.cylinder_info(face)
        return abs(abs(sum(a * b for a, b in zip(inf["axis"], d))) - 1) < 1e-6
    return False


def _sweep_refs(fid: str, solid, start_face, end_face) -> dict:
    """start / end caps (planar faces matching the first / last section) and side faces."""
    caps_s, caps_e, side = [], [], []
    c0 = _occ.face_centroid(start_face)
    c1 = _occ.face_centroid(end_face) if end_face is not None else None
    a0 = _occ.area(start_face)
    for f in _occ.faces(solid):
        if _occ.surface_type(f) == "plane":
            c = _occ.face_centroid(f)
            if math.dist(c, c0) < 1e-4 and abs(_occ.area(f) - a0) < 1e-4 * max(a0, 1):
                caps_s.append(f)
                continue
            if c1 is not None and math.dist(c, c1) < 1e-4:
                caps_e.append(f)
                continue
            if end_face is None and abs(_occ.area(f) - a0) < 1e-3 * max(a0, 1):
                caps_e.append(f)
                continue
        side.append(f)
    refs = {}
    for role, fs in (("start", caps_s), ("end", caps_e), ("side", side)):
        if fs:
            refs[f"{fid}.{role}"] = ("face", fs)
    return refs


def _frame_trsf(origin, direction):
    """Transform from a local frame (origin 0, axis +Z) to ``origin`` with +Z along ``direction``."""
    t = gp_Trsf()
    t.SetTransformation(gp_Ax3(gp_Pnt(*origin), gp_Dir(*direction)), gp_Ax3())
    return t


def _fuse_all(shapes: list):
    """Union of overlapping solids.  The result's volume is checked (at least the largest piece, at most their
    sum): the boolean has been seen to drop a whole piece silently on one platform, so a bad union retries
    pairwise and then with a small fuzzy tolerance before giving up loudly."""
    if len(shapes) == 1:
        return shapes[0]
    vols = [_occ.volume(s) for s in shapes]
    lo, hi = max(vols) * (1 - 1e-6) - 1e-9, sum(vols) * (1 + 1e-6) + 1e-9

    def sane(r):
        return r is not None and not r.IsNull() and _occ.is_valid(r) and lo <= _occ.volume(r) <= hi

    def together(fuzzy=0.0):
        alg = BRepAlgoAPI_Fuse()
        args, tools = List_TopoDS_Shape(), List_TopoDS_Shape()
        args.Append(shapes[0])
        for sh in shapes[1:]:
            tools.Append(sh)
        alg.SetArguments(args)
        alg.SetTools(tools)
        if fuzzy:
            alg.SetFuzzyValue(fuzzy)
        alg.Build()
        alg.SimplifyResult()
        return alg.Shape()

    def pairwise():
        acc = shapes[0]
        for sh in shapes[1:]:
            acc = BRepAlgoAPI_Fuse(acc, sh).Shape()
        return acc

    for attempt in (together, pairwise, lambda: together(1e-5)):
        try:
            r = attempt()
        except Standard_Failure:
            continue
        if sane(r):
            return r
    raise CadError(BOOLEAN_FAILED, f"joining {len(shapes)} pieces failed: the kernel's union lost material",
                   hint="this is a kernel robustness problem; try slightly different sizes or positions")


def _import_align(align):
    if align is None:
        return None
    if isinstance(align, str):
        align = (align, align, align)
    if len(align) != 3 or any(a not in (None, "min", "center", "max") for a in align):
        raise CadError(INVALID_ARGUMENT, f"align must be 3 of 'min' | 'center' | 'max' | None, got {align!r}",
                       hint='e.g. align=("center", "center", "min"): centred on X/Y, bottom on Z = 0')
    return tuple(align)


def _ref_safe(name: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "body"


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
