"""Deterministic, bounded graph Trace projection for Phase 3.

Trace walks only explicit, resolved compiler edges.  It is navigation, not a
proof system: source declarations and their evidence remain authoritative.
"""

from __future__ import annotations

import base64
from collections import deque
import hashlib
import json
from typing import Dict, List, Optional, Sequence, Tuple, Union

from memdsl.compiler import (
    RELATION_REGISTRY,
    CompiledEdge,
    WorkspaceInput,
    ensure_compiled,
)
from memdsl.model import Declaration
from memdsl.view import (
    ResolvedView,
    access_policy_readable,
    diagnostic_summary,
    resolve_view,
)


TRACE_SCHEMA = "memdsl.trace.v1"
MCP_TRACE_SCHEMA = "memdsl.mcp.trace.v1"
TRACE_SCHEMA_V2 = "memdsl.trace.v2"
MCP_TRACE_SCHEMA_V2 = "memdsl.mcp.trace.v2"
TRACE_SCHEMA_EXPLICIT_EDGE = "memdsl.trace.explicit-edge.experimental.v1"
MCP_TRACE_SCHEMA_EXPLICIT_EDGE = "memdsl.mcp.trace.explicit-edge.experimental.v1"
TRACE_CONTRACT_VERSION = "memdsl.trace.phase3.v1"
EXPLICIT_EDGE_TRACE_CONTRACT_VERSION = "memdsl.trace.phase6.experimental.v1"
TRACE_CURSOR_VERSION = 1
TRACE_DEFAULT_MAX_DEPTH = 3
TRACE_DEFAULT_MAX_NODES = 20
TRACE_DEFAULT_MAX_EDGES = 40
TRACE_DEFAULT_MAX_BYTES = 8192
TRACE_MIN_MAX_BYTES = 1024
TRACE_MAX_MAX_BYTES = 1024 * 1024
TRACE_MAX_NODES = 1000
TRACE_MAX_EDGES = 2000
TRACE_MAX_DEPTH = 100000

TraceSource = Union[WorkspaceInput, ResolvedView]


class TraceCursorError(ValueError):
    """A Trace cursor is invalid, stale, or bound to another request."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class TraceAnchorError(ValueError):
    """An anchor cannot be safely resolved in the requested Trace view."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def trace_memory(
    source: TraceSource,
    anchors: Sequence[str],
    *,
    direction: str = "outgoing",
    relations: Optional[Sequence[str]] = None,
    max_depth: int = TRACE_DEFAULT_MAX_DEPTH,
    max_nodes: int = TRACE_DEFAULT_MAX_NODES,
    max_edges: int = TRACE_DEFAULT_MAX_EDGES,
    max_bytes: int = TRACE_DEFAULT_MAX_BYTES,
    cursor: Optional[str] = None,
    include_provisional: bool = False,
    include_quarantined_metadata: bool = False,
) -> dict:
    """Return one statelessly paged BFS Trace under node/edge/byte budgets."""
    schema_version = (
        TRACE_SCHEMA_V2
        if isinstance(source, ResolvedView) and source.enforcement_active
        else TRACE_SCHEMA
    )
    return _build_trace(
        source,
        anchors,
        schema_version=schema_version,
        direction=direction,
        relations=relations,
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
        max_bytes=max_bytes,
        cursor=cursor,
        include_provisional=include_provisional,
        include_quarantined_metadata=include_quarantined_metadata,
    )


def _build_mcp_memory_trace(
    source: TraceSource,
    anchors: Sequence[str],
    **kwargs,
) -> dict:
    schema_version = (
        MCP_TRACE_SCHEMA_V2
        if isinstance(source, ResolvedView) and source.enforcement_active
        else MCP_TRACE_SCHEMA
    )
    return _build_trace(
        source,
        anchors,
        schema_version=schema_version,
        **kwargs,
    )


