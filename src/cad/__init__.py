"""cad — an agent-first parametric CAD library on Open CASCADE.

Quick start::

    from cad import Part, Profile, Parameter

    w = Parameter("plate.width", 60)
    part = Part("plate")
    part.box(w, 40, 4, name="base")
    part.hole_pattern(3.2, spacing=(w - 12, 28), count=(2, 2))
    part.fillet(part.edges().vertical(), radius=2)
    part.assert_valid()

See docs/REFERENCE.md for the full API and conventions.
"""

from .assembly import Assembly
from .errors import CadError, CadWarning
from .materials import Material
from .params import Parameter
from .paths import Path
from .part import BBox, Feature, FeatureRef, Part
from .profile import Plane, Profile
from .selection import EdgeSelection, FaceSelection

__version__ = "0.1.0"

__all__ = [
    "Assembly",
    "Path",
    "BBox",
    "CadError",
    "CadWarning",
    "EdgeSelection",
    "FaceSelection",
    "Feature",
    "FeatureRef",
    "Material",
    "Parameter",
    "Part",
    "Plane",
    "Profile",
    "render",
    "approx",
]


def render(model, views=("iso", "front", "right", "top"), out_dir="renders", **kwargs):
    """Render a Part (or list/dict of Parts) to PNGs.  See :func:`cad.renderer.render_views`."""
    from .renderer import render_views

    return render_views(model, views=views, out_dir=out_dir, **kwargs)


def approx(a: float, b: float, tol: float = 1e-6) -> bool:
    """``abs(a - b) <= tol`` — convenience for geometric assertions."""
    return abs(a - b) <= tol
