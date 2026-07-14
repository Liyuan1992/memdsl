"""Query executor: retrieve declarations and render a layered EvidencePack.

The reference executor uses a deterministic lexical inverted candidate index
plus alias resolution, with typed layering on top. It demonstrates the
*contract* (query in, MUST/SHOULD/CONTEXT/PROVISIONAL/CONFLICT/MISSING out) --
production systems should plug in a real retrieval backend (BM25,
embeddings, or both) behind the same contract.
"""

from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from memdsl.authority import current_declarations
from memdsl.compiler import WorkspaceInput, ensure_compiled
from memdsl.lexical import query_terms
from memdsl.model import Declaration
from memdsl.view import resolve_view

EVIDENCE_PACK_SCHEMA = "memdsl.evidence_pack.v1"

def _terms(text: str) -> List[str]:
    return query_terms(text)


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


def _score(
    decl: Declaration,
    query_terms: List[str],
    subject_hits: List[str],
    *,
    subject_routable: bool = True,
) -> ScoredDeclaration:
    hay = decl.searchable_text()
    hay_terms = set(_terms(hay))
    # Preserve query order while de-duplicating terms.  Iterating a set here
    # made the serialized matched_terms order depend on Python's hash seed.
    matched = [t for t in dict.fromkeys(query_terms) if t in hay_terms]
    score = float(len(matched))
    if subject_routable and decl.subject and decl.subject in subject_hits:
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
    for phrase, targets in compiled.dialect_aliases.items():
        existing = set(amap.get(phrase, ()))
        if existing and existing != set(targets):
            continue
        amap.setdefault(phrase, []).extend(targets)
    for phrase in list(amap):
        amap[phrase] = sorted(set(amap[phrase]))
    return amap


def build_evidence_pack(
    ws: WorkspaceInput,
    query: str,
    kinds: Optional[List[str]] = None,
    subject: Optional[str] = None,
    limit: int = 8,
    types: Optional[List[str]] = None,
) -> EvidencePack:
    """Run an indexed query and build a v0.6-compatible EvidencePack."""
    return _build_evidence_pack(
        ws,
        query,
        kinds=kinds,
        subject=subject,
        limit=limit,
        types=types,
        candidate_mode="indexed",
    )


def _build_evidence_pack_legacy(
    ws: WorkspaceInput,
    query: str,
    kinds: Optional[List[str]] = None,
    subject: Optional[str] = None,
    limit: int = 8,
    types: Optional[List[str]] = None,
) -> EvidencePack:
    """Phase 3 differential oracle using the pre-index full scoring scan."""
    return _build_evidence_pack(
        ws,
        query,
        kinds=kinds,
        subject=subject,
        limit=limit,
        types=types,
        candidate_mode="legacy",
    )


