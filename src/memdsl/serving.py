"""Phase 5 access-filtered, quarantine-aware read envelopes.

These builders are new contracts.  Legacy/report callers continue to use the
v1 Map, EvidencePack, list, explain, and compliance payloads unchanged.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Dict, List, Optional, Sequence, Tuple

from memdsl.compliance import (
    applicable_constraints_from,
    check_compliance,
)
from memdsl.model import Declaration
from memdsl.query import build_resolved_evidence_pack
from memdsl.view import ResolvedView


QUERY_SCHEMA = "memdsl.query.v2"
MCP_QUERY_SCHEMA = "memdsl.mcp.query.v2"
LIST_SCHEMA = "memdsl.list.v2"
MCP_LIST_SCHEMA = "memdsl.mcp.list.v2"
EXPLAIN_SCHEMA = "memdsl.explain.v2"
MCP_EXPLAIN_SCHEMA = "memdsl.mcp.explain.v2"
CHECK_SCHEMA = "memdsl.check.v2"
MCP_CHECK_SCHEMA = "memdsl.mcp.check.v2"
READ_CURSOR_VERSION = 1
DEFAULT_READ_MAX_BYTES = 16384
MIN_READ_MAX_BYTES = 1024
MAX_READ_MAX_BYTES = 1024 * 1024


class ResolvedCursorError(ValueError):
    """A Phase 5 list cursor is invalid, stale, or request-mismatched."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def build_resolved_query(
    view: ResolvedView,
    query: str,
    *,
    kinds: Optional[Sequence[str]] = None,
    types: Optional[Sequence[str]] = None,
    subject: Optional[str] = None,
    limit: int = 8,
    max_bytes: int = DEFAULT_READ_MAX_BYTES,
    schema_version: str = QUERY_SCHEMA,
) -> dict:
    """Build a bounded query v2 envelope over one enforced View."""
    byte_limit = _validated_bytes(max_bytes)
    query_text = str(query or "").strip()
    if not query_text:
        return _error(
            schema_version, "invalid", "query_required", view,
            ["Provide a non-empty query."], byte_limit)
    pack = build_resolved_evidence_pack(
        view,
        query_text,
        kinds=list(kinds) if kinds else None,
        types=list(types) if types else None,
        subject=subject or None,
        limit=max(0, min(50, int(limit))),
    )
    status = pack.status
    if (
        status == "no_match"
        and subject
        and any(item.subject == subject for item in view.unauthorized)
    ):
        status = "unauthorized"
    payload = {
        "ok": status not in {"compiler_error", "unauthorized"},
        "schema_version": schema_version,
        "status": status,
        "view": view.envelope(include_diagnostics=False),
        "evidence_pack": pack.as_dict(),
        "completeness": (
            "blocked" if status in {"compiler_error", "unauthorized"}
            else "complete"),
        "truncated": bool(pack.trace.get("truncated")),
        "boundary": (
            "Only authoritative declarations can enter MUST/SHOULD/CONTEXT or "
            "compliance. Provisional and quarantined matches are fail-loud "
            "leads, not authority."
        ),
        "next_actions": _query_next_actions(status),
    }
    if status == "unauthorized":
        payload.pop("evidence_pack", None)
    return _fit_query_payload(payload, byte_limit)


