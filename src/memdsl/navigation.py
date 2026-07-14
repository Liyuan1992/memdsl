"""Bounded, deterministic Catalog navigation for Phase 2.

The Catalog is a rebuildable projection over the internal report-only View.
It summarizes modules and indexed dimensions without enumerating every
declaration, and it measures ``max_bytes`` as canonical compact UTF-8 JSON.
Map v1 remains a separate compatibility surface.
"""

from __future__ import annotations

import base64
from collections import Counter
import hashlib
import json
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

from memdsl.compiler import WorkspaceInput, ensure_compiled
from memdsl.model import Declaration
from memdsl.view import ResolvedView, resolve_view


CATALOG_SCHEMA = "memdsl.catalog.v1"
MCP_CATALOG_SCHEMA = "memdsl.mcp.catalog.v1"
CATALOG_SCHEMA_V2 = "memdsl.catalog.v2"
MCP_CATALOG_SCHEMA_V2 = "memdsl.mcp.catalog.v2"
CATALOG_CONTRACT_VERSION = "memdsl.catalog.phase2.v1"
CATALOG_CURSOR_VERSION = 1
CATALOG_DEFAULT_LIMIT = 20
CATALOG_DEFAULT_MAX_BYTES = 8192
CATALOG_MIN_MAX_BYTES = 1024
CATALOG_MAX_MAX_BYTES = 1024 * 1024
CATALOG_MAX_LIMIT = 100

_DIMENSION_LIMIT = 6
_VOCABULARY_LIMIT = 8
_LABEL_MAX_BYTES = 160
_FILTER_MAX_VALUES = 64
_FILTER_VALUE_MAX_BYTES = 512


