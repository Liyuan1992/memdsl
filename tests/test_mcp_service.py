"""Tests for the SDK-free MCP service layer."""

import json
import os

import pytest

from memdsl.mcp_service import (
    MCPScopeError,
    MemdslMCPService,
    parse_scopes,
)
from memdsl.policy import EvidenceVerification, ProposalContext

MEM_SOURCE = """\
module self

entity User {
  kind: Person
  canonical_name: "Sam"
  aliases: ["me", "Sam"]
  status: active
}

boundary schedule.no_meetings_before_10 {
  subject: User
  rule: "Never schedule meetings before 10:00."
  force: hard
  scope: global
  exceptions: [emergency]
  status: active
  guard {
    when_any: ["meeting", "schedule"]
    deny_regex: ["\\\\b0?[0-9]:[0-5][0-9]\\\\b"]
  }
  evidence {
    source: chat
    quote: "Please never book me before ten."
  }
}

preference feedback.direct {
  subject: User
  claim: "Prefers direct feedback on drafts."
  force: strong
  scope: global
  confidence: high
  status: active
  evidence {
    source: chat
    quote: "Just tell me what is wrong with it."
  }
}

state project.phase {
  subject: User
  claim: "Project is in the review phase."
  as_of: 2026-06-28
  scope: global
  status: active
  evidence {
    source: chat
    quote: "We moved into review last week."
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
def service(workspace_dir):
    return MemdslMCPService([str(workspace_dir)])


def test_parse_scopes_default_and_explicit():
    assert parse_scopes(None) == {"read:summary", "read:search", "write:candidate"}
    assert parse_scopes("read:summary, ,read:search") == {"read:summary", "read:search"}
    assert parse_scopes(["all"]) == {"all"}


def test_missing_workspace_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        MemdslMCPService([str(tmp_path / "nope")])
    with pytest.raises(ValueError):
        MemdslMCPService([])


def test_status_counts(service):
    payload = service.status()
    assert payload["ok"] is True
    assert payload["schema_version"] == "memdsl.mcp.status.v1"
    assert payload["files"] == 1
    assert payload["declarations"] == 4
    assert payload["kinds"]["boundary"] == 1
    assert "boundary" in payload["registered_types"]


def test_type_registry_is_exposed(service):
    payload = service.list_types()
    assert payload["ok"] is True
    assert payload["schema_version"] == "memdsl.mcp.types.v1"
    boundary = next(item for item in payload["types"] if item["name"] == "boundary")
    assert boundary["runtime_role"] == "constraint"


def test_query_layers_and_boundary_text(service):
    payload = service.query("can you book a meeting tomorrow morning")
    assert payload["ok"] is True
    pack = payload["evidence_pack"]
    must_ids = [d["id"] for d in pack["must"]]
    assert "boundary:schedule.no_meetings_before_10" in must_ids
    assert pack["must"][0]["evidence"]["quote"]
    assert "MUST" in payload["rendered_text"]
    assert payload["boundary"]
    assert payload["next_actions"]


def test_query_requires_text(service):
    payload = service.query("   ")
    assert payload["ok"] is False
    assert payload["status"] == "invalid"


NARROW_SCOPE_SOURCE = """\
module work

entity Repo {
  kind: Repository
  canonical_name: "memdsl"
  aliases: ["the repo"]
  status: active
}

