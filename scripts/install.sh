#!/usr/bin/env bash
# Install cad into a self-contained prefix and put it on PATH:
#   PREFIX/.venv      Python 3.12 environment with the cad wheel and its dependencies
#   PREFIX/bin/cad    CLI client   (finds PREFIX/.venv automatically)
#   PREFIX/bin/cadd   session daemon
#   LINK_DIR/cad, LINK_DIR/cadd   symlinks (default LINK_DIR: ~/.local/bin; set CAD_LINK_DIR="" to skip)
# Usage: scripts/install.sh [--fea] [PREFIX]   (default: ~/.local/cad)
#   --fea   also install the optional stress-analysis packages (gmsh is GPL-licensed, hence optional)
# Needs uv and cargo; uv downloads Python 3.12 itself. Re-run to update; the symlinks keep pointing at
# the new binaries (and any optional packages stay installed). Ends by checking that cad runs.
set -euo pipefail
FEA=0
PREFIX=""
for arg in "$@"; do
  case "$arg" in
    --fea) FEA=1 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "error: unknown option $arg (see --help)" >&2; exit 2 ;;
    *) PREFIX="$arg" ;;
  esac
done
PREFIX="${PREFIX:-$HOME/.local/cad}"
LINK_DIR="${CAD_LINK_DIR-$HOME/.local/bin}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

missing=0
if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv not found. Install it:  curl -LsSf https://astral.sh/uv/install.sh | sh   (or: brew install uv)" >&2
  missing=1
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "error: cargo not found. Install Rust:  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y" >&2
  missing=1
fi
if [ "$missing" = 1 ]; then
  echo "then open a new shell (or source the env file the installer names) and re-run $0" >&2
  exit 1
fi

echo "building wheel and binaries..." >&2
rm -rf dist
uv build --wheel -q
cargo build --release -q
mkdir -p "$PREFIX/bin"
uv venv -q --allow-existing --python 3.12 "$PREFIX/.venv"
uv pip install -q --reinstall --python "$PREFIX/.venv/bin/python" dist/cad-*.whl
if [ "$FEA" = 1 ]; then
  echo "installing stress-analysis packages (gmsh, scikit-fem, scipy, pyamg)..." >&2
  uv pip install -q --python "$PREFIX/.venv/bin/python" "$(ls dist/cad-*.whl)[fea]"
fi
# replace, never overwrite in place: macOS kills a binary whose signed file was modified in place (SIGKILL)
rm -f "$PREFIX/bin/cad" "$PREFIX/bin/cadd"
cp target/release/cad target/release/cadd "$PREFIX/bin/"
"$PREFIX/bin/cad" daemon stop >/dev/null 2>&1 || true   # a running daemon would keep the old code

# check that the geometry kernel loads (on Linux it needs a few system libraries)
if ! "$PREFIX/bin/cad" --no-daemon capabilities >/dev/null 2>"$PREFIX/install-check.log"; then
  echo "error: cad is installed but does not run:" >&2
  tail -n 5 "$PREFIX/install-check.log" >&2
  if [ "$(uname -s)" = Linux ]; then
    echo "on Debian/Ubuntu install the system libraries, then re-run:" >&2
    echo "  sudo apt-get install -y libgl1 libegl1 libfontconfig1 fonts-dejavu-core" >&2
    echo "  (with --fea also: libglu1-mesa libxrender1 libxcursor1 libxft2 libxinerama1 libxi6 libxkbcommon0)" >&2
  fi
  exit 1
fi
rm -f "$PREFIX/install-check.log"
caps="$("$PREFIX/bin/cad" --no-daemon capabilities 2>/dev/null || true)"
if [[ "$caps" == *"stress analysis (cad fea): available"* ]]; then
  fea_state="stress analysis available"
else
  fea_state="stress analysis not installed; add it with --fea"
fi
echo "installed cad $("$PREFIX/bin/cad" --no-daemon --version | awk '{print $2}') into $PREFIX ($fea_state)" >&2

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
