"""Tests for the gated write pipeline (review queue)."""

import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from memdsl.cli import main as cli_main
from memdsl.model import Workspace
from memdsl.policy import (
    EvidenceVerification,
    POLICY_VERSION,
    PolicyError,
    ProposalContext,
    ReviewPolicy,
)
from memdsl.review import (
    AuditLogError,
    ReviewLockTimeout,
    ReviewStore,
    _exclusive_file_lock,
    staging_dir_for,
    workspace_fingerprint,
)

MEM_SOURCE = """\
module self

entity User {
  kind: Person
  canonical_name: "Sam"
  aliases: ["me", "Sam"]
  status: active
}

preference feedback.direct {
  subject: User
  claim: "Prefers direct feedback on drafts."
  force: strong
  scope: global
  status: active
  evidence {
    source: chat
    quote: "Just tell me what is wrong with it."
  }
}
"""

GOOD_PROPOSAL = """\
preference schedule.mornings_free {
  subject: User
  claim: "Keeps mornings free for deep work."
  force: strong
  scope: global
  status: active
  evidence {
    source: chat
    quote: "Mornings are for real work, keep them empty."
  }
}
"""

NO_EVIDENCE_PROPOSAL = """\
fact user.language {
  subject: User
  claim: "Primary language is Python."
  status: active
}
"""

BAD_SUBJECT_PROPOSAL = """\
fact pet.name {
  subject: User.Dog
  claim: "The dog is called Rex."
  status: active
  evidence {
    source: chat
    quote: "Rex chewed the cable again."
  }
}
"""


@pytest.fixture
def workspace_dir(tmp_path):
    path = tmp_path / "memory"
    path.mkdir()
    (path / "self.mem").write_text(MEM_SOURCE, encoding="utf-8")
    return path


@pytest.fixture
def store(workspace_dir):
    return ReviewStore(staging_dir_for([str(workspace_dir)]))


def load_ws(workspace_dir):
    return Workspace.load([str(workspace_dir)])


def test_staging_dir_defaults_next_to_workspace(workspace_dir):
    assert staging_dir_for([str(workspace_dir)]) == str(workspace_dir / ".memdsl")
    explicit = staging_dir_for([str(workspace_dir)], staging=str(workspace_dir / "q"))
    assert explicit == str(workspace_dir / "q")


def test_propose_and_staging_not_in_workspace(store, workspace_dir):
    result = store.create(load_ws(workspace_dir), GOOD_PROPOSAL, reason="test", client="pytest")
    assert result["ok"] is True
    assert result["status"] == "pending_review"
    assert result["declaration_id"] == "preference:schedule.mornings_free"
    # the staged proposal must NOT be loaded as workspace memory
    assert len(load_ws(workspace_dir).declarations) == 2
    # but it is on disk, with header + source
    text = open(result["path"], encoding="utf-8").read()
    assert text.startswith("# memdsl:proposal")
    assert "schedule.mornings_free" in text


def test_propose_fail_closed(store, workspace_dir):
    ws = load_ws(workspace_dir)

    missing = store.create(ws, NO_EVIDENCE_PROPOSAL)
    assert missing["ok"] is False
    assert any(e["code"] == "missing_evidence" for e in missing["errors"])

    dangling = store.create(ws, BAD_SUBJECT_PROPOSAL)
    assert dangling["ok"] is False
    assert any(e["code"] == "unresolved_symbol" for e in dangling["errors"])

    garbage = store.create(ws, "this is not a declaration {")
    assert garbage["ok"] is False
    assert any(e["code"] == "parse_error" for e in garbage["errors"])

    two = store.create(ws, GOOD_PROPOSAL + "\n" + NO_EVIDENCE_PROPOSAL)
    assert two["ok"] is False
    assert any(e["code"] == "single_declaration_required" for e in two["errors"])

    duplicate = store.create(ws, """\
preference feedback.direct {
  subject: User
  claim: "Prefers direct feedback."
  force: strong
  status: active
  evidence { source: chat quote: "Direct please." }
}
""")
    assert duplicate["ok"] is False
    assert any(e["code"] == "duplicate_declaration_id" for e in duplicate["errors"])

    assert store.list(status="pending") == []  # nothing staged by failed proposals


