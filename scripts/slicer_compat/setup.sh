#!/usr/bin/env bash
# Provision an Ubuntu 26.04 x86_64 machine (e.g. a Vercel sandbox) for check.py: PrusaSlicer (apt), OrcaSlicer and
# Cura (Linux AppImages, unpacked: no FUSE needed), uv and Rust for building cad. Writes ~/slicers/env.sh.
set -euxo pipefail
ORCA_VERSION=${ORCA_VERSION:-2.5.0}
CURA_VERSION=${CURA_VERSION:-5.14.0}
export DEBIAN_FRONTEND=noninteractive
sudo -E apt-get update -qq
sudo -E apt-get install -y -qq build-essential git curl file \
  libgl1 libegl1 libfontconfig1 fonts-dejavu-core libglu1-mesa libxrender1 libxcursor1 libxft2 libxinerama1 libxi6 \
  libxkbcommon0 prusa-slicer >/dev/null
# OrcaSlicer's AppImage links FFmpeg 7 (libavformat61 ...), which Ubuntu 26.04 replaced; take it from 25.04,
# pinned low so nothing else comes from there. (The OrcaSlicer flatpak needs a session bus and FUSE: no go here.)
echo "deb http://archive.ubuntu.com/ubuntu plucky main universe" | sudo tee /etc/apt/sources.list.d/plucky.list >/dev/null
printf 'Package: *\nPin: release n=plucky\nPin-Priority: 100\n' | sudo tee /etc/apt/preferences.d/plucky >/dev/null
sudo -E apt-get update -qq
sudo -E apt-get install -y -qq libavformat61 libavcodec61 libswscale8 libavutil59 libmspack0t64 >/dev/null
mkdir -p ~/slicers && cd ~/slicers
curl -fsSL -o orca.AppImage "https://github.com/SoftFever/OrcaSlicer/releases/download/v${ORCA_VERSION}/OrcaSlicer_Linux_AppImage_Ubuntu2404_V${ORCA_VERSION}.AppImage"
curl -fsSL -o cura.AppImage "https://github.com/Ultimaker/Cura/releases/download/${CURA_VERSION}/UltiMaker-Cura-${CURA_VERSION}-linux-X64.AppImage"
chmod +x ./*.AppImage
for a in orca cura; do rm -rf "$a" squashfs-root; "./$a.AppImage" --appimage-extract >/dev/null; mv squashfs-root "$a"; done
rm -f ./*.AppImage
if ldd orca/bin/orca-slicer | grep 'not found'; then echo "OrcaSlicer is missing libraries (above)"; exit 1; fi
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
command -v cargo || curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y -q
cat > ~/slicers/env.sh <<ENV
export PATH="\$HOME/.local/bin:\$HOME/.cargo/bin:\$PATH"
export ORCA_SLICER="\$HOME/slicers/orca/bin/orca-slicer"
export CURA_DIR="\$HOME/slicers/cura"
export ORCA_VERSION="${ORCA_VERSION}"
ENV
echo SETUP-DONE
