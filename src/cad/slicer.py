"""Slice with Bambu Studio's command line: print time, filament use and slicer warnings.

The model is written as a 3MF (the same file `cad export --format 3mf` makes),
sliced with Bambu Studio's bundled printer / process / filament presets, and the
result is read from the slicer's result.json.  The sliced file
(``<name>.gcode.3mf``) can be opened in Bambu Studio or sent to the printer.

Bambu's presets inherit from each other ("inherits": parent name) and the CLI
does not resolve the chain itself: given a leaf preset it silently prints with
zeroed values (filament density 0 -> 0 g, wrong speeds).  So presets are
flattened here, root first, before they are handed over.

Set ``CAD_BAMBU_STUDIO`` to the executable if it is not in a standard place.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path

from .errors import INVALID_ARGUMENT, NOT_FOUND, OPERATION_FAILED, CadError

SLICE_FAILED = "SLICE_FAILED"
SLICER_NOT_FOUND = "SLICER_NOT_FOUND"

DEFAULT_PRINTER = "Bambu Lab A1"
# material name -> filament presets to try, in order (Bambu's own first, then generic)
FILAMENTS = {
    "pla": ["Bambu PLA Basic", "Generic PLA"],
    "petg": ["Bambu PETG Basic", "Generic PETG"],
    "abs": ["Bambu ABS", "Generic ABS"],
    "asa": ["Bambu ASA", "Generic ASA"],
    "tpu": ["Bambu TPU 95A", "Generic TPU"],
    "pa12": ["Generic PA"],
    "nylon": ["Generic PA"],
    "pc": ["Bambu PC", "Generic PC"],
    "pva": ["Bambu PVA", "Generic PVA"],
    "hips": ["Generic HIPS"],
}
NOT_FDM = {"resin", "aluminium", "aluminum", "steel", "brass"}
SUPPORT_MODES = ("default", "off", "auto", "on")
PLATES = {"textured": "Textured PEI Plate", "cool": "Cool Plate", "engineering": "Engineering Plate",
          "high-temp": "High Temp Plate", "smooth": "High Temp Plate", "supertack": "Supertack Plate"}


# ---------------------------------------------------------------------- finding Bambu Studio
def find_bambu(configured: str | None = None) -> Path | None:
    """Locate Bambu Studio: explicit setting, then $CAD_BAMBU_STUDIO, then PATH, then the
    platform's usual install locations (a convenience fallback, not a requirement)."""
    import sys

    candidates = [Path(c).expanduser() for c in (configured, os.environ.get("CAD_BAMBU_STUDIO")) if c]
    for exe in ("bambu-studio", "BambuStudio", "bambu_studio", "bambu-studio.exe", "bambu-studio.AppImage"):
        w = shutil.which(exe)
        if w:
            candidates.append(Path(w))
    if sys.platform == "darwin":
        for apps in (Path("/Applications"), Path.home() / "Applications"):
            candidates.append(apps / "BambuStudio.app" / "Contents" / "MacOS" / "BambuStudio")
    elif sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            if os.environ.get(env):
                candidates.append(Path(os.environ[env]) / "Bambu Studio" / "bambu-studio.exe")
    else:
        candidates += [Path("/usr/bin/bambu-studio"), Path("/opt/bambu-studio/bin/bambu-studio")]
    for c in candidates:
        if c.suffix == ".app":  # a path to the bundle itself
            c = c / "Contents" / "MacOS" / "BambuStudio"
        if c.is_file() and os.access(c, os.X_OK):
            return c
    return None


def _require_bambu(configured: str | None = None) -> Path:
    exe = find_bambu(configured)
    if exe is None:
        if configured:
            raise CadError(SLICER_NOT_FOUND, f"Bambu Studio not found at {configured!r} (cad.toml [print] slicer)")
        raise CadError(SLICER_NOT_FOUND, "Bambu Studio not found (needed for slicing)",
                       hint="install it from bambulab.com, put bambu-studio on PATH, set CAD_BAMBU_STUDIO, "
                            "or set [print] slicer = \"/path/to/BambuStudio\" in cad.toml; "
                            "`cad export --format 3mf` works without it")
    return exe


