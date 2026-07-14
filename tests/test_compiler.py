"""Phase 0B characterization for the internal compiled workspace."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from memdsl.compliance import check_compliance
from memdsl.compiler import compile_workspace
from memdsl.mcp_service import MemdslMCPService
from memdsl.model import Declaration, Workspace
from memdsl.parser import parse_text
from memdsl.query import (
    build_evidence_pack,
    build_memory_map,
    explain,
    workspace_vocabulary,
)


INDEX_SOURCE = '''
module synthetic.index

entity Synthetic.Project {
  canonical_name: "Synthetic Lantern Project"
  aliases: [lantern, blue-marker]
  lifecycle { status: active }
}

fact topic.old {
  subject: Synthetic.Project
  scope: synthetic_scope
  claim: "Old synthetic lantern route."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Old route." }
}

fact topic.current {
  subject: Synthetic.Project
  scope: synthetic_scope
  claim: "Current synthetic lantern route."
  lifecycle { status: active }
  relations {
    supersedes: topic.old
    supports: safety.no_ember
  }
  evidence { source: synthetic_log quote: "Current route." }
}

boundary safety.no_ember {
  subject: Synthetic.Project
  scope: global
  force: hard
  rule: "Never publish the synthetic ember token."
  lifecycle { status: active }
  guard { deny_any: [ember-token] }
  evidence { source: synthetic_policy quote: "No ember token." }
}

fact topic.draft {
  subject: Synthetic.Project
  scope: synthetic_scope
  claim: "Draft-only synthetic marker."
  lifecycle { status: candidate }
  evidence { source: synthetic_log quote: "Draft marker." }
}
'''


def memory_workspace(source: str = INDEX_SOURCE, *, file: str = "<synthetic.mem>") -> Workspace:
    workspace = Workspace()
    workspace.add_document(parse_text(source, file=file))
    return workspace


def write_memory(path: Path, source: str = INDEX_SOURCE) -> None:
    path.write_text(source.strip() + "\n", encoding="utf-8")


def test_compiled_workspace_builds_required_indexes_and_resolves_references() -> None:
    compiled = compile_workspace(memory_workspace())

    assert set(compiled.occurrences_by_id) == {
        "entity:Synthetic.Project",
        "fact:topic.old",
        "fact:topic.current",
        "boundary:safety.no_ember",
        "fact:topic.draft",
    }
    assert [item.id for item in compiled.by_module["synthetic.index"]] == [
        "boundary:safety.no_ember",
        "entity:Synthetic.Project",
        "fact:topic.current",
        "fact:topic.draft",
        "fact:topic.old",
    ]
    assert [item.id for item in compiled.by_type["boundary"]] == [
        "boundary:safety.no_ember"]
    assert [item.id for item in compiled.by_runtime_role["constraint"]] == [
        "boundary:safety.no_ember"]
    assert {item.id for item in compiled.by_subject["Synthetic.Project"]} == {
        "fact:topic.old",
        "fact:topic.current",
        "boundary:safety.no_ember",
        "fact:topic.draft",
    }
    assert {item.id for item in compiled.by_scope["synthetic_scope"]} == {
        "fact:topic.old", "fact:topic.current", "fact:topic.draft"}
    assert [item.id for item in compiled.aliases["lantern"]] == [
        "entity:Synthetic.Project"]

    full = compiled.resolve_reference("fact:topic.old")
    bare = compiled.resolve_reference("topic.old")
    wrong_prefix = compiled.resolve_reference("decision:topic.old")
    assert full.status == bare.status == "resolved"
    assert full.target_id == bare.target_id == "fact:topic.old"
    assert wrong_prefix.status == "kind_mismatch"
    assert wrong_prefix.target_id is None


def test_duplicate_occurrences_are_preserved_without_single_value_resolution() -> None:
    workspace = Workspace()
    workspace.add_document(parse_text('''
fact duplicate.item {
  claim: "First synthetic occurrence."
  relations { supports: duplicate.target }
  evidence { source: synthetic_log quote: "First." }
}
''', file="<first.mem>"))
    workspace.add_document(parse_text('''
fact duplicate.item {
  claim: "Second synthetic occurrence."
  relations { supports: duplicate.target }
  evidence { source: synthetic_log quote: "Second." }
}
fact duplicate.target {
  claim: "Synthetic duplicate target."
  evidence { source: synthetic_log quote: "Target." }
}
''', file="<second.mem>"))

    compiled = compile_workspace(workspace)

    assert len(compiled.occurrences_by_id["fact:duplicate.item"]) == 2
    assert "fact:duplicate.item" not in compiled.resolved_by_id
    assert compiled.resolve_reference("fact:duplicate.item").status == "ambiguous"
    assert compiled.resolve_reference("duplicate.item").status == "ambiguous"
    assert len(compiled.outgoing["fact:duplicate.item"]) == 2
    assert len({
        edge.edge_id for edge in compiled.outgoing["fact:duplicate.item"]
    }) == 2
    # Occurrences remain inspectable internally, but Phase 1 no longer serves
    # one arbitrary occurrence as the resolved declaration.
    assert compiled.first_occurrence("fact:duplicate.item").claim_text == (
        "First synthetic occurrence.")
    assert "ambiguous" in explain(compiled, "fact:duplicate.item")


def test_resolved_incoming_and_outgoing_edges_are_consistent() -> None:
    compiled = compile_workspace(memory_workspace())

    all_outgoing = [
        edge for edges in compiled.outgoing.values() for edge in edges]
    resolved = [edge for edge in all_outgoing if edge.target_id is not None]
    assert {(edge.relation, edge.target_id) for edge in resolved} == {
        ("supersedes", "fact:topic.old"),
        ("supports", "boundary:safety.no_ember"),
    }
    for edge in resolved:
        assert edge in compiled.incoming[edge.target_id]
    assert sum(len(edges) for edges in compiled.incoming.values()) == len(resolved)


def test_ambiguous_bare_edge_is_unresolved_but_legacy_explain_index_is_preserved() -> None:
    workspace = memory_workspace('''
fact shared {
  claim: "Synthetic shared fact."
  evidence { source: synthetic_log quote: "Fact." }
}
decision shared {
  decision: "Synthetic shared decision."
  evidence { source: synthetic_log quote: "Decision." }
}
fact source.item {
  claim: "Synthetic source."
  relations { supports: shared }
  evidence { source: synthetic_log quote: "Source." }
}
''')
    compiled = compile_workspace(workspace)
    edge = compiled.outgoing["fact:source.item"][0]

    assert edge.status == "ambiguous"
    assert edge.target_id is None
    assert compiled.incoming == {}
    assert [item.source_id for item in compiled.legacy_incoming(
        compiled.first_occurrence("fact:shared"))] == ["fact:source.item"]
    assert [item.source_id for item in compiled.legacy_incoming(
        compiled.first_occurrence("decision:shared"))] == ["fact:source.item"]


def test_workspace_and_compiled_inputs_have_v06_read_parity() -> None:
    workspace = memory_workspace()
    compiled = compile_workspace(workspace)

    assert build_memory_map(workspace) == build_memory_map(compiled)
    assert workspace_vocabulary(workspace) == workspace_vocabulary(compiled)
    assert build_evidence_pack(
        workspace, "lantern route", limit=4).as_dict() == build_evidence_pack(
            compiled, "lantern route", limit=4).as_dict()
    assert check_compliance(
        workspace, "Publish synthetic notes", "Include ember-token."
    ).as_dict() == check_compliance(
        compiled, "Publish synthetic notes", "Include ember-token."
    ).as_dict()
    assert explain(workspace, "boundary:safety.no_ember") == explain(
        compiled, "boundary:safety.no_ember")


def test_service_list_and_explain_match_legacy_workspace_projection(tmp_path: Path) -> None:
    memory_file = tmp_path / "memory.mem"
    write_memory(memory_file)
    workspace = Workspace.load([str(tmp_path)])
    compiled = compile_workspace(workspace, paths=[str(tmp_path)])
    service = MemdslMCPService([str(tmp_path)])

    listing = service.list_declarations()
    assert listing["items"] == [
        {
            "id": declaration.id,
            "type": declaration.kind,
            "kind": declaration.kind,
            "runtime_role": declaration.runtime_role,
            "capabilities": sorted(declaration.capabilities),
            "subject": declaration.subject,
            "scope": declaration.scope,
            "status": declaration.status,
            "claim": declaration.claim_text[:200],
            "file": declaration.file,
            "line": declaration.line,
            "has_evidence": bool(declaration.evidence),
        }
        for declaration in compiled.declarations
        if declaration.id != "fact:topic.old"
    ]
    target = compiled.first_occurrence("boundary:safety.no_ember")
    legacy_refs = []
    for other in workspace.declarations:
        if other.id == target.id:
            continue
        for relation, targets in other.relations().items():
            for reference in targets:
                if reference in (target.id, target.name):
                    legacy_refs.append({"id": other.id, "relation": relation})
    assert service.explain(target.id)["declaration"]["referenced_by"] == legacy_refs


def test_explain_incoming_uses_compiled_index_without_rescanning_workspace(
    tmp_path: Path,
) -> None:
    memory_file = tmp_path / "memory.mem"
    write_memory(memory_file)
    service = MemdslMCPService([str(tmp_path)])
    service.compiled_workspace()
    original = Declaration.relations
    calls = []

    def counted(declaration: Declaration):
        calls.append(declaration.id)
        return original(declaration)

    with patch.object(Declaration, "relations", counted):
        payload = service.explain("boundary:safety.no_ember")

    assert payload["status"] == "ok"
    assert calls == ["boundary:safety.no_ember", "boundary:safety.no_ember"]


def test_workspace_load_and_path_fingerprint_ignore_reversed_input_order(
    tmp_path: Path,
) -> None:
    first = tmp_path / "a.mem"
    second = tmp_path / "b.mem"
    write_memory(first, '''
module synthetic.a
fact order.a {
  claim: "Synthetic A."
  evidence { source: synthetic_log quote: "A." }
}
''')
    write_memory(second, '''
module synthetic.b
fact order.b {
  claim: "Synthetic B."
  evidence { source: synthetic_log quote: "B." }
}
''')

    forward = Workspace.load([str(first), str(second)])
    reverse = Workspace.load([str(second), str(first)])
    compiled_forward = compile_workspace(forward, paths=[str(first), str(second)])
    compiled_reverse = compile_workspace(reverse, paths=[str(second), str(first)])

    assert [item.id for item in forward.declarations] == [
        item.id for item in reverse.declarations]
    assert compiled_forward.source_fingerprint == compiled_reverse.source_fingerprint
    assert build_memory_map(compiled_forward) == build_memory_map(compiled_reverse)


def test_pure_in_memory_fingerprint_and_indexes_are_order_independent() -> None:
    first_doc = parse_text('''
fact order.a {
  claim: "Synthetic A."
  relations { related_to: order.b }
  evidence { source: synthetic_log quote: "A." }
}
''', file="<a.mem>")
    second_doc = parse_text('''
fact order.b {
  claim: "Synthetic B."
  evidence { source: synthetic_log quote: "B." }
}
''', file="<b.mem>")
    forward = Workspace()
    forward.add_document(first_doc)
    forward.add_document(second_doc)
    reverse = Workspace()
    reverse.add_document(second_doc)
    reverse.add_document(first_doc)

    compiled_forward = compile_workspace(forward)
    compiled_reverse = compile_workspace(reverse)

    assert compiled_forward.source_fingerprint == compiled_reverse.source_fingerprint
    assert tuple(compiled_forward.occurrences_by_id) == tuple(
        compiled_reverse.occurrences_by_id)
    assert [edge.edge_id for edge in compiled_forward.outgoing["fact:order.a"]] == [
        edge.edge_id for edge in compiled_reverse.outgoing["fact:order.a"]]


def test_compilation_is_independent_of_python_hash_seed() -> None:
    repository = Path(__file__).resolve().parents[1]
    script = f'''
import json
from memdsl.compiler import compile_workspace
from memdsl.model import Workspace
from memdsl.parser import parse_text
workspace = Workspace()
workspace.add_document(parse_text({INDEX_SOURCE!r}, file="<hash-seed.mem>"))
compiled = compile_workspace(workspace)
print(json.dumps({{
    "fingerprint": compiled.source_fingerprint,
    "ids": list(compiled.occurrences_by_id),
    "aliases": {{key: [item.id for item in value] for key, value in compiled.aliases.items()}},
    "edges": [edge.edge_id for values in compiled.outgoing.values() for edge in values],
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
        ).strip())
    assert outputs[0] == outputs[1]


def test_service_reload_detects_mtime_size_and_same_stat_content_changes(
    tmp_path: Path,
) -> None:
    memory_file = tmp_path / "memory.mem"
    initial = '''
fact cache.item {
  claim: "Alpha marker."
  evidence { source: synthetic_log quote: "Alpha marker." }
}
'''.strip() + "\n"
    changed = initial.replace("Alpha", "Bravo")
    assert len(initial.encode("utf-8")) == len(changed.encode("utf-8"))
    memory_file.write_text(initial, encoding="utf-8")
    service = MemdslMCPService([str(tmp_path)])

    first = service.compiled_workspace()
    first_stat = memory_file.stat()

    os.utime(memory_file, ns=(
        first_stat.st_atime_ns,
        first_stat.st_mtime_ns + 2_000_000_000,
    ))
    mtime_reload = service.compiled_workspace()
    assert mtime_reload is not first
    assert mtime_reload.source_fingerprint == first.source_fingerprint

    stable_stat = memory_file.stat()
    memory_file.write_text(changed, encoding="utf-8")
    os.utime(memory_file, ns=(stable_stat.st_atime_ns, stable_stat.st_mtime_ns))
    content_reload = service.compiled_workspace()
    assert content_reload is not mtime_reload
    assert content_reload.source_fingerprint != mtime_reload.source_fingerprint
    assert content_reload.first_occurrence("fact:cache.item").claim_text == (
        "Bravo marker.")

    memory_file.write_text(changed + "\n", encoding="utf-8")
    size_reload = service.compiled_workspace()
    assert size_reload is not content_reload
    assert size_reload.source_fingerprint != content_reload.source_fingerprint


def test_service_reload_detects_file_add_delete_and_rename(tmp_path: Path) -> None:
    primary = tmp_path / "primary.mem"
    extra = tmp_path / "extra.mem"
    renamed = tmp_path / "renamed.mem"
    write_memory(primary, '''
fact cache.primary {
  claim: "Synthetic primary."
  evidence { source: synthetic_log quote: "Primary." }
}
''')
    service = MemdslMCPService([str(tmp_path)])

    first = service.compiled_workspace()
    write_memory(extra, '''
fact cache.extra {
  claim: "Synthetic extra."
  evidence { source: synthetic_log quote: "Extra." }
}
''')
    added = service.compiled_workspace()
    assert added is not first
    assert set(added.occurrences_by_id) == {
        "fact:cache.primary", "fact:cache.extra"}

    extra.rename(renamed)
    moved = service.compiled_workspace()
    assert moved is not added
    assert moved.source_fingerprint != added.source_fingerprint
    assert set(moved.occurrences_by_id) == set(added.occurrences_by_id)

    renamed.unlink()
    deleted = service.compiled_workspace()
    assert deleted is not moved
    assert set(deleted.occurrences_by_id) == {"fact:cache.primary"}


def test_service_reload_detects_schema_and_manifest_changes(tmp_path: Path) -> None:
    schema_one = tmp_path / "one.json"
    schema_two = tmp_path / "two.json"
    manifest = tmp_path / "memdsl.json"
    memory = tmp_path / "memory.mem"

    def schema(role: str) -> dict:
        return {
            "name": "synthetic",
            "version": "1",
            "types": {
                "note": {
                    "runtime_role": role,
                    "required_fields": ["evidence"],
                    "capabilities": ["searchable"],
                }
            },
        }

    schema_one.write_text(json.dumps(schema("assertion")), encoding="utf-8")
    schema_two.write_text(json.dumps(schema("question")), encoding="utf-8")
    manifest.write_text(json.dumps({
        "schema_version": "memdsl.workspace.v1",
        "schemas": ["one.json"],
    }), encoding="utf-8")
    write_memory(memory, '''
synthetic.note schema.item {
  claim: "Synthetic schema item."
  evidence { source: synthetic_log quote: "Schema item." }
}
''')
    service = MemdslMCPService([str(tmp_path)])

    first = service.compiled_workspace()
    assert first.first_occurrence("synthetic.note:schema.item").runtime_role == (
        "assertion")

    schema_one.write_text(json.dumps(schema("guidance")), encoding="utf-8")
    schema_reload = service.compiled_workspace()
    assert schema_reload is not first
    assert schema_reload.first_occurrence(
        "synthetic.note:schema.item").runtime_role == "guidance"

    manifest.write_text(json.dumps({
        "schema_version": "memdsl.workspace.v1",
        "schemas": ["two.json"],
    }), encoding="utf-8")
    manifest_reload = service.compiled_workspace()
    assert manifest_reload is not schema_reload
    assert manifest_reload.first_occurrence(
        "synthetic.note:schema.item").runtime_role == "question"
