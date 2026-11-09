"""Check that slicers load cad's 3MF files the way cad meant: every part present, the right size, in
place relative to the rest of the model, on the right extruder. Optionally also slice to G-code.

Run it with the Python that has cad installed (it uses the `cad` CLI on PATH to make the files):

    python scripts/slicer_compat/check.py [--out DIR] [--require prusa,orca,cura,bambu] [--json | --json-out FILE]

Slicers are found on PATH or through environment variables; missing ones are skipped unless required:
    PrusaSlicer  `prusa-slicer` (or $PRUSA_SLICER)
    OrcaSlicer   $ORCA_SLICER (the orca-slicer binary, e.g. from the unpacked Linux AppImage)
    Cura         $CURA_DIR (the unpacked Cura AppImage: its pySavitar parses the files exactly as Cura does)
    Bambu Studio found the way `cad slice` finds it ($CAD_BAMBU_STUDIO, PATH, /Applications)

Exit status: 0 when every check passed, 1 when any failed. Known limitations are reported, not failed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
PROD = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
TOL = 0.05  # mm

# (example, 3MF mode, target): the test set. Separate objects, a multi-material assembly whose parts sit at
# different heights (nameplate badge on top of the plate, case on its feet), and PrusaSlicer's layout.
FIXTURES = [
    ("plate_with_holes", "objects", "any"),
    ("multimaterial_case", "objects", "any"),
    ("multimaterial_case", "multimaterial", "any"),
    ("nameplate", "multimaterial", "any"),
    ("multimaterial_case", "multimaterial", "prusa"),
    ("nameplate", "multimaterial", "prusa"),
]


# ---------------------------------------------------------------------- reading 3MF files
def _matrix(text: str | None) -> np.ndarray:
    m = np.eye(4)
    if text:
        v = [float(x) for x in text.split()]
        m[:3, :3] = np.array(v[:9]).reshape(3, 3)  # 3MF stores row vectors: p' = p @ M3 + t
        m[3, :3] = v[9:12]
    return m


def _apply(m: np.ndarray, v: np.ndarray) -> np.ndarray:
    return v @ m[:3, :3] + m[3, :3]


class Model:
    """A 3MF package flattened to meshes in world coordinates: (object path, object id) -> world vertices,
    plus the triangle count of each mesh object."""

    def __init__(self, path: Path):
        self.z = zipfile.ZipFile(path)
        self.docs: dict[str, ET.Element] = {}
        self.root = self.doc("/3D/3dmodel.model")

    def doc(self, path: str) -> ET.Element:
        if path not in self.docs:
            self.docs[path] = ET.fromstring(self.z.read(path.lstrip("/")))
        return self.docs[path]

    def obj(self, path: str, oid: str) -> ET.Element:
        for o in self.doc(path).iter(f"{CORE}object"):
            if o.get("id") == oid:
                return o
        raise KeyError(f"{path}#{oid}")

    def meshes(self, path: str, oid: str, m: np.ndarray, out: list):
        o = self.obj(path, oid)
        mesh = o.find(f"{CORE}mesh")
        if mesh is not None:
            v = np.array([[float(x.get(k)) for k in "xyz"] for x in mesh.iter(f"{CORE}vertex")])
            t = np.array([[int(x.get(k)) for k in ("v1", "v2", "v3")] for x in mesh.iter(f"{CORE}triangle")])
            out.append({"path": path, "id": oid, "name": o.get("name"), "verts": _apply(m, v), "tris": t})
        for c in o.iter(f"{CORE}component"):
            self.meshes(c.get(f"{PROD}path") or path, c.get("objectid"), _matrix(c.get("transform")) @ m, out)

    def items(self) -> list[dict]:
        """Each build item: its object id, name and the meshes below it in world coordinates."""
        out = []
        for it in self.root.iter(f"{CORE}item"):
            meshes: list = []
            self.meshes("/3D/3dmodel.model", it.get("objectid"), _matrix(it.get("transform")), meshes)
            out.append({"id": it.get("objectid"), "name": self.obj("/3D/3dmodel.model", it.get("objectid")).get("name"),
                        "meshes": meshes})
        return out

    def text(self, name: str) -> str | None:
        try:
            return self.z.read(name).decode()
        except KeyError:
            return None


def _bbox(v: np.ndarray) -> list[list[float]]:
    return [v.min(0).tolist(), v.max(0).tolist()]


def _blocks(cfg: str, tag: str):
    for b in re.findall(rf"<{tag}\b([^>]*)>(.*?)</{tag}>", cfg, re.S):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', b[0]))
        meta = dict(re.findall(r'key="([^"]+)" value="([^"]*)"', b[1]))
        yield attrs, meta, b[1]


def parts_bambu(path: Path) -> list[dict]:
    """Parts as Bambu Studio / OrcaSlicer store them: model_settings.config objects -> parts (component ids)."""
    m = Model(path)
    cfg = m.text("Metadata/model_settings.config") or ""
    objects = {a["id"]: (meta, body) for a, meta, body in _blocks(cfg, "object")}
    out = []
    for it in m.items():
        meta, body = objects.get(it["id"], ({}, ""))
        parts = {a["id"]: pm for a, pm, _ in _blocks(body, "part")}
        for mesh in it["meshes"]:
            pm = parts.get(mesh["id"], {})
            if not pm and len(it["meshes"]) == 1 and len(parts) == 1:
                pm = next(iter(parts.values()))   # a plain mesh object: its one part
            out.append({"name": pm.get("name") or meta.get("name") or mesh["name"],
                        "extruder": int(pm.get("extruder") or meta.get("extruder") or 1),
                        "bbox": _bbox(mesh["verts"])})
    return out


def parts_prusa(path: Path) -> list[dict]:
    """Parts as PrusaSlicer stores them: Slic3r_PE_model.config objects -> volumes (triangle ranges)."""
    m = Model(path)
    cfg = m.text("Metadata/Slic3r_PE_model.config") or ""
    objects = {}
    for a, _, body in _blocks(cfg, "object"):
        ometa = dict(re.findall(r'type="object" key="([^"]+)" value="([^"]*)"', body))
        vols = []
        for va, _, vbody in _blocks(body, "volume"):
            vmeta = dict(re.findall(r'type="volume" key="([^"]+)" value="([^"]*)"', vbody))
            vols.append((int(va["firstid"]), int(va["lastid"]), vmeta))
        objects[a["id"]] = (ometa, vols)
    out = []
    for it in m.items():
        for mesh in it["meshes"]:
            ometa, vols = objects.get(mesh["id"], ({}, []))
            vols = vols or [(0, len(mesh["tris"]) - 1, {})]
            for first, last, vmeta in vols:
                used = np.unique(mesh["tris"][first:last + 1])
                ext = vmeta.get("extruder") or ometa.get("extruder") or "1"
                out.append({"name": vmeta.get("name") or ometa.get("name") or mesh["name"],
                            "extruder": int(ext) if int(ext) > 0 else int(ometa.get("extruder") or 1),
                            "bbox": _bbox(mesh["verts"][used])})
    return out


CURA_DUMP = r"""
import json, sys, zipfile
import numpy as np
sys.path.insert(0, sys.argv[1])
import pySavitar