def _build_trace(
    source: TraceSource,
    anchors: Sequence[str],
    *,
    schema_version: str,
    direction: str,
    relations: Optional[Sequence[str]],
    max_depth: int,
    max_nodes: int,
    max_edges: int,
    max_bytes: int,
    cursor: Optional[str],
    include_provisional: bool,
    include_quarantined_metadata: bool = False,
) -> dict:
    normalized_direction = str(direction or "").strip().lower()
    if normalized_direction not in {"outgoing", "incoming", "both"}:
        raise ValueError("direction must be outgoing, incoming, or both")
    depth_limit = _validated_int(
        max_depth, "max_depth", minimum=0, maximum=TRACE_MAX_DEPTH)
    node_limit = _validated_int(
        max_nodes, "max_nodes", minimum=1, maximum=TRACE_MAX_NODES)
    edge_limit = _validated_int(
        max_edges, "max_edges", minimum=1, maximum=TRACE_MAX_EDGES)
    byte_limit = _validated_int(
        max_bytes,
        "max_bytes",
        minimum=TRACE_MIN_MAX_BYTES,
        maximum=TRACE_MAX_MAX_BYTES,
    )
    if not isinstance(include_provisional, bool):
        raise ValueError("include_provisional must be a boolean")
    if not isinstance(include_quarantined_metadata, bool):
        raise ValueError("include_quarantined_metadata must be a boolean")
    relation_filter = _normalized_relations(relations)
    if isinstance(source, ResolvedView):
        view = source
        if view.compiled is None:
            raise ValueError("ResolvedView is not bound to a compiled workspace")
        compiled = view.compiled
    else:
        compiled = ensure_compiled(source)
        view = resolve_view(compiled)
    if compiled.workspace.explicit_edges_enabled:
        schema_version = (
            MCP_TRACE_SCHEMA_EXPLICIT_EDGE
            if schema_version.startswith("memdsl.mcp.")
            else TRACE_SCHEMA_EXPLICIT_EDGE
        )
    known_relations = set(RELATION_REGISTRY)
    if compiled.workspace.explicit_edges_enabled:
        known_relations.update(compiled.workspace.registry.edge_relation_names())
    unknown_relations = sorted(set(relation_filter) - known_relations)
    if unknown_relations:
        raise ValueError(
            "unknown relation filter(s): " + ", ".join(unknown_relations))
    enforced = view.enforcement_active
    if cursor:
        # Cursor revision identity wins over anchor resolution.  If Source or
        # View changed enough to remove an anchor, pagination must still fail
        # as stale rather than looking like an unrelated first-page miss.
        try:
            _decode_cursor(
                str(cursor),
                source_fingerprint=view.context.source_fingerprint,
                view_id=view.view_id,
                request_hash="",
            )
        except TraceCursorError as exc:
            if exc.code != "cursor_mismatch":
                raise

    authoritative_objects = {id(item) for item in view.authoritative}
    provisional_objects = {id(item) for item in view.provisional}
    serviceable_objects = set(authoritative_objects)
    if include_provisional:
        serviceable_objects.update(provisional_objects)
    visible_by_id = {
        declaration_id: declaration
        for declaration_id, declaration in compiled.resolved_by_id.items()
        if id(declaration) in serviceable_objects
        if enforced or not declaration.access_policy
    }
    readable_explicit_edge_ids = {
        edge.edge_id
        for edge in compiled.authoritative_explicit_edges
        if edge.source_id in visible_by_id
        if edge.target_id in visible_by_id
        if access_policy_readable(edge.access_policy, view.context)
    }
    safe_diagnostics = list(view.visible_diagnostics())

    def safe_view_envelope() -> dict:
        envelope = view.envelope(include_diagnostics=False)
        envelope["diagnostic_summary"] = {
            **diagnostic_summary(safe_diagnostics),
            "blocking": sum(
                1 for item in safe_diagnostics
                if item in view.blocking_diagnostics),
            "enforced": sum(
                1 for item in safe_diagnostics
                if item.enforcement_scope != "report"),
        }
        return envelope
    if view.blocked:
        result = {
            "ok": False,
            "schema_version": schema_version,
            "status": "compiler_error",
            "view": safe_view_envelope(),
            "available_nodes": 0,
            "available_edges": 0,
            "returned_nodes": 0,
            "returned_edges": 0,
            "nodes": [],
            "tree_edges": [],
            "back_edges": [],
            "cross_edges": [],
            "truncated": False,
            "next_cursor": None,
            "completeness": "blocked",
            "next_actions": [
                "Run lint and repair blocking identity/source diagnostics."
            ],
        }
        if _json_bytes(result) > byte_limit:
            raise ValueError(
                "max_bytes is too small for the Trace error envelope")
        return result
    canonical_anchors = _resolve_anchors(
        compiled,
        view,
        anchors,
        include_provisional=include_provisional,
        visible_by_id=visible_by_id,
    )

    request_hash = _digest_json({
        "trace_contract": (
            EXPLICIT_EDGE_TRACE_CONTRACT_VERSION
            if compiled.workspace.explicit_edges_enabled
            else TRACE_CONTRACT_VERSION),
        "schema_version": schema_version,
        "source_fingerprint": view.context.source_fingerprint,
        "view_id": view.view_id,
        "anchors": list(canonical_anchors),
        "direction": normalized_direction,
        "relations": list(relation_filter),
        "max_depth": depth_limit,
        "include_provisional": include_provisional,
        "include_quarantined_metadata": include_quarantined_metadata,
    })
    node_offset = 0
    edge_offset = 0
    if cursor:
        node_offset, edge_offset = _decode_cursor(
            str(cursor),
            source_fingerprint=view.context.source_fingerprint,
            view_id=view.view_id,
            request_hash=request_hash,
        )

    nodes, edges = _bfs_trace(
        compiled,
        visible_by_id,
        canonical_anchors,
        authoritative_objects=authoritative_objects,
        direction=normalized_direction,
        relations=relation_filter,
        max_depth=depth_limit,
        readable_explicit_edge_ids=readable_explicit_edge_ids,
    )
    if node_offset > len(nodes) or edge_offset > len(edges):
        raise TraceCursorError(
            "invalid_cursor", "cursor offset exceeds the available Trace")

    def payload_for(
        selected_nodes: Sequence[dict],
        selected_edges: Sequence[dict],
    ) -> dict:
        next_node_offset = node_offset + len(selected_nodes)
        next_edge_offset = edge_offset + len(selected_edges)
        has_more = (
            next_node_offset < len(nodes) or next_edge_offset < len(edges))
        next_cursor = (
            _encode_cursor(
                source_fingerprint=view.context.source_fingerprint,
                view_id=view.view_id,
                request_hash=request_hash,
                node_offset=next_node_offset,
                edge_offset=next_edge_offset,
            )
            if has_more else None
        )
        tree_edges = [
            item for item in selected_edges
            if item["classification"] == "tree"]
        back_edges = [
            item for item in selected_edges
            if item["classification"] == "back"]
        cross_edges = [
            item for item in selected_edges
            if item["classification"] == "cross"]
        payload = {
            "ok": True,
            "schema_version": schema_version,
            "status": "ok",
            "view": (
                safe_view_envelope()
                if enforced else view.metadata()),
            "diagnostic_summary": (
                safe_view_envelope()["diagnostic_summary"]
                if enforced else diagnostic_summary(safe_diagnostics)),
            "anchors": list(canonical_anchors),
            "direction": normalized_direction,
            "relations": list(relation_filter),
            "max_depth": depth_limit,
            "visibility": {
                "provisional_included": include_provisional,
                "quarantined_metadata_included": bool(
                    enforced and include_quarantined_metadata),
                "quarantined_nodes": len(view.quarantined),
                "access_policy": (
                    "restricted declarations are omitted without ids or counts"
                ),
            },
            "available_nodes": len(nodes),
            "available_edges": len(edges),
            "returned_nodes": len(selected_nodes),
            "returned_edges": len(selected_edges),
            "nodes": list(selected_nodes),
            "tree_edges": tree_edges,
            "back_edges": back_edges,
            "cross_edges": cross_edges,
            "truncated": has_more,
            "next_cursor": next_cursor,
            "completeness": "partial" if has_more else "complete",
            "boundary": (
                (
                    "Trace reports legacy node relations plus active, resolved "
                    "first-class explicit Edges and a deterministic BFS projection. "
                    "Connectivity is not proof. Source is runtime authority; review "
                    "and audit state are not compiled non-bypassable authorization."
                )
                if compiled.workspace.explicit_edges_enabled else
                (
                    "Trace reports explicit source relations and a deterministic "
                    "BFS projection. Connectivity is not proof that a natural-"
                    "language conclusion is true; inspect evidence before relying "
                    "on any declaration or edge."
                )
            ),
            "next_actions": [
                "Continue next_cursor with the same anchors, direction, "
                "relations, depth, and provisional setting."
                if has_more else
                "Call memory_explain on relevant node ids before citing them."
            ],
        }
        if enforced and include_quarantined_metadata:
            payload["quarantined"] = [
                {"id": item.id, "reasons": list(view.reasons_for(item))}
                for item in view.quarantined[:20]
            ]
            payload["quarantined_truncated"] = len(view.quarantined) > 20
        return payload

    selected_nodes: List[dict] = []
    selected_edges: List[dict] = []
    empty = payload_for(selected_nodes, selected_edges)
    if _json_bytes(empty) > byte_limit:
        raise ValueError(
            "max_bytes is too small for the Trace envelope; increase the budget")

    full_page_nodes = list(nodes[node_offset: node_offset + node_limit])
    full_page_edges = list(edges[edge_offset: edge_offset + edge_limit])
    if (node_offset + len(full_page_nodes) == len(nodes)
            and edge_offset + len(full_page_edges) == len(edges)):
        complete_page = payload_for(full_page_nodes, full_page_edges)
        if _json_bytes(complete_page) <= byte_limit:
            return complete_page

    for item in full_page_nodes:
        prospective = selected_nodes + [item]
        if _json_bytes(payload_for(prospective, selected_edges)) > byte_limit:
            break
        selected_nodes.append(item)
    for item in full_page_edges:
        prospective = selected_edges + [item]
        if _json_bytes(payload_for(selected_nodes, prospective)) > byte_limit:
            break
        selected_edges.append(item)

    result = payload_for(selected_nodes, selected_edges)
    if _json_bytes(result) > byte_limit:
        raise AssertionError("Trace byte budget accounting drifted")
    return result