def _build_evidence_pack(
    ws: WorkspaceInput,
    query: str,
    *,
    kinds: Optional[List[str]],
    subject: Optional[str],
    limit: int,
    types: Optional[List[str]],
    candidate_mode: str,
) -> EvidencePack:
    """Shared EvidencePack semantics over indexed or legacy candidates."""
    compiled = ensure_compiled(ws)
    current = current_declarations(compiled)
    current_objects = {id(item) for item in current}
    view = resolve_view(compiled)
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
        declaration for declaration in compiled.searchable_declarations
        if id(declaration) in current_objects
    ]
    candidates = [
        d for d in pool
        if (type_filter is None or d.kind in type_filter)
        and (
            subject is None
            or (
                d.subject == subject
                and compiled.subject_is_routable(d)
            )
        )
    ]

    indexed_pool = _indexed_candidate_pool(
        compiled, current_objects, query_terms, subject_hits)
    score_pool = pool if candidate_mode == "legacy" else indexed_pool
    all_scored = [
        _score(
            d,
            query_terms,
            subject_hits,
            subject_routable=compiled.subject_is_routable(d),
        )
        for d in score_pool
    ]
    all_positive = [item for item in all_scored if item.score > 0]
    candidate_objects = {id(item) for item in candidates}
    scored = [
        item for item in all_scored
        if id(item.declaration) in candidate_objects
    ]
    matched = [s for s in scored if s.score > 0]

    # Authority lanes must be ranked and limited independently.  Otherwise a
    # high-scoring candidate can consume the shared result budget, displacing
    # an active hit and indirectly changing MUST/SHOULD/CONTEXT/CONFLICT.
    # Provisional memory remains bounded, but never competes with active
    # authority for its result slots.
    result_limit = max(0, limit)
    active_matches = sorted(
        (s for s in matched if s.declaration.status == "active"),
        key=_scored_sort_key,
    )
    provisional_matches = sorted(
        (s for s in matched if s.declaration.status != "active"),
        key=_scored_sort_key,
    )
    active_hits = active_matches[:result_limit]
    provisional_hits = provisional_matches[:result_limit]
    pack.provisional.extend(provisional_hits)
    # MISSING is an authoritative lane too.  Provisional matches may be shown
    # as leads, but they cannot suppress an active-memory gap.
    has_active_hits = bool(active_hits)

    # Filters must fail loud: score what they excluded so a miss can say
    # "the memory exists, your filter hid it" instead of a silent no-match.
    excluded_matches: List[ScoredDeclaration] = []
    if len(candidates) != len(pool):
        excluded_matches = sorted(
            [item for item in all_positive
             if id(item.declaration) not in candidate_objects],
            key=_scored_sort_key)
    # Provisional matches are informative only: they must not fan out through
    # a shared subject or scope and thereby activate an authoritative MUST.
    hit_ids = {s.declaration.id for s in active_hits}
    hit_subjects = {
        s.declaration.subject
        for s in active_hits
        if s.declaration.subject
        if compiled.subject_is_routable(s.declaration)
    }
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
            or (
                compiled.subject_is_routable(d)
                and d.subject in hit_subjects
            )
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

    if has_active_hits:
        vocabulary_suggestions = []
        retry_queries = []
        suggestions_truncated = False
    else:
        vocabulary_suggestions, retry_queries, suggestions_truncated = (
            _vocabulary_suggestions(
                compiled,
                view.authoritative,
                query_terms,
                query,
            )
        )
    dialect_candidate = _dialect_candidate(
        compiled, vocabulary_suggestions) if not has_active_hits else None
    indexes_used = [
        "legacy_scan" if candidate_mode == "legacy" else "lexical_terms",
        "active_aliases",
    ]
    if subject_hits:
        indexes_used.append("subject")
    if type_filter is not None:
        indexes_used.append("type_filter")
    if subject is not None:
        indexes_used.append("subject_filter")
    pack.trace = {
        "view_id": view.view_id,
        "source_fingerprint": compiled.source_fingerprint,
        "indexes_used": indexes_used,
        "query_terms": query_terms,
        "matched_aliases": {alias: sorted(set(symbols))
                            for alias, symbols in amap.items()
                            if alias in lowered},
        "filters": {
            "types": list(type_filter) if type_filter is not None else None,
            "subject": subject,
        },
        "candidate_pool_total": len(all_positive),
        "candidate_pool_after_filters": len(matched),
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
        "quarantined_matches": [],
        "vocabulary_suggestions": vocabulary_suggestions,
        "retry_queries": retry_queries,
        "truncated": bool(
            len(active_matches) > result_limit
            or len(provisional_matches) > result_limit
            or len(excluded_matches) > 5
            or suggestions_truncated
        ),
    }
    if dialect_candidate is not None:
        pack.trace["dialect_candidate"] = dialect_candidate

    return pack


def _indexed_candidate_pool(
    compiled,
    current_objects: set,
    terms: Sequence[str],
    subject_hits: Sequence[str],
) -> List[Declaration]:
    selected: Dict[int, Declaration] = {}
    for term in dict.fromkeys(terms):
        for declaration in compiled.lexical_terms.get(term, ()):
            if id(declaration) in current_objects:
                selected[id(declaration)] = declaration
    for subject in dict.fromkeys(subject_hits):
        for declaration in compiled.by_subject.get(subject, ()):
            if (id(declaration) in current_objects
                    and declaration.runtime_role != "symbol"
                    and declaration.has_capability("searchable")
                    and compiled.subject_is_routable(declaration)):
                selected[id(declaration)] = declaration
    return [
        declaration for declaration in compiled.searchable_declarations
        if id(declaration) in selected
    ]


