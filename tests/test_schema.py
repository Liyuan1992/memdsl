import json
import os
import shutil
from pathlib import Path

import pytest

from memdsl.cli import main as cli_main
from memdsl.benchmark import load_cases, run_compliance_benchmark
from memdsl.compliance import check_compliance
from memdsl.linter import lint
from memdsl.mcp_service import MemdslMCPService
from memdsl.model import Workspace
from memdsl.parser import parse_text
from memdsl.query import build_evidence_pack
from memdsl.review import ReviewStore, staging_dir_for
from memdsl.schema import SchemaError, TypeDescriptor, TypeRegistry


ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ROOT / "examples" / "domains"


def test_standard_type_pack_preserves_v04_roles():
    registry = TypeRegistry.standard()
    assert registry.resolve("boundary").runtime_role == "constraint"
    preference = registry.resolve("preference")
    assert preference.role_for({"force": "strong"}) == "guidance"
    assert preference.role_for({"force": "advisory"}) == "assertion"
    assert registry.resolve("open_issue").runtime_role == "question"


def test_programmatic_type_registration_is_supported():
    registry = TypeRegistry.standard()
    registry.register(TypeDescriptor(
        name="research.hypothesis",
        runtime_role="assertion",
        required_fields=("claim", "evidence", "scope"),
        capabilities=frozenset({"requires_evidence", "searchable"}),
        allow_extra_fields=False,
        schema_name="research",
        schema_version="1",
    ))
    ws = Workspace(registry=registry)
    ws.add_document(parse_text('''
research.hypothesis retrieval.latency {
  claim: "Write-time compilation reduces query latency."
  scope: experiment
  evidence { source: test quote: "The compiled path was faster." }
}
''', file="research.mem"))
    assert lint(ws) == []
    assert ws.declarations[0].runtime_role == "assertion"


def test_descriptor_referenced_fields_are_allowed_and_discoverable():
    registry = TypeRegistry.standard()
    descriptor = TypeDescriptor(
        name="research.note",
        runtime_role="assertion",
        required_fields=("summary",),
        claim_fields=("summary",),
        search_fields=("body",),
        defaults={"strength": "normal"},
        role_field="strength",
        role_map={"strong": "guidance"},
        capabilities=frozenset({"searchable"}),
        allow_extra_fields=False,
        schema_name="research",
        schema_version="1",
    )
    registry.register(descriptor)
    ws = Workspace(registry=registry)
    ws.add_document(parse_text('''
research.note retrieval.compiler {
  summary: "Compile memory indexes at write time."
  body: "Avoid repeated query planning work."
  strength: strong
}
''', file="research.mem"))
    assert lint(ws) == []
    declaration = ws.declarations[0]
    assert declaration.claim_text == "Compile memory indexes at write time."
    assert declaration.runtime_role == "guidance"
    assert descriptor.as_dict()["role_map"] == {"strong": "guidance"}


def test_custom_symbol_type_does_not_require_standard_entity():
    registry = TypeRegistry()
    registry.register(TypeDescriptor(
        name="org.actor",
        runtime_role="symbol",
        optional_fields=("canonical_name", "aliases"),
        capabilities=frozenset({"symbol"}),
        allow_extra_fields=False,
    ))
    registry.register(TypeDescriptor(
        name="org.policy",
        runtime_role="constraint",
        required_fields=("claim", "scope"),
        capabilities=frozenset({"searchable"}),
        allow_extra_fields=False,
    ))
    ws = Workspace(registry=registry)
    ws.add_document(parse_text('''
org.actor Team.Release { canonical_name: "Release Team" aliases: [release] }
org.policy approvals.required {
  subject: Team.Release
  claim: "Require approval before publishing."
  scope: release
}
''', file="org.mem"))
    assert lint(ws) == []
    assert ws.resolve_alias("release") == ["Team.Release"]


def test_non_searchable_type_is_not_scored_into_context():
    registry = TypeRegistry.standard()
    registry.register(TypeDescriptor(
        name="private.note",
        runtime_role="assertion",
        required_fields=("claim",),
        allow_extra_fields=False,
    ))
    ws = Workspace(registry=registry)
    ws.add_document(parse_text(
        'private.note hidden { claim: "Secret launch phrase." }',
        file="private.mem"))
    pack = build_evidence_pack(ws, "secret launch phrase")
    assert pack.context == []


