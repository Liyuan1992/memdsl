"""Gated write pipeline: proposals, policy routing, approval, and audit.

Without an explicit policy, all proposed writes land in the human review
queue.  A policy may auto-approve only declarations that pass the immutable
safety floor in :mod:`memdsl.policy`; every write still traverses the normal
proposal and approval audit chain.  Proposals are stored as `.mem.proposal`
files (same declaration syntax, different extension so `Workspace.load`
never picks them up) under a staging directory, by default
`<workspace>/.memdsl/`:

    .memdsl/
      proposals/p-20260708-142530-a1b2c3.mem.proposal
      audit.log            # JSONL, append-only

Validation is fail-closed: a proposal must parse to exactly one
declaration and must survive a merged lint against the live workspace
(missing evidence, unresolved symbols, duplicate ids, and bad supersede
targets are all rejected before anything is staged).
"""

from __future__ import annotations

import datetime as _dt
import copy
import errno
import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, List, Mapping, Optional, Sequence

from memdsl.linter import lint
from memdsl.model import ReviewableSource, Workspace
from memdsl.parser import ParseError, parse_text
from memdsl.policy import (
    EvidenceVerification,
    PolicyError,
    ProposalContext,
    ReviewPolicy,
    RoutingAssessment,
    RoutingDecision,
    declaration_content_hash,
    requires_human_edge_review,
    verify_workspace_file_quote,
)
from memdsl.schema import RESERVED_EDGE_KINDS

PROPOSAL_SUFFIX = ".mem.proposal"
PROPOSAL_FILE_MARKER = "<proposal>"
PROPOSAL_STATUSES = ("pending", "approved", "rejected")

AUDIT_BASE_RESERVED = frozenset({"ts", "action", "proposal_id"})
APPROVE_AUDIT_RESERVED = AUDIT_BASE_RESERVED | frozenset({
    "by", "into", "declaration", "forced",
})
CORE_AUDIT_ACTIONS = frozenset({
    "propose", "route", "approve", "reject", "no_op", "route_fallback",
})
OPERATIONAL_AUDIT_ACTIONS = frozenset({"digest", "post_review"})
AUDIT_ACTIONS = CORE_AUDIT_ACTIONS | OPERATIONAL_AUDIT_ACTIONS
NO_POLICY_HASH = hashlib.sha256(b"memdsl:no-policy:v1").hexdigest()

EvidenceVerifier = Callable[
    [Optional[Mapping[str, object]], Sequence[str]],
    EvidenceVerification,
]

HEADER_END = "# ---"


class AuditLogError(ValueError):
    """Raised when strict audit reading encounters corruption."""

    def __init__(self, message: str, *, line: int = 0) -> None:
        self.line = line
        suffix = f" (line {line})" if line else ""
        super().__init__(message + suffix)


class ReviewLockTimeout(TimeoutError):
    """Raised when the cross-process review lock cannot be acquired in time."""

    def __init__(self, path: str, timeout_seconds: float) -> None:
        self.path = os.path.abspath(path)
        self.timeout_seconds = float(timeout_seconds)
        super().__init__(
            f"timed out after {self.timeout_seconds:.3f}s waiting for review "
            f"lock {self.path}")


@dataclass
class Proposal:
    id: str
    status: str
    created_at: str
    client: str
    reason: str
    source: str
    path: str
    decided_at: str = ""
    merged_into: str = ""
    reject_reason: str = ""
    routed: str = ""

    def summary(self) -> dict:
        head = ""
        try:
            doc = parse_text(self.source, file=PROPOSAL_FILE_MARKER)
            items = (
                list(doc.declarations)
                + list(doc.explicit_edges)
                + list(doc.edge_events)
            )
            if items:
                item = items[0]
                head = (
                    f"relation_edge:{item.name}"
                    if item.kind in {"relation_edge", "explicit_edge"}
                    else f"relation_edge_event:{item.name}"
                    if item.kind in {"relation_edge_event", "explicit_edge_event"}
                    else f"{item.kind}:{item.name}"
                )
        except ParseError:
            head = "(unparseable)"
        return {
            "id": self.id,
            "status": self.status,
            "declaration": head,
            "created_at": self.created_at,
            "client": self.client,
            "reason": self.reason,
            "decided_at": self.decided_at,
            "merged_into": self.merged_into,
            "reject_reason": self.reject_reason,
            "routed": self.routed,
        }


@dataclass
class ValidationResult:
    ok: bool
    errors: List[dict] = field(default_factory=list)
    warnings: List[dict] = field(default_factory=list)
    declaration_id: str = ""
    declaration: Optional[ReviewableSource] = field(default=None, repr=False)


def staging_dir_for(workspace_paths: Sequence[str], staging: Optional[str] = None) -> str:
    """Resolve the staging directory for a workspace.

    Explicit argument wins, then MEMDSL_STAGING, then `.memdsl/` next to
    (or inside) the first workspace path.
    """
    if staging:
        return os.path.abspath(staging)
    env = os.getenv("MEMDSL_STAGING", "")
    if env:
        return os.path.abspath(env)
    if not workspace_paths:
        raise ValueError("cannot derive a staging dir without workspace paths")
    first = os.path.abspath(str(workspace_paths[0]))
    base = first if os.path.isdir(first) else os.path.dirname(first)
    return os.path.join(base, ".memdsl")