def build_resolved_list(
    view: ResolvedView,
    *,
    kind: Optional[str] = None,
    memory_type: Optional[str] = None,
    subject: Optional[str] = None,
    limit: int = 100,
    max_bytes: int = DEFAULT_READ_MAX_BYTES,
    cursor: Optional[str] = None,
    include_provisional: bool = True,
    include_quarantined_metadata: bool = True,
    schema_version: str = LIST_SCHEMA,
) -> dict:
    """Build a bounded, cursor-bound declaration list v2."""
    byte_limit = _validated_bytes(max_bytes)
    page_limit = max(1, min(500, int(limit)))
    if view.blocked:
        return _error(
            schema_version, "compiler_error", "compiler_error", view,
            ["Run lint and repair the blocking identity/source diagnostics."],
            byte_limit,
        )
    requested_type = str(memory_type or kind or "").strip()
    requested_subject = str(subject or "").strip()
    source = list(view.authoritative)
    if include_provisional:
        source.extend(view.provisional)
    declarations = sorted(
        (
            item for item in source
            if not requested_type or item.kind == requested_type
            if not requested_subject or item.subject == requested_subject
        ),
        key=_declaration_sort_key,
    )
    quarantined = sorted(
        (
            item for item in view.quarantined
            if not requested_type or item.kind == requested_type
            if not requested_subject or item.subject == requested_subject
        ),
        key=_declaration_sort_key,
    )
    request_hash = _digest_json({
        "schema_version": schema_version,
        "view_id": view.view_id,
        "type": requested_type,
        "subject": requested_subject,
        "include_provisional": include_provisional,
        "include_quarantined_metadata": include_quarantined_metadata,
    })
    offset = 0
    if cursor:
        offset = _decode_cursor(
            cursor,
            source_fingerprint=view.context.source_fingerprint,
            view_id=view.view_id,
            request_hash=request_hash,
        )
        if offset > len(declarations):
            raise ResolvedCursorError(
                "invalid_cursor", "cursor offset exceeds available declarations")

    unauthorized = bool(
        requested_subject
        and any(item.subject == requested_subject for item in view.unauthorized)
        and not declarations
    )

    def payload_for(selected: Sequence[dict]) -> dict:
        next_offset = offset + len(selected)
        has_more = next_offset < len(declarations)
        if unauthorized:
            status = "unauthorized"
        elif declarations:
            status = "ok"
        elif quarantined:
            status = "quarantined"
        else:
            status = "no_match"
        payload = {
            "ok": status not in {"unauthorized"},
            "schema_version": schema_version,
            "status": status,
            "view": view.envelope(include_diagnostics=False),
            "filters": {
                "type": requested_type or None,
                "subject": requested_subject or None,
            },
            "returned_items": len(selected),
            "available_items": len(declarations),
            "items": list(selected),
            "truncated": has_more,
            "next_cursor": (
                _encode_cursor(
                    source_fingerprint=view.context.source_fingerprint,
                    view_id=view.view_id,
                    request_hash=request_hash,
                    offset=next_offset,
                ) if has_more else None
            ),
            "completeness": (
                "blocked" if unauthorized else
                "partial" if has_more else "complete"),
            "next_actions": [
                "Continue with next_cursor using the same filters and View."
                if has_more else
                "Call explain on an authoritative or provisional id."
            ],
        }
        if include_quarantined_metadata and not unauthorized:
            payload["quarantined_matches"] = [
                {"id": item.id, "reasons": list(view.reasons_for(item))}
                for item in quarantined[:20]
            ]
            payload["quarantined_matches_truncated"] = len(quarantined) > 20
        return payload

    selected = []
    for declaration in declarations[offset: offset + page_limit]:
        item = _list_item(view, declaration)
        if _json_bytes(payload_for(selected + [item])) > byte_limit:
            break
        selected.append(item)
    result = payload_for(selected)
    if _json_bytes(result) > byte_limit:
        result.pop("quarantined_matches", None)
        result.pop("quarantined_matches_truncated", None)
    if _json_bytes(result) > byte_limit:
        return _budget_limited(schema_version, view, byte_limit)
    return result


