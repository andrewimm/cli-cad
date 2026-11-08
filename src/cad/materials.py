"""Materials: what a part is made of (density for mass, colour for renders and 3MF, stiffness and
strength for stress analysis).

    Part("lid", material="PETG")                       # built-in, by name (case-insensitive)
    Part("seal", material=Material("TPU", color="#202020"))   # built-in with a different colour
    Part("insert", material=Material("Brass-filled PLA", density=3.5, color="#b08d57"))  # custom

A Part's material drives ``part.mass()`` (grams), its default render colour and the
material slots written to 3MF files, so a multi-material print keeps one material per body.

Mechanical properties (used by ``cad fea``) are for parts as printed at 100 % infill, loaded
along the layers: ``youngs_modulus`` and ``yield_strength`` in MPa, ``layer_strength`` in MPa for
pulling the layers apart (None for isotropic materials: metals, resin).  They are conservative
typical values; a real filament can differ by 30 % or more.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from .errors import INVALID_ARGUMENT, CadError


@dataclass(frozen=True)
class Material:
    name: str
    density: float | None = None  # g/cm^3
    color: str | None = None  # "#rrggbb"
    kind: str = "custom"  # filament | resin | metal | custom
    notes: str = ""
    youngs_modulus: float | None = None  # MPa
    poisson_ratio: float | None = None
    yield_strength: float | None = None  # MPa (tensile strength for brittle plastics), in-plane as printed
    layer_strength: float | None = None  # MPa across printed layers; None = isotropic

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise CadError(INVALID_ARGUMENT, "a material needs a non-empty name")
        # unspecified properties come from the built-in material of the same name
        base = LIBRARY.get(self.name.strip().lower()) if "LIBRARY" in globals() else None
        if base is not None:
            for f in ("density", "color", "youngs_modulus", "poisson_ratio", "yield_strength", "layer_strength"):
                if getattr(self, f) is None:
                    object.__setattr__(self, f, getattr(base, f))
            if self.kind == "custom":
                object.__setattr__(self, "kind", base.kind)
            if not self.notes:
                object.__setattr__(self, "notes", base.notes)
        if self.density is not None and not self.density > 0:
            raise CadError(INVALID_ARGUMENT, f"material density must be positive (g/cm^3), got {self.density!r}")
        if self.color is not None:
            c = self.color.strip()
            if not (c.startswith("#") and len(c) == 7 and all(ch in "0123456789abcdefABCDEF" for ch in c[1:])):
                raise CadError(INVALID_ARGUMENT, f"material colour must look like '#rrggbb', got {self.color!r}")
        for f in ("youngs_modulus", "yield_strength", "layer_strength"):
            v = getattr(self, f)
            if v is not None and not v > 0:
                raise CadError(INVALID_ARGUMENT, f"material {f} must be positive (MPa), got {v!r}")
        if self.poisson_ratio is not None and not 0 <= self.poisson_ratio < 0.5:
            raise CadError(INVALID_ARGUMENT, f"poisson_ratio must be in [0, 0.5), got {self.poisson_ratio!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    def with_color(self, color: str) -> "Material":
        return replace(self, color=color)


_BUILTIN = [
    # name, density, colour, kind, notes, E (MPa), Poisson, yield/strength (MPa), across layers (MPa)
    Material("PLA", 1.24, "#3b82c4", "filament", "easy to print; brittle; softens ~55 C", 3500, 0.36, 45, 25),
    Material("PETG", 1.27, "#2f9e8f", "filament", "tougher than PLA; good layer adhesion; ~75 C", 2000, 0.38, 40, 28),
    Material("ABS", 1.04, "#d9d4c7", "filament", "heat resistant ~95 C; needs an enclosure", 2100, 0.35, 33, 20),
    Material("ASA", 1.07, "#e8e4da", "filament", "like ABS, UV resistant", 2000, 0.35, 35, 22),
    Material("TPU", 1.21, "#2b2b2b", "filament", "flexible (Shore ~95A); seals, feet, gaskets", 26, 0.45, 8, 6),
    Material("PA12", 1.01, "#f2f2ee", "filament", "nylon; tough, wear resistant, hygroscopic", 1700, 0.39, 45, 30),
    Material("PC", 1.20, "#c9d6df", "filament", "polycarbonate; strong, heat resistant ~110 C", 2300, 0.37, 55, 35),
    Material("Resin", 1.15, "#b8bcc2", "resin", "standard photopolymer (SLA/MSLA)", 2500, 0.38, 45, None),
    Material("Aluminium", 2.70, "#b9bec4", "metal", "6061-T6 typical", 69000, 0.33, 276, None),
    Material("Steel", 7.85, "#8c9399", "metal", "carbon steel", 200000, 0.29, 250, None),
    Material("Brass", 8.50, "#c9a227", "metal", "", 100000, 0.34, 150, None),
]
LIBRARY: dict[str, Material] = {m.name.lower(): m for m in _BUILTIN}
LIBRARY["aluminum"] = LIBRARY["aluminium"]
LIBRARY["nylon"] = LIBRARY["pa12"]


def resolve(material) -> Material | None:
    """Material, name of a built-in, or None."""
    if material is None or isinstance(material, Material):
        return material
    if isinstance(material, str):
        m = LIBRARY.get(material.strip().lower())
        if m is None:
            import difflib

            near = difflib.get_close_matches(material.lower(), list(LIBRARY), n=3)
            raise CadError(INVALID_ARGUMENT, f"unknown material {material!r}",
                           hint=(f"did you mean {', '.join(near)}? " if near else "")
                           + "built-ins: " + ", ".join(m.name for m in _BUILTIN)
                           + "; or define one: Material('name', density=1.2, color='#rrggbb')")
        return m
    raise CadError(INVALID_ARGUMENT, f"material must be a Material or a name, got {type(material).__name__}")


def library() -> list[dict]:
    return [m.to_dict() for m in _BUILTIN]