def profiles_dir(exe: Path) -> Path:
    real = exe.resolve()
    for base in (real.parent.parent / "Resources" / "profiles",          # macOS .app
                 real.parent.parent / "share" / "BambuStudio" / "profiles",  # Linux install
                 real.parent / "resources" / "profiles"):                 # AppImage / Windows layout
        if (base / "BBL").is_dir():
            return base / "BBL"
    raise CadError(SLICER_NOT_FOUND, f"cannot find Bambu Studio's printer profiles next to {exe}")


def bambu_version(exe: Path) -> str:
    plist = exe.resolve().parent.parent / "Info.plist"
    if plist.exists():
        m = re.search(r"<key>CFBundleShortVersionString</key>\s*<string>([^<]+)</string>", plist.read_text(errors="replace"))
        if m:
            return m.group(1)
    return "unknown"


# ---------------------------------------------------------------------- presets
class Presets:
    """Bambu Studio's bundled presets, indexed by (type, name)."""

    def __init__(self, root: Path):
        self.root = root
        self.index: dict[tuple[str, str], Path] = {}
        self._data: dict[tuple[str, str], dict] = {}
        for f in sorted(root.rglob("*.json")):
            try:
                d = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and "name" in d and d.get("type") in ("machine", "process", "filament"):
                key = (d["type"], d["name"])
                self.index.setdefault(key, f)
                self._data.setdefault(key, d)

    def raw(self, kind: str, name: str) -> dict:
        return self._data[(kind, name)]

    def names(self, kind: str) -> list[str]:
        return sorted(n for (t, n), d in self._data.items() if t == kind and d.get("instantiation") == "true")

    def flat(self, kind: str, name: str) -> dict:
        """The preset with its whole inheritance chain merged in (root first)."""
        chain, n = [], name
        while n:
            if (kind, n) not in self._data:
                raise CadError(OPERATION_FAILED, f"Bambu preset {name!r} inherits missing preset {n!r}")
            chain.append(self._data[(kind, n)])
            n = chain[-1].get("inherits")
        out: dict = {}
        for d in reversed(chain):
            out.update(d)
        out.pop("inherits", None)
        out["name"] = name
        return out

    def compatible(self, kind: str, name: str, machine: str) -> bool:
        compat = self.flat(kind, name).get("compatible_printers") or []
        return not compat or machine in compat

    # ------------------------------------------------------------------ resolution
    def machine(self, printer: str | None, nozzle: float | None) -> str:
        printer = (printer or DEFAULT_PRINTER).strip()
        nozzle = 0.4 if nozzle is None else float(nozzle)
        machines = self.names("machine")
        if printer in machines:
            return printer
        want = printer.lower().replace("bambu lab", "").replace("bambu", "").strip()
        aliases = {"x1c": "x1 carbon", "x1": "x1 carbon", "a1m": "a1 mini", "a1mini": "a1 mini"}
        want = aliases.get(want.replace(" ", ""), want)
        target = f"bambu lab {want} {nozzle:g} nozzle"
        for m in machines:
            if m.lower() == target:
                return m
        models = sorted({re.sub(r" \d\.\d nozzle$", "", m) for m in machines})
        near = difflib.get_close_matches(f"Bambu Lab {printer}", models, n=3, cutoff=0.4)
        raise CadError(NOT_FOUND, f"no Bambu printer preset {printer!r} with a {nozzle:g} mm nozzle",
                       hint=(f"did you mean {', '.join(near)}? " if near else "") + "list them with `cad slice --list printers`",
                       details={"printers": models})

    def process(self, process: str | None, machine: str) -> str:
        if not process:
            default = self.flat("machine", machine).get("default_print_profile")
            if default and ("process", default) in self._data:
                return default
            process = "0.20mm Standard"
        if ("process", process) in self._data:
            return process
        hits = [n for n in self.names("process") if n.lower().startswith(process.lower() + " @") and self.compatible("process", n, machine)]
        if hits:
            return hits[0]
        options = sorted({n.split(" @")[0] for n in self.names("process") if self.compatible("process", n, machine)})
        raise CadError(NOT_FOUND, f"no process preset {process!r} for {machine}",
                       hint="e.g. \"0.20mm Standard\", \"0.16mm Optimal\", \"0.12mm Fine\", \"0.28mm Extra Draft\"; "
                            "`cad slice --list processes`", details={"processes": options})

    def filament(self, spec: str, machine: str) -> str:
        """A filament preset for a material name ("PLA") or a preset name ("Bambu PLA Matte")."""
        if ("filament", spec) in self._data:
            return spec
        bases = FILAMENTS.get(spec.strip().lower(), [spec])
        nozzle = re.search(r"(\d\.\d) nozzle", machine)
        for base in bases:
            hits = [n for n in self.names("filament")
                    if n.lower().startswith(base.lower() + " @") and self.compatible("filament", n, machine)]
            if hits:
                # prefer the plain preset over nozzle-specific variants unless they match this nozzle
                plain = [h for h in hits if "nozzle" not in h or (nozzle and nozzle.group(0) in h)]
                return sorted(plain or hits, key=len)[0]
        raise CadError(NOT_FOUND, f"no filament preset for {spec!r} on {machine}",
                       hint="map the material in cad.toml: [print.filaments] \"<material>\" = \"<preset>\"; "
                            "`cad slice --list filaments`")


