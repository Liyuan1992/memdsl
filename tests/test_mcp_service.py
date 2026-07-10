"""Tests for the SDK-free MCP service layer."""

import os

import pytest

from memdsl.mcp_service import (
    MCPScopeError,
    MemdslMCPService,
    parse_scopes,
)

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
