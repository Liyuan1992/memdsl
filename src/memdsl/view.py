"""Deterministic report, quarantine, and strict resolved views.

Phase 5 keeps legacy/report serving behavior intact and enables enforcement
only for ``memdsl.workspace.v2``/``v3`` workspaces that explicitly opt in. Source is
still authoritative; this module classifies declarations for one read context
without editing source or closing the lint/review repair lane.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import FrozenSet, Mapping, Optional, Sequence, Tuple

from memdsl.authority import current_declarations
from memdsl.compiler import (
    CompilationDiagnostic,
    CompiledWorkspace,
    WorkspaceInput,
    ensure_compiled,
)
from memdsl.model import Declaration, EXCLUDED_STATUSES


VIEW_CONTRACT_VERSION = "memdsl.resolved_view.phase5.v1"
RESOLVED_VIEW_SCHEMA = "memdsl.resolved_view.v1"


@dataclass(frozen=True)
class DiagnosticEnforcement:
    """Pollution scope applied by quarantine and strict modes."""

    quarantine: str = "report"
    strict: str = "report"

    def for_mode(self, mode: str) -> str:
        return self.strict if mode == "strict" else self.quarantine


# Stable Phase 5 enforcement table.  ``declaration`` isolates the diagnostic
# owner, ``file`` isolates declarations whose lexical module/use context is
# uncertain, ``family_sources`` isolates fork successors, ``family`` isolates
# every explicit revision-family participant, and ``workspace`` fails closed.
ENFORCEMENT_TABLE = MappingProxyType({
    "duplicate_declaration_id": DiagnosticEnforcement("workspace", "workspace"),
    "revision_cycle": DiagnosticEnforcement("family", "family"),
    "supersedes_fork": DiagnosticEnforcement("family_sources", "family"),
    "ambiguous_use_target": DiagnosticEnforcement("file", "file"),
    "unresolved_use_target": DiagnosticEnforcement("file", "file"),
    "unsupported_use_wildcard": DiagnosticEnforcement("file", "file"),
    "multiple_module_statements": DiagnosticEnforcement("file", "file"),
    "visibility_violation": DiagnosticEnforcement("declaration", "declaration"),
    "unresolved_symbol": DiagnosticEnforcement("declaration", "declaration"),
    "ambiguous_relation_target": DiagnosticEnforcement(
        "declaration", "declaration"),
    "relation_target_kind_mismatch": DiagnosticEnforcement(
        "declaration", "declaration"),
    "unknown_relation": DiagnosticEnforcement("declaration", "declaration"),
    "invalid_dialect_mapping": DiagnosticEnforcement(
        "declaration", "declaration"),
    "unsupported_dialect_polarity": DiagnosticEnforcement(
        "declaration", "declaration"),
    "ambiguous_dialect_mapping": DiagnosticEnforcement(
        "declaration", "declaration"),
    "unknown_memory_type": DiagnosticEnforcement("declaration", "declaration"),
    "missing_evidence": DiagnosticEnforcement("declaration", "declaration"),
    "missing_required_field": DiagnosticEnforcement(
        "declaration", "declaration"),
    "unknown_type_field": DiagnosticEnforcement("declaration", "declaration"),
    "unsupported_type_capability": DiagnosticEnforcement(
        "declaration", "declaration"),
    "invalid_guard": DiagnosticEnforcement("declaration", "declaration"),
    "invalid_guard_regex": DiagnosticEnforcement(
        "declaration", "declaration"),
    "unknown_guard_field": DiagnosticEnforcement(
        "declaration", "declaration"),
    "invalid_access_policy": DiagnosticEnforcement(
        "declaration", "declaration"),
    "unknown_access_policy_field": DiagnosticEnforcement(
        "declaration", "declaration"),
    "invalid_lifecycle_date": DiagnosticEnforcement(
        "declaration", "declaration"),
})


@dataclass(frozen=True)
class ViewDiagnostic:
    """A compiler/lint diagnostic annotated with its Phase 5 policy."""

    code: str
    severity: str
    message: str
    file: str
    line: int
    decl_id: Optional[str] = None
    related_ids: Tuple[str, ...] = ()
    enforcement_scope: str = "report"


@dataclass(frozen=True)
class ViewContext:
    """Inputs that identify one deterministic checkout."""

    source_fingerprint: str
    as_of: _dt.date
    principal: Optional[str] = None
    granted_scopes: FrozenSet[str] = field(default_factory=frozenset)
    policy_version: str = ""
    compatibility_mode: str = "v0.6"
    enforcement_mode: str = "report"
    principal_trusted: bool = False
    principal_roles: FrozenSet[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ResolvedView:
    """One classified read view over a compiled workspace."""

    view_id: str
    context: ViewContext
    authoritative: Tuple[Declaration, ...]
    provisional: Tuple[Declaration, ...]
    quarantined: Tuple[Declaration, ...]
    excluded: Tuple[Declaration, ...]
    diagnostics: Tuple[ViewDiagnostic, ...]
    status: str = "ok"
    blocking_diagnostics: Tuple[ViewDiagnostic, ...] = ()
    quarantine_reasons: Mapping[int, Tuple[str, ...]] = field(
        default_factory=dict, repr=False, compare=False)
    excluded_reasons: Mapping[int, Tuple[str, ...]] = field(
        default_factory=dict, repr=False, compare=False)
    unauthorized: Tuple[Declaration, ...] = field(
        default=(), repr=False, compare=False)
    compiled: Optional[CompiledWorkspace] = field(
        default=None, repr=False, compare=False)

    @property
    def enforcement_active(self) -> bool:
        return self.context.enforcement_mode in {"quarantine", "strict"}

    @property
    def blocked(self) -> bool:
        return self.status == "compiler_error"

    def diagnostic_summary(self) -> dict:
        return diagnostic_summary(self.diagnostics)

    def metadata(self) -> dict:
        metadata = {
            "view_id": self.view_id,
            "source_fingerprint": self.context.source_fingerprint,
            "as_of": self.context.as_of.isoformat(),
            "compatibility_mode": self.context.compatibility_mode,
            "enforcement_mode": self.context.enforcement_mode,
        }
        if self.enforcement_active:
            metadata.update({
                "schema_version": RESOLVED_VIEW_SCHEMA,
                "status": self.status,
            })
        return metadata

    def lane_for(self, declaration: Declaration) -> str:
        object_id = id(declaration)
        for lane in ("authoritative", "provisional", "quarantined", "excluded"):
            if any(id(item) == object_id for item in getattr(self, lane)):
                return lane
        return "excluded"

    def reasons_for(self, declaration: Declaration) -> Tuple[str, ...]:
        return (
            self.quarantine_reasons.get(id(declaration))
            or self.excluded_reasons.get(id(declaration))
            or ()
        )

    def public_counts(self) -> dict:
        unauthorized = {id(item) for item in self.unauthorized}
        return {
            "authoritative": len(self.authoritative),
            "provisional": len(self.provisional),
            "quarantined": len(self.quarantined),
            "excluded": sum(
                1 for item in self.excluded if id(item) not in unauthorized),
            "served": len(self.authoritative) + len(self.provisional),
        }

    def envelope(
        self,
        *,
        include_diagnostics: bool = True,
        include_quarantined: bool = True,
    ) -> dict:
        """Return the access-filtered Phase 5 view envelope."""
        visible_diagnostics = self.visible_diagnostics()
        visible_blocking = tuple(
            item for item in self.blocking_diagnostics
            if item in visible_diagnostics)
        payload = {
            "schema_version": RESOLVED_VIEW_SCHEMA,
            "status": self.status,
            "view": self.metadata(),
            "counts": self.public_counts(),
            "diagnostic_summary": _enforcement_summary(
                visible_diagnostics, visible_blocking),
        }
        if include_diagnostics:
            payload["diagnostics"] = [
                _diagnostic_dict(item, self) for item in visible_diagnostics]
        if include_quarantined:
            payload["quarantined"] = [
                {
                    "id": item.id,
                    "reasons": list(self.quarantine_reasons.get(id(item), ())),
                }
                for item in self.quarantined
            ]
        return payload

    def visible_diagnostics(self) -> Tuple[ViewDiagnostic, ...]:
        """Hide diagnostics whose source is entirely unauthorized."""
        unauthorized = {id(item) for item in self.unauthorized}
        if self.compiled is None:
            return self.diagnostics
        visible = []
        for diagnostic in self.diagnostics:
            if unauthorized:
                owned = (
                    tuple(self.compiled.occurrences_by_id.get(
                        diagnostic.decl_id, ()))
                    if diagnostic.decl_id else ()
                )
                if owned and all(id(item) in unauthorized for item in owned):
                    continue
                file_items = tuple(
                    item for item in self.compiled.declarations
                    if item.file == diagnostic.file)
                if not owned and file_items and all(
                        id(item) in unauthorized for item in file_items):
                    continue
            visible.append(diagnostic)
        if self.compiled.workspace.explicit_edges_enabled:
            visible_edge_ids = _readable_explicit_diagnostic_ids(self)
            visible = [
                diagnostic for diagnostic in visible
                if (
                    not str(diagnostic.decl_id or "").startswith((
                        "relation_edge:", "relation_edge_event:"))
                    or str(diagnostic.decl_id) in visible_edge_ids
                )
            ]
        return tuple(visible)


def resolve_view(
    source: WorkspaceInput,
    context: Optional[ViewContext] = None,
) -> ResolvedView:
    """Resolve a report-compatible or explicitly enforced workspace view."""
    compiled = ensure_compiled(source)
    configured = compiled.enforcement_mode
    if context is None:
        mode = configured if configured in {"quarantine", "strict"} else "report"
        context = ViewContext(
            source_fingerprint=compiled.source_fingerprint,
            as_of=_dt.date.today(),
            compatibility_mode=(
                "workspace.v2"
                if (
                    mode in {"quarantine", "strict"}
                    and compiled.workspace_schema_version == "memdsl.workspace.v2"
                )
                else compiled.workspace_schema_version
                if mode in {"quarantine", "strict"}
                else "v0.6"),
            enforcement_mode=mode,
        )
    if context.source_fingerprint != compiled.source_fingerprint:
        raise ValueError("ViewContext source_fingerprint does not match workspace")
    if context.enforcement_mode not in {"report", "quarantine", "strict"}:
        raise ValueError(
            "enforcement_mode must be 'report', 'quarantine', or 'strict'")
    if (
        context.enforcement_mode in {"quarantine", "strict"}
        and compiled.workspace_schema_version not in {
            "memdsl.workspace.v2", "memdsl.workspace.v3"}
    ):
        raise ValueError(
            "quarantine/strict enforcement requires memdsl.workspace.v2 or v3")

    if context.enforcement_mode == "report":
        return _report_view(compiled, context)
    return _enforced_view(compiled, context)


def diagnostic_summary(diagnostics: Sequence[object]) -> dict:
    codes = {}
    errors = 0
    warnings = 0
    for diagnostic in diagnostics:
        code = str(getattr(diagnostic, "code", ""))
        severity = str(getattr(diagnostic, "severity", ""))
        codes[code] = codes.get(code, 0) + 1
        if severity == "error":
            errors += 1
        elif severity == "warning":
            warnings += 1
    return {
        "total": len(diagnostics),
        "errors": errors,
        "warnings": warnings,
        "codes": dict(sorted(codes.items())),
    }


def _report_view(compiled: CompiledWorkspace, context: ViewContext) -> ResolvedView:
    current = tuple(current_declarations(compiled))
    current_objects = {id(declaration) for declaration in current}
    authoritative = tuple(
        declaration for declaration in current if declaration.status == "active")
    provisional = tuple(
        declaration for declaration in current if declaration.status != "active")
    excluded = tuple(
        declaration for declaration in compiled.declarations
        if id(declaration) not in current_objects)
    diagnostics = (
        _all_diagnostics(compiled, context)
        if compiled.workspace.explicit_edges_enabled else
        tuple(_compiler_diagnostic(item) for item in compiled.diagnostics)
    )
    return ResolvedView(
        view_id=_view_id(context),
        context=context,
        authoritative=authoritative,
        provisional=provisional,
        quarantined=(),
        excluded=excluded,
        diagnostics=diagnostics,
        compiled=compiled,
    )


def _enforced_view(
    compiled: CompiledWorkspace,
    context: ViewContext,
) -> ResolvedView:
    diagnostics = _all_diagnostics(compiled, context)
    unauthorized = tuple(
        item for item in compiled.declarations if not _readable(item, context))
    unauthorized_objects = {id(item) for item in unauthorized}
    quarantined_objects, reasons, blocking = _quarantine_objects(
        compiled, diagnostics, context.enforcement_mode)

    ordered = tuple(sorted(compiled.declarations, key=_declaration_sort_key))
    if blocking:
        quarantined = tuple(
            item for item in ordered if id(item) not in unauthorized_objects)
        blocked_reasons = tuple(sorted({item.code for item in blocking}))
        reason_map = {
            id(item): tuple(
                sorted(set(reasons.get(id(item), ())) | set(blocked_reasons)))
            for item in quarantined
        }
        excluded_reasons = {
            id(item): ("unauthorized",) for item in unauthorized}
        return ResolvedView(
            view_id=_view_id(context),
            context=context,
            authoritative=(),
            provisional=(),
            quarantined=quarantined,
            excluded=unauthorized,
            diagnostics=diagnostics,
            status="compiler_error",
            blocking_diagnostics=blocking,
            quarantine_reasons=MappingProxyType(reason_map),
            excluded_reasons=MappingProxyType(excluded_reasons),
            unauthorized=unauthorized,
            compiled=compiled,
        )

    superseded = set()
    for edge in compiled.authoritative_supersedes:
        source_declaration = compiled.resolved_by_id.get(edge.source_id)
        if source_declaration is None:
            continue
        if id(source_declaration) in quarantined_objects:
            continue
        if id(source_declaration) in unauthorized_objects:
            continue
        if edge.target_id is not None:
            superseded.add(edge.target_id)

    authoritative = []
    provisional = []
    quarantined = []
    excluded = []
    excluded_reasons = {}
    for declaration in ordered:
        object_id = id(declaration)
        if object_id in unauthorized_objects:
            excluded.append(declaration)
            excluded_reasons[object_id] = ("unauthorized",)
        elif object_id in quarantined_objects:
            quarantined.append(declaration)
        elif declaration.status in EXCLUDED_STATUSES:
            excluded.append(declaration)
            excluded_reasons[object_id] = (
                "lifecycle:" + declaration.status,)
        elif _expired(declaration, context.as_of):
            excluded.append(declaration)
            excluded_reasons[object_id] = ("expired",)
        elif declaration.id in superseded:
            excluded.append(declaration)
            excluded_reasons[object_id] = ("superseded",)
        elif declaration.status == "active":
            authoritative.append(declaration)
        else:
            provisional.append(declaration)

    return ResolvedView(
        view_id=_view_id(context),
        context=context,
        authoritative=tuple(authoritative),
        provisional=tuple(provisional),
        quarantined=tuple(quarantined),
        excluded=tuple(excluded),
        diagnostics=diagnostics,
        quarantine_reasons=MappingProxyType({
            key: tuple(sorted(value)) for key, value in reasons.items()}),
        excluded_reasons=MappingProxyType(excluded_reasons),
        unauthorized=unauthorized,
        compiled=compiled,
    )


def _all_diagnostics(
    compiled: CompiledWorkspace,
    context: ViewContext,
) -> Tuple[ViewDiagnostic, ...]:
    # Import lazily so the linter can continue to depend on compiler without a
    # module initialization cycle.
    from memdsl.linter import lint

    compiler_by_key = {
        _diagnostic_key(item): item for item in compiled.diagnostics}
    seen = set()
    result = []
    for item in lint(compiled, today=context.as_of):
        key = _diagnostic_key(item)
        if key in seen:
            continue
        seen.add(key)
        compiler_item = compiler_by_key.get(key)
        related_ids = (
            compiler_item.related_ids if compiler_item is not None else ())
        policy = _policy_for(item.code, item.severity, item.decl_id)
        result.append(ViewDiagnostic(
            code=item.code,
            severity=item.severity,
            message=item.message,
            file=item.file,
            line=item.line,
            decl_id=item.decl_id,
            related_ids=related_ids,
            enforcement_scope=policy.for_mode(context.enforcement_mode),
        ))
    return tuple(sorted(result, key=_view_diagnostic_sort_key))


def _quarantine_objects(
    compiled: CompiledWorkspace,
    diagnostics: Tuple[ViewDiagnostic, ...],
    mode: str,
) -> Tuple[set, dict, Tuple[ViewDiagnostic, ...]]:
    quarantined = set()
    reasons = {}
    blocking = []
    for diagnostic in diagnostics:
        scope = diagnostic.enforcement_scope
        if scope == "report":
            continue
        if scope == "workspace":
            blocking.append(diagnostic)
            continue
        declarations = []
        if scope == "declaration":
            declarations.extend(
                compiled.occurrences_by_id.get(diagnostic.decl_id or "", ()))
        elif scope == "file":
            declarations.extend(
                item for item in compiled.declarations
                if item.file == diagnostic.file)
        elif scope == "family_sources":
            declarations.extend(
                compiled.occurrences_by_id.get(diagnostic.decl_id or "", ()))
        elif scope == "family":
            family_ids = set(diagnostic.related_ids)
            if diagnostic.decl_id:
                family_ids.add(diagnostic.decl_id)
            for declaration_id in sorted(family_ids):
                declarations.extend(
                    compiled.occurrences_by_id.get(declaration_id, ()))
        for declaration in declarations:
            object_id = id(declaration)
            quarantined.add(object_id)
            reasons.setdefault(object_id, set()).add(diagnostic.code)
    return quarantined, reasons, tuple(blocking)


def _policy_for(
    code: str,
    severity: str,
    decl_id: Optional[str],
) -> DiagnosticEnforcement:
    policy = ENFORCEMENT_TABLE.get(code)
    if policy is not None:
        return policy
    if severity == "error":
        fallback = "declaration" if decl_id else "file"
        return DiagnosticEnforcement(fallback, fallback)
    return DiagnosticEnforcement()


def _readable(declaration: Declaration, context: ViewContext) -> bool:
    raw = None
    if "access_policy" in declaration.fields:
        raw = declaration.fields.get("access_policy")
    elif "access" in declaration.fields:
        raw = declaration.fields.get("access")
    return access_policy_readable(raw, context)


def access_policy_readable(raw, context: ViewContext) -> bool:
    """Evaluate one record-level access policy without exposing object identity."""
    if raw is None or raw == {}:
        return True
    if not isinstance(raw, Mapping):
        return False
    readers = raw.get("readers")
    if not context.principal_trusted or not context.principal:
        return False
    if not isinstance(readers, list) or any(
            not isinstance(item, str) for item in readers):
        return False
    allowed = {item.strip() for item in readers if item.strip()}
    identities = {context.principal} | set(context.principal_roles)
    return "*" in allowed or bool(allowed & identities)


def _readable_explicit_diagnostic_ids(view: ResolvedView) -> set:
    """Return Edge/event ids whose record and resolved endpoints are readable."""
    compiled = view.compiled
    if compiled is None:
        return set()
    readable = set()
    for edge in compiled.explicit_edges:
        if not access_policy_readable(edge.access_policy, view.context):
            continue
        endpoint_hidden = False
        for endpoint_id in (edge.source_id, edge.target_id):
            if endpoint_id is None:
                continue
            endpoint = compiled.resolved_by_id.get(endpoint_id)
            if endpoint is not None and not _readable(endpoint, view.context):
                endpoint_hidden = True
                break
        if not endpoint_hidden:
            for candidate_id in edge.candidate_ids:
                occurrences = compiled.occurrences_by_id.get(candidate_id, ())
                if occurrences and any(
                        not _readable(item, view.context)
                        for item in occurrences):
                    endpoint_hidden = True
                    break
        if endpoint_hidden:
            continue
        readable.add(edge.edge_id)
        readable.update(
            event.event_id
            for event in compiled.edge_events_by_edge.get(edge.edge_id, ()))
    return readable


def _expired(declaration: Declaration, as_of: _dt.date) -> bool:
    value = declaration.lifecycle.get("valid_until")
    if value is None:
        return False
    try:
        return _dt.date.fromisoformat(str(value)) < as_of
    except ValueError:
        return False


def _compiler_diagnostic(item: CompilationDiagnostic) -> ViewDiagnostic:
    return ViewDiagnostic(
        code=item.code,
        severity=item.severity,
        message=item.message,
        file=item.file,
        line=item.line,
        decl_id=item.decl_id,
        related_ids=item.related_ids,
    )


def _diagnostic_key(item: object) -> tuple:
    return (
        getattr(item, "code", ""),
        getattr(item, "severity", ""),
        getattr(item, "message", ""),
        getattr(item, "file", ""),
        getattr(item, "line", 0),
        getattr(item, "decl_id", None),
    )


def _view_diagnostic_sort_key(item: ViewDiagnostic) -> tuple:
    return (
        item.file,
        item.line,
        item.code,
        item.decl_id or "",
        item.message,
        item.related_ids,
    )


def _declaration_sort_key(item: Declaration) -> tuple:
    return (item.id, item.file, item.line)


def _diagnostic_dict(item: ViewDiagnostic, view: ResolvedView) -> dict:
    unauthorized_ids = {declaration.id for declaration in view.unauthorized}
    restricted_related = bool(set(item.related_ids) & unauthorized_ids)
    return {
        "code": item.code,
        "severity": item.severity,
        "scope": item.enforcement_scope,
        "message": (
            "diagnostic details withheld by access policy"
            if restricted_related else item.message),
        "file": os.path.basename(item.file) if item.file else item.file,
        "line": item.line,
        "decl_id": item.decl_id,
        "related_ids": (
            [] if restricted_related else list(item.related_ids)),
    }


def _enforcement_summary(
    diagnostics: Sequence[ViewDiagnostic],
    blocking: Sequence[ViewDiagnostic],
) -> dict:
    summary = diagnostic_summary(diagnostics)
    summary.update({
        "blocking": len(blocking),
        "enforced": sum(
            1 for item in diagnostics if item.enforcement_scope != "report"),
    })
    return summary


def _view_id(context: ViewContext) -> str:
    principal_digest = (
        hashlib.sha256(context.principal.encode("utf-8")).hexdigest()
        if context.principal_trusted and context.principal is not None
        else "anonymous"
    )
    payload = {
        "view_contract": VIEW_CONTRACT_VERSION,
        "source_fingerprint": context.source_fingerprint,
        "as_of": context.as_of.isoformat(),
        "principal": principal_digest,
        "principal_trusted": context.principal_trusted,
        "principal_roles": (
            sorted(context.principal_roles) if context.principal_trusted else []),
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