class CatalogCursorError(ValueError):
    """A Catalog cursor is invalid, stale, or bound to another request."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


CatalogSource = Union[WorkspaceInput, ResolvedView]


def build_memory_catalog(
    source: CatalogSource,
    *,
    module: Optional[str] = None,
    types: Optional[Sequence[str]] = None,
    subject: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
    limit: int = CATALOG_DEFAULT_LIMIT,
    max_bytes: int = CATALOG_DEFAULT_MAX_BYTES,
    cursor: Optional[str] = None,
    order: str = "asc",
    representation: str = "structured",
) -> dict:
    """Build one hard-bounded Catalog page.

    Cursors are opaque and bind the source fingerprint, report-only view id,
    normalized filters, order, and representation.  A cursor from another
    source revision raises ``CatalogCursorError(code='cursor_stale')``.
    """
    schema_version = (
        CATALOG_SCHEMA_V2
        if isinstance(source, ResolvedView) and source.enforcement_active
        else CATALOG_SCHEMA
    )
    return _build_memory_catalog(
        source,
        schema_version=schema_version,
        module=module,
        types=types,
        subject=subject,
        statuses=statuses,
        limit=limit,
        max_bytes=max_bytes,
        cursor=cursor,
        order=order,
        representation=representation,
    )


def _build_mcp_memory_catalog(
    source: CatalogSource,
    **kwargs,
) -> dict:
    """Build the MCP schema variant while preserving the same byte budget."""
    schema_version = (
        MCP_CATALOG_SCHEMA_V2
        if isinstance(source, ResolvedView) and source.enforcement_active
        else MCP_CATALOG_SCHEMA
    )
    return _build_memory_catalog(
        source, schema_version=schema_version, **kwargs)


def _build_memory_catalog(
    source: CatalogSource,
    *,
    schema_version: str,
    module: Optional[str],
    types: Optional[Sequence[str]],
    subject: Optional[str],
    statuses: Optional[Sequence[str]],
    limit: int,
    max_bytes: int,
    cursor: Optional[str],
    order: str,
    representation: str,
) -> dict:
    page_limit = _validated_int(
        limit, "limit", minimum=1, maximum=CATALOG_MAX_LIMIT)
    byte_limit = _validated_int(
        max_bytes,
        "max_bytes",
        minimum=CATALOG_MIN_MAX_BYTES,
        maximum=CATALOG_MAX_MAX_BYTES,
    )
    normalized_order = str(order or "").strip().lower()
    if normalized_order not in {"asc", "desc"}:
        raise ValueError("order must be 'asc' or 'desc'")
    normalized_representation = str(representation or "").strip().lower()
    if normalized_representation not in {"structured", "text"}:
        raise ValueError("representation must be 'structured' or 'text'")

    module_filter = _normalize_filter_value(module, "module", allow_none=True)
    if module_filter == "(none)":
        module_filter = ""
    subject_filter = _normalize_filter_value(subject, "subject", allow_none=True)
    type_filter = _normalize_filter_values(types, "types")
    status_filter = _normalize_filter_values(statuses, "statuses")

    if isinstance(source, ResolvedView):
        view = source
    else:
        view = resolve_view(ensure_compiled(source))
    enforced = view.enforcement_active
    if view.blocked:
        result = {
            "ok": False,
            "schema_version": schema_version,
            "status": "compiler_error",
            "view": view.envelope(include_diagnostics=False),
            "summary": view.public_counts(),
            "returned_items": 0,
            "available_items": 0,
            "items": [],
            "truncated": False,
            "next_cursor": None,
            "completeness": "blocked",
            "next_actions": [
                "Run lint and repair blocking identity/source diagnostics."
            ],
        }
        if _json_bytes(result) > byte_limit:
            raise ValueError(
                "max_bytes is too small for the Catalog error envelope")
        return result
    authoritative_objects = {id(item) for item in view.authoritative}
    serviceable = tuple(view.authoritative) + tuple(view.provisional)
    filtered = tuple(
        declaration for declaration in serviceable
        if module_filter is None or (declaration.module or "") == module_filter
        if not type_filter or declaration.kind in type_filter
        if subject_filter is None or declaration.subject == subject_filter
        if not status_filter or declaration.status in status_filter
    )

    grouped: Dict[str, List[Declaration]] = {}
    for declaration in filtered:
        grouped.setdefault(declaration.module or "", []).append(declaration)
    module_names = sorted(grouped)
    if normalized_order == "desc":
        module_names.reverse()
    items = [
        _module_item(name, grouped[name], authoritative_objects)
        for name in module_names
    ]

    filters = {
        "module": module_filter,
        "types": list(type_filter),
        "subject": subject_filter,
        "statuses": list(status_filter),
    }
    request_hash = _digest_json({
        "catalog_contract": CATALOG_CONTRACT_VERSION,
        "schema_version": schema_version,
        "source_fingerprint": view.context.source_fingerprint,
        "view_id": view.view_id,
        "filters": filters,
        "order": normalized_order,
        "representation": normalized_representation,
    })
    offset = 0
    if cursor:
        offset = _decode_cursor(
            str(cursor),
            source_fingerprint=view.context.source_fingerprint,
            view_id=view.view_id,
            request_hash=request_hash,
        )
        if offset > len(items):
            raise CatalogCursorError(
                "invalid_cursor", "cursor offset exceeds the available Catalog")

    authoritative_count = sum(
        1 for declaration in filtered if id(declaration) in authoritative_objects)
    summary = {
        "modules_total": len(items),
        "declarations_matched": len(filtered),
        "declarations_authoritative": authoritative_count,
        "declarations_provisional": len(filtered) - authoritative_count,
        "declarations_quarantined": len(view.quarantined),
        "totals": "exact",
    }
    if enforced:
        summary["declarations_excluded"] = view.public_counts()["excluded"]
    vocabulary = _catalog_vocabulary(filtered)
    compact_vocabulary = {
        key: value
        for key, value in vocabulary.items()
        if key.endswith("_total") or key.endswith("_truncated")
    }

    def payload_for(
        selected: Sequence[dict],
        *,
        vocabulary_payload: dict,
        has_more: bool,
    ) -> dict:
        next_offset = offset + len(selected)
        next_cursor = (
            _encode_cursor(
                source_fingerprint=view.context.source_fingerprint,
                view_id=view.view_id,
                request_hash=request_hash,
                offset=next_offset,
            )
            if has_more else None
        )
        next_actions = [
            "Filter Catalog further or query with its module/type/subject vocabulary."
        ]
        if has_more and not selected:
            next_actions.insert(
                0,
                "No Catalog item fit this byte budget; increase max_bytes or narrow filters.",
            )
        payload = {
            "ok": True,
            "schema_version": schema_version,
            "status": "ok",
            "view": (
                view.envelope(include_diagnostics=False)
                if enforced else view.metadata()),
            "diagnostic_summary": (
                view.envelope(
                    include_diagnostics=False,
                    include_quarantined=False,
                )["diagnostic_summary"]
                if enforced else view.diagnostic_summary()),
            "filters": filters,
            "order": normalized_order,
            "representation": normalized_representation,
            "summary": summary,
            "vocabulary": vocabulary_payload,
            "returned_items": len(selected),
            "available_items": len(items),
            "truncated": has_more,
            "next_cursor": next_cursor,
            "completeness": "partial" if has_more else "complete",
            "boundary": (
                "Catalog is bounded navigation, not citation evidence. "
                "Use query/explain/source before relying on a declaration."
            ),
            "next_actions": next_actions,
        }
        if enforced:
            payload["quarantined"] = [
                {"id": item.id, "reasons": list(view.reasons_for(item))}
                for item in view.quarantined[:20]
            ]
            payload["quarantined_truncated"] = len(view.quarantined) > 20
        if normalized_representation == "structured":
            payload["items"] = list(selected)
        else:
            payload["rendered_text"] = _render_catalog_text(payload, selected)
        return payload

    vocabulary_payload = vocabulary
    remaining = offset < len(items)
    empty = payload_for(
        (), vocabulary_payload=vocabulary_payload, has_more=remaining)
    if _json_bytes(empty) > byte_limit:
        vocabulary_payload = compact_vocabulary
        empty = payload_for(
            (), vocabulary_payload=vocabulary_payload, has_more=remaining)
    if _json_bytes(empty) > byte_limit:
        raise ValueError(
            "max_bytes is too small for the Catalog envelope; increase the budget")

    selected: List[dict] = []
    for item in items[offset: offset + page_limit]:
        prospective = selected + [item]
        has_more = offset + len(prospective) < len(items)
        payload = payload_for(
            prospective,
            vocabulary_payload=vocabulary_payload,
            has_more=has_more,
        )
        if _json_bytes(payload) > byte_limit:
            break
        selected.append(item)

    has_more = offset + len(selected) < len(items)
    result = payload_for(
        selected,
        vocabulary_payload=vocabulary_payload,
        has_more=has_more,
    )
    if _json_bytes(result) > byte_limit:  # defensive: cursor digit growth
        raise AssertionError("Catalog byte budget accounting drifted")
    return result


def _module_item(
    module_name: str,
    declarations: Sequence[Declaration],
    authoritative_objects: set,
) -> dict:
    type_counts = Counter(item.kind for item in declarations)
    role_counts = Counter(item.runtime_role for item in declarations)
    status_counts = Counter(item.status for item in declarations)
    subjects = sorted({item.subject for item in declarations if item.subject})
    authoritative = sum(
        1 for item in declarations if id(item) in authoritative_objects)
    item = {
        "module": _bounded_label(module_name or "(none)"),
        "declarations": len(declarations),
        "authoritative": authoritative,
        "provisional": len(declarations) - authoritative,
    }
    item.update(_bounded_counts("type", type_counts))
    item.update(_bounded_counts("runtime_role", role_counts))
    item.update(_bounded_counts("status", status_counts))
    item.update(_bounded_values("subjects", subjects, _DIMENSION_LIMIT))
    return item


def _bounded_counts(prefix: str, counts: Counter) -> dict:
    names = sorted(counts)
    selected = names[:_DIMENSION_LIMIT]
    return {
        f"{prefix}_counts": {
            _bounded_label(name): counts[name] for name in selected
        },
        f"{prefix}_values_total": len(names),
        f"{prefix}_counts_truncated": len(selected) < len(names),
    }


def _bounded_values(prefix: str, values: Iterable[str], limit: int) -> dict:
    ordered = sorted(set(values))
    selected = ordered[:limit]
    return {
        prefix: [_bounded_label(value) for value in selected],
        f"{prefix}_total": len(ordered),
        f"{prefix}_truncated": len(selected) < len(ordered),
    }


def _catalog_vocabulary(declarations: Sequence[Declaration]) -> dict:
    return {
        **_bounded_values(
            "modules",
            (item.module or "(none)" for item in declarations),
            _VOCABULARY_LIMIT,
        ),
        **_bounded_values(
            "types", (item.kind for item in declarations), _VOCABULARY_LIMIT),
        **_bounded_values(
            "runtime_roles",
            (item.runtime_role for item in declarations),
            _VOCABULARY_LIMIT,
        ),
        **_bounded_values(
            "statuses", (item.status for item in declarations), _VOCABULARY_LIMIT),
        **_bounded_values(
            "subjects",
            (item.subject for item in declarations if item.subject),
            _VOCABULARY_LIMIT,
        ),
    }


def _render_catalog_text(payload: dict, items: Sequence[dict]) -> str:
    summary = payload["summary"]
    lines = [
        "# memory catalog",
        (
            f"modules={summary['modules_total']} "
            f"declarations={summary['declarations_matched']} "
            f"returned={len(items)} completeness={payload['completeness']}"
        ),
    ]
    for item in items:
        types = ", ".join(
            f"{name}({count})" for name, count in item["type_counts"].items())
        statuses = ", ".join(
            f"{name}({count})" for name, count in item["status_counts"].items())
        lines.append(
            f"- {item['module']}: {item['declarations']} declaration(s); "
            f"types={types or '-'}; statuses={statuses or '-'}"
        )
    if payload["truncated"]:
        lines.append("- more modules are available; continue with next_cursor")
    return "\n".join(lines)


def _encode_cursor(
    *,
    source_fingerprint: str,
    view_id: str,
    request_hash: str,
    offset: int,
) -> str:
    payload = {
        "v": CATALOG_CURSOR_VERSION,
        "s": source_fingerprint,
        "w": view_id,
        "r": request_hash,
        "o": offset,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    checksum = hashlib.sha256(
        (CATALOG_CONTRACT_VERSION + ":" + body).encode("ascii")
    ).hexdigest()[:24]
    return body + "." + checksum


def _decode_cursor(
    token: str,
    *,
    source_fingerprint: str,
    view_id: str,
    request_hash: str,
) -> int:
    try:
        body, checksum = token.split(".", 1)
        expected = hashlib.sha256(
            (CATALOG_CONTRACT_VERSION + ":" + body).encode("ascii")
        ).hexdigest()[:24]
        if checksum != expected:
            raise ValueError("checksum")
        padding = "=" * (-len(body) % 4)
        decoded = base64.urlsafe_b64decode((body + padding).encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogCursorError(
            "invalid_cursor", "cursor is malformed or has invalid integrity") from exc
    if not isinstance(payload, dict) or payload.get("v") != CATALOG_CURSOR_VERSION:
        raise CatalogCursorError("invalid_cursor", "cursor version is unsupported")
    if payload.get("s") != source_fingerprint or payload.get("w") != view_id:
        raise CatalogCursorError(
            "cursor_stale", "source fingerprint or view id changed")
    if payload.get("r") != request_hash:
        raise CatalogCursorError(
            "cursor_mismatch", "cursor filters, order, or representation changed")
    offset = payload.get("o")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise CatalogCursorError("invalid_cursor", "cursor offset is invalid")
    return offset


def _normalize_filter_values(
    values: Optional[Sequence[str]],
    name: str,
) -> Tuple[str, ...]:
    if values is None:
        return ()
    raw_values = [values] if isinstance(values, str) else list(values)
    if len(raw_values) > _FILTER_MAX_VALUES:
        raise ValueError(f"{name} accepts at most {_FILTER_MAX_VALUES} values")
    normalized = {
        _normalize_filter_value(value, name, allow_none=False)
        for value in raw_values
    }
    return tuple(sorted(value for value in normalized if value is not None))


def _normalize_filter_value(
    value: Optional[str],
    name: str,
    *,
    allow_none: bool,
) -> Optional[str]:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{name} values must be non-empty strings")
    if not isinstance(value, str):
        raise ValueError(f"{name} values must be strings")
    normalized = value.strip()
    if not normalized:
        if allow_none:
            return None
        raise ValueError(f"{name} values must be non-empty strings")
    if len(normalized.encode("utf-8")) > _FILTER_VALUE_MAX_BYTES:
        raise ValueError(
            f"{name} values must be at most {_FILTER_VALUE_MAX_BYTES} UTF-8 bytes")
    return normalized


def _bounded_label(value: str) -> str:
    text = str(value)
    encoded = text.encode("utf-8")
    if len(encoded) <= _LABEL_MAX_BYTES:
        return text
    digest = hashlib.sha256(encoded).hexdigest()[:10]
    suffix = ("…#" + digest).encode("utf-8")
    room = _LABEL_MAX_BYTES - len(suffix)
    prefix = encoded[:room]
    while prefix:
        try:
            decoded = prefix.decode("utf-8")
            return decoded + "…#" + digest
        except UnicodeDecodeError:
            prefix = prefix[:-1]
    return "#" + digest


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
