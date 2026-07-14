"""Phase 2 bounded Catalog, pagination, cursor, and budget contracts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from memdsl.compliance import check_compliance
from memdsl.cli import main as cli_main
from memdsl.mcp_service import MemdslMCPService
from memdsl.model import Workspace
from memdsl.navigation import (
    CATALOG_DEFAULT_MAX_BYTES,
    CatalogCursorError,
    build_memory_catalog,
)
from memdsl.parser import parse_text


def _json_bytes(payload: object) -> int:
    return len(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8"))


def _module_source(index: int, *, subject: str = "Synthetic.Subject") -> str:
    return f'''
module synthetic.module_{index:03d}

fact item.{index:03d} {{
  subject: {subject}
  scope: synthetic
  claim: "Synthetic catalog item {index:03d}."
  lifecycle {{ status: active }}
  evidence {{ source: synthetic_log quote: "Catalog {index:03d}." }}
}}
'''


def _workspace(modules: int = 5) -> Workspace:
    workspace = Workspace()
    workspace.add_document(parse_text('''
entity Synthetic.Subject {
  canonical_name: "Synthetic Subject"
  aliases: [synthetic]
  lifecycle { status: active }
}
''', file="<catalog/symbol.mem>"))
    for index in range(modules):
        workspace.add_document(parse_text(
            _module_source(index), file=f"<catalog/{index:03d}.mem>"))
    return workspace


def _catalog_modules(payload: dict) -> list[str]:
    return [item["module"] for item in payload.get("items", [])]


def test_catalog_item_boundary_and_first_middle_last_pages() -> None:
    workspace = _workspace(4)
    first = build_memory_catalog(workspace, limit=2, max_bytes=8192)
    middle = build_memory_catalog(
        workspace, limit=2, max_bytes=8192, cursor=first["next_cursor"])
    last = build_memory_catalog(
        workspace, limit=2, max_bytes=8192, cursor=middle["next_cursor"])

    assert first["schema_version"] == "memdsl.catalog.v1"
    assert first["returned_items"] == middle["returned_items"] == 2
    assert last["returned_items"] == 1
    assert first["truncated"] is middle["truncated"] is True
    assert last["truncated"] is False
    assert last["next_cursor"] is None
    merged = _catalog_modules(first) + _catalog_modules(middle) + _catalog_modules(last)
    assert merged == sorted(merged)
    assert len(merged) == len(set(merged)) == first["available_items"]


def test_catalog_empty_filter_page_is_explicitly_complete() -> None:
    payload = build_memory_catalog(
        _workspace(2), module="synthetic.missing", limit=2, max_bytes=4096)

    assert payload["status"] == "ok"
    assert payload["returned_items"] == 0
    assert payload["available_items"] == 0
    assert payload["items"] == []
    assert payload["truncated"] is False
    assert payload["next_cursor"] is None
    assert payload["completeness"] == "complete"


def test_catalog_exact_byte_boundary_and_budget_truncation() -> None:
    workspace = _workspace(1)
    unbounded = build_memory_catalog(workspace, limit=10, max_bytes=8192)
    exact = _json_bytes(unbounded)

    at_boundary = build_memory_catalog(workspace, limit=10, max_bytes=exact)
    below_boundary = build_memory_catalog(
        workspace, limit=10, max_bytes=exact - 1)

    assert at_boundary == unbounded
    assert _json_bytes(at_boundary) == exact
    assert _json_bytes(below_boundary) <= exact - 1
    assert below_boundary["truncated"] is True
    assert below_boundary["next_cursor"]


def test_catalog_filters_are_index_backed_and_cursor_bound() -> None:
    workspace = Workspace()
    workspace.add_document(parse_text('''
module synthetic.filtered
entity Synthetic.Subject {
  canonical_name: "Synthetic Subject"
  lifecycle { status: active }
}
fact active.item {
  subject: Synthetic.Subject
  claim: "Synthetic active fact."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Active." }
}
decision candidate.item {
  subject: Synthetic.Subject
  decision: "Synthetic candidate decision."
  lifecycle { status: candidate }
  evidence { source: synthetic_log quote: "Candidate." }
}
''', file="<catalog/filtered.mem>"))

    page = build_memory_catalog(
        workspace,
        module="synthetic.filtered",
        types=["decision"],
        subject="Synthetic.Subject",
        statuses=["candidate"],
        limit=1,
        max_bytes=4096,
    )
    assert page["summary"]["declarations_matched"] == 1
    assert page["items"][0]["type_counts"] == {"decision": 1}
    assert page["items"][0]["status_counts"] == {"candidate": 1}

    cursor_workspace = _workspace(2)
    first = build_memory_catalog(cursor_workspace, limit=1, max_bytes=4096)
    assert first["next_cursor"]
    with pytest.raises(CatalogCursorError, match="cursor_mismatch"):
        build_memory_catalog(
            cursor_workspace, subject="Synthetic.Subject",
            limit=1, max_bytes=4096, cursor=first["next_cursor"])
    with pytest.raises(CatalogCursorError, match="cursor_mismatch"):
        build_memory_catalog(
            cursor_workspace, order="desc",
            limit=1, max_bytes=4096, cursor=first["next_cursor"])
    with pytest.raises(CatalogCursorError, match="cursor_mismatch"):
        build_memory_catalog(
            cursor_workspace, representation="text",
            limit=1, max_bytes=4096, cursor=first["next_cursor"])


def test_catalog_cursor_is_stale_after_source_change() -> None:
    workspace = _workspace(3)
    first = build_memory_catalog(workspace, limit=1, max_bytes=4096)
    workspace.add_document(parse_text(
        _module_source(999), file="<catalog/changed.mem>"))

    with pytest.raises(CatalogCursorError, match="cursor_stale") as raised:
        build_memory_catalog(
            workspace, limit=1, max_bytes=4096,
            cursor=first["next_cursor"])
    assert raised.value.code == "cursor_stale"


def test_mcp_catalog_returns_cursor_stale_after_live_source_change(
    tmp_path: Path,
) -> None:
    for index in range(3):
        (tmp_path / f"{index:03d}.mem").write_text(
            _module_source(index), encoding="utf-8")
    service = MemdslMCPService([str(tmp_path)])
    first = service.catalog(limit=1, max_bytes=4096)
    assert first["next_cursor"]

    (tmp_path / "999.mem").write_text(
        _module_source(999), encoding="utf-8")
    stale = service.catalog(
        limit=1, max_bytes=4096, cursor=first["next_cursor"])

    assert stale["ok"] is False
    assert stale["status"] == "cursor_stale"


def test_cli_catalog_has_a_new_schema_and_text_representation(
    tmp_path: Path,
    capsys,
) -> None:
    for index in range(3):
        (tmp_path / f"{index:03d}.mem").write_text(
            _module_source(index), encoding="utf-8")

    assert cli_main([
        "catalog", str(tmp_path), "--json", "--limit", "1",
        "--max-bytes", "4096",
    ]) == 0
    structured = json.loads(capsys.readouterr().out)
    assert structured["schema_version"] == "memdsl.catalog.v1"
    assert structured["returned_items"] == 1

    assert cli_main([
        "catalog", str(tmp_path), "--representation", "text",
        "--limit", "1", "--max-bytes", "4096",
    ]) == 0
    assert "# memory catalog" in capsys.readouterr().out


def test_catalog_cursor_survives_reversed_source_order_without_gaps() -> None:
    forward = _workspace(6)
    reverse = Workspace(
        declarations=list(reversed(forward.declarations)),
        files=list(reversed(forward.files)),
        registry=forward.registry,
    )
    first = build_memory_catalog(forward, limit=2, max_bytes=4096)
    second_forward = build_memory_catalog(
        forward, limit=2, max_bytes=4096, cursor=first["next_cursor"])
    second_reverse = build_memory_catalog(
        reverse, limit=2, max_bytes=4096, cursor=first["next_cursor"])

    assert second_reverse == second_forward


def test_catalog_is_independent_of_python_hash_seed() -> None:
    repository = Path(__file__).resolve().parents[1]
    script = '''
import json
from memdsl.model import Workspace
from memdsl.navigation import build_memory_catalog
from memdsl.parser import parse_text
workspace = Workspace()
for index in range(8):
    workspace.add_document(parse_text(f"""
