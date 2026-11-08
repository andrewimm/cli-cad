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


def _materials(model):
    it = model.GetBaseMaterialGroups()
    groups = []
    while it.MoveNext():
        g = it.GetCurrentBaseMaterialGroup()
        ids = g.GetAllPropertyIDs()
        groups.append([(g.GetName(pid), g.GetDisplayColor(pid)) for pid in ids])
    return groups


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
    (mats,) = _materials(model)
    assert [n for n, _ in mats] == ["PETG", "TPU", "PLA"]
    pla = mats[2][1]
    assert (pla.Red, pla.Green, pla.Blue) == (0xE8, 0xA0, 0x50)
    # each object's default property points at its material slot
    by_name = {o.GetName(): o for o in objs}
    res = by_name["gasket"].GetObjectLevelProperty()
    assert res[0] and res[-1] > 0, res  # (has property, resource id, property id): TPU is not the first slot
    builds = model.GetBuildItems()
    n = 0
    while builds.MoveNext():
        n += 1
    assert n == 3


def test_multimaterial_mode_one_object_per_triangle_materials(tmp_path):
    parts = _parts()
    rep = export_3mf(parts, tmp_path / "m.3mf", mode="multimaterial", title="enclosure")
    w, model = _read(tmp_path / "m.3mf")
    (obj,) = _objects(model)
    assert obj.IsManifoldAndOriented()  # several closed shells in one mesh are still a closed, oriented mesh
    total = sum(o["triangles"] for o in rep["objects"])
    assert obj.GetTriangleCount() == total
    props = obj.GetAllTriangleProperties()
    used = {p.PropertyIDs[0] for p in props}
    assert len(used) == 3, "every material appears on its part's triangles"
    with zipfile.ZipFile(tmp_path / "m.3mf") as z:
        cfg = z.read("Metadata/Slic3r_PE_model.config").decode()
    assert cfg.count("<volume ") == 3 and 'key="extruder" value="2"' in cfg and 'value="gasket"' in cfg


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
