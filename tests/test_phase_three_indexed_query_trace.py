"""Phase 3 indexed query, vocabulary suggestion, and bounded Trace contracts."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from memdsl.cli import main as cli_main
from memdsl.compiler import compile_workspace
from memdsl.graph import (
    TRACE_DEFAULT_MAX_BYTES,
    TraceAnchorError,
    TraceCursorError,
    trace_memory,
)
from memdsl.mcp_service import MCPScopeError, MemdslMCPService
from memdsl.model import Workspace
from memdsl.parser import parse_text
from memdsl.query import (
    _build_evidence_pack_legacy,
    _score,
    build_evidence_pack,
)


QUERY_SOURCE = '''
module synthetic.query

entity Synthetic.Aurora {
  canonical_name: "Aurora"
  aliases: ["aurora project", "north light"]
  lifecycle { status: active }
}

fact aurora.confirmed {
  subject: Synthetic.Aurora
  scope: launch
  claim: "The aurora launch route is confirmed."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Aurora route confirmed." }
}

preference aurora.guidance {
  subject: Synthetic.Aurora
  scope: launch
  claim: "Prefer a staged aurora launch."
  force: strong
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Use a staged launch." }
}

fact aurora.draft {
  subject: Synthetic.Aurora
  scope: launch
  claim: "The aurora draft route is provisional."
  lifecycle { status: candidate }
  evidence { source: synthetic_log quote: "Draft route only." }
}

boundary launch.no_ember {
  rule: "Never publish ember-token."
  scope: global
  force: hard
  lifecycle { status: active }
  guard { deny_any: [ember-token] }
  evidence { source: synthetic_policy quote: "No ember token." }
}
'''


TRACE_SOURCE = '''
module synthetic.graph

fact graph.a {
  claim: "Synthetic graph node A."
  relations {
    supports: graph.b
    related_to: graph.draft
    part_of: graph.private
  }
  lifecycle { status: active }
  evidence { source: synthetic_graph quote: "A." }
}

fact graph.b {
  claim: "Synthetic graph node B."
  relations { supports: graph.c }
  lifecycle { status: active }
  evidence { source: synthetic_graph quote: "B." }
}

fact graph.c {
  claim: "Synthetic graph node C."
  relations { supports: graph.a }
  lifecycle { status: active }
  evidence { source: synthetic_graph quote: "C." }
}

fact graph.incoming {
  claim: "Synthetic incoming node."
  relations { supports: graph.b }
  lifecycle { status: active }
  evidence { source: synthetic_graph quote: "Incoming." }
}

fact graph.draft {
  claim: "Synthetic provisional graph node."
  lifecycle { status: candidate }
  evidence { source: synthetic_graph quote: "Draft." }
}

fact graph.private {
  claim: "Synthetic restricted graph node."
  access_policy { readers: [owner] }
  lifecycle { status: active }
  evidence { source: synthetic_graph quote: "Restricted." }
}
'''


def _workspace(source: str, *, file: str = "<phase-three.mem>") -> Workspace:
    workspace = Workspace()
    workspace.add_document(parse_text(source, file=file))
    return workspace


def _query_signature(pack) -> dict:
    payload = pack.as_dict()
    return {
        "resolved_subjects": payload["resolved_subjects"],
        "must": payload["must"],
        "should": payload["should"],
        "context": payload["context"],
        "provisional": payload["provisional"],
        "conflicts": payload["conflicts"],
        "missing": payload["missing"],
        "legacy_trace": {
            key: payload["search_trace"][key]
            for key in (
                "query_terms",
                "matched_aliases",
                "filters",
                "candidates_considered",
                "hits",
                "excluded_by_filters_total",
                "excluded_by_filters",
            )
        },
    }


def _json_bytes(payload: object) -> int:
    return len(json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8"))


def test_compiler_builds_deterministic_lexical_postings() -> None:
    compiled = compile_workspace(_workspace(QUERY_SOURCE))

    assert [item.id for item in compiled.lexical_terms["aurora"]] == [
        "fact:aurora.confirmed",
        "fact:aurora.draft",
        "preference:aurora.guidance",
    ]
    assert [item.id for item in compiled.searchable_declarations] == [
        "boundary:launch.no_ember",
        "fact:aurora.confirmed",
        "fact:aurora.draft",
        "preference:aurora.guidance",
    ]


@pytest.mark.parametrize(
    ("query", "types", "subject", "limit"),
    [
        ("aurora launch", None, None, 8),
        ("north light", None, None, 1),
        ("aurora launch", ["fact"], None, 1),
        ("aurora launch", None, "Synthetic.Aurora", 2),
        ("unrelated vocabulary", None, None, 8),
    ],
)
def test_indexed_query_matches_legacy_evidence_pack_semantics(
    query: str,
    types: list[str] | None,
    subject: str | None,
    limit: int,
) -> None:
    compiled = compile_workspace(_workspace(QUERY_SOURCE))

    indexed = build_evidence_pack(
        compiled, query, types=types, subject=subject, limit=limit)
    legacy = _build_evidence_pack_legacy(
        compiled, query, types=types, subject=subject, limit=limit)

    assert _query_signature(indexed) == _query_signature(legacy)
    assert indexed.trace["indexes_used"][0] == "lexical_terms"
    assert legacy.trace["indexes_used"][0] == "legacy_scan"


def test_indexed_query_scores_only_index_candidates() -> None:
    source = [QUERY_SOURCE]
    for index in range(200):
        source.append(f'''
fact noise.{index:03d} {{
  claim: "Synthetic unrelated filler {index:03d}."
  lifecycle {{ status: active }}
  evidence {{ source: synthetic_log quote: "Noise {index:03d}." }}
}}
''')
    compiled = compile_workspace(_workspace("\n".join(source)))

    with patch("memdsl.query._score", wraps=_score) as scorer:
        pack = build_evidence_pack(compiled, "north light")

    assert scorer.call_count == 3
    assert [item.declaration.id for item in pack.context] == [
        "fact:aurora.confirmed"]


def test_indexed_legacy_tie_order_and_hash_seed_are_deterministic() -> None:
    sources = {
        "zeta": '''
fact tie.zeta {
  claim: "Synthetic equal beacon."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Zeta." }
}
''',
        "alpha": '''
fact tie.alpha {
  claim: "Synthetic equal beacon."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Alpha." }
}
''',
    }

    def queried(order: list[str]):
        workspace = Workspace()
        for name in order:
            workspace.add_document(parse_text(
                sources[name], file=f"<tie/{name}.mem>"))
        compiled = compile_workspace(workspace)
        return (
            _query_signature(build_evidence_pack(
                compiled, "synthetic equal beacon", limit=1)),
            _query_signature(_build_evidence_pack_legacy(
                compiled, "synthetic equal beacon", limit=1)),
        )

    forward = queried(["zeta", "alpha"])
    reverse = queried(["alpha", "zeta"])
    assert forward == reverse
    assert forward[0] == forward[1]
    assert [item["id"] for item in forward[0]["context"]] == [
        "fact:tie.alpha"]

    repository = Path(__file__).resolve().parents[1]
    script = f'''
import json
from memdsl.compiler import compile_workspace
from memdsl.model import Workspace
from memdsl.parser import parse_text
from memdsl.query import build_evidence_pack
workspace = Workspace()
workspace.add_document(parse_text({sources["zeta"]!r}, file="<tie/zeta.mem>"))
workspace.add_document(parse_text({sources["alpha"]!r}, file="<tie/alpha.mem>"))
pack = build_evidence_pack(
    compile_workspace(workspace), "synthetic equal beacon", limit=1)
print(json.dumps(pack.as_dict(), sort_keys=True))
'''
    outputs = []
    for seed in ("1", "777"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(repository / "src")
        outputs.append(subprocess.check_output(
            [sys.executable, "-c", script], cwd=repository, env=env, text=True))
    assert outputs[0] == outputs[1]


def test_search_trace_exposes_view_pool_filters_and_completeness() -> None:
    compiled = compile_workspace(_workspace(QUERY_SOURCE))
    pack = build_evidence_pack(
        compiled, "aurora launch", types=["boundary"], limit=1)
    trace = pack.trace

    assert trace["view_id"]
    assert trace["source_fingerprint"] == compiled.source_fingerprint
    assert trace["indexes_used"] == [
        "lexical_terms", "active_aliases", "type_filter"]
    assert trace["candidate_pool_total"] == 4
    assert trace["candidate_pool_after_filters"] == 1
    assert trace["excluded_by_filters_total"] == 3
    assert trace["quarantined_matches"] == []
    assert trace["truncated"] is False
    assert [item.id for item in pack.must] == ["boundary:launch.no_ember"]


def test_vocabulary_suggestions_recover_no_match_without_redirecting() -> None:
    pack = build_evidence_pack(_workspace(QUERY_SOURCE), "aroura voyage")
    trace = pack.trace

    suggestion = trace["vocabulary_suggestions"][0]
    assert suggestion == {
        "query_term": "aroura",
        "suggestion": "aurora",
        "category": "symbol",
        "reason": "edit_distance",
        "authoritative": True,
        "ambiguous": False,
        "symbols": ["Synthetic.Aurora"],
    }
    assert trace["retry_queries"][0] == "aurora voyage"


def test_suggestions_omit_candidate_and_restricted_vocabulary() -> None:
    workspace = _workspace('''
entity Draft.Secret {
  aliases: ["candorword"]
  lifecycle { status: candidate }
}
entity Private.Secret {
  aliases: ["privateword"]
  access_policy { readers: [owner] }
  lifecycle { status: active }
}
''')

    candidate = build_evidence_pack(workspace, "candorwrod").trace
    private = build_evidence_pack(workspace, "privatewrod").trace

    assert candidate["vocabulary_suggestions"] == []
    assert candidate["retry_queries"] == []
    assert private["vocabulary_suggestions"] == []
    assert private["retry_queries"] == []


def test_ambiguous_suggestion_is_visible_but_not_auto_retried() -> None:
    workspace = _workspace('''
entity Synthetic.Left {
  aliases: ["starpath"]
  lifecycle { status: active }
}
entity Synthetic.Right {
  aliases: ["starpath"]
  lifecycle { status: active }
}
''')

    trace = build_evidence_pack(workspace, "starpth").trace
    suggestion = trace["vocabulary_suggestions"][0]

    assert suggestion["suggestion"] == "starpath"
    assert suggestion["ambiguous"] is True
    assert suggestion["symbols"] == ["Synthetic.Left", "Synthetic.Right"]
    assert trace["retry_queries"] == []


def test_trace_direction_depth_relation_filter_and_provisional_visibility() -> None:
    workspace = _workspace(TRACE_SOURCE)

    outgoing = trace_memory(
        workspace, ["fact:graph.a"], direction="outgoing", max_depth=1)
    incoming = trace_memory(
        workspace, ["fact:graph.b"], direction="incoming", max_depth=1)
    both = trace_memory(
        workspace, ["fact:graph.b"], direction="both", max_depth=1)
    filtered = trace_memory(
        workspace,
        ["fact:graph.a"],
        direction="outgoing",
        relations=["supports"],
        max_depth=2,
    )
    depth_zero = trace_memory(
        workspace, ["fact:graph.a"], max_depth=0)
    provisional = trace_memory(
        workspace,
        ["fact:graph.a"],
        direction="outgoing",
        max_depth=1,
        include_provisional=True,
    )

    assert {item["id"] for item in outgoing["nodes"]} == {
        "fact:graph.a", "fact:graph.b"}
    assert {item["id"] for item in incoming["nodes"]} == {
        "fact:graph.a", "fact:graph.b", "fact:graph.incoming"}
    assert {item["id"] for item in both["nodes"]} == {
        "fact:graph.a", "fact:graph.b", "fact:graph.c",
        "fact:graph.incoming",
    }
    assert {item["relation"] for item in filtered["tree_edges"]} == {
        "supports"}
    assert [item["id"] for item in depth_zero["nodes"]] == ["fact:graph.a"]
    assert depth_zero["tree_edges"] == depth_zero["back_edges"] == []
    assert "fact:graph.draft" not in json.dumps(outgoing, ensure_ascii=False)
    assert outgoing["visibility"]["provisional_included"] is False
    draft = next(
        item for item in provisional["nodes"]
        if item["id"] == "fact:graph.draft")
    assert draft["lane"] == "provisional"
    assert "fact:graph.private" not in json.dumps(provisional, ensure_ascii=False)
    with pytest.raises(ValueError, match="unknown relation"):
        trace_memory(
            workspace, ["fact:graph.a"], relations=["supportz"])


def test_trace_cycle_back_edge_and_cross_edge_are_explicit() -> None:
    workspace = _workspace(TRACE_SOURCE + '''
fact graph.cross {
  claim: "Synthetic cross node."
  relations { supports: [graph.b, graph.c] }
  lifecycle { status: active }
  evidence { source: synthetic_graph quote: "Cross." }
}
''')

    cycle = trace_memory(
        workspace, ["fact:graph.a"], max_depth=4,
        max_nodes=50, max_edges=100, max_bytes=16384)
    cross = trace_memory(
        workspace, ["fact:graph.cross"], max_depth=3,
        max_nodes=50, max_edges=100, max_bytes=16384)

    assert any(
        item["source_id"] == "fact:graph.c"
        and item["target_id"] == "fact:graph.a"
        and item["classification"] == "back"
        and item["cycle"] is True
        for item in cycle["back_edges"]
    )
    assert any(
        item["classification"] == "cross"
        for item in cross["cross_edges"]
    )
    assert "proof" in cycle["boundary"].lower()


def test_trace_node_edge_byte_budgets_cursor_and_page_merge() -> None:
    workspace = _workspace(TRACE_SOURCE)
    full = trace_memory(
        workspace, ["fact:graph.a"], direction="both", max_depth=4,
        include_provisional=True, max_nodes=100, max_edges=100,
        max_bytes=32768)

    pages = []
    cursor = None
    while True:
        page = trace_memory(
            workspace,
            ["fact:graph.a"],
            direction="both",
            max_depth=4,
            include_provisional=True,
            max_nodes=2,
            max_edges=1,
            max_bytes=4096,
            cursor=cursor,
        )
        pages.append(page)
        assert page["returned_nodes"] <= 2
        assert page["returned_edges"] <= 1
        assert _json_bytes(page) <= 4096
        cursor = page["next_cursor"]
        if cursor is None:
            break

    merged_nodes = [
        item["id"] for page in pages for item in page["nodes"]]
    merged_edges = [
        item["edge_id"]
        for page in pages
        for key in ("tree_edges", "back_edges", "cross_edges")
        for item in page[key]
    ]
    full_edges = [
        item["edge_id"]
        for key in ("tree_edges", "back_edges", "cross_edges")
        for item in full[key]
    ]

    assert merged_nodes == [item["id"] for item in full["nodes"]]
    assert sorted(merged_edges) == sorted(full_edges)
    assert len(merged_nodes) == len(set(merged_nodes))
    assert len(merged_edges) == len(set(merged_edges))
    assert pages[-1]["completeness"] == "complete"


def test_trace_exact_byte_boundary_and_cursor_errors() -> None:
    workspace = _workspace(TRACE_SOURCE)
    full = trace_memory(
        workspace, ["fact:graph.a"], max_depth=3,
        max_nodes=100, max_edges=100, max_bytes=32768)
    exact = _json_bytes(full)

    assert trace_memory(
        workspace, ["fact:graph.a"], max_depth=3,
        max_nodes=100, max_edges=100, max_bytes=exact) == full
    below = trace_memory(
        workspace, ["fact:graph.a"], max_depth=3,
        max_nodes=100, max_edges=100, max_bytes=exact - 1)
    assert _json_bytes(below) <= exact - 1
    assert below["truncated"] is True
    assert below["next_cursor"]

    first = trace_memory(
        workspace, ["fact:graph.a"], max_depth=3,
        max_nodes=1, max_edges=1, max_bytes=4096)
    with pytest.raises(TraceCursorError, match="cursor_mismatch"):
        trace_memory(
            workspace, ["fact:graph.a"], direction="incoming", max_depth=3,
            max_nodes=1, max_edges=1, max_bytes=4096,
            cursor=first["next_cursor"])
    workspace.add_document(parse_text('''
fact graph.changed {
  claim: "Synthetic changed node."
  lifecycle { status: active }
  evidence { source: synthetic_graph quote: "Changed." }
}
''', file="<phase-three/changed.mem>"))
    with pytest.raises(TraceCursorError, match="cursor_stale"):
        trace_memory(
            workspace, ["fact:graph.a"], max_depth=3,
            max_nodes=1, max_edges=1, max_bytes=4096,
            cursor=first["next_cursor"])
    replacement = _workspace('''
fact graph.replacement {
  claim: "Synthetic replacement node."
  lifecycle { status: active }
  evidence { source: synthetic_graph quote: "Replacement." }
}
''')
    with pytest.raises(TraceCursorError, match="cursor_stale"):
        trace_memory(
            replacement, ["fact:graph.a"], max_depth=3,
            max_nodes=1, max_edges=1, max_bytes=4096,
            cursor=first["next_cursor"])
    with pytest.raises(TraceCursorError, match="invalid_cursor"):
        trace_memory(workspace, ["fact:graph.a"], cursor="not-a-cursor")


def test_trace_anchor_errors_do_not_expose_restricted_content() -> None:
    workspace = _workspace(TRACE_SOURCE)

    with pytest.raises(TraceAnchorError) as missing:
        trace_memory(workspace, ["fact:graph.missing"])
    assert missing.value.code == "anchor_not_found"
    with pytest.raises(TraceAnchorError) as private:
        trace_memory(workspace, ["fact:graph.private"])
    assert private.value.code == "unauthorized"
    assert "restricted graph" not in str(private.value).lower()
    with pytest.raises(TraceAnchorError) as provisional:
        trace_memory(workspace, ["fact:graph.draft"])
    assert provisional.value.code == "anchor_not_serviceable"


def test_trace_is_independent_of_python_hash_seed() -> None:
    repository = Path(__file__).resolve().parents[1]
    script = f'''
import json
from memdsl.graph import trace_memory
from memdsl.model import Workspace
from memdsl.parser import parse_text
workspace = Workspace()
workspace.add_document(parse_text({TRACE_SOURCE!r}, file="<hash/trace.mem>"))
print(json.dumps(trace_memory(
    workspace, ["fact:graph.a"], direction="both", max_depth=4,
    include_provisional=True, max_nodes=100, max_edges=100,
    max_bytes=32768), sort_keys=True))
'''
    outputs = []
    for seed in ("1", "777"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = str(repository / "src")
        outputs.append(subprocess.check_output(
            [sys.executable, "-c", script], cwd=repository, env=env, text=True))
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("declarations", [100, 1000, 10000])
def test_default_trace_stays_bounded_at_synthetic_scale(
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
  claim: "Synthetic scale node {index:05d}."
  {relation}
  lifecycle {{ status: active }}
  evidence {{ source: synthetic_generator quote: "Node {index:05d}." }}
}}
''')
    payload = trace_memory(
        _workspace("\n".join(source)), ["fact:item.00000"],
        max_depth=declarations, max_nodes=20, max_edges=20)

    assert _json_bytes(payload) <= TRACE_DEFAULT_MAX_BYTES
    assert payload["returned_nodes"] <= 20
    assert payload["returned_edges"] <= 20
    assert payload["truncated"] is (declarations > 20)


def test_cli_and_mcp_trace_surfaces_use_new_schemas(
    tmp_path: Path,
    capsys,
) -> None:
    (tmp_path / "graph.mem").write_text(TRACE_SOURCE, encoding="utf-8")

    assert cli_main([
        "trace", str(tmp_path), "fact:graph.a", "--both", "--depth", "2",
        "--max-nodes", "4", "--max-edges", "4", "--max-bytes", "4096",
        "--json",
    ]) == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["schema_version"] == "memdsl.trace.v1"
    assert cli_payload["direction"] == "both"

    service = MemdslMCPService([str(tmp_path)])
    mcp_payload = service.trace(
        ["fact:graph.a"], direction="both", max_depth=2,
        max_nodes=4, max_edges=4, max_bytes=4096)
    assert mcp_payload["schema_version"] == "memdsl.mcp.trace.v1"
    assert "memory_trace" in service.status()["tools"]
    assert "memory_trace" not in service.status()["resources"]

    summary_only = MemdslMCPService(
        [str(tmp_path)], scopes="read:summary")
    with pytest.raises(MCPScopeError):
        summary_only.trace(["fact:graph.a"])


def test_mcp_no_match_embeds_explainable_retry_suggestions(tmp_path: Path) -> None:
    (tmp_path / "memory.mem").write_text('''
entity Synthetic.Aurora {
  canonical_name: "Aurora"
  aliases: ["aurora project"]
  lifecycle { status: active }
}
fact aurora.confirmed {
  subject: Synthetic.Aurora
  claim: "The aurora route is confirmed."
  lifecycle { status: active }
  evidence { source: synthetic_log quote: "Aurora route confirmed." }
}
''', encoding="utf-8")
    service = MemdslMCPService([str(tmp_path)])

    payload = service.query("aroura voyage")
    trace = payload["evidence_pack"]["search_trace"]

    assert payload["schema_version"] == "memdsl.mcp.query.v1"
    assert trace["vocabulary_suggestions"][0]["suggestion"] == "aurora"
    assert payload["status"] == "no_match"
    assert trace["retry_queries"] == ["aurora voyage"]
    assert any("aurora voyage" in action for action in payload["next_actions"])


def test_real_mcp_stdio_trace_cursor_resources_and_scope_denial(
    tmp_path: Path,
) -> None:
    mcp = pytest.importorskip("mcp")
    from mcp.client.stdio import StdioServerParameters, stdio_client

    del mcp
    workspace = tmp_path / "stdio-workspace"
    workspace.mkdir()
    query_path = workspace / "query.mem"
    source_path = workspace / "graph.mem"
    query_path.write_text(QUERY_SOURCE, encoding="utf-8")
    source_path.write_text(TRACE_SOURCE, encoding="utf-8")

    def tool_payload(result) -> dict:
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        for item in getattr(result, "content", []):
            text = getattr(item, "text", "")
            if text:
                return json.loads(text)
        raise AssertionError("MCP tool result did not contain JSON")

    async def run_session(scopes: str = "") -> None:
        from mcp import ClientSession

        args = [
            "-m", "memdsl.mcp_server", "--workspace", str(workspace),
        ]
        if scopes:
            args.extend(["--scopes", scopes])
        parameters = StdioServerParameters(command=sys.executable, args=args)
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {item.name for item in tools.tools}
                assert {"memory_catalog", "memory_map", "memory_trace"} <= names

                if scopes:
                    denied_query = await session.call_tool(
                        "memory_query", {"query": "aurora"})
                    denied_trace = await session.call_tool(
                        "memory_trace", {"anchors": ["fact:graph.a"]})
                    assert denied_query.isError is True
                    assert denied_trace.isError is True
                    status = await session.read_resource("memdsl://status")
                    assert json.loads(status.contents[0].text)["ok"] is True
                    return

                first_catalog = tool_payload(await session.call_tool(
                    "memory_catalog", {"limit": 1, "max_bytes": 4096}))
                assert first_catalog["schema_version"] == "memdsl.mcp.catalog.v1"
                second_catalog = tool_payload(await session.call_tool(
                    "memory_catalog",
                    {
                        "limit": 1,
                        "max_bytes": 4096,
                        "cursor": first_catalog["next_cursor"],
                    },
                ))
                assert second_catalog["status"] == "ok"

                trace = tool_payload(await session.call_tool(
                    "memory_trace",
                    {
                        "anchors": ["fact:graph.a"],
                        "max_depth": 4,
                        "max_nodes": 1,
                        "max_edges": 1,
                        "max_bytes": 4096,
                    },
                ))
                assert trace["schema_version"] == "memdsl.mcp.trace.v1"
                assert trace["next_cursor"]

                query = tool_payload(await session.call_tool(
                    "memory_query", {"query": "aurora launch"}))
                assert query["evidence_pack"]["must"]
                check = tool_payload(await session.call_tool(
                    "memory_check",
                    {
                        "task": "publish a synthetic launch note",
                        "candidate": "include ember-token",
                    },
                ))
                assert check["status"] == "block"

                legacy_map = await session.read_resource("memdsl://map")
                assert json.loads(
                    legacy_map.contents[0].text)["schema_version"] == (
                        "memdsl.mcp.map.v1")

                source_path.write_text(
                    TRACE_SOURCE + '''
fact graph.changed {
  claim: "Synthetic stdio change."
  lifecycle { status: active }
  evidence { source: synthetic_graph quote: "Changed." }
}
''',
                    encoding="utf-8",
                )
                stale = tool_payload(await session.call_tool(
                    "memory_trace",
                    {
                        "anchors": ["fact:graph.a"],
                        "max_depth": 4,
                        "max_nodes": 1,
                        "max_edges": 1,
                        "max_bytes": 4096,
                        "cursor": trace["next_cursor"],
                    },
                ))
                assert stale["status"] == "cursor_stale"

    asyncio.run(run_session())
    asyncio.run(run_session("read:summary"))


def test_disposable_gated_write_keeps_pending_out_and_stales_trace_cursor(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "gated-workspace"
    workspace.mkdir()
    (workspace / "graph.mem").write_text(TRACE_SOURCE, encoding="utf-8")
    service = MemdslMCPService([str(workspace)])

    invalid = service.propose('''
fact graph.invalid {
  claim: "Synthetic missing evidence."
  lifecycle { status: active }
}
''')
    assert invalid["status"] == "invalid"
    assert {item["code"] for item in invalid["errors"]} == {
        "missing_evidence"}

    first_trace = service.trace(
        ["fact:graph.a"], max_depth=4,
        max_nodes=1, max_edges=1, max_bytes=4096)
    before_fingerprint = first_trace["view"]["source_fingerprint"]
    proposal = service.propose('''
fact graph.approved {
  claim: "Synthetic approved beacon."
  relations { supports: graph.a }
  lifecycle { status: active }
  evidence { source: synthetic_review quote: "Approved beacon." }
}
''')
    assert proposal["status"] == "pending_review"

    pending_trace = service.trace(
        ["fact:graph.a"], direction="incoming", max_depth=1,
        include_provisional=True, max_bytes=4096)
    assert "fact:graph.approved" not in json.dumps(pending_trace)
    pending_query = service.query("approved beacon")
    assert "fact:graph.approved" not in json.dumps(pending_query)

    into = workspace / "approved.mem"
    approved = service.review_store.approve(
        proposal["proposal_id"],
        Workspace.load([str(workspace)]),
        str(into),
    )
    assert approved["status"] == "approved"
    double = service.review_store.approve(
        proposal["proposal_id"],
        Workspace.load([str(workspace)]),
        str(into),
    )
    assert double["status"] == "already_approved"

    served_query = service.query("approved beacon")
    assert [item["id"] for item in served_query["evidence_pack"]["context"]] == [
        "fact:graph.approved"]
    served_trace = service.trace(
        ["fact:graph.a"], direction="incoming", max_depth=1,
        max_bytes=4096)
    assert "fact:graph.approved" in json.dumps(served_trace)
    assert served_trace["view"]["source_fingerprint"] != before_fingerprint

    stale = service.trace(
        ["fact:graph.a"], max_depth=4,
        max_nodes=1, max_edges=1, max_bytes=4096,
        cursor=first_trace["next_cursor"])
    assert stale["status"] == "cursor_stale"
    actions = [
        item["action"] for item in service.review_store.audit_entries()
    ]
    assert actions == ["propose", "route", "approve"]
