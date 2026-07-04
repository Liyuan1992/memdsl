"""Linter: code-style diagnostics for memory source.

Implements the v0.1 rule set from the spec:

    unresolved_symbol           error    subject/relation target not defined
    ambiguous_alias             warning  alias resolves to multiple entities
    duplicate_declaration_id    error    same id declared twice
    duplicate_declaration       warning  same kind+subject+scope+claim
    missing_evidence            error    active long-term declaration without evidence
    boundary_without_exception  warning  hard boundary with no exceptions list
    type_force_mismatch         warning  preference:hard or boundary:advisory
    stale_state                 warning  state past valid_until / as_of too old
    unmarked_supersede_status   warning  superseded target not marked superseded
    module_too_large            warning  module exceeds declaration budget
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import List, Optional

from memdsl.model import Workspace, Declaration

STALE_STATE_DAYS = 180
MODULE_MAX_DECLARATIONS = 50

#: Kinds that require evidence when active (entities and open issues are exempt).
EVIDENCE_REQUIRED_KINDS = {
    "fact", "preference", "boundary", "principle", "decision", "state",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def lint(ws: Workspace, today: Optional[_dt.date] = None) -> List[Diagnostic]:
    today = today or _dt.date.today()
    diags: List[Diagnostic] = []
    known = ws.known_names() | ws.known_symbols()
    superseded_targets = ws.superseded_ids()

    # duplicate ids
    seen_ids = {}
    for d in ws.declarations:
        if d.id in seen_ids:
            first = seen_ids[d.id]
            diags.append(Diagnostic(
                "duplicate_declaration_id", "error",
                f"'{d.id}' already declared at {first.file}:{first.line}",
                d.file, d.line, d.id))
        else:
            seen_ids[d.id] = d

    # duplicate content (same kind+subject+scope+claim)
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
                f"(same kind/subject/scope/claim)",
                d.file, d.line, d.id))
        else:
            seen_content.setdefault(key, d)

    # ambiguous aliases
    for alias, symbols in ws.alias_map().items():
        if len(set(symbols)) > 1:
            owners = ", ".join(sorted(set(symbols)))
            entity = ws.by_id(sorted(set(symbols))[0])
            diags.append(Diagnostic(
                "ambiguous_alias", "warning",
                f"alias '{alias}' resolves to multiple entities: {owners}",
                entity.file if entity else "<workspace>",
                entity.line if entity else 0))

    for d in ws.declarations:
        # unresolved subject symbol
        subject = d.subject
        if subject and subject not in known:
            diags.append(Diagnostic(
                "unresolved_symbol", "error",
                f"subject '{subject}' is not a declared entity or known symbol",
                d.file, d.line, d.id))

        # unresolved relation targets
        for rel, targets in d.relations().items():
            for target in targets:
                bare = target.split(":", 1)[-1]
                if target not in known and bare not in known:
                    diags.append(Diagnostic(
                        "unresolved_symbol", "error",
                        f"relation '{rel}' points to unknown declaration '{target}'",
                        d.file, d.line, d.id))

        # missing evidence
        if (d.kind in EVIDENCE_REQUIRED_KINDS
                and d.status == "active"
                and d.evidence is None):
            diags.append(Diagnostic(
                "missing_evidence", "error",
                f"active {d.kind} '{d.name}' has no evidence block "
                f"(use status: candidate for unconfirmed memories)",
                d.file, d.line, d.id))

        # boundary without exception
        if d.kind == "boundary" and "exceptions" not in d.fields:
            diags.append(Diagnostic(
                "boundary_without_exception", "warning",
                f"boundary '{d.name}' declares no exceptions; confirm it is "
                f"truly unconditional or add e.g. [user_explicit_override]",
                d.file, d.line, d.id))

        # type/force mismatch
        if d.kind == "preference" and d.force == "hard":
            diags.append(Diagnostic(
                "type_force_mismatch", "warning",
                f"preference '{d.name}' uses force: hard; promote it to a "
                f"boundary or lower its force",
                d.file, d.line, d.id))
        if d.kind == "boundary" and d.force == "advisory":
            diags.append(Diagnostic(
                "type_force_mismatch", "warning",
                f"boundary '{d.name}' uses force: advisory; demote it to a "
                f"preference or raise its force",
                d.file, d.line, d.id))

        # stale state
        if d.kind == "state" and d.status == "active":
            valid_until = _parse_date(d.fields.get("valid_until"))
            as_of = _parse_date(d.fields.get("as_of"))
            if valid_until is not None and valid_until < today:
                diags.append(Diagnostic(
                    "stale_state", "warning",
                    f"state '{d.name}' expired on {valid_until.isoformat()}",
                    d.file, d.line, d.id))
            elif as_of is not None and (today - as_of).days > STALE_STATE_DAYS:
                diags.append(Diagnostic(
                    "stale_state", "warning",
                    f"state '{d.name}' as_of {as_of.isoformat()} is older than "
                    f"{STALE_STATE_DAYS} days; re-confirm or supersede it",
                    d.file, d.line, d.id))
            if as_of is None and "as_of" not in d.fields:
                diags.append(Diagnostic(
                    "stale_state", "warning",
                    f"state '{d.name}' has no as_of date; states must be datable",
                    d.file, d.line, d.id))

    # superseded targets whose status is not updated
    for target in superseded_targets:
        td = ws.by_id(target)
        if td is not None and td.status not in ("superseded", "retracted", "archived"):
            diags.append(Diagnostic(
                "unmarked_supersede_status", "warning",
                f"'{td.id}' is superseded by a newer declaration but its "
                f"status is '{td.status}'; mark it status: superseded",
                td.file, td.line, td.id))

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

    return sorted(diags, key=lambda x: (x.file, x.line, x.code))


def has_errors(diags: List[Diagnostic]) -> bool:
    return any(d.severity == "error" for d in diags)
