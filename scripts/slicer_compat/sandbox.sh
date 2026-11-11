#!/usr/bin/env bash
# Run check.py against PrusaSlicer, OrcaSlicer and Cura in an ephemeral Vercel sandbox, on this working tree
# (uncommitted changes included). Needs the `sandbox` CLI, logged in (npm i -g sandbox; sandbox login).
#   scripts/slicer_compat/sandbox.sh                 # fresh sandbox: provisions it (~10 min), then checks
#   scripts/slicer_compat/sandbox.sh --snapshot ID   # start from a snapshot made by --save (~4 min)
#   scripts/slicer_compat/sandbox.sh --save          # also snapshot the provisioned sandbox (prints its ID)
# The report lands in slicer-compat-report.txt / .json; the sandbox is removed afterwards (--keep to keep it).
set -euo pipefail
SNAPSHOT="" SAVE=0 KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --snapshot) SNAPSHOT="$2"; shift ;;
    --save) SAVE=1 ;;
    --keep) KEEP=1 ;;
    *) echo "usage: $0 [--snapshot ID] [--save] [--keep]" >&2; exit 2 ;;
  esac
  shift
done
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
NAME="cad-slicers-$(date +%s)"
run() { sandbox exec "$NAME" -- bash -lc "$1"; }
# Hobby plans cap a sandbox at 45 minutes; a fresh run needs about 15
sandbox create --name "$NAME" --vcpus 4 --timeout 45m --network-policy allow-all ${SNAPSHOT:+--snapshot "$SNAPSHOT"} >/dev/null
cleanup() { [ "$KEEP" = 1 ] && echo "kept sandbox $NAME" >&2 || sandbox rm "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
if [ -z "$SNAPSHOT" ]; then
  # files go under the home directory (/vercel): it is what a snapshot keeps
  sandbox cp "$REPO/scripts/slicer_compat/setup.sh" "$NAME:/vercel/setup.sh" >/dev/null
  run 'bash ~/setup.sh > ~/setup.log 2>&1 || { tail -40 ~/setup.log; exit 1; }'
fi
TAR="$(mktemp -t cad-src).tgz"
(cd "$REPO" && git ls-files -co --exclude-standard -z | COPYFILE_DISABLE=1 tar --no-xattrs --null -czf "$TAR" -T -)
sandbox cp "$TAR" "$NAME:/vercel/src.tgz" >/dev/null
rm -f "$TAR"
run 'source ~/slicers/env.sh && mkdir -p ~/cli-cad && cd ~/cli-cad && tar xzf ~/src.tgz && CAD_LINK_DIR=~/.local/bin scripts/install.sh > ~/install.log 2>&1 || { tail -30 ~/install.log; exit 1; }'
if [ "$SAVE" = 1 ] && [ -z "$SNAPSHOT" ]; then
  # snapshotting stops the sandbox; carry on in a new one from the snapshot
  ID=$(sandbox snapshot "$NAME" --stop --expiration 30d 2>&1 | grep -oE 'snap_[A-Za-z0-9]+' | head -1)
  [ -n "$ID" ] || { echo "error: snapshot failed" >&2; exit 1; }
  echo "snapshot: $ID  (next time: $0 --snapshot $ID)" >&2
  sandbox rm "$NAME" >/dev/null 2>&1 || true
  sandbox create --name "$NAME" --vcpus 4 --timeout 45m --network-policy allow-all --snapshot "$ID" >/dev/null
fi
set +e
run 'source ~/slicers/env.sh && cd ~/cli-cad && ~/.local/cad/.venv/bin/python scripts/slicer_compat/check.py --require prusa,orca,cura --out ~/compat --json-out ~/report.json | tee ~/report.txt; exit ${PIPESTATUS[0]}'
STATUS=$?
set -e
sandbox cp "$NAME:/vercel/report.json" "$REPO/slicer-compat-report.json" >/dev/null
sandbox cp "$NAME:/vercel/report.txt" "$REPO/slicer-compat-report.txt" >/dev/null
exit $STATUS