@pytest.mark.parametrize("domain", ["coding", "assistant", "writing"])
def test_domain_pack_loads_without_core_customization(domain):
    ws = Workspace.load([str(DOMAINS / domain)])
    names = set(ws.registry.names())
    assert any(name.startswith(domain + ".") for name in names)
    assert ws.registry.schema_files
    assert lint(ws) == []


def test_no_implicit_user_symbol_remains():
    ws = Workspace.load([str(DOMAINS / "coding")])
    assert "User" not in ws.known_symbols()
    broken = Workspace()
    broken.add_document(parse_text('''
fact orphan.subject {
  subject: User
  claim: "This workspace never declared User."
  status: candidate
}
''', file="orphan.mem"))
    assert "unresolved_symbol" in {d.code for d in lint(broken)}


def test_coding_types_compile_to_evidence_pack_roles():
    ws = Workspace.load([str(DOMAINS / "coding")])
    rule = build_evidence_pack(ws, "force push main")
    assert [d.id for d in rule.must] == ["coding.project_rule:git.no_force_push"]

    tool = build_evidence_pack(ws, "which repository search tool")
    assert "coding.tool_preference:search.rg" in [d.id for d in tool.should]

    bug = build_evidence_pack(ws, "duplicate approval audit marker")
    assert "coding.bug_pattern:windows.review_lock" in [
        item.declaration.id for item in bug.context]


def test_assistant_and_writing_types_use_same_runtime():
    assistant = Workspace.load([str(DOMAINS / "assistant")])
    pack = build_evidence_pack(assistant, "Friday weekly review")
    assert "assistant.routine:weekly.review" in [d.id for d in pack.should]

    writing = Workspace.load([str(DOMAINS / "writing")])
    pack = build_evidence_pack(writing, "direct concise blog voice")
    assert "writing.voice_preference:voice.direct" in [d.id for d in pack.should]
    style = build_evidence_pack(writing, "atomic approval release note")
    assert "writing.style_example:release.concise" in [
        item.declaration.id for item in style.context]


def test_custom_constraint_is_enforced_without_boundary_kind():
    coding = Workspace.load([str(DOMAINS / "coding")])
    result = check_compliance(
        coding, "push main", "git push --force origin main")
    assert result.verdict == "block"
    assert result.violations[0]["id"] == "coding.project_rule:git.no_force_push"
    assert result.violations[0]["type"] == "coding.project_rule"

    writing = Workspace.load([str(DOMAINS / "writing")])
    result = check_compliance(
        writing, "publish a customer story", "Customer name: Acme Corp")
    assert result.verdict == "block"
    assert result.violations[0]["id"] == "writing.taboo_topic:privacy.customer_names"


def test_compliance_benchmark_accepts_domain_constraint_types():
    coding = DOMAINS / "coding"
    report = run_compliance_benchmark(
        Workspace.load([str(coding)]),
        load_cases(str(coding / "cases.jsonl")),
    )
    assert report["status"] == "passed"
    assert report["passed"] == 3
    assert report["modes"]["compliance_gate"]["metrics"][
        "constraint_recall"] == 1.0


def test_universal_lifecycle_access_confidence_and_relations_are_exposed():
    ws = Workspace.load([str(DOMAINS / "coding")])
    rule = ws.by_id("coding.project_rule:git.no_force_push")
    assert rule.confidence == "high"
    assert rule.lifecycle["status"] == "active"
    assert rule.access_policy["writers"] == ["maintainer"]
    bug = ws.by_id("coding.bug_pattern:windows.review_lock")
    assert bug.lifecycle["as_of"] == "2026-07-10"


def test_unknown_type_and_strict_unknown_field_are_lint_errors(tmp_path):
    unknown = Workspace()
    unknown.add_document(parse_text(
        'mystery.note x { claim: "Unknown." }', file="unknown.mem"))
    assert "unknown_memory_type" in {d.code for d in lint(unknown)}

    schema = tmp_path / "demo.memschema.json"
    schema.write_text(json.dumps({
        "name": "demo",
        "version": "1",
        "types": {
            "note": {
                "runtime_role": "assertion",
                "required_fields": ["claim"],
                "allow_extra_fields": False,
            }
        },
    }), encoding="utf-8")
    registry = TypeRegistry.standard()
    registry.load_schema(str(schema))
    ws = Workspace(registry=registry)
    ws.add_document(parse_text(
        'demo.note x { claim: "Known." author_worldview: forced }',
        file="strict.mem"))
    assert "unknown_type_field" in {d.code for d in lint(ws)}


