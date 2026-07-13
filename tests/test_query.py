from memdsl.model import Workspace
from memdsl.parser import parse_text
from memdsl.query import (
    EVIDENCE_PACK_SCHEMA,
    build_evidence_pack,
    build_memory_map,
    explain,
    render_memory_map_text,
    workspace_vocabulary,
)

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


def test_candidate_symbol_alias_cannot_redirect_query_or_activate_must():
    def symbol_workspace(status):
        ws = Workspace()
        ws.add_document(parse_text(f'''
entity DraftTarget {{
  aliases: ["ghost handle"]
  lifecycle {{ status: {status} }}
}}

boundary publication.internal_code {{
  subject: DraftTarget
  rule: "Never expose the internal release code."
  force: hard
  scope: publication
  lifecycle {{ status: active }}
  evidence {{ source: test quote: "Keep the code internal." }}
}}
''', file=f"symbol-{status}.mem"))
        return ws

    candidate = build_evidence_pack(
        symbol_workspace("candidate"), "ghost handle")
    assert candidate.resolved_subjects == []
    assert candidate.trace["matched_aliases"] == {}
    assert candidate.must == []

    active = build_evidence_pack(symbol_workspace("active"), "ghost handle")
    assert active.resolved_subjects == ["DraftTarget"]
    assert active.trace["matched_aliases"] == {
        "ghost handle": ["DraftTarget"]}
    assert [d.id for d in active.must] == [
        "boundary:publication.internal_code"]


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
    assert all(layer in text for layer in (
        "MUST", "SHOULD", "CONTEXT", "PROVISIONAL"))


def test_explain_shows_relations_and_evidence():
    out = explain(make_ws(), "boundary:schedule.no_meetings_before_10")
    assert "evidence:" in out
    assert "force:   hard" in out


def test_query_json_roundtrip():
    import json
    pack = build_evidence_pack(make_ws(), "morning schedule")
    data = json.loads(pack.render_json())
    assert data["schema_version"] == EVIDENCE_PACK_SCHEMA
    assert data["query"] == "morning schedule"
    assert isinstance(data["must"], list)
    assert isinstance(data["provisional"], list)
    assert all("matched_terms" in item for item in data["context"])


def test_non_active_searchable_hits_land_only_in_provisional():
    ws = Workspace()
    ws.add_document(parse_text(r'''
boundary draft.constraint {
  rule: "Provisional marker must not be published."
  force: hard
  scope: pilot
  lifecycle { status: candidate }
  guard { deny_any: ["published"] }
  evidence { source: test quote: "Draft constraint." }
}

preference draft.guidance {
  claim: "Provisional marker suggests a cautious rollout."
  force: strong
  scope: pilot
  lifecycle { status: candidate }
  evidence { source: test quote: "Draft guidance." }
}

fact draft.assertion {
  claim: "Provisional marker is present in the pilot."
  scope: pilot
  lifecycle { status: candidate }
  evidence { source: test quote: "Draft assertion." }
}

open_issue draft.question {
  claim: "Whether the provisional marker is ready remains open."
  next_action: "Review the pilot."
  scope: pilot
  lifecycle { status: candidate }
}
''', file="provisional.mem"))

    pack = build_evidence_pack(ws, "provisional marker")
    provisional = {s.declaration.id: s for s in pack.provisional}

    assert set(provisional) == {
        "boundary:draft.constraint",
        "preference:draft.guidance",
        "fact:draft.assertion",
        "open_issue:draft.question",
    }
    assert pack.must == []
    assert pack.should == []
    assert pack.context == []
    assert pack.missing == [
        "no active declarations matched query terms: "
        "['provisional', 'marker']"
    ]

    payload = pack.as_dict()
    assert payload["schema_version"] == EVIDENCE_PACK_SCHEMA
    assert {item["status"] for item in payload["provisional"]} == {"candidate"}
    assert {item["lifecycle"]["status"]
            for item in payload["provisional"]} == {"candidate"}
    assert {item["runtime_role"] for item in payload["provisional"]} == {
        "constraint", "guidance", "assertion", "question"}

    text = pack.render_text()
    assert "PROVISIONAL" in text
    assert "[boundary:draft.constraint]" in text
    assert "status=candidate" in text
    assert "runtime_role=constraint" in text
    assert 'lifecycle={"status":"candidate"}' in text