def _vocabulary_suggestions(
    compiled,
    authoritative: Sequence[Declaration],
    terms: Sequence[str],
    query: str,
    *,
    limit: int = 5,
) -> Tuple[List[dict], List[str], bool]:
    """Suggest active public workspace vocabulary without changing routing."""
    vocabulary: Dict[Tuple[str, str], set] = {}
    authoritative_objects = {id(item) for item in authoritative}
    public = [
        declaration for declaration in authoritative
        if not declaration.access_policy
    ]
    for declaration in public:
        if declaration.runtime_role == "symbol":
            symbol = declaration.name
            phrases = [(symbol.rsplit(".", 1)[-1].lower(), "symbol")]
            canonical = declaration.fields.get("canonical_name")
            if isinstance(canonical, str) and canonical.strip():
                phrases.append((canonical.strip().lower(), "canonical_name"))
            aliases = declaration.fields.get("aliases")
            if isinstance(aliases, list):
                phrases.extend(
                    (str(alias).strip().lower(), "alias")
                    for alias in aliases if str(alias).strip()
                )
            for phrase, category in phrases:
                vocabulary.setdefault((phrase, category), set()).add(symbol)
        if declaration.module:
            vocabulary.setdefault(
                (str(declaration.module).lower(), "module"), set())
        vocabulary.setdefault((declaration.kind.lower(), "type"), set())

    # Candidate or excluded symbols cannot enter an authoritative suggestion
    # merely because their term appears in a compiler index.
    active_symbols = {
        declaration.name
        for declaration in compiled.declarations
        if id(declaration) in authoritative_objects
        if declaration.runtime_role == "symbol"
        if not declaration.access_policy
    }
    ranked = []
    category_priority = {
        "symbol": 0,
        "alias": 1,
        "canonical_name": 2,
        "dialect": 3,
        "module": 4,
        "type": 5,
    }
    for phrase, symbols in compiled.dialect_targets.items():
        vocabulary.setdefault((phrase, "dialect"), set()).update(symbols)
    for query_term in dict.fromkeys(terms):
        for (phrase, category), raw_symbols in vocabulary.items():
            if query_term == phrase or not phrase:
                continue
            score, reason = _suggestion_score(query_term, phrase)
            if score < 0.72:
                continue
            symbols = tuple(sorted(set(raw_symbols) & active_symbols))
            ranked.append((
                -score,
                query_term,
                phrase,
                category_priority.get(category, 99),
                category,
                symbols,
                reason,
            ))
    ranked.sort()

    suggestions = []
    seen_terms = set()
    for (
        _negative_score,
        query_term,
        phrase,
        _category_priority,
        category,
        symbols,
        reason,
    ) in ranked:
        if query_term in seen_terms:
            continue
        seen_terms.add(query_term)
        suggestions.append({
            "query_term": query_term,
            "suggestion": phrase,
            "category": category,
            "reason": reason,
            "authoritative": True,
            "ambiguous": len(symbols) > 1,
            "symbols": list(symbols),
        })
        if len(suggestions) >= limit:
            break

    retry_queries = []
    replacements = {
        item["query_term"]: item["suggestion"]
        for item in suggestions
        if not item["ambiguous"]
    }
    for term, replacement in replacements.items():
        retry = " ".join(
            replacement if item == term else item for item in terms)
        if retry and retry.lower() != str(query or "").strip().lower():
            retry_queries.append(retry)
    retry_queries = list(dict.fromkeys(retry_queries))[:limit]
    return suggestions, retry_queries, len(ranked) > len(suggestions)


def _dialect_candidate(compiled, suggestions: Sequence[dict]) -> Optional[dict]:
    """Return an advisory, non-writing proposal template for one safe retry."""
    if len(compiled.dialect_mapping_types) != 1:
        return None
    suggestion = next((
        item for item in suggestions
        if not item.get("ambiguous") and len(item.get("symbols", ())) == 1
    ), None)
    if suggestion is None:
        return None
    phrase = str(suggestion["query_term"])
    target = str(suggestion["symbols"][0])
    slug = "_".join(query_terms(phrase)) or "phrase"
    digest = hashlib.sha256(
        f"{phrase}\0{target}".encode("utf-8")).hexdigest()[:10]
    return {
        "status": "proposal_required",
        "mapping_type": compiled.dialect_mapping_types[0],
        "phrase": phrase,
        "target": target,
        "name_hint": f"dialect.{slug}.{digest}",
        "fields": {
            "target": target,
            "phrases": [phrase],
            "polarity": "positive",
            "lifecycle": {"status": "active"},
        },
        "requires_evidence": True,
        "requires_review": True,
        "boundary": (
            "This is an advisory template only. The query did not write Source; "
            "a host must add trusted evidence and submit it through the existing "
            "proposal/review/approval lane. Pending mappings never route."
        ),
    }


def _suggestion_score(query_term: str, phrase: str) -> Tuple[float, str]:
    if (len(query_term) >= 3 and len(phrase) >= 3
            and (query_term.startswith(phrase) or phrase.startswith(query_term))):
        return 0.95, "prefix"
    return SequenceMatcher(None, query_term, phrase).ratio(), "edit_distance"


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
    scopes = sorted({d.scope for d in active if d.scope})
    modules = sorted({d.module for d in active if d.module})
    result = {
        "subjects": subjects[:limit],
        "scopes": scopes[:limit],
        "modules": modules[:limit],
        "types": dict(sorted(types.items())),
    }
    # Preserve ordinary v1 payload snapshots while making every actual
    # truncation visible.  Catalog v1 always carries total/truncated fields;
    # this additive v1 compatibility path emits them only when the old 50-item
    # slice would otherwise hide vocabulary.
    for name, values in (
        ("subjects", subjects),
        ("scopes", scopes),
        ("modules", modules),
    ):
        if len(values) > limit:
            result[f"{name}_total"] = len(values)
            result[f"{name}_truncated"] = True
    return result


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
    resolution = compiled.resolve_reference(decl_id)
    if resolution.status == "ambiguous":
        return f"declaration '{decl_id}' is ambiguous and cannot be resolved safely"
    d = resolution.declaration
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