def render_trace_text(payload: dict) -> str:
    """Render a compact human-readable Trace page."""
    lines = [
        "# memory trace",
        (
            f"anchors={','.join(payload.get('anchors', []))} "
            f"direction={payload.get('direction')} "
            f"nodes={payload.get('returned_nodes', 0)}/"
            f"{payload.get('available_nodes', 0)} "
            f"edges={payload.get('returned_edges', 0)}/"
            f"{payload.get('available_edges', 0)} "
            f"completeness={payload.get('completeness')}"
        ),
    ]
    for node in payload.get("nodes", []):
        lines.append(
            f"- node [{node['id']}] depth={node['depth']} lane={node['lane']}")
    for key in ("tree_edges", "back_edges", "cross_edges"):
        for edge in payload.get(key, []):
            lines.append(
                f"- {edge['classification']} [{edge['source_id']}] "
                f"--{edge['relation']}--> [{edge['target_id']}]"
            )
    if payload.get("truncated"):
        lines.append("- more Trace items are available; continue next_cursor")
    lines.append("- Trace connectivity is not proof; inspect source evidence.")
    return "\n".join(lines)


def _resolve_anchors(
    compiled,
    view: ResolvedView,
    anchors: Sequence[str],
    *,
    include_provisional: bool,
    visible_by_id: Dict[str, Declaration],
) -> Tuple[str, ...]:
    raw_anchors = [anchors] if isinstance(anchors, str) else list(anchors or ())
    normalized = []
    authoritative_objects = {id(item) for item in view.authoritative}
    provisional_objects = {id(item) for item in view.provisional}
    for raw in raw_anchors:
        reference = str(raw or "").strip()
        if not reference:
            raise TraceAnchorError(
                "anchor_required", "at least one non-empty anchor is required")
        resolution = compiled.resolve_reference(reference)
        if resolution.status == "ambiguous":
            raise TraceAnchorError(
                "anchor_ambiguous", "anchor does not resolve to one declaration")
        declaration = resolution.declaration
        if declaration is None:
            raise TraceAnchorError(
                "anchor_not_found", "anchor was not found in the current source")
        if view.enforcement_active:
            if any(id(item) == id(declaration) for item in view.unauthorized):
                raise TraceAnchorError(
                    "unauthorized",
                    "anchor is not readable in this Trace context")
            lane = view.lane_for(declaration)
            if lane == "quarantined":
                raise TraceAnchorError(
                    "anchor_quarantined",
                    "anchor is quarantined in this ResolvedView")
            if lane == "excluded":
                raise TraceAnchorError(
                    "anchor_excluded", "anchor is excluded from this ResolvedView")
        elif declaration.access_policy:
            raise TraceAnchorError(
                "unauthorized", "anchor is not readable in this Trace context")
        if id(declaration) in provisional_objects and not include_provisional:
            raise TraceAnchorError(
                "anchor_not_serviceable",
                "provisional anchor requires include_provisional=true",
            )
        if (id(declaration) not in authoritative_objects
                and id(declaration) not in provisional_objects):
            raise TraceAnchorError(
                "anchor_not_serviceable", "anchor is excluded from this View")
        if declaration.id not in visible_by_id:
            raise TraceAnchorError(
                "anchor_not_serviceable", "anchor cannot be resolved safely")
        normalized.append(declaration.id)
    if not normalized:
        raise TraceAnchorError(
            "anchor_required", "at least one non-empty anchor is required")
    return tuple(sorted(set(normalized)))


