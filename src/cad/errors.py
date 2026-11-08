"""Structured errors and warnings.

Every failure raised by the public API is a :class:`CadError` carrying a stable
machine-readable ``code``, a human ``message``, an optional ``hint`` describing
what to change, and a ``details`` dict.  The CLI serialises these verbatim with
``--json`` so agents can branch on ``code`` instead of parsing text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Stable error codes.  Add new ones; never repurpose an existing code.
INVALID_ARGUMENT = "INVALID_ARGUMENT"
EMPTY_SELECTION = "EMPTY_SELECTION"
AMBIGUOUS_SELECTION = "AMBIGUOUS_SELECTION"
UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
REFERENCE_LOST = "REFERENCE_LOST"
NO_BODY = "NO_BODY"
OPERATION_FAILED = "OPERATION_FAILED"
BOOLEAN_FAILED = "BOOLEAN_FAILED"
FILLET_FAILED = "FILLET_FAILED"
CHAMFER_FAILED = "CHAMFER_FAILED"
SHELL_FAILED = "SHELL_FAILED"
INVALID_SHAPE = "INVALID_SHAPE"
VALIDATION_FAILED = "VALIDATION_FAILED"
EXPORT_FAILED = "EXPORT_FAILED"
SCRIPT_ERROR = "SCRIPT_ERROR"
NO_MODEL = "NO_MODEL"
UNKNOWN_PARAMETER = "UNKNOWN_PARAMETER"
PARAMETER_OUT_OF_RANGE = "PARAMETER_OUT_OF_RANGE"
NOT_FOUND = "NOT_FOUND"


class CadError(Exception):
    """A structured, agent-readable modelling error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        feature: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.feature = feature
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.feature:
            d["feature"] = self.feature
        if self.hint:
            d["hint"] = self.hint
        if self.details:
            d["details"] = self.details
        return d

    def __str__(self) -> str:
        s = f"[{self.code}] {self.message}"
        if self.feature:
            s = f"[{self.code}] feature '{self.feature}': {self.message}"
        if self.hint:
            s += f"\n  hint: {self.hint}"
        return s


@dataclass
class CadWarning:
    """A non-fatal diagnostic attached to a feature (e.g. a cut that removed nothing)."""

    code: str
    message: str
    feature: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.feature:
            d["feature"] = self.feature
        if self.details:
            d["details"] = self.details
        return d

    def __str__(self) -> str:
        where = f" (feature '{self.feature}')" if self.feature else ""
        return f"warning [{self.code}]{where}: {self.message}"
