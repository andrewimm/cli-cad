import json
from pathlib import Path

import pytest

from cad.cli import main
from cad.engine import Engine


def run(args, cwd, engine=None):
    code, out, err = main(args, cwd, engine)
    return code, out, err


def j(args, cwd, engine=None):
    code, out, err = main(args + ["--json"], cwd, engine)
    return code, json.loads(out)


@pytest.fixture
def project(tmp_path):
    code, out, err = run(["examples", "copy", "mounting_bracket", "proj"], tmp_path)
    assert code == 0, err
    return tmp_path / "proj"


def test_build_cache_and_revisions(project):
    e = Engine()
    c, r = j(["build"], project, e)
    assert c == 0 and r["result"]["revision"] == 1 and not r["result"]["cached"]
    c, r = j(["build"], project, e)
    assert r["result"]["cached"] and r["result"]["revision"] == 1
    c, r = j(["set", "wall_height", "45"], project, e)
    assert c == 0 and r["result"]["build"]["revision"] == 2
    assert r["result"]["build"]["parts"]["bracket"]["bbox_size"][2] == pytest.approx(49)
    assert "wall_height" in (project / "params.toml").read_text()
    c, r = j(["unset", "wall_height"], project, e)
    assert r["result"]["build"]["revision"] == 1 and r["result"]["build"]["cached"]


def test_failed_build_preserves_head(project):
    e = Engine()
    j(["build"], project, e)
    model = project / "model.py"
    good = model.read_text()
    model.write_text(good.replace("radius=3", "radius=300"))
    c, r = j(["build"], project, e)
    assert c == 3 and not r["ok"]
    assert r["error"]["code"] == "FILLET_FAILED"
    assert r["error"]["feature"] == "corner_fillets"
    assert r["error"]["details"]["location"]["line"] > 0
    c, r = j(["inspect"], project, e)
    assert c == 0 and r["result"]["revision"] == 1
    c, r = j(["revisions"], project, e)
    assert r["result"]["last_build"]["status"] == "failed"


def test_unknown_parameter_rejected(project):
    j(["build"], project)
    c, r = j(["set", "wal_height", "45"], project)
    assert c == 2 and r["error"]["code"] == "UNKNOWN_PARAMETER"
    assert "wall_height" in r["error"]["hint"]


def test_render_cache_and_query_measure(project):
    e = Engine()
    j(["build"], project, e)
    c, r = j(["render", "--views", "iso,top", "--size", "320x240"], project, e)
    assert c == 0 and all(not i["cached"] for i in r["result"]["images"])
    assert Path(r["result"]["sheet"]).exists()
    c, r = j(["render", "--views", "iso,top,front", "--size", "320x240"], project, e)
    cached = [i["cached"] for i in r["result"]["images"]]
    assert cached == [True, True, False]
    # a fresh engine (new process) still hits the persistent cache
    c, r = j(["render", "--views", "iso", "--size", "320x240"], project, Engine())
    assert r["result"]["images"][0]["cached"]
    c, r = j(["measure", "bracket.mounting_surface"], project, e)
    assert r["result"]["count"] == 1 and r["result"]["entities"][0]["normal"] == [0, 0, -1]
    c, r = j(["query", "faces().holes()"], project, e)
    assert r["result"]["count"] == 5
    c, r = j(["measure", "--holes"], project, e)
    assert len(r["result"]["holes"]) == 5
    assert e.session(project).stats.get("builds_run") == 1


def test_query_does_not_rerun_script(project):
    e = Engine()
    j(["build"], project, e)
    (project / "model.py").write_text("raise RuntimeError('must not run')\n")
    c, r = j(["inspect"], project, Engine())  # new session loads from disk
    assert c == 0 and r["result"]["parts"]["bracket"]["valid"]


def test_checkout_diff_restore_export(project):
    e = Engine()
    j(["build"], project, e)
    j(["set", "width", "80"], project, e)
    c, r = j(["diff", "1", "2"], project, e)
    assert r["result"]["parameters"]["width"] == {"a": 60, "b": 80}
    assert r["result"]["parts"]["bracket"]["geometry_changed"]
    c, r = j(["checkout", "1"], project, e)
    assert r["result"]["head"] == 1
    assert "80" in (project / "params.toml").read_text(), "checkout must not touch sources"
    c, r = j(["export", "--format", "step,stl"], project, e)
    assert {f["format"] for f in r["result"]["files"]} == {"step", "stl"}
    assert all(Path(f["path"]).stat().st_size > 1000 for f in r["result"]["files"])
    (project / "model.py").write_text("# edited\n" + (project / "model.py").read_text())
    c, r = j(["restore", "1"], project, e)
    assert c == 2 or r["error"]["code"] == "INVALID_ARGUMENT"
    c, r = j(["restore", "1", "--force"], project, e)
    assert c == 0 and "model.py" in r["result"]["restored"]
    assert not (project / "model.py").read_text().startswith("# edited")


def test_discovery_commands(tmp_path):
    c, r = j(["capabilities"], tmp_path)
    assert c == 0 and "render" in r["result"]["commands"] and r["result"]["units"]["length"] == "mm"
    c, r = j(["help", "render"], tmp_path)
    assert any(a["name"] == "--views" for a in r["result"]["arguments"])
    c, r = j(["schema", "envelope"], tmp_path)
    assert c == 0
    c, r = j(["examples", "list"], tmp_path)
    assert {"mounting_bracket", "enclosure"} <= {x["name"] for x in r["result"]["examples"]}
    c, out, _ = run(["docs"], tmp_path)
    assert "Part" in out


def test_usage_errors(tmp_path):
    c, r = j(["render", "--bogus"], tmp_path)
    assert c == 2 and r["error"]["code"] == "USAGE"
    c, r = j(["inspect"], tmp_path)
    assert c == 5 and r["error"]["code"] == "NO_PROJECT"


def test_open_current_project(project, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    c, r = j(["open", str(project)], other)
    assert c == 0
    j(["build"], other)
    c, r = j(["inspect"], other)
    assert c == 0 and r["result"]["project"] == "mounting_bracket"


def test_run_standalone(tmp_path):
    from cad.cli import _examples_dir

    c, r = j(["run", str(_examples_dir() / "plate_with_holes.py"), "--render", "iso", "--export", "step", "--out", "o", "--size", "200x150"], tmp_path)
    assert c == 0, r
    assert (tmp_path / "o" / "plate.step").exists()
    assert (tmp_path / "o" / "plate_with_holes_iso.png").exists()
