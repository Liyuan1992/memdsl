"""Linter: code-style diagnostics for memory source.

Implements the v0.5 schema-driven rule set from the spec:

    unresolved_symbol           error    subject/relation target not defined
    ambiguous_relation_target  error    relation target resolves to many occurrences
    relation_target_kind_mismatch error full id uses the wrong type prefix
    unknown_relation           error    nested relation key is not registered
    revision_cycle             error    supersedes/revision_of cycle
    supersedes_fork            warning  multiple active successors share a target
    ambiguous_alias             warning  alias resolves to multiple symbols
    duplicate_declaration_id    error    same id declared twice
    duplicate_declaration       warning  same type+subject+scope+claim
    missing_evidence            error    active long-term declaration without evidence
    unknown_memory_type         error    no loaded schema defines this type
    missing_required_field      error    type schema requires a missing field
    unknown_type_field          error    strict type schema does not allow a field
    type_force_mismatch         warning  force is outside the type schema policy
    stale_memory                warning  temporal memory is expired or too old
    module_too_large            warning  module exceeds declaration budget
    invalid_guard               error    guard is not a nested block
    invalid_guard_regex         error    guard contains an invalid regex
    unknown_guard_field         warning  guard field is not defined
    guard_without_rule          warning  guard has no deny/require condition
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import List, Optional

from memdsl.compiler import WorkspaceInput, ensure_compiled
from memdsl.model import Declaration

STALE_STATE_DAYS = 180
MODULE_MAX_DECLARATIONS = 50

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GUARD_FIELDS = {
    "when_any", "deny_any", "deny_regex", "require_any", "require_regex",
}


@dataclass
class Diagnostic:
    code: str
    severity: str  # 'error' | 'warning'
    message: str
    file: str
    line: int
    decl_id: Optional[str] = None

    def render(self) -> str:
        return f"{self.file}:{self.line}: {self.severity}[{self.code}] {self.message}"


def _parse_date(value) -> Optional[_dt.date]:
    if isinstance(value, str) and _DATE_RE.match(value.strip()):
        try:
            return _dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _present(d: Declaration, field_name: str) -> bool:
    if field_name == "lifecycle":
        return bool(d.lifecycle)
    if field_name == "access_policy":
        return bool(d.access_policy)
    value = d.field(field_name)
    return value not in (None, "", [], {})


def _code(d: Declaration, capability: str, default: str) -> str:
    if d.type_descriptor is None:
        return default
    return str(d.type_descriptor.diagnostic_codes.get(capability, default))


def lint(ws: WorkspaceInput, today: Optional[_dt.date] = None) -> List[Diagnostic]:
    today = today or _dt.date.today()
    compiled = ensure_compiled(ws)
    ws = compiled.workspace
    diags: List[Diagnostic] = []
    known = ws.known_names() | ws.known_symbols()

    # duplicate content (same type+subject+scope+claim)
    seen_content = {}
    for d in ws.declarations:
        claim = d.claim_text.strip().lower()
        if not claim:
            continue
        key = (d.kind, d.subject, d.scope, claim)
        if key in seen_content and seen_content[key].id != d.id:
            diags.append(Diagnostic(
                "duplicate_declaration", "warning",
                f"'{d.id}' duplicates '{seen_content[key].id}' "
                f"(same type/subject/scope/claim)",
                d.file, d.line, d.id))
        else:
            seen_content.setdefault(key, d)

    # ambiguous aliases
    for alias, symbols in ws.alias_map().items():
        if len(set(symbols)) > 1:
            owners = ", ".join(sorted(set(symbols)))
            symbol = ws.by_id(sorted(set(symbols))[0])
            diags.append(Diagnostic(
                "ambiguous_alias", "warning",
                f"alias '{alias}' resolves to multiple symbols: {owners}",
                symbol.file if symbol else "<workspace>",
                symbol.line if symbol else 0))

    for d in ws.declarations:
        descriptor = d.type_descriptor

        if descriptor is None:
            diags.append(Diagnostic(
                "unknown_memory_type", "error",
                f"memory type '{d.kind}' is not defined by any loaded schema",
                d.file, d.line, d.id))
        else:
            for required in descriptor.required_fields:
                if _present(d, required):
                    continue
                code = "missing_evidence" if required == "evidence" else "missing_required_field"
                message = (
                    f"active {d.kind} '{d.name}' has no evidence block "
                    f"(use lifecycle.status: candidate for unconfirmed memories)"
                    if required == "evidence"
                    else f"memory type '{d.kind}' requires field '{required}'"
                )
                if required != "evidence" or d.status == "active":
                    diags.append(Diagnostic(
                        code, "error", message, d.file, d.line, d.id))

            if not descriptor.allow_extra_fields:
                unknown_fields = sorted(set(d.fields) - descriptor.allowed_fields)
                for field_name in unknown_fields:
                    diags.append(Diagnostic(
                        "unknown_type_field", "error",
                        f"memory type '{d.kind}' does not allow field '{field_name}'",
                        d.file, d.line, d.id))

        # unresolved subject symbol
        subject = d.subject
        if subject and subject not in known:
            diags.append(Diagnostic(
                "unresolved_symbol", "error",
                f"subject '{subject}' is not a declared symbol",
                d.file, d.line, d.id))

        # evidence capability (covers defaults and schemas that prefer a
        # capability over listing evidence in required_fields)
        if (descriptor is not None
                and descriptor.has_capability("requires_evidence")
                and d.status == "active"
                and d.evidence is None
                and "evidence" not in descriptor.required_fields):
            diags.append(Diagnostic(
                "missing_evidence", "error",
                f"active {d.kind} '{d.name}' has no evidence block "
                f"(use lifecycle.status: candidate for unconfirmed memories)",
                d.file, d.line, d.id))

        # schemas can recommend explicit exceptions for constraints
        if (descriptor is not None
                and descriptor.has_capability("exceptions_recommended")
                and "exceptions" not in d.fields):
            diags.append(Diagnostic(
                _code(d, "exceptions_recommended", "missing_recommended_exceptions"),
                "warning",
                f"constraint '{d.id}' declares no exceptions; confirm it is "
                f"truly unconditional or add e.g. [user_explicit_override]",
                d.file, d.line, d.id))

        # executable compliance guard is a capability, not a hard-coded type
        if "guard" in d.fields:
            guard = d.fields.get("guard")
            if descriptor is not None and not descriptor.has_capability("guardable"):
                diags.append(Diagnostic(
                    "unsupported_type_capability", "error",
                    f"memory type '{d.kind}' does not support guard",
                    d.file, d.line, d.id))
            if not isinstance(guard, dict):
                diags.append(Diagnostic(
                    "invalid_guard", "error",
                    f"memory '{d.id}' guard must be a nested block",
                    d.file, d.line, d.id))
            else:
                unknown = sorted(set(guard) - _GUARD_FIELDS)
                if unknown:
                    diags.append(Diagnostic(
                        "unknown_guard_field", "warning",
                        f"memory '{d.id}' guard has unknown field(s): "
                        f"{', '.join(unknown)}",
                        d.file, d.line, d.id))
                if not any(guard.get(key) for key in (
                        "deny_any", "deny_regex", "require_any", "require_regex")):
                    diags.append(Diagnostic(
                        "guard_without_rule", "warning",
                        f"memory '{d.id}' guard has no deny or require condition",
                        d.file, d.line, d.id))
                for field_name in ("deny_regex", "require_regex"):
                    raw = guard.get(field_name, [])
                    patterns = raw if isinstance(raw, list) else [raw]
                    for pattern in patterns:
                        try:
                            re.compile(str(pattern))
                        except re.error as exc:
                            diags.append(Diagnostic(
                                "invalid_guard_regex", "error",
                                f"memory '{d.id}' {field_name} pattern "
                                f"{pattern!r} is invalid: {exc}",
                                d.file, d.line, d.id))

        # force policy comes from the type descriptor
        if (descriptor is not None and d.force
                and descriptor.allowed_forces
                and d.force not in descriptor.allowed_forces):
            diags.append(Diagnostic(
                "type_force_mismatch", "warning",
                f"memory type '{d.kind}' does not allow force '{d.force}'; "
                f"allowed: {', '.join(descriptor.allowed_forces)}",
                d.file, d.line, d.id))

        # temporal lifecycle is also schema-driven
        if (descriptor is not None
                and descriptor.has_capability("temporal")
                and d.status == "active"):
            valid_until = _parse_date(d.lifecycle.get("valid_until"))
            as_of = _parse_date(d.lifecycle.get("as_of"))
            stale_code = _code(d, "stale", "stale_memory")
            if valid_until is not None and valid_until < today:
                diags.append(Diagnostic(
                    stale_code, "warning",
                    f"temporal memory '{d.id}' expired on {valid_until.isoformat()}",
                    d.file, d.line, d.id))
            elif as_of is not None and (today - as_of).days > STALE_STATE_DAYS:
                diags.append(Diagnostic(
                    stale_code, "warning",
                    f"temporal memory '{d.id}' as_of {as_of.isoformat()} is older than "
                    f"{STALE_STATE_DAYS} days; re-confirm or supersede it",
                    d.file, d.line, d.id))
            if as_of is None and "as_of" not in d.lifecycle:
                diags.append(Diagnostic(
                    stale_code, "warning",
                    f"temporal memory '{d.id}' has no as_of date",
                    d.file, d.line, d.id))

        # access policy is part of the universal declaration envelope
        access_key = "access_policy" if "access_policy" in d.fields else "access"
        if access_key in d.fields:
            policy = d.fields.get(access_key)
            if not isinstance(policy, dict):
                diags.append(Diagnostic(
                    "invalid_access_policy", "error",
                    f"memory '{d.id}' access policy must be a nested block",
                    d.file, d.line, d.id))
            else:
                allowed_access = {"readers", "writers", "reviewers", "export"}
                unknown_access = sorted(set(policy) - allowed_access)
                if unknown_access:
                    diags.append(Diagnostic(
                        "unknown_access_policy_field", "warning",
                        f"memory '{d.id}' access policy has unknown field(s): "
                        f"{', '.join(unknown_access)}",
                        d.file, d.line, d.id))

    # module size budget
    per_module = {}
    for d in ws.declarations:
        per_module.setdefault(d.module or "<no module>", []).append(d)
    for module, decls in per_module.items():
        if len(decls) > MODULE_MAX_DECLARATIONS:
            diags.append(Diagnostic(
                "module_too_large", "warning",
                f"module '{module}' has {len(decls)} declarations "
                f"(budget {MODULE_MAX_DECLARATIONS}); split it",
                decls[0].file, decls[0].line))

    # Compiler/link diagnostics use the same public Diagnostic shape.  Their
    # deterministic occurrence ordering puts real workspace source before
    # synthetic proposal markers, so a newly introduced duplicate remains
    # anchored to the proposal and the repair/review lane stays fail-closed.
    for diagnostic in compiled.diagnostics:
        diags.append(Diagnostic(
            diagnostic.code,
            diagnostic.severity,
            diagnostic.message,
            diagnostic.file,
            diagnostic.line,
            diagnostic.decl_id,
        ))

    return sorted(diags, key=lambda x: (x.file, x.line, x.code, x.message))


def has_errors(diags: List[Diagnostic]) -> bool:
    return any(d.severity == "error" for d in diags)
