"""Declared, overridable model parameters.

A script declares its tunable values with :func:`Parameter`::

    length = Parameter("arm.length", default=85, min=40, max=200, unit="mm")

The returned value is a plain ``float`` (or ``int`` / ``str`` / ``bool`` matching
the default's type), so it can be used directly in arithmetic.

Overrides come from the project's parameter overlay (``cad set arm.length 95``
writes ``params.toml``) or from ``cad run --param arm.length=95``.  The runner
installs overrides with :func:`parameter_overrides` before executing the script
and collects every declaration afterwards; nothing else reads or mutates this
state.  Running a script with plain ``python model.py`` uses the defaults.
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import asdict, dataclass
from typing import Any, Iterator

from .errors import PARAMETER_OUT_OF_RANGE, CadError


@dataclass
class ParameterInfo:
    name: str
    default: Any
    value: Any
    min: float | None = None
    max: float | None = None
    unit: str | None = None
    description: str | None = None
    overridden: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class _ParamContext:
    def __init__(self, overrides: dict[str, Any]):
        self.overrides = dict(overrides)
        self.declared: dict[str, ParameterInfo] = {}


_ctx: contextvars.ContextVar[_ParamContext | None] = contextvars.ContextVar("cad_params", default=None)


@contextlib.contextmanager
def parameter_overrides(overrides: dict[str, Any] | None = None) -> Iterator[_ParamContext]:
    """Install parameter overrides for the duration of a script run."""
    ctx = _ParamContext(overrides or {})
    token = _ctx.set(ctx)
    try:
        yield ctx
    finally:
        _ctx.reset(token)


def _coerce(value: Any, like: Any) -> Any:
    if isinstance(like, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(like, int) and not isinstance(like, bool):
        f = float(value)
        return int(f) if f.is_integer() else f
    if isinstance(like, float):
        return float(value)
    if isinstance(like, str):
        return str(value)
    return value


def Parameter(
    name: str,
    default: Any,
    *,
    min: float | None = None,
    max: float | None = None,
    unit: str | None = "mm",
    description: str | None = None,
) -> Any:
    """Declare a named parameter and return its effective value."""
    ctx = _ctx.get()
    value = default
    overridden = False
    if ctx is not None and name in ctx.overrides:
        value = _coerce(ctx.overrides[name], default)
        overridden = True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if (min is not None and value < min) or (max is not None and value > max):
            raise CadError(
                PARAMETER_OUT_OF_RANGE,
                f"parameter {name}={value} is outside [{min}, {max}]",
                hint=f"choose a value between {min} and {max}",
                details={"name": name, "value": value, "min": min, "max": max},
            )
    if ctx is not None:
        ctx.declared[name] = ParameterInfo(
            name, default, value, min, max, unit if isinstance(default, (int, float)) else None, description, overridden
        )
    return value
