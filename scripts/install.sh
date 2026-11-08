#!/usr/bin/env bash
# Install cad into a self-contained prefix:
#   PREFIX/.venv      Python 3.12 environment with the cad wheel and its dependencies
#   PREFIX/bin/cad    CLI client   (finds PREFIX/.venv automatically)
#   PREFIX/bin/cadd   session daemon
# Usage: scripts/install.sh [PREFIX]   (default: ~/.local/cad)
set -euo pipefail
PREFIX="${1:-$HOME/.local/cad}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
echo "building wheel and binaries..." >&2
rm -rf dist
uv build --wheel -q
cargo build --release -q
mkdir -p "$PREFIX/bin"
uv venv -q --python 3.12 "$PREFIX/.venv"
uv pip install -q --python "$PREFIX/.venv/bin/python" dist/cad-*.whl
cp target/release/cad target/release/cadd "$PREFIX/bin/"
echo "installed cad $("$PREFIX/bin/cad" --no-daemon --version | awk '{print $2}') into $PREFIX" >&2
echo "add to PATH:  export PATH=\"$PREFIX/bin:\$PATH\"" >&2
