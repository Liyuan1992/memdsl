"""Phase 5 quarantine enforcement and access-filtered View contracts."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Optional

import pytest

from memdsl.cli import main as cli_main
from memdsl.compiler import compile_workspace
from memdsl.graph import TraceAnchorError, trace_memory
from memdsl.mcp_service import MemdslMCPService
from memdsl.model import Workspace
from memdsl.navigation import build_memory_catalog
from memdsl.parser import parse_text
from memdsl.query import build_evidence_pack
from memdsl.review import ReviewStore
from memdsl.schema import SchemaError, TypeDescriptor, TypeRegistry
from memdsl.serving import (
    ResolvedCursorError,
    build_resolved_check,
    build_resolved_explain,
    build_resolved_list,
    build_resolved_query,
)
from memdsl.view import ViewContext, resolve_view


def _workspace(
    source: str,
    *,
    mode: str = "report",
    visibility: str = "report",
    registry: Optional[TypeRegistry] = None,
) -> Workspace:
    workspace = Workspace(
        registry=registry or TypeRegistry.standard(),
        schema_version="memdsl.workspace.v2",
        linking_visibility=visibility,
        enforcement_mode=mode,
    )
    workspace.add_document(parse_text(source, file="<phase-five/memory.mem>"))
    return workspace


def _ids(items) -> list[str]:
    return [item.id for item in items]


def test_v2_enforcement_manifest_is_explicit_and_v1_fails_closed(
    tmp_path: Path,
) -> None:
    (tmp_path / "memory.mem").write_text(
        'fact synthetic.item { claim: "Synthetic." lifecycle { status: candidate } }',
        encoding="utf-8",
    )
    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v1",
        "schemas": [],
        "enforcement": {"mode": "quarantine"},
    }), encoding="utf-8")
    with pytest.raises(SchemaError, match="cannot declare 'enforcement'"):
        Workspace.load([str(tmp_path)])

    for mode in (None, "report", "quarantine", "strict"):
        manifest = {
            "schema_version": "memdsl.workspace.v2",
            "schemas": [],
            "linking": {"visibility": "report"},
        }
        if mode is not None:
            manifest["enforcement"] = {"mode": mode}
        (tmp_path / "memdsl.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        workspace = Workspace.load([str(tmp_path)])
        assert workspace.enforcement_mode == (mode or "report")


def test_duplicate_identity_is_workspace_blocking_in_enforced_modes() -> None:
    source = '''
fact duplicate.item {
  claim: "Synthetic first."
  evidence { source: synthetic quote: "First." }
}
fact duplicate.item {
  claim: "Synthetic second."
  evidence { source: synthetic quote: "Second." }
}
fact safe.item {
  claim: "Synthetic safe."
  evidence { source: synthetic quote: "Safe." }
}
'''
    for mode in ("quarantine", "strict"):
        view = resolve_view(compile_workspace(_workspace(source, mode=mode)))
        assert view.status == "compiler_error"
        assert view.authoritative == view.provisional == ()
        assert set(_ids(view.quarantined)) == {
            "fact:duplicate.item", "fact:safe.item"}
        assert {item.code for item in view.blocking_diagnostics} == {
            "duplicate_declaration_id"}
        assert view.envelope()["status"] == "compiler_error"


def test_local_relation_errors_quarantine_only_the_source_declaration() -> None:
    source = '''
fact broken.item {
  claim: "Synthetic broken."
  relations { supports: missing.item }
  evidence { source: synthetic quote: "Broken." }
}
fact safe.item {
  claim: "Synthetic safe."
  evidence { source: synthetic quote: "Safe." }
}
'''
    report = resolve_view(compile_workspace(_workspace(source)))
    enforced = resolve_view(compile_workspace(
        _workspace(source, mode="quarantine")))

    assert set(_ids(report.authoritative)) == {
        "fact:broken.item", "fact:safe.item"}
    assert _ids(enforced.authoritative) == ["fact:safe.item"]
    assert _ids(enforced.quarantined) == ["fact:broken.item"]
    assert enforced.reasons_for(enforced.quarantined[0]) == (
        "unresolved_symbol",)


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        ('''
fact target.shared { claim: "Fact target." evidence { source: synthetic quote: "F." } }
decision target.shared { decision: "Decision target." evidence { source: synthetic quote: "D." } }
fact source.item {
  claim: "Ambiguous source."
  relations { supports: target.shared }
  evidence { source: synthetic quote: "S." }
}
''', "ambiguous_relation_target"),
        ('''
fact target.item { claim: "Target." evidence { source: synthetic quote: "T." } }
fact source.item {
  claim: "Wrong prefix source."
  relations { supports: "decision:target.item" }
  evidence { source: synthetic quote: "S." }
}
''', "relation_target_kind_mismatch"),
        ('''
fact target.item { claim: "Target." evidence { source: synthetic quote: "T." } }
fact source.item {
  claim: "Unknown relation source."
  relations { supprots: target.item }
  evidence { source: synthetic quote: "S." }
}
''', "unknown_relation"),
    ],
)
def test_relation_pollution_matrix_is_declaration_local(
    source: str,
    expected_code: str,
) -> None:
    view = resolve_view(compile_workspace(_workspace(
        source, mode="quarantine")))

    assert _ids(view.quarantined) == ["fact:source.item"]
    assert view.reasons_for(view.quarantined[0]) == (expected_code,)
    assert "fact:target.item" in _ids(view.authoritative) or {
        "decision:target.shared", "fact:target.shared"
    } <= set(_ids(view.authoritative))


def test_use_collision_quarantines_only_the_consumer_file() -> None:
    workspace = Workspace(
        registry=TypeRegistry.standard(),
        schema_version="memdsl.workspace.v2",
        linking_visibility="report",
        enforcement_mode="quarantine",
    )
    workspace.add_document(parse_text('''
module Shared.Target
fact module.item {
  claim: "Synthetic module target."
  evidence { source: synthetic quote: "Module." }
}
''', file="<phase-five/module.mem>"))
    workspace.add_document(parse_text('''
module synthetic.symbol
entity Shared.Target { lifecycle { status: active } }
''', file="<phase-five/symbol.mem>"))
    workspace.add_document(parse_text('''
module synthetic.consumer
use Shared.Target
fact consumer.item {
  claim: "Synthetic consumer."
  evidence { source: synthetic quote: "Consumer." }
}
''', file="<phase-five/consumer.mem>"))

    view = resolve_view(compile_workspace(workspace))

    assert _ids(view.quarantined) == ["fact:consumer.item"]
    assert view.reasons_for(view.quarantined[0]) == ("ambiguous_use_target",)
    assert set(_ids(view.authoritative)) == {
        "entity:Shared.Target", "fact:module.item"}


def test_fork_quarantine_restores_target_while_strict_blocks_family() -> None:
    source = '''
fact topic.old {
  claim: "Synthetic old."
  evidence { source: synthetic quote: "Old." }
}
fact topic.left {
  claim: "Synthetic left."
  relations { supersedes: topic.old }
  evidence { source: synthetic quote: "Left." }
}
fact topic.right {
  claim: "Synthetic right."
  relations { supersedes: topic.old }
  evidence { source: synthetic quote: "Right." }
}
fact safe.item {
  claim: "Synthetic safe."
  evidence { source: synthetic quote: "Safe." }
}
'''
    quarantine = resolve_view(compile_workspace(
        _workspace(source, mode="quarantine")))
    strict = resolve_view(compile_workspace(_workspace(source, mode="strict")))

    assert _ids(quarantine.authoritative) == [
        "fact:safe.item", "fact:topic.old"]
    assert _ids(quarantine.quarantined) == [
        "fact:topic.left", "fact:topic.right"]
    assert _ids(strict.authoritative) == ["fact:safe.item"]
    assert _ids(strict.quarantined) == [
        "fact:topic.left", "fact:topic.old", "fact:topic.right"]


def test_revision_cycle_quarantines_family_and_preserves_unrelated_memory() -> None:
    source = '''
fact topic.alpha {
  claim: "Synthetic alpha."
  relations { supersedes: topic.beta }
  evidence { source: synthetic quote: "Alpha." }
}
fact topic.beta {
  claim: "Synthetic beta."
  relations { revision_of: topic.alpha }
  evidence { source: synthetic quote: "Beta." }
}
fact safe.item {
  claim: "Synthetic safe."
  evidence { source: synthetic quote: "Safe." }
}
'''
    for mode in ("quarantine", "strict"):
        view = resolve_view(compile_workspace(_workspace(source, mode=mode)))
        assert _ids(view.authoritative) == ["fact:safe.item"]
        assert _ids(view.quarantined) == [
            "fact:topic.alpha", "fact:topic.beta"]


def test_use_and_module_context_errors_quarantine_the_source_file() -> None:
    workspace = Workspace(
        registry=TypeRegistry.standard(),
        schema_version="memdsl.workspace.v2",
        linking_visibility="strict",
        enforcement_mode="quarantine",
    )
    workspace.add_document(parse_text('''
module synthetic.first
use Missing.Symbol
fact first.item {
  claim: "Synthetic first."
  evidence { source: synthetic quote: "First." }
}
module synthetic.second
fact second.item {
  claim: "Synthetic second."
  evidence { source: synthetic quote: "Second." }
}
''', file="<phase-five/broken-module.mem>"))
    workspace.add_document(parse_text('''
module synthetic.safe
fact safe.item {
  claim: "Synthetic safe."
  evidence { source: synthetic quote: "Safe." }
}
''', file="<phase-five/safe.mem>"))

    view = resolve_view(compile_workspace(workspace))

    assert _ids(view.authoritative) == ["fact:safe.item"]
    assert set(_ids(view.quarantined)) == {
        "fact:first.item", "fact:second.item"}
    assert {
        code for item in view.quarantined for code in view.reasons_for(item)
    } == {"multiple_module_statements", "unresolved_use_target"}


def _dialect_registry() -> TypeRegistry:
    registry = TypeRegistry.standard()
    registry.register(TypeDescriptor(
        name="synthetic.mapping",
        runtime_role="assertion",
        required_fields=("target", "phrases", "evidence"),
        optional_fields=("polarity",),
        capabilities=frozenset({"dialect_mapping", "searchable"}),
        defaults={"polarity": "positive"},
        allow_extra_fields=False,
        schema_name="synthetic",
        schema_version="1",
        source="<phase-five-schema>",
    ))
    return registry


def test_invalid_ambiguous_and_private_dialect_never_gain_authority() -> None:
    source = '''
module synthetic.all
entity Synthetic.Left { lifecycle { status: active } }
entity Synthetic.Right { lifecycle { status: active } }
synthetic.mapping left.mapping {
  target: Synthetic.Left
  phrases: [sharedphrase]
  evidence { source: synthetic quote: "Left." }
}
synthetic.mapping right.mapping {
  target: Synthetic.Right
  phrases: [sharedphrase]
  evidence { source: synthetic quote: "Right." }
}
synthetic.mapping invalid.mapping {
  target: Synthetic.Left
  phrases: [invalidphrase]
  polarity: negative
  evidence { source: synthetic quote: "Invalid." }
}
synthetic.mapping private.mapping {
  target: Synthetic.Left
  phrases: [privatephrase]
  access_policy { readers: [owner] }
  evidence { source: synthetic quote: "Private." }
}
'''
    workspace = _workspace(
        source, mode="quarantine", registry=_dialect_registry())
    compiled = compile_workspace(workspace)
    view = resolve_view(compiled)

    assert set(_ids(view.quarantined)) == {
        "synthetic.mapping:invalid.mapping",
        "synthetic.mapping:left.mapping",
        "synthetic.mapping:right.mapping",
    }
    assert _ids(view.unauthorized) == ["synthetic.mapping:private.mapping"]
    assert build_evidence_pack(compiled, "sharedphrase").context == []
    assert build_evidence_pack(compiled, "invalidphrase").context == []
    assert build_evidence_pack(compiled, "privatephrase").context == []


def test_access_filtering_precedes_counts_and_requires_trusted_principal() -> None:
    source = '''
fact public.item {
  claim: "Synthetic public."
  evidence { source: synthetic quote: "Public." }
}
fact private.item {
  claim: "Synthetic private."
  access_policy { readers: [owner] }
  evidence { source: synthetic quote: "Private." }
}
'''
    compiled = compile_workspace(_workspace(source, mode="quarantine"))
    untrusted = resolve_view(compiled, ViewContext(
        compiled.source_fingerprint,
        dt.date(2026, 7, 14),
        principal="owner",
        enforcement_mode="quarantine",
    ))
    trusted = resolve_view(compiled, ViewContext(
        compiled.source_fingerprint,
        dt.date(2026, 7, 14),
        principal="owner",
        enforcement_mode="quarantine",
        principal_trusted=True,
    ))

    assert _ids(untrusted.authoritative) == ["fact:public.item"]
    assert _ids(untrusted.unauthorized) == ["fact:private.item"]
    assert untrusted.public_counts() == {
        "authoritative": 1,
        "provisional": 0,
        "quarantined": 0,
        "excluded": 0,
        "served": 1,
    }
    assert _ids(trusted.authoritative) == [
        "fact:private.item", "fact:public.item"]


def test_valid_until_is_enforced_only_in_opt_in_v2_view() -> None:
    registry = TypeRegistry.standard()
    source = '''
state expired.item {
  claim: "Synthetic expired state."
  lifecycle { status: active as_of: 2026-01-01 valid_until: 2026-06-01 }
  evidence { source: synthetic quote: "Expired." }
}
'''
    report = resolve_view(compile_workspace(
        _workspace(source, mode="report", registry=registry)))
    compiled = compile_workspace(
        _workspace(source, mode="quarantine", registry=registry))
    enforced = resolve_view(compiled, ViewContext(
        compiled.source_fingerprint,
        dt.date(2026, 7, 14),
        enforcement_mode="quarantine",
    ))

    assert _ids(report.authoritative) == ["state:expired.item"]
    assert enforced.authoritative == ()
    assert _ids(enforced.excluded) == ["state:expired.item"]
    assert enforced.reasons_for(enforced.excluded[0]) == ("expired",)


@pytest.mark.parametrize(("source", "bad_id", "code"), [
    (
        'mystery broken.item { claim: "Synthetic unknown type." }',
        "mystery:broken.item",
        "unknown_memory_type",
    ),
    (
        '''boundary broken.item {
  rule: "Synthetic invalid guard."
  scope: global
  exceptions: []
  guard: "not-a-block"
  evidence { source: synthetic quote: "Guard." }
}''',
        "boundary:broken.item",
        "invalid_guard",
    ),
    (
        '''state broken.item {
  claim: "Synthetic invalid date."
  as_of: "not-a-date"
  status: active
  evidence { source: synthetic quote: "Date." }
}''',
        "state:broken.item",
        "invalid_lifecycle_date",
    ),
])
def test_type_guard_and_date_errors_are_declaration_local(
    source: str,
    bad_id: str,
    code: str,
) -> None:
    view = resolve_view(compile_workspace(_workspace(
        source + '''
fact safe.item {
  claim: "Synthetic safe sibling."
  evidence { source: synthetic quote: "Safe." }
}
''',
        mode="quarantine",
    )))

    assert _ids(view.authoritative) == ["fact:safe.item"]
    assert _ids(view.quarantined) == [bad_id]
    assert view.reasons_for(view.quarantined[0]) == (code,)


def test_invalid_access_policy_fails_closed_without_poisoning_sibling() -> None:
    view = resolve_view(compile_workspace(_workspace('''
fact broken.item {
  claim: "Synthetic invalid access."
  access_policy: "not-a-block"
  evidence { source: synthetic quote: "Broken." }
}
fact safe.item {
  claim: "Synthetic safe sibling."
  evidence { source: synthetic quote: "Safe." }
}
''', mode="quarantine")))

    assert _ids(view.authoritative) == ["fact:safe.item"]
    assert _ids(view.unauthorized) == ["fact:broken.item"]
    assert view.public_counts()["excluded"] == 0
    assert "broken.item" not in json.dumps(view.envelope())


def test_quarantine_read_gate_keeps_dangling_target_repair_lane_open(
    tmp_path: Path,
) -> None:
    workspace = _workspace('''
fact source.item {
  claim: "Synthetic source."
  relations { supports: missing.target }
  evidence { source: synthetic quote: "Source." }
}
''', mode="quarantine")
    view = resolve_view(compile_workspace(workspace))
    store = ReviewStore(str(tmp_path / ".memdsl"))

    repair = store.validate(workspace, '''
fact missing.target {
  claim: "Synthetic repair target."
  evidence { source: synthetic quote: "Repair." }
}
''')

    assert _ids(view.quarantined) == ["fact:source.item"]
    assert repair.ok is True


def test_v2_query_distinguishes_all_non_success_outcomes() -> None:
    workspace = _workspace('''
fact broken.item {
  claim: "Synthetic broken beacon."
  relations { supports: missing.item }
  evidence { source: synthetic quote: "Broken." }
}
fact draft.item {
  claim: "Synthetic draft beacon."
  lifecycle { status: candidate }
  evidence { source: synthetic quote: "Draft." }
}
''', mode="quarantine")
    view = resolve_view(compile_workspace(workspace))

    assert build_resolved_query(view, "broken beacon")["status"] == "quarantined"
    assert build_resolved_query(view, "draft")["status"] == (
        "provisional_only")
    assert build_resolved_query(view, "absent token")["status"] == "no_match"

    private = resolve_view(compile_workspace(_workspace('''
fact private.item {
  subject: Synthetic.Private
  claim: "Synthetic private beacon."
  access_policy { readers: [owner] }
  evidence { source: synthetic quote: "Private." }
}
''', mode="quarantine")))
    assert build_resolved_query(
        private, "private beacon", subject="Synthetic.Private")["status"] == (
            "unauthorized")

    blocked = resolve_view(compile_workspace(_workspace('''
fact duplicate.item { claim: "One." evidence { source: synthetic quote: "One." } }
fact duplicate.item { claim: "Two." evidence { source: synthetic quote: "Two." } }
''', mode="quarantine")))
    assert build_resolved_query(blocked, "one")["status"] == "compiler_error"


def test_catalog_trace_list_and_explain_share_quarantine_authority() -> None:
    view = resolve_view(compile_workspace(_workspace('''
module synthetic
fact broken.item {
  claim: "Synthetic broken."
  relations { supports: missing.item }
  evidence { source: synthetic quote: "Broken." }
}
fact safe.item {
  claim: "Synthetic safe."
  evidence { source: synthetic quote: "Safe." }
}
''', mode="quarantine")))

    catalog = build_memory_catalog(view)
    listed = build_resolved_list(view)
    explained = build_resolved_explain(view, "fact:broken.item")
    traced = trace_memory(view, ["fact:safe.item"], max_depth=1)

    assert catalog["schema_version"] == "memdsl.catalog.v2"
    assert catalog["summary"]["declarations_authoritative"] == 1
    assert catalog["summary"]["declarations_quarantined"] == 1
    assert [item["id"] for item in listed["items"]] == ["fact:safe.item"]
    assert listed["quarantined_matches"] == [{
        "id": "fact:broken.item", "reasons": ["unresolved_symbol"]}]
    assert explained["status"] == "quarantined"
    assert [item["id"] for item in traced["nodes"]] == ["fact:safe.item"]
    with pytest.raises(TraceAnchorError) as exc_info:
        trace_memory(view, ["fact:broken.item"])
    assert exc_info.value.code == "anchor_quarantined"


def test_compliance_never_allows_unreadable_or_quarantined_constraints() -> None:
    private_view = resolve_view(compile_workspace(_workspace('''
boundary private.rule {
  rule: "Synthetic hidden rule."
  scope: global
  access_policy { readers: [owner] }
  guard { deny_any: [forbidden] }
  evidence { source: synthetic quote: "Hidden." }
}
''', mode="quarantine")))
    private_check = build_resolved_check(
        private_view, "synthetic task", "clean candidate")
    assert private_check["status"] == "unauthorized"
    assert private_check["verdict"] == "needs_review"
    assert "private.rule" not in json.dumps(private_check)

    quarantined_view = resolve_view(compile_workspace(_workspace('''
boundary broken.rule {
  rule: "Synthetic broken rule."
  scope: global
  guard { deny_regex: ["["] }
  evidence { source: synthetic quote: "Broken." }
}
''', mode="quarantine")))
    quarantined_check = build_resolved_check(
        quarantined_view, "synthetic task", "clean candidate")
    assert quarantined_check["status"] == "quarantined"
    assert quarantined_check["verdict"] == "needs_review"
    assert quarantined_check["quarantined_constraints"] == [{
        "id": "boundary:broken.rule",
        "reasons": ["invalid_guard_regex"],
    }]


def test_v2_list_cursor_is_budgeted_and_stale_across_source_revision() -> None:
    first_view = resolve_view(compile_workspace(_workspace('''
fact a.item { claim: "Synthetic A." evidence { source: synthetic quote: "A." } }
fact b.item { claim: "Synthetic B." evidence { source: synthetic quote: "B." } }
fact c.item { claim: "Synthetic C." evidence { source: synthetic quote: "C." } }
''', mode="quarantine")))
    first = build_resolved_list(first_view, limit=1, max_bytes=4096)
    assert first["truncated"] is True
    assert first["next_cursor"]
    assert len(json.dumps(
        first, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")) <= 4096

    changed_view = resolve_view(compile_workspace(_workspace('''
fact a.item { claim: "Synthetic A changed." evidence { source: synthetic quote: "A2." } }
fact b.item { claim: "Synthetic B." evidence { source: synthetic quote: "B." } }
fact c.item { claim: "Synthetic C." evidence { source: synthetic quote: "C." } }
''', mode="quarantine")))
    with pytest.raises(ResolvedCursorError) as exc_info:
        build_resolved_list(changed_view, cursor=first["next_cursor"])
    assert exc_info.value.code == "cursor_stale"


def test_mcp_switches_to_v2_only_for_explicit_enforcement(tmp_path: Path) -> None:
    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v2",
        "schemas": [],
        "linking": {"visibility": "report"},
        "enforcement": {"mode": "quarantine"},
    }), encoding="utf-8")
    (tmp_path / "memory.mem").write_text('''
module synthetic
fact broken.item {
  claim: "Synthetic broken beacon."
  relations { supports: missing.item }
  evidence { source: synthetic quote: "Broken." }
}
fact safe.item {
  claim: "Synthetic safe beacon."
  evidence { source: synthetic quote: "Safe." }
}
''', encoding="utf-8")
    service = MemdslMCPService([str(tmp_path)])

    assert service.status()["schema_version"] == "memdsl.mcp.status.v2"
    assert service.memory_map()["status"] == "unsupported_view"
    assert service.catalog()["schema_version"] == "memdsl.mcp.catalog.v2"
    assert service.query("broken")["status"] == "quarantined"
    assert service.list_declarations()["schema_version"] == "memdsl.mcp.list.v2"
    assert service.explain("fact:broken.item")["status"] == "quarantined"
    assert service.trace(["fact:safe.item"])["schema_version"] == (
        "memdsl.mcp.trace.v2")


def test_v2_report_manifest_keeps_every_v1_read_schema(tmp_path: Path) -> None:
    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v2",
        "schemas": [],
        "linking": {"visibility": "report"},
        "enforcement": {"mode": "report"},
    }), encoding="utf-8")
    (tmp_path / "memory.mem").write_text('''
fact safe.item {
  claim: "Synthetic safe beacon."
  evidence { source: synthetic quote: "Safe." }
}
''', encoding="utf-8")
    service = MemdslMCPService([str(tmp_path)])

    assert service.memory_map()["schema_version"] == "memdsl.mcp.map.v1"
    assert service.catalog()["schema_version"] == "memdsl.mcp.catalog.v1"
    assert service.query("safe")["schema_version"] == "memdsl.mcp.query.v1"
    assert service.trace(["fact:safe.item"])["schema_version"] == (
        "memdsl.mcp.trace.v1")
    assert service.list_declarations()["schema_version"] == (
        "memdsl.mcp.list.v1")
    assert service.explain("fact:safe.item")["schema_version"] == (
        "memdsl.mcp.explain.v1")


def test_enforced_mcp_raw_resources_do_not_bypass_mixed_file_access(
    tmp_path: Path,
) -> None:
    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v2",
        "schemas": [],
        "linking": {"visibility": "report"},
        "enforcement": {"mode": "quarantine"},
    }), encoding="utf-8")
    (tmp_path / "mixed.mem").write_text('''
fact public.item {
  claim: "Synthetic public."
  evidence { source: synthetic quote: "Public." }
}
fact private.item {
  claim: "Synthetic private."
  access_policy { readers: [owner] }
  evidence { source: synthetic quote: "Private." }
}
''', encoding="utf-8")
    untrusted = MemdslMCPService([str(tmp_path)])
    trusted = MemdslMCPService(
        [str(tmp_path)], principal="owner", principal_trusted=True)

    assert untrusted.list_files()["files"] == []
    assert untrusted.read_file("mixed.mem")["status"] == "unauthorized"
    assert "private.item" not in json.dumps(untrusted.status())
    assert trusted.list_files()["files"][0]["path"] == "mixed.mem"
    assert "fact private.item" in trusted.read_file("0")["content"]


def test_pending_proposal_stays_out_of_enforced_view_until_approval(
    tmp_path: Path,
) -> None:
    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v2",
        "schemas": [],
        "linking": {"visibility": "report"},
        "enforcement": {"mode": "quarantine"},
    }), encoding="utf-8")
    target = tmp_path / "memory.mem"
    target.write_text('''
fact base.item {
  claim: "Synthetic base."
  evidence { source: synthetic quote: "Base." }
}
''', encoding="utf-8")
    service = MemdslMCPService([str(tmp_path)])
    proposal = service.propose('''
fact reviewed.item {
  claim: "Synthetic reviewed beacon."
  evidence { source: synthetic_review quote: "Reviewed." }
}
''', reason="synthetic Phase 5 review")

    assert proposal["status"] == "pending_review"
    assert service.query("reviewed beacon")["status"] == "no_match"
    approved = service.review_store.approve(
        proposal["proposal_id"], Workspace.load([str(tmp_path)]), str(target))
    assert approved["status"] == "approved"
    assert service.query("reviewed beacon")["status"] == "ok"
    assert [
        item["action"] for item in service.review_store.audit_entries()
    ] == ["propose", "route", "approve"]


def test_query_and_explain_v2_fail_loud_when_budget_cannot_fit_content() -> None:
    view = resolve_view(compile_workspace(_workspace('''
fact huge.item {
  claim: "''' + ("x" * 6000) + '''"
  evidence { source: synthetic quote: "''' + ("y" * 6000) + '''" }
}
''', mode="quarantine")))

    query = build_resolved_query(view, "x", max_bytes=2048)
    explain = build_resolved_explain(
        view, "fact:huge.item", max_bytes=2048)

    assert query["status"] == "budget_limited"
    assert query["completeness"] == "incomplete"
    assert explain["status"] in {"ok", "budget_limited"}
    assert len(json.dumps(
        explain, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")) <= 2048


def test_enforced_view_and_read_envelopes_are_order_and_hash_seed_deterministic(
) -> None:
    repository = Path(__file__).resolve().parents[1]
    script = r'''
import json
from memdsl.compiler import compile_workspace
from memdsl.model import Workspace
from memdsl.parser import parse_text
from memdsl.serving import build_resolved_list, build_resolved_query
from memdsl.view import resolve_view
workspace = Workspace(
    schema_version="memdsl.workspace.v2",
    linking_visibility="report",
    enforcement_mode="quarantine",
)
workspace.add_document(parse_text("""
fact broken.item {
  claim: "Synthetic broken beacon."
  relations { supports: missing.item }
  evidence { source: synthetic quote: "Broken." }
}
fact safe.item {
  claim: "Synthetic safe beacon."
  evidence { source: synthetic quote: "Safe." }
}
""", file="<hash/memory.mem>"))
view = resolve_view(compile_workspace(workspace))
print(json.dumps({
    "view": view.envelope(),
    "list": build_resolved_list(view, max_bytes=8192),
    "query": build_resolved_query(view, "broken", max_bytes=8192),
}, sort_keys=True))
'''
    outputs = []
    for seed in ("1", "777"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(repository / "src")
        outputs.append(subprocess.check_output(
            [sys.executable, "-c", script],
            cwd=repository,
            env=env,
            text=True,
        ))
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("declarations", [100, 1000, 10000])
def test_enforced_catalog_query_trace_and_list_stay_bounded_at_scale(
    declarations: int,
) -> None:
    source = []
    for index in range(declarations):
        relation = (
            f"relations {{ supports: item.{index + 1:05d} }}"
            if index + 1 < declarations else ""
        )
        source.append(f'''
fact item.{index:05d} {{
  claim: "Synthetic scale node token{index:05d}."
  {relation}
  evidence {{ source: synthetic_generator quote: "Node {index:05d}." }}
}}
''')
    view = resolve_view(compile_workspace(_workspace(
        "\n".join(source), mode="quarantine")))

    catalog = build_memory_catalog(view)
    query = build_resolved_query(
        view, f"token{declarations - 1:05d}", max_bytes=8192)
    traced = trace_memory(
        view, ["fact:item.00000"], max_depth=declarations,
        max_nodes=20, max_edges=20, max_bytes=8192)
    listed = build_resolved_list(view, limit=20, max_bytes=8192)

    for payload in (catalog, query, traced, listed):
        assert len(json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")) <= 8192
    assert query["evidence_pack"]["search_trace"][
        "candidate_pool_total"] == 1
    assert traced["returned_nodes"] <= 20
    assert listed["returned_items"] <= 20


def test_cli_v2_status_and_exit_contracts_are_opt_in(
    tmp_path: Path,
    capsys,
) -> None:
    alex = Path(__file__).parents[1] / "examples" / "alex"
    assert cli_main([
        "explain", str(alex), "boundary:privacy.no_family_in_public",
    ]) == 0
    assert "privacy.no_family_in_public" in capsys.readouterr().out

    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v2",
        "schemas": [],
        "linking": {"visibility": "report"},
        "enforcement": {"mode": "quarantine"},
    }), encoding="utf-8")
    (tmp_path / "memory.mem").write_text('''
fact broken.item {
  claim: "Synthetic broken beacon."
  relations { supports: missing.item }
  evidence { source: synthetic quote: "Broken." }
}
boundary broken.rule {
  rule: "Synthetic broken constraint."
  scope: global
  guard { deny_regex: ["["] }
  evidence { source: synthetic quote: "Constraint." }
}
fact safe.item {
  claim: "Synthetic safe beacon."
  evidence { source: synthetic quote: "Safe." }
}
''', encoding="utf-8")
    path = str(tmp_path)

    assert cli_main(["map", path, "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "unsupported_view"

    assert cli_main(["catalog", path, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == (
        "memdsl.catalog.v2")

    assert cli_main(["query", path, "-q", "broken beacon", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "quarantined"

    assert cli_main(["trace", path, "fact:broken.item", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "anchor_quarantined"

    assert cli_main(["explain", path, "fact:broken.item", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "quarantined"

    assert cli_main([
        "check", path, "-t", "synthetic task", "-c", "clean candidate",
        "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "quarantined"


def test_real_mcp_stdio_serves_v2_quarantine_and_scope_denial(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp")
    from mcp.client.stdio import StdioServerParameters, stdio_client

    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v2",
        "schemas": [],
        "linking": {"visibility": "report"},
        "enforcement": {"mode": "quarantine"},
    }), encoding="utf-8")
    (tmp_path / "memory.mem").write_text('''
fact broken.item {
  claim: "Synthetic broken beacon."
  relations { supports: missing.item }
  evidence { source: synthetic quote: "Broken." }
}
fact safe.item {
  claim: "Synthetic safe beacon."
  evidence { source: synthetic quote: "Safe." }
}
''', encoding="utf-8")

    def payload(result) -> dict:
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        for item in getattr(result, "content", []):
            text = getattr(item, "text", "")
            if text:
                return json.loads(text)
        raise AssertionError("MCP result did not contain JSON")

    async def run(scopes: str = "") -> None:
        from mcp import ClientSession

        args = ["-m", "memdsl.mcp_server", "--workspace", str(tmp_path)]
        if scopes:
            args.extend(["--scopes", scopes])
        parameters = StdioServerParameters(command=sys.executable, args=args)
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 11
                status_resource = await session.read_resource("memdsl://status")
                status = json.loads(status_resource.contents[0].text)
                assert status["schema_version"] == "memdsl.mcp.status.v2"
                result = await session.call_tool(
                    "memory_query", {"query": "broken"})
                if scopes:
                    assert result.isError is True
                    return
                assert payload(result)["status"] == "quarantined"
                listed = payload(await session.call_tool("memory_list", {}))
                assert [item["id"] for item in listed["items"]] == [
                    "fact:safe.item"]
                explained = payload(await session.call_tool(
                    "memory_explain", {"id": "fact:broken.item"}))
                assert explained["status"] == "quarantined"
                traced = payload(await session.call_tool(
                    "memory_trace", {"anchors": ["fact:safe.item"]}))
                assert traced["schema_version"] == "memdsl.mcp.trace.v2"

    asyncio.run(run())
    asyncio.run(run("read:summary"))
