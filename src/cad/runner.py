"""Execute a CAD script and collect the parts it produces.

Script contract (in order of precedence):

1. If the script defines ``build()``, it is called with no arguments and must
   return a ``Part``, a list/tuple of Parts, or a dict ``{name: Part}``.
2. Otherwise every module-level variable holding a ``Part`` with geometry is
   collected (in definition order).

Scripts are trusted, ordinary Python.  Running one executes arbitrary code; see
docs/SECURITY.md before accepting scripts from untrusted sources.
"""

from __future__ import annotations

import contextlib
import io
import os
import runpy
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import NO_MODEL, SCRIPT_ERROR, CadError
from .params import ParameterInfo, parameter_overrides
from .part import Part


@dataclass
class BuildOutput:
    parts: dict[str, Part]
    parameters: dict[str, ParameterInfo]
    stdout: str = ""
    stderr: str = ""
    duration_ms: float = 0.0
    warnings: list[dict] = field(default_factory=list)
    joints: list[dict] = field(default_factory=list)
    studies: list[dict] = field(default_factory=list)


def _purge_project_modules(root: Path) -> None:
    """Drop cached imports of helper modules living in the project so edits are seen."""
    root_s = str(root.resolve())
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if f and os.path.abspath(f).startswith(root_s + os.sep) and "site-packages" not in f:
            del sys.modules[name]


def _collect(ns: dict[str, Any]) -> tuple[dict[str, Part], Any]:
    """(parts, assembly or None)."""
    from .assembly import Assembly

    if callable(ns.get("build")):
        result = ns["build"]()
        if isinstance(result, Assembly):
            if not result.parts:
                raise CadError(SCRIPT_ERROR, "build() returned an empty Assembly", hint="asm.add(part, ...)")
            return result.solve(), result
        return _normalise(result, "build()"), None
    parts: dict[str, Part] = {}
    seen: set[int] = set()
    for k, v in ns.items():
        if isinstance(v, Part) and not k.startswith("_") and id(v) not in seen and v.has_body:
            seen.add(id(v))
            parts[v.name if v.name not in parts else k] = v
    return parts, None


def _normalise(result: Any, where: str) -> dict[str, Part]:
    if isinstance(result, Part):
        return {result.name: result}
    if isinstance(result, dict):
        out = {}
        for k, v in result.items():
            if not isinstance(v, Part):
                raise CadError(SCRIPT_ERROR, f"{where} returned a dict whose value for {k!r} is {type(v).__name__}, not Part")
            out[str(k)] = v
        return out
    if isinstance(result, (list, tuple)):
        out = {}
        for i, v in enumerate(result):
            if not isinstance(v, Part):
                raise CadError(SCRIPT_ERROR, f"{where} returned a list whose item {i} is {type(v).__name__}, not Part")
            name = v.name if v.name not in out else f"{v.name}_{i}"
            out[name] = v
        return out
    raise CadError(
        SCRIPT_ERROR,
        f"{where} returned {type(result).__name__}; expected a Part, list of Parts or dict of Parts",
    )


def _script_frames(tb, script: Path) -> list[dict]:
    """Traceback frames that belong to user code (not the cad library)."""
    import cad

    lib = os.path.dirname(os.path.abspath(cad.__file__))
    frames = []
    for fs in traceback.extract_tb(tb):
        fn = os.path.abspath(fs.filename)
        in_lib = fn.startswith(lib + os.sep) and not fn.startswith(os.path.join(lib, "examples"))
        if in_lib or "runpy" in fn:
            continue
        frames.append({"file": fs.filename, "line": fs.lineno, "function": fs.name, "code": (fs.line or "").strip()})
    return frames


def run_script(
    script: str | os.PathLike,
    params: dict[str, Any] | None = None,
    *,
    capture: bool = True,
) -> BuildOutput:
    """Run ``script`` with parameter ``params`` overrides and return its parts.

    Raises :class:`CadError` (``SCRIPT_ERROR``, ``NO_MODEL`` or the modelling
    error raised inside the script) with the user-code location attached.
    """
    path = Path(script).resolve()
    if not path.is_file():
        raise CadError("NOT_FOUND", f"script not found: {script}")
    root = path.parent
    _purge_project_modules(root)
    out, err = io.StringIO(), io.StringIO()
    t0 = time.perf_counter()
    added = str(root) not in sys.path
    if added:
        sys.path.insert(0, str(root))
    old_cwd = os.getcwd()
    redirect = (contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)) if capture else (contextlib.nullcontext(), contextlib.nullcontext())
    try:
        with parameter_overrides(params) as ctx, redirect[0], redirect[1]:
            os.chdir(root)
            try:
                ns = runpy.run_path(str(path), run_name="__cad__")
                parts, assembly = _collect(ns)
                joints = assembly.describe() if assembly is not None else []
                studies = _studies(ctx.studies, parts)
            except CadError as e:
                frames = _script_frames(sys.exc_info()[2], path)
                if frames:
                    e.details.setdefault("location", frames[-1])
                raise
            except SystemExit as e:
                raise CadError(SCRIPT_ERROR, f"script called sys.exit({e.code})") from e
            except SyntaxError as e:
                raise CadError(
                    SCRIPT_ERROR,
                    f"syntax error: {e.msg}",
                    details={"location": {"file": e.filename, "line": e.lineno, "code": (e.text or "").strip()}},
                ) from e
            except Exception as e:
                frames = _script_frames(sys.exc_info()[2], path)
                raise CadError(
                    SCRIPT_ERROR,
                    f"{type(e).__name__}: {e}",
                    hint="the error was raised by the script itself (see details.location)",
                    details={"location": frames[-1] if frames else None, "traceback": frames[-5:]},
                ) from e
    finally:
        os.chdir(old_cwd)
        if added and str(root) in sys.path:
            sys.path.remove(str(root))
    if not parts:
        raise CadError(
            NO_MODEL,
            "the script produced no parts",
            hint="define build() returning a Part (or list/dict of Parts), or assign a Part with geometry to a module-level variable",
        )
    warnings = [dict(w.to_dict(), part=name) for name, p in parts.items() for w in p.warnings]
    warnings += [dict(w, joint=j["name"]) for j in joints for w in j["warnings"]]
    return BuildOutput(parts, dict(ctx.declared), out.getvalue(), err.getvalue(), (time.perf_counter() - t0) * 1000, warnings,
                       joints, studies)


def _studies(studies: list, parts: dict[str, Part]) -> list[dict]:
    """Resolve declared Studies against the parts the script produced."""
    out = []
    for s in studies:
        name = next((n for n, p in parts.items() if p is s.part), None)
        if name is None:  # assemblies return posed copies: match by part name
            name = next((n for n, p in parts.items() if p.name == s.part.name), None)
        if name is None:
            raise CadError(SCRIPT_ERROR, f"study '{s.name}' analyses part '{s.part.name}', which the script does not output",
                           hint="return that part from build() (or keep it in a module-level variable)")
        out.append(s.resolve(name))
    return out