def build_resolved_explain(
    view: ResolvedView,
    reference: str,
    *,
    max_bytes: int = DEFAULT_READ_MAX_BYTES,
    schema_version: str = EXPLAIN_SCHEMA,
) -> dict:
    """Explain one safely resolved declaration without serving quarantine."""
    byte_limit = _validated_bytes(max_bytes)
    ref = str(reference or "").strip()
    if not ref:
        return _error(
            schema_version, "invalid", "id_required", view,
            ["Pass one full declaration id or unique bare name."], byte_limit)
    if view.blocked:
        return _error(
            schema_version, "compiler_error", "compiler_error", view,
            ["Repair blocking identity diagnostics before reading declarations."],
            byte_limit,
        )
    if view.compiled is None:
        raise ValueError("ResolvedView is not bound to a compiled workspace")
    resolution = view.compiled.resolve_reference(ref)
    if resolution.status == "ambiguous":
        return _error(
            schema_version, "ambiguous", "ambiguous_reference", view,
            ["Pass a unique full declaration id."], byte_limit)
    declaration = resolution.declaration
    if declaration is None:
        return _error(
            schema_version, "not_found", "not_found", view,
            ["Use Catalog, query, or list to locate a declaration."], byte_limit)
    if any(id(item) == id(declaration) for item in view.unauthorized):
        return _error(
            schema_version, "unauthorized", "unauthorized", view,
            ["Use a trusted host principal with declaration read access."],
            byte_limit,
        )
    lane = view.lane_for(declaration)
    if lane == "quarantined":
        payload = {
            "ok": False,
            "schema_version": schema_version,
            "status": "quarantined",
            "view": view.envelope(include_diagnostics=False),
            "id": declaration.id,
            "reasons": list(view.reasons_for(declaration)),
            "completeness": "blocked",
            "next_actions": [
                "Run lint, edit source, or submit a repair proposal; quarantined "
                "content is not served as authority."
            ],
        }
        return _fit_or_budget(payload, schema_version, view, byte_limit)
    if lane == "excluded":
        payload = {
            "ok": False,
            "schema_version": schema_version,
            "status": "excluded",
            "view": view.envelope(include_diagnostics=False),
            "id": declaration.id,
            "reasons": list(view.reasons_for(declaration)),
            "completeness": "complete",
            "next_actions": ["Inspect lint/source history through the repair lane."],
        }
        return _fit_or_budget(payload, schema_version, view, byte_limit)

    serviceable = {
        item.id for item in tuple(view.authoritative) + tuple(view.provisional)}
    outgoing = [
        _edge_item(edge)
        for edge in view.compiled.outgoing.get(declaration.id, ())
        if edge.status == "resolved"
        if edge.target_id in serviceable
    ]
    incoming = [
        _edge_item(edge)
        for edge in view.compiled.incoming.get(declaration.id, ())
        if edge.status == "resolved"
        if edge.source_id in serviceable
    ]
    payload = {
        "ok": True,
        "schema_version": schema_version,
        "status": "ok" if lane == "authoritative" else "provisional_only",
        "view": view.envelope(include_diagnostics=False),
        "classification": lane,
        "declaration": _declaration_payload(declaration),
        "outgoing": outgoing,
        "incoming": incoming,
        "completeness": "complete",
        "truncated": False,
        "boundary": (
            "Evidence anchors this source declaration; classification controls "
            "runtime authority and graph visibility."
        ),
    }
    if _json_bytes(payload) > byte_limit:
        payload["declaration"].pop("evidence", None)
        payload["evidence_omitted_for_budget"] = True
        payload["completeness"] = "partial"
        payload["truncated"] = True
    if _json_bytes(payload) > byte_limit:
        payload["declaration"].pop("fields", None)
    return _fit_or_budget(payload, schema_version, view, byte_limit)


def build_resolved_check(
    view: ResolvedView,
    task: str,
    candidate: str,
    *,
    subject: Optional[str] = None,
    scope: Optional[str] = None,
    exceptions: Optional[Sequence[str]] = None,
    max_bytes: int = DEFAULT_READ_MAX_BYTES,
    schema_version: str = CHECK_SCHEMA,
) -> dict:
    """Evaluate compliance without silently omitting hidden/quarantined rules."""
    byte_limit = _validated_bytes(max_bytes)
    task_text = str(task or "").strip()
    candidate_text = str(candidate or "").strip()
    if not task_text or not candidate_text:
        return _error(
            schema_version, "invalid", "task_and_candidate_required", view,
            ["Provide both task and candidate."], byte_limit)
    if view.blocked:
        return _check_blocked(
            schema_version, "compiler_error", view, byte_limit,
            "Blocking compiler diagnostics make authoritative constraint "
            "evaluation incomplete.")

    unauthorized_constraints = applicable_constraints_from(
        [
            item for item in view.unauthorized
            if item.runtime_role == "constraint" and item.status == "active"
        ],
        task_text,
        candidate_text,
        subject=subject,
        scope=scope,
    )
    if unauthorized_constraints:
        return _check_blocked(
            schema_version, "unauthorized", view, byte_limit,
            "At least one potentially applicable constraint is not readable in "
            "this trusted-principal context; no id or count is disclosed.")

    quarantined_constraints = applicable_constraints_from(
        [
            item for item in view.quarantined
            if item.runtime_role == "constraint" and item.status == "active"
        ],
        task_text,
        candidate_text,
        subject=subject,
        scope=scope,
    )
    if quarantined_constraints:
        payload = _check_blocked(
            schema_version, "quarantined", view, byte_limit,
            "At least one potentially applicable constraint is quarantined; "
            "NEEDS_REVIEW is mandatory until source is repaired.")
        payload["quarantined_constraints"] = [
            {"id": item.id, "reasons": list(view.reasons_for(item))}
            for item in quarantined_constraints
        ]
        return _fit_or_budget(payload, schema_version, view, byte_limit)

    pack = check_compliance(
        view,
        task_text,
        candidate_text,
        subject=subject,
        scope=scope,
        exceptions=exceptions,
    )
    pack_payload = pack.as_dict()
    _sanitize_paths(pack_payload)
    pack_payload["candidate_sha256"] = hashlib.sha256(
        candidate_text.encode("utf-8")).hexdigest()
    pack_payload["candidate_chars"] = len(candidate_text)
    pack_payload.pop("candidate", None)
    payload = {
        "ok": True,
        "schema_version": schema_version,
        "status": pack.verdict,
        "view": view.envelope(include_diagnostics=False),
        "compliance_pack": pack_payload,
        "completeness": "complete",
        "truncated": False,
        "boundary": (
            "BLOCK forbids the candidate. NEEDS_REVIEW is not approval. "
            "Quarantined or unreadable applicable constraints never degrade to ALLOW."
        ),
    }
    if _json_bytes(payload) > byte_limit:
        _strip_evidence(pack_payload)
        payload["truncated"] = True
        payload["completeness"] = "partial"
    return _fit_or_budget(payload, schema_version, view, byte_limit)