class ReviewStore:
    """File-backed proposal queue with an append-only audit log."""

    def __init__(self, staging_dir: str) -> None:
        self.staging_dir = os.path.abspath(staging_dir)
        self.proposals_dir = os.path.join(self.staging_dir, "proposals")
        self.audit_path = os.path.join(self.staging_dir, "audit.log")
        self.lock_path = os.path.join(self.staging_dir, "review.lock")

    def _validate_automatic_target(
        self, target_path: str, workspace_paths: Sequence[str] = (),
    ) -> None:
        target = os.path.abspath(target_path)
        target_real = os.path.realpath(target)
        paths = _normalized_workspace_paths(workspace_paths)
        if paths:
            first = paths[0]
            root = first if os.path.isdir(first) else os.path.dirname(first)
            root_real = os.path.realpath(root)
            try:
                contained = os.path.commonpath(
                    [target_real, root_real]) == root_real
            except ValueError:
                contained = False
            if not contained:
                raise PolicyError(
                    "auto_merge_into resolves outside the workspace root")
            relative_parts = os.path.relpath(
                target, os.path.abspath(root)).replace("\\", "/").split("/")
            if any(part.lower() == ".memdsl" for part in relative_parts):
                raise PolicyError(
                    "auto_merge_into must not target a .memdsl internal directory")
        staging_real = os.path.realpath(self.staging_dir)
        try:
            inside_staging = os.path.commonpath(
                [target_real, staging_real]) == staging_real
        except ValueError:
            inside_staging = False
        if inside_staging:
            raise PolicyError(
                "auto_merge_into must not target memdsl staging or internal state")
        if os.path.isdir(target):
            raise PolicyError("auto_merge_into resolves to an existing directory")
        if os.path.lexists(target) and os.path.islink(target):
            raise PolicyError("auto_merge_into must not be a symbolic link")

    def validate_policy_target(
        self, policy: ReviewPolicy, workspace_paths: Sequence[str],
    ) -> str:
        """Resolve and validate a policy target against workspace + staging."""
        if not isinstance(policy, ReviewPolicy):
            raise TypeError("policy must be ReviewPolicy")
        paths = _normalized_workspace_paths(workspace_paths)
        target = policy.resolve_auto_merge_into(paths)
        self._validate_automatic_target(target, paths)
        return target

    # ---- validation ----

    def validate(self, ws: Workspace, source: str) -> ValidationResult:
        """Fail-closed check of one proposed declaration against a workspace."""
        text = str(source or "").strip()
        if not text:
            return ValidationResult(False, errors=[_diag("empty_proposal", "proposal source is empty")])
        try:
            doc = parse_text(text, file=PROPOSAL_FILE_MARKER)
        except ParseError as exc:
            return ValidationResult(False, errors=[_diag("parse_error", str(exc))])
        source_items = (
            list(doc.declarations)
            + list(doc.explicit_edges)
            + list(doc.edge_events)
        )
        if len(source_items) != 1:
            return ValidationResult(False, errors=[_diag(
                "single_declaration_required",
                f"a proposal must contain exactly one declaration or explicit Edge "
                f"item, got {len(source_items)}",
            )])

        merged = Workspace(
            declarations=list(ws.declarations),
            explicit_edges=list(ws.explicit_edges),
            edge_events=list(ws.edge_events),
            files=list(ws.files),
            registry=ws.registry,
            documents=list(ws.documents),
            schema_version=ws.schema_version,
            linking_visibility=ws.linking_visibility,
            enforcement_mode=ws.enforcement_mode,
            explicit_edges_enabled=ws.explicit_edges_enabled,
        )
        merged.add_document(doc)
        item = (
            merged.declarations[-1]
            if doc.declarations else
            merged.explicit_edges[-1]
            if doc.explicit_edges else
            merged.edge_events[-1]
        )

        errors: List[dict] = []
        warnings: List[dict] = []
        for d in lint(merged):
            if d.file != PROPOSAL_FILE_MARKER:
                continue  # pre-existing workspace diagnostics are not the proposal's fault
            entry = {"code": d.code, "severity": d.severity, "message": d.message, "line": d.line}
            (errors if d.severity == "error" else warnings).append(entry)
        return ValidationResult(
            not errors,
            errors=errors,
            warnings=warnings,
            declaration_id=item.id,
            declaration=item,
        )

    def validate_for_target(
        self, ws: Workspace, source: str, target_path: str,
    ) -> ValidationResult:
        """Re-parse an Edge proposal in its final dedicated file context."""
        preliminary = self.validate(ws, source)
        if not preliminary.ok or preliminary.declaration is None:
            return preliminary
        if preliminary.declaration.kind not in RESERVED_EDGE_KINDS:
            return ValidationResult(False, errors=[_diag(
                "edge_target_context_requires_edge",
                "target-context approval is reserved for explicit Edge items",
            )])
        basename = os.path.basename(os.path.abspath(target_path)).lower()
        if basename != "edges.mem" and not basename.endswith(".edges.mem"):
            return ValidationResult(False, errors=[_diag(
                "dedicated_edge_file_required",
                "explicit Edge approval target must be edges.mem or *.edges.mem",
            )])
        current = _read_text(target_path)
        combined = current.rstrip("\n")
        if combined:
            combined += "\n"
        combined += str(source).strip() + "\n"
        try:
            document = parse_text(combined, file=os.path.abspath(target_path))
        except ParseError as exc:
            return ValidationResult(False, errors=[_diag("parse_error", str(exc))])
        if document.declarations:
            return ValidationResult(False, errors=[_diag(
                "edge_target_not_dedicated",
                "dedicated Edge files may contain module/use plus explicit Edge "
                "records/events, not ordinary declarations",
            )])
        merged = Workspace(
            declarations=[item for item in ws.declarations
                          if os.path.abspath(item.file) != os.path.abspath(target_path)],
            explicit_edges=[item for item in ws.explicit_edges
                            if os.path.abspath(item.file) != os.path.abspath(target_path)],
            edge_events=[item for item in ws.edge_events
                         if os.path.abspath(item.file) != os.path.abspath(target_path)],
            files=[path for path in ws.files
                   if os.path.abspath(path) != os.path.abspath(target_path)],
            registry=ws.registry,
            documents=[item for item in ws.documents
                       if os.path.abspath(item.file) != os.path.abspath(target_path)],
            schema_version=ws.schema_version,
            linking_visibility=ws.linking_visibility,
            enforcement_mode=ws.enforcement_mode,
            explicit_edges_enabled=ws.explicit_edges_enabled,
        )
        merged.add_document(document)
        item = (
            merged.explicit_edges[-1]
            if preliminary.declaration.kind == "relation_edge"
            else merged.edge_events[-1]
        )
        errors: List[dict] = []
        warnings: List[dict] = []
        for diagnostic in lint(merged):
            if os.path.abspath(diagnostic.file) != os.path.abspath(target_path):
                continue
            entry = {
                "code": diagnostic.code,
                "severity": diagnostic.severity,
                "message": diagnostic.message,
                "line": diagnostic.line,
            }
            (errors if diagnostic.severity == "error" else warnings).append(entry)
        return ValidationResult(
            not errors,
            errors=errors,
            warnings=warnings,
            declaration_id=item.id,
            declaration=item,
        )

    # ---- queue operations ----

    def create(self, ws: Workspace, source: str, *, reason: str = "",
               client: str = "") -> dict:
        result = self.validate(ws, source)
        if not result.ok:
            return {
                "ok": False,
                "status": "invalid",
                "errors": result.errors,
                "warnings": result.warnings,
            }
        with _exclusive_file_lock(self.lock_path):
            return self._stage_validated_locked(
                result, source, reason=reason, client=client,
                strict_audit=False)

    def submit(
        self,
        workspace_or_paths,
        source: str,
        *,
        reason: str = "",
        client: str = "",
        policy: Optional[ReviewPolicy] = None,
        context: Optional[ProposalContext] = None,
        workspace_paths: Sequence[str] = (),
        blocking_reasons: Sequence[str] = (),
        write_auto_granted: Optional[bool] = None,
        evidence_verifier: Optional[EvidenceVerifier] = verify_workspace_file_quote,
    ) -> dict:
        """Validate, stage, assess, and optionally approve one proposal.

        Paths passed as the first argument are authoritative; accepting a
        preloaded Workspace plus ``workspace_paths=`` is a compatibility
        overload.  Every valid submission is persisted with ``propose`` and
        ``route`` events.  Missing policy routes to human review.  Automatic
        approval reloads and fingerprints the authoritative paths inside the
        approval lock and never uses ``force``.
        """
        if isinstance(workspace_or_paths, Workspace):
            authoritative_paths = _normalized_workspace_paths(workspace_paths)
            ws = (
                Workspace.load(authoritative_paths)
                if authoritative_paths else workspace_or_paths)
        else:
            if workspace_paths:
                raise TypeError(
                    "workspace_paths must not be supplied twice; pass paths as "
                    "the first argument")
            authoritative_paths = _normalized_workspace_paths(workspace_or_paths)
            ws = Workspace.load(authoritative_paths)

        if policy is None:
            return self._submit_without_policy(
                ws,
                source,
                reason=reason,
                client=client,
                workspace_paths=authoritative_paths,
                write_auto_granted=bool(write_auto_granted),
            )
        if not isinstance(policy, ReviewPolicy):
            raise TypeError("policy must be ReviewPolicy or None")
        if context is not None and not isinstance(context, ProposalContext):
            raise TypeError("context must be ProposalContext or None")
        if evidence_verifier is not None and not callable(evidence_verifier):
            raise TypeError("evidence_verifier must be callable or None")
        deployment_blockers = _validated_reason_codes(blocking_reasons)
        if write_auto_granted is not None and not isinstance(write_auto_granted, bool):
            raise TypeError("write_auto_granted must be a boolean or None")
        effective_write_auto = (
            write_auto_granted
            if write_auto_granted is not None
            else False
        )
        if not effective_write_auto and "write_auto_not_granted" not in deployment_blockers:
            deployment_blockers.append("write_auto_not_granted")

        # A damaged ledger cannot safely answer duplicate, quota, or prior
        # decision questions.  Explicit policy use therefore fails before any
        # state mutation; legacy create() remains tolerant for compatibility.
        self.audit_entries(strict=True)

        # A configured rule naming a type that does not exist is a hard policy
        # error, not a quiet queue fallback.
        current_fingerprint = ""
        if authoritative_paths:
            current_fingerprint = workspace_fingerprint(
                authoritative_paths, workspace=ws)
        policy.validate_registry(ws.registry)
        target_path: Optional[str] = None
        target_error = ""
        if authoritative_paths:
            # This also performs lexical + real-path containment checks.
            target_path = self.validate_policy_target(
                policy, authoritative_paths)
        else:
            target_error = "workspace_paths_required"

        parsed = _declaration_for_source(ws, source)
        effective_context = context
        if (parsed is not None and effective_context is not None
                and effective_context.evidence_verification is None
                and authoritative_paths):
            effective_context = effective_context.with_evidence(
                _invoke_evidence_verifier(
                    evidence_verifier, parsed.evidence, authoritative_paths))
        effective_client = (
            effective_context.client_id
            if effective_context is not None else _one_line(client))

        # Idempotent retries of an already pending/approved declaration do not
        # create another proposal.  Rejected content may be proposed again.
        if parsed is not None:
            content_hash = declaration_content_hash(parsed)
            with _exclusive_file_lock(self.lock_path):
                duplicate = self._exact_duplicate_locked(ws, content_hash)
                if duplicate is not None:
                    return self._handle_policy_duplicate_locked(
                        duplicate,
                        parsed,
                        policy=policy,
                        context=effective_context,
                        client=(
                            effective_context.client_id
                            if effective_context is not None else ""),
                        reason=reason,
                    )

        initial = self.validate(ws, source)
        if not initial.ok:
            return {
                "ok": False,
                "status": "invalid",
                "errors": initial.errors,
                "warnings": initial.warnings,
            }
        assert initial.declaration is not None
        content_hash = declaration_content_hash(initial.declaration)
        with _exclusive_file_lock(self.lock_path):
            duplicate = self._exact_duplicate_locked(ws, content_hash)
            if duplicate is not None:
                return self._handle_policy_duplicate_locked(
                    duplicate,
                    initial.declaration,
                    policy=policy,
                    context=effective_context,
                    client=(
                        effective_context.client_id
                        if effective_context is not None else ""),
                    reason=reason,
                )
            created = self._stage_validated_locked(
                initial, source, reason=reason, client=effective_client,
                strict_audit=True)

        runtime_blockers: List[str] = []
        if target_error:
            runtime_blockers.append(target_error)
        current_ws = ws
        current = initial

        route_decl = current.declaration or initial.declaration
        with _exclusive_file_lock(self.lock_path):
            automatic_today = self._automatic_routes_today(_utc_date())
            eligible = policy.assess(
                route_decl,
                warnings_count=len(current.warnings),
                context=effective_context,
                auto_approved_today=automatic_today,
                blocking_reasons=runtime_blockers,
                workspace_fingerprint=current_fingerprint,
                write_auto_granted=effective_write_auto,
            )
            assessment = policy.assess(
                route_decl,
                warnings_count=len(current.warnings),
                context=effective_context,
                auto_approved_today=automatic_today,
                blocking_reasons=runtime_blockers + deployment_blockers,
                workspace_fingerprint=current_fingerprint,
                write_auto_granted=effective_write_auto,
            )
            self._record_route_locked(
                created["proposal_id"], assessment, eligible=eligible)

        if assessment.decision is RoutingDecision.QUEUE:
            return _queued_submit_result(created, assessment, eligible=eligible)

        assert authoritative_paths and target_path is not None
        approval = self.approve(
            created["proposal_id"],
            current_ws,
            target_path,
            force=False,
            by=f"policy:{assessment.rule}@{policy.source_hash}",
            workspace_paths=authoritative_paths,
            expected_fingerprint=current_fingerprint,
            automatic_daily_limit=policy.max_auto_approve_per_day,
            expected_evidence_verification=(
                effective_context.evidence_verification
                if effective_context is not None else None),
            evidence_verifier=evidence_verifier,
            audit_extra={
                "policy_hash": policy.source_hash,
                "policy_version": policy.version,
                "routing_rule": assessment.rule,
                "routing_reason_codes": list(assessment.reason_codes),
                "routing_input": assessment.input_snapshot,
                "content_hash": assessment.content_hash,
                "assessment_hash": assessment.assessment_hash,
                "tier": assessment.tier,
                "workspace_fingerprint": current_fingerprint,
                "write_auto_granted": effective_write_auto,
            },
        )
        if not approval.get("ok"):
            return self._route_fallback(
                created,
                assessment,
                f"approve_failed:{approval.get('status', 'unknown')}",
                eligible=eligible,
                approval=approval,
            )
        return {
            **approval,
            "status": "auto_approved",
            "route": "auto_approved",
            "decision": assessment.decision.value,
            "rule": assessment.rule,
            "tier": assessment.tier,
            "reason_codes": list(assessment.reason_codes),
            "policy_hash": assessment.policy_hash,
            "content_hash": assessment.content_hash,
            "assessment_hash": assessment.assessment_hash,
            "assessment": assessment.as_dict(),
            "eligible_route": eligible.decision.value,
            "eligible_rule": eligible.rule,
            "eligible_reason_codes": list(eligible.reason_codes),
            "eligible_assessment_hash": eligible.assessment_hash,
        }

    def _submit_without_policy(
        self,
        ws: Workspace,
        source: str,
        *,
        reason: str,
        client: str,
        workspace_paths: Sequence[str],
        write_auto_granted: bool,
    ) -> dict:
        self.audit_entries(strict=True)
        parsed = _declaration_for_source(ws, source)
        if parsed is not None:
            content_hash = declaration_content_hash(parsed)
            with _exclusive_file_lock(self.lock_path):
                duplicate = self._exact_duplicate_locked(ws, content_hash)
                if duplicate is not None:
                    return self._record_no_policy_duplicate_locked(
                        duplicate,
                        parsed,
                        client=client,
                        reason=reason,
                        workspace_paths=workspace_paths,
                        workspace=ws,
                        write_auto_granted=write_auto_granted,
                    )
        result = self.validate(ws, source)
        if not result.ok:
            return {
                "ok": False,
                "status": "invalid",
                "errors": result.errors,
                "warnings": result.warnings,
            }
        assert result.declaration is not None
        with _exclusive_file_lock(self.lock_path):
            duplicate = self._exact_duplicate_locked(
                ws, declaration_content_hash(result.declaration))
            if duplicate is not None:
                return self._record_no_policy_duplicate_locked(
                    duplicate,
                    result.declaration,
                    client=client,
                    reason=reason,
                    workspace_paths=workspace_paths,
                    workspace=ws,
                    write_auto_granted=write_auto_granted,
                )
            created = self._stage_validated_locked(
                result,
                source,
                reason=reason,
                client=client,
                strict_audit=True,
            )
            assessment = _no_policy_assessment(
                result.declaration,
                warnings_count=len(result.warnings),
                workspace_paths=workspace_paths,
                workspace=ws,
                write_auto_granted=write_auto_granted,
            )
            self._record_route_locked(
                created["proposal_id"], assessment, eligible=assessment)
        return _queued_submit_result(created, assessment, eligible=assessment)

    def _record_no_policy_duplicate_locked(
        self,
        duplicate: Mapping[str, object],
        declaration: ReviewableSource,
        *,
        client: str,
        reason: str,
        workspace_paths: Sequence[str],
        workspace: Workspace,
        write_auto_granted: bool,
    ) -> dict:
        base = _no_policy_assessment(
            declaration,
            warnings_count=0,
            workspace_paths=workspace_paths,
            workspace=workspace,
            write_auto_granted=write_auto_granted,
        )
        assessment = RoutingAssessment(
            decision=RoutingDecision.NO_OP,
            rule="duplicate",
            reason_codes=("exact_duplicate",),
            policy_hash=NO_POLICY_HASH,
            content_hash=base.content_hash,
            input_snapshot=base.input_snapshot,
        )
        return self._write_duplicate_audit_locked(
            duplicate,
            declaration,
            assessment=assessment,
            client=client,
            reason=reason,
        )

    def _stage_validated_locked(
        self,
        result: ValidationResult,
        source: str,
        *,
        reason: str,
        client: str,
        strict_audit: bool,
    ) -> dict:
        proposal = Proposal(
            id=_new_id(),
            status="pending",
            created_at=_now_iso(),
            client=_one_line(client),
            reason=_one_line(reason),
            source=str(source).strip() + "\n",
            path="",
        )
        os.makedirs(self.proposals_dir, exist_ok=True)
        proposal.path = os.path.join(
            self.proposals_dir, proposal.id + PROPOSAL_SUFFIX)
        _write_proposal(proposal)
        self._audit_once(
            "propose", proposal.id, client=proposal.client,
            declaration=result.declaration_id, reason=proposal.reason,
            strict=strict_audit)
        return {
            "ok": True,
            "status": "pending_review",
            "proposal_id": proposal.id,
            "declaration_id": result.declaration_id,
            "path": proposal.path,
            "warnings": result.warnings,
        }

    def _exact_duplicate_locked(
        self, ws: Workspace, content_hash: str,
    ) -> Optional[dict]:
        workspace_has_content = any(
            declaration_content_hash(declaration) == content_hash
            for declaration in ws.reviewable_sources())
        for proposal in self.list(status="all"):
            if proposal.status not in ("pending", "approved"):
                continue
            declaration = _declaration_for_source(ws, proposal.source)
            if (declaration is not None
                    and declaration_content_hash(declaration) == content_hash):
                if proposal.status == "approved" and not workspace_has_content:
                    continue
                return {
                    "proposal_id": proposal.id,
                    "duplicate_of": proposal.id,
                    "existing_status": proposal.status,
                    "path": proposal.path,
                    **self._proposal_route_state(proposal.id),
                }
        # A declaration may have been written directly or imported before the
        # review store existed.  Exact normalized content is still an
        # idempotent no-op, even though there is no proposal file to reference.
        for declaration in ws.reviewable_sources():
            if declaration_content_hash(declaration) == content_hash:
                return {
                    "proposal_id": "",
                    "duplicate_of": declaration.id,
                    "existing_status": "workspace",
                    "path": declaration.file,
                }
        return None

    def _proposal_route_state(self, proposal_id: str) -> dict:
        route: Optional[dict] = None
        fallback_after_route = False
        for entry in self._audit_entries(strict=True):
            if entry.get("proposal_id") != proposal_id:
                continue
            if entry.get("action") == "route":
                route = entry
                fallback_after_route = False
            elif entry.get("action") == "route_fallback" and route is not None:
                fallback_after_route = True
        if route is None:
            return {}
        return {
            "routed_decision": str(route.get("decision", "")),
            "routed_rule": str(route.get("rule", "")),
            "routed_policy_hash": str(route.get("policy_hash", "")),
            "routed_content_hash": str(route.get("content_hash", "")),
            "routed_assessment_hash": str(route.get("assessment_hash", "")),
            "routed_eligible_assessment_hash": str(
                route.get("eligible_assessment_hash", "")),
            "route_fallback_recorded": fallback_after_route,
        }

    def _handle_policy_duplicate_locked(
        self,
        duplicate: Mapping[str, object],
        declaration: ReviewableSource,
        *,
        policy: ReviewPolicy,
        context: Optional[ProposalContext],
        client: str,
        reason: str,
    ) -> dict:
        if (duplicate.get("existing_status") == "pending"
                and duplicate.get("routed_decision")
                == RoutingDecision.AUTO_APPROVE.value
                and not duplicate.get("route_fallback_recorded")):
            return self._downgrade_routed_duplicate_locked(
                duplicate, declaration, policy=policy)
        return self._record_duplicate_locked(
            duplicate,
            declaration,
            policy=policy,
            context=context,
            client=client,
            reason=reason,
        )

    def _downgrade_routed_duplicate_locked(
        self,
        duplicate: Mapping[str, object],
        declaration: ReviewableSource,
        *,
        policy: ReviewPolicy,
    ) -> dict:
        proposal_id = str(duplicate.get("proposal_id", ""))
        original_rule = str(duplicate.get("routed_rule", "")) or "unknown"
        policy_hash = (
            str(duplicate.get("routed_policy_hash", "")) or policy.source_hash)
        content_hash = (
            str(duplicate.get("routed_content_hash", ""))
            or declaration_content_hash(declaration))
        assessment_hash = str(
            duplicate.get("routed_assessment_hash", ""))
        eligible_hash = str(
            duplicate.get("routed_eligible_assessment_hash", ""))
        proposal = self.get(proposal_id)
        if proposal is not None:
            proposal.routed = f"queue:fallback:{original_rule}"
            _write_proposal(proposal)
        self._audit_once(
            "route_fallback",
            proposal_id,
            policy_hash=policy_hash,
            original_rule=original_rule,
            reason_codes=["retry_after_routed_auto_approve"],
            content_hash=content_hash,
            assessment_hash=assessment_hash,
            eligible_assessment_hash=eligible_hash or assessment_hash,
            strict=True,
        )
        return {
            "ok": True,
            "status": "pending_review",
            "route": "queued",
            "decision": RoutingDecision.QUEUE.value,
            "proposal_id": proposal_id,
            "duplicate_of": str(duplicate.get("duplicate_of", proposal_id)),
            "existing_status": "pending",
            "declaration_id": declaration.id,
            "path": str(duplicate.get("path", "")),
            "warnings": [],
            "rule": f"fallback:{original_rule}",
            "route_rule": f"fallback:{original_rule}",
            "reason_codes": ["retry_after_routed_auto_approve"],
            "policy_hash": policy_hash,
            "content_hash": content_hash,
            "assessment_hash": assessment_hash,
            "eligible_route": RoutingDecision.AUTO_APPROVE.value,
            "eligible_rule": original_rule,
            "eligible_reason_codes": ["routed_before_interruption"],
            "eligible_assessment_hash": eligible_hash or assessment_hash,
            "recovered": False,
        }

    def _record_duplicate_locked(
        self,
        duplicate: Mapping[str, object],
        declaration: ReviewableSource,
        *,
        policy: ReviewPolicy,
        context: Optional[ProposalContext],
        client: str,
        reason: str,
    ) -> dict:
        base = policy.assess(
            declaration,
            warnings_count=0,
            context=context,
            auto_approved_today=self._automatic_routes_today(_utc_date()),
        )
        assessment = RoutingAssessment(
            decision=RoutingDecision.NO_OP,
            rule="duplicate",
            reason_codes=("exact_duplicate",),
            policy_hash=policy.source_hash,
            content_hash=base.content_hash,
            input_snapshot=base.input_snapshot,
        )
        return self._write_duplicate_audit_locked(
            duplicate,
            declaration,
            assessment=assessment,
            client=client,
            reason=reason,
        )

    def _write_duplicate_audit_locked(
        self,
        duplicate: Mapping[str, object],
        declaration: ReviewableSource,
        *,
        assessment: RoutingAssessment,
        client: str,
        reason: str,
    ) -> dict:
        proposal_id = str(duplicate.get("proposal_id", ""))
        duplicate_of = str(duplicate.get("duplicate_of", ""))
        existing_status = str(duplicate.get("existing_status", ""))
        attempt_id = f"a-{uuid.uuid4().hex}"
        self._audit(
            "no_op",
            proposal_id,
            attempt_id=attempt_id,
            duplicate_of=duplicate_of,
            existing_status=existing_status,
            declaration=declaration.id,
            client=_one_line(client),
            reason=_one_line(reason),
            policy_hash=assessment.policy_hash,
            rule=assessment.rule,
            reason_codes=list(assessment.reason_codes),
            input_snapshot=assessment.input_snapshot,
            content_hash=assessment.content_hash,
            assessment_hash=assessment.assessment_hash,
            assessment=assessment.as_dict(),
        )
        return {
            "ok": True,
            "status": "no_op",
            "route": "no_op",
            "decision": RoutingDecision.NO_OP.value,
            "proposal_id": proposal_id,
            "attempt_id": attempt_id,
            "duplicate_of": duplicate_of,
            "existing_status": existing_status,
            "declaration_id": declaration.id,
            "path": str(duplicate.get("path", "")),
            "warnings": [],
            "rule": assessment.rule,
            "reason_codes": list(assessment.reason_codes),
            "policy_hash": assessment.policy_hash,
            "content_hash": assessment.content_hash,
            "assessment_hash": assessment.assessment_hash,
            "assessment": assessment.as_dict(),
            "eligible_route": RoutingDecision.NO_OP.value,
            "eligible_rule": assessment.rule,
            "eligible_reason_codes": list(assessment.reason_codes),
            "eligible_assessment_hash": assessment.assessment_hash,
        }

    def _record_route_locked(
        self,
        proposal_id: str,
        assessment: RoutingAssessment,
        *,
        eligible: RoutingAssessment,
    ) -> None:
        proposal = self.get(proposal_id)
        if proposal is not None:
            proposal.routed = f"{assessment.decision.value}:{assessment.rule}"
            _write_proposal(proposal)
        self._audit_once(
            "route",
            proposal_id,
            policy_hash=assessment.policy_hash,
            decision=assessment.decision.value,
            rule=assessment.rule,
            reason_codes=list(assessment.reason_codes),
            input_snapshot=assessment.input_snapshot,
            content_hash=assessment.content_hash,
            assessment_hash=assessment.assessment_hash,
            tier=assessment.tier,
            sample_bucket=assessment.sample_bucket,
            assessment=assessment.as_dict(),
            eligible_route=eligible.decision.value,
            eligible_rule=eligible.rule,
            eligible_reason_codes=list(eligible.reason_codes),
            eligible_assessment_hash=eligible.assessment_hash,
            eligible_assessment=eligible.as_dict(),
            workspace_fingerprint=assessment.input_snapshot.get(
                "workspace", {}).get("fingerprint", ""),
            write_auto_granted=assessment.input_snapshot.get(
                "deployment", {}).get("write_auto_granted"),
            strict=True,
        )

    def _route_fallback(
        self,
        created: Mapping[str, object],
        assessment: RoutingAssessment,
        reason_code: str,
        *,
        eligible: RoutingAssessment,
        approval: Optional[Mapping[str, object]] = None,
    ) -> dict:
        proposal_id = str(created["proposal_id"])
        with _exclusive_file_lock(self.lock_path):
            proposal = self.get(proposal_id)
            if proposal is not None:
                proposal.routed = f"queue:fallback:{assessment.rule}"
                _write_proposal(proposal)
            self._audit_once(
                "route_fallback",
                proposal_id,
                policy_hash=assessment.policy_hash,
                original_rule=assessment.rule,
                reason_codes=[reason_code],
                content_hash=assessment.content_hash,
                assessment_hash=assessment.assessment_hash,
                eligible_assessment_hash=eligible.assessment_hash,
                strict=True,
            )
        payload = dict(created)
        payload.update({
            "status": "pending_review",
            "route": "queued",
            "decision": RoutingDecision.QUEUE.value,
            "route_rule": f"fallback:{assessment.rule}",
            "rule": f"fallback:{assessment.rule}",
            "reason_codes": [reason_code],
            "policy_hash": assessment.policy_hash,
            "content_hash": assessment.content_hash,
            "assessment_hash": assessment.assessment_hash,
            "assessment": assessment.as_dict(),
            "eligible_route": eligible.decision.value,
            "eligible_rule": eligible.rule,
            "eligible_reason_codes": list(eligible.reason_codes),
            "eligible_assessment_hash": eligible.assessment_hash,
        })
        if approval is not None:
            payload["approval_error"] = copy.deepcopy(dict(approval))
        return payload

    def list(self, status: str = "pending") -> List[Proposal]:
        if not os.path.isdir(self.proposals_dir):
            return []
        out: List[Proposal] = []
        for name in sorted(os.listdir(self.proposals_dir)):
            if not name.endswith(PROPOSAL_SUFFIX):
                continue
            proposal = _read_proposal(os.path.join(self.proposals_dir, name))
            if proposal is None:
                continue
            if status != "all" and proposal.status != status:
                continue
            out.append(proposal)
        return out

    def get(self, proposal_id: str) -> Optional[Proposal]:
        ref = str(proposal_id or "").strip()
        if not ref:
            return None
        path = os.path.join(self.proposals_dir, ref + PROPOSAL_SUFFIX)
        if os.path.isfile(path):
            return _read_proposal(path)
        return None

    def approve(
        self,
        proposal_id: str,
        ws: Workspace,
        into: str,
        *,
        force: bool = False,
        by: str = "human",
        audit_extra: Optional[Mapping[str, object]] = None,
        workspace_paths: Sequence[str] = (),
        expected_fingerprint: str = "",
        automatic_daily_limit: Optional[int] = None,
        expected_evidence_verification: Optional[EvidenceVerification] = None,
        evidence_verifier: Optional[EvidenceVerifier] = verify_workspace_file_quote,
        target_context: bool = False,
    ) -> dict:
        extra = _validated_audit_extra(
            audit_extra, reserved=APPROVE_AUDIT_RESERVED)
        fresh_paths = _normalized_workspace_paths(workspace_paths)
        if expected_fingerprint:
            if (not isinstance(expected_fingerprint, str)
                    or len(expected_fingerprint) != 64
                    or any(c not in "0123456789abcdef" for c in expected_fingerprint)):
                raise ValueError(
                    "expected_fingerprint must be a full lowercase SHA-256 digest")
            if not fresh_paths:
                raise ValueError(
                    "workspace_paths are required with expected_fingerprint")
        if automatic_daily_limit is not None:
            if (not isinstance(automatic_daily_limit, int)
                    or isinstance(automatic_daily_limit, bool)
                    or automatic_daily_limit < 0):
                raise ValueError(
                    "automatic_daily_limit must be a non-negative integer or None")
            if not expected_fingerprint:
                raise ValueError(
                    "automatic_daily_limit is only valid for fingerprinted approval")
        if (expected_evidence_verification is not None
                and not expected_fingerprint):
            raise ValueError(
                "expected evidence verification requires fingerprinted approval")
        if (expected_evidence_verification is not None
                and not isinstance(
                    expected_evidence_verification, EvidenceVerification)):
            raise TypeError(
                "expected_evidence_verification must be EvidenceVerification")
        if evidence_verifier is not None and not callable(evidence_verifier):
            raise TypeError("evidence_verifier must be callable or None")
        if not isinstance(target_context, bool):
            raise TypeError("target_context must be a boolean")
        into_path = os.path.abspath(into)
        with _exclusive_file_lock(self.lock_path):
            proposal = self.get(proposal_id)
            if proposal is None:
                return {"ok": False, "status": "not_found", "proposal_id": proposal_id}
            if proposal.status != "pending":
                return {"ok": False, "status": f"already_{proposal.status}",
                        "proposal_id": proposal.id}
            proposed_item = _declaration_for_source(ws, proposal.source)
            if (
                proposed_item is not None
                and proposed_item.kind in RESERVED_EDGE_KINDS
                and not target_context
            ):
                return {
                    "ok": False,
                    "status": "edge_target_context_required",
                    "proposal_id": proposal.id,
                    "hint": (
                        "use the explicit Edge confirmation API/CLI so the "
                        "proposal is recompiled in edges.mem or *.edges.mem"),
                }

            prior = self._decision(proposal.id)
            if prior and prior.get("action") == "reject":
                proposal.status = "rejected"
                proposal.decided_at = str(prior.get("ts", ""))
                proposal.reject_reason = str(prior.get("reason", ""))
                _write_proposal(proposal)
                return {"ok": False, "status": "already_rejected",
                        "proposal_id": proposal.id}
            if prior and prior.get("action") == "approve" and prior.get("into"):
                # Recovery must finish the original target, even if a retry
                # accidentally supplies a different --into path.
                into_path = os.path.abspath(str(prior["into"]))

            if expected_fingerprint:
                try:
                    self._validate_automatic_target(into_path, fresh_paths)
                except PolicyError as exc:
                    return {
                        "ok": False,
                        "status": "invalid_auto_merge_target",
                        "proposal_id": proposal.id,
                        "error": str(exc),
                    }
                if (automatic_daily_limit is not None
                        and self._automatic_routes_today(_utc_date())
                        > automatic_daily_limit):
                    return {
                        "ok": False,
                        "status": "daily_limit_reached",
                        "proposal_id": proposal.id,
                    }

            current = _read_text(into_path)
            proposed_declaration = _declaration_for_source(ws, proposal.source)
            proposed_hash = (
                declaration_content_hash(proposed_declaration)
                if proposed_declaration is not None else "")
            marker_lines = _approval_marker_lines(current, proposal.id)
            marker_present = bool(marker_lines)
            content_present = (
                marker_present
                and _target_contains_exact_declaration(
                    current, proposal.source, ws.registry))
            marker_valid = (
                marker_present
                and _approval_marker_valid(marker_lines, proposed_hash))
            if marker_present and not (content_present and marker_valid):
                return {
                    "ok": False,
                    "status": "target_marker_mismatch",
                    "proposal_id": proposal.id,
                }
            already_merged = marker_present and content_present and marker_valid

            if expected_fingerprint and not already_merged:
                try:
                    fresh_ws = Workspace.load(fresh_paths)
                    actual_fingerprint = workspace_fingerprint(
                        fresh_paths, workspace=fresh_ws)
                except Exception as exc:
                    return {
                        "ok": False,
                        "status": "workspace_reload_failed",
                        "proposal_id": proposal.id,
                        "error": str(exc),
                    }
                if actual_fingerprint != expected_fingerprint:
                    return {
                        "ok": False,
                        "status": "workspace_changed",
                        "proposal_id": proposal.id,
                        "expected_fingerprint": expected_fingerprint,
                        "actual_fingerprint": actual_fingerprint,
                    }
                ws = fresh_ws
                if expected_evidence_verification is not None:
                    fresh_declaration = _declaration_for_source(
                        fresh_ws, proposal.source)
                    if evidence_verifier is None:
                        return {
                            "ok": False,
                            "status": "evidence_reverification_unavailable",
                            "proposal_id": proposal.id,
                        }
                    fresh_proof = _invoke_evidence_verifier(
                        evidence_verifier,
                        fresh_declaration.evidence if fresh_declaration else None,
                        fresh_paths,
                    )
                    expected = expected_evidence_verification
                    if not _evidence_verification_matches(expected, fresh_proof):
                        return {
                            "ok": False,
                            "status": "evidence_changed",
                            "proposal_id": proposal.id,
                            "reason": fresh_proof.reason,
                        }

            # A prior process may have atomically replaced the target and
            # crashed before persisting proposal status.  The source marker
            # makes the operation idempotent and lets us finish the decision.
            if already_merged:
                declaration_id = _declaration_id(proposal.source)
                warnings: List[dict] = []
                forced = False
                stamp = str((prior or {}).get("ts") or _now_iso())
            else:
                # Re-validate against the *current* workspace: it may have
                # changed since the proposal was staged.
                result = (
                    self.validate_for_target(ws, proposal.source, into_path)
                    if target_context else
                    self.validate(ws, proposal.source)
                )
                if not result.ok and not force:
                    return {
                        "ok": False,
                        "status": "stale_or_invalid",
                        "proposal_id": proposal.id,
                        "errors": result.errors,
                        "warnings": result.warnings,
                        "hint": "fix the workspace or re-propose; --force overrides",
                    }
                declaration_id = result.declaration_id
                warnings = result.warnings
                forced = bool(force and not result.ok)
                stamp = _now_iso()
                block = (
                    f"\n# approved from proposal {proposal.id} "
                    f"content {proposed_hash} at {stamp}\n"
                    + proposal.source.rstrip("\n") + "\n"
                )
                os.makedirs(os.path.dirname(into_path) or ".", exist_ok=True)
                _atomic_write(into_path, current + block)

            # Commit order is target -> audit -> proposal state.  Every stage
            # is idempotent, so a retry completes an interrupted approval
            # without duplicating source or audit records.
            self._audit_once(
                "approve", proposal.id, by=by, into=into_path,
                declaration=declaration_id, forced=forced, strict=True, **extra)
            proposal.status = "approved"
            proposal.decided_at = stamp
            proposal.merged_into = into_path
            _write_proposal(proposal)
            return {
                "ok": True,
                "status": "approved",
                "proposal_id": proposal.id,
                "declaration_id": declaration_id,
                "merged_into": into_path,
                "warnings": warnings,
                "recovered": already_merged,
            }

    def reject(self, proposal_id: str, *, reason: str = "", by: str = "human") -> dict:
        with _exclusive_file_lock(self.lock_path):
            proposal = self.get(proposal_id)
            if proposal is None:
                return {"ok": False, "status": "not_found", "proposal_id": proposal_id}
            if proposal.status != "pending":
                return {"ok": False, "status": f"already_{proposal.status}",
                        "proposal_id": proposal.id}
            prior = self._decision(proposal.id)
            if prior and prior.get("action") == "approve":
                proposal.status = "approved"
                proposal.decided_at = str(prior.get("ts", ""))
                proposal.merged_into = str(prior.get("into", ""))
                _write_proposal(proposal)
                return {"ok": False, "status": "already_approved",
                        "proposal_id": proposal.id}
            proposal.status = "rejected"
            proposal.decided_at = str((prior or {}).get("ts") or _now_iso())
            proposal.reject_reason = _one_line(
                str((prior or {}).get("reason") or reason))
            self._audit_once(
                "reject", proposal.id, by=by, reason=proposal.reject_reason,
                strict=True)
            _write_proposal(proposal)
            return {"ok": True, "status": "rejected", "proposal_id": proposal.id}

    # ---- audit ----

    def audit_entries(self, strict: bool = True) -> List[dict]:
        """Return a defensive copy of readable append-only audit entries."""
        return copy.deepcopy(self._audit_entries(strict=strict))

    def record_audit(self, action: str, proposal_id: str = "", **details) -> dict:
        """Append a non-core operational event such as ``digest``.

        Decision actions are reserved for ReviewStore's gated methods, so a
        reporting caller cannot forge an approval or route record.
        """
        clean_action = _one_line(action)
        clean_proposal = _one_line(proposal_id)
        if not clean_action or clean_action != action:
            raise ValueError("audit action must be a non-empty single line")
        if clean_action in CORE_AUDIT_ACTIONS:
            raise ValueError(f"audit action {clean_action!r} is reserved")
        if clean_action not in OPERATIONAL_AUDIT_ACTIONS:
            raise ValueError(f"unknown audit action {clean_action!r}")
        extra = _validated_audit_extra(details, reserved=AUDIT_BASE_RESERVED)
        with _exclusive_file_lock(self.lock_path):
            self._audit_entries(strict=True)
            self._audit(clean_action, clean_proposal, **extra)
        return {
            "ok": True,
            "action": clean_action,
            "proposal_id": clean_proposal,
        }

    def _audit(self, action: str, proposal_id: str, **details) -> None:
        overlap = AUDIT_BASE_RESERVED & set(details)
        if overlap:
            raise ValueError(
                "audit details cannot override reserved field(s): "
                + ", ".join(sorted(overlap)))
        os.makedirs(self.staging_dir, exist_ok=True)
        entry = {"ts": _now_iso(), "action": action, "proposal_id": proposal_id}
        entry.update({k: v for k, v in details.items() if v not in ("", None)})
        _validate_audit_entry(entry)
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _audit_once(
        self, action: str, proposal_id: str, *, strict: bool = False, **details,
    ) -> None:
        if any(
                entry.get("action") == action
                and entry.get("proposal_id") == proposal_id
                for entry in self._audit_entries(strict=strict)):
            return
        self._audit(action, proposal_id, **details)

    def _audit_entries(self, *, strict: bool = False) -> List[dict]:
        if not os.path.isfile(self.audit_path):
            return []
        entries = []
        try:
            with open(self.audit_path, "r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    try:
                        entry = json.loads(
                            line,
                            object_pairs_hook=_strict_audit_object,
                            parse_constant=_reject_audit_constant,
                        )
                        _validate_audit_entry(entry)
                        entries.append(entry)
                    except (json.JSONDecodeError, ValueError) as exc:
                        if strict:
                            message = (
                                exc.msg
                                if isinstance(exc, json.JSONDecodeError)
                                else str(exc))
                            raise AuditLogError(
                                f"invalid audit JSON: {message}",
                                line=line_number,
                            ) from exc
                        continue
        except (OSError, UnicodeError) as exc:
            if strict:
                raise AuditLogError(f"cannot read audit log: {exc}") from exc
            return []
        return entries

    def _automatic_routes_today(self, day: str) -> int:
        proposal_ids = {
            str(entry.get("proposal_id", ""))
            for entry in self._audit_entries(strict=True)
            if str(entry.get("ts", ""))[:10] == day
            and entry.get("action") == "route"
            and entry.get("decision") == RoutingDecision.AUTO_APPROVE.value
            and entry.get("proposal_id")
        }
        return len(proposal_ids)

    def _decision(self, proposal_id: str) -> Optional[dict]:
        decisions = [
            entry for entry in self._audit_entries(strict=True)
            if entry.get("proposal_id") == proposal_id
            and entry.get("action") in ("approve", "reject")
        ]
        return decisions[-1] if decisions else None


# ---- proposal file format ----

def _write_proposal(proposal: Proposal) -> None:
    lines = [
        "# memdsl:proposal",
        f"# id: {proposal.id}",
        f"# status: {proposal.status}",
        f"# created_at: {proposal.created_at}",
    ]
    if proposal.client:
        lines.append(f"# client: {proposal.client}")
    if proposal.reason:
        lines.append(f"# reason: {proposal.reason}")
    if proposal.decided_at:
        lines.append(f"# decided_at: {proposal.decided_at}")
    if proposal.merged_into:
        lines.append(f"# merged_into: {proposal.merged_into}")
    if proposal.reject_reason:
        lines.append(f"# reject_reason: {proposal.reject_reason}")
    if proposal.routed:
        lines.append(f"# routed: {proposal.routed}")
    lines.append(HEADER_END)
    body = "\n".join(lines) + "\n" + proposal.source
    _atomic_write(proposal.path, body)


def _read_proposal(path: str) -> Optional[Proposal]:
    try:
        text = open(path, "r", encoding="utf-8").read()
    except OSError:
        return None
    meta = {}
    source_lines: List[str] = []
    in_header = True
    for line in text.splitlines():
        if in_header:
            if line.strip() == HEADER_END:
                in_header = False
                continue
            if line.startswith("# ") and ": " in line:
                key, _, value = line[2:].partition(": ")
                meta[key.strip()] = value.strip()
            continue
        source_lines.append(line)
    if in_header or "id" not in meta:
        return None
    return Proposal(
        id=meta.get("id", ""),
        status=meta.get("status", "pending"),
        created_at=meta.get("created_at", ""),
        client=meta.get("client", ""),
        reason=meta.get("reason", ""),
        source="\n".join(source_lines).strip() + "\n",
        path=path,
        decided_at=meta.get("decided_at", ""),
        merged_into=meta.get("merged_into", ""),
        reject_reason=meta.get("reject_reason", ""),
        routed=meta.get("routed", ""),
    )


def _new_id() -> str:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"p-{stamp}-{uuid.uuid4().hex[:6]}"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())