@lru_cache(maxsize=2)
def presets(root: str) -> Presets:
    return Presets(Path(root))


# ---------------------------------------------------------------------- slicing
def _apply_overrides(configs: dict[str, dict], overrides: dict[str, str]) -> list[str]:
    """Set raw slicer keys (`--set key=value`) on whichever preset defines them."""
    unknown = []
    for k, v in overrides.items():
        hit = False
        for kind in ("process", "machine", "filament"):
            for cfg in (configs[kind] if kind == "filament" else [configs[kind]]):
                if k in cfg:
                    cfg[k] = [str(v)] * max(1, len(cfg[k])) if isinstance(cfg[k], list) else str(v)
                    hit = True
            if hit:
                break
        if not hit:
            unknown.append(k)
    return unknown


def _fits(machine_cfg: dict, size: list[float]) -> str | None:
    pts = [tuple(float(c) for c in p.split("x")) for p in machine_cfg.get("printable_area", [])]
    height = float(machine_cfg.get("printable_height", 0) or 0)
    if not pts:
        return None
    bw = max(p[0] for p in pts) - min(p[0] for p in pts)
    bd = max(p[1] for p in pts) - min(p[1] for p in pts)
    w, d, h = size
    if height and h > height + 1e-6:
        return f"the model is {h:.1f} mm tall; the printer builds up to {height:g} mm"
    if not ((w <= bw and d <= bd) or (w <= bd and d <= bw)):
        return f"the model's footprint {w:.1f} x {d:.1f} mm does not fit the {bw:g} x {bd:g} mm plate"
    return None


