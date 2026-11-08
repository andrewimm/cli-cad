"""3MF export with materials, verified with lib3mf (the 3MF Consortium's reference implementation)."""
import zipfile

import pytest

from cad import CadError, Material, Part, Profile
from cad.threemf import export_3mf

lib3mf = pytest.importorskip("lib3mf")


def _parts():
    body = Part("housing", material="PETG")
    body.extrude(Profile.rounded_rect(60, 40, 5), 20, name="shell")
    body.shell(2, open_faces=body.faces("shell.top"))
    seal = Part("gasket", material="TPU")
    seal.extrude(Profile.rounded_rect(56, 36, 3) - Profile.rounded_rect(52, 32, 1), 1.5, offset=20)
    inlay = Part("inlay", material=Material("PLA", color="#e8a050"))
    inlay.box(20, 1, 0.6, at=(0, -20, 8), align=("center", "max", "center"))
    return {"housing": body, "gasket": seal, "inlay": inlay}


def _read(path):
    w = lib3mf.get_wrapper()
    model = w.CreateModel()
    model.QueryReader("3mf").ReadFromFile(str(path))
    return w, model


def _objects(model):
    it = model.GetMeshObjects()
    out = []
    while it.MoveNext():
        out.append(it.GetCurrentMeshObject())
    return out


def _colors(model):
    it = model.GetColorGroups()
    groups = []
    while it.MoveNext():
        g = it.GetCurrentColorGroup()
        groups.append([g.GetColor(pid) for pid in g.GetAllPropertyIDs()])
    return groups


def _material_meta(obj):
    mdg = obj.GetMetaDataGroup()
    return {mdg.GetMetaData(k).GetName(): mdg.GetMetaData(k).GetValue() for k in range(mdg.GetMetaDataCount())}


def test_objects_mode_reads_back_with_materials(tmp_path):
    parts = _parts()
    rep = export_3mf(parts, tmp_path / "a.3mf", title="enclosure")
    assert [m["name"] for m in rep["materials"]] == ["PETG", "TPU", "PLA"]
    codes = [w["code"] for w in rep["warnings"]]
    assert "PARTS_OVERLAP" not in codes and "CONSIDER_MULTIMATERIAL" in codes  # touching parts in different materials
    w, model = _read(tmp_path / "a.3mf")
    assert model.GetUnit() == lib3mf.ModelUnit.MilliMeter
    objs = _objects(model)
    assert sorted(o.GetName() for o in objs) == ["gasket", "housing", "inlay"]
    for o in objs:
        assert o.IsManifoldAndOriented(), o.GetName()
        assert o.GetTriangleCount() > 0
    (colors,) = _colors(model)
    pla = colors[2]
    assert (pla.Red, pla.Green, pla.Blue) == (0xE8, 0xA0, 0x50)
    by_name = {o.GetName(): o for o in objs}
    assert {n: _material_meta(o)["material"] for n, o in by_name.items()} == {"housing": "PETG", "gasket": "TPU", "inlay": "PLA"}
    _, pid_tpu, has = by_name["gasket"].GetObjectLevelProperty()  # (resource id, property id, has property)
    _, pid_petg, _ = by_name["housing"].GetObjectLevelProperty()
    assert has and pid_tpu != pid_petg  # each object points at its material's colour
    builds = model.GetBuildItems()
    n = 0
    while builds.MoveNext():
        n += 1
    assert n == 3


def test_multimaterial_mode_assembly_with_part_filaments(tmp_path):
    parts = _parts()
    export_3mf(parts, tmp_path / "m.3mf", mode="multimaterial", title="enclosure")
    w, model = _read(tmp_path / "m.3mf")
    objs = _objects(model)
    assert sorted(o.GetName() for o in objs) == ["gasket", "housing", "inlay"]
    assert all(o.IsManifoldAndOriented() for o in objs)
    builds = model.GetBuildItems()
    items = []
    while builds.MoveNext():
        items.append(builds.GetCurrent().GetObjectResource())
    assert len(items) == 1 and not items[0].IsMeshObject(), "one assembly build item"
    with zipfile.ZipFile(tmp_path / "m.3mf") as z:
        cfg = z.read("Metadata/model_settings.config").decode()
    assert cfg.count("<part ") == 3 and 'value="gasket"' in cfg and '<metadata key="extruder" value="2"/>' in cfg


def test_overlap_warning_and_single_part(tmp_path):
    a = Part("a", material="PLA"); a.box(10, 10, 10)
    b = Part("b", material="TPU"); b.box(10, 10, 10, at=(5, 0, 0))
    rep = export_3mf({"a": a, "b": b}, tmp_path / "o.3mf", mode="multimaterial")
    assert rep["warnings"][0]["code"] == "MATERIAL_OVERLAP"
    path = a.export(str(tmp_path / "single.3mf"))
    w, model = _read(path)
    assert len(_objects(model)) == 1


def test_material_api():
    p = Part("p", material="petg")
    p.box(10, 10, 10)
    assert p.material.name == "PETG" and p.mass() == pytest.approx(1.27)
    assert Part("q", material=Material("TPU", color="#ff0000")).material.density == pytest.approx(1.21)
    with pytest.raises(CadError) as e:
        Part("x", material="PTEG")
    assert "PETG" in e.value.hint
    with pytest.raises(CadError):
        Part("y").mass()
    with pytest.raises(CadError):
        Material("bad", color="red")