def test_approve_merges_and_audits(store, workspace_dir):
    ws = load_ws(workspace_dir)
    created = store.create(ws, GOOD_PROPOSAL, reason="deep work")
    pid = created["proposal_id"]
    into = workspace_dir / "approved.mem"

    result = store.approve(pid, ws, str(into))
    assert result["ok"] is True
    assert result["merged_into"] == str(into)

    # approved declaration is now live memory
    ws2 = load_ws(workspace_dir)
    assert ws2.by_id("preference:schedule.mornings_free") is not None
    merged_text = into.read_text(encoding="utf-8")
    assert f"# approved from proposal {pid}" in merged_text

    # proposal is marked approved and cannot be approved twice
    assert store.get(pid).status == "approved"
    again = store.approve(pid, ws2, str(into))
    assert again["ok"] is False
    assert again["status"] == "already_approved"

    # audit log carries propose + approve
    actions = [json.loads(line)["action"]
               for line in open(store.audit_path, encoding="utf-8")]
    assert actions == ["propose", "approve"]


def test_concurrent_approve_is_idempotent(store, workspace_dir):
    ws = load_ws(workspace_dir)
    created = store.create(ws, GOOD_PROPOSAL)
    pid = created["proposal_id"]
    into = workspace_dir / "approved.mem"

    def approve_once():
        return store.approve(pid, ws, str(into))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _n: approve_once(), range(2)))

    assert sum(result["ok"] for result in results) == 1
    assert into.read_text(encoding="utf-8").count(
        f"# approved from proposal {pid}") == 1
    actions = [json.loads(line)["action"]
               for line in open(store.audit_path, encoding="utf-8")]
    assert actions == ["propose", "approve"]


def test_approve_recovers_after_target_and_audit_commit(store, workspace_dir):
    ws = load_ws(workspace_dir)
    created = store.create(ws, GOOD_PROPOSAL)
    pid = created["proposal_id"]
    proposal = store.get(pid)
    into = workspace_dir / "approved.mem"
    into.write_text(
        f"# approved from proposal {pid} at 2026-07-10T00:00:00+00:00\n"
        + proposal.source,
        encoding="utf-8",
    )
    store._audit(
        "approve", pid, into=str(into),
        declaration="preference:schedule.mornings_free",
        by="human", forced=False)

    retry_target = workspace_dir / "wrong-retry-target.mem"
    result = store.approve(pid, ws, str(retry_target))
    assert result["ok"] is True
    assert result["recovered"] is True
    assert result["merged_into"] == str(into)
    assert not retry_target.exists()
    assert store.get(pid).status == "approved"
    assert into.read_text(encoding="utf-8").count(
        f"# approved from proposal {pid}") == 1
    actions = [json.loads(line)["action"]
               for line in open(store.audit_path, encoding="utf-8")]
    assert actions == ["propose", "approve"]


def test_approve_revalidates_against_current_workspace(store, workspace_dir):
    ws = load_ws(workspace_dir)
    created = store.create(ws, GOOD_PROPOSAL)
    pid = created["proposal_id"]
    # workspace changes after staging: same id gets declared directly
    (workspace_dir / "self.mem").write_text(
        MEM_SOURCE + "\n" + GOOD_PROPOSAL, encoding="utf-8")
    ws2 = load_ws(workspace_dir)
    result = store.approve(pid, ws2, str(workspace_dir / "approved.mem"))
    assert result["ok"] is False
    assert result["status"] == "stale_or_invalid"
    assert any(e["code"] == "duplicate_declaration_id" for e in result["errors"])
    assert store.get(pid).status == "pending"  # untouched


def test_reject(store, workspace_dir):
    created = store.create(load_ws(workspace_dir), GOOD_PROPOSAL)
    pid = created["proposal_id"]
    result = store.reject(pid, reason="not durable")
    assert result["ok"] is True
    assert store.get(pid).status == "rejected"
    assert store.get(pid).reject_reason == "not durable"
    assert store.list(status="pending") == []
    assert len(store.list(status="rejected")) == 1