def slice_parts(parts: dict, *, title: str, out_dir: Path, printer: str | None = None, nozzle: float | None = None,
                process: str | None = None, filaments: dict[str, str] | None = None, supports: str = "default",
                overrides: dict[str, str] | None = None, mode: str = "objects", plate: str | None = None,
                slicer: str | None = None, timeout: int = 540) -> dict:
    """Slice ``parts`` ({name: Part}); write ``out_dir/<title>.gcode.3mf``; return a report."""
    from .threemf import export_3mf

    if supports not in SUPPORT_MODES:
        raise CadError(INVALID_ARGUMENT, f"supports must be one of {SUPPORT_MODES}")
    exe = _require_bambu(slicer)
    ps = presets(str(profiles_dir(exe)))
    machine = ps.machine(printer, nozzle)
    proc = ps.process(process, machine)
    mcfg, pcfg = ps.flat("machine", machine), ps.flat("process", proc)

    # overall size check before spending time slicing, on the parts as they will print
    from . import _occ
    from .threemf import orient_for_print

    parts, orient_notes = orient_for_print(parts, mode)

    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for p in parts.values():
        a, b = _occ.bbox(p.shape)
        lo = [min(x, y) for x, y in zip(lo, a)]
        hi = [max(x, y) for x, y in zip(hi, b)]
    size = [h - l for l, h in zip(lo, hi)]
    if mode == "multimaterial" or len(parts) == 1:
        problem = _fits(mcfg, size)
        if problem:
            raise CadError(SLICE_FAILED, f"does not fit {machine}: {problem}",
                           hint="split the model, rotate it to lie flatter, or pick a bigger printer (--printer)")

    with tempfile.TemporaryDirectory(prefix="cad-slice-") as td:
        tmp = Path(td)
        src = tmp / f"{title}.3mf"
        report3 = export_3mf(parts, src, mode=mode, title=title)
        fil_cfgs, fil_used = [], []
        mapping = {k.lower(): v for k, v in (filaments or {}).items()}
        for slot in report3["materials"]:
            mat = slot["name"]
            if mat.lower() in NOT_FDM:
                raise CadError(INVALID_ARGUMENT, f"material {mat} (parts {', '.join(slot['parts'])}) is not an FDM filament",
                               hint="slicing is for FDM printing; give the parts a printable material (PLA, PETG, ...)")
            spec = mapping.get(mat.lower()) or (mat if mat.lower() in FILAMENTS else None)
            if spec is None:
                spec = "PLA"
            name = ps.filament(spec, machine)
            cfg = ps.flat("filament", name)
            cfg["filament_colour"] = [slot["color"]]
            fil_cfgs.append(cfg)
            fil_used.append({"slot": slot["slot"] + 1, "material": mat, "preset": name, "color": slot["color"],
                             "parts": slot["parts"], "assumed": spec == "PLA" and mat.lower() != "pla"
                             and mat.lower() not in mapping})
        if plate is not None and plate not in PLATES and plate not in PLATES.values():
            raise CadError(INVALID_ARGUMENT, f"unknown plate {plate!r}", hint=f"use one of {', '.join(PLATES)}")
        bed = PLATES.get(plate, plate) or mcfg.get("default_bed_type") or "Textured PEI Plate"
        pcfg["curr_bed_type"] = bed
        if supports == "off":
            pcfg["enable_support"] = "0"
        elif supports in ("auto", "on"):
            pcfg["enable_support"] = "1"
            pcfg["support_type"] = "tree(auto)" if supports == "auto" else "normal(auto)"
        configs = {"machine": mcfg, "process": pcfg, "filament": fil_cfgs}
        unknown = _apply_overrides(configs, overrides or {})
        if unknown:
            raise CadError(INVALID_ARGUMENT, f"unknown slicer setting(s): {', '.join(unknown)}",
                           hint="use Bambu Studio's setting keys, e.g. sparse_infill_density=25%, wall_loops=3, "
                                "layer_height=0.16, top_shell_layers=5")
        mfile, pfile = tmp / "machine.json", tmp / "process.json"
        mfile.write_text(json.dumps(mcfg))
        pfile.write_text(json.dumps(pcfg))
        ffiles = []
        for i, cfg in enumerate(fil_cfgs):
            f = tmp / f"filament{i + 1}.json"
            f.write_text(json.dumps(cfg))
            ffiles.append(str(f))
        outdir = tmp / "out"
        outdir.mkdir()
        cmd = [str(exe), "--slice", "0", "--load-settings", f"{mfile};{pfile}", "--load-filaments", ";".join(ffiles),
               "--orient", "0", "--arrange", "1",
               "--outputdir", str(outdir), "--export-3mf", f"{title}.gcode.3mf", str(src)]
        t0 = time.monotonic()
        try:
            proc_run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=tmp)
        except subprocess.TimeoutExpired as e:
            raise CadError(SLICE_FAILED, f"Bambu Studio did not finish slicing within {timeout}s") from e
        elapsed = time.monotonic() - t0
        result_file = outdir / "result.json"
        result = json.loads(result_file.read_text()) if result_file.exists() else {}
        sliced = outdir / f"{title}.gcode.3mf"
        plates = result.get("sliced_plates") or []
        if proc_run.returncode != 0 or not sliced.exists() or not plates:
            errors = [ln.split("]", 2)[-1].strip() for ln in proc_run.stdout.splitlines() if "[error]" in ln][-6:]
            hint = "check the model with `cad inspect`; very thin walls or parts off the plate are common causes"
            if any("does not support filament" in e for e in errors):
                hint = f"the {bed} is not rated for one of the filaments: pick another with --plate ({', '.join(PLATES)})"
            raise CadError(SLICE_FAILED, f"Bambu Studio could not slice the model: {result.get('error_string') or 'exit ' + str(proc_run.returncode)}",
                           hint=hint,
                           details={"return_code": result.get("return_code", proc_run.returncode), "slicer_errors": errors})
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / sliced.name
        shutil.copyfile(sliced, dst)
        info = _slice_info(sliced)

    plate = plates[0]
    grams = {f["id"]: f.get("total_used_g", 0.0) for f in plate.get("filaments", [])}
    for f in fil_used:
        f["grams"] = round(grams.get(f["slot"], 0.0), 2)
        f["meters"] = info.get("meters", {}).get(f["slot"])
    warnings = []
    msg = (plate.get("warning_message") or "").strip()
    if msg:
        if "cantilever" in msg or "floating" in msg.lower():
            warnings.append({"code": "NEEDS_SUPPORT", "message": msg,
                             "hint": "re-orient the part so overhangs face up / lie on the bed, or slice with --supports auto"})
        else:
            warnings.append({"code": "SLICER_WARNING", "message": msg})
    if info.get("outside"):
        warnings.append({"code": "OFF_PLATE", "message": "part of the model is outside the printable area"})
    for f in fil_used:
        if f.pop("assumed"):
            warnings.append({"code": "FILAMENT_ASSUMED", "message": f"material {f['material']!r} has no filament mapping; "
                             f"sliced as {f['preset']}", "hint": "set [print.filaments] in cad.toml or use --filament"})
    supports_used = info.get("support_used")
    seconds = float(plate.get("total_predication") or 0)
    return {
        "printer": machine, "process": proc, "plate_type": bed, "slicer": f"Bambu Studio {bambu_version(exe)}", "slicer_path": str(exe),
        "time_s": round(seconds), "time": _hms(seconds),
        "filament_g": round(sum(f["grams"] for f in fil_used), 2), "filaments": fil_used,
        "filament_changes": plate.get("filament_change_times", 0),
        "layers": _layers(dst), "layer_height": float(pcfg.get("layer_height", 0) or 0),
        "supports": {"enabled": pcfg.get("enable_support") == "1", "used": supports_used},
        "plate": {"size": _plate_size(mcfg), "objects": [o.get("name") for o in plate.get("objects", [])]},
        "time_by_feature_s": {k: round(v) for k, v in sorted(plate.get("feature_type_times", {}).items(), key=lambda kv: -kv[1]) if v >= 1},
        "model_size": [round(s, 3) for s in size], "mode": mode, "oriented_for_print": orient_notes,
        "output": str(dst), "slice_seconds": round(elapsed, 2), "warnings": warnings,
    }


