"""Load cases for stress analysis (``cad fea``).

A Study says how a part is held and loaded, using the same face references the
script already has::

    s = Study("payload", arm, target=2)          # target safety factor
    s.fixed("mount.bore")                         # held in place
    s.bearing("tip.bore", 20, direction="-z")     # a pin pushing on a hole, N
    s.force(arm.faces("pad.top"), 50, "-z")       # spread evenly over the faces, N
    s.torque("hub.bore", 1.2)                     # N*m about the bore's axis
    s.pressure("lid.top", 0.05)                   # MPa pushing into the faces
    s.gravity(3)                                  # own weight at 3 g
    s.force("deck.top", 30, "-z", at=(40, 0, 5), radius=6)   # only the part of the face within 6 mm of a point

Studies are declared in the script (anywhere, after the part's last feature) and
stored with the revision; ``cad fea`` solves them.  Units: N, N*m, MPa, mm.
"""

from __future__ import annotations

from typing import Any, Sequence

from . import _occ
from .errors import INVALID_ARGUMENT, CadError

STUDY_FACE_LOST = "STUDY_FACE_LOST"
KINDS = ("fixed", "force", "bearing", "torque", "pressure", "gravity")


def _direction(d) -> list[float]:
    from .part import _axis_dir

    return [float(c) for c in _axis_dir(d)]


