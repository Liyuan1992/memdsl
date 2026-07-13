"""Tests for fail-closed, host-attested review policy routing."""

import json
import hashlib
from dataclasses import replace

import pytest

from memdsl.model import Declaration
from memdsl.policy import (
    POLICY_VERSION,
    WORKSPACE_FILE_QUOTE_VERIFIER,
    EvidenceVerification,
    PolicyError,
    ProposalContext,
    ReviewPolicy,
    RoutingDecision,
    declaration_content_hash,
    deterministic_sample_bucket,
    load_policy,
    verify_workspace_file_quote,
)
from memdsl.schema import TypeDescriptor, TypeRegistry


EVIDENCE = {"source": "evidence.txt", "quote": "Verified sentence."}


def descriptor(*, role="assertion", auto=True):
    capabilities = {"searchable"}
    if auto:
        capabilities.add("auto_approvable")
    return TypeDescriptor(
        name="demo.note",
        runtime_role=role,
        capabilities=frozenset(capabilities),
    )


def declaration(*, role="assertion", auto=True, **overrides):
    fields = {
        "claim": "A verified candidate note.",
        "scope": "project-alpha",
        "status": "candidate",
        "evidence": dict(EVIDENCE),
    }
    fields.update(overrides)
    return Declaration(
        kind="demo.note",
        name="candidate.one",
        fields=fields,
        file="proposal.mem",
        line=1,
        type_descriptor=descriptor(role=role, auto=auto),
    )


def context(*, client="trusted-host", evidence=EVIDENCE):
    proof = EvidenceVerification.verified_content(
        verifier=WORKSPACE_FILE_QUOTE_VERIFIER,
        evidence=evidence,
        source_content="prefix Verified sentence. suffix",
    )
    return ProposalContext(client=client, evidence=proof)


def policy_payload(**overrides):
    payload = {
        "version": POLICY_VERSION,
        "default_route": "queue",
        "auto_merge_into": "auto-approved.mem",
        "sample_to_queue_percent": 0,
        "max_auto_approve_per_day": 10,
        "trusted_clients": ["trusted-host"],
        "rules": [{
            "name": "safe-demo-notes",
            "route": "auto_approve",
            "tier": "T0",
            "match": {
                "kind": ["demo.note"],
                "evidence_verifier": [WORKSPACE_FILE_QUOTE_VERIFIER],
            },
        }],
    }
    payload.update(overrides)
    return payload


def policy(**overrides):
    return ReviewPolicy.from_dict(policy_payload(**overrides))


def assess(decl=None, *, review_policy=None, ctx=None, warnings=0, count=0):
    return (review_policy or policy()).assess(
        decl or declaration(),
        warnings_count=warnings,
        context=ctx or context(),
        auto_approved_today=count,
    )


def test_safe_floor_and_explicit_rule_allow_candidate_assertion():
    result = assess()
    assert result.decision is RoutingDecision.AUTO_APPROVE
    assert result.rule == "safe-demo-notes"
    assert result.reason_codes == ("safe_floor_passed", "policy_rule_matched")
    assert len(result.policy_hash) == 64
    assert result.input_snapshot["context"]["client"] == "trusted-host"
    assert result.input_snapshot["context"]["evidence"]["verified"] is True


@pytest.mark.parametrize(
    ("decl", "ctx", "warnings", "reason"),
    [
        (declaration(role="question"), context(), 0, "runtime_role_not_assertion"),
        (declaration(status="active"), context(), 0, "status_not_candidate"),
        (declaration(auto=False), context(), 0, "type_not_auto_approvable"),
        (declaration(), context(), 1, "lint_warnings_present"),
        (declaration(scope=""), context(), 0, "scope_missing"),
        (declaration(scope="global"), context(), 0, "global_scope"),
        (declaration(access_policy={"readers": ["private"]}), context(), 0,
         "access_policy_present"),
        (declaration(force="hard"), context(), 0, "force_requires_human_review"),
        (declaration(force="strong"), context(), 0, "force_requires_human_review"),
        (declaration(relations={"supersedes": ["demo.note:old"]}), context(), 0,
         "destructive_relation:supersedes"),
        (declaration(relations={"conflicts_with": ["demo.note:old"]}), context(), 0,
         "destructive_relation:conflicts_with"),
        (declaration(relations={"revision_of": ["demo.note:old"]}), context(), 0,
         "destructive_relation:revision_of"),
        (declaration(), context(client="other-host"), 0, "untrusted_client"),
        (declaration(), None, 0, "proposal_context_missing"),
        (declaration(), ProposalContext(client="trusted-host"), 0,
         "evidence_not_verified"),
    ],
)
def test_non_configurable_floor_routes_unsafe_inputs_to_human_review(
    decl, ctx, warnings, reason,
):
    result = policy().assess(
        decl, warnings_count=warnings, context=ctx, auto_approved_today=0)
    assert result.decision is RoutingDecision.QUEUE
    assert result.rule.startswith("floor:")
    assert reason in result.reason_codes