def _slice_info(sliced: Path) -> dict:
    import zipfile

    out: dict = {"meters": {}}
    try:
        with zipfile.ZipFile(sliced) as z:
            text = z.read("Metadata/slice_info.config").decode()
    except (KeyError, OSError, zipfile.BadZipFile):
        return out
    out["outside"] = 'key="outside" value="true"' in text
    out["support_used"] = 'key="support_used" value="true"' in text
    for m in re.finditer(r'<filament id="(\d+)"[^>]*used_m="([\d.]+)"', text):
        out["meters"][int(m.group(1))] = float(m.group(2))
    return out


def _layers(sliced: Path) -> int | None:
    import zipfile

    try:
        with zipfile.ZipFile(sliced) as z:
            name = next(n for n in z.namelist() if n.endswith(".gcode"))
            with z.open(name) as f:
                head = f.read(4096).decode(errors="replace")
    except (StopIteration, OSError, zipfile.BadZipFile):
        return None
    m = re.search(r"total layer number: (\d+)", head)
    return int(m.group(1)) if m else None


def _plate_size(mcfg: dict) -> list[float]:
    pts = [tuple(float(c) for c in p.split("x")) for p in mcfg.get("printable_area", [])]
    if not pts:
        return []
    return [max(p[0] for p in pts) - min(p[0] for p in pts), max(p[1] for p in pts) - min(p[1] for p in pts),
            float(mcfg.get("printable_height", 0) or 0)]


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def listing(kind: str, printer: str | None = None, nozzle: float | None = None, slicer: str | None = None) -> list[str]:
    exe = _require_bambu(slicer)
    ps = presets(str(profiles_dir(exe)))
    if kind == "printers":
        return sorted({re.sub(r" \d\.\d nozzle$", "", m) for m in ps.names("machine")})
    machine = ps.machine(printer, nozzle)
    if kind == "processes":
        return sorted({n.split(" @")[0] for n in ps.names("process") if ps.compatible("process", n, machine)})
    if kind == "filaments":
        return sorted({n.split(" @")[0] for n in ps.names("filament") if ps.compatible("filament", n, machine)})
    raise CadError(INVALID_ARGUMENT, "list one of: printers, processes, filaments")