def test_cli_review_roundtrip(workspace_dir, capsys):
    ws_path = str(workspace_dir)
    store = ReviewStore(staging_dir_for([ws_path]))
    created = store.create(load_ws(workspace_dir), GOOD_PROPOSAL, reason="cli test")
    pid = created["proposal_id"]

    assert cli_main(["review", "list", ws_path]) == 0
    out = capsys.readouterr().out
    assert pid in out and "preference:schedule.mornings_free" in out

    assert cli_main(["review", "show", ws_path, pid]) == 0
    out = capsys.readouterr().out
    assert "schedule.mornings_free" in out

    assert cli_main(["review", "approve", ws_path, pid]) == 0
    out = capsys.readouterr().out
    assert "approved" in out
    assert os.path.isfile(os.path.join(ws_path, "approved.mem"))

    # approved memory is queryable through the normal CLI
    assert cli_main(["query", ws_path, "-q", "deep work mornings"]) == 0
    out = capsys.readouterr().out
    assert "schedule.mornings_free" in out

    # unknown id fails cleanly
    assert cli_main(["review", "show", ws_path, "p-nope"]) == 1
    assert cli_main(["review", "reject", ws_path, "p-nope"]) == 1


AUTO_PROPOSAL = '''\
demo.note candidate.one {
  claim: "A verified candidate note."
  scope: "project-alpha"
  status: candidate
  evidence {
    source: evidence.txt
    quote: "Verified sentence."
  }
}
'''


def auto_proposal(name="candidate.one", *, relations="", status="candidate"):
    relation_block = f"\n  relations {{ {relations} }}" if relations else ""
    return f'''\
demo.note {name} {{
  claim: "A verified candidate note named {name}."
  scope: "project-alpha"
  status: {status}{relation_block}
  evidence {{
    source: evidence.txt
    quote: "Verified sentence."
  }}
}}
'''


@pytest.fixture
def policy_workspace(tmp_path):
    path = tmp_path / "policy-memory"
    path.mkdir()
    schema = path / "demo.memschema.json"
    schema.write_text(json.dumps({
        "name": "demo",
        "version": "1",
        "types": {
            "note": {
                "runtime_role": "assertion",
                "required_fields": ["claim", "scope", "evidence"],
                "capabilities": [
                    "searchable", "requires_evidence", "auto_approvable",
                ],
                "allow_extra_fields": True,
            },
        },
    }), encoding="utf-8")
    (path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v1",
        "schemas": [schema.name],
    }), encoding="utf-8")
    (path / "evidence.txt").write_text(
        "Before. Verified sentence. After.", encoding="utf-8")
    return path


def auto_policy(**overrides):
    payload = {
        "version": POLICY_VERSION,
        "default_route": "queue",
        "auto_merge_into": "auto-approved.mem",
        "sample_to_queue_percent": 0,
        "max_auto_approve_per_day": 10,
        "trusted_clients": ["pytest-host"],
        "rules": [{
            "name": "verified-demo-note",
            "route": "auto_approve",
            "match": {
                "kind": ["demo.note"],
                "evidence_verifier": ["workspace_file_quote"],
            },
        }],
    }
    payload.update(overrides)
    return ReviewPolicy.from_dict(payload)


def auto_policy_for_verifier(verifier):
    return auto_policy(rules=[{
        "name": "verified-demo-note",
        "route": "auto_approve",
        "match": {
            "kind": ["demo.note"],
            "evidence_verifier": [verifier],
        },
    }])


def policy_store(path):
    return ReviewStore(staging_dir_for([str(path)]))


def test_submit_without_policy_preserves_pending_semantics_and_routes(policy_workspace):
    store = policy_store(policy_workspace)
    result = store.submit([str(policy_workspace)], AUTO_PROPOSAL)
    assert result["status"] == "pending_review"
    assert result["route"] == "queued"
    assert result["rule"] == "no_policy"
    assert result["reason_codes"] == ["policy_missing"]
    assert store.get(result["proposal_id"]).status == "pending"
    assert [entry["action"] for entry in store.audit_entries()] == [
        "propose", "route",
    ]


