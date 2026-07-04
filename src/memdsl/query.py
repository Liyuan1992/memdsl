"""Query executor: retrieve declarations and render a layered EvidencePack.

The reference executor is deliberately simple: lowercase term overlap
plus alias resolution, with typed layering on top. It demonstrates the
*contract* (query in, MUST/SHOULD/CONTEXT/CONFLICT/MISSING out) --
production systems should plug in a real retrieval backend (BM25,
embeddings, or both) behind the same contract.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from memdsl.model import Workspace, Declaration

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


@dataclass
class EvidencePack:
    query: str
    must: List[Declaration] = field(default_factory=list)
    should: List[Declaration] = field(default_factory=list)
    context: List[ScoredDeclaration] = field(default_factory=list)
    conflicts: List[Tuple[Declaration, str]] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    resolved_subjects: List[str] = field(default_factory=list)

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
                                if "exceptions" in d.fields else ""))
        else:
            lines.append("- (no hard boundaries apply)")
        lines.append("")
        lines.append("SHOULD")
        if self.should:
            for d in self.should:
                lines.append(f"- [{d.id}] {d.claim_text}")
        else:
            lines.append("- (none)")
        lines.append("")
        lines.append("CONTEXT")
        if self.context:
            for s in self.context:
                d = s.declaration
                extra = ""
                if d.kind == "state" and "as_of" in d.fields:
                    extra = f" (as_of {d.fields['as_of']})"
                lines.append(f"- [{d.id}] {d.claim_text}{extra}")
        else:
            lines.append("- (none)")
        if self.conflicts:
            lines.append("")
            lines.append("CONFLICT")
            for d, target in self.conflicts:
                lines.append(f"- [{d.id}] conflicts_with [{target}]")
        if self.missing:
            lines.append("")
            lines.append("MISSING")
            for m in self.missing:
                lines.append(f"- {m}")
        return "\n".join(lines)

    def render_json(self) -> str:
        def decl(d: Declaration) -> dict:
            return {"id": d.id, "claim": d.claim_text, "force": d.force,
                    "scope": d.scope, "status": d.status,
                    "file": d.file, "line": d.line}
        return json.dumps({
            "query": self.query,
            "resolved_subjects": self.resolved_subjects,
            "must": [decl(d) for d in self.must],
            "should": [decl(d) for d in self.should],
            "context": [dict(decl(s.declaration), score=round(s.score, 3))
                        for s in self.context],
            "conflicts": [{"id": d.id, "conflicts_with": t}
                          for d, t in self.conflicts],
            "missing": self.missing,
        }, indent=2, ensure_ascii=False)


def _score(decl: Declaration, query_terms: List[str],
           subject_hits: List[str]) -> ScoredDeclaration:
    hay = decl.searchable_text()
    hay_terms = set(_terms(hay))
    matched = [t for t in set(query_terms) if t in hay_terms]
    score = float(len(matched))
    if decl.subject and decl.subject in subject_hits:
        score += 2.0
        matched.append(f"subject:{decl.subject}")
    if score > 0 and str(decl.fields.get("confidence", "")) == "high":
        score += 0.25
    return ScoredDeclaration(decl, score, matched)


def build_evidence_pack(
    ws: Workspace,
    query: str,
    kinds: Optional[List[str]] = None,
    subject: Optional[str] = None,
    limit: int = 8,
) -> EvidencePack:
    """Run a query against the workspace and build a layered EvidencePack."""
    pack = EvidencePack(query=query)
    query_terms = _terms(query)

    # alias resolution: map query words/phrases to entity symbols
    amap = ws.alias_map()
    subject_hits: List[str] = []
    lowered = query.lower()
    for alias, symbols in amap.items():
        if alias in lowered:
            subject_hits.extend(symbols)
    if subject:
        subject_hits.append(subject)
    pack.resolved_subjects = sorted(set(subject_hits))

    superseded = ws.superseded_ids()
    candidates = [
        d for d in ws.active()
        if d.kind != "entity"
        and d.id not in superseded and d.name not in superseded
        and (kinds is None or d.kind in kinds)
        and (subject is None or d.subject == subject)
    ]

    scored = [_score(d, query_terms, subject_hits) for d in candidates]
    hits = sorted([s for s in scored if s.score > 0],
                  key=lambda s: -s.score)[:limit]
    hit_ids = {s.declaration.id for s in hits}
    hit_subjects = {s.declaration.subject for s in hits if s.declaration.subject}
    hit_scopes = {s.declaration.scope for s in hits if s.declaration.scope}

    # MUST: hard boundaries that matched, or that share subject/scope
    # with the matched declarations, or that are global.
    for d in ws.active():
        if d.kind != "boundary" or d.force not in (None, "hard"):
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

    # SHOULD: strong preferences and active principles among the hits
    for s in hits:
        d = s.declaration
        if d.id in must_ids:
            continue
        if (d.kind == "preference" and d.force == "strong") or d.kind == "principle":
            pack.should.append(d)

    should_ids = {d.id for d in pack.should}

    # CONTEXT: everything else that matched. `open_issue` never enters
    # CONTEXT -- unresolved questions are gaps, not facts (SPEC §7 rule 3);
    # they surface under MISSING below.
    for s in hits:
        d = s.declaration
        if d.id in must_ids or d.id in should_ids:
            continue
        if d.kind == "open_issue":
            continue
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
    if not hits:
        pack.missing.append(f"no declarations matched query terms: {query_terms}")
    if subject and not any(d.subject == subject for d in selected):
        pack.missing.append(f"no declarations found for subject '{subject}'")
    for s in scored:
        if s.declaration.kind == "open_issue" and s.score > 0:
            pack.missing.append(
                f"open issue [{s.declaration.id}]: {s.declaration.claim_text}")

    return pack


def explain(ws: Workspace, decl_id: str) -> str:
    """Render one declaration with its relations and evidence."""
    d = ws.by_id(decl_id)
    if d is None:
        return f"declaration '{decl_id}' not found"
    lines = [
        f"{d.id}",
        f"  file:    {d.file}:{d.line}",
        f"  module:  {d.module or '(none)'}",
        f"  status:  {d.status}",
    ]
    if d.subject:
        lines.append(f"  subject: {d.subject}")
    if d.force:
        lines.append(f"  force:   {d.force}")
    if d.scope:
        lines.append(f"  scope:   {d.scope}")
    if d.claim_text:
        lines.append(f"  claim:   {d.claim_text}")
    rels = d.relations()
    if rels:
        lines.append("  relations:")
        for rel, targets in rels.items():
            for t in targets:
                lines.append(f"    {rel} -> {t}")
    # reverse relations
    reverse = []
    for other in ws.declarations:
        if other.id == d.id:
            continue
        for rel, targets in other.relations().items():
            for t in targets:
                if t in (d.id, d.name):
                    reverse.append(f"    {other.id} --{rel}--> this")
    if reverse:
        lines.append("  referenced by:")
        lines.extend(reverse)
    ev = d.evidence
    if ev:
        lines.append("  evidence:")
        for k, v in ev.items():
            lines.append(f"    {k}: {v}")
    return "\n".join(lines)
