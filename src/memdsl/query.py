"""Query executor: retrieve declarations and render a layered EvidencePack.

The reference executor is deliberately simple: lowercase term overlap
plus alias resolution, with typed layering on top. It demonstrates the
*contract* (query in, MUST/SHOULD/CONTEXT/PROVISIONAL/CONFLICT/MISSING out) --
production systems should plug in a real retrieval backend (BM25,
embeddings, or both) behind the same contract.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from memdsl.authority import current_declarations
from memdsl.compiler import WorkspaceInput, ensure_compiled
from memdsl.model import Declaration

EVIDENCE_PACK_SCHEMA = "memdsl.evidence_pack.v1"

_WORD_RE = re.compile(r"[a-z0-9_]+")

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "of", "to",
    "in", "on", "at", "for", "and", "or", "not", "no", "my", "me", "i",
    "it", "its", "this", "that", "these", "those", "do", "does", "did",
    "how", "what", "when", "where", "which", "who", "why", "should",
    "would", "could", "can", "will", "with", "about", "into", "over",
    "please", "help", "going", "keep", "get", "make", "your", "you", "we",
    "our", "us", "if", "so", "as", "by", "from", "up", "out", "any",
}


def _terms(text: str) -> List[str]:
    return [t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS]


@dataclass
class ScoredDeclaration:
    declaration: Declaration
    score: float
    matched_terms: List[str] = field(default_factory=list)


def _render_lifecycle(d: Declaration) -> str:
    """Make a declaration's authority level unambiguous in text output."""
    lifecycle = json.dumps(
        d.lifecycle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        f" [status={d.status}; runtime_role={d.runtime_role}; "
        f"lifecycle={lifecycle}]"
    )


