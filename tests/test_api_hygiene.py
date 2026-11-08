"""Guards against API mistakes found during evaluation."""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_no_duplicate_method_names():
    for f in (ROOT / "src" / "cad").glob("*.py"):
        tree = ast.parse(f.read_text())
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            names = [n.name for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            dups = {n for n in names if names.count(n) > 1}
            assert not dups, f"{f.name}:{cls.name} defines {dups} more than once"


def test_part_attributes_do_not_shadow_methods():
    from cad import Part

    p = Part("x")
    for attr in vars(p):
        assert not callable(getattr(Part, attr, None)), f"instance attribute {attr!r} shadows Part.{attr}()"


def test_eval_reference_solutions_pass():
    r = subprocess.run([sys.executable, "-m", "cadeval", "selftest"], cwd=ROOT / "evals", capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
