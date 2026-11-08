"""Section (cut-away) views: cut a shape with an axis-aligned plane for rendering.

Spec strings: ``"y=0"`` (remove the half facing the camera), ``"y=0:+"`` (keep
the +Y side), ``"y=0:-"`` (keep the -Y side).  Capping faces created by the cut
are reported so the renderer can colour them.
"""

from __future__ import annotations

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt

from . import _occ
from .errors import INVALID_ARGUMENT, CadError

SECTION_COLOR = (0.86, 0.38, 0.30)


def parse_section(spec: str) -> tuple[int, float, int | None]:
    s = spec.strip().lower().replace(" ", "")
    side = None
    if ":" in s:
        s, sd = s.split(":", 1)
        if sd not in ("+", "-"):
            raise CadError(INVALID_ARGUMENT, f"section side must be '+' or '-', got {sd!r}")
        side = 1 if sd == "+" else -1
    if "=" not in s or s[0] not in "xyz":
        raise CadError(INVALID_ARGUMENT, f"cannot parse section {spec!r}", hint="use e.g. 'y=0', 'x=12.5:+' or 'z=10:-'")
    try:
        value = float(s.split("=", 1)[1])
    except ValueError as e:
        raise CadError(INVALID_ARGUMENT, f"cannot parse section value in {spec!r}") from e
    return "xyz".index(s[0]), value, side


def keep_sign(axis: int, side: int | None, eye) -> int:
    """Which side to keep: explicit, or the side away from the camera."""
    if side is not None:
        return side
    return -1 if eye[axis] > 1e-9 else 1 if eye[axis] < -1e-9 else -1


def cut_shape(shape, axis: int, value: float, keep: int):
    """Keep the half-space ``keep * (coord - value) >= 0``; returns (shape, cap_face_indices) or (None, [])."""
    lo, hi = _occ.bbox(shape, optimal=False)
    pad = 1.0 + 0.1 * max(h - l for l, h in zip(lo, hi))
    a = [l - pad for l in lo]
    b = [h + pad for h in hi]
    if keep > 0:
        a[axis] = value
    else:
        b[axis] = value
    if b[axis] <= a[axis]:
        return None, []
    box = BRepPrimAPI_MakeBox(gp_Pnt(*a), gp_Pnt(*b)).Shape()
    op = BRepAlgoAPI_Common(shape, box)
    if not op.IsDone():
        raise CadError("OPERATION_FAILED", "section cut failed")
    res = op.Shape()
    if not _occ.solids(res):
        return None, []
    caps = []
    for i, f in enumerate(_occ.faces(res)):
        if _occ.surface_type(f) != "plane":
            continue
        n = _occ.face_normal(f)
        if abs(abs(n[axis]) - 1) < 1e-6 and abs(_occ.face_centroid(f)[axis] - value) < 1e-6:
            caps.append(i)
    return res, caps
