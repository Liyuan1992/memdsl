"""Phase 4 exact-use visibility and workspace-owned Dialect contracts."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from memdsl.cli import main as cli_main
from memdsl.compiler import compile_workspace
from memdsl.graph import trace_memory
from memdsl.linter import lint
from memdsl.mcp_service import MemdslMCPService
from memdsl.model import Workspace
from memdsl.navigation import build_memory_catalog
from memdsl.parser import parse_text
from memdsl.query import build_evidence_pack
from memdsl.schema import TypeDescriptor, TypeRegistry


ROOT = Path(__file__).resolve().parents[1]
DIALECT_SCHEMA = ROOT / "examples" / "dialect" / "workspace-dialect.memschema.json"


def _workspace(
    documents: list[tuple[str, str]],
    *,
    visibility: str = "legacy",
    dialect: bool = False,
) -> Workspace:
    registry = TypeRegistry.standard()
    if dialect:
        registry.load_schema(str(DIALECT_SCHEMA))
    workspace = Workspace(
        registry=registry,
        schema_version=(
            "memdsl.workspace.v1"
            if visibility == "legacy" else "memdsl.workspace.v2"
        ),
        linking_visibility=visibility,
    )
    for file, source in documents:
        workspace.add_document(parse_text(source, file=file))
    return workspace


def _codes(workspace: Workspace) -> list[tuple[str, str]]:
    return [(item.code, item.severity) for item in lint(workspace)]


SYMBOL_SOURCE = '''
module synthetic.symbols

entity Synthetic.Project {
  canonical_name: "Synthetic Project"
  aliases: [project]
  lifecycle { status: active }
}

fact project.route {
  subject: Synthetic.Project
  claim: "The synthetic project route is staged."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Staged route." }
}
'''


def test_parser_workspace_and_compiler_preserve_document_uses() -> None:
    source = '''
use Synthetic.Project
module synthetic.consumer
use synthetic.symbols
fact consumer.note {
  subject: Synthetic.Project
  claim: "Synthetic consumer note."
  evidence { source: synthetic_log quote: "Consumer." }
}
'''
    document = parse_text(source, file="<phase-four/consumer.mem>")
    workspace = _workspace([
        ("<phase-four/symbols.mem>", SYMBOL_SOURCE),
        ("<phase-four/consumer.mem>", source),
    ], visibility="report")
    compiled = compile_workspace(workspace)

    assert document.uses == ["Synthetic.Project", "synthetic.symbols"]
    assert [item.value for item in document.use_statements] == document.uses
    declaration = next(
        item for item in workspace.declarations
        if item.id == "fact:consumer.note")
    assert declaration.uses == ("Synthetic.Project", "synthetic.symbols")
    resolutions = compiled.uses_by_file["<phase-four/consumer.mem>"]
    assert [(item.target, item.status, item.target_kind) for item in resolutions] == [
        ("Synthetic.Project", "resolved", "symbol"),
        ("synthetic.symbols", "resolved", "module"),
    ]


def test_two_pass_linking_is_order_independent_for_module_and_symbol_imports() -> None:
    consumer = '''
module synthetic.consumer
use synthetic.symbols
use Synthetic.Project
fact consumer.note {
  subject: Synthetic.Project
  claim: "Synthetic consumer note."
  relations { supports: project.route }
  evidence { source: synthetic_log quote: "Consumer." }
}
'''

    def signature(order: list[tuple[str, str]]) -> dict:
        compiled = compile_workspace(_workspace(order, visibility="strict"))
        edge = compiled.outgoing["fact:consumer.note"][0]
        declaration = next(
            item for item in compiled.declarations
            if item.id == "fact:consumer.note")
        return {
            "diagnostics": [
                (item.code, item.severity, item.message)
                for item in compiled.diagnostics
            ],
            "edge": (edge.status, edge.target_id, edge.visibility),
            "subject_routable": compiled.subject_is_routable(declaration),
            "uses": [
                (item.target, item.status, item.target_kind)
                for item in compiled.uses_by_file["<phase-four/consumer.mem>"]
            ],
        }

    forward = [
        ("<phase-four/symbols.mem>", SYMBOL_SOURCE),
        ("<phase-four/consumer.mem>", consumer),
    ]
    assert signature(forward) == signature(list(reversed(forward)))
    assert signature(forward)["edge"] == (
        "resolved", "fact:project.route", "visible")
    assert signature(forward)["subject_routable"] is True


def test_use_namespace_collision_missing_and_wildcard_fail_loud() -> None:
    collision_module = '''
module Shared.Target
fact module.item {
  claim: "Synthetic module item."
  evidence { source: synthetic_log quote: "Module." }
}
'''
    collision_symbol = '''
module synthetic.symbols
entity Shared.Target { lifecycle { status: active } }
'''
    consumer = '''
module synthetic.consumer
use Shared.Target
use Missing.Target
use synthetic.*
fact consumer.note {
  claim: "Synthetic consumer note."
  evidence { source: synthetic_log quote: "Consumer." }
}
'''
    report = _workspace([
        ("<phase-four/module.mem>", collision_module),
        ("<phase-four/symbol.mem>", collision_symbol),
        ("<phase-four/consumer.mem>", consumer),
    ], visibility="report")
    strict = _workspace([
        ("<phase-four/module.mem>", collision_module),
        ("<phase-four/symbol.mem>", collision_symbol),
        ("<phase-four/consumer.mem>", consumer),
    ], visibility="strict")

    assert _codes(report) == [
        ("ambiguous_use_target", "warning"),
        ("unresolved_use_target", "warning"),
        ("unsupported_use_wildcard", "warning"),
    ]
    assert _codes(strict) == [
        ("ambiguous_use_target", "error"),
        ("unresolved_use_target", "error"),
        ("unsupported_use_wildcard", "error"),
    ]


def test_legacy_report_and_strict_visibility_do_not_change_v1_in_place() -> None:
    target = '''
module synthetic.target
fact target.item {
  claim: "Synthetic cross module beacon."
  evidence { source: synthetic_log quote: "Target." }
}
'''
    consumer = '''
module synthetic.consumer
fact consumer.item {
  claim: "Synthetic consumer beacon."
  relations { supports: target.item }
  evidence { source: synthetic_log quote: "Consumer." }
}
'''
    docs = [
        ("<phase-four/target.mem>", target),
        ("<phase-four/consumer.mem>", consumer),
    ]
    legacy = _workspace(docs, visibility="legacy")
    report = _workspace(docs, visibility="report")
    strict = _workspace(docs, visibility="strict")

    legacy_compiled = compile_workspace(legacy)
    report_compiled = compile_workspace(report)
    strict_compiled = compile_workspace(strict)
    assert legacy_compiled.outgoing["fact:consumer.item"][0].target_id == (
        "fact:target.item")
    assert report_compiled.outgoing["fact:consumer.item"][0].target_id == (
        "fact:target.item")
    assert report_compiled.outgoing["fact:consumer.item"][0].visibility == (
        "violation")
    assert strict_compiled.outgoing["fact:consumer.item"][0].target_id is None
    assert strict_compiled.outgoing["fact:consumer.item"][0].status == (
        "visibility_violation")
    assert "visibility_violation" not in {item.code for item in legacy_compiled.diagnostics}
    assert ("visibility_violation", "warning") in _codes(report)
    assert ("visibility_violation", "error") in _codes(strict)

    legacy_query = build_evidence_pack(legacy, "synthetic target beacon")
    report_query = build_evidence_pack(report, "synthetic target beacon")
    assert [item.declaration.id for item in legacy_query.context] == [
        item.declaration.id for item in report_query.context
    ]
    assert [item["module"] for item in build_memory_catalog(legacy)["items"]] == [
        item["module"] for item in build_memory_catalog(report)["items"]
    ]
    assert {
        item["id"] for item in trace_memory(
            legacy, ["fact:consumer.item"], max_depth=1)["nodes"]
    } == {
        item["id"] for item in trace_memory(
            report, ["fact:consumer.item"], max_depth=1)["nodes"]
    }
    assert [item["id"] for item in trace_memory(
        strict, ["fact:consumer.item"], max_depth=1)["nodes"]] == [
        "fact:consumer.item"]


def test_use_does_not_parse_or_rewrite_scope() -> None:
    workspace = _workspace([
        ("<phase-four/scope.mem>", '''
module synthetic.scope
fact scope.item {
  scope: project("Not.A.Module")
  claim: "Synthetic opaque scope."
  evidence { source: synthetic_log quote: "Scope." }
}
'''),
    ], visibility="strict")
    assert "visibility_violation" not in {item.code for item in lint(workspace)}


def test_workspace_v2_manifest_and_multiple_module_migration(tmp_path: Path) -> None:
    source = '''
module synthetic.first
fact first.item {
  claim: "Synthetic first item."
  evidence { source: synthetic_log quote: "First." }
}
module synthetic.second
fact second.item {
  claim: "Synthetic second item."
  evidence { source: synthetic_log quote: "Second." }
}
'''
    document = parse_text(source, file="<phase-four/multiple.mem>")
    legacy = Workspace()
    legacy.add_document(document)
    assert document.module == "synthetic.second"
    assert "multiple_module_statements" not in {
        item.code for item in lint(legacy)}

    for visibility, severity in (("report", "warning"), ("strict", "error")):
        workspace = _workspace([
            ("<phase-four/multiple.mem>", source),
        ], visibility=visibility)
        diagnostic = next(
            item for item in lint(workspace)
            if item.code == "multiple_module_statements")
        assert diagnostic.severity == severity
        assert "split the file or keep one module" in diagnostic.message

    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v2",
        "schemas": [],
        "linking": {"visibility": "strict"},
    }), encoding="utf-8")
    (tmp_path / "memory.mem").write_text(source, encoding="utf-8")
    loaded = Workspace.load([str(tmp_path)])
    assert loaded.schema_version == "memdsl.workspace.v2"
    assert loaded.linking_visibility == "strict"
    service = MemdslMCPService([str(tmp_path)])
    assert service.status()["workspace_schema_version"] == "memdsl.workspace.v2"
    assert service.status()["linking_visibility"] == "strict"


def test_v1_manifest_rejects_in_place_linking_semantics(tmp_path: Path) -> None:
    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v1",
        "schemas": [],
        "linking": {"visibility": "strict"},
    }), encoding="utf-8")
    (tmp_path / "memory.mem").write_text(
        'fact item { claim: "Synthetic." lifecycle { status: candidate } }',
        encoding="utf-8",
    )
    payload = MemdslMCPService([str(tmp_path)]).status()
    assert payload["status"] == "schema_error"
    assert "cannot declare 'linking'" in payload["error"]


def _dialect_documents(
    mapping_status: str = "active",
    *,
    access: str = "",
    use_target: bool = True,
    phrase: str = "little workshop",
    target: str = "Synthetic.Aurora",
    polarity: str = "positive",
) -> list[tuple[str, str]]:
    symbols = '''
module synthetic.projects
entity Synthetic.Aurora {
  canonical_name: "Aurora"
  aliases: [aurora]
  lifecycle { status: active }
}
fact aurora.route {
  subject: Synthetic.Aurora
  claim: "The synthetic aurora route is staged."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Aurora route." }
}
'''
    use = "use Synthetic.Aurora" if use_target else ""
    mapping = f'''
module synthetic.dialect
{use}
workspace_dialect.mapping aurora.mapping {{
  target: {target}
  phrases: ["{phrase}"]
  polarity: {polarity}
  {access}
  lifecycle {{ status: {mapping_status} }}
  evidence {{ source: synthetic_review quote: "Dialect mapping." }}
}}
'''
    return [
        ("<phase-four/projects.mem>", symbols),
        ("<phase-four/dialect.mem>", mapping),
    ]


def test_active_candidate_private_and_strict_dialect_routing() -> None:
    active = _workspace(
        _dialect_documents(), visibility="report", dialect=True)
    candidate = _workspace(
        _dialect_documents("candidate"), visibility="report", dialect=True)
    private = _workspace(
        _dialect_documents(access="access_policy { readers: [owner] }"),
        visibility="report",
        dialect=True,
    )
    strict_missing_use = _workspace(
        _dialect_documents(use_target=False),
        visibility="strict",
        dialect=True,
    )

    assert [item.declaration.id for item in build_evidence_pack(
        active, "little workshop voyage").context] == ["fact:aurora.route"]
    assert build_evidence_pack(
        candidate, "little workshop voyage").context == []
    assert build_evidence_pack(private, "little workshop voyage").context == []
    assert build_evidence_pack(
        strict_missing_use, "little workshop voyage").context == []
    assert ("visibility_violation", "error") in _codes(strict_missing_use)


def test_ambiguous_and_negative_dialect_mappings_never_redirect() -> None:
    symbols = '''
module synthetic.projects
entity Synthetic.Left { lifecycle { status: active } }
entity Synthetic.Right { lifecycle { status: active } }
fact left.route {
  subject: Synthetic.Left
  claim: "Synthetic left route."
  evidence { source: synthetic_log quote: "Left." }
}
fact right.route {
  subject: Synthetic.Right
  claim: "Synthetic right route."
  evidence { source: synthetic_log quote: "Right." }
}
'''
    mappings = '''
module synthetic.dialect
use Synthetic.Left
use Synthetic.Right
workspace_dialect.mapping route.left {
  target: Synthetic.Left
  phrases: [sharedphrase]
  evidence { source: synthetic_review quote: "Left mapping." }
}
workspace_dialect.mapping route.right {
  target: Synthetic.Right
  phrases: [sharedphrase]
  evidence { source: synthetic_review quote: "Right mapping." }
}
workspace_dialect.mapping route.negative {
  target: Synthetic.Left
  phrases: [blockedphrase]
  polarity: negative
  evidence { source: synthetic_review quote: "Negative mapping." }
}
'''
    workspace = _workspace([
        ("<phase-four/projects.mem>", symbols),
        ("<phase-four/dialect.mem>", mappings),
    ], visibility="report", dialect=True)
    codes = _codes(workspace)

    assert codes.count(("ambiguous_dialect_mapping", "warning")) == 2
    assert ("unsupported_dialect_polarity", "error") in codes
    assert build_evidence_pack(workspace, "sharedphrase").context == []
    assert build_evidence_pack(workspace, "blockedphrase").context == []


def test_dialect_capability_requires_evidence_even_if_schema_omits_it() -> None:
    registry = TypeRegistry.standard()
    registry.register(TypeDescriptor(
        name="generic.mapping",
        runtime_role="assertion",
        required_fields=("target", "phrases"),
        optional_fields=("polarity",),
        capabilities=frozenset({"dialect_mapping"}),
        defaults={"polarity": "positive"},
        allow_extra_fields=False,
        schema_name="generic",
        schema_version="1",
        source="<phase-four-schema>",
    ))
    workspace = Workspace(
        registry=registry,
        schema_version="memdsl.workspace.v2",
        linking_visibility="report",
    )
    workspace.add_document(parse_text('''
module synthetic.projects
entity Synthetic.Target { lifecycle { status: active } }
''', file="<phase-four/target.mem>"))
    workspace.add_document(parse_text('''
module synthetic.dialect
use Synthetic.Target
generic.mapping target.no_evidence {
  target: Synthetic.Target
  phrases: [targetphrase]
  lifecycle { status: active }
}
''', file="<phase-four/no-evidence.mem>"))

    assert ("invalid_dialect_mapping", "error") in _codes(workspace)
    assert build_evidence_pack(workspace, "targetphrase").context == []


def test_no_match_dialect_candidate_stays_pending_until_review_approval(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "workspace-dialect.memschema.json").write_text(
        DIALECT_SCHEMA.read_text(encoding="utf-8"), encoding="utf-8")
    (workspace / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v2",
        "schemas": ["workspace-dialect.memschema.json"],
        "linking": {"visibility": "report"},
    }), encoding="utf-8")
    (workspace / "projects.mem").write_text('''
module synthetic.projects
entity Synthetic.Aurora {
  canonical_name: "Aurora"
  aliases: [aurora]
  lifecycle { status: active }
}
fact aurora.route {
  subject: Synthetic.Aurora
  claim: "The synthetic aurora route is staged."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Aurora route." }
}
''', encoding="utf-8")
    dialect_file = workspace / "dialect.mem"
    dialect_file.write_text('''
module synthetic.dialect
use Synthetic.Aurora
''', encoding="utf-8")
    service = MemdslMCPService([str(workspace)])

    miss = service.query("aroura voyage")
    candidate = miss["evidence_pack"]["search_trace"]["dialect_candidate"]
    assert miss["status"] == "no_match"
    assert candidate["mapping_type"] == "workspace_dialect.mapping"
    assert candidate["target"] == "Synthetic.Aurora"
    assert candidate["requires_review"] is True

    proposal = service.propose('''
workspace_dialect.mapping aurora.aroura {
  target: Synthetic.Aurora
  phrases: [aroura]
  polarity: positive
  lifecycle { status: active }
  evidence {
    source: synthetic_review
    quote: "A fictional reviewer confirmed the aroura spelling."
  }
}
''', reason="synthetic dialect correction")
    assert proposal["status"] == "pending_review"
    assert service.query("aroura voyage")["status"] == "no_match"

    approved = service.review_store.approve(
        proposal["proposal_id"],
        Workspace.load([str(workspace)]),
        str(dialect_file),
    )
    assert approved["status"] == "approved"
    served = service.query("aroura voyage")
    assert [item["id"] for item in served["evidence_pack"]["context"]] == [
        "fact:aurora.route"]
    assert [
        item["action"] for item in service.review_store.audit_entries()
    ] == ["propose", "route", "approve"]


def test_public_dialect_example_is_generic_and_loadable() -> None:
    workspace = Workspace.load([str(ROOT / "examples" / "dialect")])
    compiled = compile_workspace(
        workspace, paths=[str(ROOT / "examples" / "dialect")])
    pack = build_evidence_pack(compiled, "the little workshop release")

    assert compiled.workspace_schema_version == "memdsl.workspace.v2"
    assert compiled.linking_visibility == "report"
    assert compiled.diagnostics == ()
    assert [item.declaration.id for item in pack.context] == [
        "fact:starboard.release_route"]


def test_phase_four_linking_is_hash_seed_deterministic() -> None:
    repository = ROOT
    script = f'''
import json
from memdsl.compiler import compile_workspace
from memdsl.model import Workspace
from memdsl.parser import parse_text
from memdsl.schema import TypeRegistry
registry = TypeRegistry.standard()
registry.load_schema({str(DIALECT_SCHEMA)!r})
workspace = Workspace(
    registry=registry,
    schema_version="memdsl.workspace.v2",
    linking_visibility="strict",
)
workspace.add_document(parse_text({SYMBOL_SOURCE!r}, file="<hash/symbols.mem>"))
workspace.add_document(parse_text("""
module synthetic.consumer
use Synthetic.Project
use synthetic.symbols
workspace_dialect.mapping project.mapping {{
  target: Synthetic.Project
  phrases: [projectspace]
  evidence {{ source: synthetic_review quote: "Mapping." }}
}}
fact consumer.item {{
  subject: Synthetic.Project
  claim: "Synthetic consumer item."
  relations {{ supports: project.route }}
  evidence {{ source: synthetic_log quote: "Consumer." }}
}}
""", file="<hash/consumer.mem>"))
compiled = compile_workspace(workspace)
print(json.dumps({{
  "diagnostics": [[d.code, d.severity, d.message] for d in compiled.diagnostics],
  "uses": {{k: [[u.target, u.status, u.target_kind] for u in v] for k, v in compiled.uses_by_file.items()}},
  "dialect": dict(compiled.dialect_aliases),
  "edges": [[e.edge_id, e.status, e.target_id, e.visibility] for values in compiled.outgoing.values() for e in values],
}}, sort_keys=True))
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


def test_cli_report_and_strict_modes_keep_exit_boundary(tmp_path: Path, capsys) -> None:
    (tmp_path / "target.mem").write_text('''
module synthetic.target
fact target.item {
  claim: "Synthetic target."
  evidence { source: synthetic_log quote: "Target." }
}
''', encoding="utf-8")
    (tmp_path / "consumer.mem").write_text('''
module synthetic.consumer
fact consumer.item {
  claim: "Synthetic consumer."
  relations { supports: target.item }
  evidence { source: synthetic_log quote: "Consumer." }
}
''', encoding="utf-8")
    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v2",
        "schemas": [],
        "linking": {"visibility": "report"},
    }), encoding="utf-8")
    assert cli_main(["lint", str(tmp_path)]) == 0
    assert "warning[visibility_violation]" in capsys.readouterr().out

    (tmp_path / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v2",
        "schemas": [],
        "linking": {"visibility": "strict"},
    }), encoding="utf-8")
    assert cli_main(["lint", str(tmp_path)]) == 1
    assert "error[visibility_violation]" in capsys.readouterr().out
    capsys.readouterr()

    service = MemdslMCPService([str(tmp_path)])
    assert service.status()["linking_visibility"] == "strict"


def test_real_mcp_stdio_serves_dialect_and_scope_denial(tmp_path: Path) -> None:
    mcp = pytest.importorskip("mcp")
    from mcp.client.stdio import StdioServerParameters, stdio_client

    del mcp
    workspace = tmp_path / "dialect-workspace"
    workspace.mkdir()
    for source in (ROOT / "examples" / "dialect").iterdir():
        if source.is_file():
            (workspace / source.name).write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8")

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

        args = ["-m", "memdsl.mcp_server", "--workspace", str(workspace)]
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
                assert status["workspace_schema_version"] == "memdsl.workspace.v2"
                assert status["linking_visibility"] == "report"
                result = await session.call_tool(
                    "memory_query", {"query": "the little workshop voyage"})
                if scopes:
                    assert result.isError is True
                    return
                query = payload(result)
                assert [
                    item["id"] for item in query["evidence_pack"]["context"]
                ] == ["fact:starboard.release_route"]

    asyncio.run(run())
    asyncio.run(run("read:summary"))
