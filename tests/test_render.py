import json

import numpy as np
import pytest
from PIL import Image

from cad import Part, render
from cad.renderer import parse_view, _split_views


def _part():
    p = Part("cube")
    p.box(20, 20, 20, align="center")
    p.hole(8, at=(0, 0))
    return p


def test_standard_camera_axes():
    f = parse_view("front")
    assert list(f.right) == pytest.approx([1, 0, 0]) and list(f.up) == pytest.approx([0, 0, 1])
    t = parse_view("top")
    assert list(t.right) == pytest.approx([1, 0, 0]) and list(t.up) == pytest.approx([0, 1, 0])
    r = parse_view("right")
    assert list(r.right) == pytest.approx([0, 1, 0])
    b = parse_view("bottom")
    assert list(b.right) == pytest.approx([1, 0, 0]) and list(b.up) == pytest.approx([0, -1, 0])
    assert list(parse_view("az=90,el=0").eye) == pytest.approx([1, 0, 0])
    assert list(parse_view("dir=0,0,1").eye) == pytest.approx([0, 0, 1])


def test_split_views():
    assert _split_views("iso,front,az=30,el=20,dir=1,-1,1,top") == ["iso", "front", "az=30,el=20", "dir=1,-1,1", "top"]


def test_render_files_metadata_and_determinism(tmp_path):
    p = _part()
    res = render(p, ["iso", "top"], tmp_path / "a", size=(320, 240))
    res2 = render(p, ["iso", "top"], tmp_path / "b", size=(320, 240))
    assert [r["view"] for r in res] == ["iso", "top", "sheet"]
    for r1, r2 in zip(res[:2], res2[:2]):
        a = np.asarray(Image.open(r1["path"]))
        b = np.asarray(Image.open(r2["path"]))
        assert a.shape == (240, 320, 3)
        assert (a == b).all(), "renders must be deterministic"
        meta = json.loads(open(r1["metadata_path"]).read())
        assert meta["camera"]["projection"] == "orthographic"
        assert meta["model"]["bbox"]["size"] == pytest.approx([20, 20, 20])


def test_top_view_shows_through_hole(tmp_path):
    p = _part()
    (r, *_) = render(p, ["top"], tmp_path, size=(200, 200), annotate_images=False, sheet=False)
    img = np.asarray(Image.open(r["path"])).astype(int)
    centre = img[100, 100]
    assert (centre > 245).all(), "background must be visible through the hole"
    off = img[100, 60]
    assert (off < 240).any(), "material must be shaded"


def test_framing_scale(tmp_path):
    p = Part("bar")
    p.box(100, 10, 10)
    (r, *_) = render(p, ["front"], tmp_path, size=(400, 200), annotate_images=False, sheet=False)
    meta = json.loads(open(r["metadata_path"]).read())
    # 100 mm across 84% of 400 px
    assert meta["framing"]["mm_per_pixel"] == pytest.approx(100 / (400 * 0.84), rel=1e-3)


def test_section_view(tmp_path):
    p = Part("box")
    p.box(40, 30, 20, name="b")
    p.shell(2, open_faces=p.faces("b.top"))
    (r, *_) = render(p, ["front"], tmp_path, size=(200, 150), annotate_images=False, sheet=False, section="y=0")
    meta = json.loads(open(r["metadata_path"]).read())
    assert meta["section"]["kept_side"] == "+"   # front camera sits at -Y, so the -Y half is removed
    img = np.asarray(Image.open(r["path"])).astype(int)
    tinted = (img[..., 0].astype(int) - img[..., 2].astype(int)) > 25   # the part is blue-grey; cut faces lean red
    assert tinted.sum() > 200, "cut faces must be tinted"
    assert "section" in r["path"]
