"""`cad slice` through Bambu Studio's CLI (skipped when Bambu Studio is not installed)."""
import json
from pathlib import Path

import pytest

from cad import CadError, Part
from cad.cli import main
from cad.slicer import find_bambu, slice_parts

pytestmark = pytest.mark.skipif(find_bambu() is None, reason="Bambu Studio not installed")


def test_slice_cube_reports_time_and_grams(tmp_path):
    p = Part("cube", material="PLA"); p.box(20, 20, 20)
    r = slice_parts({"cube": p}, title="cube", out_dir=tmp_path)
    assert Path(r["output"]).exists() and r["layers"] == 100
    assert 5 * 60 < r["time_s"] < 40 * 60
    # 20 mm cube at 15 % infill weighs a few grams of PLA (8 mL solid = 10 g); flattened presets give real density
    assert 2 < r["filament_g"] < 10 and r["filaments"][0]["preset"].startswith("Bambu PLA Basic")
    assert not r["warnings"]


def test_slice_multimaterial_grams_per_filament(tmp_path):
    c = Part("coaster", material="PLA"); c.cylinder(60, 4); c.cylinder(50, 1.6, at=(0, 0, 2.4), op="cut")
    i = Part("insert", material="TPU"); i.cylinder(50, 1.6, at=(0, 0, 2.4))
    r = slice_parts({"coaster": c, "insert": i}, title="coaster", out_dir=tmp_path, mode="multimaterial")
    g = {f["material"]: f["grams"] for f in r["filaments"]}
    assert set(g) == {"PLA", "TPU"} and all(v > 0.5 for v in g.values())
    assert r["filament_changes"] > 0


def test_overhang_needs_support(tmp_path):
    t = Part("tee", material="PLA"); t.box(10, 10, 20); t.box(60, 10, 4, at=(0, 0, 20))
    r = slice_parts({"tee": t}, title="tee", out_dir=tmp_path)
    assert [w["code"] for w in r["warnings"]] == ["NEEDS_SUPPORT"]
    r = slice_parts({"tee": t}, title="tee", out_dir=tmp_path, supports="auto")
    assert r["supports"]["used"] and not r["warnings"]


def test_errors_are_specific(tmp_path):
    p = Part("long", material="PLA"); p.box(250, 20, 5)
    with pytest.raises(CadError) as e:
        slice_parts({"long": p}, title="long", out_dir=tmp_path, printer="A1 mini")
    assert "does not fit" in e.value.message
    with pytest.raises(CadError) as e:
        slice_parts({"long": p}, title="long", out_dir=tmp_path, printer="X9")
    assert e.value.code == "NOT_FOUND"
    with pytest.raises(CadError) as e:
        slice_parts({"long": p}, title="long", out_dir=tmp_path, overrides={"no_such_key": "1"})
    assert "unknown slicer setting" in e.value.message
    s = Part("s", material="Steel"); s.box(10, 10, 10)
    with pytest.raises(CadError) as e:
        slice_parts({"s": s}, title="s", out_dir=tmp_path)
    assert "not an FDM filament" in e.value.message


def test_cli_slice_caches(tmp_path):
    main(["init"], tmp_path)
    (tmp_path / "model.py").write_text("from cad import Part\n\ndef build():\n    p = Part('b', material='PETG'); p.box(30, 20, 4)\n    return p\n")
    assert main(["build"], tmp_path)[0] == 0
    code, out, err = main(["slice", "--json"], tmp_path)
    r = json.loads(out)["result"]
    assert code == 0, err
    assert not r["cached"] and r["plate_type"] == "Textured PEI Plate" and Path(r["output"]).exists()
    r2 = json.loads(main(["slice", "--json"], tmp_path)[1])["result"]
    assert r2["cached"] and r2["time_s"] == r["time_s"]
    r3 = json.loads(main(["slice", "--set", "sparse_infill_density=60%", "--json"], tmp_path)[1])["result"]
    assert not r3["cached"] and r3["filament_g"] > r["filament_g"]


def test_find_bambu_prefers_explicit_and_env(tmp_path, monkeypatch):
    fake = tmp_path / "bambu-studio"
    fake.write_text("#!/bin/sh\n"); fake.chmod(0o755)
    assert find_bambu(str(fake)) == fake
    monkeypatch.setenv("CAD_BAMBU_STUDIO", str(fake))
    assert find_bambu() == fake