def matrix(t):
    m = np.eye(4)
    if t:
        v = [float(x) for x in t.split()]
        m[:3, :3] = np.array(v[:9]).reshape(3, 3); m[3, :3] = v[9:12]
    return m

def walk(n, m, ext, out):
    m = matrix(n.getTransformation()) @ m
    s = {k: e.value for k, e in n.getSettings().items()}
    ext = int(s.get("extruder_nr", ext))
    md = n.getMeshData()
    if md is not None:
        v = np.frombuffer(md.getVerticesAsBytes(), dtype=np.float32).reshape(-1, 3).astype(float)
        if len(v):
            w = v @ m[:3, :3] + m[3, :3]
            out.append({"name": n.getName(), "extruder": ext + 1, "bbox": [w.min(0).tolist(), w.max(0).tolist()]})
    for c in n.getChildren():
        walk(c, m, ext, out)

with zipfile.ZipFile(sys.argv[2]) as z:
    scene = pySavitar.ThreeMFParser().parse(z.read("3D/3dmodel.model"))
out = []
for n in scene.getSceneNodes():
    walk(n, np.eye(4), 0, out)
print(json.dumps({"unit": scene.getUnit(), "parts": out}))
"""


# ---------------------------------------------------------------------- slicers
class Slicer:
    name = ""
    reads = ("any",)   # which targets this slicer is expected to load correctly

    def available(self) -> bool:
        raise NotImplementedError

    def load(self, src: Path, work: Path) -> list[dict]:
        """The parts as the slicer understood them: name, extruder, world bbox."""
        raise NotImplementedError

    def known_limit(self, mode: str, target: str) -> str | None:
        return None


class Prusa(Slicer):
    name = "PrusaSlicer"
    reads = ("any", "prusa")

    def __init__(self):
        self.exe = os.environ.get("PRUSA_SLICER") or shutil.which("prusa-slicer")

    def available(self):
        return bool(self.exe)

    def version(self):
        return subprocess.run([self.exe, "--help"], capture_output=True, text=True).stdout.split("\n")[0].strip()

    def load(self, src, work):
        out = work / "prusa.3mf"
        p = subprocess.run([self.exe, "--export-3mf", "-o", str(out), str(src)], capture_output=True, text=True,
                           timeout=300)
        if p.returncode or not out.exists():
            raise RuntimeError((p.stdout + p.stderr)[-800:])
        return parts_prusa(out)

    def known_limit(self, mode, target):
        if mode == "multimaterial" and target == "any":
            return "PrusaSlicer splits 3MF components into separate objects and drops each onto the bed: use --3mf-for prusa"
        return None

    def slice(self, src, work, extruders: int) -> list[float]:
        """Filament used per extruder (mm of filament; the cm3 figure rounds a small part to 0) when slicing with PrusaSlicer's defaults and `extruders` extruders."""
        gcode = work / "prusa.gcode"
        n = max(extruders, 1)
        args = [self.exe, "--export-gcode", "-o", str(gcode), "--nozzle-diameter", ",".join(["0.4"] * n),
                "--filament-diameter", ",".join(["1.75"] * n), "--temperature", ",".join(["215"] * n),
                "--first-layer-temperature", ",".join(["215"] * n), "--bed-shape", "0x0,250x0,250x210,0x210",
                "--center", "125,105", str(src)]
        p = subprocess.run(args, capture_output=True, text=True, timeout=600)
        if p.returncode or not gcode.exists():
            raise RuntimeError((p.stdout + p.stderr)[-800:])
        m = re.search(r"^; filament used \[mm\] = (.*)$", gcode.read_text(errors="replace"), re.M)
        return [float(x) for x in m.group(1).split(",")] if m else []