def test_evidence_attestation_is_bound_to_complete_proposal_evidence():
    trusted = context()
    changed = declaration(evidence={
        "source": "different.txt",
        "quote": "Verified sentence.",
    })
    result = policy().assess(changed, warnings_count=0, context=trusted)
    assert result.decision is RoutingDecision.QUEUE
    assert "evidence_attestation_mismatch" in result.reason_codes


def test_rules_only_narrow_and_floor_cannot_be_bypassed():
    malicious = policy_payload(rules=[{
        "name": "try-constraint",
        "route": "auto_approve",
        "match": {"kind": ["demo.note"]},
    }])
    result = ReviewPolicy.from_dict(malicious).assess(
        declaration(role="constraint"), warnings_count=0, context=context())
    assert result.decision is RoutingDecision.QUEUE
    assert "runtime_role_not_assertion" in result.reason_codes

    other_kind = replace(declaration(), kind="demo.other")
    result = assess(other_kind)
    assert result.decision is RoutingDecision.QUEUE
    assert result.rule == "default"


def test_daily_limit_zero_disables_and_positive_limit_is_enforced():
    disabled = policy(max_auto_approve_per_day=0)
    result = assess(review_policy=disabled)
    assert result.decision is RoutingDecision.QUEUE
    assert result.reason_codes == ("daily_limit_reached",)

    enabled = policy(max_auto_approve_per_day=1)
    assert assess(review_policy=enabled, count=0).decision is RoutingDecision.AUTO_APPROVE
    assert assess(review_policy=enabled, count=1).decision is RoutingDecision.QUEUE


def test_sampling_uses_normalized_content_and_full_policy_hash():
    first = declaration()
    same = replace(first, fields={
        "evidence": {"quote": "Verified sentence.", "source": "evidence.txt"},
        "status": "candidate",
        "scope": "project-alpha",
        "claim": "A verified candidate note.",
    })
    assert declaration_content_hash(first) == declaration_content_hash(same)
    content_hash = declaration_content_hash(first)
    bucket = deterministic_sample_bucket(content_hash, policy().source_hash)
    assert bucket == deterministic_sample_bucket(content_hash, policy().source_hash)

    sampled = policy(sample_to_queue_percent=100)
    result = assess(review_policy=sampled)
    assert result.decision is RoutingDecision.QUEUE
    assert result.rule == "sample:safe-demo-notes"
    assert result.reason_codes == ("sampled_to_queue",)
    assert result.sample_bucket == deterministic_sample_bucket(
        result.content_hash, sampled.source_hash)

    un_sampled = policy(sample_to_queue_percent=0)
    assert assess(review_policy=un_sampled).decision is RoutingDecision.AUTO_APPROVE