def test_submit_auto_approves_through_full_audit_chain(policy_workspace):
    store = policy_store(policy_workspace)
    review_policy = auto_policy()
    result = store.submit(
        [str(policy_workspace)],
        AUTO_PROPOSAL,
        policy=review_policy,
        context=ProposalContext(client_id="pytest-host"),
        write_auto_granted=True,
    )
    assert result["status"] == "auto_approved"
    assert result["route"] == "auto_approved"
    assert result["eligible_route"] == "auto_approve"
    assert len(result["assessment_hash"]) == 64
    assert (policy_workspace / "auto-approved.mem").is_file()
    assert store.get(result["proposal_id"]).status == "approved"
    assert Workspace.load([str(policy_workspace)]).by_id(
        "demo.note:candidate.one") is not None

    audit = store.audit_entries()
    assert [entry["action"] for entry in audit] == [
        "propose", "route", "approve",
    ]
    route = audit[1]
    assert route["policy_hash"] == review_policy.source_hash
    assert route["assessment_hash"] == result["assessment_hash"]
    assert route["assessment"] == result["assessment"]
    assert route["workspace_fingerprint"]
    assert route["write_auto_granted"] is True
    approved = audit[2]
    assert approved["by"] == (
        f"policy:verified-demo-note@{review_policy.source_hash}")
    assert approved["forced"] is False
    assert approved["routing_rule"] == "verified-demo-note"
    assert "Verified sentence." not in (policy_workspace / ".memdsl" / "audit.log").read_text(
        encoding="utf-8")


def test_policy_without_explicit_write_key_is_shadow_only(policy_workspace):
    store = policy_store(policy_workspace)
    result = store.submit(
        [str(policy_workspace)],
        AUTO_PROPOSAL,
        policy=auto_policy(),
        context=ProposalContext(client_id="pytest-host"),
    )
    assert result["status"] == "pending_review"
    assert result["route"] == "queued"
    assert result["eligible_route"] == "auto_approve"
    assert "write_auto_not_granted" in result["reason_codes"]
    route = store.audit_entries()[1]
    assert route["decision"] == "queue"
    assert route["eligible_route"] == "auto_approve"
    assert route["write_auto_granted"] is False


def test_submit_exact_duplicate_is_no_op_for_pending_approved_and_workspace(
    policy_workspace,
):
    store = policy_store(policy_workspace)
    ctx = ProposalContext(client_id="pytest-host")
    pending = store.submit(
        [str(policy_workspace)], AUTO_PROPOSAL,
        policy=auto_policy(), context=ctx, write_auto_granted=False)
    duplicate = store.submit(
        [str(policy_workspace)], AUTO_PROPOSAL,
        policy=auto_policy(), context=ctx, write_auto_granted=False)
    assert duplicate["status"] == "no_op"
    assert duplicate["proposal_id"] == pending["proposal_id"]
    assert len(store.list(status="all")) == 1
    no_op = store.audit_entries()[-1]
    assert no_op["action"] == "no_op"
    assert no_op["attempt_id"] == duplicate["attempt_id"]

    approved_workspace = policy_workspace.parent / "approved-duplicate"
    approved_workspace.mkdir()
    for name in ("demo.memschema.json", "memdsl.json", "evidence.txt"):
        (approved_workspace / name).write_bytes((policy_workspace / name).read_bytes())
    approved_store = policy_store(approved_workspace)
    first = approved_store.submit(
        [str(approved_workspace)], AUTO_PROPOSAL,
        policy=auto_policy(), context=ctx, write_auto_granted=True)
    again = approved_store.submit(
        [str(approved_workspace)], AUTO_PROPOSAL,
        policy=auto_policy(), context=ctx, write_auto_granted=True)
    assert first["status"] == "auto_approved"
    assert again["status"] == "no_op"
    assert again["existing_status"] == "approved"

    direct_workspace = policy_workspace.parent / "direct-duplicate"
    direct_workspace.mkdir()
    for name in ("demo.memschema.json", "memdsl.json", "evidence.txt"):
        (direct_workspace / name).write_bytes((policy_workspace / name).read_bytes())
    (direct_workspace / "direct.mem").write_text(AUTO_PROPOSAL, encoding="utf-8")
    direct_store = policy_store(direct_workspace)
    direct = direct_store.submit(
        [str(direct_workspace)], AUTO_PROPOSAL,
        policy=auto_policy(), context=ctx, write_auto_granted=True)
    assert direct["status"] == "no_op"
    assert direct["proposal_id"] == ""
    assert direct["duplicate_of"] == "demo.note:candidate.one"
    assert direct_store.list(status="all") == []