class Orca(Slicer):
    name = "OrcaSlicer"

    def __init__(self):
        self.exe = os.environ.get("ORCA_SLICER")

    def available(self):
        return bool(self.exe) and Path(self.exe).exists()

    def env(self):
        e = dict(os.environ)
        lib = Path(self.exe).resolve().parent.parent / "lib"
        if lib.is_dir():  # unpacked AppImage
            e["LD_LIBRARY_PATH"] = f"{lib}:{e.get('LD_LIBRARY_PATH', '')}"
        if not e.get("XDG_RUNTIME_DIR"):
            d = Path(tempfile.gettempdir()) / f"xdg-{os.getuid()}"
            d.mkdir(mode=0o700, exist_ok=True)
            e["XDG_RUNTIME_DIR"] = str(d)
        return e

    def version(self):
        return f"OrcaSlicer {os.environ.get('ORCA_VERSION', '')}".strip()

    def load(self, src, work):
        out = work / "orca.3mf"
        p = subprocess.run([self.exe, "--arrange", "0", "--export-3mf", str(out), str(src)], capture_output=True,
                           text=True, timeout=300, env=self.env(), cwd=work)
        if p.returncode or not out.exists():
            raise RuntimeError((p.stdout + p.stderr)[-800:])
        return parts_bambu(out)


