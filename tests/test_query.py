from memdsl.model import Workspace
from memdsl.parser import parse_text
from memdsl.query import build_evidence_pack, explain

SOURCE = """
module self

entity User {
  kind: Person
  canonical_name: "Alex"
  aliases: ["me"]
  status: active
}

entity User.DayJob {
  kind: Employment
  canonical_name: "DayJob"
  aliases: ["work", "day job"]
  status: active
}

boundary schedule.no_meetings_before_10 {
  subject: User
  rule: "Do not schedule meetings before 10:00."
  force: hard
  scope: scheduling
  exceptions: [user_explicit_override]
  status: active
  evidence { source: chat quote: "No meetings before ten." }
}

preference schedule.deep_work_mornings {
  subject: User
  claim: "Prefers deep work in the morning."
  force: strong
  scope: scheduling
  confidence: high
  status: active
  evidence { source: chat quote: "Mornings are for real work." }
}

state dayjob.current_load {
  subject: User.DayJob
  claim: "Current workload at the day job feels draining."
  as_of: 2026-06-15
  scope: scheduling
  confidence: medium
  status: active
  evidence { source: chat quote: "Work is draining me lately." }
}

state dayjob.old_load {
  subject: User.DayJob
  claim: "Workload was fine in spring."
  as_of: 2026-03-01
  scope: scheduling
  status: superseded
  evidence { source: chat quote: "Work is fine right now." }
}

open_issue dayjob.raise_negotiation {
  subject: User.DayJob
  claim: "Whether to ask for a raise this quarter is unresolved."
  next_action: "Decide after the June review."
  scope: scheduling
  status: active
}
"""


def make_ws():
    ws = Workspace()
    ws.add_document(parse_text(SOURCE))
    return ws


def test_boundary_lands_in_must():
    pack = build_evidence_pack(make_ws(), "plan my morning schedule")
    must_ids = [d.id for d in pack.must]
    assert "boundary:schedule.no_meetings_before_10" in must_ids


def test_strong_preference_lands_in_should():
    pack = build_evidence_pack(make_ws(), "plan my morning schedule")
    should_ids = [d.id for d in pack.should]
    assert "preference:schedule.deep_work_mornings" in should_ids


def test_alias_resolves_subject():
    pack = build_evidence_pack(make_ws(), "how is my day job going")
    assert "User.DayJob" in pack.resolved_subjects
    context_ids = [s.declaration.id for s in pack.context]
    assert "state:dayjob.current_load" in context_ids


def test_superseded_state_excluded():
    pack = build_evidence_pack(make_ws(), "how is my day job workload")
    all_ids = ([d.id for d in pack.must + pack.should]
               + [s.declaration.id for s in pack.context])
    assert "state:dayjob.old_load" not in all_ids


def test_open_issue_never_in_context_always_in_missing():
    # SPEC §7 rule 3: open_issue surfaces under MISSING, never as facts.
    pack = build_evidence_pack(make_ws(), "day job raise this quarter")
    all_fact_ids = ([d.id for d in pack.must + pack.should]
                    + [s.declaration.id for s in pack.context])
    assert "open_issue:dayjob.raise_negotiation" not in all_fact_ids
    assert any("dayjob.raise_negotiation" in m for m in pack.missing)


def test_no_match_reports_missing():
    pack = build_evidence_pack(make_ws(), "zzz qqq unrelated")
    assert pack.missing


def test_render_text_has_layers():
    text = build_evidence_pack(make_ws(), "morning schedule").render_text()
    assert "MUST" in text and "SHOULD" in text and "CONTEXT" in text


def test_explain_shows_relations_and_evidence():
    out = explain(make_ws(), "boundary:schedule.no_meetings_before_10")
    assert "evidence:" in out
    assert "force:   hard" in out


def test_query_json_roundtrip():
    import json
    pack = build_evidence_pack(make_ws(), "morning schedule")
    data = json.loads(pack.render_json())
    assert data["query"] == "morning schedule"
    assert isinstance(data["must"], list)