def _diag(code: str, message: str) -> dict:
    return {"code": code, "severity": "error", "message": message, "line": 0}


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        return ""


def _declaration_id(source: str) -> str:
    try:
        doc = parse_text(source, file=PROPOSAL_FILE_MARKER)
    except ParseError:
        return ""
    items = (
        list(doc.declarations) + list(doc.explicit_edges) + list(doc.edge_events)
    )
    if not items:
        return ""
    item = items[0]
    if item.kind in {"relation_edge", "explicit_edge"}:
        return f"relation_edge:{item.name}"
    if item.kind in {"relation_edge_event", "explicit_edge_event"}:
        return f"relation_edge_event:{item.name}"
    return f"{item.kind}:{item.name}"


def _declaration_for_source(
    ws: Workspace, source: str,
) -> Optional[ReviewableSource]:
    try:
        doc = parse_text(str(source or "").strip(), file=PROPOSAL_FILE_MARKER)
    except ParseError:
        return None
    items = (
        list(doc.declarations) + list(doc.explicit_edges) + list(doc.edge_events)
    )
    if len(items) != 1:
        return None
    probe = Workspace(
        registry=ws.registry,
        schema_version=ws.schema_version,
        linking_visibility=ws.linking_visibility,
        enforcement_mode=ws.enforcement_mode,
        explicit_edges_enabled=ws.explicit_edges_enabled,
    )
    probe.add_document(doc)
    reviewable = probe.reviewable_sources()
    return reviewable[0] if len(reviewable) == 1 else None


