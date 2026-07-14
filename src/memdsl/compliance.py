"""Deterministic compliance preflight for schema-defined constraints.

The EvidencePack contract makes applicable constraints visible.  The
CompliancePack contract takes the next step: it checks a proposed action or
draft against machine-readable ``guard`` clauses on enforceable types.

Natural-language rules without an executable guard are never guessed at by
the reference implementation.  They produce ``needs_review`` so callers can
route them to a person or a semantic evaluator.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from memdsl.authority import current_declarations
from memdsl.compiler import WorkspaceInput, ensure_compiled
from memdsl.model import Declaration


VERDICTS = ("allow", "block", "needs_review")
GUARD_MATCH_FIELDS = (
    "when_any",
    "deny_any",
    "deny_regex",
    "require_any",
    "require_regex",
)
_WORD_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "before", "by", "for",
    "from", "in", "is", "it", "of", "on", "or", "the", "this", "to",
    "with", "my", "me", "i", "user", "never", "must", "any",
}


def _values(value) -> List[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _contains(text: str, patterns: Sequence[str]) -> List[str]:
    lowered = text.lower()
    return [pattern for pattern in patterns if pattern.lower() in lowered]


def _regex_matches(text: str, patterns: Sequence[str]) -> List[str]:
    matched: List[str] = []
    for pattern in patterns:
        try:
            if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
                matched.append(pattern)
        except re.error:
            # The linter reports invalid patterns.  The checker still fails
            # safely if called on an unlinted workspace.
            continue
    return matched


def _terms(text: str) -> set:
    return {
        token for token in _WORD_RE.findall(text.lower())
        if token not in _STOPWORDS
    }


def _decl_dict(decl: Declaration) -> dict:
    result = {
        "id": decl.id,
        "type": decl.kind,
        "kind": decl.kind,  # backward-compatible alias
        "runtime_role": decl.runtime_role,
        "capabilities": sorted(decl.capabilities),
        "rule": decl.claim_text,
        "force": decl.force,
        "scope": decl.scope,
        "subject": decl.subject,
        "status": decl.status,
        "lifecycle": decl.lifecycle,
        "file": decl.file,
        "line": decl.line,
    }
    if decl.evidence:
        result["evidence"] = decl.evidence
    return result


def _ref(decl: Declaration) -> dict:
    return {
        "id": decl.id,
        "type": decl.kind,
        "runtime_role": decl.runtime_role,
        "status": decl.status,
        "lifecycle": decl.lifecycle,
        # v0.4 compatibility for clients that still read boundary_id.
        "boundary_id": decl.id,
    }


@dataclass
class CompliancePack:
    task: str
    candidate: str
    subject: str = ""
    scope: str = ""
    asserted_exceptions: List[str] = field(default_factory=list)
    verdict: str = "allow"
    applicable_must: List[Declaration] = field(default_factory=list)
    evaluated: List[dict] = field(default_factory=list)
    violations: List[dict] = field(default_factory=list)
    exceptions_applied: List[dict] = field(default_factory=list)
    unknowns: List[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "task": self.task,
            "candidate": self.candidate,
            "subject": self.subject,
            "scope": self.scope,
            "asserted_exceptions": list(self.asserted_exceptions),
            "verdict": self.verdict,
            "applicable_must": [_decl_dict(d) for d in self.applicable_must],
            "applicable_constraints": [_decl_dict(d) for d in self.applicable_must],
            "evaluated": list(self.evaluated),
            "violations": list(self.violations),
            "exceptions_applied": list(self.exceptions_applied),
            "unknowns": list(self.unknowns),
        }

    def render_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)

    def render_text(self) -> str:
        lines = [f"VERDICT: {self.verdict.upper()}", "", "APPLICABLE MUST"]
        if self.applicable_must:
            for decl in self.applicable_must:
                lifecycle = json.dumps(
                    decl.lifecycle, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"))
                lines.append(
                    f"- [{decl.id}] {decl.claim_text} "
                    f"[status={decl.status}; runtime_role={decl.runtime_role}; "
                    f"lifecycle={lifecycle}]")
        else:
            lines.append("- (none)")
        if self.violations:
            lines.extend(["", "VIOLATIONS"])
            for item in self.violations:
                matched = ", ".join(item.get("matched", []))
                suffix = f" (matched: {matched})" if matched else ""
                lines.append(
                    f"- [{item['id']}] {item['reason']}{suffix}")
        if self.exceptions_applied:
            lines.extend(["", "EXCEPTIONS APPLIED"])
            for item in self.exceptions_applied:
                lines.append(
                    f"- [{item['id']}] {', '.join(item['exceptions'])}")
        if self.unknowns:
            lines.extend(["", "NEEDS REVIEW"])
            for item in self.unknowns:
                lines.append(f"- [{item['id']}] {item['reason']}")
        return "\n".join(lines)


def applicable_constraints(
    ws: WorkspaceInput,
    task: str,
    candidate: str = "",
    *,
    subject: Optional[str] = None,
    scope: Optional[str] = None,
) -> List[Declaration]:
    """Return schema-defined constraints relevant to a proposed action.

    Compliance applicability is deliberately narrower than EvidencePack
    retrieval.  EvidencePack may fan MUST rules out through a shared subject
    to maximize visibility; an enforcement decision only accepts global
    constraints, an explicit subject/scope match, or direct lexical overlap
    with the memory itself.  A declaration superseded by another
    declaration is excluded even when its status field was not updated yet.
    """
    query = "\n".join(part for part in (task, candidate) if part).strip()
    query_terms = _terms(query)
    selected: Dict[str, Declaration] = {}
    for decl in current_declarations(ensure_compiled(ws)):
        if decl.runtime_role != "constraint" or decl.status != "active":
            continue
        if decl.scope == "global":
            selected[decl.id] = decl
        if subject and decl.subject == subject:
            selected[decl.id] = decl
        if scope and decl.scope == scope:
            selected[decl.id] = decl
        if query_terms & _terms(decl.searchable_text()):
            selected[decl.id] = decl
        guard = decl.fields.get("guard")
        if isinstance(guard, dict) and _contains(
                query, _values(guard.get("when_any"))):
            selected[decl.id] = decl
    # Enforcement must not silently drop a rule because a retrieval-style
    # result limit was reached.
    return sorted(selected.values(), key=lambda d: d.id)


def applicable_boundaries(
    ws: WorkspaceInput,
    task: str,
    candidate: str = "",
    *,
    subject: Optional[str] = None,
    scope: Optional[str] = None,
) -> List[Declaration]:
    """Backward-compatible alias for :func:`applicable_constraints`."""
    return applicable_constraints(
        ws, task, candidate, subject=subject, scope=scope)


def check_compliance(
    ws: WorkspaceInput,
    task: str,
    candidate: str,
    *,
    subject: Optional[str] = None,
    scope: Optional[str] = None,
    exceptions: Optional[Sequence[str]] = None,
) -> CompliancePack:
    """Build a fail-safe CompliancePack for a proposed action or draft."""
    task_text = str(task or "").strip()
    candidate_text = str(candidate or "").strip()
    supplied_exceptions = {
        str(item).strip() for item in (exceptions or []) if str(item).strip()
    }
    compiled = ensure_compiled(ws)
    pack = CompliancePack(
        task=task_text,
        candidate=candidate_text,
        subject=str(subject or ""),
        scope=str(scope or ""),
        asserted_exceptions=sorted(supplied_exceptions),
    )
    pack.applicable_must = applicable_constraints(
        compiled, task_text, candidate_text, subject=subject, scope=scope)

    combined = "\n".join(part for part in (task_text, candidate_text) if part)
    for decl in pack.applicable_must:
        ref = _ref(decl)
        declared_exceptions = set(_values(decl.fields.get("exceptions")))
        applied = sorted(declared_exceptions & supplied_exceptions)
        guard = decl.fields.get("guard")
        if not isinstance(guard, dict):
            if applied:
                pack.exceptions_applied.append({
                    **ref,
                    "exceptions": applied,
                    "rule": decl.claim_text,
                })
                pack.evaluated.append({
                    **ref,
                    "status": "exception_applied",
                })
                continue
            pack.unknowns.append({
                **ref,
                "reason": "constraint has no executable guard",
                "rule": decl.claim_text,
            })
            pack.evaluated.append({
                **ref,
                "status": "needs_review",
            })
            continue

        when_patterns = _values(guard.get("when_any"))
        when_matches = _contains(combined, when_patterns)
        if when_patterns and not when_matches:
            pack.evaluated.append({
                **ref,
                "status": "not_triggered",
            })
            continue

        if applied:
            pack.exceptions_applied.append({
                **ref,
                "exceptions": applied,
                "rule": decl.claim_text,
            })
            pack.evaluated.append({
                **ref,
                "status": "exception_applied",
            })
            continue

        if not (decl.has_capability("enforceable")
                and decl.has_capability("guardable")):
            pack.unknowns.append({
                **ref,
                "reason": (
                    f"memory type '{decl.kind}' is a constraint but does not "
                    "declare enforceable + guardable capabilities"),
                "rule": decl.claim_text,
            })
            pack.evaluated.append({
                **ref,
                "status": "needs_review",
            })
            continue

        invalid_regex = []
        for field_name in ("deny_regex", "require_regex"):
            for pattern in _values(guard.get(field_name)):
                try:
                    re.compile(pattern)
                except re.error as exc:
                    invalid_regex.append(f"{field_name}={pattern!r}: {exc}")
        if invalid_regex:
            pack.unknowns.append({
                **ref,
                "reason": "invalid guard regex: " + "; ".join(invalid_regex),
                "rule": decl.claim_text,
            })
            pack.evaluated.append({
                **ref,
                "status": "needs_review",
            })
            continue

        deny_matches = _contains(candidate_text, _values(guard.get("deny_any")))
        deny_regex_matches = _regex_matches(
            candidate_text, _values(guard.get("deny_regex")))
        require_any = _values(guard.get("require_any"))
        require_any_matches = _contains(candidate_text, require_any)
        require_regex = _values(guard.get("require_regex"))
        require_regex_matches = _regex_matches(candidate_text, require_regex)
        actionable = bool(
            _values(guard.get("deny_any"))
            or _values(guard.get("deny_regex"))
            or require_any
            or require_regex
        )
        if not actionable:
            pack.unknowns.append({
                **ref,
                "reason": "guard has no deny or require condition",
                "rule": decl.claim_text,
            })
            pack.evaluated.append({
                **ref,
                "status": "needs_review",
            })
            continue

        reasons: List[str] = []
        matched: List[str] = []
        if deny_matches:
            reasons.append("candidate contains a denied phrase")
            matched.extend(deny_matches)
        if deny_regex_matches:
            reasons.append("candidate matches a denied pattern")
            matched.extend(deny_regex_matches)
        if require_any and not require_any_matches:
            reasons.append("candidate is missing a required phrase")
            matched.extend(require_any)
        if require_regex and not require_regex_matches:
            reasons.append("candidate is missing a required pattern")
            matched.extend(require_regex)

        if reasons:
            finding = {
                **ref,
                "rule": decl.claim_text,
                "reason": "; ".join(reasons),
                "matched": sorted(set(matched)),
                "file": decl.file,
                "line": decl.line,
            }
            if decl.evidence:
                finding["evidence"] = decl.evidence
            pack.violations.append(finding)
            pack.evaluated.append({
                **ref,
                "status": "violated",
            })
        else:
            pack.evaluated.append({
                **ref,
                "status": "passed",
            })

    if pack.violations:
        pack.verdict = "block"
    elif pack.unknowns:
        pack.verdict = "needs_review"
    else:
        pack.verdict = "allow"
    return pack
