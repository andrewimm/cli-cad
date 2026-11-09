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


def _config_extruders(cfg: str, tag: str) -> dict:
    """{name: extruder} for each <tag> block of a Bambu / PrusaSlicer model config."""
    import re
    out = {}
    for block in cfg.split(f"<{tag} ")[1:]:
        block = block.split(f"</{tag}>")[0]
        name = re.search(r'key="name" value="([^"]*)"', block).group(1)
        out[name] = re.search(r'key="extruder" value="(\d+)"', block).group(1)
    return out


def test_objects_mode_states_extruders_for_every_slicer(tmp_path):
    # Bambu Studio reads the colour group; OrcaSlicer, PrusaSlicer and Cura need their own metadata
    export_3mf(_parts(), tmp_path / "a.3mf")
    want = {"housing": "1", "gasket": "2", "inlay": "3"}
    with zipfile.ZipFile(tmp_path / "a.3mf") as z:
        bambu = z.read("Metadata/model_settings.config").decode()
        prusa = z.read("Metadata/Slic3r_PE_model.config").decode()
    assert _config_extruders(bambu, "object") == want
    assert _config_extruders(prusa, "object") == want
    w, model = _read(tmp_path / "a.3mf")
    cura = {o.GetName(): _material_meta(o)["extruder_nr"] for o in _objects(model)}   # 0-based
    assert cura == {"housing": "0", "gasket": "1", "inlay": "2"}


def test_multimaterial_for_prusa_is_one_object_with_volumes(tmp_path):
    parts = _parts()
    rep = export_3mf(parts, tmp_path / "p.3mf", mode="multimaterial", title="enclosure", target="prusa")
    assert rep["target"] == "prusa"
    w, model = _read(tmp_path / "p.3mf")
    (obj,) = _objects(model)
    assert obj.GetName() == "enclosure" and obj.IsManifoldAndOriented()
    with zipfile.ZipFile(tmp_path / "p.3mf") as z:
        names = z.namelist()
        cfg = z.read("Metadata/Slic3r_PE_model.config").decode()
    assert "Metadata/model_settings.config" not in names   # Bambu's parts would name objects that are not there
    assert _config_extruders(cfg, "volume") == {"housing": "1", "gasket": "2", "inlay": "3"}
    # the volumes' triangle ranges tile the mesh, in order, one per part with that part's triangle count
    import re
    ranges = [(int(a), int(b)) for a, b in re.findall(r'<volume firstid="(\d+)" lastid="(\d+)"', cfg)]
    counts = [o["triangles"] for o in rep["objects"]]
    assert ranges[0][0] == 0 and ranges[-1][1] == obj.GetTriangleCount() - 1
    assert [b - a + 1 for a, b in ranges] == counts
    assert all(ranges[i + 1][0] == ranges[i][1] + 1 for i in range(len(ranges) - 1))
    with pytest.raises(CadError):
        export_3mf(parts, tmp_path / "x.3mf", target="simplify3d")


def _footprints(model):
    out = {}
    for o in _objects(model):
        v = [p.Coordinates[0:3] for p in o.GetVertices()]
        xs, ys, zs = zip(*v)
        out[o.GetName()] = ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
    return out


def test_objects_mode_lays_out_parts_whose_footprints_collide(tmp_path):
    from cad.threemf import footprint_conflicts

    # the gasket and inlay sit inside the housing's footprint: printed as separate objects they would collide
    rep = export_3mf(_parts(), tmp_path / "a.3mf")
    assert rep["arranged"] and "housing/gasket" in rep["arranged"]["reason"]
    w, model = _read(tmp_path / "a.3mf")
    boxes = _footprints(model)
    assert not footprint_conflicts(boxes, min_gap=4.9)          # 5 mm apart
    assert all(abs(lo[2]) < 1e-6 for lo, _ in boxes.values())    # each on the bed
    sizes = {n: [round(h - l, 3) for l, h in zip(lo, hi)] for n, (lo, hi) in boxes.items()}
    assert sizes["housing"] == [60.0, 40.0, 20.0]                # moved, not changed
    # parts already apart keep their modelled positions
    box = Part("box", material="PLA"); box.box(40, 40, 20)
    lid = Part("lid", material="PLA"); lid.box(40, 40, 3, at=(60, 0, 0))
    rep = export_3mf({"box": box, "lid": lid}, tmp_path / "b.3mf")
    assert rep["arranged"] is None
    w, model = _read(tmp_path / "b.3mf")
    assert round(_footprints(model)["lid"][0][0], 3) == 40.0
    # multimaterial mode keeps the assembly together
    assert export_3mf(_parts(), tmp_path / "m.3mf", mode="multimaterial")["arranged"] is None


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