def _approval_marker_lines(text: str, proposal_id: str) -> List[str]:
    prefix = f"# approved from proposal {proposal_id} "
    return [line for line in text.splitlines() if line.startswith(prefix)]


def _approval_marker_valid(lines: Sequence[str], content_hash: str) -> bool:
    if not content_hash:
        return False
    for line in lines:
        if f" content {content_hash} at " in line:
            return True
        # Backward-compatible v0.5 marker.  Recovery still requires exact
        # normalized declaration content, so this predictable comment alone
        # is never sufficient.
        if " content " not in line and " at " in line:
            return True
    return False


def _target_contains_exact_declaration(
    target_text: str, proposal_source: str, registry,
) -> bool:
    probe = Workspace(
        registry=registry,
        schema_version=registry.workspace_schema_version,
        linking_visibility=registry.linking_visibility,
        enforcement_mode=registry.enforcement_mode,
        explicit_edges_enabled=registry.explicit_edges_enabled,
    )
    proposal = _declaration_for_source(probe, proposal_source)
    if proposal is None:
        return False
    expected = declaration_content_hash(proposal)
    try:
        document = parse_text(target_text, file="<approval-target>")
    except ParseError:
        return False
    target = Workspace(
        registry=registry,
        schema_version=registry.workspace_schema_version,
        linking_visibility=registry.linking_visibility,
        enforcement_mode=registry.enforcement_mode,
        explicit_edges_enabled=registry.explicit_edges_enabled,
    )
    target.add_document(document)
    return any(
        declaration_content_hash(declaration) == expected
        for declaration in target.reviewable_sources())