def test_candidate_constraint_does_not_enter_must_but_active_constraint_does():
    def make_constraint(status):
        ws = Workspace()
        ws.add_document(parse_text(f'''
boundary rollout.safety {{
  rule: "Rollout safety requires a review."
  force: hard
  scope: rollout
  lifecycle {{ status: {status} }}
  evidence {{ source: test quote: "Review rollout safety." }}
}}
''', file=f"{status}.mem"))
        return ws

    candidate = build_evidence_pack(
        make_constraint("candidate"), "rollout safety")
    assert candidate.must == []
    assert [s.declaration.id for s in candidate.provisional] == [
        "boundary:rollout.safety"]

    active = build_evidence_pack(make_constraint("active"), "rollout safety")
    assert [d.id for d in active.must] == ["boundary:rollout.safety"]
    assert active.provisional == []


def test_provisional_hit_cannot_activate_must_through_subject_or_scope():
    ws = Workspace()
    ws.add_document(parse_text('''
fact draft.release_observation {
  subject: User
  claim: "A provisional lantern appeared in the rollout."
  scope: release
  lifecycle { status: candidate }
  evidence { source: test quote: "Draft rollout observation." }
}

boundary release.internal_key {
  subject: User
  rule: "Never publish the internal launch key."
  force: hard
  scope: release
  lifecycle { status: active }
  evidence { source: test quote: "Keep the launch key internal." }
}
''', file="fanout.mem"))

    provisional_only = build_evidence_pack(ws, "provisional lantern")
    assert [s.declaration.id for s in provisional_only.provisional] == [
        "fact:draft.release_observation"]
    assert provisional_only.must == []
    assert provisional_only.missing == [
        "no active declarations matched query terms: "
        "['provisional', 'lantern']"
    ]

    direct_constraint_hit = build_evidence_pack(ws, "internal launch key")
    assert [d.id for d in direct_constraint_hit.must] == [
        "boundary:release.internal_key"]


def test_provisional_only_hits_cannot_suppress_active_missing():
    empty = Workspace()
    before = build_evidence_pack(empty, "draft-only signal")

    with_candidate = Workspace()
    with_candidate.add_document(parse_text('''
fact draft.only_signal {
  subject: Draft
  claim: "A draft-only signal exists."
  scope: pilot
  lifecycle { status: candidate }
  evidence { source: test quote: "Unconfirmed signal." }
}
''', file="candidate-only.mem"))
    after = build_evidence_pack(with_candidate, "draft-only signal")

    assert after.missing == before.missing
    assert [item.declaration.id for item in after.provisional] == [
        "fact:draft.only_signal"]


def test_candidate_hits_cannot_consume_active_limit_or_change_active_layers():
    active_source = '''
fact release.aurora_observation {
  subject: Release
  claim: "The aurora launch observation is confirmed."
  scope: release
  lifecycle { status: active }
  evidence { source: test quote: "Confirmed launch observation." }
}

boundary release.signing_material {
  subject: Release
  rule: "Never expose internal signing material."
  force: hard
  scope: release
  lifecycle { status: active }
  evidence { source: test quote: "Keep signing material internal." }
}

open_issue release.readiness_question {
  subject: Release
  claim: "Whether the aurora readiness review is complete remains open."
  scope: release
  lifecycle { status: active }
}
'''
    candidate_source = '''
fact draft.noisy_candidate {
  subject: Draft
  claim: "Aurora launch packet readiness packet launch readiness."
  scope: draft
  lifecycle { status: candidate }
  evidence { source: test quote: "Unreviewed draft packet." }
}
'''

    active_only = Workspace()
    active_only.add_document(parse_text(active_source, file="active.mem"))
    with_candidate = Workspace()
    with_candidate.add_document(parse_text(active_source, file="active.mem"))
    with_candidate.add_document(
        parse_text(candidate_source, file="candidate.mem"))

    baseline = build_evidence_pack(
        active_only, "aurora launch packet readiness", limit=1)
    actual = build_evidence_pack(
        with_candidate, "aurora launch packet readiness", limit=1)

    def active_layers(pack):
        return {
            "must": [d.id for d in pack.must],
            "should": [d.id for d in pack.should],
            "context": [s.declaration.id for s in pack.context],
            "conflicts": [(d.id, target) for d, target in pack.conflicts],
            "missing": list(pack.missing),
        }

    assert active_layers(actual) == active_layers(baseline)
    assert active_layers(actual)["must"] == [
        "boundary:release.signing_material"]
    assert active_layers(actual)["context"] == [
        "fact:release.aurora_observation"]
    assert [s.declaration.id for s in actual.provisional] == [
        "fact:draft.noisy_candidate"]


