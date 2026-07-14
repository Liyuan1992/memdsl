"""Internal report-only resolved view for Phase 1.

This module is intentionally not re-exported from :mod:`memdsl`.  Phase 1
freezes deterministic checkout metadata and classification while preserving
the v0.6 serving contract.  Quarantine and strict enforcement remain later
phases.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass, field
from typing import FrozenSet, Optional, Tuple

from memdsl.authority import current_declarations
from memdsl.compiler import (
    CompilationDiagnostic,
    CompiledWorkspace,
    WorkspaceInput,
    ensure_compiled,
)
from memdsl.model import Declaration


VIEW_CONTRACT_VERSION = "memdsl.resolved_view.phase1.report.v1"


@dataclass(frozen=True)
class ViewContext:
    """Inputs that identify one deterministic report-only checkout."""

    source_fingerprint: str
    as_of: _dt.date
    principal: Optional[str] = None
    granted_scopes: FrozenSet[str] = field(default_factory=frozenset)
    policy_version: str = ""
    compatibility_mode: str = "v0.6"
    enforcement_mode: str = "report"


@dataclass(frozen=True)
class ResolvedView:
    """Phase 1 classification over a compiled workspace.

    Report mode exposes diagnostics but does not quarantine declarations or
    change v1 map/query/list/compliance serving.  Cycle-invalid supersedes
    edges are already excluded from the compatibility authority calculation.
    """

    view_id: str
    context: ViewContext
    authoritative: Tuple[Declaration, ...]
    provisional: Tuple[Declaration, ...]
    quarantined: Tuple[Declaration, ...]
    excluded: Tuple[Declaration, ...]
    diagnostics: Tuple[CompilationDiagnostic, ...]

    def diagnostic_summary(self) -> dict:
        return diagnostic_summary(self.diagnostics)

    def metadata(self) -> dict:
        return {
            "view_id": self.view_id,
            "source_fingerprint": self.context.source_fingerprint,
            "as_of": self.context.as_of.isoformat(),
            "compatibility_mode": self.context.compatibility_mode,
            "enforcement_mode": self.context.enforcement_mode,
        }


def resolve_view(
    source: WorkspaceInput,
    context: Optional[ViewContext] = None,
) -> ResolvedView:
    """Resolve the internal Phase 1 report view.

    Later enforcement modes deliberately fail here instead of being silently
    treated as report mode; their quarantine semantics are not yet frozen.
    """
    compiled = ensure_compiled(source)
    if context is None:
        context = ViewContext(
            source_fingerprint=compiled.source_fingerprint,
            as_of=_dt.date.today(),
        )
    if context.source_fingerprint != compiled.source_fingerprint:
        raise ValueError("ViewContext source_fingerprint does not match workspace")
    if context.enforcement_mode != "report":
        raise ValueError("Phase 1 supports only enforcement_mode='report'")

    current = tuple(current_declarations(compiled))
    current_objects = {id(declaration) for declaration in current}
    authoritative = tuple(
        declaration for declaration in current
        if declaration.status == "active"
    )
    provisional = tuple(
        declaration for declaration in current
        if declaration.status != "active"
    )
    excluded = tuple(
        declaration for declaration in compiled.declarations
        if id(declaration) not in current_objects
    )
    return ResolvedView(
        view_id=_view_id(context),
        context=context,
        authoritative=authoritative,
        provisional=provisional,
        quarantined=(),
        excluded=excluded,
        diagnostics=compiled.diagnostics,
    )


def diagnostic_summary(
    diagnostics: Tuple[CompilationDiagnostic, ...],
) -> dict:
    codes = {}
    errors = 0
    warnings = 0
    for diagnostic in diagnostics:
        codes[diagnostic.code] = codes.get(diagnostic.code, 0) + 1
        if diagnostic.severity == "error":
            errors += 1
        elif diagnostic.severity == "warning":
            warnings += 1
    return {
        "total": len(diagnostics),
        "errors": errors,
        "warnings": warnings,
        "codes": dict(sorted(codes.items())),
    }


def _view_id(context: ViewContext) -> str:
    principal_digest = (
        hashlib.sha256(context.principal.encode("utf-8")).hexdigest()
        if context.principal is not None else "anonymous"
    )
    payload = {
        "view_contract": VIEW_CONTRACT_VERSION,
        "source_fingerprint": context.source_fingerprint,
        "as_of": context.as_of.isoformat(),
        "principal": principal_digest,
        "granted_scopes": sorted(context.granted_scopes),
        "policy_version": context.policy_version,
        "compatibility_mode": context.compatibility_mode,
        "enforcement_mode": context.enforcement_mode,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