def _queued_submit_result(
    created: Mapping[str, object],
    assessment: RoutingAssessment,
    *,
    eligible: RoutingAssessment,
) -> dict:
    payload = dict(created)
    payload.update({
        "status": "pending_review",
        "route": "queued",
        "decision": assessment.decision.value,
        "route_rule": assessment.rule,
        "rule": assessment.rule,
        "tier": assessment.tier,
        "reason_codes": list(assessment.reason_codes),
        "policy_hash": assessment.policy_hash,
        "content_hash": assessment.content_hash,
        "assessment_hash": assessment.assessment_hash,
        "assessment": assessment.as_dict(),
        "eligible_route": eligible.decision.value,
        "eligible_rule": eligible.rule,
        "eligible_reason_codes": list(eligible.reason_codes),
        "eligible_assessment_hash": eligible.assessment_hash,
    })
    return payload


def _no_policy_assessment(
    declaration: ReviewableSource,
    *,
    warnings_count: int,
    workspace_paths: Sequence[str],
    workspace: Workspace,
    write_auto_granted: bool,
) -> RoutingAssessment:
    fingerprint = ""
    if workspace_paths:
        try:
            fingerprint = workspace_fingerprint(
                workspace_paths, workspace=workspace)
        except Exception:
            fingerprint = ""
    content_hash = declaration_content_hash(declaration)
    snapshot = {
        "declaration": {
            "id": declaration.id,
            "kind": declaration.kind,
            "runtime_role": declaration.runtime_role,
            "status": declaration.status,
            "scope": declaration.scope or "",
            "force": declaration.force or "",
            "capabilities": sorted(declaration.capabilities),
            "has_access_policy": bool(declaration.access_policy),
            "relations": {
                key: sorted(values)
                for key, values in sorted(declaration.relations().items())
                if values
            },
            "warnings_count": warnings_count,
            "content_hash": content_hash,
        },
        "context": None,
        "policy": {
            "version": "",
            "policy_hash": NO_POLICY_HASH,
            "auto_approved_today": 0,
            "max_auto_approve_per_day": 0,
        },
        "workspace": {"fingerprint": fingerprint},
        "deployment": {"write_auto_granted": write_auto_granted},
    }
    return RoutingAssessment(
        decision=RoutingDecision.QUEUE,
        rule=(
            "floor:explicit_edge_human_review_required"
            if requires_human_edge_review(declaration) else "no_policy"),
        reason_codes=(
            ("explicit_edge_human_review_required", "policy_missing")
            if requires_human_edge_review(declaration)
            else ("policy_missing",)
        ),
        policy_hash=NO_POLICY_HASH,
        content_hash=content_hash,
        input_snapshot=snapshot,
    )


