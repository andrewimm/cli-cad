"""Metric fastener dimensions for 3D-printed parts (mm).

Sources: ISO 273 (medium clearance holes), ISO 4762 (socket head cap screws),
ISO 10642 (countersunk socket screws), ISO 4032 (hex nuts), and the common
heat-set insert sizes (e.g. Ruthex / CNC Kitchen "standard" inserts).  The
allowances added for printing (recess and pocket oversize) are the usual FDM
values; they are listed in ``ALLOWANCE`` so they are not magic numbers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .errors import INVALID_ARGUMENT, CadError


@dataclass(frozen=True)
class Fastener:
    size: str
    d: float              # nominal diameter
    pitch: float          # coarse thread pitch
    clearance: float      # ISO 273 medium clearance hole
    tap: float            # pilot hole for a screw cutting its own thread in plastic
    head_d: float         # socket head cap screw head diameter (ISO 4762 dk)
    head_h: float         # socket head height (k)
    csk_head_d: float     # countersunk head diameter (ISO 10642 dk, theoretical)
    nut_af: float         # hex nut width across flats (ISO 4032 s)
    nut_h: float          # hex nut height (m)
    insert_d: float       # heat-set insert hole diameter
    insert_len: float     # heat-set insert length

    def to_dict(self) -> dict:
        return asdict(self)


TABLE = {f.size: f for f in (
    Fastener("M2", 2.0, 0.40, 2.4, 1.7, 3.8, 2.0, 4.4, 4.0, 1.6, 3.2, 4.0),
    Fastener("M2.5", 2.5, 0.45, 2.9, 2.1, 4.5, 2.5, 5.5, 5.0, 2.0, 3.6, 5.7),
    Fastener("M3", 3.0, 0.50, 3.4, 2.5, 5.5, 3.0, 6.72, 5.5, 2.4, 4.0, 5.7),
    Fastener("M4", 4.0, 0.70, 4.5, 3.3, 7.0, 4.0, 8.96, 7.0, 3.2, 5.6, 8.1),
    Fastener("M5", 5.0, 0.80, 5.5, 4.2, 8.5, 5.0, 11.2, 8.0, 4.7, 6.4, 9.5),
    Fastener("M6", 6.0, 1.00, 6.6, 5.0, 10.0, 6.0, 13.44, 10.0, 5.2, 8.0, 12.7),
    Fastener("M8", 8.0, 1.25, 9.0, 6.8, 13.0, 8.0, 17.92, 13.0, 6.8, 9.7, 12.7),
)}

ALLOWANCE = {
    "counterbore_d": 1.0,   # head clearance in the counterbore (0.6 for M2 / M2.5)
    "counterbore_h": 0.2,   # head sits this far below the surface
    "countersink_d": 0.4,   # countersink a little wider than the head so it sits flush
    "nut_af": 0.3,          # hex pocket oversize so the nut presses in
    "nut_h": 0.3,
    "insert_extra_depth": 0.5,  # pocket deeper than the insert (melted plastic needs room)
    "insert_lead_in": 0.6,  # 90-degree chamfer at the pocket mouth, diameter oversize
}

KINDS = ("clearance", "counterbore", "countersunk", "tap", "insert", "nut")
STANDARD_LENGTHS = (3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 25, 30, 35, 40, 45, 50, 55, 60, 70, 80)


def lookup(size: str) -> Fastener:
    key = str(size).strip().upper().replace(" ", "")
    if not key.startswith("M"):
        key = "M" + key
    if key not in TABLE:
        raise CadError(INVALID_ARGUMENT, f"unknown screw size {size!r}", hint=f"use one of {', '.join(TABLE)}")
    return TABLE[key]


def screw_length(needed: float) -> int | None:
    """Shortest standard screw length >= ``needed``."""
    return next((L for L in STANDARD_LENGTHS if L >= needed - 1e-6), None)