def _bfs_trace(
    compiled,
    visible_by_id: Dict[str, Declaration],
    anchors: Sequence[str],
    *,
    authoritative_objects: set,
    direction: str,
    relations: Tuple[str, ...],
    max_depth: int,
    readable_explicit_edge_ids: set,
) -> Tuple[List[dict], List[dict]]:
    relation_filter = set(relations)
    depth = {anchor: 0 for anchor in anchors}
    parent = {anchor: None for anchor in anchors}
    parent_edge = {anchor: None for anchor in anchors}
    queue = deque(anchors)
    node_ids = list(anchors)
    edges: List[dict] = []
    seen_edges = set()

    while queue:
        node_id = queue.popleft()
        if depth[node_id] >= max_depth:
            continue
        for traversal_direction, edge_group, neighbor_id in _adjacent_edges(
            compiled,
            node_id,
            direction=direction,
            readable_explicit_edge_ids=readable_explicit_edge_ids,
        ):
            resolved_group = [
                edge for edge in edge_group
                if edge.status == "resolved" and edge.target_id is not None
            ]
            if not resolved_group:
                continue
            edge = next(
                (item for item in resolved_group
                 if getattr(item, "origin", "") == "explicit_edge"),
                resolved_group[0],
            )
            triple = (edge.source_id, edge.relation, edge.target_id)
            seen_key = (
                triple
                if compiled.workspace.explicit_edges_enabled
                else edge.edge_id
            )
            if seen_key in seen_edges:
                continue
            if relation_filter and edge.relation not in relation_filter:
                continue
            if (edge.source_id not in visible_by_id
                    or edge.target_id not in visible_by_id
                    or neighbor_id not in visible_by_id):
                continue
            seen_edges.add(seen_key)
            if neighbor_id not in depth:
                depth[neighbor_id] = depth[node_id] + 1
                parent[neighbor_id] = node_id
                parent_edge[neighbor_id] = edge.edge_id
                queue.append(neighbor_id)
                node_ids.append(neighbor_id)
                classification = "tree"
            elif _is_ancestor(neighbor_id, node_id, parent):
                classification = "back"
            else:
                classification = "cross"
            edges.append({
                "sequence": len(edges),
                "edge_id": edge.edge_id,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "relation": edge.relation,
                "traversal_direction": traversal_direction,
                "classification": classification,
                "cycle": classification == "back",
                "provenance": (
                    getattr(edge, "origin", "legacy_node_relation")
                    if compiled.workspace.explicit_edges_enabled else "explicit"),
            })
            if compiled.workspace.explicit_edges_enabled:
                origins = sorted(
                    resolved_group,
                    key=lambda item: (
                        getattr(item, "origin", "legacy_node_relation"),
                        item.edge_id,
                    ),
                )
                edges[-1].update({
                    "origin_ids": [item.edge_id for item in origins],
                    "provenance": [
                        getattr(item, "origin", "legacy_node_relation")
                        for item in origins
                    ],
                })
            if getattr(edge, "origin", "") == "explicit_edge":
                edges[-1].update({
                    "explicit_edge_id": edge.edge_id,
                    "relation_stability": edge.relation_stability,
                    "lifecycle": dict(edge.lifecycle),
                    "evidence": dict(edge.evidence),
                })

    nodes = []
    for sequence, node_id in enumerate(node_ids):
        declaration = visible_by_id[node_id]
        nodes.append({
            "sequence": sequence,
            "id": declaration.id,
            "type": declaration.kind,
            "runtime_role": declaration.runtime_role,
            "status": declaration.status,
            "lane": (
                "authoritative"
                if id(declaration) in authoritative_objects else "provisional"
            ),
            "module": declaration.module,
            "subject": declaration.subject,
            "depth": depth[node_id],
            "parent_id": parent[node_id],
            "parent_edge_id": parent_edge[node_id],
        })
    return nodes, edges


