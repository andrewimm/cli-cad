"""Text as planar geometry (glyph outlines -> faces), for embossing and engraving.

``size`` is the height of capital letters in mm (an "H" is ``size`` tall), so
"5 mm letters" means the same thing whatever the font.  Fonts are looked up by
system font name (strictly: an unknown name is an error, never a silent
substitution) or given as a .ttf/.otf/.ttc file path.
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from .errors import INVALID_ARGUMENT, CadError

DEFAULT_FONTS = ("Helvetica", "Arial", "DejaVu Sans", "Liberation Sans", "Noto Sans")
HALIGN = ("left", "center", "right")
VALIGN = ("baseline", "bottom", "center", "top")


def _aspect(bold: bool, italic: bool):
    from OCP.Font import Font_FontAspect

    if bold and italic:
        return Font_FontAspect.Font_FontAspect_BoldItalic
    if bold:
        return Font_FontAspect.Font_FontAspect_Bold
    if italic:
        return Font_FontAspect.Font_FontAspect_Italic
    return Font_FontAspect.Font_FontAspect_Regular


def available_fonts() -> list[str]:
    from OCP.collections import Sequence_TCollection_HAsciiString
    from OCP.Font import Font_FontMgr

    seq = Sequence_TCollection_HAsciiString()
    Font_FontMgr.GetInstance_s().GetAvailableFontsNames(seq)
    return sorted({seq.Value(i).ToCString() for i in range(1, seq.Length() + 1)}, key=str.lower)


def resolve_font(font: str | None, bold: bool = False, italic: bool = False) -> tuple[str, str]:
    """(kind, value): ("path", file) or ("name", family).  Raises if the font does not exist."""
    from OCP.Font import Font_FontMgr, Font_StrictLevel
    from OCP.TCollection import TCollection_AsciiString

    if font and (font.lower().endswith((".ttf", ".otf", ".ttc")) or "/" in font):
        p = Path(font).expanduser()
        if not p.is_file():
            raise CadError(INVALID_ARGUMENT, f"font file {font!r} not found")
        return "path", str(p)
    mgr = Font_FontMgr.GetInstance_s()
    candidates = [font] if font else list(DEFAULT_FONTS)
    for name in candidates:
        found = mgr.FindFont(TCollection_AsciiString(name), Font_StrictLevel.Font_StrictLevel_Strict, _aspect(bold, italic), False)
        if found is not None:
            return "name", found.FontName().ToCString()
    style = " bold" if bold else ""
    style += " italic" if italic else ""
    fonts = available_fonts()
    if font:
        import difflib

        near = difflib.get_close_matches(font, fonts, n=5, cutoff=0.5)
        raise CadError(INVALID_ARGUMENT, f"font {font!r}{style} is not installed",
                       hint=(f"did you mean {', '.join(near)}? " if near else "") + "list fonts with `cad fonts`, or pass a .ttf/.otf path",
                       details={"available": fonts[:80]})
    raise CadError(INVALID_ARGUMENT, f"none of the default fonts {DEFAULT_FONTS}{style} are installed",
                   hint="pass font= with an installed font name (`cad fonts`) or a .ttf/.otf path", details={"available": fonts[:80]})


def _font(kind: str, value: str, em: float, bold: bool, italic: bool):
    from OCP.StdPrs import StdPrs_BRepFont
    from OCP.TCollection import TCollection_AsciiString

    f = StdPrs_BRepFont()
    ok = f.Init(TCollection_AsciiString(value), em, 0) if kind == "path" else \
        f.FindAndInit(TCollection_AsciiString(value), _aspect(bold, italic), em)
    if not ok:
        raise CadError(INVALID_ARGUMENT, f"could not load font {value!r}")
    return f


@lru_cache(maxsize=64)
def _cap_ratio(kind: str, value: str, bold: bool, italic: bool) -> float:
    """Height of 'H' for a font size of 1."""
    from . import _occ

    shape = _render(_font(kind, value, 100.0, bold, italic), "H")
    lo, hi = _occ.bbox(shape)
    h = hi[1] - lo[1]
    return h / 100.0 if h > 0 else 0.7


def _render(font, text: str):
    from OCP.gp import gp_Ax3
    from OCP.NCollection import NCollection_String
    from OCP.StdPrs import StdPrs_BRepTextBuilder

    return StdPrs_BRepTextBuilder().Perform(font, NCollection_String(text), gp_Ax3())


def text_shape(text: str, size: float, *, font: str | None = None, bold: bool = False, italic: bool = False,
               halign: str = "center", valign: str = "center", angle: float = 0.0):
    """Planar faces of ``text`` in the local XY plane; returns (shape, info)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

    from . import _occ

    if not isinstance(text, str) or not text.strip():
        raise CadError(INVALID_ARGUMENT, "text must be a non-empty string")
    if not isinstance(size, (int, float)) or size <= 0:
        raise CadError(INVALID_ARGUMENT, f"text size (capital letter height, mm) must be positive, got {size!r}")
    if halign not in HALIGN or valign not in VALIGN:
        raise CadError(INVALID_ARGUMENT, f"align must be (horizontal, vertical) with horizontal in {HALIGN} and vertical in {VALIGN}")
    kind, value = resolve_font(font, bold, italic)
    em = size / _cap_ratio(kind, value, bold, italic)
    shape = _render(_font(kind, value, em, bold, italic), text)
    faces = _occ.faces(shape)
    if not faces:
        raise CadError(INVALID_ARGUMENT, f"font {value!r} produced no outlines for {text!r}",
                       hint="the font may lack these characters; try another font")
    lo, hi = _occ.bbox(shape)
    dx = {"left": -lo[0], "center": -(lo[0] + hi[0]) / 2, "right": -hi[0]}[halign]
    dy = {"baseline": 0.0, "bottom": -lo[1], "center": -(lo[1] + hi[1]) / 2, "top": -hi[1]}[valign]
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, 0))
    if angle:
        r = gp_Trsf()
        r.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), math.radians(angle))
        t = r.Multiplied(t)
    shape = BRepBuilderAPI_Transform(shape, t, True).Shape()
    lo, hi = _occ.bbox(shape)
    return shape, {"font": value, "font_size": round(em, 4), "glyph_faces": len(faces),
                   "width": round(hi[0] - lo[0], 4), "height": round(hi[1] - lo[1], 4)}


@lru_cache(maxsize=64)
def _stem_ratio(kind: str, value: str, bold: bool, italic: bool) -> float:
    """Stroke width per unit of cap height, measured from the font's capital "I"."""
    from . import _occ

    f = _font(kind, value, 100.0, bold, italic)
    lo, hi = _occ.bbox(_render(f, "I"))
    w = hi[0] - lo[0]
    return w / (100.0 * _cap_ratio(kind, value, bold, italic)) if w > 0 else 0.1


def stroke_width(size: float, font: str | None = None, bold: bool = False, italic: bool = False) -> float:
    """Estimated stroke width (mm) of text with capital height ``size``.

    Uses the stem of the capital "I" (exact for sans fonts; serifs make it an
    overestimate) scaled by 0.85 for the thinner horizontal strokes of most fonts.
    Deliberately avoids 2D offsetting: OCCT's offset algorithm crashes on some glyph
    outlines (found while building this feature).
    """
    kind, value = resolve_font(font, bold, italic)
    return 0.85 * size * _stem_ratio(kind, value, bold, italic)
