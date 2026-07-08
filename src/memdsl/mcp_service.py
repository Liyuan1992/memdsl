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
for query/explain. The server is read-only in v0.2; write scopes will
arrive with the gated write pipeline.
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence, Union

from memdsl import __version__
from memdsl.linter import lint
from memdsl.model import Workspace, Declaration
from memdsl.parser import ParseError
from memdsl.query import build_evidence_pack, explain as explain_text

SUMMARY_SCOPE = "read:summary"
SEARCH_SCOPE = "read:search"
DEFAULT_SCOPES = frozenset({SUMMARY_SCOPE, SEARCH_SCOPE})

QUERY_BOUNDARY = (
    "MUST items are hard rules to enforce, not context to weigh. CONTEXT "
    "items are scored candidates. Never average the two kinds of signal. "
    "Surface CONFLICT items instead of silently resolving them."
)

RESOURCE_URIS = (
    "memdsl://status",
    "memdsl://files",
)

TOOL_NAMES = (
    "memory_query",
    "memory_explain",
    "memory_list",
    "memory_lint",
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
    ) -> None:
        paths = [os.path.abspath(str(p)) for p in workspace_paths if str(p).strip()]
        if not paths:
            raise ValueError("at least one workspace path is required")
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            raise FileNotFoundError(f"workspace path(s) not found: {', '.join(missing)}")
        self.workspace_paths = paths
        self.scopes = parse_scopes(scopes)
        self._ws: Optional[Workspace] = None
        self._ws_signature: Optional[tuple] = None

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
        for f in self.mem_files():
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

    def _parse_error(self, schema_version: str, exc: ParseError) -> dict:
        return {
            "ok": False,
            "schema_version": schema_version,
            "status": "parse_error",
            "error": str(exc),
            "next_actions": [
                "Run memory_lint or `memdsl lint` on the workspace and fix the reported file.",
            ],
        }

    # ---- read surfaces ----

    def status(self) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.status.v1"
        try:
            ws = self.workspace()
        except ParseError as exc:
            return self._parse_error(schema, exc)
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
            "scopes": sorted(self.scopes),
            "resources": list(RESOURCE_URIS),
            "tools": list(TOOL_NAMES),
            "boundary": "This server is read-only; it never writes or approves memory.",
        }

    def query(
        self,
        query: str,
        *,
        kinds: Optional[Sequence[str]] = None,
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
        except ParseError as exc:
            return self._parse_error(schema, exc)
        limit = _clamp_int(limit, 1, 50, 8)
        pack = build_evidence_pack(
            ws, query_text,
            kinds=list(kinds) if kinds else None,
            subject=subject or None,
            limit=limit,
        )
        pack_dict = pack.as_dict()
        matched = bool(pack_dict["must"] or pack_dict["should"] or pack_dict["context"])
        next_actions = ["Call memory_explain on any [id] before citing it as evidence."]
        if pack_dict["missing"]:
            next_actions.append(
                "MISSING lists known gaps and open issues; treat them as unknowns, not as absence of rules."
            )
        if not matched:
            next_actions.append("No match: call memory_list to browse declarations, then retry with concrete nouns.")
        return {
            "ok": True,
            "schema_version": schema,
            "status": "ok" if matched else "no_match",
            "evidence_pack": pack_dict,
            "rendered_text": pack.render_text(),
            "boundary": QUERY_BOUNDARY,
            "next_actions": next_actions,
        }

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
                "next_actions": ["Pass a declaration id (kind:name or name)."],
            }
        try:
            ws = self.workspace()
        except ParseError as exc:
            return self._parse_error(schema, exc)
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
                "kind": d.kind,
                "name": d.name,
                "module": d.module,
                "status": d.status,
                "subject": d.subject,
                "force": d.force,
                "scope": d.scope,
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

    def list_declarations(
        self,
        *,
        kind: Optional[str] = None,
        subject: Optional[str] = None,
        include_inactive: bool = False,
        limit: int = 100,
    ) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.list.v1"
        try:
            ws = self.workspace()
        except ParseError as exc:
            return self._parse_error(schema, exc)
        limit = _clamp_int(limit, 1, 500, 100)
        pool = ws.declarations if include_inactive else ws.active()
        items = []
        for d in pool:
            if kind and d.kind != kind:
                continue
            if subject and d.subject != subject:
                continue
            items.append({
                "id": d.id,
                "kind": d.kind,
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

    def lint_workspace(self) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.lint.v1"
        try:
            ws = self.workspace()
        except ParseError as exc:
            return self._parse_error(schema, exc)
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

    # ---- source resources ----

    def list_files(self) -> dict:
        self.require_scope(SUMMARY_SCOPE)
        schema = "memdsl.mcp.files.v1"
        try:
            ws = self.workspace()
        except ParseError as exc:
            return self._parse_error(schema, exc)
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
