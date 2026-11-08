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
                              "color": part.color if not isinstance(part.color, tuple) else list(part.color)}
            src = tmp / "source"
            for rel in files:
                dst = src / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.root / rel, dst)
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
                                          graph.get("persisted_refs"), graph.get("features"))
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
            d["hole_list"] = p.holes()
            if refs:
                d["references"] = p.references()
            if features:
                d["feature_graph"] = p.feature_graph()["features"]
            else:
                d["feature_list"] = [f"{f.id}:{f.type}" + ("" if f.status == "ok" else f" ({f.status})") for f in p.features]
            out["parts"][n] = d
        return out

    def measure(self, target: str | None, metrics: list[str], rev=None, *, other: str | None = None, density: float | None = None) -> dict:
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
            out["holes"] = part.holes()
        if all_m or "validity" in metrics:
            out["valid"] = part.is_valid()
            out["solids"] = part.solid_count
        if density is not None:
            out["mass_g"] = round(part.mass(density), 4)
        if other:
            _, op, oref = self.split_target(other, r)
            oshape = _occ.compound(op.faces(oref).shapes) if oref else op.shape
            d, p1, p2 = _occ.distance(part.shape, oshape)
            out["distance"] = {"to": other, "min_distance": round(d, 6), "point_on_self": _r(p1), "point_on_other": _r(p2)}
            if not oref and op is not part:
                out["distance"]["interference_volume"] = round(part.interference(op), 6)
        return out

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
        title = f"{cfg.name} r{r}" + ("" if names == list(all_parts) else f" [{', '.join(names)}]")
        scene_key = {
            "geom": [m["parts"][n]["geometry_hash"] for n in names],
            "names": names,
            "size": list(size),
            "style": style,
            "bg": list(bg),
            "annotate": annotate,
            "title": title,
            "deflection": deflection,
            "renderer": R.RENDERER_VERSION,
        }
        out = Path(out_dir) if out_dir else self.root / "renders" / f"r{r}"
        if not out.is_absolute():
            out = self.root / out
        out.mkdir(parents=True, exist_ok=True)
        prefix = "_".join(names) if len(names) <= 3 else f"{len(names)}parts"
        scene = None
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
                                         R._parse_color(all_parts[n].color, R.PALETTE[i % len(R.PALETTE)]),
                                         _occ.bbox(all_parts[n].shape))
                             for i, n in enumerate(names)]
                img, meta = R.render_one(scene, cam, size=size, style=style, background=bg, title=title,
                                         annotate_images=annotate, metadata={"revision": r, "project": cfg.name})
                R.save_png(img, cpng)
                cjson.write_text(json.dumps(meta, indent=1))
                cached = False
            dst = out / f"{prefix}_{cam.name}.png"
            shutil.copyfile(cpng, dst)
            meta = dict(meta)
            meta["image"] = dict(meta["image"], path=str(dst))
            mdst = dst.with_suffix(".json")
            mdst.write_text(json.dumps(meta, indent=1))
            results.append({"view": cam.name, "path": str(dst), "metadata": str(mdst), "cached": cached,
                            "mm_per_pixel": meta["framing"]["mm_per_pixel"], "screen_axes": meta["camera"]["screen_axes"]})
            images.append(dst)
        sheet_path = None
        if sheet and len(images) > 1:
            from PIL import Image

            sheet_path = out / f"{prefix}_sheet.png"
            R.save_png(R.contact_sheet([(p.stem, Image.open(p)) for p in images], size), sheet_path)
        return {"revision": r, "parts": names, "out_dir": str(out), "images": results,
                "sheet": str(sheet_path) if sheet_path else None}

    # ------------------------------------------------------------------ export
    def export(self, formats: list[str] | None = None, *, rev=None, parts: list[str] | None = None,
               out_dir: str | None = None, tolerance: float = 0.01) -> dict:
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
        for n in parts or list(all_parts):
            if n not in all_parts:
                raise CadError(NOT_FOUND, f"no part named '{n}'", details={"parts": list(all_parts)})
            for fmt in formats:
                ghash = m["parts"][n]["geometry_hash"]
                ext = {"step": "step", "stl": "stl", "brep": "brep"}[fmt]
                cpath = self.store.cache_dir / "exports" / f"{ghash[:32]}-{tolerance if fmt == 'stl' else ''}-{n}.{ext}"
                if not cpath.exists():
                    self.stats.bump("export_cache_misses")
                    all_parts[n].export(str(cpath), tolerance=tolerance) if fmt == "stl" else all_parts[n].export(str(cpath))
                else:
                    self.stats.bump("export_cache_hits")
                dst = out / f"{n}.{ext}"
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(cpath, dst)
                files.append({"part": n, "format": fmt, "path": str(dst), "bytes": dst.stat().st_size})
        return {"revision": r, "files": files}

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