@dataclass
class EvidencePack:
    query: str
    must: List[Declaration] = field(default_factory=list)
    should: List[Declaration] = field(default_factory=list)
    context: List[ScoredDeclaration] = field(default_factory=list)
    conflicts: List[Tuple[Declaration, str]] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    resolved_subjects: List[str] = field(default_factory=list)
    # Diagnostic retrieval trace (additive to memdsl.evidence_pack.v1): how
    # the query was interpreted and what the filters excluded, so an agent
    # that misses can correct course instead of concluding the memory is
    # absent.
    trace: Dict = field(default_factory=dict)
    # Additive to memdsl.evidence_pack.v1 and deliberately appended after the
    # original positional fields. Declarations that remain serviceable but
    # are not active (normally lifecycle.status=candidate) are visible here
    # without acquiring normative or factual authority.
    provisional: List[ScoredDeclaration] = field(default_factory=list)

    # ---- rendering ----

    def render_text(self) -> str:
        lines: List[str] = []
        if self.resolved_subjects:
            lines.append(f"# resolved subjects: {', '.join(self.resolved_subjects)}")
        lines.append("MUST")
        if self.must:
            for d in self.must:
                lines.append(f"- [{d.id}] {d.claim_text}"
                             + (f" (exceptions: {d.fields['exceptions']})"
                                if "exceptions" in d.fields else "")
                             + _render_lifecycle(d))
        else:
            lines.append("- (no constraints apply)")
        lines.append("")
        lines.append("SHOULD")
        if self.should:
            for d in self.should:
                lines.append(f"- [{d.id}] {d.claim_text}{_render_lifecycle(d)}")
        else:
            lines.append("- (none)")
        lines.append("")
        lines.append("CONTEXT")
        if self.context:
            for s in self.context:
                d = s.declaration
                extra = ""
                if d.has_capability("temporal") and d.lifecycle.get("as_of"):
                    extra = f" (as_of {d.lifecycle['as_of']})"
                lines.append(
                    f"- [{d.id}] {d.claim_text}{extra}{_render_lifecycle(d)}")
        else:
            lines.append("- (none)")
        lines.append("")
        lines.append("PROVISIONAL")
        if self.provisional:
            for s in self.provisional:
                d = s.declaration
                lines.append(
                    f"- [{d.id}] {d.claim_text}{_render_lifecycle(d)}")
        else:
            lines.append("- (none)")
        if self.conflicts:
            lines.append("")
            lines.append("CONFLICT")
            for d, target in self.conflicts:
                lines.append(
                    f"- [{d.id}] conflicts_with [{target}]"
                    f"{_render_lifecycle(d)}")
        if self.missing:
            lines.append("")
            lines.append("MISSING")
            for m in self.missing:
                lines.append(f"- {m}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        """Plain-dict form of the pack: the stable contract for JSON and MCP.

        Declarations keep their type label and evidence so downstream
        consumers can tell a verified, evidence-backed item from a scored
        candidate instead of flattening both into one relevance list.
        """
        def decl(d: Declaration) -> dict:
            out = {"id": d.id, "type": d.kind, "kind": d.kind,
                   "runtime_role": d.runtime_role,
                   "capabilities": sorted(d.capabilities),
                   "claim": d.claim_text,
                   "force": d.force, "scope": d.scope, "subject": d.subject,
                   "confidence": d.confidence, "lifecycle": d.lifecycle,
                   "access_policy": d.access_policy,
                   "status": d.status, "file": d.file, "line": d.line}
            if d.evidence:
                out["evidence"] = d.evidence
            return out
        return {
            "schema_version": EVIDENCE_PACK_SCHEMA,
            "query": self.query,
            "resolved_subjects": self.resolved_subjects,
            "must": [decl(d) for d in self.must],
            "should": [decl(d) for d in self.should],
            "context": [dict(
                            decl(s.declaration),
                            score=round(s.score, 3),
                            matched_terms=list(s.matched_terms),
                        )
                        for s in self.context],
            "provisional": [dict(
                                decl(s.declaration),
                                score=round(s.score, 3),
                                matched_terms=list(s.matched_terms),
                            )
                            for s in self.provisional],
            "conflicts": [{"id": d.id, "conflicts_with": t,
                           "runtime_role": d.runtime_role,
                           "status": d.status, "lifecycle": d.lifecycle}
                          for d, t in self.conflicts],
            "missing": self.missing,
            "search_trace": self.trace,
        }

    def render_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)


def _score(decl: Declaration, query_terms: List[str],
           subject_hits: List[str]) -> ScoredDeclaration:
    hay = decl.searchable_text()
    hay_terms = set(_terms(hay))
    # Preserve query order while de-duplicating terms.  Iterating a set here
    # made the serialized matched_terms order depend on Python's hash seed.
    matched = [t for t in dict.fromkeys(query_terms) if t in hay_terms]
    score = float(len(matched))
    if decl.subject and decl.subject in subject_hits:
        score += 2.0
        matched.append(f"subject:{decl.subject}")
    if score > 0 and str(decl.confidence or "") == "high":
        score += 0.25
    return ScoredDeclaration(decl, score, matched)


def _scored_sort_key(scored: ScoredDeclaration) -> tuple:
    """Stable ranking key shared by active and provisional retrieval."""
    declaration = scored.declaration
    return (
        -scored.score,
        declaration.id,
        declaration.file,
        declaration.line,
    )


def _active_alias_map(ws: WorkspaceInput) -> Dict[str, List[str]]:
    """Aliases trusted for query routing and MUST relevance.

    Candidate symbols remain visible in the memory map, but must not redirect
    a query or activate constraints before human confirmation. Keep this
    filter local so the older Workspace.alias_map() API retains its behavior.
    """
    compiled = ensure_compiled(ws)
    current_objects = {id(item) for item in current_declarations(compiled)}
    amap: Dict[str, List[str]] = {}
    for alias, declarations in compiled.aliases.items():
        for decl in declarations:
            if id(decl) not in current_objects or decl.status != "active":
                continue
            amap.setdefault(alias, []).append(decl.name)
    return amap


def build_evidence_pack(
    ws: WorkspaceInput,
    query: str,
    kinds: Optional[List[str]] = None,
    subject: Optional[str] = None,
    limit: int = 8,
    types: Optional[List[str]] = None,
) -> EvidencePack:
    """Run a query against the workspace and build a layered EvidencePack."""
    compiled = ensure_compiled(ws)
    current = current_declarations(compiled)
    pack = EvidencePack(query=query)
    query_terms = _terms(query)

    # alias resolution: map query words/phrases to canonical symbols
    amap = _active_alias_map(compiled)
    subject_hits: List[str] = []
    lowered = query.lower()
    for alias, symbols in amap.items():
        if alias in lowered:
            subject_hits.extend(symbols)
    if subject:
        subject_hits.append(subject)
    pack.resolved_subjects = sorted(set(subject_hits))

    type_filter = types if types is not None else kinds
    pool = [
        d for d in current
        if d.runtime_role != "symbol"
        and d.has_capability("searchable")
    ]
    candidates = [
        d for d in pool
        if (type_filter is None or d.kind in type_filter)
        and (subject is None or d.subject == subject)
    ]

    scored = [_score(d, query_terms, subject_hits) for d in candidates]
    matched = [s for s in scored if s.score > 0]

    # Authority lanes must be ranked and limited independently.  Otherwise a
    # high-scoring candidate can consume the shared result budget, displacing
    # an active hit and indirectly changing MUST/SHOULD/CONTEXT/CONFLICT.
    # Provisional memory remains bounded, but never competes with active
    # authority for its result slots.
    result_limit = max(0, limit)
    active_hits = sorted(
        (s for s in matched if s.declaration.status == "active"),
        key=_scored_sort_key,
    )[:result_limit]
    provisional_hits = sorted(
        (s for s in matched if s.declaration.status != "active"),
        key=_scored_sort_key,
    )[:result_limit]
    pack.provisional.extend(provisional_hits)
    # MISSING is an authoritative lane too.  Provisional matches may be shown
    # as leads, but they cannot suppress an active-memory gap.
    has_active_hits = bool(active_hits)

    # Filters must fail loud: score what they excluded so a miss can say
    # "the memory exists, your filter hid it" instead of a silent no-match.
    excluded_matches: List[ScoredDeclaration] = []
    if len(candidates) != len(pool):
        candidate_ids = {d.id for d in candidates}
        excluded_matches = sorted(
            [s for s in (_score(d, query_terms, subject_hits)
                         for d in pool if d.id not in candidate_ids)
             if s.score > 0],
            key=_scored_sort_key)
    # Provisional matches are informative only: they must not fan out through
    # a shared subject or scope and thereby activate an authoritative MUST.
    hit_ids = {s.declaration.id for s in active_hits}
    hit_subjects = {
        s.declaration.subject for s in active_hits if s.declaration.subject}
    hit_scopes = {
        s.declaration.scope for s in active_hits if s.declaration.scope}

    # MUST: constraints that matched, share subject/scope with hits, or are
    # global. Domain types reach this layer through runtime_role.
    for d in current:
        if d.runtime_role != "constraint" or d.status != "active":
            continue
        relevant = (
            d.id in hit_ids
            or d.scope in hit_scopes
            or d.subject in hit_subjects
            or d.scope == "global"
        )
        if relevant:
            pack.must.append(d)

    must_ids = {d.id for d in pack.must}

    # SHOULD: any domain type compiled to the guidance runtime role
    for s in active_hits:
        d = s.declaration
        if d.id in must_ids:
            continue
        if d.runtime_role == "guidance":
            pack.should.append(d)

    should_ids = {d.id for d in pack.should}

    # CONTEXT: assertions among the remaining hits. Questions never become
    # facts; custom types reach MISSING through the question runtime role.
    for s in active_hits:
        d = s.declaration
        if d.id in must_ids or d.id in should_ids:
            continue
        if d.runtime_role == "assertion":
            pack.context.append(s)

    # CONFLICT: declared conflicts among selected declarations
    selected = pack.must + pack.should + [s.declaration for s in pack.context]
    selected_ids = {d.id for d in selected} | {d.name for d in selected}
    for d in selected:
        for target in d.relations().get("conflicts_with", []):
            bare = target.split(":", 1)[-1]
            if target in selected_ids or bare in selected_ids:
                pack.conflicts.append((d, target))

    # MISSING: explicit gaps
    if not has_active_hits:
        pack.missing.append(
            f"no active declarations matched query terms: {query_terms}")
    excluded_active_matches = [
        item for item in excluded_matches
        if item.declaration.status == "active"
    ]
    if excluded_active_matches and not has_active_hits:
        pack.missing.append(
            f"{len(excluded_active_matches)} active declaration(s) matched "
            "the query but "
            "were excluded by type/subject filters")
    if subject and not any(d.subject == subject for d in selected):
        pack.missing.append(
            f"no active declarations found for subject '{subject}'")
    for s in scored:
        if (s.declaration.status == "active"
                and s.declaration.runtime_role == "question"
                and s.score > 0):
            d = s.declaration
            pack.missing.append(
                f"question [{d.id}]: {d.claim_text}{_render_lifecycle(d)}")

    pack.trace = {
        "query_terms": query_terms,
        "matched_aliases": {alias: sorted(set(symbols))
                            for alias, symbols in amap.items()
                            if alias in lowered},
        "filters": {
            "types": list(type_filter) if type_filter is not None else None,
            "subject": subject,
        },
        "candidates_considered": len(candidates),
        "hits": len(active_hits) + len(provisional_hits),
        "excluded_by_filters_total": len(excluded_matches),
        "excluded_by_filters": [
            {"id": s.declaration.id,
             "type": s.declaration.kind,
             "subject": s.declaration.subject,
             "matched_terms": sorted(s.matched_terms)}
            for s in excluded_matches[:5]
        ],
    }

    return pack


def workspace_vocabulary(ws: WorkspaceInput, limit: int = 50) -> dict:
    """The words a workspace speaks: subjects, aliases, scopes, types, modules.

    A no-match answer is only useful if the agent learns which vocabulary to
    re-ask in; this is that vocabulary, computed from serviceable declarations.
    """
    active = current_declarations(ensure_compiled(ws))
    subjects = []
    for d in active:
        if d.runtime_role != "symbol":
            continue
        entry: dict = {"symbol": d.name}
        canonical = d.fields.get("canonical_name")
        if isinstance(canonical, str) and canonical:
            entry["canonical_name"] = canonical
        aliases = d.fields.get("aliases")
        if isinstance(aliases, list) and aliases:
            entry["aliases"] = [str(a) for a in aliases]
        subjects.append(entry)
    types: Dict[str, int] = {}
    for d in active:
        types[d.kind] = types.get(d.kind, 0) + 1
    return {
        "subjects": subjects[:limit],
        "scopes": sorted({d.scope for d in active if d.scope})[:limit],
        "modules": sorted({d.module for d in active if d.module})[:limit],
        "types": dict(sorted(types.items())),
    }


def build_memory_map(ws: WorkspaceInput, claim_chars: int = 120) -> dict:
    """Compact per-module index of every serviceable declaration.

    Designed to sit in an agent's context from turn one -- the agent knows
    what memory exists before it queries, instead of discovering the
    workspace only through retrieval misses. Candidate status is explicit so
    provisional memory cannot masquerade as active authority. Claims are
    truncated and carry no evidence: the map is for navigation, not citation.
    """
    compiled = ensure_compiled(ws)
    modules: Dict[str, List[dict]] = {}
    total = 0
    for d in current_declarations(compiled):
        entry: dict = {"id": d.id, "type": d.kind,
                       "runtime_role": d.runtime_role,
                       "status": d.status,
                       "lifecycle": d.lifecycle}
        if d.subject:
            entry["subject"] = d.subject
        if d.scope:
            entry["scope"] = d.scope
        if d.runtime_role == "symbol":
            parts = []
            canonical = d.fields.get("canonical_name")
            if isinstance(canonical, str) and canonical:
                parts.append(f'"{canonical}"')
            aliases = d.fields.get("aliases")
            if isinstance(aliases, list) and aliases:
                parts.append("aliases: " + ", ".join(str(a) for a in aliases))
            entry["summary"] = "; ".join(parts)
        else:
            entry["summary"] = _clip(d.claim_text, claim_chars)
        modules.setdefault(d.module or "", []).append(entry)
        total += 1
    return {
        "declarations": total,
        "modules": [
            {"module": name or "(none)", "declarations": len(items),
             "items": items}
            for name, items in sorted(modules.items())
        ],
        "vocabulary": workspace_vocabulary(compiled),
    }


def render_memory_map_text(map_data: dict) -> str:
    """Render a memory map as a compact text index for context residence."""
    lines = [
        f"# memory map: {map_data['declarations']} declaration(s) "
        f"in {len(map_data['modules'])} module(s)"
    ]
    for mod in map_data["modules"]:
        lines.append("")
        lines.append(f"## module {mod['module']}")
        for item in mod["items"]:
            status = item.get("status", "active")
            lifecycle = item.get("lifecycle", {"status": status})
            lifecycle_text = json.dumps(
                lifecycle, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"))
            head = (
                f"- [{item['id']}] {item['runtime_role']} "
                f"[status={status}; lifecycle={lifecycle_text}]"
            )
            details = []
            if item.get("subject"):
                details.append(f"subject {item['subject']}")
            if item.get("scope"):
                details.append(f"scope {item['scope']}")
            if details:
                head += " (" + ", ".join(details) + ")"
            if item.get("summary"):
                head += f": {item['summary']}"
            lines.append(head)
    vocab = map_data.get("vocabulary", {})
    if vocab:
        lines.append("")
        lines.append("## vocabulary")
        subject_bits = []
        for s in vocab.get("subjects", []):
            bit = s["symbol"]
            names = [s.get("canonical_name", "")] + list(s.get("aliases", []))
            names = [n for n in dict.fromkeys(names) if n]
            if names:
                bit += " (aka " + ", ".join(names) + ")"
            subject_bits.append(bit)
        if subject_bits:
            lines.append("subjects: " + "; ".join(subject_bits))
        if vocab.get("scopes"):
            lines.append("scopes: " + ", ".join(vocab["scopes"]))
        if vocab.get("types"):
            lines.append("types: " + ", ".join(
                f"{name}({count})" for name, count in vocab["types"].items()))
    return "\n".join(lines)


def _clip(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def explain(ws: WorkspaceInput, decl_id: str) -> str:
    """Render one declaration with its relations and evidence."""
    compiled = ensure_compiled(ws)
    d = compiled.first_occurrence(decl_id)
    if d is None:
        return f"declaration '{decl_id}' not found"
    lines = [
        f"{d.id}",
        f"  file:    {d.file}:{d.line}",
        f"  module:  {d.module or '(none)'}",
        f"  type:    {d.kind}",
        f"  role:    {d.runtime_role}",
        f"  status:  {d.status}",
    ]
    if d.subject:
        lines.append(f"  subject: {d.subject}")
    if d.force:
        lines.append(f"  force:   {d.force}")
    if d.scope:
        lines.append(f"  scope:   {d.scope}")
    if d.confidence is not None:
        lines.append(f"  confidence: {d.confidence}")
    if d.claim_text:
        lines.append(f"  claim:   {d.claim_text}")
    rels = d.relations()
    if rels:
        lines.append("  relations:")
        for rel, targets in rels.items():
            for t in targets:
                lines.append(f"    {rel} -> {t}")
    # reverse relations
    reverse = [
        f"    {edge.source_id} --{edge.relation}--> this"
        for edge in compiled.legacy_incoming(d)
    ]
    if reverse:
        lines.append("  referenced by:")
        lines.extend(reverse)
    ev = d.evidence
    if ev:
        lines.append("  evidence:")
        for k, v in ev.items():
            lines.append(f"    {k}: {v}")
    if d.access_policy:
        lines.append("  access policy:")
        for k, v in d.access_policy.items():
            lines.append(f"    {k}: {v}")
    return "\n".join(lines)
