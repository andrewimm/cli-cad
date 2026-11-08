"""The ``cad`` command line.

``main(argv, cwd)`` is a pure function returning ``(exit_code, stdout, stderr)``
so it can run in-process (standalone mode, ``python -m cad``) or inside the
long-lived model worker that the daemon talks to.  The Rust ``cad`` binary is a
thin client that forwards argv to the daemon (or execs this module directly with
``--no-daemon``).

Exit codes (stable, see ``cad capabilities``):

  0 success
  1 internal error
  2 usage error (bad arguments, unknown parameter)
  3 model error (script raised, geometry operation failed, no parts)
  4 validation failed (assert_valid / checks)
  5 not found (project, revision, part, reference)
  6 worker crashed (daemon only)
  7 timeout (daemon only)
  8 daemon unavailable
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from . import __version__
from .errors import CadError

EXIT = {"ok": 0, "internal": 1, "usage": 2, "model": 3, "validation": 4, "not_found": 5,
        "worker_crashed": 6, "timeout": 7, "daemon_unavailable": 8}

_CODE_EXIT = {
    "VALIDATION_FAILED": 4,
    "NOT_FOUND": 5,
    "UNKNOWN_REFERENCE": 5,
    "REFERENCE_LOST": 3,
    "NO_PROJECT": 5,
    "UNKNOWN_PARAMETER": 2,
    "PARAMETER_OUT_OF_RANGE": 2,
    "USAGE": 2,
}

# --------------------------------------------------------------------------- command table

COMMANDS: dict[str, dict] = {
    "init": {"summary": "Create a new project (cad.toml + model.py template)", "project": False},
    "open": {"summary": "Make a project (or script's directory) the current project for later commands", "project": False},
    "status": {"summary": "Show the current project, active revision, last build and session stats", "project": True},
    "build": {"summary": "Run the model script and publish an immutable revision (cached if inputs are unchanged)", "project": True},
    "run": {"summary": "Standalone: run a script once, optionally render/export, no project or daemon state", "project": False},
    "inspect": {"summary": "Summarise parts of a revision: validity, bbox, volume, holes, features, references", "project": True},
    "measure": {"summary": "Measure a part or named reference: volume, area, bbox, com, holes, distance", "project": True},
    "query": {"summary": "Evaluate a selection expression, e.g. \"faces().facing('+z')\", and list matches", "project": True},
    "render": {"summary": "Render PNG views (iso, front, back, left, right, top, bottom, az=..,el=.., dir=x,y,z)", "project": True},
    "export": {"summary": "Export STEP / STL / 3MF (with materials) / BREP for a revision (reference parts are skipped)", "project": True},
    "materials": {"summary": "List built-in materials (density, colour) for Part(..., material=...)", "project": False},
    "slice": {"summary": "Slice with Bambu Studio: print time, filament grams per material, layers, supports, warnings; writes a .gcode.3mf", "project": True},
    "info": {"summary": "What a STEP / IGES / STL / BREP file contains: bodies, names, sizes, units (before importing it)", "project": False},
    "fonts": {"summary": "List installed fonts usable for text (Profile.text, Part.emboss / engrave)", "project": False},
    "clearance": {"summary": "Clear / touching / overlap with minimum distance for every pair of parts (and per-face gaps for reference envelopes)", "project": True},
    "sweep": {"summary": "Rebuild over a range of one parameter, checking clearances (and rendering) at each value", "project": True},
    "params": {"summary": "List declared parameters and the override overlay", "project": True},
    "set": {"summary": "Override parameters (writes params.toml) and rebuild", "project": True},
    "unset": {"summary": "Remove parameter overrides and rebuild", "project": True},
    "revisions": {"summary": "List revisions and the last build attempt", "project": True},
    "diff": {"summary": "Compare two revisions: sources, parameters, geometry deltas", "project": True},
    "checkout": {"summary": "Change the active revision (does not touch source files)", "project": True},
    "restore": {"summary": "Restore source files and parameters from a revision (explicit, needs --force)", "project": True},
    "capabilities": {"summary": "Machine-readable description of commands, views, formats and exit codes", "project": False},
    "schema": {"summary": "JSON shapes of command results and errors", "project": False},
    "examples": {"summary": "List, show or copy bundled example projects", "project": False},
    "docs": {"summary": "Print the API reference (Markdown)", "project": False},
    "help": {"summary": "Help for a command (use --json for machine-readable)", "project": False},
}


class UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # never sys.exit from inside the worker
        raise UsageError(f"{self.prog}: {message}")

    def exit(self, status=0, message=None):
        if message:
            raise UsageError(message)
        raise _HelpShown()


class _HelpShown(Exception):
    pass


def _parser() -> _Parser:
    p = _Parser(prog="cad", description="Agent-first parametric CAD: Python scripts in, exact solids, renders and STEP/STL out.",
                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=GETTING_STARTED)
    p.add_argument("--version", action="store_true", help="print version and exit")
    sub = p.add_subparsers(dest="command", parser_class=_Parser)

    def cmd(name, **kw):
        sp = sub.add_parser(name, help=COMMANDS[name]["summary"], description=COMMANDS[name]["summary"], **kw)
        sp.add_argument("--json", action="store_true", help="machine-readable JSON output")
        if COMMANDS[name]["project"]:
            sp.add_argument("--project", "-C", help="project directory (default: cwd ancestors, then the opened project)")
        return sp

    s = cmd("init")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--name")
    s.add_argument("--example", help="start from a bundled example (see `cad examples list`)")

    s = cmd("open")
    s.add_argument("path", help="project directory or a model .py file")

    cmd("status")

    s = cmd("build")
    s.add_argument("--param", "-p", action="append", default=[], metavar="NAME=VALUE", help="one-off override (not saved)")
    s.add_argument("--force", action="store_true", help="rebuild even if an identical revision exists")

    s = cmd("run")
    s.add_argument("script")
    s.add_argument("--param", "-p", action="append", default=[], metavar="NAME=VALUE")
    s.add_argument("--render", metavar="VIEWS", help="comma-separated views, e.g. iso,front or all")
    s.add_argument("--export", metavar="FORMATS", help="comma-separated: step,stl,3mf,brep")
    s.add_argument("--3mf-mode", dest="threemf_mode", default="objects", choices=["objects", "multimaterial"])
    s.add_argument("--out", help="output directory (default ./out/<script-name>)")
    s.add_argument("--size", default="1024x768")
    s.add_argument("--style", default="shaded_edges", choices=["shaded_edges", "shaded", "lines"])
    s.add_argument("--section", metavar="PLANE", help="render a cut-away view, e.g. y=0")

    s = cmd("inspect")
    s.add_argument("part", nargs="?")
    s.add_argument("--revision", "-r")
    s.add_argument("--features", action="store_true", help="include the full feature graph")
    s.add_argument("--refs", action="store_true", help="include named references")

    s = cmd("measure")
    s.add_argument("target", nargs="?", help="part, part.reference (e.g. bracket.base.top), or reference in single-part projects")
    s.add_argument("--revision", "-r")
    for m in ("volume", "area", "bbox", "com", "holes", "validity", "length"):
        s.add_argument(f"--{m}", action="store_true")
    s.add_argument("--thickness", action="store_true", help="sampled wall thickness with the thinnest locations")
    s.add_argument("--distance", metavar="OTHER", help="minimum distance (and interference) to another part or reference")
    s.add_argument("--density", type=float, metavar="G_PER_CM3", help="report mass for this density")
    s.add_argument("--section", metavar="AXIS=VALUE",
                   help="cross-section at a plane, e.g. z=-5: regions with outlines (rectangles, circles) and holes")

    s = cmd("query")
    s.add_argument("target", nargs="?", help="part name (optional for single-part projects)")
    s.add_argument("expr", nargs="?", default="", help="selection expression, e.g. \"edges().vertical().convex()\"")
    s.add_argument("--revision", "-r")

    s = cmd("render")
    s.add_argument("--views", "-v", help="e.g. iso,front,right,top | all | az=30,el=20 | dir=1,-1,0.5 (default from cad.toml)")
    s.add_argument("--revision", "-r")
    s.add_argument("--part", action="append", help="render only these parts (repeatable)")
    s.add_argument("--size", help="WIDTHxHEIGHT, default 1024x768")
    s.add_argument("--style", default="shaded_edges", choices=["shaded_edges", "shaded", "lines"])
    s.add_argument("--background", default="#ffffff")
    s.add_argument("--out", help="output directory (default renders/r<rev>)")
    s.add_argument("--section", metavar="PLANE", help="cut-away view: 'y=0' removes the half facing the camera; 'x=10:+' keeps the +X side; cut faces are tinted red")
    s.add_argument("--no-annotate", action="store_true", help="omit the title, axis triad and scale bar")
    s.add_argument("--no-sheet", action="store_true", help="do not write the combined contact sheet")

    s = cmd("export")
    s.add_argument("--format", "-f", help="comma-separated: step,stl,3mf,brep (default from cad.toml)")
    s.add_argument("--3mf-mode", dest="threemf_mode", default=None, choices=["objects", "multimaterial"],
                   help="multimaterial: one print, parts as material regions in place; objects: separate pieces "
                        "(default from cad.toml [export] threemf_mode, else objects)")
    s.add_argument("--revision", "-r")
    s.add_argument("--part", action="append")
    s.add_argument("--out", help="output directory (default out/r<rev>)")
    s.add_argument("--tolerance", type=float, default=0.01, help="STL chordal tolerance in mm")

    cmd("materials")
    s = cmd("slice")
    s.add_argument("parts", nargs="*", help="parts to print (default: all non-reference parts)")
    s.add_argument("--revision", "-r")
    s.add_argument("--printer", help='Bambu printer, e.g. "A1", "A1 mini", "P1S", "X1 Carbon", "H2D" (default A1; cad.toml [print] printer)')
    s.add_argument("--nozzle", type=float, help="nozzle diameter mm (default 0.4)")
    s.add_argument("--process", help='process preset, e.g. "0.20mm Standard", "0.16mm Optimal", "0.12mm Fine"')
    s.add_argument("--filament", action="append", default=[], metavar="MATERIAL=PRESET",
                   help='filament preset for a material, e.g. PLA="Bambu PLA Matte" (repeatable)')
    s.add_argument("--supports", choices=["default", "off", "auto", "on"], help="auto = tree supports where needed")
    s.add_argument("--plate", choices=["textured", "cool", "engineering", "high-temp", "smooth", "supertack"],
                   help="build plate (default: the printer's, usually textured PEI)")
    s.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", dest="overrides",
                   help="raw slicer setting, e.g. sparse_infill_density=25%%, wall_loops=3 (repeatable)")
    s.add_argument("--3mf-mode", dest="threemf_mode", choices=["objects", "multimaterial"])
    s.add_argument("--out", help="output directory (default out/r<N>)")
    s.add_argument("--list", choices=["printers", "processes", "filaments"], help="list Bambu presets and exit")
    s = cmd("info")
    s.add_argument("file", help="a .step/.stp/.iges/.igs/.stl/.brep file")
    s = cmd("fonts")
    s.add_argument("filter", nargs="?", help="only fonts whose name contains this text")

    s = cmd("clearance")
    s.add_argument("--min", type=float, help="required clearance in mm; violations exit with code 4")
    s.add_argument("--allow-contact", action="store_true", help="touching without overlap is OK (supports, seated parts); "
                   "per-face gaps of reference parts still show which faces touch")
    s.add_argument("--part", action="append", help="limit to these parts (repeatable)")
    s.add_argument("--revision", "-r")

    s = cmd("sweep")
    s.add_argument("parameter")
    s.add_argument("values", help="START:STOP:STEP (inclusive) or a comma list, e.g. 0:90:15 or 0,45,90")
    s.add_argument("--min", type=float, help="required clearance between parts in mm; violations exit with code 4")
    s.add_argument("--allow-contact", action="store_true", help="touching without overlap is OK")
    s.add_argument("--render", metavar="VIEWS", help="also render each value, e.g. front or iso,top")
    s.add_argument("--section", metavar="PLANE")
    s.add_argument("--size", help="WIDTHxHEIGHT for --render")

    cmd("params")

    s = cmd("set")
    s.add_argument("assignments", nargs="+", metavar="NAME VALUE | NAME=VALUE")
    s.add_argument("--no-build", action="store_true")
    s.add_argument("--force", action="store_true", help="allow parameters the model does not declare")

    s = cmd("unset")
    s.add_argument("names", nargs="+")
    s.add_argument("--no-build", action="store_true")

    s = cmd("revisions")
    s.add_argument("--limit", type=int, default=50)

    s = cmd("diff")
    s.add_argument("a", nargs="?", default="-1", help="revision (default: previous)")
    s.add_argument("b", nargs="?", default="head", help="revision (default: head)")

    s = cmd("checkout")
    s.add_argument("revision")

    s = cmd("restore")
    s.add_argument("revision")
    s.add_argument("--force", action="store_true")

    cmd("capabilities")
    s = cmd("schema")
    s.add_argument("name", nargs="?")

    s = cmd("examples")
    s.add_argument("action", nargs="?", default="list", choices=["list", "show", "copy"])
    s.add_argument("name", nargs="?")
    s.add_argument("dest", nargs="?")

    s = cmd("docs")
    s.add_argument("topic", nargs="*", help="print only the matching section, e.g. `cad docs holes` (default: everything)")
    s.add_argument("--list", action="store_true", help="list the section titles")
    s = cmd("help")
    s.add_argument("topic", nargs="?")
    return p


# --------------------------------------------------------------------------- state


def state_dir() -> Path:
    d = os.environ.get("CAD_STATE_DIR")
    if d:
        return Path(d)
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "cad"


def current_project_file() -> Path:
    return state_dir() / "current_project"


def resolve_project(args, cwd: Path) -> Path:
    from .project import CONFIG_NAME, find_project_root

    if getattr(args, "project", None):
        p = (cwd / args.project).resolve()
        root = find_project_root(p) if not (p / CONFIG_NAME).exists() else p
        if root is None:
            raise CadError("NO_PROJECT", f"{p} is not inside a cad project (no cad.toml)", hint="create one with `cad init`")
        return root
    root = find_project_root(cwd)
    if root:
        return root
    if (cwd / "model.py").is_file() and getattr(args, "command", None) in ("build", "set", "unset"):
        # a model script but no project yet: create the minimal project file instead of failing
        (cwd / "cad.toml").write_text(f'[project]\nname = "{cwd.name}"\nentry = "model.py"\n')
        args._auto_init = str(cwd / "cad.toml")
        return cwd
    f = current_project_file()
    if f.exists():
        r = Path(f.read_text().strip())
        if (r / CONFIG_NAME).exists():
            return r
    here = [p.name for p in cwd.glob("*.py")]
    hint = ("this directory has no cad.toml: run `cad init` here (it keeps your existing model.py"
            + (f"; or `cad open {here[0]}`" if here and "model.py" not in here else "") + ")") if here else \
        "run `cad init` to make this directory a project, `cad open <dir>`, or pass --project"
    raise CadError("NO_PROJECT", "no project found: not inside a project directory and no project is open", hint=hint)


def _kv(items: list[str]) -> dict[str, Any]:
    from .project import parse_value

    out = {}
    for it in items:
        if "=" not in it:
            raise UsageError(f"expected NAME=VALUE, got {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = parse_value(v)
    return out


def _size(s: str | None):
    if not s:
        return None
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except ValueError as e:
        raise UsageError(f"--size must look like 1024x768, got {s!r}") from e


# --------------------------------------------------------------------------- entry


_ENGINE = None


def default_engine():
    global _ENGINE
    if _ENGINE is None:
        from .engine import Engine

        _ENGINE = Engine()
    return _ENGINE


def main(argv: list[str], cwd: str | os.PathLike | None = None, engine=None) -> tuple[int, str, str]:
    cwd = Path(cwd or os.getcwd())
    out, err = io.StringIO(), io.StringIO()
    as_json = "--json" in argv
    t0 = time.perf_counter()
    command = None
    try:
        parser = _parser()
        try:
            with contextlib.redirect_stdout(out):
                args = parser.parse_args(argv)
        except _HelpShown:
            return 0, out.getvalue(), ""
        if args.version:
            return 0, f"cad {__version__}\n", ""
        command = args.command
        if command is None:
            return 0, parser.format_help(), ""
        ret = _dispatch(args, cwd, engine or default_engine(), parser)
        result, text = ret[0], ret[1]
        failure = ret[2] if len(ret) > 2 else None  # a check that ran but did not pass: show results and fail
        warnings = result.get("warnings", []) if isinstance(result, dict) else []
        code = _exit_for(failure["code"]) if failure else 0
        if as_json:
            env = {"ok": failure is None, "command": command, "result": result, "warnings": warnings,
                   "duration_ms": round((time.perf_counter() - t0) * 1000, 2)}
            if failure:
                env["error"] = failure
                env["exit_code"] = code
            out.write(json.dumps(env, indent=2, default=str) + "\n")
        else:
            out.write(text if text.endswith("\n") else text + "\n")
            for w in warnings:
                err.write(f"warning [{w.get('code')}]: {w.get('message')}\n")
            if failure:
                err.write(f"error [{failure['code']}]: {failure['message']}\n")
        return code, out.getvalue(), err.getvalue()
    except UsageError as e:
        return _fail(as_json, command, {"code": "USAGE", "message": str(e), "hint": "see `cad help <command>`"}, 2, out, err)
    except CadError as e:
        return _fail(as_json, command, e.to_dict(), _exit_for(e.code), out, err)
    except Exception as e:  # internal bug: report with traceback
        tb = traceback.format_exc()
        return _fail(as_json, command, {"code": "INTERNAL", "message": f"{type(e).__name__}: {e}", "details": {"traceback": tb[-4000:]}}, 1, out, err)


def _exit_for(code: str) -> int:
    if code in _CODE_EXIT:
        return _CODE_EXIT[code]
    return 3


def _fail(as_json, command, error, code, out, err):
    if as_json:
        out.write(json.dumps({"ok": False, "command": command, "error": error, "exit_code": code}, indent=2, default=str) + "\n")
    else:
        msg = f"error [{error['code']}]"
        if error.get("feature"):
            msg += f" in feature '{error['feature']}'"
        msg += f": {error['message']}\n"
        if error.get("hint"):
            msg += f"  hint: {error['hint']}\n"
        loc = (error.get("details") or {}).get("location")
        if loc:
            msg += f"  at {loc.get('file')}:{loc.get('line')}: {loc.get('code', '')}\n"
        det = {k: v for k, v in (error.get("details") or {}).items() if k not in ("location", "traceback")}
        if det:
            msg += "  details: " + json.dumps(det, default=str)[:1500] + "\n"
        if error["code"] == "INTERNAL":
            msg += (error.get("details") or {}).get("traceback", "")
        err.write(msg)
    return code, out.getvalue(), err.getvalue()


def _dispatch(args, cwd: Path, engine, parser) -> tuple[Any, str]:
    c = args.command
    if c == "help":
        return _help(args.topic, parser)
    if c == "capabilities":
        return _capabilities(), _capabilities_text()
    if c == "schema":
        from .schema import SCHEMAS

        if args.name:
            if args.name not in SCHEMAS:
                raise CadError("NOT_FOUND", f"no schema named {args.name!r}", details={"available": sorted(SCHEMAS)})
            return SCHEMAS[args.name], json.dumps(SCHEMAS[args.name], indent=2)
        return SCHEMAS, json.dumps(SCHEMAS, indent=2)
    if c == "docs":
        return _docs(args)
    if c == "examples":
        return _examples(args, cwd)
    if c == "slice" and args.list:
        from .slicer import listing

        items = listing(args.list, args.printer, args.nozzle)
        return {args.list: items}, "\n".join(items)
    if c == "info":
        from .importer import describe

        path = Path(args.file)
        if not path.is_absolute():
            path = Path(cwd) / path
        d = describe(path)
        d["file"] = args.file
        lines = [f"{args.file}: {d['format'].upper()}, {len(d['bodies'])} solid bod{'y' if len(d['bodies']) == 1 else 'ies'}"
                 + (f", units in file: {d['units_in_file']} (converted to mm)" if d.get("units_in_file") else ", taken as mm")
                 + (f", {d['triangles']} triangles" if d.get("triangles") else ""),
                 f"overall: size {_fmt3(d['size'])}  min {_fmt3(d['bbox_min'])}  max {_fmt3(d['bbox_max'])}"]
        for b in d["bodies"]:
            lines.append(f"  {b['path']}: size {_fmt3(b['size'])} min {_fmt3(b['bbox_min'])} volume {b['volume']:g} mm3"
                         + (f" colour {b['color']}" if b["color"] else "") + ("" if b["valid"] else "  INVALID"))
        lines.append(f"\nuse: Part.from_file({args.file!r}, reference=True)   # or solid=\"<name>\", align=(\"center\", \"center\", \"min\")")
        return d, "\n".join(lines)
    if c == "fonts":
        from .text import DEFAULT_FONTS, available_fonts

        fonts = [f for f in available_fonts() if not args.filter or args.filter.lower() in f.lower()]
        text = "\n".join(fonts) + f"\n\n{len(fonts)} font(s). Default (first installed): {', '.join(DEFAULT_FONTS)}"
        return {"fonts": fonts, "defaults": list(DEFAULT_FONTS)}, text
    if c == "materials":
        from .materials import library

        lib = library()
        text = "\n".join(f"{m['name']:<10} {m['density']:>5} g/cm3  {m['color']}  {m['kind']:<8} {m['notes']}" for m in lib)
        return {"materials": lib}, text + "\n\nuse: Part('lid', material='PETG')  or  Material('name', density=1.2, color='#rrggbb')"
    if c == "init":
        from .project import init_project

        tmpl = None
        if args.example:
            tmpl = _example_source(args.example)
        root = init_project((cwd / args.dir).resolve(), args.name, tmpl)
        _set_current(root)
        return {"root": str(root), "current": True}, f"created project at {root} (now the current project)\nnext: edit model.py, then `cad build`"
    if c == "open":
        return _open(args, cwd, engine)
    if c == "run":
        return _run(args, cwd)

    root = resolve_project(args, cwd)
    s = engine.session(root)
    if c == "status":
        r = s.status()
        lb = r["last_build"] or {}
        return r, (f"project {r['project']} at {r['root']}\n  head revision: {r['head']}  ({r['revisions']} revisions)\n"
                   f"  last build: {lb.get('status', 'none')}" + (f" — {lb['error']['message']}" if lb.get("error") else "")
                   + f"\n  session pid {r['session']['pid']}, stats {r['session']['stats']}")
    if c == "build":
        r = s.build(_kv(args.param), force=args.force)
        text = _fmt_build(r)
        if getattr(args, "_auto_init", None):
            r["created_project_file"] = args._auto_init
            text = f"note: created {args._auto_init} (entry = model.py)\n" + text
        return r, text
    if c == "inspect":
        r = s.inspect(args.revision, args.part, features=args.features, refs=args.refs)
        return r, _fmt_inspect(r)
    if c == "measure":
        metrics = [m for m in ("volume", "area", "bbox", "com", "holes", "validity", "length", "thickness") if getattr(args, m)]
        section = None
        if args.section:
            ax, _, val = args.section.partition("=")
            try:
                section = (ax.strip(), float(val))
            except ValueError:
                raise CadError(INVALID_ARGUMENT, f"--section expects AXIS=VALUE, e.g. z=-5, got {args.section!r}") from None
        r = s.measure(args.target, metrics, args.revision, other=args.distance, density=args.density, section=section)
        return r, _fmt_yaml(r)
    if c == "query":
        target, expr = args.target, args.expr
        if target and not expr and ("(" in target):
            target, expr = None, target
        r = s.query(target, expr or "faces()", args.revision)
        return r, _fmt_query(r)
    if c == "render":
        r = s.render(args.views, rev=args.revision, parts=args.part, size=_size(args.size), style=args.style,
                     background=args.background, out_dir=args.out, annotate=not args.no_annotate, sheet=not args.no_sheet,
                     section=args.section)
        lines = [f"revision {r['revision']}: {len(r['images'])} view(s) -> {r['out_dir']}"]
        for im in r["images"]:
            lines.append(f"  {im['view']:<10} {im['path']}  ({'cached' if im['cached'] else 'rendered'}, "
                         f"1px={im['mm_per_pixel']:.4g}mm, right={im['screen_axes']['right']} up={im['screen_axes']['up']})")
        if r["sheet"]:
            lines.append(f"  sheet      {r['sheet']}")
        return r, "\n".join(lines)
    if c == "slice":
        def pairs(items, flag):
            out = {}
            for it in items:
                if "=" not in it:
                    raise CadError(INVALID_ARGUMENT, f"{flag} expects KEY=VALUE, got {it!r}")
                k, v = it.split("=", 1)
                out[k.strip()] = v.strip().strip('"')
            return out

        r = s.slice(rev=args.revision, parts=args.parts or None, printer=args.printer, nozzle=args.nozzle, process=args.process,
                      filaments=pairs(args.filament, "--filament"), supports=args.supports,
                      overrides=pairs(args.overrides, "--set"), threemf_mode=args.threemf_mode, out_dir=args.out,
                    plate=args.plate)
        lines = [f"revision {r['revision']} sliced{' (cached)' if r['cached'] else ''} for {r['printer']}, {r['process']}, "
                 f"{r['plate_type']}  [{r['slicer']}]",
                 f"  print time {r['time']}, {r['filament_g']} g filament, {r['layers']} layers at {r['layer_height']:g} mm"
                 + (f", {r['filament_changes']} filament changes" if r.get("filament_changes") else ""),
                 f"  supports: {'used' if r['supports']['used'] else ('enabled, none needed' if r['supports']['enabled'] else 'off')}"]
        for f in r["filaments"]:
            lines.append(f"  filament {f['slot']}: {f['material']} -> {f['preset']} ({', '.join(f['parts'])}): {f['grams']} g"
                         + (f", {f['meters']} m" if f.get("meters") else ""))
        top = list(r["time_by_feature_s"].items())[:4]
        if top:
            lines.append("  time by feature: " + ", ".join(f"{k} {v // 60}m" if v >= 60 else f"{k} {v}s" for k, v in top))
        for w in r["warnings"]:
            lines.append(f"  warning {w['code']}: {w['message']}")
        if r.get("skipped_reference_parts"):
            lines.append(f"  skipped reference parts: {', '.join(r['skipped_reference_parts'])}")
        lines.append(f"  sliced file: {r['output']}  (open in Bambu Studio or send to the printer)")
        return r, "\n".join(lines)
    if c == "export":
        fmts = [f.strip() for f in args.format.split(",")] if args.format else None
        r = s.export(fmts, rev=args.revision, parts=args.part, out_dir=args.out, tolerance=args.tolerance,
                     threemf_mode=args.threemf_mode)
        lines = [f"revision {r['revision']}:"]
        for f in r["files"]:
            lines.append(f"  {f['path']}  ({f['bytes']} bytes)")
            for m in f.get("materials", []):
                lines.append(f"      material slot {m['slot']} (extruder {m['extruder']}): {m['name']} {m['color']} <- {', '.join(m['parts'])}")
            pr = f.get("printability")
            if pr:
                state = "watertight, manifold" if pr["watertight"] else f"NOT watertight ({pr.get('open_edges')} open / {pr.get('non_manifold_edges')} non-manifold edges)"
                lines.append(f"      STL check: {state}; {pr['triangles']} triangles; size {pr.get('size_mm')} mm; volume {pr.get('volume_mm3')} mm3")
        return r, "\n".join(lines)
    if c == "clearance":
        r = s.clearance(args.revision, parts=args.part, min_distance=args.min, allow_contact=args.allow_contact)
        lines = [f"revision {r['revision']} clearances" + (f" (required >= {args.min} mm)" if args.min is not None else "") + ":"]
        for p in r["pairs"]:
            flag = "" if p.get("ok", True) else "   <-- VIOLATION"
            extra = f", overlap {p['overlap_volume']} mm3" if p["overlap_volume"] else ""
            lines.append(f"  {p['a']} <-> {p['b']}: {p['state']}, min distance {p['min_distance']} mm{extra} "
                         f"at {p['closest_points'][0]} / {p['closest_points'][1]}{flag}")
            faces = p.get("reference_faces", [])
            facing = sorted((f for f in faces if f["gap"] is not None), key=lambda f: f["gap"])
            refname = p["b"] if p["b"] in r["references"] else p["a"]
            for f in facing[:6]:
                gap = "contact" if f["gap"] < 1e-4 else f"{f['gap']} mm"
                lines.append(f"      {refname} face {', '.join(f['faces'])} (normal {f['normal']}): gap {gap}")
            hidden = len(facing) - 6 if len(facing) > 6 else 0
            open_ = len(faces) - len(facing)
            if hidden or open_:
                lines.append(f"      ({hidden} more facing faces, " if hidden else "      (" )
                lines[-1] += f"{open_} faces with nothing in front; all in --json)"
        fail = None
        if r.get("violations"):
            fail = {"code": "VALIDATION_FAILED", "message": f"{len(r['violations'])} pair(s) closer than {args.min} mm",
                    "hint": "for envelopes, per-face distances show which faces touch; contact on a supporting face is often intended"}
        return r, "\n".join(lines), fail
    if c == "sweep":
        vals = _sweep_values(args.values)
        r = s.sweep(args.parameter, vals, views=args.render, size=_size(args.size), min_distance=args.min, section=args.section,
                    allow_contact=args.allow_contact)
        lines = [f"sweep {args.parameter} over {vals} (active revision restored to r{r['head']}):"]
        for row in r["results"]:
            cp = row.get("closest_pair")
            desc = f"closest {cp['a']}<->{cp['b']} {cp['state']} {cp['min_distance']} mm" if cp else "single part"
            bad = f"  VIOLATIONS: {[(v['a'], v['b'], v['min_distance']) for v in row['violations']]}" if row.get("violations") else ""
            lines.append(f"  {args.parameter}={row['value']}: r{row['revision']} {desc}{bad}")
            for img in row.get("images", []):
                lines.append(f"      {img}")
        fail = None
        if r.get("ok") is False:
            bad = [x["value"] for x in r["results"] if x.get("violations")]
            fail = {"code": "VALIDATION_FAILED", "message": f"clearance below {args.min} mm at {args.parameter} = {bad}"}
        return r, "\n".join(lines), fail
    if c == "params":
        r = s.params()
        lines = [f"parameters (revision {r['revision']}):"]
        for k, d in sorted(r["declared"].items()):
            rng = f" [{d.get('min')}..{d.get('max')}]" if d.get("min") is not None or d.get("max") is not None else ""
            ov = "  (overridden)" if k in r["overlay"] else ""
            lines.append(f"  {k} = {d['value']} {d.get('unit') or ''}{rng}  default {d['default']}{ov}")
        extra = [k for k in r["overlay"] if k not in r["declared"]]
        if extra:
            lines.append(f"  overlay entries not declared by the model: {extra}")
        return r, "\n".join(lines)
    if c == "set":
        vals = _assignments(args.assignments)
        r = s.set_params(vals, force=args.force)
        text = f"params.toml: {r['overlay']}"
        if not args.no_build:
            b = s.build()
            r["build"] = b
            r["warnings"] = b.get("warnings", [])
            text += "\n" + _fmt_build(b)
        return r, text
    if c == "unset":
        r = s.unset_params(args.names)
        text = f"params.toml: {r['overlay']}"
        if not args.no_build:
            b = s.build()
            r["build"] = b
            text += "\n" + _fmt_build(b)
        return r, text
    if c == "revisions":
        r = s.revisions(args.limit)
        lines = []
        for rv in r["revisions"]:
            mark = "*" if rv["head"] else " "
            parts = ", ".join(f"{n} {p['bbox']} vol={p['volume']}" for n, p in rv["parts"].items())
            lines.append(f"{mark} r{rv['revision']:<4} {rv['created_at']}  src {rv['source_hash']}  {rv['overrides'] or ''}  {parts}")
        lb = r["last_build"]
        if lb and lb.get("status") == "failed":
            lines.append(f"last build FAILED: {lb['error']['message']} (head unchanged at r{r['head']})")
        return r, "\n".join(lines) or "no revisions yet"
    if c == "diff":
        r = s.diff(args.a, args.b)
        return r, _fmt_yaml(r)
    if c == "checkout":
        r = s.checkout(args.revision)
        return r, f"active revision is now r{r['head']} ({r['note']})"
    if c == "restore":
        r = s.restore(args.revision, force=args.force)
        return r, f"restored r{r['revision']}: {r.get('restored')}"
    raise UsageError(f"unknown command {c}")


def _sweep_values(text: str) -> list:
    from .project import parse_value

    t = text.strip()
    if ":" in t:
        try:
            a, b, step = (float(x) for x in t.split(":"))
        except ValueError as e:
            raise UsageError(f"sweep range must be START:STOP:STEP, got {text!r}") from e
        if step <= 0:
            raise UsageError("sweep STEP must be positive")
        n = int(round((b - a) / step))
        vals = [a + i * step for i in range(n + 1) if a + i * step <= b + 1e-9]
        return [int(v) if float(v).is_integer() else round(v, 9) for v in vals]
    return [parse_value(x) for x in t.split(",") if x.strip()]


def _assignments(items: list[str]) -> dict[str, Any]:
    from .project import parse_value

    vals: dict[str, Any] = {}
    i = 0
    while i < len(items):
        it = items[i]
        if "=" in it:
            k, v = it.split("=", 1)
            vals[k] = parse_value(v)
            i += 1
        elif i + 1 < len(items):
            vals[it] = parse_value(items[i + 1])
            i += 2
        else:
            raise UsageError(f"missing value for parameter {it!r}")
    return vals


def _set_current(root: Path) -> None:
    """Remember the current project (best effort: sandboxes often forbid writes outside the workspace)."""
    try:
        f = current_project_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(str(root) + "\n")
    except OSError:
        pass


def _open(args, cwd: Path, engine):
    from .project import CONFIG_NAME, find_project_root

    p = (cwd / args.path).resolve()
    if p.is_file() and p.suffix == ".py":
        root = find_project_root(p)
        if root is None:
            root = p.parent
            cfg = root / CONFIG_NAME
            if not cfg.exists():
                cfg.write_text(f'[project]\nname = "{p.stem}"\nentry = "{p.name}"\n')
    elif p.is_dir():
        root = p if (p / CONFIG_NAME).exists() else find_project_root(p)
        if root is None:
            raise CadError("NO_PROJECT", f"{p} has no cad.toml", hint="use `cad init` to create a project, or open a .py file")
    else:
        raise CadError("NOT_FOUND", f"{p} does not exist")
    _set_current(root)
    s = engine.session(root)
    st = s.status()
    return st, f"opened {st['project']} at {root} (head revision: {st['head']})"


def _run(args, cwd: Path):
    from .runner import run_script

    script = (cwd / args.script).resolve()
    t0 = time.perf_counter()
    out = run_script(script, _kv(args.param))
    outdir = Path(args.out) if args.out else cwd / "out" / script.stem
    if not outdir.is_absolute():
        outdir = cwd / outdir
    result: dict[str, Any] = {
        "script": str(script),
        "parts": {n: p.summary() for n, p in out.parts.items()},
        "parameters": {k: v.value for k, v in out.parameters.items()},
        "stdout": out.stdout,
        "warnings": out.warnings,
    }
    if args.render:
        from .renderer import render_views

        result["renders"] = render_views(out.parts, args.render, outdir, size=_size(args.size), style=args.style,
                                         prefix=script.stem, section=args.section)
    if args.export:
        files = []
        for fmt in [f.strip() for f in args.export.split(",")]:
            deliver = {n: p for n, p in out.parts.items() if not p.reference}
            if fmt == "3mf":  # one file with every part and its material
                from .threemf import export_3mf

                rep = export_3mf(deliver, outdir / f"{script.stem}.3mf", mode=args.threemf_mode, title=script.stem)
                files.append(rep["path"])
                result.setdefault("warnings", []).extend(rep["warnings"])
                continue
            for n, p in deliver.items():
                files.append(p.export(str(outdir / f"{n}.{fmt}")))
        result["exports"] = files
    result["duration_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    lines = [_fmt_parts(result["parts"])]
    if out.stdout.strip():
        lines.append("script output:\n" + _indent(out.stdout.rstrip()))
    for r in result.get("renders", []):
        lines.append(f"render {r['view']}: {r['path']}")
    for f in result.get("exports", []):
        lines.append(f"export: {f}")
    return result, "\n".join(lines)


# --------------------------------------------------------------------------- formatting


def _indent(s: str, n: int = 2) -> str:
    return "\n".join(" " * n + line for line in s.splitlines())


def _fmt_parts(parts: dict) -> str:
    lines = []
    for n, p in parts.items():
        sz = p.get("bbox", {}).get("size") or p.get("bbox_size")
        lines.append(f"part {n}: valid={p.get('valid')} solids={p.get('solids')} bbox={sz} volume={p.get('volume')} holes={p.get('holes')}")
    return "\n".join(lines)


def _fmt_build(r: dict) -> str:
    head = f"revision {r['revision']} ({'cached, inputs unchanged' if r['cached'] else 'built'} in {r['duration_ms']:.0f} ms)"
    lines = [head, _fmt_parts(r["parts"])]
    if r.get("parameters"):
        lines.append("parameters: " + ", ".join(f"{k}={v}" for k, v in r["parameters"].items()))
    if r.get("stdout", "").strip():
        lines.append("script output:\n" + _indent(r["stdout"].rstrip()))
    return "\n".join(lines)


def _fmt_inspect(r: dict) -> str:
    lines = [f"{r['project']} revision {r['revision']} (head {r['head']}, built {r['created_at']})"]
    if r["parameters"]:
        lines.append("parameters: " + ", ".join(f"{k}={v['value']}" for k, v in r["parameters"].items()))
    for n, p in r["parts"].items():
        b = p["bbox"]
        lines.append(f"part {n}{' (reference: not exported)' if p.get('reference') else ''}: valid={p['valid']} solids={p['solids']} faces={p['faces']} edges={p['edges']}")
        lines.append(f"  bbox min {b['min']} max {b['max']} size {b['size']}")
        lines.append(f"  volume {p['volume']} mm3, area {p['area']} mm2, center of mass {p['center_of_mass']}")
        if p.get("material"):
            lines.append(f"  material {p['material']}" + (f", mass {p['mass_g']} g" if p.get("mass_g") is not None else ""))
        for h in p["hole_list"]:
            lines.append(f"  hole d={h['diameter']} axis={h['axis']} at {h['position']} depth {h['depth']} {h['names']}")
        if "feature_list" in p:
            lines.append("  features: " + ", ".join(p["feature_list"]))
        if "references" in p:
            lines.append("  references: " + ", ".join(f"{k}({v['count']})" if v["status"] == "ok" else f"{k}(lost in {v['lost_in']})"
                                                      for k, v in p["references"].items()))
        if "feature_graph" in p:
            for f in p["feature_graph"]:
                lines.append(f"  - {f['id']} [{f['type']}] deps={f['depends_on']} params={json.dumps(f['params'], default=str)[:200]}")
        for w in p.get("warnings", []):
            lines.append(f"  warning [{w['code']}] {w.get('feature', '')}: {w['message']}")
    return "\n".join(lines)


def _fmt_query(r: dict) -> str:
    if "items" not in r:
        return json.dumps(r["value"], indent=2, default=str)
    lines = [f"{r['selection']}: {r['count']} {r['kind']}(s)"]
    for i, it in enumerate(r["items"]):
        lines.append(f"  [{i}] " + json.dumps(it, default=str))
    return "\n".join(lines)


def _fmt_yaml(d: Any, ind: int = 0) -> str:
    pad = "  " * ind
    if isinstance(d, dict):
        lines = []
        for k, v in d.items():
            if isinstance(v, (dict, list)) and v and not _is_flat(v):
                lines.append(f"{pad}{k}:")
                lines.append(_fmt_yaml(v, ind + 1))
            else:
                lines.append(f"{pad}{k}: {json.dumps(v, default=str)}")
        return "\n".join(lines)
    if isinstance(d, list):
        return "\n".join(f"{pad}- {json.dumps(x, default=str)}" for x in d)
    return f"{pad}{d}"


def _is_flat(v) -> bool:
    if isinstance(v, list):
        return all(not isinstance(x, (dict, list)) for x in v)
    return False


# --------------------------------------------------------------------------- discovery


def _help(topic, parser):
    if not topic:
        return {"commands": {k: v["summary"] for k, v in COMMANDS.items()}}, parser.format_help()
    if topic not in COMMANDS:
        raise CadError("NOT_FOUND", f"no command {topic!r}", details={"commands": sorted(COMMANDS)})
    sp = parser._subparsers._group_actions[0].choices[topic]
    opts = []
    for a in sp._actions:
        if isinstance(a, argparse._HelpAction):
            continue
        opts.append({
            "name": a.option_strings[0] if a.option_strings else a.dest,
            "flags": a.option_strings,
            "positional": not a.option_strings,
            "help": a.help,
            "default": a.default if a.default is not argparse.SUPPRESS else None,
            "choices": list(a.choices) if a.choices else None,
            "repeatable": isinstance(a, argparse._AppendAction),
            "takes_value": a.nargs != 0,
        })
    return {"command": topic, "summary": COMMANDS[topic]["summary"], "requires_project": COMMANDS[topic]["project"],
            "arguments": opts, "usage": sp.format_usage().strip()}, sp.format_help()


def _capabilities() -> dict:
    from .renderer import ALL_VIEWS, STANDARD_VIEWS, STYLES

    return {
        "name": "cad",
        "version": __version__,
        "kernel": "Open CASCADE (OCP bindings)",
        "units": {"length": "mm", "angle": "degrees"},
        "coordinate_system": "right-handed, Z up; front view looks from -Y; width=X, depth=Y, height=Z",
        "commands": {k: v["summary"] for k, v in COMMANDS.items()},
        "render": {"views": sorted(STANDARD_VIEWS), "default_set": list(ALL_VIEWS), "custom": ["az=<deg>,el=<deg>", "dir=x,y,z[,up=x,y,z]"],
                   "styles": list(STYLES), "projection": ["orthographic"], "outputs": ["png", "json metadata", "contact sheet"]},
        "export_formats": ["step", "stl", "brep"],
        "exit_codes": {str(v): k for k, v in EXIT.items()},
        "json_envelope": {"ok": "bool", "command": "str", "result": "object", "warnings": "list", "error": "{code,message,hint?,feature?,details?}"},
        "python_api": "from cad import Part, Profile, Plane, Parameter  (run `cad docs` for the reference)",
        "modes": {"daemon": "default; the cad binary auto-starts cadd", "standalone": "cad --no-daemon ... or cad run script.py"},
    }


def _capabilities_text() -> str:
    c = _capabilities()
    lines = [f"cad {c['version']} — units mm/deg, {c['coordinate_system']}", "", "commands:"]
    lines += [f"  {k:<13} {v}" for k, v in c["commands"].items()]
    lines += ["", f"views: {', '.join(c['render']['views'])}, plus {', '.join(c['render']['custom'])}",
              f"styles: {', '.join(c['render']['styles'])};  export: {', '.join(c['export_formats'])}",
              "exit codes: " + ", ".join(f"{k}={v}" for k, v in c["exit_codes"].items())]
    return "\n".join(lines)


GETTING_STARTED = """getting started:
  cad init                      make this directory a project (writes cad.toml and a model.py to edit)
  # edit model.py:  from cad import Part;  p = Part("plate");  p.box(80, 50, 4);  p.hole(5, at=(30, 15))
  cad build                     run the model -> revision 1 (errors point at your script line)
  cad render --views iso,top    PNGs in renders/r1/ to look at
  cad export --format stl       printable files in out/r1/  (3mf keeps materials: Part("seal", material="TPU"))