boundary git.no_force_push {
  subject: Repo
  rule: "Never force-push the main branch."
  force: hard
  scope: repository
  exceptions: []
  status: active
  evidence {
    source: chat
    quote: "Never force-push main."
  }
}
"""


def _narrow_service(tmp_path):
    path = tmp_path / "narrow"
    path.mkdir()
    (path / "work.mem").write_text(NARROW_SCOPE_SOURCE, encoding="utf-8")
    return MemdslMCPService([str(path)])


def test_query_no_match_returns_vocabulary_guidance(tmp_path):
    svc = _narrow_service(tmp_path)
    payload = svc.query("weekend hiking plans")
    assert payload["ok"] is True
    assert payload["status"] == "no_match"
    vocab = payload["vocabulary"]
    assert vocab["subjects"][0]["symbol"] == "Repo"
    assert "repository" in vocab["scopes"]
    assert "boundary" in vocab["types"]
    assert payload["evidence_pack"]["search_trace"]["hits"] == 0
    assert any("vocabulary" in action for action in payload["next_actions"])


def test_query_filter_exclusion_is_reported_not_silent(tmp_path):
    svc = _narrow_service(tmp_path)
    payload = svc.query("force push main branch", types=["preference"])
    assert payload["status"] == "no_match"
    trace = payload["evidence_pack"]["search_trace"]
    assert trace["excluded_by_filters_total"] == 1
    assert trace["excluded_by_filters"][0]["id"] == "boundary:git.no_force_push"
    assert any("excluded by your types/subject filter" in action
               for action in payload["next_actions"])


def test_memory_map_payload(service):
    payload = service.memory_map()
    assert payload["ok"] is True
    assert payload["schema_version"] == "memdsl.mcp.map.v1"
    assert payload["declarations"] == 4
    module = payload["modules"][0]
    assert module["module"] == "self"
    ids = [item["id"] for item in module["items"]]
    assert "entity:User" in ids
    assert "boundary:schedule.no_meetings_before_10" in ids
    assert "[boundary:schedule.no_meetings_before_10]" in payload["rendered_text"]
    assert payload["vocabulary"]["subjects"][0]["symbol"] == "User"
    assert payload["boundary"]


def test_memory_map_scope_enforced(workspace_dir):
    svc = MemdslMCPService([str(workspace_dir)], scopes="read:search")
    with pytest.raises(MCPScopeError):
        svc.memory_map()


def test_check_blocks_candidate_and_requires_both_inputs(service):
    payload = service.check(
        "schedule a meeting", "Meeting confirmed at 09:30.")
    assert payload["ok"] is True
    assert payload["status"] == "block"
    pack = payload["compliance_pack"]
    assert pack["violations"][0]["boundary_id"] == (
        "boundary:schedule.no_meetings_before_10")
    assert "BLOCK" in payload["boundary"]

    invalid = service.check("schedule a meeting", "")
    assert invalid["ok"] is False
    assert invalid["status"] == "invalid"


def test_query_scope_enforced(workspace_dir):
    svc = MemdslMCPService([str(workspace_dir)], scopes="read:summary")
    with pytest.raises(MCPScopeError):
        svc.query("meetings")
    with pytest.raises(MCPScopeError):
        svc.check("schedule meeting", "Meeting at 09:30")
    # summary surfaces still work
    assert svc.status()["ok"] is True


def test_propose_creates_pending_proposal(service):
    source = (
        "decision tooling.editor {\n"
        "  subject: User\n"
        "  decision: \"Use one standard editor for reviews.\"\n"
        "  status: active\n"
        "  evidence {\n"
        "    source: chat\n"
        "    quote: \"Let's standardize on one editor.\"\n"
        "  }\n"
        "}\n"
    )
    payload = service.propose(source, reason="test proposal")
    assert payload["ok"] is True
    assert payload["status"] == "pending_review"
    assert payload["declaration_id"] == "decision:tooling.editor"
    assert payload["boundary"]

    queue = service.list_proposals()
    assert queue["total"] == 1
    assert queue["proposals"][0]["id"] == payload["proposal_id"]

    # a pending proposal is never served as memory
    assert service.status()["declarations"] == 4
    assert service.status()["pending_proposals"] == 1


def test_propose_fail_closed_and_scope(workspace_dir):
    svc = MemdslMCPService([str(workspace_dir)])
    bad = svc.propose("fact user.language {\n  subject: User\n  claim: \"Python.\"\n  status: active\n}\n")
    assert bad["ok"] is False
    assert bad["status"] == "invalid"
    assert any(e["code"] == "missing_evidence" for e in bad["errors"])
    assert svc.list_proposals()["total"] == 0

    readonly = MemdslMCPService([str(workspace_dir)], scopes="read:summary,read:search")
    with pytest.raises(MCPScopeError):
        readonly.propose("anything")


def test_explain_found_and_not_found(service):
    payload = service.explain("boundary:schedule.no_meetings_before_10")
    assert payload["ok"] is True
    decl = payload["declaration"]
    assert decl["force"] == "hard"
    assert decl["evidence"]["quote"]
    assert "force:   hard" in payload["rendered_text"]

    missing = service.explain("boundary:does.not.exist")
    assert missing["ok"] is False
    assert missing["status"] == "not_found"


def test_list_declarations_filters(service):
    payload = service.list_declarations(kind="preference")
    assert payload["ok"] is True
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "preference:feedback.direct"
    assert payload["items"][0]["has_evidence"] is True


def test_lint_clean_workspace(service):
    payload = service.lint_workspace()
    assert payload["ok"] is True
    assert payload["errors"] == 0
    assert payload["declarations"] == 4


def test_lint_reports_missing_evidence(tmp_path):
    path = tmp_path / "memory"
    path.mkdir()
    (path / "bad.mem").write_text(
        "module self\n\n"
        "fact user.language {\n"
        "  subject: User\n"
        "  claim: \"Primary language is Python.\"\n"
        "  status: active\n"
        "}\n",
        encoding="utf-8",
    )
    svc = MemdslMCPService([str(path)])
    payload = svc.lint_workspace()
    assert payload["ok"] is False
    codes = {d["code"] for d in payload["diagnostics"]}
    assert "missing_evidence" in codes


def test_workspace_reload_on_change(service, workspace_dir):
    assert service.status()["declarations"] == 4
    target = workspace_dir / "self.mem"
    extra = (
        "\ndecision tooling.editor {\n"
        "  subject: User\n"
        "  decision: \"Use the standard editor for reviews.\"\n"
        "  status: active\n"
        "  evidence {\n"
        "    source: chat\n"
        "    quote: \"Let's standardize on one editor.\"\n"
        "  }\n"
        "}\n"
    )
    target.write_text(MEM_SOURCE + extra, encoding="utf-8")
    stat = target.stat()
    os.utime(target, (stat.st_atime + 2, stat.st_mtime + 2))
    assert service.status()["declarations"] == 5


def test_files_and_read_file(service, workspace_dir):
    files = service.list_files()
    assert files["ok"] is True
    assert files["files"][0]["declarations"] == 4
    by_index = service.read_file("0")
    assert by_index["ok"] is True
    assert "boundary schedule.no_meetings_before_10" in by_index["content"]
    by_name = service.read_file("self.mem")
    assert by_name["ok"] is True
    missing = service.read_file("42")
    assert missing["ok"] is False
    assert missing["status"] == "not_found"


def _policy_workspace(
    tmp_path,
    *,
    auto_approvable=True,
    sample_percent=0,
    daily_limit=5,
    verifier="workspace_file_quote",
):
    path = tmp_path / "policy-memory"
    path.mkdir()
    (path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v1",
        "schemas": ["example.memschema.json"],
    }), encoding="utf-8")
    (path / "example.memschema.json").write_text(json.dumps({
        "name": "example",
        "version": "1",
        "types": {
            "observation": {
                "runtime_role": "assertion",
                "required_fields": ["claim", "scope", "evidence"],
                "capabilities": [
                    "requires_evidence",
                    "searchable",
                    *(["auto_approvable"] if auto_approvable else []),
                ],
                "allow_extra_fields": False,
            },
        },
    }), encoding="utf-8")
    (path / "base.mem").write_text("module observations\n", encoding="utf-8")
    (path / "evidence.txt").write_text(
        "The fictional build is green.\n", encoding="utf-8")
    staging = path / ".memdsl"
    staging.mkdir()
    policy = {
        "version": "memdsl.policy.v1",
        "default_route": "queue",
        "auto_merge_into": "generated/observations.mem",
        "sample_to_queue_percent": sample_percent,
        "max_auto_approve_per_day": daily_limit,
        "trusted_clients": ["mcp:fictional-collector"],
        "rules": [{
            "name": "verified-observations",
            "route": "auto_approve",
            "match": {
                "kind": ["example.observation"],
                "scope": ["project:fictional"],
                "client": ["mcp:fictional-collector"],
                "evidence_verifier": [verifier],
            },
        }],
    }
    (staging / "policy.json").write_text(
        json.dumps(policy, indent=2), encoding="utf-8")
    source = (
        "example.observation build.green {\n"
        "  claim: \"The fictional build is green.\"\n"
        "  scope: \"project:fictional\"\n"
        "  lifecycle { status: candidate }\n"
        "  evidence {\n"
        "    source: evidence.txt\n"
        "    quote: \"The fictional build is green.\"\n"
        "  }\n"
        "}\n"
    )
    return path, source


def test_policy_auto_approve_is_provisional_and_idempotent(tmp_path):
    workspace, source = _policy_workspace(tmp_path)
    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:fictional-collector",
    )

    result = service.propose(source)
    assert result["ok"] is True
    assert result["schema_version"] == "memdsl.mcp.propose.v2"
    assert result["route"] == "auto_approved"
    assert result["status"] == "auto_approved"
    assert result["assessment_hash"]
    assert result["merged_into"].endswith("generated\\observations.mem") or (
        result["merged_into"].endswith("generated/observations.mem"))

    query = service.query("fictional build green")
    assert query["status"] == "ok"
    pack = query["evidence_pack"]
    assert [item["id"] for item in pack["provisional"]] == [
        "example.observation:build.green"]
    assert pack["must"] == []
    assert pack["should"] == []
    assert pack["context"] == []

    duplicate = service.propose(source)
    assert duplicate["route"] == "no_op"
    assert duplicate["duplicate_of"] == result["proposal_id"]

    status = service.status()
    assert status["automation_effective"] is True
    assert status["auto_approvals_today"] == 1
    assert status["unaudited_auto_approvals"] == 1


def test_policy_shadow_routes_to_queue_but_reports_eligibility(tmp_path):
    workspace, source = _policy_workspace(tmp_path)
    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate",
        client_name="mcp:fictional-collector",
    )
    result = service.propose(source)
    assert result["route"] == "queued"
    assert result["status"] == "pending_review"
    assert result["eligible_route"] == "auto_approve"
    assert "write_auto_not_granted" in result["reason_codes"]
    assert not (workspace / "generated" / "observations.mem").exists()


def test_invalid_policy_fails_before_staging_even_without_auto_scope(tmp_path):
    workspace, source = _policy_workspace(tmp_path)
    policy_path = workspace / ".memdsl" / "policy.json"
    policy_path.write_text('{"version":"memdsl.policy.v1","unknown":true}',
                           encoding="utf-8")
    service = MemdslMCPService([str(workspace)])
    result = service.propose(source)
    assert result["ok"] is False
    assert result["status"] == "policy_invalid"
    proposals = workspace / ".memdsl" / "proposals"
    assert not proposals.exists() or not list(proposals.iterdir())


def test_in_process_host_can_inject_context_factory_and_custom_verifier(tmp_path):
    workspace, source = _policy_workspace(tmp_path, verifier="host_fixture")
    context_clients = []
    verifier_calls = []

    def context_factory(client_id):
        context_clients.append(client_id)
        return ProposalContext(client_id=client_id)

    def host_verifier(evidence, workspace_paths):
        verifier_calls.append((evidence, tuple(workspace_paths)))
        return EvidenceVerification.verified_content(
            verifier="host_fixture",
            evidence=evidence,
            source_content="host-authenticated synthetic evidence",
        )

    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:fictional-collector",
        context_factory=context_factory,
        evidence_verifier=host_verifier,
    )
    result = service.propose(source)

    assert result["route"] == "auto_approved"
    assert context_clients == ["mcp:fictional-collector"]
    assert len(verifier_calls) == 2
    assert verifier_calls[0][0]["quote"] == "The fictional build is green."
    assert verifier_calls[0][1] == (str(workspace),)
    assert verifier_calls[1] == verifier_calls[0]


def test_custom_verifier_exception_on_locked_recheck_falls_back(tmp_path):
    workspace, source = _policy_workspace(tmp_path, verifier="host_fixture")
    verifier_calls = []

    def host_verifier(evidence, workspace_paths):
        verifier_calls.append((evidence, tuple(workspace_paths)))
        if len(verifier_calls) == 2:
            raise RuntimeError("synthetic second-pass failure")
        return EvidenceVerification.verified_content(
            verifier="host_fixture",
            evidence=evidence,
            source_content="stable first-pass source",
        )

    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:fictional-collector",
        evidence_verifier=host_verifier,
    )

    result = service.propose(source)

    assert len(verifier_calls) == 2
    assert result["route"] == "queued"
    assert result["approval_error"]["status"] == "evidence_changed"
    assert result["approval_error"]["reason"] == "evidence_verifier_exception"
    assert not (workspace / "generated" / "observations.mem").exists()


def test_custom_verifier_digest_change_on_locked_recheck_falls_back(tmp_path):
    workspace, source = _policy_workspace(tmp_path, verifier="host_fixture")
    verifier_calls = []

    def host_verifier(evidence, workspace_paths):
        verifier_calls.append((evidence, tuple(workspace_paths)))
        source_content = (
            "first source containing The fictional build is green."
            if len(verifier_calls) == 1
            else "changed source containing The fictional build is green."
        )
        return EvidenceVerification.verified_content(
            verifier="host_fixture",
            evidence=evidence,
            source_content=source_content,
        )

    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:fictional-collector",
        evidence_verifier=host_verifier,
    )

    result = service.propose(source)

    assert len(verifier_calls) == 2
    assert result["route"] == "queued"
    assert result["approval_error"]["status"] == "evidence_changed"
    assert not (workspace / "generated" / "observations.mem").exists()


def test_unverified_evidence_is_queued(tmp_path):
    workspace, source = _policy_workspace(tmp_path)
    (workspace / "evidence.txt").write_text(
        "This file does not contain the proposal quote.\n", encoding="utf-8")
    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:fictional-collector",
    )

    result = service.propose(source)

    assert result["route"] == "queued"
    assert "evidence_not_verified" in result["reason_codes"]
    assert not (workspace / "generated" / "observations.mem").exists()


def test_verifier_exception_becomes_unverified_and_queues(tmp_path):
    workspace, source = _policy_workspace(tmp_path, verifier="exploding_verifier")

    def exploding_verifier(_evidence, _workspace_paths):
        raise RuntimeError("synthetic verifier failure")

    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:fictional-collector",
        evidence_verifier=exploding_verifier,
    )

    result = service.propose(source)

    assert result["route"] == "queued"
    assert "evidence_not_verified" in result["reason_codes"]
    assert not (workspace / "generated" / "observations.mem").exists()


def test_missing_verifier_is_unverified_and_queues(tmp_path):
    workspace, source = _policy_workspace(tmp_path)
    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:fictional-collector",
        evidence_verifier=None,
    )

    result = service.propose(source)

    assert result["route"] == "queued"
    assert "evidence_not_verified" in result["reason_codes"]
    assert service.status()["automation_effective"] is False


def test_status_uses_quota_reservation_when_auto_approval_falls_back(
    tmp_path, monkeypatch,
):
    workspace, source = _policy_workspace(tmp_path, daily_limit=1)
    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:fictional-collector",
    )
    monkeypatch.setattr(
        service.review_store,
        "approve",
        lambda *_args, **_kwargs: {"ok": False, "status": "workspace_changed"},
    )

    result = service.propose(source)
    status = service.status()

    assert result["route"] == "queued"
    assert result["rule"].startswith("fallback:")
    assert status["auto_approvals_today"] == 1
    assert status["automation_effective"] is False


def test_status_disables_automation_when_every_candidate_is_sampled(tmp_path):
    workspace, source = _policy_workspace(tmp_path, sample_percent=100)
    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:fictional-collector",
    )

    assert service.status()["automation_effective"] is False
    result = service.propose(source)
    assert result["route"] == "queued"
    assert "sampled_to_queue" in result["reason_codes"]


def test_status_disables_automation_without_auto_approvable_type(tmp_path):
    workspace, source = _policy_workspace(tmp_path, auto_approvable=False)
    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:fictional-collector",
    )

    assert service.status()["automation_effective"] is False
    result = service.propose(source)
    assert result["route"] == "queued"
    assert "type_not_auto_approvable" in result["reason_codes"]


def test_status_disables_automation_for_current_untrusted_client(tmp_path):
    workspace, _source = _policy_workspace(tmp_path)
    service = MemdslMCPService(
        [str(workspace)],
        scopes="read:summary,read:search,write:candidate,write:auto",
        client_name="mcp:untrusted",
    )

    assert service.status()["automation_effective"] is False