def test_manifest_schema_error_is_fail_closed(tmp_path):
    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v1",
        "schemas": ["missing.memschema.json"],
    }), encoding="utf-8")
    (tmp_path / "memory.mem").write_text(
        'fact x { claim: "x" status: candidate }', encoding="utf-8")
    with pytest.raises(SchemaError, match="cannot read schema"):
        Workspace.load([str(tmp_path)])


def test_manifest_version_and_schema_field_types_fail_closed(tmp_path):
    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v9",
        "schemas": [],
    }), encoding="utf-8")
    with pytest.raises(SchemaError, match="schema_version"):
        Workspace.load([str(tmp_path)])

    registry = TypeRegistry.standard()
    cases = [
        ({"required_fields": [1]}, "must contain only strings"),
        ({"allow_extra_fields": "false"}, "must be a boolean"),
        ({"role_map": {"strong": "guidance"}}, "without role_field"),
    ]
    for index, (override, message) in enumerate(cases):
        schema = tmp_path / f"invalid-{index}.memschema.json"
        schema.write_text(json.dumps({
            "name": f"invalid{index}",
            "version": "1",
            "types": {"note": {"runtime_role": "assertion", **override}},
        }), encoding="utf-8")
        with pytest.raises(SchemaError, match=message):
            registry.load_schema(str(schema))


def test_mcp_returns_structured_schema_errors(tmp_path):
    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v9",
        "schemas": [],
    }), encoding="utf-8")
    (tmp_path / "memory.mem").write_text(
        'fact x { claim: "x" status: candidate }', encoding="utf-8")
    service = MemdslMCPService([str(tmp_path)])
    status = service.status()
    assert status["ok"] is False
    assert status["status"] == "schema_error"
    assert "schema_version" in status["error"]
    types = service.list_types()
    assert types["status"] == "schema_error"


def test_review_pipeline_preserves_custom_type_registry(tmp_path):
    workspace = tmp_path / "coding"
    shutil.copytree(DOMAINS / "coding", workspace)
    ws = Workspace.load([str(workspace)])
    store = ReviewStore(staging_dir_for([str(workspace)]))
    source = '''coding.project_rule tests.before_release {
  subject: Repository.Memdsl
  claim: "Run tests before a release."
  scope: repository("memdsl")
  exceptions: []
  evidence { source: release_policy quote: "Tests must pass before release." }
}
'''
    proposal = store.create(ws, source)
    assert proposal["ok"] is True
    target = workspace / "approved.mem"
    approved = store.approve(proposal["proposal_id"], ws, str(target))
    assert approved["ok"] is True
    reloaded = Workspace.load([str(workspace)])
    declaration = reloaded.by_id("coding.project_rule:tests.before_release")
    assert declaration.runtime_role == "constraint"


def test_cli_and_mcp_expose_loaded_types(capsys):
    coding = str(DOMAINS / "coding")
    assert cli_main(["types", coding, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    names = {item["name"] for item in payload["types"]}
    assert "coding.project_rule" in names

    service = MemdslMCPService([coding])
    types = service.list_types()
    assert types["schema_version"] == "memdsl.mcp.types.v1"
    assert any(item["name"] == "coding.project_rule" for item in types["types"])
    project_rule = next(
        item for item in types["types"]
        if item["name"] == "coding.project_rule")
    assert project_rule["defaults"]["force"] == "hard"
    preference = next(
        item for item in types["types"] if item["name"] == "preference")
    assert preference["role_field"] == "force"
    assert preference["role_map"]["strong"] == "guidance"
    status = service.status()
    assert "coding.project_rule" in status["registered_types"]


def test_mcp_reloads_when_schema_changes(tmp_path):
    workspace = tmp_path / "coding"
    shutil.copytree(DOMAINS / "coding", workspace)
    service = MemdslMCPService([str(workspace)])
    assert service.workspace().registry.resolve(
        "coding.tool_preference").runtime_role == "guidance"
    schema_path = workspace / "coding.memschema.json"
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    payload["types"]["tool_preference"]["runtime_role"] = "assertion"
    schema_path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(schema_path, None)
    assert service.workspace().registry.resolve(
        "coding.tool_preference").runtime_role == "assertion"
