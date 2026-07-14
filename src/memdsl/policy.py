"""Fail-closed, host-attested routing for review-gated writes.

Policies never grant authority on their own.  A declaration must first pass
the non-configurable safety floor in :meth:`ReviewPolicy.assess`; matching a
rule can only narrow that already-small set.  In particular, evidence and
client identity come from :class:`ProposalContext`, not from proposal fields
or proposal-file headers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from memdsl.model import ReviewableSource
from memdsl.schema import RESERVED_EDGE_CAPABILITIES, RESERVED_EDGE_KINDS


POLICY_FILENAME = "policy.json"
POLICY_VERSION = "memdsl.policy.v1"
AUTO_APPROVABLE_CAPABILITY = "auto_approvable"
WORKSPACE_FILE_QUOTE_VERIFIER = "workspace_file_quote"

DESTRUCTIVE_RELATIONS = frozenset({
    "supersedes", "conflicts_with", "revision_of",
})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_FIELDS = frozenset({
    "version",
    "default_route",
    "auto_merge_into",
    "sample_to_queue_percent",
    "max_auto_approve_per_day",
    "trusted_clients",
    "rules",
})
_RULE_FIELDS = frozenset({"name", "route", "tier", "match"})
_MATCH_FIELDS = frozenset({
    "kind",
    "scope",
    "scope_not",
    "client",
    "evidence_verifier",
    "force_not",
})


class PolicyError(ValueError):
    """Raised when a review policy is invalid or unsafe to apply."""


class RoutingDecision(str, Enum):
    """Stable routing outcomes emitted by the policy core."""

    AUTO_APPROVE = "auto_approve"
    QUEUE = "queue"
    NO_OP = "no_op"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _value_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return _canonical_json(value).encode("utf-8")


def evidence_value_digest(value: object) -> str:
    """Return a full SHA-256 digest for one evidence value."""
    return _sha256_bytes(_value_bytes(value))


def evidence_block_digest(evidence: Mapping[str, object]) -> str:
    """Bind an attestation to the complete proposal evidence block."""
    return _sha256_bytes(_canonical_json(dict(evidence)).encode("utf-8"))


@dataclass(frozen=True)
class EvidenceVerification:
    """Host-produced proof about evidence referenced by a proposal.

    ``evidence_digest`` binds the proof to the entire declaration evidence
    block.  ``source_digest`` records the verified source content, while
    ``quote_digest`` records the exact quoted text.  Merely placing similarly
    named fields in a proposal cannot create this object.
    """

    verified: bool
    verifier: str = ""
    source_digest: str = ""
    quote_digest: str = ""
    evidence_digest: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.verified, bool):
            raise TypeError("verified must be a boolean")
        for name in (
                "verifier", "source_digest", "quote_digest",
                "evidence_digest", "reason"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a string")
        if self.verifier != _one_line(self.verifier):
            raise ValueError("verifier must be a single line")
        if self.reason != _one_line(self.reason):
            raise ValueError("reason must be a single line")
        for name in ("source_digest", "quote_digest", "evidence_digest"):
            value = getattr(self, name)
            if value and not _SHA256_RE.fullmatch(value):
                raise ValueError(f"{name} must be a full lowercase SHA-256 digest")
        if self.verified:
            if not self.verifier:
                raise ValueError("a verified attestation requires a verifier")
            missing = [
                name for name in (
                    "source_digest", "quote_digest", "evidence_digest")
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(
                    "a verified attestation requires " + ", ".join(missing))

    @classmethod
    def verified_content(
        cls,
        *,
        verifier: str,
        evidence: Mapping[str, object],
        source_content: Union[str, bytes],
    ) -> "EvidenceVerification":
        """Construct an attestation after a host has verified source content."""
        quote = evidence.get("quote") if isinstance(evidence, Mapping) else None
        if not isinstance(quote, str) or not quote:
            raise ValueError("verified evidence requires a non-empty string quote")
        return cls(
            verified=True,
            verifier=_one_line(verifier),
            source_digest=evidence_value_digest(source_content),
            quote_digest=evidence_value_digest(quote),
            evidence_digest=evidence_block_digest(evidence),
        )

    @classmethod
    def unverified(
        cls,
        reason: str,
        *,
        verifier: str = "",
        evidence: Optional[Mapping[str, object]] = None,
        source_content: Optional[Union[str, bytes]] = None,
    ) -> "EvidenceVerification":
        quote = evidence.get("quote") if isinstance(evidence, Mapping) else None
        return cls(
            verified=False,
            verifier=_one_line(verifier),
            source_digest=(
                evidence_value_digest(source_content)
                if source_content is not None else ""),
            quote_digest=(
                evidence_value_digest(quote) if isinstance(quote, str) else ""),
            evidence_digest=(
                evidence_block_digest(evidence)
                if isinstance(evidence, Mapping) else ""),
            reason=_one_line(reason),
        )

    def as_dict(self) -> dict:
        return {
            "verified": self.verified,
            "verifier": self.verifier,
            "source_digest": self.source_digest,
            "quote_digest": self.quote_digest,
            "evidence_digest": self.evidence_digest,
            "reason": self.reason,
        }


@dataclass(frozen=True, init=False)
class ProposalContext:
    """Host-owned identity and evidence proof for one proposal.

    ``client``/``evidence`` aliases are accepted for ergonomic compatibility,
    but the canonical attributes are ``client_id`` and
    ``evidence_verification``.
    """

    client_id: str
    evidence_verification: Optional[EvidenceVerification]

    def __init__(
        self,
        client_id: str = "",
        evidence_verification: Optional[EvidenceVerification] = None,
        *,
        client: Optional[str] = None,
        evidence: Optional[EvidenceVerification] = None,
    ) -> None:
        if client is not None:
            if client_id and client_id != client:
                raise ValueError("client and client_id disagree")
            client_id = client
        if evidence is not None:
            if (evidence_verification is not None
                    and evidence_verification != evidence):
                raise ValueError("evidence and evidence_verification disagree")
            evidence_verification = evidence
        if not isinstance(client_id, str):
            raise TypeError("client_id must be a string")
        clean_client = _one_line(client_id)
        if clean_client != client_id:
            raise ValueError("client_id must be a non-empty single line")
        if not clean_client:
            raise ValueError("client_id must be a non-empty string")
        if (evidence_verification is not None
                and not isinstance(evidence_verification, EvidenceVerification)):
            raise TypeError("evidence_verification must be EvidenceVerification")
        object.__setattr__(self, "client_id", clean_client)
        object.__setattr__(self, "evidence_verification", evidence_verification)

    @property
    def client(self) -> str:
        return self.client_id

    @property
    def evidence(self) -> Optional[EvidenceVerification]:
        return self.evidence_verification

    def with_evidence(self, proof: EvidenceVerification) -> "ProposalContext":
        return ProposalContext(self.client_id, proof)

    def as_dict(self) -> dict:
        return {
            "client": self.client_id,
            "evidence": (
                self.evidence_verification.as_dict()
                if self.evidence_verification is not None else None),
        }


@dataclass(frozen=True)
class PolicyRule:
    """A conjunctive allow rule that can only narrow the safety floor."""

    name: str
    match: Mapping[str, object]
    route: str = RoutingDecision.AUTO_APPROVE.value
    tier: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _one_line(self.name):
            raise PolicyError("rule name must be a non-empty string")
        if self.name != _one_line(self.name):
            raise PolicyError("rule name must be a single line")
        if self.route != RoutingDecision.AUTO_APPROVE.value:
            raise PolicyError("rule route must be 'auto_approve'")
        if not isinstance(self.tier, str) or self.tier != _one_line(self.tier):
            raise PolicyError(f"rule {self.name!r} tier must be a single-line string")
        normalized = _validate_match(self.match, rule_name=self.name)
        object.__setattr__(self, "match", normalized)

    def matches(self, declaration: ReviewableSource, context: ProposalContext) -> bool:
        match = self.match
        if declaration.kind not in match["kind"]:
            return False
        if "scope" in match and declaration.scope not in match["scope"]:
            return False
        if "scope_not" in match and declaration.scope in match["scope_not"]:
            return False
        if "client" in match and context.client_id not in match["client"]:
            return False
        proof = context.evidence_verification
        if ("evidence_verifier" in match
                and (proof is None or proof.verifier not in match["evidence_verifier"])):
            return False
        if "force_not" in match and declaration.force in match["force_not"]:
            return False
        return True

    def as_dict(self) -> dict:
        payload = {
            "name": self.name,
            "route": self.route,
            "match": {key: list(value) for key, value in self.match.items()},
        }
        if self.tier:
            payload["tier"] = self.tier
        return payload


@dataclass(frozen=True)
class RoutingAssessment:
    """Serializable explanation of a policy routing decision."""

    decision: RoutingDecision
    rule: str
    reason_codes: Tuple[str, ...]
    policy_hash: str
    content_hash: str
    input_snapshot: Mapping[str, object]
    tier: str = ""
    sample_bucket: Optional[int] = None

    @property
    def route(self) -> str:
        return self.decision.value

    @property
    def reasons(self) -> List[str]:
        return list(self.reason_codes)

    @property
    def assessment_hash(self) -> str:
        """Full SHA-256 of the canonical assessment, excluding this hash."""
        return _sha256_bytes(
            _canonical_json(self._base_dict()).encode("utf-8"))

    def _base_dict(self) -> dict:
        payload = {
            "decision": self.decision.value,
            "rule": self.rule,
            "reason_codes": list(self.reason_codes),
            "policy_hash": self.policy_hash,
            "content_hash": self.content_hash,
            "input_snapshot": _json_copy(self.input_snapshot),
        }
        if self.tier:
            payload["tier"] = self.tier
        if self.sample_bucket is not None:
            payload["sample_bucket"] = self.sample_bucket
        return payload

    def as_dict(self) -> dict:
        payload = self._base_dict()
        payload["assessment_hash"] = self.assessment_hash
        return payload


@dataclass(frozen=True)
class ReviewPolicy:
    """Strict v1 review policy with a non-configurable safety floor."""

    version: str
    default_route: str
    auto_merge_into: str
    sample_to_queue_percent: int
    max_auto_approve_per_day: int
    trusted_clients: Tuple[str, ...]
    rules: Tuple[PolicyRule, ...]
    source_hash: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.version != POLICY_VERSION:
            raise PolicyError(f"version must be {POLICY_VERSION!r}")
        if self.default_route != RoutingDecision.QUEUE.value:
            raise PolicyError("default_route must be 'queue'")
        _validate_auto_merge_into(self.auto_merge_into)
        if not _plain_int(self.sample_to_queue_percent):
            raise PolicyError("sample_to_queue_percent must be an integer")
        if not 0 <= self.sample_to_queue_percent <= 100:
            raise PolicyError("sample_to_queue_percent must be between 0 and 100")
        if not _plain_int(self.max_auto_approve_per_day):
            raise PolicyError("max_auto_approve_per_day must be an integer")
        if self.max_auto_approve_per_day < 0:
            raise PolicyError("max_auto_approve_per_day must be >= 0")
        trusted = _string_tuple(self.trusted_clients, "trusted_clients", allow_empty=True)
        if len(set(trusted)) != len(trusted):
            raise PolicyError("trusted_clients contains duplicate values")
        object.__setattr__(self, "trusted_clients", trusted)
        if not isinstance(self.rules, (tuple, list)):
            raise PolicyError("rules must be a list")
        rules = tuple(self.rules)
        if any(not isinstance(rule, PolicyRule) for rule in rules):
            raise PolicyError("rules must contain PolicyRule values")
        names = [rule.name for rule in rules]
        if len(set(names)) != len(names):
            raise PolicyError("rule names must be unique")
        trusted_set = set(trusted)
        for rule in rules:
            rule_clients = set(rule.match.get("client", ()))
            if not rule_clients.issubset(trusted_set):
                unknown = sorted(rule_clients - trusted_set)
                raise PolicyError(
                    f"rule {rule.name!r} match.client is not a subset of "
                    f"trusted_clients: {', '.join(unknown)}")
        object.__setattr__(self, "rules", rules)
        if self.source_hash:
            if not isinstance(self.source_hash, str) or not _SHA256_RE.fullmatch(
                    self.source_hash):
                raise PolicyError("source_hash must be a full lowercase SHA-256 digest")
        else:
            digest = _sha256_bytes(
                _canonical_json(self.as_config_dict()).encode("utf-8"))
            object.__setattr__(self, "source_hash", digest)

    @property
    def policy_hash(self) -> str:
        return self.source_hash

    @classmethod
    def from_dict(cls, payload: Mapping[str, object], *, source_hash: str = "") -> "ReviewPolicy":
        if not isinstance(payload, Mapping):
            raise PolicyError("policy root must be an object")
        _reject_unknown(payload, _TOP_LEVEL_FIELDS, "policy")
        missing = sorted(_TOP_LEVEL_FIELDS - set(payload))
        if missing:
            raise PolicyError("policy is missing required field(s): " + ", ".join(missing))
        raw_rules = payload["rules"]
        if not isinstance(raw_rules, list):
            raise PolicyError("rules must be a list")
        rules: List[PolicyRule] = []
        for index, raw_rule in enumerate(raw_rules):
            if not isinstance(raw_rule, Mapping):
                raise PolicyError(f"rules[{index}] must be an object")
            _reject_unknown(raw_rule, _RULE_FIELDS, f"rules[{index}]")
            missing_rule = {"name", "route", "match"} - set(raw_rule)
            if missing_rule:
                raise PolicyError(
                    f"rules[{index}] is missing field(s): "
                    + ", ".join(sorted(missing_rule)))
            rules.append(PolicyRule(
                name=raw_rule["name"],  # type: ignore[arg-type]
                route=raw_rule["route"],  # type: ignore[arg-type]
                tier=raw_rule.get("tier", ""),  # type: ignore[arg-type]
                match=raw_rule["match"],  # type: ignore[arg-type]
            ))
        return cls(
            version=payload["version"],  # type: ignore[arg-type]
            default_route=payload["default_route"],  # type: ignore[arg-type]
            auto_merge_into=payload["auto_merge_into"],  # type: ignore[arg-type]
            sample_to_queue_percent=payload["sample_to_queue_percent"],  # type: ignore[arg-type]
            max_auto_approve_per_day=payload["max_auto_approve_per_day"],  # type: ignore[arg-type]
            trusted_clients=payload["trusted_clients"],  # type: ignore[arg-type]
            rules=tuple(rules),
            source_hash=source_hash,
        )

    def as_config_dict(self) -> dict:
        return {
            "version": self.version,
            "default_route": self.default_route,
            "auto_merge_into": self.auto_merge_into,
            "sample_to_queue_percent": self.sample_to_queue_percent,
            "max_auto_approve_per_day": self.max_auto_approve_per_day,
            "trusted_clients": list(self.trusted_clients),
            "rules": [rule.as_dict() for rule in self.rules],
        }

    def validate_registry(self, registry) -> None:
        """Reject rule kinds that are not present in the current registry."""
        for rule in self.rules:
            for kind in rule.match["kind"]:
                if kind in RESERVED_EDGE_KINDS:
                    raise PolicyError(
                        f"rule {rule.name!r} cannot auto-route reserved explicit "
                        f"Edge kind {kind!r}; Phase 6 requires human review")
                if registry.resolve(kind) is None:
                    raise PolicyError(
                        f"rule {rule.name!r} references unknown memory type {kind!r}")

    def resolve_auto_merge_into(self, workspace_paths: Sequence[str]) -> str:
        """Resolve the target inside the first workspace root, fail-closed."""
        if not workspace_paths:
            raise PolicyError("workspace_paths are required for automatic approval")
        first = os.path.abspath(str(workspace_paths[0]))
        root = first if os.path.isdir(first) else os.path.dirname(first)
        if not root:
            raise PolicyError("cannot resolve the workspace root")
        candidate = os.path.abspath(os.path.join(root, self.auto_merge_into))
        root_real = os.path.realpath(root)
        candidate_real = os.path.realpath(candidate)
        try:
            contained = os.path.commonpath([root_real, candidate_real]) == root_real
        except ValueError:
            contained = False
        if not contained:
            raise PolicyError("auto_merge_into resolves outside the workspace root")
        if not candidate.lower().endswith(".mem"):
            raise PolicyError("auto_merge_into must resolve to a .mem file")
        return candidate

    def assess(
        self,
        declaration: ReviewableSource,
        *,
        warnings_count: int,
        context: Optional[ProposalContext],
        auto_approved_today: int = 0,
        blocking_reasons: Sequence[str] = (),
        workspace_fingerprint: str = "",
        write_auto_granted: Optional[bool] = None,
    ) -> RoutingAssessment:
        """Apply the hard floor, then the first matching narrowing rule."""
        if not _plain_int(warnings_count) or warnings_count < 0:
            raise ValueError("warnings_count must be a non-negative integer")
        if not _plain_int(auto_approved_today) or auto_approved_today < 0:
            raise ValueError("auto_approved_today must be a non-negative integer")
        if not isinstance(workspace_fingerprint, str):
            raise TypeError("workspace_fingerprint must be a string")
        if (workspace_fingerprint
                and not _SHA256_RE.fullmatch(workspace_fingerprint)):
            raise ValueError(
                "workspace_fingerprint must be a full lowercase SHA-256 digest")
        if write_auto_granted is not None and not isinstance(write_auto_granted, bool):
            raise TypeError("write_auto_granted must be a boolean or None")
        content_hash = declaration_content_hash(declaration)
        snapshot = _input_snapshot(
            declaration,
            content_hash=content_hash,
            warnings_count=warnings_count,
            context=context,
            policy=self,
            auto_approved_today=auto_approved_today,
            workspace_fingerprint=workspace_fingerprint,
            write_auto_granted=write_auto_granted,
        )
        floor = [_one_line(reason) for reason in blocking_reasons if _one_line(reason)]
        floor.extend(_floor_reasons(declaration, warnings_count, context, self))
        if floor:
            return RoutingAssessment(
                decision=RoutingDecision.QUEUE,
                rule=f"floor:{floor[0]}",
                reason_codes=tuple(_unique(floor)),
                policy_hash=self.source_hash,
                content_hash=content_hash,
                input_snapshot=snapshot,
            )

        assert context is not None  # guaranteed by the floor
        matched = next(
            (rule for rule in self.rules if rule.matches(declaration, context)),
            None,
        )
        if matched is None:
            return RoutingAssessment(
                decision=RoutingDecision.QUEUE,
                rule="default",
                reason_codes=("no_matching_rule",),
                policy_hash=self.source_hash,
                content_hash=content_hash,
                input_snapshot=snapshot,
            )

        if auto_approved_today >= self.max_auto_approve_per_day:
            return RoutingAssessment(
                decision=RoutingDecision.QUEUE,
                rule=f"limit:{matched.name}",
                reason_codes=("daily_limit_reached",),
                policy_hash=self.source_hash,
                content_hash=content_hash,
                input_snapshot=snapshot,
                tier=matched.tier,
            )

        bucket = deterministic_sample_bucket(content_hash, self.source_hash)
        if bucket < self.sample_to_queue_percent:
            return RoutingAssessment(
                decision=RoutingDecision.QUEUE,
                rule=f"sample:{matched.name}",
                reason_codes=("sampled_to_queue",),
                policy_hash=self.source_hash,
                content_hash=content_hash,
                input_snapshot=snapshot,
                tier=matched.tier,
                sample_bucket=bucket,
            )

        return RoutingAssessment(
            decision=RoutingDecision.AUTO_APPROVE,
            rule=matched.name,
            reason_codes=("safe_floor_passed", "policy_rule_matched"),
            policy_hash=self.source_hash,
            content_hash=content_hash,
            input_snapshot=snapshot,
            tier=matched.tier,
            sample_bucket=bucket,
        )

    def route(self, declaration: ReviewableSource, **kwargs) -> RoutingAssessment:
        """Compatibility spelling for callers that think in routes."""
        return self.assess(declaration, **kwargs)


def declaration_content_hash(declaration: ReviewableSource) -> str:
    """Hash normalized declaration content, independent of source formatting."""
    payload = {
        "kind": declaration.kind,
        "name": declaration.name,
        "module": declaration.module or "",
        "fields": declaration.fields,
    }
    return _sha256_bytes(_canonical_json(payload).encode("utf-8"))


def deterministic_sample_bucket(content_hash: str, policy_hash: str) -> int:
    """Stable 0..99 sample bucket bound to content and the exact policy."""
    if not _SHA256_RE.fullmatch(str(content_hash or "")):
        raise ValueError("content_hash must be a full lowercase SHA-256 digest")
    if not _SHA256_RE.fullmatch(str(policy_hash or "")):
        raise ValueError("policy_hash must be a full lowercase SHA-256 digest")
    digest = _sha256_bytes(f"{content_hash}:{policy_hash}".encode("ascii"))
    return int(digest[:8], 16) % 100


def load_policy(path: str, *, registry=None) -> Optional[ReviewPolicy]:
    """Load strict JSON from ``path`` or ``<staging>/policy.json``.

    A missing file means no policy.  Malformed or unsafe configuration raises
    :class:`PolicyError`; callers must not silently treat it as no policy.
    """
    raw_path = os.path.abspath(str(path))
    policy_path = (
        raw_path
        if os.path.basename(raw_path).lower() == POLICY_FILENAME
        else os.path.join(raw_path, POLICY_FILENAME)
    )
    if not os.path.exists(policy_path):
        return None
    if not os.path.isfile(policy_path):
        raise PolicyError(f"policy path is not a regular file: {policy_path}")
    try:
        with open(policy_path, "rb") as handle:
            raw = handle.read()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PolicyError(f"cannot read policy {policy_path}: {exc}") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: _reject_json_constant(value),
        )
    except (json.JSONDecodeError, PolicyError) as exc:
        if isinstance(exc, PolicyError):
            raise
        raise PolicyError(f"{policy_path}: invalid JSON: {exc}") from exc
    policy = ReviewPolicy.from_dict(payload, source_hash=_sha256_bytes(raw))
    if registry is not None:
        policy.validate_registry(registry)
    return policy


def verify_workspace_file_quote(
    evidence: Optional[Mapping[str, object]],
    workspace_paths: Sequence[str],
) -> EvidenceVerification:
    """Verify an exact quote against an ordinary UTF-8 workspace file.

    Relative sources are resolved independently under every workspace root.
    Absolute sources are accepted only when their real path remains inside a
    root.  Symlinks, ambiguous matches, traversal, decoding failures, and quote
    mismatches all produce an unverified result rather than raising.
    """
    verifier = WORKSPACE_FILE_QUOTE_VERIFIER
    if not isinstance(evidence, Mapping):
        return EvidenceVerification.unverified(
            "missing_evidence", verifier=verifier)
    source = evidence.get("source")
    quote = evidence.get("quote")
    if not isinstance(source, str) or not source.strip():
        return EvidenceVerification.unverified(
            "invalid_source", verifier=verifier, evidence=evidence)
    if source != source.strip() or "\x00" in source:
        return EvidenceVerification.unverified(
            "invalid_source", verifier=verifier, evidence=evidence)
    if not isinstance(quote, str) or not quote:
        return EvidenceVerification.unverified(
            "invalid_quote", verifier=verifier, evidence=evidence)

    roots = _workspace_roots(workspace_paths)
    if not roots:
        return EvidenceVerification.unverified(
            "missing_workspace_root", verifier=verifier, evidence=evidence)
    source_is_absolute = (
        os.path.isabs(source)
        or PureWindowsPath(source).is_absolute()
        or PurePosixPath(source).is_absolute()
    )
    raw_candidates = [source] if source_is_absolute else [
        os.path.join(root, source) for root in roots
    ]
    candidates: List[str] = []
    for raw_candidate in raw_candidates:
        absolute = os.path.abspath(raw_candidate)
        real = os.path.realpath(absolute)
        if not any(_contained(real, root) for root in roots):
            continue
        if (_path_uses_symlink(absolute, roots)
                or not os.path.isfile(absolute)):
            continue
        if real not in candidates:
            candidates.append(real)
    if not candidates:
        return EvidenceVerification.unverified(
            "source_not_found_or_outside_workspace",
            verifier=verifier,
            evidence=evidence,
        )
    if len(candidates) != 1:
        return EvidenceVerification.unverified(
            "ambiguous_source", verifier=verifier, evidence=evidence)

    source_path = candidates[0]
    try:
        with open(source_path, "rb") as handle:
            raw = handle.read()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return EvidenceVerification.unverified(
            "source_read_failed", verifier=verifier, evidence=evidence)
    if quote not in text:
        return EvidenceVerification.unverified(
            "quote_not_found",
            verifier=verifier,
            evidence=evidence,
            source_content=raw,
        )
    return EvidenceVerification.verified_content(
        verifier=verifier,
        evidence=evidence,
        source_content=raw,
    )


def _floor_reasons(
    declaration: ReviewableSource,
    warnings_count: int,
    context: Optional[ProposalContext],
    policy: ReviewPolicy,
) -> List[str]:
    reasons: List[str] = []
    if requires_human_edge_review(declaration):
        reasons.append("explicit_edge_human_review_required")
    if declaration.runtime_role != "assertion":
        reasons.append("runtime_role_not_assertion")
    if declaration.status != "candidate":
        reasons.append("status_not_candidate")
    if not declaration.has_capability(AUTO_APPROVABLE_CAPABILITY):
        reasons.append("type_not_auto_approvable")
    if warnings_count != 0:
        reasons.append("lint_warnings_present")
    if not declaration.scope:
        reasons.append("scope_missing")
    elif declaration.scope.strip().lower() == "global":
        reasons.append("global_scope")
    if declaration.access_policy:
        reasons.append("access_policy_present")
    if declaration.force in {"hard", "strong"}:
        reasons.append("force_requires_human_review")
    relations = declaration.relations()
    for relation in sorted(DESTRUCTIVE_RELATIONS):
        if relations.get(relation):
            reasons.append(f"destructive_relation:{relation}")
    if context is None:
        reasons.append("proposal_context_missing")
        return reasons
    if context.client_id not in policy.trusted_clients:
        reasons.append("untrusted_client")
    proof = context.evidence_verification
    if proof is None or not proof.verified:
        reasons.append("evidence_not_verified")
    else:
        evidence = declaration.evidence
        if evidence is None:
            reasons.append("evidence_missing")
        else:
            if proof.evidence_digest != evidence_block_digest(evidence):
                reasons.append("evidence_attestation_mismatch")
            quote = evidence.get("quote")
            if (not isinstance(quote, str)
                    or proof.quote_digest != evidence_value_digest(quote)):
                reasons.append("quote_attestation_mismatch")
    return reasons


def requires_human_edge_review(declaration: ReviewableSource) -> bool:
    """Return the immutable Phase 6 floor for every reserved Edge capability."""
    return any(
        declaration.has_capability(capability)
        for capability in RESERVED_EDGE_CAPABILITIES
    )


def _input_snapshot(
    declaration: ReviewableSource,
    *,
    content_hash: str,
    warnings_count: int,
    context: Optional[ProposalContext],
    policy: ReviewPolicy,
    auto_approved_today: int,
    workspace_fingerprint: str,
    write_auto_granted: Optional[bool],
) -> dict:
    relations = {
        key: sorted(values)
        for key, values in sorted(declaration.relations().items())
        if values
    }
    return {
        "declaration": {
            "id": declaration.id,
            "kind": declaration.kind,
            "runtime_role": declaration.runtime_role,
            "status": declaration.status,
            "scope": declaration.scope or "",
            "force": declaration.force or "",
            "capabilities": sorted(declaration.capabilities),
            "has_access_policy": bool(declaration.access_policy),
            "relations": relations,
            "warnings_count": warnings_count,
            "content_hash": content_hash,
        },
        "context": context.as_dict() if context is not None else None,
        "policy": {
            "version": policy.version,
            "policy_hash": policy.source_hash,
            "auto_approved_today": auto_approved_today,
            "max_auto_approve_per_day": policy.max_auto_approve_per_day,
        },
        "workspace": {
            "fingerprint": workspace_fingerprint,
        },
        "deployment": {
            "write_auto_granted": write_auto_granted,
        },
    }


def _validate_match(value: object, *, rule_name: str) -> Dict[str, Tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise PolicyError(f"rule {rule_name!r} match must be an object")
    _reject_unknown(value, _MATCH_FIELDS, f"rule {rule_name!r} match")
    if "kind" not in value:
        raise PolicyError(
            f"rule {rule_name!r} match must name at least one explicit kind")
    normalized: Dict[str, Tuple[str, ...]] = {}
    for key, raw in value.items():
        normalized[key] = _string_tuple(
            raw, f"rule {rule_name!r} match.{key}", allow_empty=False)
    overlap = set(normalized.get("scope", ())) & set(
        normalized.get("scope_not", ()))
    if overlap:
        raise PolicyError(
            f"rule {rule_name!r} match.scope contradicts scope_not: "
            + ", ".join(sorted(overlap)))
    return normalized


def _validate_auto_merge_into(value: object) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise PolicyError("auto_merge_into must be a non-empty relative path")
    if "\x00" in value:
        raise PolicyError("auto_merge_into contains a NUL byte")
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    if os.path.isabs(value) or windows.is_absolute() or posix.is_absolute() or windows.drive:
        raise PolicyError("auto_merge_into must be relative to the workspace root")
    parts = tuple(windows.parts) + tuple(posix.parts)
    if ".." in parts:
        raise PolicyError("auto_merge_into must not contain parent traversal")
    if not value.lower().endswith(".mem"):
        raise PolicyError("auto_merge_into must name a .mem file")


def _workspace_roots(workspace_paths: Sequence[str]) -> List[str]:
    roots: List[str] = []
    for raw in workspace_paths:
        path = os.path.abspath(str(raw))
        root = path if os.path.isdir(path) else os.path.dirname(path)
        real = os.path.realpath(root)
        if real and real not in roots:
            roots.append(real)
    return roots


def _contained(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def _path_uses_symlink(path: str, roots: Sequence[str]) -> bool:
    """Return true unless path is lexically under a root with no symlink part."""
    absolute = os.path.abspath(path)
    for root in roots:
        try:
            if os.path.commonpath([absolute, root]) != root:
                continue
        except ValueError:
            continue
        relative = os.path.relpath(absolute, root)
        current = root
        for part in relative.split(os.sep):
            if part in ("", "."):
                continue
            current = os.path.join(current, part)
            if os.path.islink(current):
                return True
        return False
    return True


def _strict_object(pairs) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PolicyError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str):
    raise PolicyError(f"non-standard JSON constant {value!r} is not allowed")


def _reject_unknown(value: Mapping[str, object], allowed: frozenset, where: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PolicyError(f"{where} has unknown field(s): {', '.join(unknown)}")


def _string_tuple(value: object, field_name: str, *, allow_empty: bool) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise PolicyError(f"{field_name} must be a list of strings")
    if not allow_empty and not value:
        raise PolicyError(f"{field_name} must not be empty")
    if any(not isinstance(item, str) for item in value):
        raise PolicyError(f"{field_name} must contain only strings")
    result = tuple(_one_line(item) for item in value)
    if any(not item for item in result):
        raise PolicyError(f"{field_name} contains an empty value")
    if any(item != original for item, original in zip(result, value)):
        raise PolicyError(f"{field_name} values must be single-line and trimmed")
    if len(set(result)) != len(result):
        raise PolicyError(f"{field_name} contains duplicate values")
    return result


def _plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonical JSON data: {exc}") from exc


def _json_copy(value: object):
    return json.loads(_canonical_json(value))


def _unique(values: Sequence[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _one_line(value: object) -> str:
    return " ".join(str(value or "").split())
