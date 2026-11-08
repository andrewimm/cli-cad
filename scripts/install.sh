#!/usr/bin/env bash
# Install cad into a self-contained prefix and put it on PATH:
#   PREFIX/.venv      Python 3.12 environment with the cad wheel and its dependencies
#   PREFIX/bin/cad    CLI client   (finds PREFIX/.venv automatically)
#   PREFIX/bin/cadd   session daemon
#   LINK_DIR/cad, LINK_DIR/cadd   symlinks (default LINK_DIR: ~/.local/bin; set CAD_LINK_DIR="" to skip)
# Usage: scripts/install.sh [PREFIX]   (default: ~/.local/cad)
# Re-run to update; the symlinks keep pointing at the new binaries.
set -euo pipefail
PREFIX="${1:-$HOME/.local/cad}"
LINK_DIR="${CAD_LINK_DIR-$HOME/.local/bin}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
echo "building wheel and binaries..." >&2
rm -rf dist
uv build --wheel -q
cargo build --release -q
mkdir -p "$PREFIX/bin"
uv venv -q --allow-existing --python 3.12 "$PREFIX/.venv"
uv pip install -q --reinstall --python "$PREFIX/.venv/bin/python" dist/cad-*.whl
# replace, never overwrite in place: macOS kills a binary whose signed file was modified in place (SIGKILL)
rm -f "$PREFIX/bin/cad" "$PREFIX/bin/cadd"
cp target/release/cad target/release/cadd "$PREFIX/bin/"
"$PREFIX/bin/cad" daemon stop >/dev/null 2>&1 || true   # a running daemon would keep the old code
echo "installed cad $("$PREFIX/bin/cad" --no-daemon --version | awk '{print $2}') into $PREFIX" >&2
if [ -n "$LINK_DIR" ]; then
  mkdir -p "$LINK_DIR"
  ln -sf "$PREFIX/bin/cad" "$LINK_DIR/cad"
  ln -sf "$PREFIX/bin/cadd" "$LINK_DIR/cadd"
  echo "linked cad and cadd into $LINK_DIR" >&2
  case ":$PATH:" in
    *":$LINK_DIR:"*) echo "ready: run 'cad --help'" >&2 ;;
    *) echo "warning: $LINK_DIR is not on PATH; add it (fish: fish_add_path $LINK_DIR; bash/zsh: export PATH=\"$LINK_DIR:\$PATH\")" >&2 ;;
  esac
else
  echo "add to PATH:  export PATH=\"$PREFIX/bin:\$PATH\"" >&2
fi