def test_provisional_limit_and_tie_break_are_deterministic():
    sources = {
        "zeta": '''
fact draft.zeta {
  claim: "A provisional beacon was observed."
  lifecycle { status: candidate }
  evidence { source: test quote: "Draft zeta." }
}
''',
        "alpha": '''
fact draft.alpha {
  claim: "A provisional beacon was observed."
  lifecycle { status: candidate }
  evidence { source: test quote: "Draft alpha." }
}
''',
    }

    def query_in_order(order):
        ws = Workspace()
        for name in order:
            ws.add_document(parse_text(sources[name], file=f"{name}.mem"))
        return build_evidence_pack(ws, "provisional beacon", limit=1)

    forward = query_in_order(["zeta", "alpha"])
    reverse = query_in_order(["alpha", "zeta"])

    assert [s.declaration.id for s in forward.provisional] == [
        "fact:draft.alpha"]
    assert [s.declaration.id for s in reverse.provisional] == [
        "fact:draft.alpha"]
    assert forward.provisional[0].matched_terms == [
        "provisional", "beacon"]


def test_search_trace_reports_query_interpretation():
    pack = build_evidence_pack(make_ws(), "how is my day job going")
    trace = pack.trace
    assert "day" in trace["query_terms"] and "job" in trace["query_terms"]
    assert trace["matched_aliases"]["day job"] == ["User.DayJob"]
    assert trace["hits"] >= 1
    assert trace["excluded_by_filters_total"] == 0
    assert pack.as_dict()["search_trace"] == trace


def test_filter_exclusions_fail_loud_instead_of_silent_no_match():
    # The right memory exists, but the caller's type filter hides it. The
    # miss must say so instead of looking identical to genuine absence.
    pack = build_evidence_pack(
        make_ws(), "meetings before ten", kinds=["state"])
    assert not pack.must and not pack.should and not pack.context
    trace = pack.trace
    assert trace["filters"]["types"] == ["state"]
    assert trace["excluded_by_filters_total"] >= 1
    excluded_ids = [e["id"] for e in trace["excluded_by_filters"]]
    assert "boundary:schedule.no_meetings_before_10" in excluded_ids
    assert any("excluded by type/subject filters" in m for m in pack.missing)


def test_workspace_vocabulary_lists_the_words_a_workspace_speaks():
    vocab = workspace_vocabulary(make_ws())
    symbols = {s["symbol"] for s in vocab["subjects"]}
    assert {"User", "User.DayJob"} <= symbols
    dayjob = next(s for s in vocab["subjects"] if s["symbol"] == "User.DayJob")
    assert "day job" in dayjob["aliases"]
    assert "scheduling" in vocab["scopes"]
    assert "self" in vocab["modules"]
    assert vocab["types"]["boundary"] == 1


def test_memory_map_indexes_active_memory_per_module():
    map_data = build_memory_map(make_ws())
    assert map_data["declarations"] == 6
    module = next(m for m in map_data["modules"] if m["module"] == "self")
    ids = [item["id"] for item in module["items"]]
    assert "entity:User" in ids
    assert "boundary:schedule.no_meetings_before_10" in ids
    # inactive memory stays out of the map
    assert "state:dayjob.old_load" not in ids
    text = render_memory_map_text(map_data)
    assert "# memory map" in text
    assert "[boundary:schedule.no_meetings_before_10]" in text
    assert "## vocabulary" in text
    assert "day job" in text


def test_memory_map_marks_candidate_entries_as_provisional_status():
    ws = Workspace()
    ws.add_document(parse_text('''
fact draft.map_entry {
  claim: "A candidate map entry."
  lifecycle { status: candidate as_of: 2026-07-14 }
}
''', file="candidate.mem"))
    map_data = build_memory_map(ws)
    item = map_data["modules"][0]["items"][0]
    assert item["status"] == "candidate"
    assert item["lifecycle"] == {
        "status": "candidate", "as_of": "2026-07-14"}
    text = render_memory_map_text(map_data)
    assert "status=candidate" in text
    assert 'lifecycle={"as_of":"2026-07-14","status":"candidate"}' in text