class Bambu(Orca):
    name = "Bambu Studio"

    def __init__(self):
        try:
            from cad.slicer import find_bambu
            exe = find_bambu()
        except ImportError:
            exe = None
        self.exe = str(exe) if exe else None

    def version(self):
        try:
            from cad.slicer import bambu_version
            return f"Bambu Studio {bambu_version(Path(self.exe))}"
        except ImportError:
            return "Bambu Studio"

    def load(self, src, work):
        out = work / "bambu.3mf"
        # Bambu Studio writes result.json into the current directory
        p = subprocess.run([self.exe, "--outputdir", str(work), "--export-3mf", out.name, str(src)],
                           capture_output=True, text=True, timeout=300, cwd=work)
        if p.returncode or not out.exists():
            raise RuntimeError((p.stdout + p.stderr)[-800:])
        return parts_bambu(out)


class Cura(Slicer):
    name = "Cura"

    def __init__(self):
        self.dir = os.environ.get("CURA_DIR")

    def available(self):
        return bool(self.dir) and (Path(self.dir) / "pySavitar.so").exists()

    def version(self):
        desktop = next(Path(self.dir).glob("*.desktop"), None)
        m = re.search(r"X-AppImage-Version=(\S+)", desktop.read_text()) if desktop else None
        return f"Cura {m.group(1)} (its 3MF parser)" if m else "Cura (its 3MF parser)"

    def load(self, src, work):
        env = dict(os.environ, LD_LIBRARY_PATH=f"{self.dir}:{os.environ.get('LD_LIBRARY_PATH', '')}")
        p = subprocess.run([sys.executable, "-c", CURA_DUMP, self.dir, str(src)], capture_output=True, text=True,
                           timeout=300, env=env)
        if p.returncode:
            raise RuntimeError(p.stderr[-800:])
        d = json.loads(p.stdout)
        if d["unit"] != "millimeter":
            raise RuntimeError(f"unit {d['unit']}")
        return d["parts"]


# ---------------------------------------------------------------------- comparison
def compare(want: list[dict], got: list[dict], mode: str) -> list[str]:
    """Differences between cad's parts and the slicer's, by name. In multimaterial mode positions are compared
    relative to the whole model (slicers may move the model on the bed); in objects mode only sizes."""
    problems = []
    g = {p["name"]: p for p in got}
    if sorted(g) != sorted(p["name"] for p in want):
        return [f"parts {sorted(g)} instead of {sorted(p['name'] for p in want)}"]

    def origin(parts):
        return np.min([p["bbox"][0] for p in parts], axis=0)

    ow, og = origin(want), origin(got)
    for w in want:
        s = g[w["name"]]
        if s["extruder"] != w["extruder"]:
            problems.append(f"{w['name']}: extruder {s['extruder']}, want {w['extruder']}")
        bw, bs = np.array(w["bbox"]), np.array(s["bbox"])
        if np.abs((bw[1] - bw[0]) - (bs[1] - bs[0])).max() > TOL:
            problems.append(f"{w['name']}: size {np.round(bs[1] - bs[0], 3).tolist()}, want {np.round(bw[1] - bw[0], 3).tolist()}")
        elif mode == "multimaterial" and np.abs((bw[0] - ow) - (bs[0] - og)).max() > TOL:
            problems.append(f"{w['name']}: at {np.round(bs[0] - og, 3).tolist()} in the model, "
                            f"want {np.round(bw[0] - ow, 3).tolist()}")
    return problems


def footprints_overlap(parts: list[dict]) -> list[str]:
    """Pairs of parts whose footprints on the bed overlap (objects mode keeps each part's modelled X/Y)."""
    out = []
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            (a0, a1), (b0, b1) = np.array(a["bbox"]), np.array(b["bbox"])
            if all(a0[k] < b1[k] - TOL and b0[k] < a1[k] - TOL for k in (0, 1)):
                out.append(f"{a['name']}/{b['name']}")
    return out