module synthetic.module_{index:03d}
fact item.{index:03d} {{
  claim: \"Synthetic item {index:03d}.\"
  lifecycle {{ status: active }}
  evidence {{ source: synthetic_log quote: \"Item.\" }}
}}
""", file=f"<hash/{index:03d}.mem>"))
print(json.dumps(build_memory_catalog(workspace, limit=3, max_bytes=4096), sort_keys=True))
'''
    outputs = []
    for seed in ("1", "777"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(repository / "src")
        outputs.append(subprocess.check_output(
            [sys.executable, "-c", script], cwd=repository, env=env, text=True))
    assert outputs[0] == outputs[1]


def test_catalog_representation_does_not_duplicate_rendered_data() -> None:
    workspace = _workspace(3)
    structured = build_memory_catalog(
        workspace, representation="structured", limit=2, max_bytes=4096)
    text = build_memory_catalog(
        workspace, representation="text", limit=2, max_bytes=4096)

    assert "items" in structured and "rendered_text" not in structured
    assert "rendered_text" in text and "items" not in text
    assert structured["returned_items"] == text["returned_items"]
    assert _json_bytes(structured) <= 4096
    assert _json_bytes(text) <= 4096


def test_catalog_bounds_unlimited_modules_and_oversized_alias_lifecycle_fields() -> None:
    workspace = _workspace(120)
    aliases = ", ".join(
        f'"alias-{index:03d}-' + ("x" * 64) + '"'
        for index in range(200)
    )
    workspace.add_document(parse_text(f'''
module synthetic.wide
entity Synthetic.Wide {{
  canonical_name: "Synthetic Wide"
  aliases: [{aliases}]
  lifecycle {{ status: active note: "{'y' * 8192}" }}
}}
''', file="<catalog/wide.mem>"))

    payload = build_memory_catalog(
        workspace, limit=20, max_bytes=CATALOG_DEFAULT_MAX_BYTES)
    encoded = json.dumps(payload, ensure_ascii=False)

    assert payload["available_items"] == 122
    assert payload["returned_items"] <= 20
    assert payload["truncated"] is True
    assert _json_bytes(payload) <= CATALOG_DEFAULT_MAX_BYTES
    assert "alias-199" not in encoded
    assert "y" * 512 not in encoded


@pytest.mark.parametrize("declarations", [100, 1000, 10000])
def test_default_catalog_stays_bounded_at_synthetic_scale(declarations: int) -> None:
    source = ["module synthetic.scale"]
    for index in range(declarations):
        source.append(f'''
fact item.{index:05d} {{
  claim: "Synthetic scale item {index:05d}."
  scope: synthetic
  lifecycle {{ status: active }}
  evidence {{ source: synthetic_generator quote: "Item {index:05d}." }}
}}
''')
    workspace = Workspace()
    workspace.add_document(parse_text(
        "\n".join(source), file=f"<catalog/scale-{declarations}.mem>"))

    payload = build_memory_catalog(workspace)

    assert payload["summary"]["declarations_matched"] == declarations
    assert payload["available_items"] == 1
    assert _json_bytes(payload) <= CATALOG_DEFAULT_MAX_BYTES


def test_catalog_budget_never_limits_hard_rule_compliance() -> None:
    workspace = Workspace()
    workspace.add_document(parse_text('''
module synthetic.rules
boundary safety.no_ember {
  rule: "Never include ember-token."
  scope: global
  force: hard
  exceptions: []
  lifecycle { status: active }
  guard { deny_any: [ember-token] }
  evidence { source: synthetic_policy quote: "No ember token." }
}
fact context.item {
  claim: "Synthetic context item."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Context." }
}
''', file="<catalog/completeness.mem>"))

    catalog = build_memory_catalog(
        workspace, limit=1, max_bytes=2048, representation="text")
    compliance = check_compliance(
        workspace, "publish synthetic note", "include ember-token")

    assert _json_bytes(catalog) <= 2048
    assert compliance.verdict == "block"
    assert [item.id for item in compliance.applicable_must] == [
        "boundary:safety.no_ember"]