def test_strict_loader_and_registry_validation(tmp_path):
    assert load_policy(str(tmp_path)) is None
    path = tmp_path / "policy.json"
    raw = json.dumps(policy_payload(), indent=2)
    path.write_text(raw, encoding="utf-8")
    loaded = load_policy(str(tmp_path))
    assert loaded.source_hash == hashlib.sha256(path.read_bytes()).hexdigest()

    registry = TypeRegistry.standard()
    with pytest.raises(PolicyError, match="unknown memory type"):
        load_policy(str(path), registry=registry)
    registry.register(descriptor())
    assert load_policy(str(path), registry=registry).rules[0].name == "safe-demo-notes"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({**policy_payload(), "unknown": True}, "unknown field"),
        (policy_payload(default_route="auto_approve"), "default_route"),
        (policy_payload(auto_merge_into="../escape.mem"), "parent traversal"),
        (policy_payload(auto_merge_into="not-memory.txt"), ".mem"),
        (policy_payload(sample_to_queue_percent=True), "integer"),
        (policy_payload(max_auto_approve_per_day=-1), ">= 0"),
        (policy_payload(trusted_clients=["trusted-host", "trusted-host"]), "duplicate"),
        (policy_payload(rules=[{
            "name": "missing-kind", "route": "auto_approve", "match": {},
        }]), "explicit kind"),
        (policy_payload(rules=[{
            "name": "unknown-match", "route": "auto_approve",
            "match": {"kind": ["demo.note"], "evidence_present": True},
        }]), "unknown field"),
        (policy_payload(rules=[{
            "name": "contradictory-scope", "route": "auto_approve",
            "match": {
                "kind": ["demo.note"],
                "scope": ["x"],
                "scope_not": ["x"],
            },
        }]), "contradicts"),
        (policy_payload(rules=[{
            "name": "untrusted-rule-client", "route": "auto_approve",
            "match": {"kind": ["demo.note"], "client": ["other"]},
        }]), "not a subset"),
    ],
)
def test_policy_schema_is_fail_closed(payload, message):
    with pytest.raises(PolicyError, match=message):
        ReviewPolicy.from_dict(payload)


@pytest.mark.parametrize(
    "raw",
    [
        "{broken",
        '{"version":"a","version":"b"}',
        '{"version":NaN}',
    ],
)
def test_loader_rejects_bad_or_nonstandard_json(tmp_path, raw):
    (tmp_path / "policy.json").write_text(raw, encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(str(tmp_path))


def test_workspace_file_quote_verifier_is_contained_exact_and_utf8(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence_file = workspace / "evidence.txt"
    evidence_file.write_text(
        "Before. Verified sentence. After.", encoding="utf-8")
    proof = verify_workspace_file_quote(EVIDENCE, [str(workspace)])
    assert proof.verified is True
    assert proof.verifier == WORKSPACE_FILE_QUOTE_VERIFIER
    assert all(len(value) == 64 for value in (
        proof.source_digest, proof.quote_digest, proof.evidence_digest))

    mismatch = verify_workspace_file_quote(
        {"source": "evidence.txt", "quote": "Not present."}, [str(workspace)])
    assert mismatch.verified is False
    assert mismatch.reason == "quote_not_found"

    outside = tmp_path / "outside.txt"
    outside.write_text("Verified sentence.", encoding="utf-8")
    escaped = verify_workspace_file_quote(
        {"source": "../outside.txt", "quote": "Verified sentence."},
        [str(workspace)],
    )
    assert escaped.verified is False
    assert escaped.reason == "source_not_found_or_outside_workspace"

    (workspace / "binary.txt").write_bytes(b"\xff\xfe")
    binary = verify_workspace_file_quote(
        {"source": "binary.txt", "quote": "x"}, [str(workspace)])
    assert binary.verified is False
    assert binary.reason == "source_read_failed"


def test_auto_merge_target_must_remain_in_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    review_policy = policy(auto_merge_into="generated/approved.mem")
    assert review_policy.resolve_auto_merge_into([str(workspace)]) == str(
        workspace / "generated" / "approved.mem")
    with pytest.raises(PolicyError, match="workspace_paths"):
        review_policy.resolve_auto_merge_into([])


def test_workspace_file_quote_rejects_symlink_components(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    real = workspace / "real"
    real.mkdir()
    (real / "evidence.txt").write_text(
        "Verified sentence.", encoding="utf-8")
    link = workspace / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this host")
    proof = verify_workspace_file_quote(
        {"source": "linked/evidence.txt", "quote": "Verified sentence."},
        [str(workspace)],
    )
    assert proof.verified is False
    assert proof.reason == "source_not_found_or_outside_workspace"
