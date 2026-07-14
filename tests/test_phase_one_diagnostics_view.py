"""Phase 1 compiler diagnostics and report-only resolved view."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from memdsl.compiler import compile_workspace
from memdsl.linter import lint
from memdsl.mcp_service import MemdslMCPService
from memdsl.model import Workspace
from memdsl.parser import parse_text
from memdsl.query import build_memory_map
from memdsl.review import ReviewStore
from memdsl.view import ViewContext, resolve_view


FIXTURES = Path(__file__).parent / "fixtures" / "phase_minus_one"


def workspace_from_file(name: str) -> Workspace:
    workspace = Workspace()
    workspace.add_document(parse_text(
        (FIXTURES / name).read_text(encoding="utf-8"),
        file=f"<phase-one/{name}>",
    ))
    return workspace


def diagnostic_rows(workspace: Workspace) -> list[tuple]:
    return [
        (
            diagnostic.code,
            diagnostic.severity,
            diagnostic.message,
            diagnostic.file,
            diagnostic.line,
            diagnostic.decl_id,
        )
        for diagnostic in compile_workspace(workspace).diagnostics
    ]


def lint_rows(workspace: Workspace) -> list[tuple]:
    return [
        (
            diagnostic.code,
            diagnostic.severity,
            diagnostic.message,
            diagnostic.file,
            diagnostic.line,
            diagnostic.decl_id,
        )
        for diagnostic in lint(workspace, today=dt.date(2026, 7, 14))
    ]


@pytest.mark.parametrize(
    "fixture",
    [
        "revision_fork.mem",
        "revision_cycle.mem",
        "reference_resolution.mem",
        "duplicate_id.mem",
    ],
)
def test_phase_one_diagnostics_ignore_reversed_declaration_order(
    fixture: str,
) -> None:
    forward = workspace_from_file(fixture)
    reverse = Workspace(
        declarations=list(reversed(forward.declarations)),
        files=list(forward.files),
        registry=forward.registry,
    )

    assert diagnostic_rows(forward) == diagnostic_rows(reverse)
    assert lint_rows(forward) == lint_rows(reverse)


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("revision_fork.mem", {("supersedes_fork", "warning", 2)}),
        ("revision_cycle.mem", {("revision_cycle", "error", 2)}),
        ("reference_resolution.mem", {
            ("ambiguous_relation_target", "error", 1),
            ("relation_target_kind_mismatch", "error", 1),
            ("unknown_relation", "error", 1),
        }),
        ("duplicate_id.mem", {("duplicate_declaration_id", "error", 1)}),
    ],
)
def test_compiler_diagnostic_codes_and_severities_are_stable(
    fixture: str,
    expected: set[tuple],
) -> None:
    diagnostics = compile_workspace(workspace_from_file(fixture)).diagnostics
    actual = {
        (
            code,
            next(item.severity for item in diagnostics if item.code == code),
            sum(1 for item in diagnostics if item.code == code),
        )
        for code in {item.code for item in diagnostics}
    }
    assert actual == expected


def test_dangling_relation_keeps_the_existing_unresolved_symbol_code() -> None:
    workspace = Workspace()
    workspace.add_document(parse_text('''
fact source.item {
  claim: "Synthetic dangling source."
  relations { supports: missing.target }
  evidence { source: synthetic_log quote: "Dangling." }
}
''', file="<phase-one/dangling.mem>"))

    diagnostics = lint(workspace, today=dt.date(2026, 7, 14))

    assert [(item.code, item.decl_id) for item in diagnostics] == [
        ("unresolved_symbol", "fact:source.item")]


def test_mixed_revision_cycle_is_reported_and_cannot_apply_supersede_authority(
) -> None:
    workspace = Workspace()
    workspace.add_document(parse_text('''
fact topic.alpha {
  claim: "Synthetic alpha."
  relations { supersedes: topic.beta }
  evidence { source: synthetic_log quote: "Alpha." }
}
fact topic.beta {
  claim: "Synthetic beta."
  relations { revision_of: topic.alpha }
  evidence { source: synthetic_log quote: "Beta." }
}
''', file="<phase-one/mixed-cycle.mem>"))

    compiled = compile_workspace(workspace)
    ids = {
        item["id"]
        for module in build_memory_map(compiled)["modules"]
        for item in module["items"]
    }

    assert ids == {"fact:topic.alpha", "fact:topic.beta"}
    assert {item.code for item in compiled.diagnostics} == {"revision_cycle"}
    assert compiled.authoritative_supersedes == ()


def test_candidate_revision_edge_cannot_cancel_active_supersede_authority() -> None:
    workspace = Workspace()
    workspace.add_document(parse_text('''
fact topic.active {
  claim: "Synthetic active successor."
  relations { supersedes: topic.candidate }
  evidence { source: synthetic_log quote: "Active." }
}
fact topic.candidate {
  claim: "Synthetic candidate target."
  lifecycle { status: candidate }
  relations { revision_of: topic.active }
  evidence { source: synthetic_log quote: "Candidate." }
}
''', file="<phase-one/candidate-cycle.mem>"))

    compiled = compile_workspace(workspace)
    ids = [
        item["id"]
        for module in build_memory_map(compiled)["modules"]
        for item in module["items"]
    ]

    assert ids == ["fact:topic.active"]
    assert [edge.target_id for edge in compiled.authoritative_supersedes] == [
        "fact:topic.candidate"]
    assert {item.code for item in compiled.diagnostics} == {"revision_cycle"}


def test_report_view_classifies_without_quarantine_or_v1_payload_change() -> None:
    workspace = Workspace()
    workspace.add_document(parse_text('''
fact topic.old {
  claim: "Synthetic old route."
  evidence { source: synthetic_log quote: "Old." }
}
fact topic.current {
  claim: "Synthetic current route."
  relations { supersedes: topic.old }
  evidence { source: synthetic_log quote: "Current." }
}
fact topic.draft {
  claim: "Synthetic draft route."
  lifecycle { status: candidate }
  evidence { source: synthetic_log quote: "Draft." }
}
fact topic.archived {
  claim: "Synthetic archived route."
  lifecycle { status: archived }
  evidence { source: synthetic_log quote: "Archived." }
}
''', file="<phase-one/view.mem>"))
    compiled = compile_workspace(workspace)
    before = build_memory_map(compiled)
    context = ViewContext(
        source_fingerprint=compiled.source_fingerprint,
        as_of=dt.date(2026, 7, 14),
        principal="fictional-reviewer",
        granted_scopes=frozenset({"read:summary"}),
    )

    view = resolve_view(compiled, context)

    assert [item.id for item in view.authoritative] == ["fact:topic.current"]
    assert [item.id for item in view.provisional] == ["fact:topic.draft"]
    assert view.quarantined == ()
    assert [item.id for item in view.excluded] == [
        "fact:topic.old", "fact:topic.archived"]
    assert build_memory_map(compiled) == before
    assert view.metadata()["enforcement_mode"] == "report"
    assert resolve_view(compiled, context).view_id == view.view_id


def test_phase_one_rejects_unfrozen_enforcement_modes() -> None:
    compiled = compile_workspace(workspace_from_file("revision_fork.mem"))
    context = ViewContext(
        source_fingerprint=compiled.source_fingerprint,
        as_of=dt.date(2026, 7, 14),
        enforcement_mode="quarantine",
    )

    with pytest.raises(ValueError, match="only enforcement_mode='report'"):
        resolve_view(compiled, context)


def test_diagnostics_and_view_are_independent_of_document_order() -> None:
    first = parse_text('''
fact topic.alpha {
  claim: "Synthetic alpha."
  relations { supersedes: topic.beta }
  evidence { source: synthetic_log quote: "Alpha." }
}
''', file="<phase-one/a.mem>")
    second = parse_text('''
fact topic.beta {
  claim: "Synthetic beta."
  relations { supersedes: topic.alpha }
  evidence { source: synthetic_log quote: "Beta." }
}
''', file="<phase-one/b.mem>")
    forward = Workspace()
    forward.add_document(first)
    forward.add_document(second)
    reverse = Workspace()
    reverse.add_document(second)
    reverse.add_document(first)

    compiled_forward = compile_workspace(forward)
    compiled_reverse = compile_workspace(reverse)
    context_forward = ViewContext(
        compiled_forward.source_fingerprint, dt.date(2026, 7, 14))
    context_reverse = ViewContext(
        compiled_reverse.source_fingerprint, dt.date(2026, 7, 14))

    assert diagnostic_rows(forward) == diagnostic_rows(reverse)
    assert compiled_forward.source_fingerprint == compiled_reverse.source_fingerprint
    assert resolve_view(compiled_forward, context_forward).view_id == resolve_view(
        compiled_reverse, context_reverse).view_id
    assert build_memory_map(compiled_forward) == build_memory_map(forward)
    assert build_memory_map(compiled_reverse) == build_memory_map(reverse)
    assert {
        item["id"]
        for module in build_memory_map(compiled_forward)["modules"]
        for item in module["items"]
    } == {
        item["id"]
        for module in build_memory_map(compiled_reverse)["modules"]
        for item in module["items"]
    }


def test_diagnostics_and_view_are_independent_of_python_hash_seed() -> None:
    repository = Path(__file__).resolve().parents[1]
    sources = {
        name: (FIXTURES / name).read_text(encoding="utf-8")
        for name in (
            "revision_fork.mem",
            "revision_cycle.mem",
            "reference_resolution.mem",
            "duplicate_id.mem",
        )
    }
    script = f'''
import datetime as dt
import json
from memdsl.compiler import compile_workspace
from memdsl.model import Workspace
from memdsl.parser import parse_text
from memdsl.view import ViewContext, resolve_view
results = {{}}
for name, source in {sources!r}.items():
    workspace = Workspace()
    workspace.add_document(parse_text(source, file=f"<phase-one/{{name}}>"))
    compiled = compile_workspace(workspace)
    context = ViewContext(compiled.source_fingerprint, dt.date(2026, 7, 14))
    results[name] = {{
        "diagnostics": [
            [item.code, item.severity, item.message, item.decl_id]
            for item in compiled.diagnostics
        ],
        "view_id": resolve_view(compiled, context).view_id,
    }}
print(json.dumps(results, sort_keys=True))
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


def test_mcp_status_and_lint_expose_report_only_diagnostic_summaries(
    tmp_path: Path,
) -> None:
    (tmp_path / "memory.mem").write_text(
        (FIXTURES / "reference_resolution.mem").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    service = MemdslMCPService([str(tmp_path)])

    status = service.status()
    lint_payload = service.lint_workspace()

    assert status["view"]["enforcement_mode"] == "report"
    assert status["diagnostic_summary"]["codes"] == {
        "ambiguous_relation_target": 1,
        "relation_target_kind_mismatch": 1,
        "unknown_relation": 1,
    }
    assert lint_payload["diagnostic_summary"]["compiler"] == (
        status["diagnostic_summary"])
    assert lint_payload["status"] == "errors"
    assert service.memory_map()["status"] == "ok"
    assert service.query("synthetic prefix target")["status"] == "ok"


def test_duplicate_identity_never_resolves_to_one_mcp_declaration() -> None:
    workspace = workspace_from_file("duplicate_id.mem")
    service = MemdslMCPService([str(FIXTURES)])
    service.workspace = lambda: workspace  # type: ignore[method-assign]

    full = service.explain("fact:duplicate.item")
    bare = service.explain("duplicate.item")

    assert full["status"] == bare["status"] == "ambiguous"
    assert full["error"] == "duplicate_declaration_id"
    assert bare["error"] == "ambiguous_reference"


def test_report_diagnostics_do_not_close_repair_lane_but_new_cycle_is_rejected(
    tmp_path: Path,
) -> None:
    preexisting_cycle = Workspace()
    preexisting_cycle.add_document(parse_text('''
fact topic.alpha {
  claim: "Synthetic alpha."
  relations { supersedes: topic.beta }
  evidence { source: synthetic_log quote: "Alpha." }
}
fact topic.beta {
  claim: "Synthetic beta."
  relations { supersedes: topic.alpha }
  evidence { source: synthetic_log quote: "Beta." }
}
''', file="<phase-one/preexisting-cycle.mem>"))
    store = ReviewStore(str(tmp_path / ".memdsl"))

    unrelated = store.validate(preexisting_cycle, '''
entity Synthetic.Repair {
  canonical_name: "Synthetic Repair"
  lifecycle { status: active }
}
''')

    dangling = Workspace()
    dangling.add_document(parse_text('''
fact topic.old {
  claim: "Synthetic old."
  relations { revision_of: topic.new }
  evidence { source: synthetic_log quote: "Old." }
}
''', file="<phase-one/dangling-revision.mem>"))
    creates_cycle = store.validate(dangling, '''
fact topic.new {
  claim: "Synthetic new."
  relations { supersedes: topic.old }
  evidence { source: synthetic_log quote: "New." }
}
''')

    assert unrelated.ok is True
    assert creates_cycle.ok is False
    assert {item["code"] for item in creates_cycle.errors} == {
        "revision_cycle"}
