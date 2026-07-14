"""Phase -1 characterization for the public memdsl 0.6.0 baseline.

These tests deliberately separate two things:

* passing characterization records what 0.6.0 does today;
* strict xfails record desired invariants that later phases must implement.

An xfail becoming XPASS is intentionally a suite failure: the implementing
phase must convert that case into an ordinary regression test and update the
design evidence instead of silently inheriting a stale known-defect marker.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from memdsl.authority import authoritative_superseded_ids
from memdsl.compliance import check_compliance
from memdsl.linter import lint
from memdsl.mcp_service import MemdslMCPService
from memdsl.model import Workspace
from memdsl.parser import parse_text
from memdsl.query import build_evidence_pack, build_memory_map, workspace_vocabulary


FIXTURES = Path(__file__).parent / "fixtures" / "phase_minus_one"
SNAPSHOTS = Path(__file__).parent / "snapshots" / "phase_minus_one"
TODAY = datetime.date(2026, 7, 14)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def workspace_from_fixture(name: str) -> Workspace:
    ws = Workspace()
    ws.add_document(parse_text(
        fixture_text(name), file=f"<phase-minus-one/{name}>"))
    return ws


def service_for_workspace(ws: Workspace) -> MemdslMCPService:
    service = MemdslMCPService([str(FIXTURES)])
    service.workspace = lambda: ws  # type: ignore[method-assign]
    return service


def map_ids(ws: Workspace) -> list[str]:
    return [
        item["id"]
        for module in build_memory_map(ws)["modules"]
        for item in module["items"]
    ]


def codes(ws: Workspace) -> set[str]:
    return {diagnostic.code for diagnostic in lint(ws, today=TODAY)}


def snapshot(name: str) -> dict:
    return json.loads((SNAPSHOTS / name).read_text(encoding="utf-8"))


def test_map_query_and_explain_payload_snapshots() -> None:
    ws = workspace_from_fixture("baseline.mem")
    service = service_for_workspace(ws)

    assert service.memory_map() == snapshot("memory_map.json")
    assert service.query("lantern release", limit=3) == snapshot("query.json")
    assert service.explain("boundary:safety.no_ember") == snapshot("explain.json")


@pytest.mark.parametrize(
    ("fixture_name", "superseder_id"),
    [
        ("authority_candidate_fact.mem", "fact:topic.draft_override"),
        ("authority_retracted.mem", "fact:topic.withdrawn_override"),
        ("authority_archived.mem", "fact:topic.archived_override"),
    ],
)
def test_non_authoritative_superseders_must_not_hide_active_target(
    fixture_name: str,
    superseder_id: str,
) -> None:
    ws = workspace_from_fixture(fixture_name)
    pack = build_evidence_pack(ws, "synthetic beacon active")

    assert ws.by_id(superseder_id) is not None
    assert "fact:topic.current" in map_ids(ws)
    assert "fact:topic.current" not in authoritative_superseded_ids(ws)
    assert [item.declaration.id for item in pack.context] == [
        "fact:topic.current"]


@pytest.mark.parametrize("superseder_status", ["candidate", "retracted", "archived"])
def test_non_authoritative_supersedes_global_constraint_must_remain_blocked(
    superseder_status: str,
) -> None:
    source = fixture_text("authority_candidate_constraint.mem").replace(
        "status: candidate", f"status: {superseder_status}")
    ws = Workspace()
    ws.add_document(parse_text(
        source, file=f"<phase-minus-one/constraint-{superseder_status}.mem>"))
    active_only_workspace = Workspace()
    active_only = next(
        d for d in ws.declarations if d.id == "boundary:safety.no_ember")
    active_only_workspace.declarations.append(active_only)

    query_pack = build_evidence_pack(ws, "synthetic ember token")
    before = check_compliance(
        active_only_workspace, "Publish a synthetic note", "Include ember-token.")
    after = check_compliance(
        ws, "Publish a synthetic note", "Include ember-token.")

    assert [d.id for d in query_pack.must] == ["boundary:safety.no_ember"]
    assert before.verdict == "block"
    assert after.verdict == "block"
    assert [d.id for d in after.applicable_must] == ["boundary:safety.no_ember"]


def test_supersedes_fork_currently_has_no_fork_diagnostic() -> None:
    ws = workspace_from_fixture("revision_fork.mem")

    assert map_ids(ws) == ["fact:topic.left", "fact:topic.right"]
    assert "supersedes_fork" not in codes(ws)


@pytest.mark.xfail(
    strict=True,
    reason="Phase 1: a fork must be explicit and must never choose a winner",
)
def test_supersedes_fork_must_emit_a_diagnostic() -> None:
    diagnostics = lint(workspace_from_fixture("revision_fork.mem"), today=TODAY)
    assert any("fork" in item.message.lower() for item in diagnostics)


def test_supersedes_cycle_currently_hides_both_nodes_without_cycle_diagnostic(
) -> None:
    ws = workspace_from_fixture("revision_cycle.mem")

    assert map_ids(ws) == []
    assert "supersedes_cycle" not in codes(ws)


@pytest.mark.xfail(
    strict=True,
    reason="Phase 1: cycle edges cannot make every participating node disappear",
)
def test_supersedes_cycle_must_fail_loud_without_applying_exclusion() -> None:
    ws = workspace_from_fixture("revision_cycle.mem")
    assert set(map_ids(ws)) == {"fact:topic.alpha", "fact:topic.beta"}
    assert any("cycle" in item.message.lower() for item in lint(ws, today=TODAY))


def test_map_list_status_and_vocabulary_must_share_current_set(
    tmp_path: Path,
) -> None:
    (tmp_path / "memory.mem").write_text(
        fixture_text("revision_fork.mem"), encoding="utf-8")
    service = MemdslMCPService([str(tmp_path)])
    memory_map = service.memory_map()
    listing = service.list_declarations()
    status = service.status()
    vocabulary = memory_map["vocabulary"]

    counts = {
        memory_map["declarations"],
        listing["total"],
        status["active_declarations"],
        vocabulary["types"]["fact"],
    }
    assert len(counts) == 1


def test_ambiguous_bare_reference_has_no_authority_effect() -> None:
    ws = workspace_from_fixture("reference_resolution.mem")
    remaining = set(map_ids(ws))

    assert "ambiguous_relation_target" not in codes(ws)
    assert "fact:shared" in remaining
    assert "decision:shared" in remaining
    assert "fact:bare.successor" in remaining


@pytest.mark.parametrize("target_reference", ["topic.old", "fact:topic.old"])
def test_active_unique_supersedes_keeps_append_only_revision_compatibility(
    target_reference: str,
) -> None:
    ws = Workspace()
    ws.add_document(parse_text(f'''
fact topic.old {{
  claim: "Old synthetic route."
  lifecycle {{ status: active }}
  evidence {{ source: synthetic_log quote: "Old route." }}
}}

fact topic.new {{
  claim: "New synthetic route."
  lifecycle {{ status: active }}
  relations {{ supersedes: "{target_reference}" }}
  evidence {{ source: synthetic_log quote: "New route." }}
}}
''', file="<phase-minus-one/linear-revision.mem>"))

    assert authoritative_superseded_ids(ws) == {"fact:topic.old"}
    assert map_ids(ws) == ["fact:topic.new"]
    pack = build_evidence_pack(ws, "synthetic route")
    assert [item.declaration.id for item in pack.context] == ["fact:topic.new"]


def test_wrong_kind_prefix_passes_lint_but_does_not_link_at_runtime() -> None:
    ws = workspace_from_fixture("reference_resolution.mem")
    prefix_target = ws.by_id("fact:prefix.target")
    assert prefix_target is not None

    target_diags = [
        item for item in lint(ws, today=TODAY)
        if item.decl_id == "fact:prefix.successor"
    ]
    assert "unresolved_symbol" not in {item.code for item in target_diags}
    assert "fact:prefix.target" in map_ids(ws)
    explained = service_for_workspace(ws).explain("fact:prefix.target")
    assert explained["declaration"]["referenced_by"] == []


def test_unknown_relation_key_is_silently_dropped() -> None:
    ws = workspace_from_fixture("reference_resolution.mem")
    declaration = ws.by_id("fact:typo.source")
    assert declaration is not None

    assert declaration.fields["relations"] == {"supercedes": "prefix.target"}
    assert declaration.relations() == {}
    assert "unknown_relation" not in codes(ws)


@pytest.mark.xfail(
    strict=True,
    reason="Phase 1: compiler resolver exists; full reference diagnostics must fail loud",
)
def test_reference_resolution_must_fail_loud_consistently() -> None:
    ws = workspace_from_fixture("reference_resolution.mem")
    diagnostics = lint(ws, today=TODAY)
    ambiguous = [
        item for item in diagnostics if item.decl_id == "fact:bare.successor"]
    wrong_prefix = [
        item for item in diagnostics if item.decl_id == "fact:prefix.successor"]
    relation_typo = [
        item for item in diagnostics if item.decl_id == "fact:typo.source"]
    assert ambiguous and wrong_prefix and relation_typo
    assert {"fact:shared", "decision:shared"} <= set(map_ids(ws))


def test_duplicate_full_id_is_lint_error_but_read_paths_serve_both_and_first(
) -> None:
    ws = workspace_from_fixture("duplicate_id.mem")
    payload = service_for_workspace(ws).explain("fact:duplicate.item")

    assert "duplicate_declaration_id" in codes(ws)
    assert map_ids(ws) == ["fact:duplicate.item", "fact:duplicate.item"]
    assert payload["status"] == "ok"
    assert payload["declaration"]["claim"] == "First synthetic occurrence."


@pytest.mark.xfail(
    strict=True,
    reason="Phase 1: occurrences are preserved; duplicate identity must gate serving",
)
def test_duplicate_full_id_must_not_be_served_as_a_single_resolved_declaration(
) -> None:
    ws = workspace_from_fixture("duplicate_id.mem")
    payload = service_for_workspace(ws).explain("fact:duplicate.item")
    assert payload["status"] != "ok"


def test_parser_assigns_last_module_to_every_declaration_in_a_file() -> None:
    document = parse_text(
        fixture_text("multiple_modules.mem"), file="<phase-minus-one/modules.mem>")

    assert document.module == "phase_minus_one.second"
    assert {d.module for d in document.declarations} == {"phase_minus_one.second"}
    assert [d.name for d in document.declarations] == [
        "module.first_item", "module.second_item"]


def test_vocabulary_silently_truncates_at_fifty_subjects() -> None:
    source = "\n".join(
        f'''entity Synthetic.Subject{index:02d} {{
  canonical_name: "Synthetic subject {index:02d}"
  lifecycle {{ status: active }}
}}'''
        for index in range(51)
    )
    ws = Workspace()
    ws.add_document(parse_text(source, file="<phase-minus-one/51-subjects.mem>"))
    vocabulary = workspace_vocabulary(ws)

    assert len(vocabulary["subjects"]) == 50
    assert "subjects_total" not in vocabulary
    assert "subjects_truncated" not in vocabulary


@pytest.mark.xfail(
    strict=True,
    reason="Phase 2: vocabulary truncation must expose completeness metadata",
)
def test_vocabulary_truncation_must_be_visible() -> None:
    source = "\n".join(
        f"entity Synthetic.Subject{index:02d} {{ lifecycle {{ status: active }} }}"
        for index in range(51)
    )
    ws = Workspace()
    ws.add_document(parse_text(source, file="<phase-minus-one/51-subjects.mem>"))
    vocabulary = workspace_vocabulary(ws)
    completeness_keys = {
        key for key in vocabulary if "total" in key or "trunc" in key
    }
    assert len(vocabulary["subjects"]) == 51 or completeness_keys


def test_map_single_item_aliases_and_lifecycle_are_not_strictly_bounded() -> None:
    aliases = [f"alias-{index:03d}-" + ("x" * 32) for index in range(100)]
    alias_source = ", ".join(f'"{alias}"' for alias in aliases)
    source = f'''
entity Synthetic.Wide {{
  canonical_name: "Synthetic Wide Symbol"
  aliases: [{alias_source}]
  lifecycle {{ status: active note: "{'y' * 2048}" }}
}}
'''
    ws = Workspace()
    ws.add_document(parse_text(source, file="<phase-minus-one/wide-item.mem>"))
    map_data = build_memory_map(ws, claim_chars=16)
    item = map_data["modules"][0]["items"][0]

    assert len(item["summary"]) > 4000
    assert len(item["lifecycle"]["note"]) == 2048
    assert len(map_data["vocabulary"]["subjects"][0]["aliases"]) == 100


def test_query_and_explain_return_full_evidence_and_incoming_refs_without_budget(
) -> None:
    quote = "E" * 4096
    references = "\n".join(
        f'''fact incoming.item_{index:02d} {{
  claim: "Synthetic incoming item {index:02d}."
  lifecycle {{ status: active }}
  relations {{ supports: payload.target }}
  evidence {{ source: synthetic_log quote: "Incoming {index:02d}." }}
}}'''
        for index in range(32)
    )
    source = f'''
fact payload.target {{
  claim: "Synthetic payload target."
  lifecycle {{ status: active }}
  evidence {{ source: synthetic_log quote: "{quote}" }}
}}
{references}
'''
    ws = Workspace()
    ws.add_document(parse_text(source, file="<phase-minus-one/unbounded.mem>"))
    service = service_for_workspace(ws)

    query_payload = service.query("synthetic payload target")
    explain_payload = service.explain("fact:payload.target")

    assert query_payload["evidence_pack"]["context"][0]["evidence"]["quote"] == quote
    assert "rendered_text" in query_payload
    assert "truncated" not in query_payload
    assert explain_payload["declaration"]["evidence"]["quote"] == quote
    assert len(explain_payload["declaration"]["referenced_by"]) == 32
    assert quote in explain_payload["rendered_text"]
    assert "truncated" not in explain_payload


def test_valid_until_and_access_policy_do_not_change_v06_serving() -> None:
    ws = workspace_from_fixture("temporal_access.mem")
    service = service_for_workspace(ws)
    pack = build_evidence_pack(ws, "synthetic lantern red")

    assert "stale_state" in codes(ws)
    assert map_ids(ws) == ["state:expired.owner_only"]
    assert [item.declaration.id for item in pack.context] == [
        "state:expired.owner_only"]
    assert service.list_declarations()["items"][0]["id"] == (
        "state:expired.owner_only")
    assert service.explain("state:expired.owner_only")["status"] == "ok"


def test_lint_errors_do_not_gate_reads_and_repair_proposals_remain_available(
    tmp_path: Path,
) -> None:
    broken_but_parseable = '''
fact broken.anchor {
  subject: Missing.Symbol
  claim: "Synthetic repair anchor."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Repair anchor." }
}
'''
    (tmp_path / "memory.mem").write_text(
        broken_but_parseable, encoding="utf-8")
    service = MemdslMCPService([str(tmp_path)])

    assert service.lint_workspace()["status"] == "errors"
    assert service.query("synthetic repair anchor")["status"] == "ok"

    repair = service.propose('''
entity Missing.Symbol {
  canonical_name: "Synthetic Missing Symbol"
  lifecycle { status: active }
}
''', reason="synthetic repair proposal")
    assert repair["status"] == "pending_review"


def test_parse_errors_gate_both_reads_and_mcp_proposals(tmp_path: Path) -> None:
    (tmp_path / "broken.mem").write_text(
        'fact broken.item { claim: "unterminated"', encoding="utf-8")
    service = MemdslMCPService([str(tmp_path)])

    query_payload = service.query("broken")
    propose_payload = service.propose('''
entity Synthetic.Repair {
  canonical_name: "Synthetic Repair"
  lifecycle { status: active }
}
''')

    assert query_payload["status"] == "parse_error"
    assert propose_payload["status"] == "parse_error"
