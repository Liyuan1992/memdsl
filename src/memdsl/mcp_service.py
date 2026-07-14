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
for query/explain/check, and "write:candidate" for memory_propose.  The
optional "write:auto" scope is a deployment key for policy-authorized writes;
it is never enabled by default.  Pending proposals remain invisible.  Only a
candidate assertion that passes the non-configurable safety floor, an explicit
workspace policy, host identity, verified evidence, quota, and sampling may be
auto-approved into the PROVISIONAL layer.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Callable, List, Mapping, Optional, Sequence, Union

from memdsl import __version__
from memdsl.authority import current_declarations
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
from memdsl.policy import (
    AUTO_APPROVABLE_CAPABILITY,
    EvidenceVerification,
    PolicyError,
    ProposalContext,
    load_policy,
    verify_workspace_file_quote,
)
from memdsl.review import AuditLogError, ReviewStore, staging_dir_for
from memdsl.review_reporting import proposal_review_metadata
from memdsl.schema import SchemaError

SUMMARY_SCOPE = "read:summary"
SEARCH_SCOPE = "read:search"
WRITE_CANDIDATE_SCOPE = "write:candidate"
WRITE_AUTO_SCOPE = "write:auto"
DEFAULT_SCOPES = frozenset({SUMMARY_SCOPE, SEARCH_SCOPE, WRITE_CANDIDATE_SCOPE})

