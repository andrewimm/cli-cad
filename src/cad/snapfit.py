"""Cantilever snap-fit design numbers.

For a rectangular cantilever of length L (to the hook), thickness t (in the bending
direction) and width b, deflected by the hook depth y:

    strain   e = 1.5 * t * y / L**2          (peak, at the root)
    force    P = b * t**2 * E * e / (6 * L)  (to deflect it, N with mm and MPa)

Allowable strains are conservative values for FDM prints that snap more than once
(printed parts are weaker than moulded ones, and much weaker across layers).
"""

from __future__ import annotations

import math

# material -> (flexural modulus E in MPa, allowable strain for repeated snapping)
PROPERTIES = {
    "PLA": (3500, 0.020),
    "PETG": (2000, 0.035),
    "ABS": (2200, 0.025),
    "ASA": (2000, 0.025),
    "PC": (2300, 0.040),
    "PA12": (1700, 0.060),
    "TPU": (30, 0.30),
}


def properties(material) -> tuple[str, float, float, bool]:
    """(name, E, allowable strain, assumed?) for a Material / name / None (assumes PLA)."""
    name = getattr(material, "name", material) or "PLA"
    key = str(name).upper()
    if key in PROPERTIES:
        return key, *PROPERTIES[key], False
    return "PLA", *PROPERTIES["PLA"], True


def analyse(length: float, thickness: float, width: float, catch: float, material=None, upright: bool = False) -> dict:
    """``upright``: the beam is printed along Z, bending across its layers (about half the strength),
    so the allowable strain is halved."""
    name, E, allow, assumed = properties(material)
    if upright:
        allow /= 2
    strain = 1.5 * thickness * catch / length ** 2
    force = width * thickness ** 2 * E * strain / (6 * length)
    min_length = math.sqrt(1.5 * thickness * catch / allow)
    return {"strain": round(strain, 5), "strain_pct": round(100 * strain, 2), "allowable_strain_pct": round(100 * allow, 2),
            "material": name, "material_assumed": assumed, "printed_upright": upright, "deflection_force_N": round(force, 2),
            "min_length_for_material": round(min_length, 2), "ok": strain <= allow}
