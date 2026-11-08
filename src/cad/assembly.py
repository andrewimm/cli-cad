"""Assemblies: parts connected by joints (revolute, slider, cylindrical, fixed).

Parts are modelled in place: the pose they are built in is the *rest pose*, where every
joint value is 0.  A joint names a parent and a child part and an axis; its value turns
(revolute, degrees) or moves (slider, mm) the child -- and everything attached below it
-- about / along that axis, measured in the parent's design frame.  So a chain composes
automatically: moving the hip moves the knee axis with it.

    asm = Assembly("leg")
    asm.add(base)                                    # the first part is fixed to the world
    asm.revolute("hip", base, upper, axis=base.faces("hip.wall"), angle="hip_angle")
    asm.revolute("knee", upper, lower, axis=upper.faces("knee.wall"), angle="knee_angle")
    return asm

Values are numbers or the names of declared Parameters (``Parameter("knee_angle", 0,
min=0, max=90, unit="deg")``): then the joint takes the parameter's limits, `cad set
knee_angle 45` poses it and `cad sweep knee 0:90:15` moves it.

Axes come from geometry (a cylindrical face such as a hole or boss wall, a circular edge,
a flat face for sliders) or are given as ``(point, direction)``.  A direction taken from
geometry points along the positive world axis it is closest to; pass ``direction=`` to
reverse it.  Positive angles turn right-handed about the axis direction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from . import _occ
from .errors import INVALID_ARGUMENT, CadError

JOINT_LIMIT = "JOINT_LIMIT"
TYPES = ("revolute", "slider", "cylindrical", "fixed")


@dataclass
class Joint:
    name: str
    type: str
    parent: str
    child: str
    origin: tuple[float, float, float]
    direction: tuple[float, float, float]
    value: float = 0.0                 # degrees (revolute) / mm (slider)
    slide: float = 0.0                 # mm, cylindrical joints only
    param: str | None = None
    slide_param: str | None = None
    limits: tuple[float, float] | None = None
    axis_source: str = ""
    warnings: list[dict] = field(default_factory=list)


def _value(v, what: str) -> tuple[float, str | None, tuple[float, float] | None]:
    """(number, parameter name, parameter limits) from a number or the name of a declared Parameter."""
    from .params import _ctx

    if isinstance(v, str):
        ctx = _ctx.get()
        info = ctx.declared.get(v) if ctx is not None else None
        if info is None:
            known = sorted(ctx.declared) if ctx is not None else []
            raise CadError(INVALID_ARGUMENT, f"joint {what} {v!r} is not a declared Parameter",
                           hint="declare it first: knee = Parameter('knee_angle', 0, min=0, max=90, unit='deg'), "
                                "then pass angle='knee_angle'", details={"parameters": known})
        lim = (info.min, info.max) if info.min is not None and info.max is not None else None
        return float(info.value), v, lim
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v), None, None
    raise CadError(INVALID_ARGUMENT, f"joint {what} must be a number or a Parameter name, got {type(v).__name__}")


def _canonical(d: Sequence[float]) -> tuple[float, float, float]:
    """Point a geometric axis along the positive world axis it is closest to."""
    d = _occ.vec(d)
    n = math.sqrt(sum(c * c for c in d))
    d = tuple(c / n for c in d)
    k = max(range(3), key=lambda i: abs(d[i]))
    return tuple(-c for c in d) if d[k] < 0 else d


def axis_from(spec, direction=None) -> tuple[tuple, tuple, str]:
    """(origin, unit direction, description) for a joint axis specification."""
    from .selection import EdgeSelection, FaceSelection

    if isinstance(spec, (FaceSelection, EdgeSelection)):
        shapes = spec.shapes
        if not shapes:
            raise CadError(INVALID_ARGUMENT, f"joint axis selection {spec.description} is empty")
        if isinstance(spec, FaceSelection):
            cyl = [s for s in shapes if _occ.cylinder_info(s)]
            if cyl:
                infos = [_occ.cylinder_info(s) for s in cyl]
                a0 = infos[0]
                for inf in infos[1:]:  # several faces (a split hole wall) must share one axis
                    if abs(abs(sum(x * y for x, y in zip(inf["axis"], a0["axis"]))) - 1) > 1e-6 or \
                            _dist_point_line(inf["axis_point"], a0["axis_point"], a0["axis"]) > 1e-4:
                        raise CadError(INVALID_ARGUMENT, f"joint axis selection {spec.description} has cylinders on different axes",
                                       hint="select one hole or boss, e.g. part.faces('hinge.wall')")
                origin, d, src = tuple(a0["axis_point"]), tuple(a0["axis"]), f"axis of {spec.description} (diameter {2 * a0['radius']:g})"
            elif all(_occ.surface_type(s) == "plane" for s in shapes):
                f = max(shapes, key=_occ.area)
                origin, d, src = _occ.face_centroid(f), _occ.face_normal(f), f"normal of {spec.description}"
            else:
                raise CadError(INVALID_ARGUMENT, f"joint axis needs a cylindrical face (hole/boss) or a flat face, got {spec.description}")
        else:
            circ = [_occ.circle_info(e) for e in shapes]
            if circ[0]:
                origin, d, src = tuple(circ[0]["center"]), tuple(circ[0]["axis"]), f"axis of circle {spec.description}"
            elif _occ.curve_type(shapes[0]) == "line":
                a, b = _occ.edge_endpoints(shapes[0])
                origin, d, src = a, tuple(q - p for p, q in zip(a, b)), f"line {spec.description}"
            else:
                raise CadError(INVALID_ARGUMENT, "joint axis edge must be a circle or a straight line")
        d = _canonical(d)
    elif isinstance(spec, (list, tuple)) and len(spec) == 2 and all(isinstance(c, (list, tuple)) for c in spec):
        origin, d, src = _occ.vec(spec[0]), _occ.vec(spec[1]), "explicit"
        n = math.sqrt(sum(c * c for c in d))
        if n < 1e-12:
            raise CadError(INVALID_ARGUMENT, "joint axis direction is zero")
        d = tuple(c / n for c in d)
    else:
        raise CadError(INVALID_ARGUMENT, "joint axis must be a face/edge selection or (point, direction)",
                       hint="e.g. axis=base.faces('hinge.wall') or axis=((0, 0, 10), (0, 1, 0))")
    if direction is not None:
        from .part import _axis_dir

        want = _axis_dir(direction)
        dot = sum(a * b for a, b in zip(want, d))
        if abs(dot) < 0.5:
            raise CadError(INVALID_ARGUMENT, f"direction={direction!r} is not along the joint axis {tuple(round(c, 3) for c in d)}")
        if dot < 0:
            d = tuple(-c for c in d)
    return tuple(float(c) for c in origin), tuple(float(c) for c in d), src


def _dist_point_line(p, o, d) -> float:
    v = [a - b for a, b in zip(p, o)]
    t = sum(a * b for a, b in zip(v, d))
    return math.sqrt(max(0.0, sum(c * c for c in v) - t * t))


def joint_trsf(j: Joint, value: float | None = None, slide: float | None = None):
    """gp_Trsf of a joint's motion (in the parent's design frame)."""
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

    v = j.value if value is None else value
    s = j.slide if slide is None else slide
    t = gp_Trsf()
    if j.type in ("revolute", "cylindrical") and v:
        t.SetRotation(gp_Ax1(gp_Pnt(*j.origin), gp_Dir(*j.direction)), math.radians(v))
    move = v if j.type == "slider" else (s if j.type == "cylindrical" else 0.0)
    if move:
        m = gp_Trsf()
        m.SetTranslation(gp_Vec(*[c * move for c in j.direction]))
        t = m.Multiplied(t)
    return t


class Assembly:
    """Parts and the joints between them.  Return it from ``build()``."""

    def __init__(self, name: str = "assembly"):
        self.name = name
        self.parts: dict[str, Any] = {}
        self.ground: str | None = None
        self.joints: list[Joint] = []

    # ------------------------------------------------------------------ parts
    def add(self, *parts, ground: bool = False) -> "Assembly":
        """Add parts.  The first part added (or one with ``ground=True``) is fixed to the world;
        parts not connected to it by joints stay where they were modelled."""
        from .part import Part

        for p in parts:
            if not isinstance(p, Part):
                raise CadError(INVALID_ARGUMENT, f"Assembly.add() takes Parts, got {type(p).__name__}")
            if p.name in self.parts and self.parts[p.name] is not p:
                raise CadError(INVALID_ARGUMENT, f"two different parts are named {p.name!r}", hint="give each part a unique name")
            self.parts[p.name] = p
            if ground or self.ground is None:
                self.ground = p.name if ground or self.ground is None else self.ground
        return self

    def _name(self, p) -> str:
        from .part import Part

        name = p.name if isinstance(p, Part) else str(p)
        if isinstance(p, Part) and name not in self.parts:
            self.add(p)
        if name not in self.parts:
            raise CadError(INVALID_ARGUMENT, f"part {name!r} is not in assembly {self.name!r}", details={"parts": list(self.parts)})
        return name

    # ------------------------------------------------------------------ joints
    def revolute(self, name: str, parent, child, *, axis, angle=0.0, direction=None,
                 limits: tuple[float, float] | None = None) -> Joint:
        """``child`` turns about ``axis`` (fixed in ``parent``) by ``angle`` degrees from its
        modelled pose; positive = right-handed about the axis direction."""
        return self._joint("revolute", name, parent, child, axis, direction, angle, limits)

    def slider(self, name: str, parent, child, *, axis, distance=0.0, direction=None,
               limits: tuple[float, float] | None = None) -> Joint:
        """``child`` moves ``distance`` mm along ``axis`` (a flat face's normal, an edge, a
        hole axis or (point, direction)) from its modelled pose."""
        return self._joint("slider", name, parent, child, axis, direction, distance, limits)

    def cylindrical(self, name: str, parent, child, *, axis, angle=0.0, distance=0.0, direction=None,
                    limits: tuple[float, float] | None = None) -> Joint:
        """Turns by ``angle`` and slides by ``distance`` along one axis (a pin in a hole)."""
        j = self._joint("cylindrical", name, parent, child, axis, direction, angle, limits)
        j.slide, j.slide_param, _ = _value(distance, "distance")
        return j

    def fixed(self, name: str, parent, child) -> Joint:
        """``child`` is attached rigidly to ``parent`` and follows it."""
        return self._joint("fixed", name, parent, child, ((0, 0, 0), (0, 0, 1)), None, 0.0, None)

    def _joint(self, jtype, name, parent, child, axis, direction, value, limits) -> Joint:
        if any(j.name == name for j in self.joints):
            raise CadError(INVALID_ARGUMENT, f"joint {name!r} already exists")
        pn, cn = self._name(parent), self._name(child)
        if pn == cn:
            raise CadError(INVALID_ARGUMENT, f"joint {name!r} connects {pn!r} to itself")
        if cn == self.ground:
            raise CadError(INVALID_ARGUMENT, f"joint {name!r}: {cn!r} is the fixed (ground) part, so it cannot be a child",
                           hint="swap parent and child, or add another part first / with ground=True")
        other = next((j for j in self.joints if j.child == cn), None)
        if other:
            raise CadError(INVALID_ARGUMENT, f"{cn!r} already hangs from joint {other.name!r}; a part can have only one parent joint",
                           hint="closed loops (four-bar linkages) are not supported yet: model one link of the loop "
                                "as driven by the others, or check the closing joint with cad clearance")
        origin, d, src = axis_from(axis, direction)
        v, param, plim = _value(value, "value")
        lim = tuple(limits) if limits is not None else plim
        j = Joint(name, jtype, pn, cn, origin, d, v, param=param, limits=lim, axis_source=src)
        self.joints.append(j)
        # a cycle through parents would never resolve
        seen, cur = set(), pn
        while cur is not None:
            if cur in seen or cur == cn:
                self.joints.pop()
                raise CadError(INVALID_ARGUMENT, f"joint {name!r} closes a loop ({cn!r} is already above {pn!r})")
            seen.add(cur)
            cur = next((x.parent for x in self.joints if x.child == cur), None)
        return j

    # ------------------------------------------------------------------ solving
    def chain(self, part: str) -> list[Joint]:
        """Joints from the ground (or a free part) down to ``part``, outermost first."""
        out, cur = [], part
        while True:
            j = next((x for x in self.joints if x.child == cur), None)
            if j is None:
                return list(reversed(out))
            out.append(j)
            cur = j.parent

    def part_trsf(self, part: str, values: dict[str, float] | None = None):
        """World transform of ``part`` for joint ``values`` (default: the joints' own values)."""
        from OCP.gp import gp_Trsf

        values = values or {}
        t = gp_Trsf()
        for j in self.chain(part):  # outermost first: T = M1 * M2 * ... * Mk
            t = t.Multiplied(joint_trsf(j, values.get(j.name)))
        return t

    def solve(self) -> dict:
        """Placed copies of every part ({name: Part}) for the current joint values."""
        for j in self.joints:
            if j.limits and not (j.limits[0] - 1e-9 <= j.value <= j.limits[1] + 1e-9):
                raise CadError(JOINT_LIMIT, f"joint {j.name!r} is at {j.value:g}, outside its limits {j.limits[0]:g}..{j.limits[1]:g}")
        out = {}
        for name, p in self.parts.items():
            chain = self.chain(name)
            if not chain or all(_is_identity(joint_trsf(j)) for j in chain):
                out[name] = p
                continue
            q = p.copy()
            q._transform("pose", None, self.part_trsf(name),
                         {"joints": [{"joint": j.name, "type": j.type, "value": j.value} for j in chain]})
            out[name] = q
        return out

    def describe(self) -> list[dict]:
        """Joint records for the manifest / `cad joints` (axes in world coordinates at the current pose)."""
        from OCP.gp import gp_Dir, gp_Pnt

        out = []
        for j in self.joints:
            parent_t = self.part_trsf(j.parent)
            o = gp_Pnt(*j.origin).Transformed(parent_t)
            d = gp_Dir(*j.direction).Transformed(parent_t)
            rec = {"name": j.name, "type": j.type, "parent": j.parent, "child": j.child,
                   "axis_origin": [round(o.X(), 6), round(o.Y(), 6), round(o.Z(), 6)],
                   "axis_direction": [round(d.X(), 6), round(d.Y(), 6), round(d.Z(), 6)],
                   "axis_source": j.axis_source, "value": j.value, "unit": "mm" if j.type == "slider" else "deg",
                   "parameter": j.param, "limits": list(j.limits) if j.limits else None,
                   "moves": sorted({p for p in self.parts if j in self.chain(p)}),
                   "positive_motion": self._motion_hint(j), "warnings": self._axis_warnings(j)}
            if j.type == "cylindrical":
                rec.update(slide=j.slide, slide_parameter=j.slide_param)
            out.append(rec)
        return out

    def _motion_hint(self, j: Joint) -> str | None:
        """Plain-words effect of a small positive value on the child's farthest point from the axis."""
        if j.type == "fixed":
            return None
        child = self.parts[j.child]
        lo, hi = _occ.bbox(child.shape)
        corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        if j.type == "slider":
            return "the child moves along " + _dir_words(j.direction)
        far = max(corners, key=lambda c: _dist_point_line(c, j.origin, j.direction))
        if _dist_point_line(far, j.origin, j.direction) < 1e-6:
            return None
        v = [a - b for a, b in zip(far, j.origin)]
        move = [j.direction[1] * v[2] - j.direction[2] * v[1], j.direction[2] * v[0] - j.direction[0] * v[2],
                j.direction[0] * v[1] - j.direction[1] * v[0]]  # d x r: direction of travel for +angle
        return (f"in the modelled pose, its far end near ({', '.join(f'{c:.4g}' for c in far)}) moves "
                + _dir_words(move))

    def _axis_warnings(self, j: Joint) -> list[dict]:
        if j.type == "fixed" or j.type == "slider":
            return []
        missing = []
        for pn in (j.parent, j.child):
            part = self.parts[pn]
            if not any(_coaxial(f, j.origin, j.direction) for f in _occ.faces(part.shape)):
                missing.append(pn)
        if missing:
            return [{"code": "JOINT_AXIS_OFF_GEOMETRY",
                     "message": f"no hole or boss of {', '.join(missing)} lies on the axis of joint {j.name!r}",
                     "hint": "a revolute joint usually runs through a pin hole in both parts; check the axis position"}]
        return []


def _coaxial(face, origin, d) -> bool:
    inf = _occ.cylinder_info(face)
    if not inf:
        return False
    return abs(abs(sum(a * b for a, b in zip(inf["axis"], d))) - 1) < 1e-6 and _dist_point_line(inf["axis_point"], origin, d) < 1e-3


def _dir_words(v) -> str:
    names = (("+X", "-X"), ("+Y", "-Y"), ("+Z (up)", "-Z (down)"))
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    parts = [(abs(c) / n, names[i][0] if c > 0 else names[i][1]) for i, c in enumerate(v)]
    parts = [p for p in sorted(parts, reverse=True) if p[0] > 0.25]
    return " and ".join(name for _, name in parts) if parts else "nowhere"


def _is_identity(t) -> bool:
    from OCP.gp import gp_Pnt

    return all(gp_Pnt(*p).Transformed(t).Distance(gp_Pnt(*p)) < 1e-12 for p in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)))
