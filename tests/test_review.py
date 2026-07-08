"""Tests for the gated write pipeline (review queue)."""

import json
import os

import pytest

from memdsl.cli import main as cli_main
from memdsl.model import Workspace
from memdsl.review import ReviewStore, staging_dir_for

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