def _validated_audit_extra(
    value: Optional[Mapping[str, object]], *, reserved: frozenset,
) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("audit metadata must be a mapping")
    invalid_keys = [
        key for key in value
        if not isinstance(key, str) or not key or key != _one_line(key)
    ]
    if invalid_keys:
        raise ValueError("audit metadata keys must be non-empty single-line strings")
    overlap = reserved & set(value)
    if overlap:
        raise ValueError(
            "audit metadata cannot override reserved field(s): "
            + ", ".join(sorted(overlap)))
    try:
        encoded = json.dumps(
            dict(value), ensure_ascii=False, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"audit metadata must be JSON-serializable: {exc}") from exc
    return json.loads(encoded)


def _strict_audit_object(pairs) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate audit key {key!r}")
        result[key] = value
    return result


def _reject_audit_constant(value: str):
    raise ValueError(f"non-standard JSON constant {value!r}")


def _validate_audit_entry(entry: object) -> None:
    if not isinstance(entry, dict):
        raise ValueError("audit entry must be an object")
    missing = {"ts", "action", "proposal_id"} - set(entry)
    if missing:
        raise ValueError(
            "audit entry is missing field(s): " + ", ".join(sorted(missing)))
    if (not isinstance(entry["ts"], str)
            or not isinstance(entry["action"], str)
            or not isinstance(entry["proposal_id"], str)):
        raise ValueError("audit ts, action, and proposal_id must be strings")
    if not entry["ts"] or not _one_line(entry["action"]):
        raise ValueError("audit ts and action must be non-empty")
    try:
        stamp = _dt.datetime.fromisoformat(entry["ts"])
    except ValueError as exc:
        raise ValueError("audit ts must be an ISO-8601 datetime") from exc
    if stamp.tzinfo is None:
        raise ValueError("audit ts must include a timezone")
    action = entry["action"]
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"unknown audit action {action!r}")

    required = {
        "propose": {"declaration"},
        "route": {
            "policy_hash", "decision", "rule", "reason_codes",
            "content_hash", "assessment_hash", "assessment",
        },
        "approve": {"by", "into", "declaration", "forced"},
        "reject": {"by"},
        "no_op": {
            "attempt_id", "duplicate_of", "existing_status", "declaration",
            "policy_hash", "rule", "reason_codes", "content_hash",
            "assessment_hash", "assessment",
        },
        "route_fallback": {
            "policy_hash", "original_rule", "reason_codes", "content_hash",
            "assessment_hash", "eligible_assessment_hash",
        },
        "digest": {"cursor_source", "counts"},
        "post_review": {"by", "verdict", "assessment_hash"},
    }[action]
    missing_action = required - set(entry)
    if missing_action:
        raise ValueError(
            f"{action} audit is missing field(s): "
            + ", ".join(sorted(missing_action)))

    if action != "digest" and action != "no_op" and not entry["proposal_id"]:
        raise ValueError(f"{action} audit requires a proposal_id")
    string_fields = {
        "propose": ("declaration",),
        "route": ("policy_hash", "decision", "rule", "content_hash",
                  "assessment_hash"),
        "approve": ("by", "into", "declaration"),
        "reject": ("by",),
        "no_op": ("attempt_id", "duplicate_of", "existing_status",
                  "declaration", "policy_hash", "rule", "content_hash",
                  "assessment_hash"),
        "route_fallback": ("policy_hash", "original_rule", "content_hash",
                           "assessment_hash", "eligible_assessment_hash"),
        "digest": ("cursor_source",),
        "post_review": ("by", "verdict", "assessment_hash"),
    }[action]
    for field_name in string_fields:
        value = entry.get(field_name)
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"{action} audit field {field_name!r} must be a non-empty string")

    if action in {"route", "no_op", "route_fallback"}:
        for field_name in ("policy_hash", "content_hash", "assessment_hash"):
            _require_sha256(entry[field_name], action, field_name)
    if action == "route_fallback":
        _require_sha256(
            entry["eligible_assessment_hash"], action,
            "eligible_assessment_hash")
    if action == "post_review":
        _require_sha256(entry["assessment_hash"], action, "assessment_hash")
        if entry["verdict"] not in {"confirm", "flag"}:
            raise ValueError("post_review audit verdict must be 'confirm' or 'flag'")
    if action in {"route", "no_op", "route_fallback"}:
        for field_name in ("reason_codes",):
            _require_string_list(
                entry[field_name], action, field_name,
                allow_empty=(action == "route"))
    if action == "route":
        if entry["decision"] not in {"auto_approve", "queue"}:
            raise ValueError("route audit decision must be auto_approve or queue")
        if not isinstance(entry["assessment"], dict):
            raise ValueError("route audit assessment must be an object")
        _validate_assessment_binding(
            entry,
            entry["assessment"],
            action="route",
            allowed_decisions={"auto_approve", "queue"},
        )
        eligible_core = {
            "eligible_route", "eligible_assessment_hash", "eligible_assessment",
        }
        present_eligible = eligible_core & set(entry)
        if present_eligible and present_eligible != eligible_core:
            raise ValueError(
                "route audit eligible fields must be present as a complete group")
        if present_eligible:
            if entry["eligible_route"] not in {"auto_approve", "queue"}:
                raise ValueError(
                    "route audit eligible_route must be auto_approve or queue")
            _require_sha256(
                entry["eligible_assessment_hash"], action,
                "eligible_assessment_hash")
            if not isinstance(entry["eligible_assessment"], dict):
                raise ValueError("route audit eligible_assessment must be an object")
            _validate_assessment_binding(
                entry,
                entry["eligible_assessment"],
                action="route eligible",
                allowed_decisions={"auto_approve", "queue"},
                envelope_prefix="eligible_",
            )
        if ("eligible_rule" in entry
                and (not isinstance(entry["eligible_rule"], str)
                     or not entry["eligible_rule"])):
            raise ValueError(
                "route audit eligible_rule must be a non-empty string")
        if "eligible_reason_codes" in entry:
            _require_string_list(
                entry["eligible_reason_codes"], action,
                "eligible_reason_codes", allow_empty=True)
    if action == "no_op":
        if not isinstance(entry["assessment"], dict):
            raise ValueError("no_op audit assessment must be an object")
        _validate_assessment_binding(
            entry,
            entry["assessment"],
            action="no_op",
            allowed_decisions={"no_op"},
        )
    if action == "approve" and not isinstance(entry["forced"], bool):
        raise ValueError("approve audit forced must be a boolean")
    if action == "digest" and not isinstance(entry["counts"], dict):
        raise ValueError("digest audit counts must be an object")