class Study:
    def __init__(self, name: str, part, *, target: float = 2.0, description: str | None = None):
        """``target``: the safety factor (strength / peak stress) the part should reach."""
        from .params import _ctx
        from .part import Part

        if not isinstance(name, str) or not name.strip() or any(c in name for c in " /\\"):
            raise CadError(INVALID_ARGUMENT, f"study name {name!r} must be a non-empty word (no spaces or slashes)")
        if not isinstance(part, Part):
            raise CadError(INVALID_ARGUMENT, f"Study needs the Part to analyse, got {type(part).__name__}")
        if not target > 0:
            raise CadError(INVALID_ARGUMENT, f"target safety factor must be positive, got {target!r}")
        self.name = name
        self.part = part
        self.target = float(target)
        self.description = description
        self.loads: list[dict] = []
        ctx = _ctx.get()
        if ctx is not None:
            if any(s.name == name for s in ctx.studies):
                raise CadError(INVALID_ARGUMENT, f"study {name!r} is declared twice")
            ctx.studies.append(self)

    # ------------------------------------------------------------------ boundary conditions
    # every face-based load takes ``at=(x, y, z), radius=r`` to act on only the part of the faces
    # within r mm of a point (a pad on a large face: coplanar faces merge into one when unioned)

    def fixed(self, faces, *, directions: str = "xyz", at=None, radius=None) -> "Study":
        """Hold ``faces`` still (bolted down, clamped, glued).  ``directions="z"`` only stops motion
        along Z (a part resting on a surface it can slide on)."""
        if not directions or any(c not in "xyz" for c in directions):
            raise CadError(INVALID_ARGUMENT, f"directions must be letters from 'xyz', got {directions!r}")
        return self._add("fixed", faces, at, radius, directions="".join(sorted(set(directions))))

    def force(self, faces, newtons: float, direction="-z", *, at=None, radius=None) -> "Study":
        """A force of ``newtons`` N spread evenly over ``faces``."""
        return self._add("force", faces, at, radius, newtons=_num(newtons, "newtons"), direction=_direction(direction))

    def bearing(self, faces, newtons: float, direction="-z", *, at=None, radius=None) -> "Study":
        """A pin, bolt or shaft in a hole pushing the part along ``direction`` with ``newtons`` N.
        Only the side of the hole the pin pushes on carries the load (cosine distribution), which is
        how holes really fail; a plain force() on a bore loads both sides and underestimates stress."""
        return self._add("bearing", faces, at, radius, newtons=_num(newtons, "newtons"), direction=_direction(direction))

    def torque(self, faces, newton_metres: float, *, axis=None, center: Sequence[float] | None = None, at=None,
               radius=None) -> "Study":
        """Twist ``faces`` by ``newton_metres`` N*m (right-handed about ``axis``).  For a cylindrical
        face (a bore, a shaft) the axis defaults to the cylinder's own axis."""
        kw: dict[str, Any] = {"newton_metres": _num(newton_metres, "newton_metres")}
        if axis is not None:
            kw["axis"] = _direction(axis)
        if center is not None:
            kw["center"] = list(_occ.vec(center))
        return self._add("torque", faces, at, radius, **kw)

    def pressure(self, faces, mpa: float, *, at=None, radius=None) -> "Study":
        """A pressure of ``mpa`` MPa (N/mm^2; 0.1 MPa = 1 bar) pushing into ``faces``."""
        return self._add("pressure", faces, at, radius, mpa=_num(mpa, "mpa"))

    def gravity(self, g: float = 1.0, direction="-z") -> "Study":
        """The part's own weight (density from its material) times ``g``; use g > 1 for acceleration
        (a robot arm swinging fast)."""
        self.loads.append({"type": "gravity", "g": _num(g, "g"), "direction": _direction(direction)})
        return self

    # ------------------------------------------------------------------ internals
    def _add(self, kind: str, faces, at, radius, **kw) -> "Study":
        label, shapes = self._faces(faces)
        if (at is None) != (radius is None):
            raise CadError(INVALID_ARGUMENT, f"{kind}(): give both at=(x, y, z) and radius=, or neither")
        if at is not None:
            if not _num(radius, "radius") > 0:
                raise CadError(INVALID_ARGUMENT, f"{kind}(): radius must be positive")
            kw["region"] = {"center": list(_occ.vec(at)), "radius": float(radius)}
        self.loads.append({"type": kind, "faces": label, "_shapes": shapes, **kw})
        return self

    def _faces(self, faces) -> tuple[str, list]:
        from .part import FeatureRef
        from .selection import FaceSelection

        p = self.part
        if isinstance(faces, str):
            return faces, p.faces(faces).shapes
        if isinstance(faces, FeatureRef):
            sel = faces.faces()
            return faces.id, sel.shapes
        if isinstance(faces, FaceSelection):
            if faces._part is not p:
                raise CadError(INVALID_ARGUMENT, f"those faces belong to part '{faces._part.name}', not '{p.name}'")
            if not faces:
                raise CadError(INVALID_ARGUMENT, f"empty face selection {faces.description}")
            return faces.description, faces.shapes
        raise CadError(INVALID_ARGUMENT, f"expected a reference name, FaceSelection or FeatureRef, got {type(faces).__name__}",
                       hint="e.g. study.fixed('base.bottom') or study.fixed(part.faces().facing('-z'))")

    def resolve(self, part_name: str) -> dict:
        """JSON spec with faces as indices into the part's final faces() order."""
        p = self.part
        faces = _occ.faces(p.shape)
        out = []
        for ld in self.loads:
            ld = dict(ld)
            shapes = ld.pop("_shapes", None)
            if shapes is not None:
                idx = [i for i, f in enumerate(faces) if any(f.IsSame(s) for s in shapes)]
                if len(idx) < len(shapes) and isinstance(ld["faces"], str) and ld["faces"] in p._refs:
                    shapes = p.faces(ld["faces"]).shapes  # a later feature rebuilt them: look the name up again
                    idx = [i for i, f in enumerate(faces) if any(f.IsSame(s) for s in shapes)]
                if not idx:
                    raise CadError(STUDY_FACE_LOST, f"study '{self.name}': the faces of {ld['type']}({ld['faces']!r}) are not on the "
                                   "finished part (a later feature replaced them)",
                                   hint="declare studies after the part's last feature, or use a reference name")
                ld["face_indices"] = idx
            out.append(ld)
        return {"name": self.name, "part": part_name, "target": self.target, "description": self.description, "loads": out}

    def __repr__(self) -> str:
        return f"<Study {self.name} on {self.part.name}: {', '.join(ld['type'] for ld in self.loads)}>"


def _num(v, what: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise CadError(INVALID_ARGUMENT, f"{what} must be a number, got {v!r}") from None
    if f != f or abs(f) == float("inf"):
        raise CadError(INVALID_ARGUMENT, f"{what} must be finite")
    return f