def _check_blocked(
    schema_version: str,
    status: str,
    view: ResolvedView,
    byte_limit: int,
    reason: str,
) -> dict:
    payload = {
        "ok": False,
        "schema_version": schema_version,
        "status": status,
        "view": view.envelope(include_diagnostics=False),
        "verdict": "needs_review",
        "completeness": "blocked",
        "reason": reason,
        "next_actions": [
            "Repair source or obtain a trusted authorized evaluation, then rerun check."
        ],
    }
    return _fit_or_budget(payload, schema_version, view, byte_limit)


def _query_next_actions(status: str) -> List[str]:
    if status == "compiler_error":
        return ["Run lint and repair blocking source diagnostics."]
    if status == "unauthorized":
        return ["Use a trusted host principal; do not infer hidden memory content."]
    if status == "quarantined":
        return ["Inspect authorized quarantine metadata and repair source."]
    if status == "provisional_only":
        return ["Treat matches as unconfirmed leads; they carry no authority."]
    if status == "no_match":
        return ["Retry with authorized workspace vocabulary or Catalog filters."]
    return ["Explain authoritative ids before citing their evidence."]


def _fit_query_payload(payload: dict, byte_limit: int) -> dict:
    if _json_bytes(payload) <= byte_limit:
        return payload
    pack = payload.get("evidence_pack", {})
    _strip_evidence(pack)
    payload["truncated"] = True
    payload["completeness"] = "partial"
    if _json_bytes(payload) <= byte_limit:
        return payload
    for lane in ("provisional", "context", "should"):
        items = pack.get(lane)
        while isinstance(items, list) and items and _json_bytes(payload) > byte_limit:
            items.pop()
    if _json_bytes(payload) <= byte_limit:
        return payload
    schema_version = payload.get("schema_version", QUERY_SCHEMA)
    view = payload.get("view", {})
    return {
        "ok": False,
        "schema_version": schema_version,
        "status": "budget_limited",
        "view": view,
        "completeness": "incomplete",
        "truncated": True,
        "next_actions": [
            "Increase max_bytes or narrow query filters; no apparently complete "
            "authority result is returned."
        ],
    }


def _strip_evidence(payload: dict) -> None:
    for lane in ("must", "should", "context", "provisional"):
        for item in payload.get(lane, []) if isinstance(payload, dict) else []:
            if isinstance(item, dict):
                item.pop("evidence", None)
    for lane in ("applicable_must", "applicable_constraints"):
        for item in payload.get(lane, []) if isinstance(payload, dict) else []:
            if isinstance(item, dict):
                item.pop("evidence", None)


