"""Geometric selections of faces and edges.

Selections are immutable, chainable filters over the faces or edges of a
:class:`~cad.part.Part` at the moment they were created::

    part.edges().vertical()                  # edges parallel to Z
    part.faces().planar().facing("+z").max("z")  # top-most upward face(s)
    part.edges().of(part.faces("base.top")).convex()

Every selection remembers a human-readable ``description`` of how it was
built ("edges().vertical().convex()"); the feature graph records it so an agent
can see *why* a fillet touched the edges it did.

Selections never silently pick "the first" item.  Use :meth:`one` when exactly
one entity is expected — it raises ``AMBIGUOUS_SELECTION`` / ``EMPTY_SELECTION``
with the candidates listed instead of guessing.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable, Iterable, Sequence

from . import _occ
from .errors import AMBIGUOUS_SELECTION, EMPTY_SELECTION, INVALID_ARGUMENT, CadError

if TYPE_CHECKING:
    from .part import Part

_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
ANGLE_TOL_DEG = 0.5
POS_TOL = 1e-4


def parse_direction(d: str | Sequence[float]) -> tuple[float, float, float]:
    """'+z', '-x', 'z', or a 3-vector -> unit vector."""
    if isinstance(d, str):
        s = d.strip().lower()
        sign = -1.0 if s.startswith("-") else 1.0
        s = s.lstrip("+-")
        if s not in _AXES:
            raise CadError(INVALID_ARGUMENT, f"unknown direction {d!r}", hint="use '+x', '-y', 'z', or (x, y, z)")
        return tuple(sign * c for c in _AXES[s])  # type: ignore[return-value]
    v = _occ.vec(d)
    n = math.sqrt(sum(c * c for c in v))
    if n == 0:
        raise CadError(INVALID_ARGUMENT, "direction vector has zero length")
    return (v[0] / n, v[1] / n, v[2] / n)


def _axis_index(axis: str) -> int:
    a = axis.strip().lower().lstrip("+-")
    if a not in _AXES:
        raise CadError(INVALID_ARGUMENT, f"unknown axis {axis!r}", hint="use 'x', 'y' or 'z'")
    return "xyz".index(a)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _r(v, nd=4):
    return [round(c, nd) + 0.0 for c in v]


class _Selection:
    kind = "entity"

    def __init__(self, part: "Part", items: Sequence, description: str):
        self._part = part
        self._items = list(items)
        self.description = description

    # -- container protocol
    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.description}: {len(self)} {self.kind}(s)>"

    @property
    def shapes(self) -> list:
        return list(self._items)

    def _derive(self, items: Iterable, label: str):
        return type(self)(self._part, list(items), f"{self.description}.{label}")

    # -- generic filters
    def where(self, predicate: Callable, label: str = "where(<fn>)"):
        """Keep items for which ``predicate(info_dict)`` is true. See :meth:`info`."""
        return self._derive([s for s in self._items if predicate(self._info(s))], label)

    def _extreme(self, axis: str, pick_max: bool, tol: float):
        if not self._items:
            return self._derive([], f"{'max' if pick_max else 'min'}({axis!r})")
        i = _axis_index(axis)
        vals = [self._centroid(s)[i] for s in self._items]
        target = max(vals) if pick_max else min(vals)
        keep = [s for s, v in zip(self._items, vals) if abs(v - target) <= tol]
        return self._derive(keep, f"{'max' if pick_max else 'min'}({axis!r})")

    def max(self, axis: str = "z", tol: float = 1e-3):
        """Items whose centroid is at the maximum coordinate along ``axis``."""
        return self._extreme(axis, True, tol)

    def min(self, axis: str = "z", tol: float = 1e-3):
        """Items whose centroid is at the minimum coordinate along ``axis``."""
        return self._extreme(axis, False, tol)

    def at(self, axis: str, value: float, tol: float = 1e-3):
        """Items whose centroid coordinate along ``axis`` equals ``value`` (± tol)."""
        i = _axis_index(axis)
        return self._derive(
            [s for s in self._items if abs(self._centroid(s)[i] - value) <= tol], f"at({axis!r}, {value})"
        )

    def between(self, axis: str, lo: float, hi: float):
        """Items whose centroid coordinate along ``axis`` is within [lo, hi]."""
        i = _axis_index(axis)
        return self._derive(
            [s for s in self._items if lo - POS_TOL <= self._centroid(s)[i] <= hi + POS_TOL],
            f"between({axis!r}, {lo}, {hi})",
        )

    def nearest(self, point: Sequence[float], count: int = 1):
        """The ``count`` items whose centroid is closest to ``point``."""
        p = _occ.vec(point)
        ranked = sorted(self._items, key=lambda s: sum((a - b) ** 2 for a, b in zip(self._centroid(s), p)))
        return self._derive(ranked[:count], f"nearest({_r(p)}, {count})")

    def named(self, name: str):
        """Intersect with the named reference ``name`` (see ``Part.tag``)."""
        ref = _occ.ShapeSet(self._part._resolve_ref(name, self.kind))
        return self._derive([s for s in self._items if s in ref], f"named({name!r})")

    def created_by(self, feature: str):
        """Items generated or modified by feature ``feature`` (e.g. 'hole1')."""
        refs = _occ.ShapeSet()
        for n, shapes in self._part._refs.items():
            if n.split(".", 1)[0] == feature and self._part._ref_kind.get(n) == self.kind:
                for s in shapes:
                    refs.add(s)
        return self._derive([s for s in self._items if s in refs], f"created_by({feature!r})")

    def exclude(self, other: "_Selection"):
        drop = _occ.ShapeSet(other._items)
        return self._derive([s for s in self._items if s not in drop], f"exclude({other.description})")

    def __or__(self, other: "_Selection"):
        seen = _occ.ShapeSet(self._items)
        merged = list(self._items) + [s for s in other._items if s not in seen]
        return type(self)(self._part, merged, f"({self.description} | {other.description})")

    def __sub__(self, other: "_Selection"):
        return self.exclude(other)

    def one(self):
        """Assert exactly one item and return the selection (raises otherwise)."""
        if len(self._items) == 1:
            return self
        if not self._items:
            raise CadError(
                EMPTY_SELECTION,
                f"selection {self.description} matched no {self.kind}s",
                hint=f"inspect candidates with part.{self.kind}s().info() or loosen the filters",
            )
        raise CadError(
            AMBIGUOUS_SELECTION,
            f"selection {self.description} matched {len(self._items)} {self.kind}s, expected exactly 1",
            hint="add a filter such as .max('z'), .nearest(point) or .named(...)",
            details={"candidates": self.info()[:12]},
        )

    def expect(self, count: int):
        """Assert the selection has exactly ``count`` items (raises otherwise)."""
        if len(self._items) != count:
            raise CadError(
                EMPTY_SELECTION if not self._items else AMBIGUOUS_SELECTION,
                f"selection {self.description} matched {len(self._items)} {self.kind}s, expected {count}",
                details={"candidates": self.info()[:12]},
            )
        return self

    def info(self) -> list[dict]:
        """JSON-friendly description of every item (type, centroid, size...)."""
        return [self._info(s) for s in self._items]

    # subclass hooks
    def _centroid(self, s):  # pragma: no cover - abstract
        raise NotImplementedError

    def _info(self, s) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError


class FaceSelection(_Selection):
    kind = "face"

    def __init__(self, part, items, description):
        super().__init__(part, items, description)
        self._cache: dict[int, dict] = {}

    def _centroid(self, s):
        return self._info(s)["centroid"]

    def _info(self, s) -> dict:
        key = id(s)
        if key not in self._cache:
            d = {
                "type": _occ.surface_type(s),
                "area": round(_occ.area(s), 6),
                "centroid": _r(_occ.face_centroid(s)),
                "normal": _r(_occ.face_normal(s)),
            }
            cyl = _occ.cylinder_info(s)
            if cyl:
                d["radius"] = round(cyl["radius"], 6)
                d["sweep_deg"] = round(math.degrees(cyl["angle"]), 3)
                d["axis"] = _r(cyl["axis"])
                d["concave"] = cyl["concave"]
            names = self._part._names_of(s, "face")
            if names:
                d["names"] = names
            self._cache[key] = d
        return self._cache[key]

    def _derive(self, items, label):
        sel = FaceSelection(self._part, list(items), f"{self.description}.{label}")
        sel._cache = self._cache
        return sel

    def planar(self):
        return self._derive([f for f in self if self._info(f)["type"] == "plane"], "planar()")

    def cylindrical(self):
        return self._derive([f for f in self if self._info(f)["type"] == "cylinder"], "cylindrical()")

    def of_type(self, surface_type: str):
        """Filter by surface type: plane, cylinder, cone, sphere, torus, bspline."""
        return self._derive([f for f in self if self._info(f)["type"] == surface_type], f"of_type({surface_type!r})")

    def facing(self, direction: str | Sequence[float], tol_deg: float = ANGLE_TOL_DEG):
        """Planar faces whose outward normal points along ``direction`` ('+z', (0,1,0), ...)."""
        d = parse_direction(direction)
        c = math.cos(math.radians(tol_deg))
        keep = [f for f in self if self._info(f)["type"] == "plane" and _dot(self._info(f)["normal"], d) >= c]
        return self._derive(keep, f"facing({direction!r})")

    def holes(self, diameter: float | None = None, tol: float = 1e-3):
        """Hole walls: concave cylindrical faces sweeping at least 180 degrees.

        Concave fillets (quarter cylinders) are excluded.  Optionally filter by
        ``diameter``.
        """
        keep = []
        for f in self:
            i = self._info(f)
            if i["type"] == "cylinder" and i.get("concave") and i.get("sweep_deg", 0) >= 179.0:
                if diameter is None or abs(2 * i["radius"] - diameter) <= tol:
                    keep.append(f)
        return self._derive(keep, f"holes({diameter})" if diameter is not None else "holes()")

    def larger_than(self, area: float):
        return self._derive([f for f in self if self._info(f)["area"] > area], f"larger_than({area})")

    def smaller_than(self, area: float):
        return self._derive([f for f in self if self._info(f)["area"] < area], f"smaller_than({area})")

    def largest(self):
        if not self._items:
            return self._derive([], "largest()")
        a = max(self._info(f)["area"] for f in self)
        return self._derive([f for f in self if abs(self._info(f)["area"] - a) <= 1e-6 * max(a, 1)], "largest()")

    def edges(self) -> "EdgeSelection":
        """All edges bounding these faces."""
        seen = _occ.ShapeSet()
        out = []
        for f in self:
            for e in _occ.edges(f):
                if e not in seen:
                    seen.add(e)
                    out.append(e)
        all_edges = {hash(e): e for e in _occ.edges(self._part.shape)}
        canon = [next((g for g in [all_edges.get(hash(e))] if g is not None and g.IsSame(e)), e) for e in out]
        return EdgeSelection(self._part, canon, f"{self.description}.edges()")


class EdgeSelection(_Selection):
    kind = "edge"

    def __init__(self, part, items, description):
        super().__init__(part, items, description)
        self._cache: dict[int, dict] = {}

    def _derive(self, items, label):
        sel = EdgeSelection(self._part, list(items), f"{self.description}.{label}")
        sel._cache = self._cache
        return sel

    def _centroid(self, s):
        return self._info(s)["midpoint"]

    def _info(self, s) -> dict:
        key = id(s)
        if key not in self._cache:
            a, b = _occ.edge_endpoints(s)
            d = {
                "type": _occ.curve_type(s),
                "length": round(_occ.length(s), 6),
                "midpoint": _r(_occ.edge_midpoint(s)),
                "start": _r(a),
                "end": _r(b),
            }
            if d["type"] == "line":
                d["direction"] = _r(_occ.edge_tangent(s))
            ci = _occ.circle_info(s)
            if ci:
                d["radius"] = round(ci["radius"], 6)
                d["center"] = _r(ci["center"])
                d["axis"] = _r(ci["axis"])
            names = self._part._names_of(s, "edge")
            if names:
                d["names"] = names
            self._cache[key] = d
        return self._cache[key]

    def linear(self):
        return self._derive([e for e in self if self._info(e)["type"] == "line"], "linear()")

    def circular(self, radius: float | None = None, tol: float = 1e-3):
        keep = [
            e
            for e in self
            if self._info(e)["type"] == "circle" and (radius is None or abs(self._info(e)["radius"] - radius) <= tol)
        ]
        return self._derive(keep, f"circular({radius})" if radius is not None else "circular()")

    def parallel_to(self, direction: str | Sequence[float], tol_deg: float = ANGLE_TOL_DEG):
        """Straight edges parallel to ``direction`` (either sense)."""
        d = parse_direction(direction)
        c = math.cos(math.radians(tol_deg))
        keep = [e for e in self if self._info(e)["type"] == "line" and abs(_dot(self._info(e)["direction"], d)) >= c]
        return self._derive(keep, f"parallel_to({direction!r})")

    def perpendicular_to(self, direction: str | Sequence[float], tol_deg: float = ANGLE_TOL_DEG):
        """Edges lying in planes perpendicular to ``direction`` (lines and circles)."""
        d = parse_direction(direction)
        s = math.sin(math.radians(tol_deg))
        keep = []
        for e in self:
            i = self._info(e)
            if i["type"] == "line" and abs(_dot(i["direction"], d)) <= s:
                keep.append(e)
            elif i["type"] == "circle" and abs(abs(_dot(i["axis"], d)) - 1) <= 1 - math.cos(math.radians(tol_deg)) + 1e-9:
                keep.append(e)
        return self._derive(keep, f"perpendicular_to({direction!r})")

    def vertical(self):
        """Straight edges parallel to Z."""
        sel = self.parallel_to("z")
        sel.description = f"{self.description}.vertical()"
        return sel

    def horizontal(self):
        """Edges lying in a plane perpendicular to Z (lines and arcs)."""
        sel = self.perpendicular_to("z")
        sel.description = f"{self.description}.horizontal()"
        return sel

    def _convexity(self) -> dict[int, float]:
        if "_cvx" not in self.__dict__:
            efmap = _occ.edge_face_map(self._part.shape)
            out = {}
            for e in self:
                fs = _occ.faces_of_edge(efmap, e)
                out[id(e)] = _occ.edge_convexity(e, fs[0], fs[1]) if len(fs) == 2 else 0.0
            self.__dict__["_cvx"] = out
        return self.__dict__["_cvx"]

    def convex(self, tol: float = 1e-3):
        """Outside corners (where material is less than 180 degrees around the edge)."""
        c = self._convexity()
        return self._derive([e for e in self if c[id(e)] < -tol], "convex()")

    def concave(self, tol: float = 1e-3):
        """Inside corners (where material wraps more than 180 degrees around the edge)."""
        c = self._convexity()
        return self._derive([e for e in self if c[id(e)] > tol], "concave()")

    def of(self, faces: FaceSelection):
        """Edges that bound any face in ``faces``."""
        bound = _occ.ShapeSet(faces.edges())
        return self._derive([e for e in self if e in bound], f"of({faces.description})")

    def longer_than(self, length: float):
        return self._derive([e for e in self if self._info(e)["length"] > length], f"longer_than({length})")

    def shorter_than(self, length: float):
        return self._derive([e for e in self if self._info(e)["length"] < length], f"shorter_than({length})")