def test_daily_limit_reserves_routes_and_queues_later_proposals(policy_workspace):
    store = policy_store(policy_workspace)
    review_policy = auto_policy(max_auto_approve_per_day=1)
    ctx = ProposalContext(client_id="pytest-host")
    first = store.submit(
        [str(policy_workspace)], auto_proposal("candidate.one"),
        policy=review_policy, context=ctx, write_auto_granted=True)
    second = store.submit(
        [str(policy_workspace)], auto_proposal("candidate.two"),
        policy=review_policy, context=ctx, write_auto_granted=True)
    assert first["status"] == "auto_approved"
    assert second["status"] == "pending_review"
    assert second["reason_codes"] == ["daily_limit_reached"]
    assert store.get(second["proposal_id"]).status == "pending"


def test_workspace_change_after_route_falls_back_to_pending(
    policy_workspace, monkeypatch,
):
    store = policy_store(policy_workspace)
    original_approve = store.approve

    def mutate_then_approve(*args, **kwargs):
        (policy_workspace / "external-edit.mem").write_text(
            'goal external.edit { claim: "Changed concurrently." status: candidate }',
            encoding="utf-8",
        )
        return original_approve(*args, **kwargs)

    monkeypatch.setattr(store, "approve", mutate_then_approve)
    result = store.submit(
        [str(policy_workspace)], AUTO_PROPOSAL,
        policy=auto_policy(),
        context=ProposalContext(client_id="pytest-host"),
        write_auto_granted=True,
    )
    assert result["status"] == "pending_review"
    assert result["approval_error"]["status"] == "workspace_changed"
    assert store.get(result["proposal_id"]).status == "pending"
    assert not (policy_workspace / "auto-approved.mem").exists()
    assert store.audit_entries()[-1]["action"] == "route_fallback"


def test_custom_verifier_rechecks_fresh_evidence_before_target_write(
    policy_workspace,
):
    store = policy_store(policy_workspace)
    evidence_path = policy_workspace / "evidence.txt"
    verifier_calls = []

    def custom_file_quote(evidence, workspace_paths):
        verifier_calls.append((evidence, tuple(workspace_paths)))
        content = evidence_path.read_text(encoding="utf-8")
        quote = evidence.get("quote") if isinstance(evidence, dict) else None
        if not isinstance(quote, str) or quote not in content:
            return EvidenceVerification.unverified(
                "quote_not_found",
                verifier="custom_file_quote",
                evidence=evidence,
                source_content=content,
            )
        proof = EvidenceVerification.verified_content(
            verifier="custom_file_quote",
            evidence=evidence,
            source_content=content,
        )
        if len(verifier_calls) == 1:
            evidence_path.write_text(
                "Evidence was changed after the routing proof.", encoding="utf-8")
        return proof

    result = store.submit(
        [str(policy_workspace)],
        AUTO_PROPOSAL,
        policy=auto_policy_for_verifier("custom_file_quote"),
        context=ProposalContext(client_id="pytest-host"),
        write_auto_granted=True,
        evidence_verifier=custom_file_quote,
    )

    assert len(verifier_calls) == 2
    assert result["status"] == "pending_review"
    assert result["route"] == "queued"
    assert result["approval_error"]["status"] == "evidence_changed"
    assert store.get(result["proposal_id"]).status == "pending"
    assert not (policy_workspace / "auto-approved.mem").exists()
    assert store.audit_entries()[-1]["action"] == "route_fallback"


def test_preverified_custom_context_without_matching_callback_falls_back(
    policy_workspace,
):
    store = policy_store(policy_workspace)
    evidence = {
        "source": "evidence.txt",
        "quote": "Verified sentence.",
    }
    proof = EvidenceVerification.verified_content(
        verifier="custom_host",
        evidence=evidence,
        source_content="Before. Verified sentence. After.",
    )

    result = store.submit(
        [str(policy_workspace)],
        AUTO_PROPOSAL,
        policy=auto_policy_for_verifier("custom_host"),
        context=ProposalContext(
            client_id="pytest-host", evidence_verification=proof),
        write_auto_granted=True,
    )

    assert result["status"] == "pending_review"
    assert result["approval_error"]["status"] == "evidence_changed"
    assert not (policy_workspace / "auto-approved.mem").exists()