def _sanitize_paths(payload: dict) -> None:
    for value in payload.values():
        if isinstance(value, dict):
            if "file" in value and isinstance(value["file"], str):
                value["file"] = os.path.basename(value["file"])
            _sanitize_paths(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    if "file" in item and isinstance(item["file"], str):
                        item["file"] = os.path.basename(item["file"])
                    _sanitize_paths(item)


def _list_item(view: ResolvedView, declaration: Declaration) -> dict:
    return {
        "id": declaration.id,
        "type": declaration.kind,
        "runtime_role": declaration.runtime_role,
        "subject": declaration.subject,
        "scope": declaration.scope,
        "status": declaration.status,
        "classification": view.lane_for(declaration),
        "claim": _clip(declaration.claim_text, 200),
        "has_evidence": bool(declaration.evidence),
    }


def _declaration_payload(declaration: Declaration) -> dict:
    payload = {
        "id": declaration.id,
        "type": declaration.kind,
        "runtime_role": declaration.runtime_role,
        "capabilities": sorted(declaration.capabilities),
        "name": declaration.name,
        "module": declaration.module,
        "status": declaration.status,
        "subject": declaration.subject,
        "scope": declaration.scope,
        "confidence": declaration.confidence,
        "lifecycle": declaration.lifecycle,
        "claim": declaration.claim_text,
        "relations": declaration.relations(),
        "fields": {
            key: value for key, value in declaration.fields.items()
            if key not in {"evidence", "access_policy", "access"}
        },
    }
    if declaration.evidence:
        payload["evidence"] = declaration.evidence
    return payload


def _edge_item(edge) -> dict:
    return {
        "edge_id": edge.edge_id,
        "source_id": edge.source_id,
        "relation": edge.relation,
        "target_id": edge.target_id,
        "provenance": "explicit",
    }


def _error(
    schema_version: str,
    status: str,
    error: str,
    view: ResolvedView,
    next_actions: Sequence[str],
    byte_limit: int,
) -> dict:
    payload = {
        "ok": False,
        "schema_version": schema_version,
        "status": status,
        "error": error,
        "view": view.envelope(include_diagnostics=False),
        "completeness": "blocked" if status != "not_found" else "complete",
        "next_actions": list(next_actions),
    }
    return _fit_or_budget(payload, schema_version, view, byte_limit)


def _budget_limited(
    schema_version: str,
    view: ResolvedView,
    byte_limit: int,
) -> dict:
    payload = {
        "ok": False,
        "schema_version": schema_version,
        "status": "budget_limited",
        "view": {
            "schema_version": "memdsl.resolved_view.v1",
            "status": view.status,
            "view": view.metadata(),
        },
        "completeness": "incomplete",
        "truncated": True,
        "next_actions": ["Increase max_bytes or narrow the request."],
    }
    if _json_bytes(payload) > byte_limit:
        raise ValueError("max_bytes is too small for the read envelope")
    return payload


def _fit_or_budget(
    payload: dict,
    schema_version: str,
    view: ResolvedView,
    byte_limit: int,
) -> dict:
    if _json_bytes(payload) <= byte_limit:
        return payload
    return _budget_limited(schema_version, view, byte_limit)


def _encode_cursor(
    *,
    source_fingerprint: str,
    view_id: str,
    request_hash: str,
    offset: int,
) -> str:
    payload = {
        "v": READ_CURSOR_VERSION,
        "source_fingerprint": source_fingerprint,
        "view_id": view_id,
        "request_hash": request_hash,
        "offset": offset,
    }
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    token: str,
    *,
    source_fingerprint: str,
    view_id: str,
    request_hash: str,
) -> int:
    try:
        padding = "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(token + padding))
    except Exception as exc:
        raise ResolvedCursorError("invalid_cursor", "cursor is not valid") from exc
    if not isinstance(payload, dict):
        raise ResolvedCursorError("invalid_cursor", "cursor is not an object")
    if payload.get("v") != READ_CURSOR_VERSION:
        raise ResolvedCursorError("invalid_cursor", "cursor version is unsupported")
    if payload.get("source_fingerprint") != source_fingerprint:
        raise ResolvedCursorError("cursor_stale", "Source changed since first page")
    if payload.get("view_id") != view_id:
        raise ResolvedCursorError("cursor_stale", "ResolvedView changed since first page")
    if payload.get("request_hash") != request_hash:
        raise ResolvedCursorError("cursor_mismatch", "cursor belongs to another request")
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise ResolvedCursorError("invalid_cursor", "cursor offset is invalid")
    return offset


def _validated_bytes(value: int) -> int:
    parsed = int(value)
    if parsed < MIN_READ_MAX_BYTES or parsed > MAX_READ_MAX_BYTES:
        raise ValueError(
            f"max_bytes must be between {MIN_READ_MAX_BYTES} and "
            f"{MAX_READ_MAX_BYTES}")
    return parsed


def _clip(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _declaration_sort_key(item: Declaration) -> tuple:
    return (item.id, item.file, item.line)


def _json_bytes(payload: object) -> int:
    return len(json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))


def _digest_json(payload: object) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
