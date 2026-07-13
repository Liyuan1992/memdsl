"""SDK-free service layer for the memdsl MCP server.

Builds plain-dict payloads over a `.mem` workspace so the whole contract
can be exercised without the MCP SDK installed; `memdsl.mcp_server` wires
these payloads into FastMCP tools and resources.

Every payload carries:

    schema_version   versioned payload shape, e.g. "memdsl.mcp.query.v1"
    boundary         the normative contract the caller must respect
    next_actions     what a well-behaved agent should do next

Access is gated by scopes (comma-separated in MEMDSL_MCP_SCOPES or passed
explicitly): "read:summary" for status/list/lint/source, "read:search"
for query/explain/check, "write:candidate" for memory_propose. Writes are
propose-only and fail-closed: a proposal lands in the review queue
(`memdsl.review.ReviewStore`) and nothing becomes memory until a human
approves it with `memdsl review approve`.
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence, Union

from memdsl import __version__
from memdsl.compliance import check_compliance
from memdsl.linter import lint
from memdsl.model import Workspace, Declaration
from memdsl.parser import ParseError
from memdsl.query import (
    build_evidence_pack,
    build_memory_map,
    explain as explain_text,
    render_memory_map_text,
    workspace_vocabulary,
)
from memdsl.review import ReviewStore, staging_dir_for
from memdsl.schema import SchemaError

SUMMARY_SCOPE = "read:summary"
SEARCH_SCOPE = "read:search"
WRITE_CANDIDATE_SCOPE = "write:candidate"
DEFAULT_SCOPES = frozenset({SUMMARY_SCOPE, SEARCH_SCOPE, WRITE_CANDIDATE_SCOPE})

QUERY_BOUNDARY = (
    "MUST items are hard rules to enforce, not context to weigh. CONTEXT "
    "items are scored candidates. Never average the two kinds of signal. "
    "Surface CONFLICT items instead of silently resolving them."
)

RESOURCE_URIS = (
    "memdsl://status",
    "memdsl://map",
    "memdsl://types",
    "memdsl://files",
)

TOOL_NAMES = (
    "memory_map",
    "memory_query",
    "memory_check",
    "memory_types",
    "memory_explain",
    "memory_list",
    "memory_lint",
    "memory_propose",
    "memory_review_list",
)

PROPOSE_BOUNDARY = (
    "A proposal is not memory. It sits in the review queue and is never "
    "served by memory_query until a human approves it with "
    "`memdsl review approve`. Do not treat a pending proposal as an "
    "accepted fact or rule."
)


class MCPScopeError(PermissionError):
    """Raised when a requested operation is outside the configured scopes."""


def parse_scopes(value: Union[str, Sequence[str], None] = None) -> set:
    raw = value
    if raw is None:
        raw = os.getenv("MEMDSL_MCP_SCOPES", "")
    if isinstance(raw, str):
        items = [item.strip() for item in raw.split(",")]
    else:
        items = [str(item or "").strip() for item in raw]
    scopes = {item for item in items if item}
    return scopes or set(DEFAULT_SCOPES)


class MemdslMCPService:
    """Expose a `.mem` workspace as stable MCP-shaped payloads."""

    def __init__(
        self,
        workspace_paths: Sequence[str],
        *,
        scopes: Union[str, Sequence[str], None] = None,
        staging: Optional[str] = None,
        client_name: str = "",
    ) -> None:
        paths = [os.path.abspath(str(p)) for p in workspace_paths if str(p).strip()]
        if not paths:
            raise ValueError("at least one workspace path is required")
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            raise FileNotFoundError(f"workspace path(s) not found: {', '.join(missing)}")
        self.workspace_paths = paths
        self.scopes = parse_scopes(scopes)
        self.client_name = client_name or os.getenv("MEMDSL_MCP_CLIENT", "mcp-client")
        self._staging = staging
        self._review: Optional[ReviewStore] = None
        self._ws: Optional[Workspace] = None
        self._ws_signature: Optional[tuple] = None

    @property
    def review_store(self) -> ReviewStore:
        if self._review is None:
            self._review = ReviewStore(staging_dir_for(self.workspace_paths, self._staging))
        return self._review

    # ---- workspace loading ----

    def mem_files(self) -> List[str]:
        files: List[str] = []
        for path in self.workspace_paths:
            if os.path.isdir(path):
                for root, _dirs, names in os.walk(path):
                    for name in sorted(names):
                        if name.endswith(".mem"):
                            files.append(os.path.join(root, name))
            elif path.endswith(".mem"):
                files.append(path)
        return files

    def workspace(self) -> Workspace:
        """Load the workspace, reloading when any `.mem` file changes."""
        signature = []
        tracked_files = list(self.mem_files())
        if self._ws is not None:
            tracked_files.extend(self._ws.registry.schema_files)
            for path in self.workspace_paths:
                root = path if os.path.isdir(path) else os.path.dirname(path)
                manifest = os.path.join(root, "memdsl.json")
                if os.path.isfile(manifest):
                    tracked_files.append(manifest)
        for f in sorted(set(tracked_files)):
            try:
                signature.append((f, os.path.getmtime(f), os.path.getsize(f)))
            except OSError:
                signature.append((f, 0.0, -1))
        signature = tuple(signature)
        if self._ws is None or signature != self._ws_signature:
            self._ws = Workspace.load(self.workspace_paths)
            self._ws_signature = signature
        return self._ws

    def require_scope(self, scope: str) -> None:
        if scope not in self.scopes and "all" not in self.scopes:
            raise MCPScopeError(
                f"memdsl MCP scope '{scope}' is required. "
                f"Configured scopes: {', '.join(sorted(self.scopes)) or '(none)'}"
            )

    def _workspace_error(
        self,
        schema_version: str,
        exc: Union[ParseError, SchemaError],
    ) -> dict:
        status = "schema_error" if isinstance(exc, SchemaError) else "parse_error"
        return {
            "ok": False,
            "schema_version": schema_version,
            "status": status,
            "error": str(exc),
            "next_actions": [
                "Run `memdsl lint` on the workspace and fix the reported source, "
                "manifest, or schema file.",
            ],
        }

    # ---- read surfaces ----

    def status(self) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.status.v1"
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        kinds: dict = {}
        for d in ws.declarations:
            kinds[d.kind] = kinds.get(d.kind, 0) + 1
        return {
            "ok": True,
            "schema_version": schema,
            "server": "memdsl",
            "version": __version__,
            "workspace_paths": list(self.workspace_paths),
            "files": len(ws.files),
            "declarations": len(ws.declarations),
            "active_declarations": len(ws.active()),
            "kinds": dict(sorted(kinds.items())),
            "types": dict(sorted(kinds.items())),
            "registered_types": self._ws.registry.names(),
            "schema_files": list(self._ws.registry.schema_files),
            "scopes": sorted(self.scopes),
            "resources": list(RESOURCE_URIS),
            "tools": list(TOOL_NAMES),
            "pending_proposals": len(self.review_store.list(status="pending")),
            "boundary": (
                "Writes are propose-only: memory_propose stages a proposal for "
                "human review; this server never approves or serves unapproved memory."
            ),
        }

    def memory_map(self) -> dict:
        """Compact per-module index of all active memory, for session start."""
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.map.v1"
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        map_data = build_memory_map(ws)
        return {
            "ok": True,
            "schema_version": schema,
            "status": "ok",
            "declarations": map_data["declarations"],
            "modules": map_data["modules"],
            "vocabulary": map_data["vocabulary"],
            "rendered_text": render_memory_map_text(map_data),
            "boundary": (
                "The map is a navigation index, not the memory itself: "
                "claims are truncated and carry no evidence. Call "
                "memory_explain (or read the .mem source) before citing or "
                "acting on any item."
            ),
            "next_actions": [
                "Keep this map in context and query with the map's own "
                "nouns (subjects, scopes, module names).",
                "Call memory_explain on an id for full evidence and relations.",
            ],
        }

    def query(
        self,
        query: str,
        *,
        kinds: Optional[Sequence[str]] = None,
        types: Optional[Sequence[str]] = None,
        subject: Optional[str] = None,
        limit: int = 8,
    ) -> dict:
        self.require_scope(SEARCH_SCOPE)
        schema = "memdsl.mcp.query.v1"
        query_text = str(query or "").strip()
        if not query_text:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "invalid",
                "error": "query_required",
                "next_actions": ["Provide a non-empty query."],
            }
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        limit = _clamp_int(limit, 1, 50, 8)
        pack = build_evidence_pack(
            ws, query_text,
            kinds=list(kinds) if kinds else None,
            types=list(types) if types else None,
            subject=subject or None,
            limit=limit,
        )
        pack_dict = pack.as_dict()
        matched = bool(pack_dict["must"] or pack_dict["should"] or pack_dict["context"])
        next_actions = []
        if matched:
            next_actions.append(
                "Call memory_explain on any [id] before citing it as evidence.")
        if pack_dict["missing"]:
            next_actions.append(
                "MISSING lists known gaps and open issues; treat them as unknowns, not as absence of rules."
            )
        payload = {
            "ok": True,
            "schema_version": schema,
            "status": "ok" if matched else "no_match",
            "evidence_pack": pack_dict,
            "rendered_text": pack.render_text(),
            "boundary": QUERY_BOUNDARY,
            "next_actions": next_actions,
        }
        if not matched:
            # A miss is a retry signal, not proof of absence: say what the
            # filters hid and which vocabulary this workspace answers to.
            excluded = pack.trace.get("excluded_by_filters_total", 0)
            if excluded:
                next_actions.append(
                    f"{excluded} declaration(s) matched the query but were "
                    "excluded by your types/subject filter; see "
                    "evidence_pack.search_trace.excluded_by_filters and retry "
                    "without the filter, or memory_explain those ids directly."
                )
            next_actions.append(
                "No match: re-ask using this workspace's own vocabulary "
                "(see vocabulary.subjects/aliases/scopes/types), or call "
                "memory_list to browse declarations."
            )
            payload["vocabulary"] = workspace_vocabulary(ws)
        return payload

    def explain(self, decl_id: str) -> dict:
        self.require_scope(SEARCH_SCOPE)
        schema = "memdsl.mcp.explain.v1"
        ref = str(decl_id or "").strip()
        if not ref:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "invalid",
                "error": "id_required",
                "next_actions": ["Pass a declaration id (type:name or name)."],
            }
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        d = ws.by_id(ref)
        if d is None:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "not_found",
                "id": ref,
                "next_actions": ["Call memory_list to browse available declaration ids."],
            }
        referenced_by = []
        for other in ws.declarations:
            if other.id == d.id:
                continue
            for rel, targets in other.relations().items():
                for t in targets:
                    if t in (d.id, d.name):
                        referenced_by.append({"id": other.id, "relation": rel})
        return {
            "ok": True,
            "schema_version": schema,
            "status": "ok",
            "declaration": {
                "id": d.id,
                "type": d.kind,
                "kind": d.kind,
                "runtime_role": d.runtime_role,
                "capabilities": sorted(d.capabilities),
                "name": d.name,
                "module": d.module,
                "status": d.status,
                "subject": d.subject,
                "force": d.force,
                "scope": d.scope,
                "confidence": d.confidence,
                "lifecycle": d.lifecycle,
                "access_policy": d.access_policy,
                "claim": d.claim_text,
                "file": d.file,
                "line": d.line,
                "relations": d.relations(),
                "referenced_by": referenced_by,
                "evidence": d.evidence or {},
                "fields": {k: v for k, v in d.fields.items() if k != "evidence"},
            },
            "rendered_text": explain_text(ws, ref),
            "boundary": (
                "evidence.quote and source anchor this declaration to its origin; "
                "cite the declaration id, do not paraphrase it as your own inference."
            ),
        }

    def check(
        self,
        task: str,
        candidate: str,
        *,
        subject: Optional[str] = None,
        scope: Optional[str] = None,
        exceptions: Optional[Sequence[str]] = None,
    ) -> dict:
        """Preflight a proposed action or draft against applicable MUST rules."""
        self.require_scope(SEARCH_SCOPE)
        schema = "memdsl.mcp.check.v1"
        task_text = str(task or "").strip()
        candidate_text = str(candidate or "").strip()
        if not task_text or not candidate_text:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "invalid",
                "error": "task_and_candidate_required",
                "next_actions": [
                    "Provide both the attempted task and the candidate action or draft.",
                ],
            }
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        pack = check_compliance(
            ws, task_text, candidate_text,
            subject=subject or None,
            scope=scope or None,
            exceptions=list(exceptions or []),
        )
        next_actions = []
        if pack.verdict == "block":
            next_actions.append(
                "Do not use the candidate. Revise it to remove every cited violation, then call memory_check again.")
        elif pack.verdict == "needs_review":
            next_actions.append(
                "Do not assume approval. Route each unknown constraint to a human or semantic evaluator.")
        else:
            next_actions.append(
                "The deterministic guard checks passed; continue to respect the cited MUST declarations.")
        return {
            "ok": True,
            "schema_version": schema,
            "status": pack.verdict,
            "compliance_pack": pack.as_dict(),
            "rendered_text": pack.render_text(),
            "boundary": (
                "BLOCK forbids the candidate. NEEDS_REVIEW is not approval: it means "
                "an applicable natural-language constraint lacks a deterministic guard."
            ),
            "next_actions": next_actions,
        }

    def list_declarations(
        self,
        *,
        kind: Optional[str] = None,
        memory_type: Optional[str] = None,
        subject: Optional[str] = None,
        include_inactive: bool = False,
        limit: int = 100,
    ) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.list.v1"
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        limit = _clamp_int(limit, 1, 500, 100)
        pool = ws.declarations if include_inactive else ws.active()
        items = []
        for d in pool:
            requested_type = memory_type or kind
            if requested_type and d.kind != requested_type:
                continue
            if subject and d.subject != subject:
                continue
            items.append({
                "id": d.id,
                "type": d.kind,
                "kind": d.kind,
                "runtime_role": d.runtime_role,
                "capabilities": sorted(d.capabilities),
                "subject": d.subject,
                "scope": d.scope,
                "status": d.status,
                "claim": _truncate(d.claim_text, 200),
                "file": d.file,
                "line": d.line,
                "has_evidence": bool(d.evidence),
            })
        return {
            "ok": True,
            "schema_version": schema,
            "status": "ok",
            "total": len(items),
            "items": items[:limit],
            "next_actions": ["Call memory_explain on an id to see its evidence and relations."],
        }

    def list_types(self) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.types.v1"
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        items = []
        for descriptor in ws.registry.descriptors():
            items.append(descriptor.as_dict())
        return {
            "ok": True,
            "schema_version": schema,
            "status": "ok",
            "total": len(items),
            "schema_files": list(ws.registry.schema_files),
            "types": items,
            "next_actions": [
                "Choose a loaded domain type whose runtime_role and required_fields match the memory being proposed.",
            ],
        }

    def lint_workspace(self) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.lint.v1"
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        diags = lint(ws)
        errors = sum(1 for d in diags if d.severity == "error")
        warnings = sum(1 for d in diags if d.severity == "warning")
        return {
            "ok": errors == 0,
            "schema_version": schema,
            "status": "ok" if errors == 0 else "errors",
            "declarations": len(ws.declarations),
            "errors": errors,
            "warnings": warnings,
            "diagnostics": [
                {
                    "code": d.code,
                    "severity": d.severity,
                    "message": d.message,
                    "file": d.file,
                    "line": d.line,
                    "decl_id": d.decl_id,
                }
                for d in diags
            ],
            "boundary": "Diagnostics describe the memory source; fixing it is a human edit, not an MCP write.",
        }

    # ---- gated writes (propose-only) ----

    def propose(self, source: str, *, reason: str = "") -> dict:
        self.require_scope(WRITE_CANDIDATE_SCOPE)
        schema = "memdsl.mcp.propose.v1"
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        result = self.review_store.create(
            ws, source, reason=reason, client=self.client_name)
        if not result["ok"]:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "invalid",
                "errors": result.get("errors", []),
                "warnings": result.get("warnings", []),
                "boundary": PROPOSE_BOUNDARY,
                "next_actions": [
                    "Fix the declaration source: it must parse to exactly one declaration "
                    "and pass lint against the live workspace (types with the "
                    "requires_evidence capability need a verbatim evidence quote).",
                ],
            }
        return {
            "ok": True,
            "schema_version": schema,
            "status": "pending_review",
            "proposal_id": result["proposal_id"],
            "declaration_id": result["declaration_id"],
            "path": result["path"],
            "warnings": result.get("warnings", []),
            "boundary": PROPOSE_BOUNDARY,
            "next_actions": [
                "Tell the user a proposal is pending and how to review it: "
                "`memdsl review list <workspace>` then "
                f"`memdsl review approve <workspace> {result['proposal_id']} --into <file.mem>`.",
            ],
        }

    def list_proposals(self, *, status: str = "pending", limit: int = 50) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.review_list.v1"
        if status not in ("pending", "approved", "rejected", "all"):
            return {
                "ok": False,
                "schema_version": schema,
                "status": "invalid",
                "error": "status must be pending, approved, rejected, or all",
            }
        limit = _clamp_int(limit, 1, 200, 50)
        proposals = [p.summary() for p in self.review_store.list(status=status)]
        return {
            "ok": True,
            "schema_version": schema,
            "status": "ok",
            "filter": status,
            "total": len(proposals),
            "proposals": proposals[:limit],
            "boundary": PROPOSE_BOUNDARY,
            "next_actions": [
                "Approval and rejection are human-only, via the memdsl review CLI.",
            ],
        }

    # ---- source resources ----

    def list_files(self) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.files.v1"
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        per_file: dict = {}
        for d in ws.declarations:
            per_file[d.file] = per_file.get(d.file, 0) + 1
        files = [
            {"file_id": str(i), "path": path, "declarations": per_file.get(path, 0)}
            for i, path in enumerate(self.mem_files())
        ]
        return {
            "ok": True,
            "schema_version": schema,
            "status": "ok",
            "files": files,
            "next_actions": ["Read memdsl://file/{file_id} for the raw .mem source."],
        }

    def read_file(self, file_id: str) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.file.v1"
        files = self.mem_files()
        ref = str(file_id or "").strip()
        index: Optional[int] = None
        if ref.isdigit() and int(ref) < len(files):
            index = int(ref)
        else:
            for i, path in enumerate(files):
                if ref and (path == ref or os.path.basename(path) == ref):
                    index = i
                    break
        if index is None:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "not_found",
                "file_id": ref,
                "next_actions": ["Read memdsl://files for valid file ids."],
            }
        path = files[index]
        try:
            content = open(path, "r", encoding="utf-8").read()
        except OSError as exc:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "read_error",
                "file_id": ref,
                "error": str(exc),
            }
        return {
            "ok": True,
            "schema_version": schema,
            "status": "ok",
            "file_id": str(index),
            "path": path,
            "content": content,
        }


def _clamp_int(value, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"