documentation:
  cad docs                      full API reference      cad docs --list    section titles
  cad docs holes                one section (any title words: fillet, text, selecting, assemblies, ...)
  cad examples list             worked examples         cad examples show <name>
  cad help <command>            options of one command
"""


def _sections(text: str) -> list[tuple[str, int, str]]:
    """(title, level, body) for every ## / ### section of the reference."""
    out, cur, lvl, buf = [], None, 0, []
    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if cur is not None:
                out.append((cur, lvl, "\n".join(buf)))
            lvl = 2 if line.startswith("## ") else 3
            cur, buf = line.lstrip("#").strip(), [line]
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out.append((cur, lvl, "\n".join(buf)))
    return out


def _docs(args):
    text = _docs_text()
    secs = _sections(text)
    if args.list:
        lines = [("  " if lvl == 3 else "") + title for title, lvl, _ in secs]
        return {"sections": [t for t, _, _ in secs]}, "sections (print one with `cad docs <words>`):\n" + "\n".join("  " + l for l in lines)
    if not args.topic:
        return {"markdown": text}, text
    words = [w.lower() for w in args.topic]

    def score(title, body):
        t = title.lower()
        return sum(3 for w in words if w in t) + sum(1 for w in words if w in body.lower())

    ranked = sorted(((score(t, b), i) for i, (t, _, b) in enumerate(secs)), reverse=True)
    if not ranked or ranked[0][0] == 0:
        raise CadError("NOT_FOUND", f"no documentation section matches {' '.join(args.topic)!r}",
                       hint="see `cad docs --list` for section titles", details={"sections": [t for t, _, _ in secs]})
    best = ranked[0][0]
    # sections whose title matches; otherwise the best body matches (at most 3)
    picks = [i for sc, i in ranked if sc >= 3 and sc >= best - 1][:3] or [i for sc, i in ranked if sc == best][:3]
    body = "\n\n".join(secs[i][2] for i in sorted(picks))
    return {"markdown": body, "sections": [secs[i][0] for i in sorted(picks)]}, body


