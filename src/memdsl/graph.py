"""Deterministic, bounded graph Trace projection for Phase 3.

Trace walks only explicit, resolved compiler edges.  It is navigation, not a
proof system: source declarations and their evidence remain authoritative.
"""

from __future__ import annotations

import base64
from collections import deque
import hashlib
import json
from typing import Dict, List, Optional, Sequence, Tuple

from memdsl.compiler import (
    RELATION_REGISTRY,
    CompiledEdge,
    WorkspaceInput,
    ensure_compiled,
)
from memdsl.model import Declaration
from memdsl.view import ResolvedView, resolve_view


TRACE_SCHEMA = "memdsl.trace.v1"
MCP_TRACE_SCHEMA = "memdsl.mcp.trace.v1"
TRACE_CONTRACT_VERSION = "memdsl.trace.phase3.v1"
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

TraceSource = WorkspaceInput


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
) -> dict:
    """Return one statelessly paged BFS Trace under node/edge/byte budgets."""
    return _build_trace(
        source,
        anchors,
        schema_version=TRACE_SCHEMA,
        direction=direction,
        relations=relations,
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
        max_bytes=max_bytes,
        cursor=cursor,
        include_provisional=include_provisional,
    )


def _build_mcp_memory_trace(
    source: TraceSource,
    anchors: Sequence[str],
    **kwargs,
) -> dict:
    return _build_trace(
        source,
        anchors,
        schema_version=MCP_TRACE_SCHEMA,
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
    relation_filter = _normalized_relations(relations)
    unknown_relations = sorted(set(relation_filter) - set(RELATION_REGISTRY))
    if unknown_relations:
        raise ValueError(
            "unknown relation filter(s): " + ", ".join(unknown_relations))

    compiled = ensure_compiled(source)
    view = resolve_view(compiled)
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
        if not declaration.access_policy
    }
    canonical_anchors = _resolve_anchors(
        compiled,
        view,
        anchors,
        include_provisional=include_provisional,
        visible_by_id=visible_by_id,
    )

    request_hash = _digest_json({
        "trace_contract": TRACE_CONTRACT_VERSION,
        "schema_version": schema_version,
        "source_fingerprint": view.context.source_fingerprint,
        "view_id": view.view_id,
        "anchors": list(canonical_anchors),
        "direction": normalized_direction,
        "relations": list(relation_filter),
        "max_depth": depth_limit,
        "include_provisional": include_provisional,
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
        return {
            "ok": True,
            "schema_version": schema_version,
            "status": "ok",
            "view": view.metadata(),
            "diagnostic_summary": view.diagnostic_summary(),
            "anchors": list(canonical_anchors),
            "direction": normalized_direction,
            "relations": list(relation_filter),
            "max_depth": depth_limit,
            "visibility": {
                "provisional_included": include_provisional,
                "quarantined_metadata_included": False,
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
                "Trace reports explicit source relations and a deterministic "
                "BFS projection. Connectivity is not proof that a natural-"
                "language conclusion is true; inspect evidence before relying "
                "on any declaration or edge."
            ),
            "next_actions": [
                "Continue next_cursor with the same anchors, direction, "
                "relations, depth, and provisional setting."
                if has_more else
                "Call memory_explain on relevant node ids before citing them."
            ],
        }

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
        if declaration.access_policy:
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
        for traversal_direction, edge, neighbor_id in _adjacent_edges(
            compiled, node_id, direction=direction):
            if edge.edge_id in seen_edges:
                continue
            if edge.status != "resolved" or edge.target_id is None:
                continue
            if relation_filter and edge.relation not in relation_filter:
                continue
            if (edge.source_id not in visible_by_id
                    or edge.target_id not in visible_by_id
                    or neighbor_id not in visible_by_id):
                continue
            seen_edges.add(edge.edge_id)
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
                "provenance": "explicit",
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
) -> List[Tuple[str, CompiledEdge, str]]:
    adjacent = []
    if direction in {"outgoing", "both"}:
        adjacent.extend(
            ("outgoing", edge, str(edge.target_id or ""))
            for edge in compiled.outgoing.get(node_id, ())
        )
    if direction in {"incoming", "both"}:
        adjacent.extend(
            ("incoming", edge, edge.source_id)
            for edge in compiled.incoming.get(node_id, ())
        )
    return sorted(adjacent, key=lambda item: (
        item[0],
        item[1].relation,
        item[2],
        item[1].edge_id,
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
