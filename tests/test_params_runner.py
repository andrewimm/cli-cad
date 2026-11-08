import pytest

from cad import CadError, Parameter
from cad.params import parameter_overrides
from cad.runner import run_script


def test_parameter_defaults_and_overrides():
    assert Parameter("x", 5) == 5
    with parameter_overrides({"x": "7.5", "n": "3", "flag": "true"}) as ctx:
        assert Parameter("x", 5.0) == 7.5
        assert Parameter("n", 2) == 3 and isinstance(Parameter("n", 2), int)
        assert Parameter("flag", False) is True
    assert ctx.declared["x"].overridden


def test_parameter_range():
    with parameter_overrides({"x": 99}):
        with pytest.raises(CadError) as e:
            Parameter("x", 5, max=10)
    assert e.value.code == "PARAMETER_OUT_OF_RANGE"


def test_run_script_build_function(tmp_path):
    s = tmp_path / "m.py"
    s.write_text("from cad import *\nw = Parameter('w', 10)\ndef build():\n    p = Part('a'); p.box(w, 5, 5); print('hi'); return p\n")
    out = run_script(s, {"w": 20})
    assert out.parts["a"].bbox.width == pytest.approx(20)
    assert out.stdout == "hi\n"


def test_run_script_module_level_parts(tmp_path):
    s = tmp_path / "m.py"
    s.write_text("from cad import *\na = Part('a'); a.box(1,1,1)\nb = Part('b'); b.box(2,2,2)\n_empty = Part('e')\n")
    assert list(run_script(s).parts) == ["a", "b"]


def test_run_script_error_location(tmp_path):
    s = tmp_path / "m.py"
    s.write_text("from cad import *\np = Part('a')\np.box(10,10,10)\np.fillet(p.edges().vertical(), 30)\n")
    with pytest.raises(CadError) as e:
        run_script(s)
    assert e.value.code == "FILLET_FAILED"
    assert e.value.details["location"]["line"] == 4


def test_run_script_python_error(tmp_path):
    s = tmp_path / "m.py"
    s.write_text("x = 1\ny = x / 0\n")
    with pytest.raises(CadError) as e:
        run_script(s)
    assert e.value.code == "SCRIPT_ERROR" and e.value.details["location"]["line"] == 2


def test_no_model(tmp_path):
    s = tmp_path / "m.py"
    s.write_text("x = 1\n")
    with pytest.raises(CadError) as e:
        run_script(s)
    assert e.value.code == "NO_MODEL"
