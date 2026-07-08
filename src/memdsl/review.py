"""Gated write pipeline: proposals, review queue, approval, audit.

Implements the SPEC §10 posture for early deployments: **all** proposed
writes land in a human review queue; nothing becomes memory until a
person approves it. Proposals are stored as `.mem.proposal` files (same
declaration syntax, different extension so `Workspace.load` never picks
them up) under a staging directory, by default `<workspace>/.memdsl/`:

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
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from memdsl.linter import lint
from memdsl.model import Workspace
from memdsl.parser import ParseError, parse_text

PROPOSAL_SUFFIX = ".mem.proposal"
PROPOSAL_FILE_MARKER = "<proposal>"
PROPOSAL_STATUSES = ("pending", "approved", "rejected")

HEADER_END = "# ---"


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

    def summary(self) -> dict:
        head = ""
        try:
            doc = parse_text(self.source, file=PROPOSAL_FILE_MARKER)
            if doc.declarations:
                d = doc.declarations[0]
                head = f"{d.kind}:{d.name}"
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
        }


@dataclass
class ValidationResult:
    ok: bool
    errors: List[dict] = field(default_factory=list)
    warnings: List[dict] = field(default_factory=list)
    declaration_id: str = ""


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
        if len(doc.declarations) != 1:
            return ValidationResult(False, errors=[_diag(
                "single_declaration_required",
                f"a proposal must contain exactly one declaration, got {len(doc.declarations)}",
            )])

        merged = Workspace(declarations=list(ws.declarations), files=list(ws.files))
        merged.add_document(doc)
        decl = merged.declarations[-1]

        errors: List[dict] = []
        warnings: List[dict] = []
        for d in lint(merged):
            if d.file != PROPOSAL_FILE_MARKER:
                continue  # pre-existing workspace diagnostics are not the proposal's fault
            entry = {"code": d.code, "severity": d.severity, "message": d.message, "line": d.line}
            (errors if d.severity == "error" else warnings).append(entry)
        return ValidationResult(not errors, errors=errors, warnings=warnings,
                                declaration_id=decl.id)

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
        proposal.path = os.path.join(self.proposals_dir, proposal.id + PROPOSAL_SUFFIX)
        _write_proposal(proposal)
        self._audit("propose", proposal.id, client=proposal.client,
                    declaration=result.declaration_id, reason=proposal.reason)
        return {
            "ok": True,
            "status": "pending_review",
            "proposal_id": proposal.id,
            "declaration_id": result.declaration_id,
            "path": proposal.path,
            "warnings": result.warnings,
        }

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

    def approve(self, proposal_id: str, ws: Workspace, into: str, *,
                force: bool = False, by: str = "human") -> dict:
        proposal = self.get(proposal_id)
        if proposal is None:
            return {"ok": False, "status": "not_found", "proposal_id": proposal_id}
        if proposal.status != "pending":
            return {"ok": False, "status": f"already_{proposal.status}",
                    "proposal_id": proposal.id}
        # Re-validate against the *current* workspace: it may have changed
        # since the proposal was staged.
        result = self.validate(ws, proposal.source)
        if not result.ok and not force:
            return {
                "ok": False,
                "status": "stale_or_invalid",
                "proposal_id": proposal.id,
                "errors": result.errors,
                "warnings": result.warnings,
                "hint": "fix the workspace or re-propose; --force overrides",
            }
        into_path = os.path.abspath(into)
        os.makedirs(os.path.dirname(into_path) or ".", exist_ok=True)
        stamp = _now_iso()
        block = (
            f"\n# approved from proposal {proposal.id} at {stamp}\n"
            + proposal.source.rstrip("\n") + "\n"
        )
        with open(into_path, "a", encoding="utf-8") as f:
            f.write(block)
        proposal.status = "approved"
        proposal.decided_at = stamp
        proposal.merged_into = into_path
        _write_proposal(proposal)
        self._audit("approve", proposal.id, by=by, into=into_path,
                    declaration=result.declaration_id, forced=bool(force and not result.ok))
        return {
            "ok": True,
            "status": "approved",
            "proposal_id": proposal.id,
            "declaration_id": result.declaration_id,
            "merged_into": into_path,
            "warnings": result.warnings,
        }

    def reject(self, proposal_id: str, *, reason: str = "", by: str = "human") -> dict:
        proposal = self.get(proposal_id)
        if proposal is None:
            return {"ok": False, "status": "not_found", "proposal_id": proposal_id}
        if proposal.status != "pending":
            return {"ok": False, "status": f"already_{proposal.status}",
                    "proposal_id": proposal.id}
        proposal.status = "rejected"
        proposal.decided_at = _now_iso()
        proposal.reject_reason = _one_line(reason)
        _write_proposal(proposal)
        self._audit("reject", proposal.id, by=by, reason=proposal.reject_reason)
        return {"ok": True, "status": "rejected", "proposal_id": proposal.id}

    # ---- audit ----

    def _audit(self, action: str, proposal_id: str, **details) -> None:
        os.makedirs(self.staging_dir, exist_ok=True)
        entry = {"ts": _now_iso(), "action": action, "proposal_id": proposal_id}
        entry.update({k: v for k, v in details.items() if v not in ("", None)})
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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
    lines.append(HEADER_END)
    body = "\n".join(lines) + "\n" + proposal.source
    with open(proposal.path, "w", encoding="utf-8") as f:
        f.write(body)


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
