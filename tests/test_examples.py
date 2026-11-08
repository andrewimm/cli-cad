import pytest

from cad.cli import _examples_dir
from cad.runner import run_script

EXAMPLES = sorted(p.name for p in _examples_dir().glob("*.py"))


@pytest.mark.parametrize("name", EXAMPLES)
def test_example_builds_valid(name):
    out = run_script(_examples_dir() / name)
    for part in out.parts.values():
        part.assert_valid()
    assert not [w for w in out.warnings if w["code"] in ("CUT_NO_EFFECT", "DISCONNECTED_BODIES")]


def test_reference_recipes():
    from cad import Part, Profile

    p = Part("plate"); p.box(80, 50, 5, name="body")
    p.fillet(p.edges().vertical(), 4)
    p.chamfer(p.edges("body.top").exclude(p.edges().circular()), 0.5)
    p.assert_valid()

    p = Part("bracket")
    p.box(60, 40, 4, name="base")
    p.box(60, 4, 30, at=(0, 20, 4), align=("center", "max", "min"), name="wall")
    p.fillet(p.edges().concave(), 3)
    p.hole(5, at=(0, 20), direction="+y")
    rib = Profile.polygon([(0, 0), (20, 0), (0, 20)])
    p.assert_valid()
    assert len(p.holes()) == 1

    b = Part("box"); b.extrude(Profile.rounded_rect(90, 60, 5), 35, name="body")
    b.shell(2, open_faces=b.faces("body.top"))
    b.assert_valid()
    r = Part("rib"); r.extrude(rib, 3, plane="XZ", symmetric=True)
    assert r.bbox.size == pytest.approx((20, 3, 20))
