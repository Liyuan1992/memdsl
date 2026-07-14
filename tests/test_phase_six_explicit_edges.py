"""Phase 6 experimental first-class explicit Edge contract and safety gates."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Optional
import asyncio

import pytest

from memdsl.authority import current_declarations
from memdsl.cli import main as cli_main
from memdsl.compiler import compile_workspace
from memdsl.compliance import check_compliance
from memdsl.edge import (
    build_edge_transition_source,
    build_explicit_edge_catalog,
    confirm_edge_proposal,
    propose_edge_transition,
)
from memdsl.graph import trace_memory
from memdsl.mcp_service import MemdslMCPService, TOOL_NAMES
from memdsl.model import Workspace
from memdsl.policy import POLICY_VERSION, PolicyError, ProposalContext, ReviewPolicy
from memdsl.review import ReviewStore, staging_dir_for
from memdsl.schema import SchemaError
from memdsl.view import resolve_view


V3_MANIFEST = {
    "schema_version": "memdsl.workspace.v3",
    "schemas": [],
    "linking": {"visibility": "report"},
    "enforcement": {"mode": "report"},
    "features": {"explicit_edges": "experimental-v1"},
}

NODES = '''\
module fictional.graph

entity Reviewer {
  canonical_name: "Fictional reviewer"
  status: active
}

fact graph.alpha {
  claim: "Synthetic alpha node."
  status: active
  evidence { source: synthetic_fixture quote: "Alpha exists." }
}

fact graph.beta {
  claim: "Synthetic beta node."
  status: active
  evidence { source: synthetic_fixture quote: "Beta exists." }
}
'''


def edge_source(
    name: str = "graph.alpha_supports_beta",
    *,
    spelling: str = "relation_edge",
    relation: str = "supports",
    status: str = "active",
    access: str = "",
) -> str:
    access_block = (
        f"\n  access_policy {{ readers: [{access}] }}" if access else "")
    return f'''\
{spelling} {name} {{
  declared_by: "entity:Reviewer"
  source: "fact:graph.alpha"
  target: "fact:graph.beta"
  relation: {relation}
  lifecycle {{ status: {status} }}{access_block}
  evidence {{
    source: synthetic_fixture
    quote: "Alpha supports beta in this fictional example."
  }}
}}
'''


def write_workspace(
    root: Path,
    *,
    source: str = NODES,
    manifest: Optional[dict] = None,
    enforcement: str = "report",
) -> Path:
    root.mkdir()
    payload = dict(V3_MANIFEST if manifest is None else manifest)
    if payload.get("schema_version") == "memdsl.workspace.v3":
        payload = json.loads(json.dumps(payload))
        payload["enforcement"] = {"mode": enforcement}
    (root / "memdsl.json").write_text(
        json.dumps(payload), encoding="utf-8")
    (root / "memory.mem").write_text(source, encoding="utf-8")
    return root


def load(root: Path) -> Workspace:
    return Workspace.load([str(root)])


def test_workspace_v3_feature_is_required_and_old_lines_remain_fail_closed(
    tmp_path: Path,
) -> None:
    no_manifest = tmp_path / "no-manifest"
    no_manifest.mkdir()
    (no_manifest / "memory.mem").write_text(
        NODES + edge_source(), encoding="utf-8")
    with pytest.raises(SchemaError, match="workspace.v3"):
        load(no_manifest)

    v2 = write_workspace(
        tmp_path / "v2",
        source=NODES + edge_source(),
        manifest={
            "schema_version": "memdsl.workspace.v2",
            "schemas": [],
            "linking": {"visibility": "report"},
        },
    )
    with pytest.raises(SchemaError, match="workspace.v3"):
        load(v2)

    missing_feature = write_workspace(
        tmp_path / "v3-missing",
        source=NODES,
        manifest={
            "schema_version": "memdsl.workspace.v3",
            "schemas": [],
            "linking": {"visibility": "report"},
            "features": {},
        },
    )
    with pytest.raises(SchemaError, match="features.explicit_edges"):
        load(missing_feature)

    valid = write_workspace(
        tmp_path / "v3-valid", source=NODES + edge_source())
    workspace = load(valid)
    assert workspace.schema_version == "memdsl.workspace.v3"
    assert workspace.explicit_edges_enabled is True


def test_v1_surfaces_keep_exact_tool_set_and_no_edge_envelope_fields(
    tmp_path: Path,
) -> None:
    root = tmp_path / "legacy"
    root.mkdir()
    (root / "memory.mem").write_text(NODES, encoding="utf-8")
    service = MemdslMCPService([str(root)])
    assert TOOL_NAMES == (
        "memory_catalog", "memory_map", "memory_query", "memory_trace",
        "memory_check", "memory_types", "memory_explain", "memory_list",
        "memory_lint", "memory_propose", "memory_review_list",
    )
    status = service.status()
    assert "explicit_edges" not in status
    assert "registered_edge_relations" not in status
    assert "edge_relations" not in service.list_types()
    legacy_list = service.list_declarations(kind="relation_edge")
    legacy_explain = service.explain("relation_edge:missing")
    assert legacy_list["schema_version"] == "memdsl.mcp.list.v1"
    assert legacy_list["total"] == 0
    assert legacy_explain["schema_version"] == "memdsl.mcp.explain.v1"
    assert "edge" not in legacy_explain
    invalid_filter = service.trace(
        ["fact:graph.alpha"], relations=["contradicts"])
    assert invalid_filter["status"] == "invalid"


def test_v2_enforced_envelopes_keep_exact_pre_edge_compatibility(
    tmp_path: Path,
) -> None:
    root = write_workspace(
        tmp_path / "v2-enforced",
        source=NODES,
        manifest={
            "schema_version": "memdsl.workspace.v2",
            "schemas": [],
            "linking": {"visibility": "report"},
            "enforcement": {"mode": "quarantine"},
        },
        enforcement="quarantine",
    )
    service = MemdslMCPService([str(root)])
    status = service.status()
    assert status["schema_version"] == "memdsl.mcp.status.v2"
    assert status["view"]["view"]["compatibility_mode"] == "workspace.v2"
    assert resolve_view(compile_workspace(load(root))).context.compatibility_mode == (
        "workspace.v2")
    assert "explicit_edges" not in status
    legacy_list = service.list_declarations(kind="relation_edge")
    legacy_explain = service.explain("relation_edge:missing")
    assert legacy_list["schema_version"] == "memdsl.mcp.list.v2"
    assert legacy_explain["schema_version"] == "memdsl.mcp.explain.v2"
    assert "edge" not in legacy_explain


def test_record_owner_and_graph_endpoints_are_distinct_and_stable(
    tmp_path: Path,
) -> None:
    first = write_workspace(
        tmp_path / "first", source=NODES + edge_source())
    second = write_workspace(
        tmp_path / "second",
        source=edge_source() + "\n" + NODES,
    )
    first_compiled = compile_workspace(load(first), paths=[str(first)])
    second_compiled = compile_workspace(load(second), paths=[str(second)])
    edge = first_compiled.explicit_edges[0]
    assert edge.edge_id == edge.record_id == "relation_edge:graph.alpha_supports_beta"
    assert edge.declared_by_id == "entity:Reviewer"
    assert edge.source_id == "fact:graph.alpha"
    assert edge.target_id == "fact:graph.beta"
    assert edge.record_id not in {edge.source_id, edge.target_id}
    assert second_compiled.explicit_edges[0].edge_id == edge.edge_id

    script = (
        "from memdsl.model import Workspace; "
        "from memdsl.compiler import compile_workspace; "
        f"w=Workspace.load([{str(first)!r}]); "
        "print(compile_workspace(w).explicit_edges[0].edge_id)"
    )
    outputs = []
    for seed in ("1", "8675309"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        outputs.append(subprocess.check_output(
            [sys.executable, "-c", script], env=env, text=True).strip())
    assert outputs == [edge.edge_id, edge.edge_id]


@pytest.mark.parametrize("hidden_part", ["record", "source", "target"])
def test_access_intersection_hides_edge_before_counts_traversal_and_diagnostics(
    tmp_path: Path, hidden_part: str,
) -> None:
    nodes = NODES
    access = ""
    if hidden_part == "record":
        access = "edge-reader"
    elif hidden_part == "source":
        nodes = nodes.replace(
            'fact graph.alpha {\n',
            'fact graph.alpha {\n  access_policy { readers: [edge-reader] }\n')
    else:
        nodes = nodes.replace(
            'fact graph.beta {\n',
            'fact graph.beta {\n  access_policy { readers: [edge-reader] }\n')
    root = write_workspace(
        tmp_path / hidden_part,
        source=nodes + edge_source(access=access),
        enforcement="quarantine",
    )
    untrusted = MemdslMCPService([str(root)])
    listing = untrusted.list_declarations(kind="relation_edge")
    assert listing["total"] == 0
    status_text = json.dumps(untrusted.status())
    lint_text = json.dumps(untrusted.lint_workspace())
    trace = untrusted.trace(
        ["fact:graph.alpha"], direction="both", max_depth=1)
    assert 'relation_edge:graph.alpha_supports_beta' not in status_text
    assert 'relation_edge:graph.alpha_supports_beta' not in lint_text
    assert trace.get("available_edges", 0) == 0

    trusted = MemdslMCPService(
        [str(root)],
        principal="fictional-reviewer",
        principal_trusted=True,
        principal_roles=["edge-reader"],
    )
    assert trusted.list_declarations(kind="relation_edge")["total"] == 1
    trusted_trace = trusted.trace(
        ["fact:graph.alpha"], direction="both", max_depth=1)
    assert trusted_trace["available_edges"] == 1


def test_relation_registry_has_pilot_minimum_and_refines_is_extension_only(
    tmp_path: Path,
) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    schema = {
        "name": "lab",
        "version": "1",
        "types": {},
        "relations": {
            "refines": {
                "stability": "experimental",
                "description": "Fictional refinement relation.",
            },
        },
    }
    (root / "lab.memschema.json").write_text(
        json.dumps(schema), encoding="utf-8")
    manifest = json.loads(json.dumps(V3_MANIFEST))
    manifest["schemas"] = ["lab.memschema.json"]
    (root / "memdsl.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "memory.mem").write_text(
        NODES + edge_source(relation="lab.refines"), encoding="utf-8")
    workspace = load(root)
    builtin_descriptors = [
        item for item in workspace.registry.edge_relation_descriptors()
        if item.source.startswith("<builtin:")
    ]
    builtins = {item.name for item in builtin_descriptors}
    assert builtins == {"supports", "depends_on", "supersedes", "contradicts"}
    assert {item.stability for item in builtin_descriptors} == {"experimental"}
    assert workspace.registry.resolve_edge_relation("refines") is None
    extension = workspace.registry.resolve_edge_relation("lab.refines")
    assert extension is not None and extension.stability == "experimental"


def test_hidden_edge_diagnostics_are_filtered_before_counts(tmp_path: Path) -> None:
    root = write_workspace(
        tmp_path / "hidden-diagnostic",
        source=NODES + edge_source(
            relation="fictional.unknown", access="edge-reader"),
        enforcement="quarantine",
    )
    hidden = MemdslMCPService([str(root)]).lint_workspace()
    hidden_status = MemdslMCPService([str(root)]).status()
    hidden_text = json.dumps({"lint": hidden, "status": hidden_status})
    assert "graph.alpha_supports_beta" not in hidden_text
    assert "unknown_edge_relation" not in hidden_text

    visible = MemdslMCPService(
        [str(root)],
        principal="fictional-reviewer",
        principal_trusted=True,
        principal_roles=["edge-reader"],
    ).lint_workspace()
    assert any(
        item["code"] == "unknown_edge_relation"
        for item in visible["diagnostics"])


def test_report_mode_filters_hidden_edge_before_diagnostics_and_vocabulary_use(
    tmp_path: Path,
) -> None:
    root = write_workspace(
        tmp_path / "report-hidden-diagnostic",
        source=NODES + edge_source(
            relation="fictional.unknown", access="edge-reader"),
        enforcement="report",
    )
    service = MemdslMCPService([str(root)])
    payloads = {
        "status": service.status(),
        "lint": service.lint_workspace(),
        "list": service.list_declarations(kind="relation_edge"),
        "trace": service.trace(["fact:graph.alpha"], max_depth=1),
    }
    rendered = json.dumps(payloads)
    assert "graph.alpha_supports_beta" not in rendered
    assert "unknown_edge_relation" not in rendered
    assert payloads["list"]["total"] == 0
    assert payloads["trace"]["available_edges"] == 0


def test_report_mode_keeps_public_invalid_edge_diagnostics_repairable(
    tmp_path: Path,
) -> None:
    root = write_workspace(
        tmp_path / "report-public-diagnostic",
        source=NODES + edge_source().replace(
            'target: "fact:graph.beta"', 'target: "fact:graph.missing"'),
        enforcement="report",
    )
    payload = MemdslMCPService([str(root)]).lint_workspace()
    assert "unresolved_edge_target" in {
        item["code"] for item in payload["diagnostics"]}


def test_hidden_kind_mismatch_candidate_does_not_leak_through_diagnostics(
    tmp_path: Path,
) -> None:
    nodes = NODES.replace(
        'fact graph.alpha {\n',
        'fact graph.alpha {\n  access_policy { readers: [edge-reader] }\n')
    source = edge_source().replace(
        'source: "fact:graph.alpha"', 'source: "decision:graph.alpha"')
    root = write_workspace(
        tmp_path / "hidden-kind-mismatch",
        source=nodes + source,
        enforcement="report",
    )
    payload = MemdslMCPService([str(root)]).lint_workspace()
    rendered = json.dumps(payload)
    assert "graph.alpha_supports_beta" not in rendered
    assert "edge_source_kind_mismatch" not in rendered


@pytest.mark.parametrize(("source", "expected_code"), [
    (edge_source().replace(
        'quote: "Alpha supports beta in this fictional example."',
        'quote: ""'), "invalid_edge_evidence"),
    (edge_source().replace(
        'source: "fact:graph.alpha"', 'source: "graph.alpha"'),
     "edge_source_requires_full_id"),
    (edge_source().replace(
        "lifecycle { status: active }", "status: active"),
     "invalid_edge_lifecycle"),
    (edge_source().replace(
        "  evidence {", "  access: public\n  evidence {"),
     "invalid_edge_access_policy"),
])
def test_structurally_invalid_active_edge_never_enters_graph(
    tmp_path: Path, source: str, expected_code: str,
) -> None:
    root = write_workspace(
        tmp_path / expected_code, source=NODES + source)
    compiled = compile_workspace(load(root))
    assert len(compiled.explicit_edges) == 1
    assert compiled.authoritative_explicit_edges == ()
    trace = trace_memory(
        compiled, ["fact:graph.alpha"], max_depth=1, max_bytes=8192)
    assert trace["available_edges"] == 0
    lint_payload = MemdslMCPService([str(root)]).lint_workspace()
    assert expected_code in {
        item["code"] for item in lint_payload["diagnostics"]}


def test_invalid_edge_event_cannot_change_lifecycle_state(tmp_path: Path) -> None:
    root = write_workspace(
        tmp_path / "invalid-event", source=NODES + edge_source())
    event = build_edge_transition_source(
        "graph.alpha_supports_beta",
        "retract",
        evidence_source="synthetic_fixture",
        evidence_quote="Fictional retraction evidence.",
        event_id="event.invalid_retract",
        event_at="2026-07-15T00:00:00+00:00",
    ).replace(
        'quote: "Fictional retraction evidence."', 'quote: ""')
    (root / "events.edges.mem").write_text(event, encoding="utf-8")
    compiled = compile_workspace(load(root))
    edge = compiled.explicit_edges_by_id[
        "relation_edge:graph.alpha_supports_beta"]
    assert edge.lifecycle_status == "active"
    assert edge.authoritative is True
    assert edge.events == ()
    lint_payload = MemdslMCPService([str(root)]).lint_workspace()
    assert "invalid_edge_event_evidence" in {
        item["code"] for item in lint_payload["diagnostics"]}


def test_schema_and_policy_cannot_make_explicit_edges_auto_approvable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "schema-floor"
    root.mkdir()
    (root / "bad.memschema.json").write_text(json.dumps({
        "name": "bad",
        "version": "1",
        "types": {
            "edge_like": {
                "runtime_role": "assertion",
                "capabilities": ["explicit_edge", "auto_approvable"],
            },
        },
    }), encoding="utf-8")
    manifest = json.loads(json.dumps(V3_MANIFEST))
    manifest["schemas"] = ["bad.memschema.json"]
    (root / "memdsl.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "memory.mem").write_text(NODES, encoding="utf-8")
    with pytest.raises(SchemaError, match="cannot combine explicit Edge"):
        load(root)

    policy = ReviewPolicy.from_dict({
        "version": POLICY_VERSION,
        "default_route": "queue",
        "auto_merge_into": "auto-approved.mem",
        "sample_to_queue_percent": 0,
        "max_auto_approve_per_day": 10,
        "trusted_clients": ["fictional-host"],
        "rules": [{
            "name": "forbidden-edge-auto",
            "route": "auto_approve",
            "match": {"kind": ["relation_edge"]},
        }],
    })
    good = write_workspace(
        tmp_path / "policy-floor", source=NODES + edge_source(status="candidate"))
    with pytest.raises(PolicyError, match="requires human review"):
        policy.validate_registry(load(good).registry)


@pytest.mark.parametrize("capability", [
    "relation_edge", "explicit_edge", "relation_edge_event",
    "explicit_edge_event", "edge_lifecycle",
])
def test_every_reserved_edge_capability_rejects_auto_approvable_schema(
    tmp_path: Path, capability: str,
) -> None:
    root = tmp_path / capability
    root.mkdir()
    (root / "bad.memschema.json").write_text(json.dumps({
        "name": "bad",
        "version": "1",
        "types": {
            "edge_like": {
                "runtime_role": "assertion",
                "capabilities": [capability, "auto_approvable"],
            },
        },
    }), encoding="utf-8")
    (root / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v1",
        "schemas": ["bad.memschema.json"],
    }), encoding="utf-8")
    (root / "memory.mem").write_text(NODES, encoding="utf-8")
    with pytest.raises(SchemaError, match="cannot combine explicit Edge"):
        load(root)


@pytest.mark.parametrize("capability", [
    "relation_edge", "explicit_edge", "relation_edge_event",
    "explicit_edge_event", "edge_lifecycle",
])
def test_every_reserved_edge_capability_gets_human_queue_reason(
    tmp_path: Path, capability: str,
) -> None:
    root = tmp_path / f"queue-{capability}"
    root.mkdir()
    (root / "edge-like.memschema.json").write_text(json.dumps({
        "name": "synthetic",
        "version": "1",
        "types": {
            "edge_like": {
                "runtime_role": "assertion",
                "required_fields": ["claim", "evidence"],
                "capabilities": [capability],
            },
        },
    }), encoding="utf-8")
    (root / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v1",
        "schemas": ["edge-like.memschema.json"],
    }), encoding="utf-8")
    (root / "memory.mem").write_text(NODES, encoding="utf-8")
    policy = ReviewPolicy.from_dict({
        "version": POLICY_VERSION,
        "default_route": "queue",
        "auto_merge_into": "auto-approved.mem",
        "sample_to_queue_percent": 0,
        "max_auto_approve_per_day": 10,
        "trusted_clients": ["fictional-host"],
        "rules": [{
            "name": "try-edge-like-auto",
            "route": "auto_approve",
            "match": {"kind": ["synthetic.edge_like"]},
        }],
    })
    store = ReviewStore(staging_dir_for([str(root)]))
    result = store.submit(
        [str(root)],
        '''synthetic.edge_like sample {
  claim: "Synthetic edge-like candidate."
  lifecycle { status: candidate }
  evidence { source: synthetic_fixture quote: "Synthetic evidence." }
}\n''',
        policy=policy,
        context=ProposalContext(client_id="fictional-host"),
        write_auto_granted=True,
    )
    assert result["status"] == "pending_review"
    assert "explicit_edge_human_review_required" in result["reason_codes"]


@pytest.mark.parametrize("spelling", ["relation_edge", "explicit_edge"])
@pytest.mark.parametrize(
    "event_spelling", ["relation_edge_event", "explicit_edge_event"])
def test_every_edge_spelling_and_lifecycle_event_routes_to_human_queue(
    tmp_path: Path, spelling: str, event_spelling: str,
) -> None:
    root = write_workspace(
        tmp_path / spelling, source=NODES + edge_source())
    store = ReviewStore(staging_dir_for([str(root)]))
    disabled_policy = ReviewPolicy.from_dict({
        "version": POLICY_VERSION,
        "default_route": "queue",
        "auto_merge_into": "auto-approved.mem",
        "sample_to_queue_percent": 0,
        "max_auto_approve_per_day": 10,
        "trusted_clients": ["fictional-host"],
        "rules": [],
    })
    queued = store.submit(
        [str(root)], edge_source(name="graph.second", spelling=spelling),
        policy=disabled_policy,
        context=ProposalContext(client_id="fictional-host"),
        write_auto_granted=True,
    )
    assert queued["status"] == "pending_review"
    assert "explicit_edge_human_review_required" in queued["reason_codes"]

    event = build_edge_transition_source(
        "graph.alpha_supports_beta",
        "retract",
        evidence_source="synthetic_fixture",
        evidence_quote="Fictional retraction evidence.",
        event_id="event.retract",
        event_at="2026-07-15T00:00:00+00:00",
    )
    event = event.replace("relation_edge_event ", f"{event_spelling} ", 1)
    event_result = store.submit(
        [str(root)], event,
        policy=disabled_policy,
        context=ProposalContext(client_id="fictional-host"),
        write_auto_granted=True,
    )
    assert event_result["status"] == "pending_review"
    assert "explicit_edge_human_review_required" in event_result["reason_codes"]


def test_pending_edge_is_not_serviceable_and_confirmation_uses_target_context(
    tmp_path: Path,
) -> None:
    root = write_workspace(tmp_path / "review", source=NODES)
    (root / "edges.mem").write_text(
        "module fictional.reviewed_edges\nuse fictional.graph\n",
        encoding="utf-8",
    )
    service = MemdslMCPService([str(root)])
    proposed = service.propose(edge_source(), reason="synthetic edge review")
    assert proposed["status"] == "pending_review"
    assert "explicit_edge_human_review_required" in proposed["reason_codes"]
    assert service.list_declarations(kind="relation_edge")["total"] == 0
    assert service.trace(
        ["fact:graph.alpha"], direction="outgoing", max_depth=1
    )["available_edges"] == 0

    workspace = load(root)
    generic = service.review_store.approve(
        proposed["proposal_id"], workspace, str(root / "approved.mem"))
    assert generic["status"] == "edge_target_context_required"
    confirmed = confirm_edge_proposal(
        service.review_store,
        proposed["proposal_id"],
        workspace,
        str(root / "edges.mem"),
    )
    assert confirmed["status"] == "approved"
    assert [
        item["action"]
        for item in service.review_store.audit_entries(strict=True)
    ] == ["propose", "route", "approve"]
    reloaded = load(root)
    assert reloaded.explicit_edges[0].module == "fictional.reviewed_edges"
    assert MemdslMCPService([str(root)]).list_declarations(
        kind="relation_edge")["total"] == 1


def test_dedicated_edge_target_rejects_ordinary_declarations(
    tmp_path: Path,
) -> None:
    root = write_workspace(tmp_path / "bad-target", source=NODES)
    (root / "edges.mem").write_text(
        'fact misplaced { claim: "Wrong file." status: active '
        'evidence { source: synthetic quote: "Wrong file." } }\n',
        encoding="utf-8",
    )
    store = ReviewStore(staging_dir_for([str(root)]))
    proposed = store.submit([str(root)], edge_source())
    result = confirm_edge_proposal(
        store, proposed["proposal_id"], load(root), str(root / "edges.mem"))
    assert result["status"] == "stale_or_invalid"
    assert {item["code"] for item in result["errors"]} == {
        "edge_target_not_dedicated"}


def test_edge_confirmation_rejects_invalid_target_module_use_context(
    tmp_path: Path,
) -> None:
    manifest = json.loads(json.dumps(V3_MANIFEST))
    manifest["linking"] = {"visibility": "strict"}
    root = write_workspace(
        tmp_path / "bad-target-use", source=NODES, manifest=manifest)
    (root / "edges.mem").write_text(
        "module fictional.reviewed_edges\nuse fictional.missing\n",
        encoding="utf-8",
    )
    store = ReviewStore(staging_dir_for([str(root)]))
    proposed = store.submit([str(root)], edge_source())
    result = confirm_edge_proposal(
        store, proposed["proposal_id"], load(root), str(root / "edges.mem"))
    assert result["status"] == "stale_or_invalid"
    assert "unresolved_use_target" in {
        item["code"] for item in result["errors"]}


def test_lifecycle_events_change_only_edge_record_not_endpoints(
    tmp_path: Path,
) -> None:
    root = write_workspace(
        tmp_path / "lifecycle",
        source=NODES + edge_source()
        + edge_source("graph.replacement", relation="depends_on"),
    )
    store = ReviewStore(staging_dir_for([str(root)]))
    target = root / "edges.mem"
    target.write_text("module fictional.edge_events\n", encoding="utf-8")

    def transition(action: str, *, replacement: str = "") -> None:
        result = propose_edge_transition(
            store,
            [str(root)],
            "graph.alpha_supports_beta",
            action,
            evidence_source="synthetic_fixture",
            evidence_quote=f"Fictional {action} evidence.",
            event_id=f"event.{action}.{len(store.list(status='all'))}",
            event_at=f"2026-07-15T00:00:0{len(store.list(status='all'))}+00:00",
            replacement=replacement,
        )
        assert result["status"] == "pending_review"
        approved = confirm_edge_proposal(
            store, result["proposal_id"], load(root), str(target))
        assert approved["status"] == "approved"

    transition("dispute")
    assert compile_workspace(load(root)).explicit_edges_by_id[
        "relation_edge:graph.alpha_supports_beta"].lifecycle_status == "disputed"
    transition("confirm")
    assert compile_workspace(load(root)).explicit_edges_by_id[
        "relation_edge:graph.alpha_supports_beta"].authoritative is True
    transition("retract")
    assert compile_workspace(load(root)).explicit_edges_by_id[
        "relation_edge:graph.alpha_supports_beta"].authoritative is False
    transition("confirm")
    transition("supersede", replacement="graph.replacement")
    compiled = compile_workspace(load(root))
    edge = compiled.explicit_edges_by_id[
        "relation_edge:graph.alpha_supports_beta"]
    assert edge.lifecycle_status == "superseded"
    assert edge.lifecycle["superseded_by"] == "relation_edge:graph.replacement"
    assert compiled.resolved_by_id["fact:graph.alpha"].status == "active"
    assert compiled.resolved_by_id["fact:graph.beta"].status == "active"


def test_legacy_and_explicit_same_triple_coalesce_but_preserve_origins(
    tmp_path: Path,
) -> None:
    nodes = NODES.replace(
        'fact graph.alpha {\n',
        'fact graph.alpha {\n  relations { supports: graph.beta }\n')
    root = write_workspace(
        tmp_path / "coexist", source=nodes + edge_source())
    compiled = compile_workspace(load(root), paths=[str(root)])
    trace = trace_memory(
        compiled, ["fact:graph.alpha"], max_depth=1, max_bytes=8192)
    assert trace["available_edges"] == 1
    edge = trace["tree_edges"][0]
    assert edge["provenance"] == ["explicit_edge", "legacy_node_relation"]
    assert edge["origin_ids"][0] == "relation_edge:graph.alpha_supports_beta"
    assert len(edge["origin_ids"]) == 2

    event_source = build_edge_transition_source(
        "graph.alpha_supports_beta",
        "retract",
        evidence_source="synthetic_fixture",
        evidence_quote="Fictional retraction.",
        event_id="event.retract.explicit",
        event_at="2026-07-15T00:00:00+00:00",
    )
    (root / "events.edges.mem").write_text(event_source, encoding="utf-8")
    retracted_trace = trace_memory(
        compile_workspace(load(root)),
        ["fact:graph.alpha"],
        max_depth=1,
        max_bytes=8192,
    )
    assert retracted_trace["available_edges"] == 1
    remaining = retracted_trace["tree_edges"][0]
    assert remaining["provenance"] == ["legacy_node_relation"]
    assert len(remaining["origin_ids"]) == 1


@pytest.mark.parametrize(
    "status", ["active", "candidate", "private", "quarantined", "retracted"])
def test_explicit_supersedes_never_weakens_legacy_constraint_authority(
    tmp_path: Path, status: str,
) -> None:
    edge_status = "active" if status == "private" else status
    access = "edge-reader" if status == "private" else ""
    source = NODES + '''\
boundary safety.block_synthetic_publish {
  rule: "Never publish the synthetic ember token."
  force: hard
  scope: global
  status: active
  exceptions: []
  guard { deny_any: ["EMBER-SYNTHETIC"] }
  evidence { source: synthetic_policy quote: "Never publish EMBER-SYNTHETIC." }
}
''' + edge_source(
        name=f"graph.supersedes_{status}",
        relation="supersedes",
        status=edge_status,
        access=access,
    ).replace('target: "fact:graph.beta"',
              'target: "boundary:safety.block_synthetic_publish"')
    root = write_workspace(tmp_path / status, source=source)
    workspace = load(root)
    ids = {item.id for item in current_declarations(workspace)}
    assert "boundary:safety.block_synthetic_publish" in ids
    pack = check_compliance(
        workspace,
        "publish fictional token",
        "Publish EMBER-SYNTHETIC now.",
    )
    assert pack.verdict == "block"


def test_existing_mcp_tools_reuse_edge_contract_and_scopes(tmp_path: Path) -> None:
    root = write_workspace(tmp_path / "mcp", source=NODES + edge_source())
    service = MemdslMCPService([str(root)])
    listed = service.list_declarations(kind="relation_edge")
    explained = service.explain("relation_edge:graph.alpha_supports_beta")
    traced = service.trace(["fact:graph.alpha"], max_depth=1)
    assert service.status()["schema_version"].endswith("experimental.v1")
    assert service.list_types()["schema_version"].endswith("experimental.v1")
    assert service.lint_workspace()["schema_version"].endswith("experimental.v1")
    assert listed["schema_version"].endswith("experimental.v1")
    assert explained["edge"]["record_id"] == (
        "relation_edge:graph.alpha_supports_beta")
    assert traced["schema_version"].endswith("experimental.v1")

    summary_only = MemdslMCPService([str(root)], scopes="read:summary")
    assert summary_only.list_declarations(kind="relation_edge")["ok"] is True
    with pytest.raises(PermissionError):
        summary_only.explain("relation_edge:graph.alpha_supports_beta")
    with pytest.raises(PermissionError):
        summary_only.propose(edge_source())


def test_cli_edge_workflow_uses_dedicated_target(tmp_path: Path, capsys) -> None:
    root = write_workspace(tmp_path / "cli", source=NODES)
    proposal_file = tmp_path / "edge-proposal.mem"
    proposal_file.write_text(edge_source(), encoding="utf-8")
    assert cli_main([
        "edge", "propose", str(root), "--source-file", str(proposal_file),
    ]) == 0
    output = capsys.readouterr().out
    proposal_id = output.split()[1].rstrip(":")
    assert cli_main(["edge", "confirm", str(root), proposal_id]) == 0
    capsys.readouterr()
    assert (root / "edges.mem").is_file()
    assert cli_main(["edge", "list", str(root), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 1


def test_source_authority_limitation_is_behavioral_and_documented(
    tmp_path: Path,
) -> None:
    root = write_workspace(
        tmp_path / "direct-source", source=NODES + edge_source())
    compiled = compile_workspace(load(root))
    assert len(compiled.authoritative_explicit_edges) == 1
    assert not (root / ".memdsl" / "audit.log").exists()

    repo = Path(__file__).resolve().parents[1]
    spec = (repo / "docs" / "SPEC.md").read_text(encoding="utf-8")
    api = (repo / "docs" / "PUBLIC_API.md").read_text(encoding="utf-8")
    design = (repo / "docs" / "DESIGN_explicit_edges_phase6.md").read_text(
        encoding="utf-8")
    for text in (spec, api, design):
        assert "Source" in text
        assert "review" in text
        assert "non-bypassable" in text
    assert "Source-authority + review-gated workflow contract" in spec
    assert "direct active Source writes can bypass" in spec
    assert "authoritative only as an audit record" in spec
    assert "It is not an input\n  to `CompiledWorkspace`" in spec
    assert "Risk matrix" in design


def test_explicit_edge_scale_indexes_and_trace_budgets_are_bounded(
    tmp_path: Path,
) -> None:
    declarations = [
        'entity Reviewer { canonical_name: "Fictional reviewer" status: active }'
    ]
    for index in range(240):
        declarations.append(f'''\
fact scale.node_{index:04d} {{
  claim: "Synthetic scale node {index}."
  status: active
  evidence {{ source: synthetic_scale quote: "Node {index}." }}
}}
''')
    for index in range(239):
        declarations.append(f'''\
relation_edge scale.edge_{index:04d} {{
  declared_by: "entity:Reviewer"
  source: "fact:scale.node_{index:04d}"
  target: "fact:scale.node_{index + 1:04d}"
  relation: depends_on
  lifecycle {{ status: active }}
  evidence {{ source: synthetic_scale quote: "Edge {index}." }}
}}
''')
    root = write_workspace(
        tmp_path / "scale", source="\n".join(declarations))
    compiled = compile_workspace(load(root), paths=[str(root)])
    assert len(compiled.explicit_edges) == 239
    assert len(compiled.explicit_outgoing) == 239
    payload = trace_memory(
        compiled,
        ["fact:scale.node_0000"],
        max_depth=1000,
        max_nodes=20,
        max_edges=20,
        max_bytes=8192,
    )
    assert payload["returned_nodes"] <= 20
    assert payload["returned_edges"] <= 20
    assert payload["truncated"] is True
    assert len(json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")) <= 8192


def test_real_mcp_stdio_reuses_existing_tools_for_explicit_edges(
    tmp_path: Path,
) -> None:
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    root = write_workspace(tmp_path / "stdio", source=NODES + edge_source())

    def result_payload(result) -> dict:
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        for item in getattr(result, "content", []):
            text = getattr(item, "text", "")
            if text:
                return json.loads(text)
        raise AssertionError("MCP result did not contain JSON")

    async def run() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "memdsl.mcp_server", "--workspace", str(root)],
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 11
                assert all("edge_" not in tool.name for tool in tools.tools)
                listed = result_payload(await session.call_tool(
                    "memory_list", {"kind": "relation_edge"}))
                assert listed["total"] == 1
                explained = result_payload(await session.call_tool(
                    "memory_explain",
                    {"id": "relation_edge:graph.alpha_supports_beta"},
                ))
                assert explained["edge"]["record_id"] == (
                    "relation_edge:graph.alpha_supports_beta")
                traced = result_payload(await session.call_tool(
                    "memory_trace", {"anchors": ["fact:graph.alpha"]}))
                assert traced["available_edges"] == 1
                proposed = result_payload(await session.call_tool(
                    "memory_propose",
                    {"source": edge_source(name="graph.stdio_second")},
                ))
                assert proposed["status"] == "pending_review"
                assert "explicit_edge_human_review_required" in proposed[
                    "reason_codes"]

    asyncio.run(run())
