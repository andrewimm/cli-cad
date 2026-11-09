"""Release bookkeeping: one version (crates/cad/Cargo.toml) everywhere, with a changelog entry, and an
installer template the release workflow can fill in."""
import re
import subprocess
from pathlib import Path

import cad

ROOT = Path(__file__).resolve().parents[1]


def _cargo_version() -> str:
    return re.search(r'^version = "([^"]+)"', (ROOT / "crates/cad/Cargo.toml").read_text(), re.M).group(1)


def test_one_version_everywhere():
    v = _cargo_version()
    assert cad.__version__ == v, "re-run `uv sync` after bumping crates/cad/Cargo.toml"
    assert re.search(rf'^name = "cad"\nversion = "{re.escape(v)}"', (ROOT / "Cargo.lock").read_text(), re.M), \
        "Cargo.lock is behind crates/cad/Cargo.toml: run cargo build"
    assert 'dynamic = ["version"]' in (ROOT / "pyproject.toml").read_text()


def test_changelog_has_this_version_on_top():
    first = re.search(r"^## (\S+) \(\d{4}-\d{2}-\d{2}\)$", (ROOT / "CHANGELOG.md").read_text(), re.M)
    assert first and first.group(1) == _cargo_version()


def test_release_installer_template():
    script = (ROOT / "scripts/install-release.sh").read_text()
    assert 'VERSION="@VERSION@"' in script and 'WHEELS="@WHEELS@"' in script
    subprocess.run(["sh", "-n", str(ROOT / "scripts/install-release.sh")], check=True)