def _docs_text() -> str:
    p = Path(__file__).parent / "docs" / "REFERENCE.md"
    return p.read_text() if p.exists() else "reference not installed"


def _examples_dir() -> Path:
    return Path(__file__).parent / "examples"


def _example_source(name: str) -> str:
    p = _examples_dir() / f"{name}.py"
    if not p.exists():
        raise CadError("NOT_FOUND", f"no example {name!r}", details={"available": sorted(x.stem for x in _examples_dir().glob("*.py"))})
    return p.read_text()


def _examples(args, cwd: Path):
    d = _examples_dir()
    if args.action == "list":
        items = []
        for p in sorted(d.glob("*.py")):
            doc = p.read_text().split('"""')
            items.append({"name": p.stem, "summary": doc[1].strip().splitlines()[0] if len(doc) > 2 else ""})
        return {"examples": items}, "\n".join(f"{i['name']:<22} {i['summary']}" for i in items)
    if not args.name:
        raise UsageError("example name required")
    src = _example_source(args.name)
    if args.action == "show":
        return {"name": args.name, "source": src}, src
    from .project import init_project

    dest = (cwd / (args.dest or args.name)).resolve()
    init_project(dest, args.name, src)
    return {"root": str(dest)}, f"copied example {args.name} to {dest}\nnext: cd {dest} && cad build && cad render"


def _fmt3(v) -> str:
    return " x ".join(f"{x:g}" for x in v) if len(v) == 3 else str(v)


def console_main() -> None:  # pragma: no cover - entry point
    code, out, err = main(sys.argv[1:])
    sys.stdout.write(out)
    sys.stderr.write(err)
    sys.exit(code)


if __name__ == "__main__":  # pragma: no cover
    console_main()