def _adjacent_edges(
    compiled,
    node_id: str,
    *,
    direction: str,
    readable_explicit_edge_ids: set,
) -> list:
    adjacent = []
    if direction in {"outgoing", "both"}:
        adjacent.extend(
            ("outgoing", edge, str(edge.target_id or ""))
            for edge in compiled.outgoing.get(node_id, ())
        )
        adjacent.extend(
            ("outgoing", edge, str(edge.target_id or ""))
            for edge in compiled.explicit_outgoing.get(node_id, ())
            if edge.edge_id in readable_explicit_edge_ids
        )
    if direction in {"incoming", "both"}:
        adjacent.extend(
            ("incoming", edge, edge.source_id)
            for edge in compiled.incoming.get(node_id, ())
        )
        adjacent.extend(
            ("incoming", edge, str(edge.source_id or ""))
            for edge in compiled.explicit_incoming.get(node_id, ())
            if edge.edge_id in readable_explicit_edge_ids
        )
    if not compiled.workspace.explicit_edges_enabled:
        return sorted(
            [
                (traversal_direction, (edge,), neighbor_id)
                for traversal_direction, edge, neighbor_id in adjacent
            ],
            key=lambda item: (
                item[0], item[1][0].relation, item[2], item[1][0].edge_id),
        )
    grouped = {}
    for traversal_direction, edge, neighbor_id in adjacent:
        key = (
            traversal_direction,
            edge.source_id,
            edge.relation,
            edge.target_id or edge.target_ref,
            neighbor_id,
        )
        grouped.setdefault(key, []).append(edge)
    coalesced = [
        (key[0], tuple(values), key[4])
        for key, values in grouped.items()
    ]
    return sorted(coalesced, key=lambda item: (
        item[0],
        item[1][0].relation,
        item[2],
        tuple(sorted(edge.edge_id for edge in item[1])),
    ))