def test_fingerprint_changes_for_memory_manifest_and_schema(policy_workspace):
    paths = [str(policy_workspace)]
    ws = Workspace.load(paths)
    original = workspace_fingerprint(paths, workspace=ws)
    (policy_workspace / "new.mem").write_text(
        'goal new.item { claim: "New." status: candidate }', encoding="utf-8")
    changed_memory = workspace_fingerprint(paths, workspace=ws)
    assert changed_memory != original

    (policy_workspace / "new.mem").unlink()
    manifest = policy_workspace / "memdsl.json"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    changed_manifest = workspace_fingerprint(paths, workspace=ws)
    assert changed_manifest != original

    schema = policy_workspace / "demo.memschema.json"
    schema.write_text(schema.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    changed_schema = workspace_fingerprint(paths, workspace=ws)
    assert changed_schema != changed_manifest


def test_auto_target_rejects_internal_directory_and_symlink_escape(
    policy_workspace,
):
    ctx = ProposalContext(client_id="pytest-host")
    store = policy_store(policy_workspace)
    internal = auto_policy(auto_merge_into=".memdsl/auto.mem")
    with pytest.raises(PolicyError, match="internal"):
        store.submit(
            [str(policy_workspace)], AUTO_PROPOSAL,
            policy=internal, context=ctx, write_auto_granted=True)
    assert store.list(status="all") == []

    directory = policy_workspace / "already.mem"
    directory.mkdir()
    with pytest.raises(PolicyError, match="directory"):
        store.submit(
            [str(policy_workspace)], AUTO_PROPOSAL,
            policy=auto_policy(auto_merge_into="already.mem"),
            context=ctx, write_auto_granted=True)

    outside = policy_workspace.parent / "outside-target"
    outside.mkdir()
    link = policy_workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this host")
    with pytest.raises(PolicyError, match="outside"):
        store.submit(
            [str(policy_workspace)], AUTO_PROPOSAL,
            policy=auto_policy(auto_merge_into="linked/escape.mem"),
            context=ctx, write_auto_granted=True)


def test_malformed_audit_blocks_policy_submit_but_legacy_create_is_tolerant(
    policy_workspace,
):
    store = policy_store(policy_workspace)
    os.makedirs(store.staging_dir, exist_ok=True)
    with open(store.audit_path, "w", encoding="utf-8") as handle:
        handle.write("{broken\n")
    with pytest.raises(AuditLogError) as exc:
        store.submit(
            [str(policy_workspace)], AUTO_PROPOSAL,
            policy=auto_policy(),
            context=ProposalContext(client_id="pytest-host"),
            write_auto_granted=True,
        )
    assert exc.value.line == 1
    assert store.list(status="all") == []
    assert store.audit_entries(strict=False) == []

    legacy = store.create(Workspace.load([str(policy_workspace)]), AUTO_PROPOSAL)
    assert legacy["status"] == "pending_review"


def test_approve_audit_metadata_cannot_override_reserved_fields(
    store, workspace_dir,
):
    ws = load_ws(workspace_dir)
    created = store.create(ws, GOOD_PROPOSAL)
    target = workspace_dir / "reserved.mem"
    with pytest.raises(ValueError, match="reserved"):
        store.approve(
            created["proposal_id"], ws, str(target),
            audit_extra={"action": "forged"})
    assert not target.exists()
    assert store.get(created["proposal_id"]).status == "pending"


def test_destructive_revision_always_queues_then_can_be_human_approved(
    policy_workspace,
):
    store = policy_store(policy_workspace)
    ctx = ProposalContext(client_id="pytest-host")
    first = store.submit(
        [str(policy_workspace)], AUTO_PROPOSAL,
        policy=auto_policy(), context=ctx, write_auto_granted=True)
    assert first["status"] == "auto_approved"

    revision = auto_proposal(
        "candidate.revision",
        relations=(
            "supersedes: [candidate.one]\n"
            "    revision_of: [candidate.one]"),
    )
    queued = store.submit(
        [str(policy_workspace)], revision,
        policy=auto_policy(), context=ctx, write_auto_granted=True)
    assert queued["status"] == "pending_review"
    assert any(code.startswith("destructive_relation:")
               for code in queued["reason_codes"])

    current = Workspace.load([str(policy_workspace)])
    human = store.approve(
        queued["proposal_id"], current,
        str(policy_workspace / "human-reviewed.mem"))
    assert human["status"] == "approved"
    reloaded = Workspace.load([str(policy_workspace)])
    assert "candidate.one" in reloaded.superseded_ids()


def test_authoritative_registry_policy_error_happens_before_staging(
    policy_workspace,
):
    stale = Workspace.load([str(policy_workspace)])
    schema_path = policy_workspace / "demo.memschema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["types"] = {}
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    store = policy_store(policy_workspace)

    with pytest.raises(PolicyError, match="unknown memory type"):
        store.submit(
            stale,
            AUTO_PROPOSAL,
            workspace_paths=[str(policy_workspace)],
            policy=auto_policy(),
            context=ProposalContext(client_id="pytest-host"),
            write_auto_granted=True,
        )

    assert store.list(status="all") == []
    assert store.audit_entries(strict=True) == []


def test_forged_approval_marker_without_exact_content_fails_closed(
    store, workspace_dir,
):
    ws = load_ws(workspace_dir)
    created = store.create(ws, GOOD_PROPOSAL)
    proposal_id = created["proposal_id"]
    target = workspace_dir / "forged.mem"
    target.write_text(
        f"# approved from proposal {proposal_id} at "
        "2026-07-10T00:00:00+00:00\n",
        encoding="utf-8",
    )

    result = store.approve(proposal_id, ws, str(target))
    assert result["ok"] is False
    assert result["status"] == "target_marker_mismatch"
    assert store.get(proposal_id).status == "pending"
    assert [entry["action"] for entry in store.audit_entries()] == ["propose"]


def test_approval_marker_hash_must_match_normalized_proposal(
    store, workspace_dir,
):
    ws = load_ws(workspace_dir)
    created = store.create(ws, GOOD_PROPOSAL)
    proposal_id = created["proposal_id"]
    proposal = store.get(proposal_id)
    target = workspace_dir / "wrong-hash.mem"
    target.write_text(
        f"# approved from proposal {proposal_id} content {'0' * 64} at "
        "2026-07-10T00:00:00+00:00\n" + proposal.source,
        encoding="utf-8",
    )

    result = store.approve(proposal_id, ws, str(target))
    assert result["ok"] is False
    assert result["status"] == "target_marker_mismatch"
    assert store.get(proposal_id).status == "pending"


def test_routed_auto_retry_is_explicitly_downgraded_not_no_op(
    policy_workspace, monkeypatch,
):
    store = policy_store(policy_workspace)
    original_approve = store.approve

    def crash_before_approve(*_args, **_kwargs):
        raise RuntimeError("simulated crash after route")

    monkeypatch.setattr(store, "approve", crash_before_approve)
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.submit(
            [str(policy_workspace)],
            AUTO_PROPOSAL,
            policy=auto_policy(),
            context=ProposalContext(client_id="pytest-host"),
            write_auto_granted=True,
        )
    proposal = store.list(status="pending")[0]
    assert [entry["action"] for entry in store.audit_entries()] == [
        "propose", "route",
    ]

    monkeypatch.setattr(store, "approve", original_approve)
    retry = store.submit(
        [str(policy_workspace)],
        AUTO_PROPOSAL,
        policy=auto_policy(),
        context=ProposalContext(client_id="pytest-host"),
        write_auto_granted=True,
    )
    assert retry["status"] == "pending_review"
    assert retry["route"] == "queued"
    assert retry["proposal_id"] == proposal.id
    assert retry["reason_codes"] == ["retry_after_routed_auto_approve"]
    assert [entry["action"] for entry in store.audit_entries()] == [
        "propose", "route", "route_fallback",
    ]
    assert not (policy_workspace / "auto-approved.mem").exists()


@pytest.mark.parametrize(
    "entry",
    [
        {"ts": "2026-07-10T00:00:00+00:00", "action": "unknown",
         "proposal_id": "p-1"},
        {"ts": "2026-07-10T00:00:00+00:00", "action": "route",
         "proposal_id": "p-1", "decision": "auto_approve"},
        {"ts": "2026-07-10T00:00:00+00:00", "action": "approve",
         "proposal_id": "p-1", "by": "human", "into": "x.mem",
         "declaration": "fact:x", "forced": "false"},
        {"ts": "2026-07-10T00:00:00+00:00", "action": "post_review",
         "proposal_id": "p-1", "by": "human", "verdict": "approve",
         "assessment_hash": "0" * 64},
    ],
)
def test_strict_audit_rejects_unknown_or_malformed_action_envelopes(
    tmp_path, entry,
):
    store = ReviewStore(str(tmp_path / "staging"))
    os.makedirs(store.staging_dir, exist_ok=True)
    with open(store.audit_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    with pytest.raises(AuditLogError) as exc:
        store.audit_entries(strict=True)
    assert exc.value.line == 1
    assert store.audit_entries(strict=False) == []


def test_record_audit_rejects_unknown_operational_action(tmp_path):
    store = ReviewStore(str(tmp_path / "staging"))
    with pytest.raises(ValueError, match="unknown audit action"):
        store.record_audit("custom_event")


def test_review_lock_timeout_is_bounded_and_structured(tmp_path):
    lock_path = str(tmp_path / "review.lock")
    with _exclusive_file_lock(lock_path):
        with pytest.raises(ReviewLockTimeout) as exc:
            with _exclusive_file_lock(
                lock_path, timeout_seconds=0.03, poll_interval=0.005):
                pass
    assert exc.value.path == os.path.abspath(lock_path)
    assert exc.value.timeout_seconds == 0.03


def _write_audit_entries(store, entries):
    with open(store.audit_path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


def test_strict_audit_recomputes_route_assessment_hash(policy_workspace):
    store = policy_store(policy_workspace)
    store.submit(
        [str(policy_workspace)],
        AUTO_PROPOSAL,
        policy=auto_policy(),
        context=ProposalContext(client_id="pytest-host"),
        write_auto_granted=False,
    )
    entries = store.audit_entries(strict=True)
    route = entries[1]
    route["assessment"]["input_snapshot"]["declaration"]["scope"] = "tampered"
    _write_audit_entries(store, entries)

    with pytest.raises(AuditLogError, match="assessment_hash.*content"):
        store.audit_entries(strict=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("decision", "auto_approve"),
        ("rule", "different-rule"),
        ("content_hash", "e" * 64),
        ("policy_hash", "f" * 64),
    ],
)
def test_strict_audit_rejects_route_envelope_snapshot_mismatch(
    policy_workspace, field, value,
):
    store = policy_store(policy_workspace)
    store.submit(
        [str(policy_workspace)],
        AUTO_PROPOSAL,
        policy=auto_policy(),
        context=ProposalContext(client_id="pytest-host"),
        write_auto_granted=False,
    )
    entries = store.audit_entries(strict=True)
    entries[1][field] = value
    _write_audit_entries(store, entries)

    with pytest.raises(AuditLogError, match="does not match assessment"):
        store.audit_entries(strict=True)


def test_strict_audit_recomputes_no_op_assessment_hash(policy_workspace):
    store = policy_store(policy_workspace)
    kwargs = {
        "policy": auto_policy(),
        "context": ProposalContext(client_id="pytest-host"),
        "write_auto_granted": False,
    }
    store.submit([str(policy_workspace)], AUTO_PROPOSAL, **kwargs)
    store.submit([str(policy_workspace)], AUTO_PROPOSAL, **kwargs)
    entries = store.audit_entries(strict=True)
    no_op = entries[-1]
    assert no_op["action"] == "no_op"
    no_op["assessment"]["rule"] = "tampered-duplicate"
    _write_audit_entries(store, entries)

    with pytest.raises(AuditLogError, match="assessment_hash.*content"):
        store.audit_entries(strict=True)


def test_strict_audit_accepts_historical_snapshot_without_embedded_hash(
    policy_workspace,
):
    store = policy_store(policy_workspace)
    store.submit(
        [str(policy_workspace)],
        AUTO_PROPOSAL,
        policy=auto_policy(),
        context=ProposalContext(client_id="pytest-host"),
        write_auto_granted=False,
    )
    entries = store.audit_entries(strict=True)
    route = entries[1]
    route["assessment"].pop("assessment_hash")
    route["eligible_assessment"].pop("assessment_hash")
    _write_audit_entries(store, entries)

    assert store.audit_entries(strict=True)[1]["action"] == "route"