def _require_sha256(value: object, action: str, field_name: str) -> None:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError(
            f"{action} audit field {field_name!r} must be a full SHA-256")


def _validate_assessment_binding(
    envelope: Mapping[str, object],
    assessment: Mapping[str, object],
    *,
    action: str,
    allowed_decisions: set,
    envelope_prefix: str = "",
) -> None:
    allowed_fields = {
        "decision", "rule", "reason_codes", "policy_hash", "content_hash",
        "input_snapshot", "tier", "sample_bucket", "assessment_hash",
    }
    unknown = sorted(set(assessment) - allowed_fields)
    if unknown:
        raise ValueError(
            f"{action} assessment has unknown field(s): {', '.join(unknown)}")
    required = {
        "decision", "rule", "reason_codes", "policy_hash", "content_hash",
        "input_snapshot",
    }
    missing = sorted(required - set(assessment))
    if missing:
        raise ValueError(
            f"{action} assessment is missing field(s): {', '.join(missing)}")
    if assessment["decision"] not in allowed_decisions:
        raise ValueError(f"{action} assessment has an invalid decision")
    if not isinstance(assessment["rule"], str) or not assessment["rule"]:
        raise ValueError(f"{action} assessment rule must be a non-empty string")
    _require_string_list(
        assessment["reason_codes"], action, "assessment.reason_codes",
        allow_empty=(action.startswith("route")))
    _require_sha256(
        assessment["policy_hash"], action, "assessment.policy_hash")
    _require_sha256(
        assessment["content_hash"], action, "assessment.content_hash")
    if not isinstance(assessment["input_snapshot"], dict):
        raise ValueError(f"{action} assessment input_snapshot must be an object")
    if ("tier" in assessment
            and (not isinstance(assessment["tier"], str)
                 or not assessment["tier"])):
        raise ValueError(f"{action} assessment tier must be a non-empty string")
    if "sample_bucket" in assessment:
        bucket = assessment["sample_bucket"]
        if (not isinstance(bucket, int) or isinstance(bucket, bool)
                or not 0 <= bucket <= 99):
            raise ValueError(
                f"{action} assessment sample_bucket must be an integer 0..99")

    calculated = _canonical_assessment_hash(assessment)
    hash_field = envelope_prefix + "assessment_hash"
    if envelope.get(hash_field) != calculated:
        raise ValueError(
            f"{action} envelope {hash_field} does not match assessment content")

    field_pairs = {
        envelope_prefix + "route": "decision",
        envelope_prefix + "rule": "rule",
        envelope_prefix + "reason_codes": "reason_codes",
    }
    if not envelope_prefix:
        field_pairs.update({
            "decision": "decision",
            "rule": "rule",
            "reason_codes": "reason_codes",
            "policy_hash": "policy_hash",
            "content_hash": "content_hash",
        })
    for envelope_field, assessment_field in field_pairs.items():
        if (envelope_field in envelope
                and envelope[envelope_field] != assessment[assessment_field]):
            raise ValueError(
                f"{action} envelope {envelope_field} does not match assessment")
    if envelope_prefix:
        if assessment["policy_hash"] != envelope.get("policy_hash"):
            raise ValueError(
                f"{action} assessment policy_hash does not match route envelope")
        if assessment["content_hash"] != envelope.get("content_hash"):
            raise ValueError(
                f"{action} assessment content_hash does not match route envelope")
    if (not envelope_prefix and "input_snapshot" in envelope
            and envelope["input_snapshot"] != assessment["input_snapshot"]):
        raise ValueError(
            f"{action} envelope input_snapshot does not match assessment")
    if not envelope_prefix:
        for optional_field in ("tier", "sample_bucket"):
            if (optional_field in envelope or optional_field in assessment):
                if envelope.get(optional_field) != assessment.get(optional_field):
                    raise ValueError(
                        f"{action} envelope {optional_field} "
                        "does not match assessment")


