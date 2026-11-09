#!/bin/sh
# Install cad from a GitHub release of andrewimm/clicd: no Rust, compiler or clone needed.
#
#   curl -LsSf https://github.com/andrewimm/clicd/releases/latest/download/install.sh | sh
#   curl -LsSf https://github.com/andrewimm/clicd/releases/latest/download/install.sh | sh -s -- --fea
#
# Installs uv if it is missing, picks this platform's wheel from the release (macOS arm64 / x86_64,
# Linux x86_64 / aarch64) and runs `uv tool install` on it: `cad` and `cadd` land in uv's tool bin
# directory (~/.local/bin), with their own Python 3.12 environment. Re-run to upgrade or reinstall.
#   --fea   also install the optional stress-analysis packages (gmsh is GPL-licensed, hence optional)
# The release workflow fills in VERSION and WHEELS; CLICD_DOWNLOAD_BASE overrides where wheels come from.
set -eu

VERSION="@VERSION@"
WHEELS="@WHEELS@"
BASE="${CLICD_DOWNLOAD_BASE:-https://github.com/andrewimm/clicd/releases/download/v$VERSION}"

say() { printf '%s\n' "$*" >&2; }
die() { say "error: $*"; exit 1; }

FEA=0
for arg in "$@"; do
  case "$arg" in
    --fea) FEA=1 ;;
    -h|--help) sed -n '2,12p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option $arg (options: --fea)" ;;
  esac
done

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) pattern="macosx_*_arm64.whl" ;;
  Darwin-x86_64) pattern="macosx_*_x86_64.whl" ;;
  Linux-x86_64) pattern="manylinux_*_x86_64.whl" ;;
  Linux-aarch64 | Linux-arm64) pattern="manylinux_*_aarch64.whl" ;;
  *) die "no prebuilt cad for $(uname -s) $(uname -m); build from source: https://github.com/andrewimm/clicd#install" ;;
esac
wheel=""
for w in $WHEELS; do
  case "$w" in *$pattern) wheel="$w" ;; esac
done
[ -n "$wheel" ] || die "release v$VERSION has no wheel for $(uname -s) $(uname -m)"

if [ "$(uname -s)" = Linux ] && command -v ldconfig >/dev/null 2>&1; then
  missing=""
  for lib in libGL.so.1 libEGL.so.1 libfontconfig.so.1; do
    ldconfig -p 2>/dev/null | grep -q "$lib" || missing="$missing $lib"
  done
  if [ -n "$missing" ]; then
    say "warning: missing system libraries:$missing (the geometry kernel needs them). On Debian/Ubuntu:"
    say "  sudo apt-get install -y libgl1 libegl1 libfontconfig1 fonts-dejavu-core"
    [ "$FEA" = 1 ] && say "  sudo apt-get install -y libglu1-mesa libxrender1 libxcursor1 libxft2 libxinerama1 libxi6 libxkbcommon0"
  fi
fi

UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  say "installing uv (https://docs.astral.sh/uv/)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh >&2
  for c in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do [ -x "$c" ] && UV="$c" && break; done
  [ -n "$UV" ] || die "uv was installed but cannot be found; open a new shell and re-run"
fi

extra=""
[ "$FEA" = 1 ] && extra="[fea]"
say "installing cad $VERSION ($wheel)${extra:+ with stress analysis}..."
"$UV" tool install --force --python 3.12 "clicd$extra @ $BASE/$wheel" >&2

bindir="$("$UV" tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
cad="$bindir/cad"
[ -x "$cad" ] || die "installed, but $cad is missing"
if ! out="$("$cad" --no-daemon capabilities 2>&1)"; then
  say "error: cad is installed but does not run:"
  printf '%s\n' "$out" | tail -n 5 >&2
  [ "$(uname -s)" = Linux ] && say "install the system libraries above, then re-run"
  exit 1
fi
"$cad" daemon stop >/dev/null 2>&1 || true   # a daemon from an earlier version would keep the old code
say "installed $("$cad" --no-daemon --version) into $bindir ($(printf '%s\n' "$out" | tail -n 1 | sed 's/ — .*//'))"
if [ -d "$HOME/.local/cad" ]; then
  say "note: an older from-source install remains in ~/.local/cad (scripts/install.sh); remove it with: rm -rf ~/.local/cad"
fi
case ":$PATH:" in
  *":$bindir:"*) say "ready: run 'cad --help'" ;;
  *) say "add $bindir to PATH: run '$UV tool update-shell' (then open a new shell), or export PATH=\"$bindir:\$PATH\"" ;;
esac