QUERY_BOUNDARY = (
    "MUST items are active hard rules to enforce, not context to weigh. "
    "SHOULD and CONTEXT contain active guidance and assertions. PROVISIONAL "
    "items are non-active, unconfirmed candidates and never carry MUST, "
    "SHOULD, CONTEXT, MISSING, or compliance authority. Surface CONFLICT "
    "items instead of silently resolving them."
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

AUTO_APPROVED_BOUNDARY = (
    "This proposal was auto-approved as candidate-status provisional memory. "
    "It has not been human-confirmed. It never becomes MUST, SHOULD, CONTEXT, "
    "MISSING, or an enforceable compliance constraint while non-active. A "
    "human may later confirm or flag it and may supersede it through another "
    "reviewed declaration proposal."
)

NO_OP_BOUNDARY = (
    "This submission is an exact normalized duplicate. No second proposal or "
    "memory declaration was created; the response points to the existing record."
)


class MCPScopeError(PermissionError):
    """Raised when a requested operation is outside the configured scopes."""


EvidenceVerifier = Callable[
    [Optional[Mapping[str, object]], Sequence[str]],
    EvidenceVerification,
]
ProposalContextFactory = Callable[[str], ProposalContext]


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
        evidence_verifier: Optional[EvidenceVerifier] = verify_workspace_file_quote,
        context_factory: Optional[ProposalContextFactory] = None,
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
        if evidence_verifier is not None and not callable(evidence_verifier):
            raise TypeError("evidence_verifier must be callable or None")
        if context_factory is not None and not callable(context_factory):
            raise TypeError("context_factory must be callable or None")
        self.evidence_verifier = evidence_verifier
        self.context_factory = context_factory
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

    def _write_auto_granted(self) -> bool:
        return WRITE_AUTO_SCOPE in self.scopes or "all" in self.scopes

    def _base_proposal_context(self) -> tuple:
        """Build host-owned identity without accepting proposal/tool attestation."""
        if self.context_factory is None:
            return ProposalContext(client_id=self.client_name), ""
        try:
            context = self.context_factory(self.client_name)
        except Exception:
            return ProposalContext(client_id=self.client_name), "context_factory_exception"
        if not isinstance(context, ProposalContext):
            return ProposalContext(client_id=self.client_name), "context_factory_invalid"
        return context, ""

    def _proposal_context(self, ws: Workspace, source: str) -> ProposalContext:
        """Attach host-verified evidence, failing closed to an unverified proof."""
        context, context_error = self._base_proposal_context()
        if context.evidence_verification is not None:
            return context

        validation = self.review_store.validate(ws, source)
        evidence = (
            validation.declaration.evidence
            if validation.declaration is not None else None)
        if context_error:
            proof = EvidenceVerification.unverified(
                context_error, evidence=evidence)
            return context.with_evidence(proof)
        if self.evidence_verifier is None:
            proof = EvidenceVerification.unverified(
                "evidence_verifier_unavailable", evidence=evidence)
            return context.with_evidence(proof)
        try:
            proof = self.evidence_verifier(evidence, self.workspace_paths)
        except Exception:
            proof = EvidenceVerification.unverified(
                "evidence_verifier_exception",
                verifier=_callable_name(self.evidence_verifier),
                evidence=evidence,
            )
        if not isinstance(proof, EvidenceVerification):
            proof = EvidenceVerification.unverified(
                "evidence_verifier_invalid_result",
                verifier=_callable_name(self.evidence_verifier),
                evidence=evidence,
            )
        return context.with_evidence(proof)

    def _automation_effective(self, policy, ws: Workspace, auto_today: int) -> bool:
        """Whether this service configuration can still auto-route a safe type."""
        if (
            policy is None
            or not self._write_auto_granted()
            or policy.sample_to_queue_percent >= 100
            or auto_today >= policy.max_auto_approve_per_day
        ):
            return False
        context, context_error = self._base_proposal_context()
        if context_error or context.client_id not in policy.trusted_clients:
            return False
        if self.evidence_verifier is None:
            proof = context.evidence_verification
            if proof is None or not proof.verified:
                return False
        for rule in policy.rules:
            rule_clients = rule.match.get("client")
            if rule_clients and context.client_id not in rule_clients:
                continue
            scopes = rule.match.get("scope")
            excluded_scopes = set(rule.match.get("scope_not", ()))
            if scopes and not any(
                    scope and str(scope).strip().lower() != "global"
                    and scope not in excluded_scopes
                    for scope in scopes):
                continue
            for kind in rule.match["kind"]:
                descriptor = ws.registry.resolve(kind)
                if (
                    descriptor is not None
                    and descriptor.runtime_role == "assertion"
                    and descriptor.has_capability(AUTO_APPROVABLE_CAPABILITY)
                ):
                    return True
        return False

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
        current = current_declarations(ws)
        kinds: dict = {}
        for d in ws.declarations:
            kinds[d.kind] = kinds.get(d.kind, 0) + 1
        policy_present = os.path.isfile(
            os.path.join(self.review_store.staging_dir, "policy.json"))
        try:
            policy = load_policy(self.review_store.staging_dir, registry=ws.registry)
            if policy is not None:
                self.review_store.validate_policy_target(
                    policy, self.workspace_paths)
        except PolicyError as exc:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "policy_invalid",
                "error": "policy_invalid",
                "details": [str(exc)],
                "policy_present": policy_present,
                "policy_valid": False,
                "write_auto_granted": self._write_auto_granted(),
                "boundary": (
                    "A configured review policy is invalid. Writes fail closed "
                    "until the operator fixes or removes policy.json."
                ),
            }
        try:
            audit = self.review_store.audit_entries(strict=True)
        except AuditLogError as exc:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "audit_invalid",
                "error": "audit_invalid",
                "details": [str(exc)],
                "policy_present": policy_present,
                "policy_valid": policy is not None,
                "policy_hash": policy.source_hash if policy is not None else "",
                "write_auto_granted": self._write_auto_granted(),
                "boundary": (
                    "The append-only audit log cannot be replayed reliably. "
                    "Automatic approval is disabled until it is repaired."
                ),
            }
        auto_ids, reviewed_ids = _automatic_review_ids(audit)
        today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        auto_today = len(_automatic_route_reservation_ids(audit, today))
        write_auto = self._write_auto_granted()
        automation_effective = self._automation_effective(policy, ws, auto_today)
        return {
            "ok": True,
            "schema_version": schema,
            "server": "memdsl",
            "version": __version__,
            "workspace_paths": list(self.workspace_paths),
            "files": len(ws.files),
            "declarations": len(ws.declarations),
            "active_declarations": sum(
                1 for declaration in current
                if declaration.status == "active"),
            "provisional_declarations": sum(
                1 for declaration in current
                if declaration.status != "active"),
            "kinds": dict(sorted(kinds.items())),
            "types": dict(sorted(kinds.items())),
            "registered_types": self._ws.registry.names(),
            "schema_files": list(self._ws.registry.schema_files),
            "scopes": sorted(self.scopes),
            "resources": list(RESOURCE_URIS),
            "tools": list(TOOL_NAMES),
            "pending_proposals": len(self.review_store.list(status="pending")),
            "policy_present": policy_present,
            "policy_valid": True,
            "policy_hash": policy.source_hash if policy is not None else "",
            "write_auto_granted": write_auto,
            "automation_effective": automation_effective,
            "auto_approvals_today": auto_today,
            "max_auto_approve_per_day": (
                policy.max_auto_approve_per_day if policy is not None else 0),
            "unaudited_auto_approvals": len(auto_ids - reviewed_ids),
            "boundary": (
                "Pending proposals are never served. Automatic approval is "
                "available only for policy- and type-opted-in candidate "
                "assertions with a trusted client, verified evidence, write:auto, "
                "quota, and sampling approval; they remain PROVISIONAL until a "
                "human-approved revision activates or supersedes them."
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
        matched = bool(
            pack_dict["must"]
            or pack_dict["should"]
            or pack_dict["context"]
            or pack_dict.get("provisional")
        )
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
        pool = ws.declarations if include_inactive else current_declarations(ws)
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

    # ---- governed writes ----

    def propose(self, source: str, *, reason: str = "") -> dict:
        self.require_scope(WRITE_CANDIDATE_SCOPE)
        schema = "memdsl.mcp.propose.v2"
        try:
            ws = self.workspace()
        except (ParseError, SchemaError) as exc:
            return self._workspace_error(schema, exc)
        try:
            policy = load_policy(self.review_store.staging_dir, registry=ws.registry)
        except PolicyError as exc:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "policy_invalid",
                "error": "policy_invalid",
                "details": [str(exc)],
                "boundary": (
                    "A configured policy is invalid. Nothing was staged or "
                    "approved; fix or remove policy.json before retrying."
                ),
                "next_actions": [
                    "Run `memdsl review policy validate <workspace>` and fix every error."
                ],
            }
        write_auto = self._write_auto_granted()
        context = self._proposal_context(ws, source) if policy is not None else None
        try:
            result = self.review_store.submit(
                self.workspace_paths,
                source,
                reason=reason,
                client=self.client_name,
                policy=policy,
                context=context,
                blocking_reasons=([] if write_auto else ["write_auto_not_granted"]),
                write_auto_granted=write_auto,
                evidence_verifier=self.evidence_verifier,
            )
        except PolicyError as exc:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "policy_invalid",
                "error": "policy_invalid",
                "details": [str(exc)],
                "boundary": (
                    "The review policy or its automatic target is unsafe. "
                    "Nothing was auto-approved."
                ),
                "next_actions": [
                    "Run `memdsl review policy validate <workspace>` and correct the policy."
                ],
            }
        except AuditLogError as exc:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "audit_invalid",
                "error": "audit_invalid",
                "details": [str(exc)],
                "boundary": (
                    "The append-only audit cannot be replayed reliably, so "
                    "policy routing failed closed before automatic approval."
                ),
                "next_actions": [
                    "Inspect and repair the audit log without deleting valid history."
                ],
            }
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
        route = str(result.get("route") or "queued")
        rule = str(result.get("rule") or result.get("route_rule") or "no_policy")
        reason_codes = list(result.get("reason_codes") or (
            ["policy_missing"] if policy is None else ["human_review_required"]))
        if route == "auto_approved":
            boundary = AUTO_APPROVED_BOUNDARY
            next_actions = [
                "Treat the new declaration only as PROVISIONAL candidate memory.",
                "Use `memdsl review digest <workspace>` and `memdsl review audit` "
                "to confirm or flag policy-approved items.",
            ]
        elif route == "no_op":
            boundary = NO_OP_BOUNDARY
            next_actions = [
                "Use the returned existing proposal or declaration id; do not resubmit it."
            ]
        else:
            boundary = (
                PROPOSE_BOUNDARY
                + (f" Routing reason: {reason_codes[0]}." if reason_codes else "")
            )
            next_actions = [
                "Tell the user the proposal is pending and how to review it: "
                "`memdsl review list <workspace>` then "
                f"`memdsl review approve <workspace> {result.get('proposal_id', '')} --into <file.mem>`.",
            ]
        payload = {
            "ok": True,
            "schema_version": schema,
            "status": result.get("status", "pending_review"),
            "route": route,
            "proposal_id": result.get("proposal_id", ""),
            "declaration_id": result.get("declaration_id", ""),
            "path": result.get("path", ""),
            "rule": rule,
            "reason_codes": reason_codes,
            "assessment_hash": result.get("assessment_hash", ""),
            "eligible_route": result.get("eligible_route", route),
            "warnings": result.get("warnings", []),
            "boundary": boundary,
            "next_actions": next_actions,
        }
        if result.get("merged_into"):
            payload["merged_into"] = result["merged_into"]
        if result.get("content_hash"):
            payload["content_hash"] = result["content_hash"]
        if result.get("policy_hash"):
            payload["policy_hash"] = result["policy_hash"]
        if result.get("duplicate_of"):
            payload["duplicate_of"] = result["duplicate_of"]
        if result.get("approval_error"):
            payload["approval_error"] = result["approval_error"]
        return payload

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
        try:
            audit = self.review_store.audit_entries(strict=True)
        except AuditLogError as exc:
            return {
                "ok": False,
                "schema_version": schema,
                "status": "audit_invalid",
                "error": "audit_invalid",
                "details": [str(exc)],
            }
        metadata = proposal_review_metadata(audit)
        proposals = []
        for proposal in self.review_store.list(status=status):
            summary = proposal.summary()
            review = metadata.get(proposal.id, {})
            summary.update({
                "route": review.get("route", "legacy_unknown"),
                "rule": review.get("rule", "legacy_unknown"),
                "assessment_hash": review.get("assessment_hash", ""),
                "content_hash": review.get("content_hash", ""),
                "post_review_verdict": review.get("post_review_verdict", ""),
            })
            proposals.append(summary)
        return {
            "ok": True,
            "schema_version": schema,
            "status": "ok",
            "filter": status,
            "total": len(proposals),
            "proposals": proposals[:limit],
            "boundary": (
                "Pending proposals remain invisible. Policy-approved candidate "
                "assertions are PROVISIONAL and may receive a later human "
                "confirm or flag; high-risk and superseding writes require a "
                "human decision."
            ),
            "next_actions": [
                "Use the memdsl review CLI for approve/reject, digest, stats, "
                "and post-review audit decisions.",
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


def _automatic_review_ids(entries: Sequence[dict]) -> tuple:
    automatic = {
        str(entry.get("proposal_id", ""))
        for entry in entries
        if entry.get("action") == "approve"
        and str(entry.get("by", "")).startswith("policy:")
        and entry.get("proposal_id")
    }
    reviewed = {
        str(entry.get("proposal_id", ""))
        for entry in entries
        if entry.get("action") == "post_review"
        and entry.get("verdict") in ("confirm", "flag")
        and entry.get("proposal_id")
    }
    return automatic, reviewed


def _automatic_route_reservation_ids(
    entries: Sequence[dict], day: str,
) -> set:
    """Replay the same route reservations used by ReviewStore's daily quota."""
    return {
        str(entry.get("proposal_id", ""))
        for entry in entries
        if str(entry.get("ts", ""))[:10] == day
        and entry.get("action") == "route"
        and entry.get("decision") == "auto_approve"
        and entry.get("proposal_id")
    }


def _callable_name(value: object) -> str:
    name = getattr(value, "__name__", "")
    return " ".join(name.split()) if isinstance(name, str) else ""


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