def _canonical_assessment_hash(assessment: Mapping[str, object]) -> str:
    embedded = assessment.get("assessment_hash")
    if embedded is not None:
        _require_sha256(embedded, "assessment", "assessment_hash")
    base = {
        key: value for key, value in assessment.items()
        if key != "assessment_hash"
    }
    try:
        canonical = json.dumps(
            base,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"assessment is not canonical JSON data: {exc}") from exc
    calculated = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if embedded is not None and embedded != calculated:
        raise ValueError(
            "assessment embedded assessment_hash does not match assessment content")
    return calculated


def _require_string_list(
    value: object,
    action: str,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> None:
    if (not isinstance(value, list) or (not allow_empty and not value)
            or any(not isinstance(item, str) or not item for item in value)):
        raise ValueError(
            f"{action} audit field {field_name!r} must be a non-empty string list")


def _utc_date() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _invoke_evidence_verifier(
    verifier: Optional[EvidenceVerifier],
    evidence: Optional[Mapping[str, object]],
    workspace_paths: Sequence[str],
) -> EvidenceVerification:
    """Call a host verifier without allowing failures to become trust."""
    if verifier is None:
        return EvidenceVerification.unverified(
            "evidence_verifier_unavailable", evidence=evidence)
    try:
        proof = verifier(evidence, workspace_paths)
    except Exception:
        return EvidenceVerification.unverified(
            "evidence_verifier_exception",
            verifier=_callable_name(verifier),
            evidence=evidence,
        )
    if not isinstance(proof, EvidenceVerification):
        return EvidenceVerification.unverified(
            "evidence_verifier_invalid_result",
            verifier=_callable_name(verifier),
            evidence=evidence,
        )
    return proof


def _evidence_verification_matches(
    expected: EvidenceVerification,
    actual: EvidenceVerification,
) -> bool:
    return bool(
        expected.verified
        and actual.verified
        and actual.verifier == expected.verifier
        and actual.source_digest == expected.source_digest
        and actual.quote_digest == expected.quote_digest
        and actual.evidence_digest == expected.evidence_digest
    )


def _callable_name(value: object) -> str:
    name = getattr(value, "__name__", "")
    return " ".join(name.split()) if isinstance(name, str) else ""


def _normalized_workspace_paths(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (str, os.PathLike)):
        items = [value]
    else:
        try:
            items = list(value)
        except TypeError as exc:
            raise TypeError("workspace paths must be a path or sequence of paths") from exc
    paths: List[str] = []
    for raw in items:
        try:
            text = os.fspath(raw)
        except TypeError as exc:
            raise TypeError("workspace paths must contain only path-like values") from exc
        if not isinstance(text, str) or not text.strip():
            raise ValueError("workspace paths must not contain empty values")
        absolute = os.path.abspath(text)
        if absolute not in paths:
            paths.append(absolute)
    return paths


def _validated_reason_codes(value: Sequence[str]) -> List[str]:
    if isinstance(value, str):
        raise TypeError("blocking_reasons must be a sequence, not a string")
    result: List[str] = []
    for raw in value:
        if not isinstance(raw, str) or not raw or raw != _one_line(raw):
            raise ValueError(
                "blocking_reasons must contain non-empty single-line strings")
        if raw not in result:
            result.append(raw)
    return result


def workspace_fingerprint(
    workspace_paths: Sequence[str], *, workspace: Optional[Workspace] = None,
) -> str:
    """Hash every loaded memory, manifest, and registry schema input.

    Entries use root-relative labels plus full content digests, making the
    aggregate stable without writing machine-specific absolute paths to audit.
    """
    paths = _normalized_workspace_paths(workspace_paths)
    if not paths:
        raise ValueError("workspace fingerprint requires at least one path")
    ws = workspace or Workspace.load(paths)
    roots: List[str] = []
    files = set()
    for path in paths:
        root = path if os.path.isdir(path) else os.path.dirname(path)
        root_real = os.path.realpath(root)
        if root_real not in roots:
            roots.append(root_real)
        if os.path.isdir(path):
            for current_root, _dirs, names in os.walk(path):
                for name in names:
                    if name.endswith(".mem"):
                        files.add(os.path.realpath(os.path.join(current_root, name)))
        elif path.endswith(".mem"):
            files.add(os.path.realpath(path))
        manifest = os.path.join(root, "memdsl.json")
        if os.path.isfile(manifest):
            files.add(os.path.realpath(manifest))
    for schema_path in ws.registry.schema_files:
        files.add(os.path.realpath(schema_path))

    entries = []
    for path in sorted(files, key=lambda item: os.path.normcase(item)):
        if not os.path.isfile(path):
            raise OSError(f"workspace fingerprint input is missing: {path}")
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        entries.append({
            "path": _fingerprint_label(path, roots),
            "sha256": digest,
        })
    encoded = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint_label(path: str, roots: Sequence[str]) -> str:
    for index, root in enumerate(roots):
        try:
            if os.path.commonpath([path, root]) != root:
                continue
        except ValueError:
            continue
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        return f"root-{index}/{relative}"
    # External schemas are supported by today's manifest loader.  Hash the
    # location label so the audit fingerprint does not expose an absolute path.
    location = hashlib.sha256(
        os.path.normcase(path).encode("utf-8")).hexdigest()
    return f"external-schema/{location}"


def _atomic_write(path: str, text: str) -> None:
    """Replace one text file atomically and durably on the same filesystem."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".memdsl-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@contextmanager
def _exclusive_file_lock(
    path: str,
    *,
    timeout_seconds: float = 10.0,
    poll_interval: float = 0.05,
):
    """Cross-platform process lock with a bounded, structured timeout."""
    if (not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool) or timeout_seconds < 0):
        raise ValueError("timeout_seconds must be a non-negative number")
    if (not isinstance(poll_interval, (int, float))
            or isinstance(poll_interval, bool) or poll_interval <= 0):
        raise ValueError("poll_interval must be a positive number")
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    handle = open(path, "a+b")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + float(timeout_seconds)
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError) as exc:
                if isinstance(exc, OSError) and exc.errno not in {
                        errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ReviewLockTimeout(path, float(timeout_seconds)) from exc
                time.sleep(min(float(poll_interval), remaining))
        try:
            yield
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
