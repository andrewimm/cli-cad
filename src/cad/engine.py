"""Project sessions: build, inspect, render, measure, export, revisions.

The :class:`Engine` holds live session state (loaded shapes, meshes, caches) for
any number of projects.  The CLI uses it in-process for standalone runs, and the
model worker keeps one alive between commands when driven by the daemon.  Both
paths execute exactly this code, so standalone and daemon-backed runs produce
identical geometry.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np

from . import __version__, _occ
from .errors import INVALID_ARGUMENT, UNKNOWN_PARAMETER, CadError
from .export import read_brep
from .part import Part
from .project import (
    NOT_FOUND,
    ProjectConfig,
    Store,
    hash_json,
    now_iso,
    read_overlay,
    write_overlay,
)
from .runner import run_script
from .tessellate import Mesh, brep_bytes, tessellate

KERNEL = "OCCT/OCP 8.0"
LOADED_REVISIONS = 4


class Stats(dict):
    def bump(self, key: str, n: int = 1) -> None:
        self[key] = self.get(key, 0) + n


class ProjectSession:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.store = Store(self.root)
        self._loaded: OrderedDict[int, dict[str, Part]] = OrderedDict()
        self._meshes: dict[tuple[str, float | None], Mesh] = {}
        self.stats = Stats()
        self.opened_at = now_iso()

    @property
    def config(self) -> ProjectConfig:
        return ProjectConfig.load(self.root)

    # ------------------------------------------------------------------ build
    def build_key(self, params: dict) -> tuple[str, str, dict]:
        src_hash, files = self.store.source_hash()
        key = hash_json({"source": src_hash, "params": params, "cad": __version__, "kernel": KERNEL})
        return key, src_hash, files

    def build(self, overrides: dict | None = None, *, force: bool = False) -> dict:
        cfg = self.config
        entry = self.root / cfg.entry
        if not entry.exists():
            raise CadError(NOT_FOUND, f"entry script {cfg.entry} not found in {self.root}", hint="set [project].entry in cad.toml")
        params = dict(read_overlay(self.root))
        params.update(overrides or {})
        key, src_hash, files = self.build_key(params)
        t0 = time.perf_counter()
        if not force:
            existing = self.store.find_by_key(key)
            if existing is not None:
                self.stats.bump("build_cache_hits")
                self.store.set_head(existing)
                m = self.store.manifest(existing)
                self.store.write_last_build({"status": "ok", "revision": existing, "cached": True})
                return self._build_result(existing, m, cached=True, duration_ms=(time.perf_counter() - t0) * 1000)
        self.stats.bump("builds_run")
        try:
            from . import importer

            importer.set_cache_dir(self.store.cache_dir / "imports")
            out = run_script(entry, params)
        except CadError as e:
            self.store.write_last_build({"status": "failed", "error": e.to_dict(), "head": self.store.head()})
            e.details.setdefault("active_revision", self.store.head())
            raise
        warnings = list(out.warnings)
        for k in params:
            if k not in out.parameters:
                warnings.append({"code": UNKNOWN_PARAMETER, "message": f"override '{k}' is not declared by the script and was ignored"})
        geom: dict[str, dict] = {}

        def write(tmp: Path, rev: int) -> None:
            (tmp / "parts").mkdir()
            for name, part in out.parts.items():
                data = brep_bytes(part.shape)
                (tmp / "parts" / f"{name}.brep").write_bytes(data)
                ghash = hashlib.sha256(data).hexdigest()
                summary = part.summary()
                graph = part.feature_graph()
                graph["persisted_refs"] = part._persisted_refs()
                (tmp / "parts" / f"{name}.json").write_text(json.dumps(graph, indent=1, default=str))
                geom[name] = {"brep": f"parts/{name}.brep", "geometry_hash": ghash, "summary": summary,
                              "color": part.color if not isinstance(part.color, tuple) else list(part.color),
                              "reference": part.reference,
                              "print_down": list(part.print_down) if part.print_down else None,
                              "material": part.material.to_dict() if part.material else None}
            src = tmp / "source"
            for rel, digest in files.items():
                self.store.snapshot_file(self.root / rel, src / rel, digest)
            manifest = {
                "revision": rev,
                "key": key,
                "created_at": now_iso(),
                "project": self.config.name,
                "entry": cfg.entry,
                "source_hash": src_hash,
                "source_files": files,
                "params_hash": hash_json(params),
                "overrides": params,
                "parameters": {k: v.to_dict() for k, v in out.parameters.items()},
                "parts": geom,
                "build": {"duration_ms": round(out.duration_ms, 2), "stdout": out.stdout[-20000:],
                          "stderr": out.stderr[-20000:], "warnings": warnings},
                "cad_version": __version__,
                "kernel": KERNEL,
            }
            (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))

        rev = self.store.publish(write)
        self._remember(rev, out.parts)
        self.store.write_last_build({"status": "ok", "revision": rev, "cached": False})
        return self._build_result(rev, self.store.manifest(rev), cached=False, duration_ms=(time.perf_counter() - t0) * 1000)

    def _build_result(self, rev: int, m: dict, *, cached: bool, duration_ms: float) -> dict:
        return {
            "revision": rev,
            "cached": cached,
            "duration_ms": round(duration_ms, 2),
            "parts": {n: _compact(p["summary"]) for n, p in m["parts"].items()},
            "parameters": {k: v["value"] for k, v in m.get("parameters", {}).items()},
            "warnings": m["build"]["warnings"],
            "stdout": m["build"]["stdout"],
        }

    # ------------------------------------------------------------------ loading
    def _remember(self, rev: int, parts: dict[str, Part]) -> None:
        self._loaded[rev] = parts
        self._loaded.move_to_end(rev)
        while len(self._loaded) > LOADED_REVISIONS:
            self._loaded.popitem(last=False)

    def resolve_rev(self, rev: int | str | None) -> int:
        if rev is None or rev == "head" or rev == "HEAD":
            h = self.store.head()
            if h is None:
                raise CadError(NOT_FOUND, "the project has no successful revision yet", hint="run `cad build`")
            return h
        if isinstance(rev, str):
            if rev.startswith("-") and rev[1:].isdigit():
                nums = self.store.revision_numbers()
                i = len(nums) - 1 - int(rev[1:])
                if i < 0:
                    raise CadError(NOT_FOUND, f"no revision {rev}")
                return nums[i]
            if not rev.isdigit():
                raise CadError(INVALID_ARGUMENT, f"revision must be a number, 'head' or -N, got {rev!r}")
            rev = int(rev)
        self.store.manifest(rev)
        return rev

    def parts(self, rev: int | str | None = None) -> tuple[int, dict[str, Part]]:
        r = self.resolve_rev(rev)
        if r in self._loaded:
            self.stats.bump("model_memory_hits")
            self._loaded.move_to_end(r)
            return r, self._loaded[r]
        self.stats.bump("model_disk_loads")
        m = self.store.manifest(r)
        d = self.store.revision_dir(r)
        parts = {}
        for name, info in m["parts"].items():
            shape = read_brep(d / info["brep"])
            gpath = d / "parts" / f"{name}.json"
            graph = json.loads(gpath.read_text()) if gpath.exists() else {}
            color = info.get("color")
            parts[name] = Part._rehydrate(name, shape, tuple(color) if isinstance(color, list) else color,
                                          graph.get("persisted_refs"), graph.get("features"), info.get("reference", False),
                                          info.get("material"), info.get("print_down"))
        self._remember(r, parts)
        return r, parts

    def part(self, name: str | None, rev=None) -> tuple[int, Part]:
        r, parts = self.parts(rev)
        if name is None:
            if len(parts) == 1:
                return r, next(iter(parts.values()))
            raise CadError(INVALID_ARGUMENT, f"revision {r} has {len(parts)} parts; name one", details={"parts": list(parts)})
        if name not in parts:
            raise CadError(NOT_FOUND, f"no part named '{name}' in revision {r}", details={"parts": list(parts)})
        return r, parts[name]

    def split_target(self, target: str | None, rev=None) -> tuple[int, Part, str | None]:
        """'part', 'part.ref.name' or (single-part projects) 'ref.name'."""
        r, parts = self.parts(rev)
        if target is None or target in parts:
            return (*self.part(target, r), None)
        head, _, rest = target.partition(".")
        if head in parts:
            return r, parts[head], rest or None
        if len(parts) == 1:
            return r, next(iter(parts.values())), target
        raise CadError(NOT_FOUND, f"cannot resolve '{target}': no such part", details={"parts": list(parts)})

    # ------------------------------------------------------------------ queries
    def inspect(self, rev=None, part: str | None = None, *, features: bool = False, refs: bool = False) -> dict:
        r, parts = self.parts(rev)
        m = self.store.manifest(r)
        sel = {part: parts[part]} if part else parts
        if part and part not in parts:
            raise CadError(NOT_FOUND, f"no part named '{part}'", details={"parts": list(parts)})
        out = {
            "project": self.config.name,
            "root": str(self.root),
            "revision": r,
            "head": self.store.head(),
            "created_at": m["created_at"],
            "parameters": m.get("parameters", {}),
            "parts": {},
        }
        for n, p in sel.items():
            d = p.summary()
            d["hole_list"] = p.find_holes()
            if refs:
                d["references"] = p.references()
            if features:
                d["feature_graph"] = p.feature_graph()["features"]
            else:
                d["feature_list"] = [f"{f.id}:{f.type}" + ("" if f.status == "ok" else f" ({f.status})") for f in p.features]
            out["parts"][n] = d
        return out

    def measure(self, target: str | None, metrics: list[str], rev=None, *, other: str | None = None, density: float | None = None,
                section: tuple[str, float] | None = None) -> dict:
        if target is None:
            r, all_parts = self.parts(rev)
            if len(all_parts) > 1:  # no target in a multi-part model: measure every part
                if section:
                    raise CadError(INVALID_ARGUMENT, "--section needs a part name", hint="e.g. cad measure servo --section z=-5",
                                   details={"parts": list(all_parts)})
                return {"revision": r, "parts": {n: self.measure(n, metrics, r, other=other if other != n else None, density=density)
                                                  for n in all_parts}}
        r, part, ref = self.split_target(target, rev)
        out: dict[str, Any] = {"revision": r, "part": part.name}
        all_m = not metrics
        if ref:
            sel = part.faces(ref) if part._ref_kind.get(ref, "face") == "face" else part.edges(ref)
            shapes = sel.shapes
            comp = _occ.compound(shapes)
            out["reference"] = ref
            out["kind"] = sel.kind
            out["count"] = len(shapes)
            lo, hi = _occ.bbox(comp)
            if all_m or "bbox" in metrics:
                out["bbox"] = {"min": _r(lo), "max": _r(hi), "size": _r([b - a for a, b in zip(lo, hi)])}
            if sel.kind == "face" and (all_m or "area" in metrics):
                out["area"] = round(_occ.area(comp), 6)
            if sel.kind == "edge" and (all_m or "length" in metrics):
                out["length"] = round(_occ.length(comp), 6)
            out["entities"] = sel.info()
            if other:
                out["distance"] = self._distance(comp, other, r)
            return out
        if section:
            from .analysis import cross_section

            out["section"] = cross_section(part.shape, *section)
            if all_m:
                return out
        if all_m or "volume" in metrics:
            out["volume"] = round(part.volume, 6)
        if all_m or "area" in metrics:
            out["area"] = round(part.area, 6)
        if all_m or "bbox" in metrics:
            out["bbox"] = part.bbox.to_dict()
        if all_m or "com" in metrics:
            out["center_of_mass"] = _r(part.center_of_mass)
        if all_m or "holes" in metrics:
            out["holes"] = part.find_holes()
        if all_m or "validity" in metrics:
            out["valid"] = part.is_valid()
            out["solids"] = part.solid_count
        if "thickness" in metrics:
            out["wall_thickness"] = part.wall_thickness()
        if density is not None:
            out["mass_g"] = round(part.mass(density), 4)
        if other:
            out["distance"] = self._distance(part.shape, other, r)
            _, op, oref = self.split_target(other, r)
            if not oref and op is not part:
                out["distance"]["interference_volume"] = round(part.interference(op), 6)
        return out

    def _distance(self, shape, other: str, rev: int) -> dict:
        _, op, oref = self.split_target(other, rev)
        if oref:
            osel = op.faces(oref) if op._ref_kind.get(oref, "face") == "face" else op.edges(oref)
            oshape = _occ.compound(osel.shapes)
        else:
            oshape = op.shape
        d, p1, p2 = _occ.distance(shape, oshape)
        return {"to": other, "min_distance": round(d, 6), "point_on_self": _r(p1), "point_on_other": _r(p2)}

    def query(self, target: str | None, expr: str, rev=None) -> dict:
        r, part, ref = self.split_target(target, rev)
        if ref:
            expr = f"faces({ref!r})" if not expr else expr
        env = {"part": part, "faces": part.faces, "edges": part.edges}
        try:
            val = eval(expr, {"__builtins__": {}}, env)  # trusted local use; see docs/SECURITY.md
        except CadError:
            raise
        except Exception as e:
            raise CadError(INVALID_ARGUMENT, f"cannot evaluate query {expr!r}: {type(e).__name__}: {e}",
                           hint="examples: \"faces().facing('+z')\", \"edges().vertical().convex()\", \"faces().holes(3.2)\"") from e
        if hasattr(val, "info") and hasattr(val, "description"):
            return {"revision": r, "part": part.name, "selection": val.description, "kind": val.kind, "count": len(val), "items": val.info()}
        return {"revision": r, "part": part.name, "expression": expr, "value": _jsonify(val)}

    # ------------------------------------------------------------------ meshes & renders
    def mesh(self, rev: int, name: str, part: Part, deflection: float | None = None) -> Mesh:
        ghash = self.store.manifest(rev)["parts"][name]["geometry_hash"]
        key = (ghash, deflection)
        if key in self._meshes:
            self.stats.bump("mesh_memory_hits")
            return self._meshes[key]
        path = self.store.cache_dir / "meshes" / f"{ghash[:32]}-{deflection or 'auto'}.npz"
        if path.exists():
            try:
                m = Mesh.from_npz(path)
                self.stats.bump("mesh_disk_hits")
                self._meshes[key] = m
                return m
            except Exception:
                path.unlink(missing_ok=True)
        self.stats.bump("mesh_computed")
        m = tessellate(part.shape, deflection)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.stem + f".tmp{os.getpid()}.npz")
        m.to_npz(tmp)
        os.replace(tmp, path)
        self._meshes[key] = m
        return m

    def render(
        self,
        views: list[str] | str | None = None,
        *,
        rev=None,
        parts: list[str] | None = None,
        size: tuple[int, int] | None = None,
        style: str = "shaded_edges",
        background: str = "#ffffff",
        out_dir: str | None = None,
        annotate: bool = True,
        sheet: bool = True,
        deflection: float | None = None,
        section: str | None = None,
    ) -> dict:
        from . import renderer as R

        r, all_parts = self.parts(rev)
        m = self.store.manifest(r)
        names = parts or list(all_parts)
        for n in names:
            if n not in all_parts:
                raise CadError(NOT_FOUND, f"no part named '{n}' in revision {r}", details={"parts": list(all_parts)})
        cfg = self.config
        size = size or cfg.size
        cams = R.parse_views(views or cfg.views)
        bg = R._parse_color(background, (1.0, 1.0, 1.0))
        title = f"{' + '.join(names)}  (rev {r})"
        if section:
            from .section import parse_section

            parse_section(section)  # validate early
        scene_key = {
            "geom": [m["parts"][n]["geometry_hash"] for n in names],
            "names": names,
            "size": list(size),
            "style": style,
            "bg": list(bg),
            "annotate": annotate,
            "title": title,
            "deflection": deflection,
            "section": section,
            "renderer": R.RENDERER_VERSION,
        }
        out = Path(out_dir) if out_dir else self.root / "renders" / f"r{r}"
        if not out.is_absolute():
            out = self.root / out
        out.mkdir(parents=True, exist_ok=True)
        prefix = "_".join(names) if len(names) <= 3 else f"{len(names)}parts"
        scene = None
        full_bounds = None
        section_cache: dict = {}
        results, images = [], []
        for cam in cams:
            vkey = hash_json({**scene_key, "eye": cam.eye.round(9).tolist(), "up": cam.up.round(9).tolist()})
            cdir = self.store.cache_dir / "renders" / vkey[:40]
            cpng, cjson = cdir / "image.png", cdir / "meta.json"
            if cpng.exists() and cjson.exists():
                self.stats.bump("render_cache_hits")
                meta = json.loads(cjson.read_text())
                cached = True
            else:
                self.stats.bump("render_cache_misses")
                if scene is None:
                    scene = [R.SceneItem(n, self.mesh(r, n, all_parts[n], deflection),
                                         R._parse_color(all_parts[n].color, R.REFERENCE_COLOR if all_parts[n].reference
                                                        else R.PALETTE[i % len(R.PALETTE)]),
                                         _occ.bbox(all_parts[n].shape))
                             for i, n in enumerate(names)]
                if full_bounds is None:
                    full_bounds = R.scene_bounds(scene)
                view_scene, sec = scene, None
                if section:
                    view_scene, sec = R.section_scene([(n, all_parts[n].shape, all_parts[n].color, all_parts[n].reference) for n in names],
                                                      cam, section, deflection, section_cache)
                img, meta = R.render_one(view_scene, cam, size=size, style=style, background=bg, title=title,
                                         fit_bounds=full_bounds, section=sec,
                                         annotate_images=annotate, metadata={"revision": r, "project": cfg.name})
                R.save_png(img, cpng)
                cjson.write_text(json.dumps(meta, indent=1))
                cached = False
            suffix = f"_section_{R._safe_name(section)}" if section else ""
            dst = out / f"{prefix}_{cam.name}{suffix}.png"
            shutil.copyfile(cpng, dst)
            meta = dict(meta)
            meta["image"] = dict(meta["image"], path=str(dst))
            mdst = dst.with_suffix(".json")
            mdst.write_text(json.dumps(meta, indent=1))
            results.append({"view": cam.name + (f" section {section}" if section else ""), "path": str(dst), "metadata": str(mdst), "cached": cached,
                            "mm_per_pixel": meta["framing"]["mm_per_pixel"], "screen_axes": meta["camera"]["screen_axes"]})
            images.append(dst)
        sheet_path = None
        if sheet and len(images) > 1:
            from PIL import Image

            sheet_path = out / f"{prefix}_sheet{'_section_' + R._safe_name(section) if section else ''}.png"
            R.save_png(R.contact_sheet([(p.stem, Image.open(p)) for p in images], size), sheet_path)
        return {"revision": r, "parts": names, "out_dir": str(out), "images": results,
                "sheet": str(sheet_path) if sheet_path else None}

    # ------------------------------------------------------------------ export
    def export(self, formats: list[str] | None = None, *, rev=None, parts: list[str] | None = None,
               out_dir: str | None = None, tolerance: float = 0.01, threemf_mode: str | None = None) -> dict:
        from .export import FORMATS

        r, all_parts = self.parts(rev)
        m = self.store.manifest(r)
        formats = formats or self.config.export_formats
        valid = sorted(set(FORMATS.values()))
        for f in formats:
            if f not in valid:
                raise CadError(INVALID_ARGUMENT, f"unknown export format {f!r}", hint=f"use one of {valid}")
        out = Path(out_dir) if out_dir else self.root / "out" / f"r{r}"
        if not out.is_absolute():
            out = self.root / out
        files = []
        skipped = [] if parts else [n for n, p in all_parts.items() if p.reference]
        chosen = parts or [n for n in all_parts if n not in skipped]
        threemf = None
        if "3mf" in formats:
            # one 3MF holds every part (with its material) - that is the point of the format
            from .threemf import export_3mf

            for n in chosen:
                if n not in all_parts:
                    raise CadError(NOT_FOUND, f"no part named '{n}'", details={"parts": list(all_parts)})
            threemf_mode = threemf_mode or self.config.threemf_mode
            dst = out / f"{self.config.name}.3mf"
            threemf = export_3mf({n: all_parts[n] for n in chosen}, dst, mode=threemf_mode, tolerance=tolerance,
                                 title=self.config.name)
            files.append({"part": ",".join(chosen), "format": "3mf", "path": str(dst), "bytes": threemf["bytes"],
                          "materials": threemf["materials"], "mode": threemf_mode})
            formats = [f for f in formats if f != "3mf"]
        for n in chosen:
            if n not in all_parts:
                raise CadError(NOT_FOUND, f"no part named '{n}'", details={"parts": list(all_parts)})
            for fmt in formats:
                ghash = m["parts"][n]["geometry_hash"]
                ext = {"step": "step", "stl": "stl", "brep": "brep"}[fmt]
                # STL is for printing: it is written in the print orientation (Part.print_on); STEP keeps the design pose
                down = all_parts[n].print_down if fmt == "stl" else None
                tag = "" if not down else "-p" + hashlib.sha256(repr(down).encode()).hexdigest()[:8]
                cpath = self.store.cache_dir / "exports" / f"{ghash[:32]}-{tolerance if fmt == 'stl' else ''}{tag}-{n}.{ext}"
                if not cpath.exists():
                    self.stats.bump("export_cache_misses")
                    src_part = all_parts[n].as_printed() if down else all_parts[n]
                    src_part.export(str(cpath), tolerance=tolerance) if fmt == "stl" else src_part.export(str(cpath))
                else:
                    self.stats.bump("export_cache_hits")
                dst = out / f"{n}.{ext}"
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(cpath, dst)
                entry = {"part": n, "format": fmt, "path": str(dst), "bytes": dst.stat().st_size}
                if down:
                    entry["oriented_for_print"] = True
                if fmt == "stl":
                    from .export import stl_check

                    entry["printability"] = stl_check(dst)
                files.append(entry)
        out = {"revision": r, "files": files}
        if threemf and threemf["warnings"]:
            out["warnings"] = threemf["warnings"]
        if skipped:
            out["skipped_reference_parts"] = skipped
        return out

    # ------------------------------------------------------------------ slicing
    def slice(self, *, rev=None, parts: list[str] | None = None, printer: str | None = None, nozzle: float | None = None,
              process: str | None = None, filaments: dict[str, str] | None = None, supports: str | None = None,
              overrides: dict[str, str] | None = None, threemf_mode: str | None = None, out_dir: str | None = None,
              plate: str | None = None) -> dict:
        from . import slicer

        r, all_parts = self.parts(rev)
        m = self.store.manifest(r)
        cfg = self.config.raw.get("print", {})
        skipped = [] if parts else [n for n, p in all_parts.items() if p.reference]
        chosen = parts or [n for n in all_parts if n not in skipped]
        for n in chosen:
            if n not in all_parts:
                raise CadError(NOT_FOUND, f"no part named '{n}'", details={"parts": list(all_parts)})
        settings = {
            "printer": printer or cfg.get("printer"), "nozzle": nozzle or cfg.get("nozzle"),
            "process": process or cfg.get("process"),
            "filaments": {**cfg.get("filaments", {}), **(filaments or {})},
            "supports": supports or cfg.get("supports", "default"),
            "overrides": {**{k: str(v) for k, v in cfg.get("settings", {}).items()}, **(overrides or {})},
            "mode": threemf_mode or self.config.threemf_mode,
            "plate": plate or cfg.get("plate"),
        }
        exe = slicer.find_bambu(cfg.get("slicer"))
        key = hash_json({"parts": {n: m["parts"][n]["geometry_hash"] for n in chosen},
                         "print_down": {n: all_parts[n].print_down for n in chosen},
                         "materials": {n: (all_parts[n].material.to_dict() if all_parts[n].material else None) for n in chosen},
                         "settings": settings, "slicer": slicer.bambu_version(exe) if exe else None, "cad": __version__})
        cache = self.store.cache_dir / "slices" / key[:32]
        out = Path(out_dir) if out_dir else self.root / "out" / f"r{r}"
        if not out.is_absolute():
            out = self.root / out
        if (cache / "report.json").exists():
            self.stats.bump("slice_cache_hits")
            report = json.loads((cache / "report.json").read_text())
            out.mkdir(parents=True, exist_ok=True)
            dst = out / Path(report["output"]).name
            shutil.copyfile(cache / Path(report["output"]).name, dst)
            report["output"], report["cached"] = str(dst), True
        else:
            report = slicer.slice_parts({n: all_parts[n] for n in chosen}, title=self.config.name, out_dir=cache,
                                        printer=settings["printer"], nozzle=settings["nozzle"], process=settings["process"],
                                        filaments=settings["filaments"], supports=settings["supports"],
                                        overrides=settings["overrides"], mode=settings["mode"], plate=settings["plate"],
                                        slicer=cfg.get("slicer"))
            (cache / "report.json").write_text(json.dumps(report))
            out.mkdir(parents=True, exist_ok=True)
            dst = out / Path(report["output"]).name
            shutil.copyfile(report["output"], dst)
            report["output"], report["cached"] = str(dst), False
        report = {"revision": r, "parts": chosen, **report}
        if skipped:
            report["skipped_reference_parts"] = skipped
        return report

    # ------------------------------------------------------------------ design checks
    def clearance(self, rev=None, *, parts: list[str] | None = None, min_distance: float | None = None,
                  allow_contact: bool = False) -> dict:
        from .analysis import clearance_matrix

        r, all_parts = self.parts(rev)
        sel = {n: all_parts[n] for n in (parts or all_parts)}
        if len(sel) < 2:
            raise CadError(INVALID_ARGUMENT, "clearance needs at least two parts (add a reference=True part for an envelope)")
        out = clearance_matrix(sel, min_distance, allow_contact=allow_contact)
        out["revision"] = r
        out["references"] = [n for n, p in sel.items() if p.reference]
        return out

    def sweep(self, parameter: str, values: list, *, views: str | None = None, size=None, min_distance: float | None = None,
              section: str | None = None, allow_contact: bool = False) -> dict:
        """Rebuild at each parameter value, check clearances (and render), then restore the active revision."""
        from .analysis import clearance_matrix

        head = self.store.head()
        rows = []
        try:
            for v in values:
                b = self.build({parameter: v})
                r, parts = self.parts(b["revision"])
                row: dict[str, Any] = {"value": v, "revision": r}
                if len(parts) >= 2:
                    cm = clearance_matrix(parts, min_distance, allow_contact=allow_contact)
                    row["closest_pair"] = cm["pairs"][0]
                    if min_distance is not None:
                        row["violations"] = cm["violations"]
                row["warnings"] = b.get("warnings", [])
                if views:
                    rr = self.render(views, rev=r, size=size, sheet=False, section=section)
                    row["images"] = [i["path"] for i in rr["images"]]
                rows.append(row)
        finally:
            if head is not None:
                self.store.set_head(head)
        out: dict[str, Any] = {"parameter": parameter, "values": values, "results": rows, "head": head}
        if min_distance is not None:
            out["min_required"] = min_distance
            out["ok"] = all(not row.get("violations") for row in rows)
        return out

    # ------------------------------------------------------------------ params
    def params(self) -> dict:
        overlay = read_overlay(self.root)
        head = self.store.head()
        declared = self.store.manifest(head).get("parameters", {}) if head else {}
        return {"overlay": overlay, "declared": declared, "revision": head}

    def set_params(self, values: dict[str, Any], *, force: bool = False) -> dict:
        head = self.store.head()
        declared = self.store.manifest(head).get("parameters", {}) if head else {}
        if declared and not force:
            import difflib

            for k, v in values.items():
                if k not in declared:
                    sugg = difflib.get_close_matches(k, list(declared), n=3)
                    raise CadError(UNKNOWN_PARAMETER, f"parameter '{k}' is not declared by the model",
                                   hint=(f"did you mean {', '.join(sugg)}? " if sugg else "") + "use --force to set it anyway",
                                   details={"declared": sorted(declared)})
                d = declared[k]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if (d.get("min") is not None and v < d["min"]) or (d.get("max") is not None and v > d["max"]):
                        raise CadError("PARAMETER_OUT_OF_RANGE", f"{k}={v} is outside [{d.get('min')}, {d.get('max')}]")
        overlay = read_overlay(self.root)
        overlay.update(values)
        write_overlay(self.root, overlay)
        return {"overlay": overlay}

    def unset_params(self, names: list[str]) -> dict:
        overlay = read_overlay(self.root)
        missing = [n for n in names if n not in overlay]
        for n in names:
            overlay.pop(n, None)
        write_overlay(self.root, overlay)
        return {"overlay": overlay, "not_set": missing}

    # ------------------------------------------------------------------ revisions
    def revisions(self, limit: int = 50) -> dict:
        head = self.store.head()
        out = []
        for r in self.store.revision_numbers()[-limit:]:
            m = self.store.manifest(r)
            out.append({
                "revision": r,
                "head": r == head,
                "created_at": m["created_at"],
                "source_hash": m["source_hash"][:12],
                "overrides": m.get("overrides", {}),
                "parts": {n: {"volume": round(p["summary"].get("volume", 0), 3), "bbox": p["summary"].get("bbox", {}).get("size")}
                          for n, p in m["parts"].items()},
            })
        return {"head": head, "revisions": out, "last_build": self.store.last_build()}

    def checkout(self, rev) -> dict:
        r = self.resolve_rev(rev)
        self.store.set_head(r)
        return {"head": r, "note": "active revision changed; source files were not modified (use `cad restore` to restore sources)"}

    def restore(self, rev, *, force: bool = False) -> dict:
        r = self.resolve_rev(rev)
        m = self.store.manifest(r)
        src = self.store.revision_dir(r) / "source"
        _, current = self.store.source_hash()
        changed = [f for f, h in m["source_files"].items() if current.get(f) != h]
        if not changed:
            return {"revision": r, "restored": [], "note": "sources already match"}
        if not force:
            raise CadError(INVALID_ARGUMENT, f"restoring revision {r} would overwrite {len(changed)} file(s)",
                           hint="re-run with --force to overwrite", details={"files": changed})
        for f in changed:
            dst = self.root / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / f, dst)
        overlay = m.get("overrides", {})
        write_overlay(self.root, overlay)
        self.store.set_head(r)
        return {"revision": r, "restored": changed, "params": overlay}

    def diff(self, a, b) -> dict:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut

        ra, rb = self.resolve_rev(a), self.resolve_rev(b)
        ma, mb = self.store.manifest(ra), self.store.manifest(rb)
        _, pa = self.parts(ra)
        _, pb = self.parts(rb)
        fa, fb = ma["source_files"], mb["source_files"]
        out: dict[str, Any] = {
            "a": ra,
            "b": rb,
            "sources": {
                "changed": sorted(f for f in set(fa) & set(fb) if fa[f] != fb[f]),
                "added": sorted(set(fb) - set(fa)),
                "removed": sorted(set(fa) - set(fb)),
            },
            "parameters": {
                k: {"a": ma["parameters"].get(k, {}).get("value"), "b": mb["parameters"].get(k, {}).get("value")}
                for k in sorted(set(ma.get("parameters", {})) | set(mb.get("parameters", {})))
                if ma["parameters"].get(k, {}).get("value") != mb["parameters"].get(k, {}).get("value")
            },
            "parts": {},
        }
        for n in sorted(set(pa) | set(pb)):
            if n not in pa or n not in pb:
                out["parts"][n] = {"status": "added" if n in pb else "removed"}
                continue
            sa, sb = ma["parts"][n]["summary"], mb["parts"][n]["summary"]
            d: dict[str, Any] = {"geometry_changed": ma["parts"][n]["geometry_hash"] != mb["parts"][n]["geometry_hash"]}
            for k in ("volume", "area", "faces", "edges", "holes", "solids"):
                if sa.get(k) != sb.get(k):
                    d[k] = {"a": sa.get(k), "b": sb.get(k)}
            if sa["bbox"]["size"] != sb["bbox"]["size"]:
                d["bbox_size"] = {"a": sa["bbox"]["size"], "b": sb["bbox"]["size"]}
            ida = {f.id: f.type for f in pa[n].features}
            idb = {f.id: f.type for f in pb[n].features}
            if ida != idb:
                d["features"] = {"added": sorted(set(idb) - set(ida)), "removed": sorted(set(ida) - set(idb))}
            if d["geometry_changed"]:
                try:
                    d["volume_removed"] = round(_occ.volume(BRepAlgoAPI_Cut(pa[n].shape, pb[n].shape).Shape()), 6)
                    d["volume_added"] = round(_occ.volume(BRepAlgoAPI_Cut(pb[n].shape, pa[n].shape).Shape()), 6)
                except Exception:
                    pass
            out["parts"][n] = d
        return out

    def status(self) -> dict:
        head = self.store.head()
        return {
            "project": self.config.name,
            "root": str(self.root),
            "entry": self.config.entry,
            "head": head,
            "revisions": len(self.store.revision_numbers()),
            "last_build": self.store.last_build(),
            "session": {"opened_at": self.opened_at, "loaded_revisions": list(self._loaded),
                        "meshes_in_memory": len(self._meshes), "stats": dict(self.stats), "pid": os.getpid()},
        }


class Engine:
    def __init__(self):
        self.sessions: dict[Path, ProjectSession] = {}

    def session(self, root: Path) -> ProjectSession:
        root = root.resolve()
        if root not in self.sessions:
            self.sessions[root] = ProjectSession(root)
        return self.sessions[root]


# --------------------------------------------------------------------------- helpers


def _r(v) -> list[float]:
    return [round(float(c), 6) + 0.0 for c in v]


def _compact(summary: dict) -> dict:
    keys = ("valid", "solids", "volume", "faces", "holes")
    d = {k: summary.get(k) for k in keys}
    d["bbox_size"] = summary.get("bbox", {}).get("size")
    return d


def _jsonify(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonify(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonify(x) for k, x in v.items()}
    if isinstance(v, np.ndarray):
        return v.tolist()
    if hasattr(v, "to_dict"):
        return v.to_dict()
    return repr(v)