def _is_ancestor(candidate: str, node_id: str, parent: Dict[str, Optional[str]]) -> bool:
    current = node_id
    while current is not None:
        if current == candidate:
            return True
        current = parent.get(current)
    return False


def _normalized_relations(relations: Optional[Sequence[str]]) -> Tuple[str, ...]:
    if relations is None:
        return ()
    raw = [relations] if isinstance(relations, str) else list(relations)
    normalized = set()
    for value in raw:
        relation = str(value or "").strip()
        if not relation:
            raise ValueError("relations must contain non-empty strings")
        normalized.add(relation)
    return tuple(sorted(normalized))


def _encode_cursor(
    *,
    source_fingerprint: str,
    view_id: str,
    request_hash: str,
    node_offset: int,
    edge_offset: int,
) -> str:
    payload = {
        "v": TRACE_CURSOR_VERSION,
        "s": source_fingerprint,
        "w": view_id,
        "r": request_hash,
        "n": node_offset,
        "e": edge_offset,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    checksum = hashlib.sha256(
        (TRACE_CONTRACT_VERSION + ":" + body).encode("ascii")
    ).hexdigest()[:24]
    return body + "." + checksum


def _decode_cursor(
    token: str,
    *,
    source_fingerprint: str,
    view_id: str,
    request_hash: str,
) -> Tuple[int, int]:
    try:
        body, checksum = token.split(".", 1)
        expected = hashlib.sha256(
            (TRACE_CONTRACT_VERSION + ":" + body).encode("ascii")
        ).hexdigest()[:24]
        if checksum != expected:
            raise ValueError("checksum")
        padding = "=" * (-len(body) % 4)
        raw = base64.urlsafe_b64decode((body + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise TraceCursorError(
            "invalid_cursor", "cursor is malformed or has invalid integrity") from exc
    if not isinstance(payload, dict) or payload.get("v") != TRACE_CURSOR_VERSION:
        raise TraceCursorError("invalid_cursor", "cursor version is unsupported")
    if payload.get("s") != source_fingerprint or payload.get("w") != view_id:
        raise TraceCursorError(
            "cursor_stale", "source fingerprint or view id changed")
    if payload.get("r") != request_hash:
        raise TraceCursorError(
            "cursor_mismatch", "cursor Trace request identity changed")
    node_offset = payload.get("n")
    edge_offset = payload.get("e")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (node_offset, edge_offset)
    ):
        raise TraceCursorError("invalid_cursor", "cursor offsets are invalid")
    return node_offset, edge_offset


def _validated_int(value, name: str, *, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _json_bytes(payload: object) -> int:
    return len(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8"))


def _digest_json(payload: object) -> str:
    return hashlib.sha256(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