def make_fixtures(out: Path) -> list[dict]:
    fixtures = []
    for example, mode, target in FIXTURES:
        proj = out / "projects" / example
        if not proj.exists():
            subprocess.run(["cad", "examples", "copy", example, str(proj)], check=True, capture_output=True)
            subprocess.run(["cad", "build"], cwd=proj, check=True, capture_output=True)
        dst = out / f"{example}-{mode}-{target}"
        r = subprocess.run(["cad", "export", "--format", "3mf", "--3mf-mode", mode, "--3mf-for", target,
                            "--out", str(dst), "--json"], cwd=proj, check=True, capture_output=True, text=True)
        f = json.loads(r.stdout)["result"]["files"][0]
        src = Path(f["path"])
        extruder = {part: m["extruder"] for m in f["materials"] for part in m["parts"]}
        want = parts_prusa(src) if (mode, target) == ("multimaterial", "prusa") else parts_bambu(src)
        for w in want:  # extruders from cad's report, not from our own reading of the file
            w["extruder"] = extruder[w["name"]]
        fixtures.append({"name": dst.name, "example": example, "mode": mode, "target": target, "path": src,
                         "want": want, "extruders": sorted(set(extruder.values()))})
    return fixtures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=None, help="working directory (default: a temporary one)")
    ap.add_argument("--require", default="", help="comma-separated slicers that must be present: prusa,orca,cura,bambu")
    ap.add_argument("--no-slice", action="store_true", help="skip slicing to G-code (PrusaSlicer)")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    ap.add_argument("--json-out", type=Path, help="also write the full report as JSON to this file")
    args = ap.parse_args()
    out = args.out or Path(tempfile.mkdtemp(prefix="slicer-compat-"))
    out.mkdir(parents=True, exist_ok=True)
    slicers = {"prusa": Prusa(), "orca": Orca(), "cura": Cura(), "bambu": Bambu()}
    required = [s for s in args.require.split(",") if s]
    report = {"slicers": {}, "results": [], "missing": []}
    for key, s in slicers.items():
        if s.available():
            report["slicers"][key] = s.version()
        else:
            report["missing"].append(key)
    missing_required = [k for k in required if k in report["missing"]]

    fixtures = make_fixtures(out)
    failed = bool(missing_required)
    for fx in fixtures:
        for key, s in slicers.items():
            if key in report["missing"] or fx["target"] not in s.reads:
                continue
            work = out / "work" / key / fx["name"]
            work.mkdir(parents=True, exist_ok=True)
            row = {"fixture": fx["name"], "slicer": key}
            try:
                problems = compare(fx["want"], s.load(fx["path"], work), fx["mode"])
            except Exception as e:  # noqa: BLE001 - a slicer crash is a result
                problems = [f"could not load: {e}"]
            limit = s.known_limit(fx["mode"], fx["target"])
            if problems and limit:
                row.update(status="known", note=limit, problems=problems)
            elif problems:
                row.update(status="fail", problems=problems)
                failed = True
            else:
                row.update(status="ok")
                if limit:
                    row.update(status="fail", problems=["known limitation no longer reproduces; update check.py"])
                    failed = True
            overlap = footprints_overlap(fx["want"]) if fx["mode"] == "objects" else []
            if key == "prusa" and not args.no_slice and row["status"] == "ok" and overlap:
                row["note"] = (f"not sliced: in objects mode these parts overlap on the bed ({', '.join(overlap[:3])}); "
                               "PrusaSlicer reports G-code path conflicts")
            elif key == "prusa" and not args.no_slice and row["status"] == "ok":
                try:
                    used = s.slice(fx["path"], work, max(fx["extruders"]))
                    on = sorted(i + 1 for i, v in enumerate(used) if v > 0)
                    row["filament_mm"] = used
                    if on != fx["extruders"]:
                        row.update(status="fail", problems=[f"G-code uses extruders {on}, want {fx['extruders']}"])
                        failed = True
                except Exception as e:  # noqa: BLE001
                    row.update(status="fail", problems=[f"could not slice: {e}"])
                    failed = True
            report["results"].append(row)

    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=1, default=str))
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        for k, v in report["slicers"].items():
            print(f"{k:6} {v}")
        for k in report["missing"]:
            print(f"{k:6} not found{' (REQUIRED)' if k in required else ', skipped'}")
        print()
        for r in report["results"]:
            mark = {"ok": "ok  ", "known": "know", "fail": "FAIL"}[r["status"]]
            extra = f"  filament mm {r['filament_mm']}" if "filament_mm" in r else ""
            print(f"{mark} {r['slicer']:6} {r['fixture']}{extra}")
            for p in r.get("problems", []):
                print(f"       - {p}")
            if r.get("note"):
                print(f"       ({r['note']})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
