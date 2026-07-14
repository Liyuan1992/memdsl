"""Experimental Phase 6 first-class explicit Edge public API.

Source remains authoritative. The review store is a workflow/audit contract,
not a compiled authority ledger, so callers must not describe these helpers as
non-bypassable authorization proof.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import uuid
from typing import Optional, Sequence, Union

from memdsl.compiler import CompiledExplicitEdge, WorkspaceInput, ensure_compiled
from memdsl.model import EDGE_LIFECYCLE_ACTIONS, Workspace
from memdsl.parser import parse_text
from memdsl.review import ReviewStore
from memdsl.view import ResolvedView, access_policy_readable, resolve_view


EDGE_CATALOG_SCHEMA = "memdsl.explicit_edges.experimental.v1"
EDGE_EXPLAIN_SCHEMA = "memdsl.explicit_edge.experimental.v1"


def build_explicit_edge_catalog(
    source: Union[WorkspaceInput, ResolvedView],
    *,
    include_inactive: bool = False,
    relation: Optional[str] = None,
) -> dict:
    """List compiled explicit Edges without reading pending review proposals."""
    compiled, view = _source_context(source)
    relation_filter = str(relation or "").strip()
    if relation_filter and compiled.workspace.registry.resolve_edge_relation(
            relation_filter) is None:
        raise ValueError(f"unknown explicit Edge relation: {relation_filter}")
    readable_nodes = {
        item.id
        for item in view.authoritative
        if view.enforcement_active or not item.access_policy
    }
    edges = [
        edge
        for edge in compiled.explicit_edges
        if include_inactive or edge.authoritative
        if edge.source_id in readable_nodes
        if edge.target_id in readable_nodes
        if access_policy_readable(edge.access_policy, view.context)
        if not relation_filter or edge.relation == relation_filter
    ]
    return {
        "ok": True,
        "schema_version": EDGE_CATALOG_SCHEMA,
        "status": "ok",
        "source_fingerprint": compiled.source_fingerprint,
        "include_inactive": include_inactive,
        "relation": relation_filter or None,
        "total": len(edges),
        "edges": [
            _edge_payload(edge, hide_paths=view.enforcement_active)
            for edge in edges
        ],
        "relation_registry": [
            descriptor.as_dict()
            for descriptor in compiled.workspace.registry.edge_relation_descriptors()
        ],
        "boundary": (
            "Only active, resolved explicit Edges are serviceable by default. "
            "Pending proposals are never loaded. Source is the runtime authority; "
            "review/audit state is not a digest-bound authority ledger."
        ),
        "next_actions": [
            "Inspect an Edge and both endpoint declarations before relying on it."
        ],
    }


def explain_explicit_edge(
    source: Union[WorkspaceInput, ResolvedView], edge_id: str,
) -> dict:
    """Explain one stable explicit Edge id and its append-only lifecycle events."""
    compiled, _view = _source_context(source)
    catalog = build_explicit_edge_catalog(source, include_inactive=True)
    canonical = _canonical_edge_id(edge_id)
    payload_by_id = {item["id"]: item for item in catalog["edges"]}
    edge_payload = payload_by_id.get(canonical)
    if edge_payload is None:
        return {
            "ok": False,
            "schema_version": EDGE_EXPLAIN_SCHEMA,
            "status": "not_found",
            "edge_id": canonical,
            "boundary": "No Edge authority may be inferred from a missing id.",
            "next_actions": ["List explicit Edges and use an exact stable id."],
        }
    legacy_origins = [
        item.edge_id
        for item in compiled.outgoing.get(edge_payload["source_id"], ())
        if item.status == "resolved"
        if item.relation == edge_payload["relation"]
        if item.target_id == edge_payload["target_id"]
    ]
    edge_payload["origin_ids"] = [canonical] + sorted(legacy_origins)
    edge_payload["provenance"] = ["explicit_edge"] + [
        "legacy_node_relation" for _item in sorted(legacy_origins)]
    return {
        "ok": True,
        "schema_version": EDGE_EXPLAIN_SCHEMA,
        "status": "ok",
        "edge": edge_payload,
        "boundary": (
            "This is a Source-derived graph record, not non-bypassable review "
            "proof. Explicit supersedes does not replace legacy node authority in "
            "experimental Phase 6."
        ),
        "next_actions": [
            "Inspect endpoint evidence and review audit separately when provenance matters."
        ],
    }


def build_edge_transition_source(
    edge_id: str,
    action: str,
    *,
    evidence_source: str,
    evidence_quote: str,
    event_id: str = "",
    event_at: str = "",
    replacement: str = "",
) -> str:
    """Build one synthetic-safe lifecycle event proposal source string."""
    normalized_action = str(action or "").strip()
    if normalized_action not in EDGE_LIFECYCLE_ACTIONS:
        raise ValueError(
            "action must be confirm, dispute, retract, or supersede")
    canonical = _canonical_edge_id(edge_id)
    replacement_id = _canonical_edge_id(replacement) if replacement else ""
    if normalized_action == "supersede" and not replacement_id:
        raise ValueError("supersede requires a replacement Edge id")
    timestamp = event_at or _dt.datetime.now(_dt.timezone.utc).isoformat()
    event_name = str(event_id or f"event.{uuid.uuid4().hex}").strip()
    if not event_name or any(ch.isspace() for ch in event_name):
        raise ValueError("event_id must be a non-empty atom without whitespace")
    lines = [
        f"relation_edge_event {event_name} {{",
        f"  edge: {_quoted(canonical)}",
        f"  action: {normalized_action}",
        f"  event_at: {_quoted(timestamp)}",
    ]
    if replacement_id:
        lines.append(f"  replacement: {_quoted(replacement_id)}")
    lines.extend([
        "  lifecycle { status: active }",
        "  evidence {",
        f"    source: {_quoted(evidence_source)}",
        f"    quote: {_quoted(evidence_quote)}",
        "  }",
        "}",
    ])
    return "\n".join(lines) + "\n"


def propose_edge_transition(
    store: ReviewStore,
    workspace_paths: Sequence[str],
    edge_id: str,
    action: str,
    *,
    evidence_source: str,
    evidence_quote: str,
    reason: str = "",
    client: str = "",
    event_id: str = "",
    event_at: str = "",
    replacement: str = "",
) -> dict:
    """Queue an Edge lifecycle transition; never auto-approve it."""
    source = build_edge_transition_source(
        edge_id,
        action,
        evidence_source=evidence_source,
        evidence_quote=evidence_quote,
        event_id=event_id,
        event_at=event_at,
        replacement=replacement,
    )
    return store.submit(
        workspace_paths,
        source,
        reason=reason,
        client=client,
        policy=None,
        write_auto_granted=False,
    )


def confirm_edge_proposal(
    store: ReviewStore,
    proposal_id: str,
    workspace: Workspace,
    into: str,
) -> dict:
    """Human confirmation wrapper restricted to Edge or Edge-event proposals."""
    proposal = store.get(proposal_id)
    if proposal is None:
        return {"ok": False, "status": "not_found", "proposal_id": proposal_id}
    try:
        document = parse_text(proposal.source, file="<edge-confirm>")
    except Exception:
        return {"ok": False, "status": "invalid_edge_proposal", "proposal_id": proposal_id}
    if len(document.explicit_edges) + len(document.edge_events) != 1:
        return {"ok": False, "status": "not_an_edge_proposal", "proposal_id": proposal_id}
    return store.approve(
        proposal_id,
        workspace,
        into,
        force=False,
        by="human:edge-confirm",
        target_context=True,
    )


def _edge_payload(edge: CompiledExplicitEdge, *, hide_paths: bool = False) -> dict:
    return {
        "id": edge.edge_id,
        "record_id": edge.record_id,
        "declared_by": edge.declared_by_ref,
        "declared_by_id": edge.declared_by_id,
        "source": edge.source_ref,
        "source_id": edge.source_id,
        "target": edge.target_ref,
        "target_id": edge.target_id,
        "relation": edge.relation,
        "relation_stability": edge.relation_stability,
        "resolution_status": edge.status,
        "lifecycle": dict(edge.lifecycle),
        "authoritative_graph": edge.authoritative,
        "evidence": dict(edge.evidence),
        "events": [
            {
                "id": event.event_id,
                "action": event.action,
                "event_at": event.event_at,
                "replacement": event.replacement_id or event.replacement_ref or None,
                "evidence": dict(event.evidence),
            }
            for event in edge.events
        ],
        "source_location": {
            "file": os.path.basename(edge.file) if hide_paths else edge.file,
            "line": edge.line,
        },
    }


def _source_context(source):
    if isinstance(source, ResolvedView):
        if source.compiled is None:
            raise ValueError("ResolvedView is not bound to a compiled workspace")
        return source.compiled, source
    compiled = ensure_compiled(source)
    return compiled, resolve_view(compiled)


def _canonical_edge_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("edge_id is required")
    if raw.startswith("relation_edge:"):
        return raw
    if raw.startswith("explicit_edge:"):
        return "relation_edge:" + raw.split(":", 1)[1]
    return "relation_edge:" + raw


def _quoted(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)
