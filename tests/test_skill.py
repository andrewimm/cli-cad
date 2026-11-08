"""The skills.sh skill must stay true: valid frontmatter, runnable Python examples, real commands."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "cad" / "SKILL.md"


def _frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md must start with YAML frontmatter"
    fields = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    return {k.strip(): v.strip() for k, v in fields.items()}


def test_frontmatter():
    fm = _frontmatter(SKILL.read_text())
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fm["name"]), "name: lowercase, hyphens allowed"
    assert fm["name"] == SKILL.parent.name
    assert 20 < len(fm["description"]) <= 1024


@pytest.mark.parametrize("block", re.findall(r"```python\n(.*?)```", SKILL.read_text(), re.S))
def test_python_examples_run(block):
    env: dict = {}
    exec(block, env)
    if callable(env.get("build")):
        out = env["build"]()
        out.assert_valid()


def test_cli_commands_exist():
    from cad.cli import COMMANDS

    text = SKILL.read_text()
    used = set(re.findall(r"`cad ([a-z]+)", text)) | set(re.findall(r"^cad ([a-z]+)", text, re.M))
    unknown = used - set(COMMANDS) - {"daemon"}
    assert not unknown, f"skill mentions commands that do not exist: {unknown}"
