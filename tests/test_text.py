"""Text: profiles, emboss and engrave on faces, orientation, fonts, warnings."""
import json

import pytest
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.gp import gp_Pnt
from OCP.TopAbs import TopAbs_IN

from cad import CadError, Part, Plane, Profile
from cad.cli import main


def inside(part, p):
    return BRepClass3d_SolidClassifier(part.shape, gp_Pnt(*p), 1e-6).State() == TopAbs_IN


def test_profile_text_size_is_cap_height():
    h = Profile.text("H", 10, align=("center", "center"))
    assert h.description["height"] == pytest.approx(10, abs=0.02)
    t = Profile.text("SN 042", 5)
    assert t.description["glyph_faces"] == 5 and t.area > 0


def _installed_default_font() -> str:
    from cad.text import DEFAULT_FONTS, available_fonts

    have = available_fonts()
    return next(f for f in DEFAULT_FONTS if any(f in x for x in have))


def test_unknown_font_is_an_error_not_a_substitution():
    font = _installed_default_font()  # Helvetica on macOS, DejaVu Sans on most Linux
    with pytest.raises(CadError) as e:
        Profile.text("x", 5, font=font[:-1] + "q")  # a near miss
    assert font in e.value.hint


def test_engrave_removes_text_volume():
    p = Part("plate"); p.box(60, 30, 4, name="body")
    v0 = p.volume
    label = Profile.text("SN 042", 6)
    f = p.engrave("SN 042", on=p.faces("body.top"), size=6, depth=0.6)
    assert not f.warnings and p.solid_count == 1 and p.is_valid()
    assert v0 - p.volume == pytest.approx(label.area * 0.6, rel=0.01)
    assert "engrave1.floor" in p.references()


def test_emboss_adds_text_volume_and_stays_one_solid():
    p = Part("plate"); p.box(60, 30, 4, name="body")
    v0 = p.volume
    label = Profile.text("CAD", 8, bold=True)
    p.emboss("CAD", on=p.faces("body.top"), size=8, height=0.8, bold=True)
    assert p.solid_count == 1 and p.is_valid()
    assert p.volume - v0 == pytest.approx(label.area * 0.8, rel=0.01)
    assert p.bbox.max[2] == pytest.approx(4.8, abs=1e-6)


@pytest.mark.parametrize("face,normal_axis,sign,right,up", [
    ("top", 2, +1, (1, 0, 0), (0, 1, 0)),      # seen from above: reads along +X, letters point +Y
    ("front", 1, -1, (1, 0, 0), (0, 0, 1)),    # seen from the front (-Y): reads along +X, upright
    ("back", 1, +1, (-1, 0, 0), (0, 0, 1)),    # seen from behind: reads along -X, upright
    ("right", 0, +1, (0, 1, 0), (0, 0, 1)),    # seen from +X: reads along +Y, upright
])
def test_text_reads_correctly_on_each_face(face, normal_axis, sign, right, up):
    """An embossed 'L': its stem is on the reader's left, its foot at the bottom."""
    p = Part("block"); p.box(40, 40, 40, align="center", name="b")
    f = p.emboss("L", on=p.faces(f"b.{face}"), size=20, height=1.0)
    assert not f.warnings
    stroke = f.feature.metrics["text"]["stroke_mm"] / 0.85
    w = f.feature.metrics["text"]["width"]
    out = [0.0, 0.0, 0.0]
    out[normal_axis] = sign * 20.5  # half a millimetre above the face, inside the raised letter
    def at(r, u):
        return tuple(o + r * a + u * b for o, a, b in zip(out, right, up))
    left, bottom = -w / 2 + stroke / 2, -10 + stroke / 2
    assert inside(p, at(left, 6)), "stem on the left, upper half"
    assert inside(p, at(w / 2 - stroke / 2, bottom)), "foot reaches the right at the bottom"
    assert not inside(p, at(w / 2 - stroke / 2, 6)), "nothing at the top right of an L"


def test_text_on_split_coplanar_face_and_warnings():
    p = Part("plate"); p.box(60, 30, 4, name="body")
    p.engrave("SN 042", on=p.faces("body.top"), size=6, depth=0.6)
    assert len(p.faces("body.top")) > 1  # islands inside engraved letters
    f = p.emboss("OK", on=p.faces("body.top"), size=4, height=0.4, at=(0, 9))
    assert p.solid_count == 1 and not any(w.code == "TEXT_OFF_FACE" for w in f.warnings)
    g = p.emboss("FAR TOO LONG FOR THIS PLATE", on=p.faces("body.top"), size=5, height=0.4, at=(0, -9))
    assert any(w.code == "TEXT_OFF_FACE" for w in g.warnings)
    q = Part("q"); q.box(20, 20, 2, name="b")
    h = q.engrave("ab", on=q.faces("b.top"), size=1.5, depth=0.2)
    assert any(w.code == "TEXT_STROKES_THIN" for w in h.warnings)
    with pytest.raises(CadError):
        q.engrave("x", on=q.faces("b"), size=3)  # six faces in different planes


def test_plane_from_face_and_text_as_separate_part():
    base = Part("base", material="PETG"); base.box(50, 30, 3, name="body")
    label = Part("label", material=Material_PLA())
    label.extrude(Profile.text("PLA", 8), 0.6, plane=Plane.from_face(base.faces("body.top")))
    assert label.bbox.min[2] == pytest.approx(3) and base.distance_to(label) < 1e-6 and base.interference(label) < 1e-6


def Material_PLA():
    from cad import Material

    return Material("PLA", color="#e8a050")


def test_cli_fonts(tmp_path):
    font = _installed_default_font()
    code, out, _ = main(["fonts", font[:5].lower(), "--json"], tmp_path)
    r = json.loads(out)["result"]
    assert code == 0 and any(font in f for f in r["fonts"])
