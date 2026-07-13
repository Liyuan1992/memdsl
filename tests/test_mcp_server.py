"""Tests for the FastMCP wiring. Skipped when the mcp extra is absent."""

import asyncio
import json

import pytest

pytest.importorskip("mcp")

from memdsl.mcp_server import build_mcp_server, inspection_payload, main
from memdsl.mcp_service import MemdslMCPService, TOOL_NAMES

MEM_SOURCE = """\
module self

entity User {
  kind: Person
  canonical_name: "Sam"
  aliases: ["me", "Sam"]
  status: active
}

boundary schedule.no_meetings_before_10 {
  subject: User
  rule: "Never schedule meetings before 10:00."
  force: hard
  scope: global
  exceptions: [emergency]
  status: active
  guard {
    when_any: ["meeting", "schedule"]
    deny_regex: ["\\\\b0?[0-9]:[0-5][0-9]\\\\b"]
  }
  evidence {
    source: chat
    quote: "Please never book me before ten."
  }
}
"""


@pytest.fixture
def workspace_dir(tmp_path):
    path = tmp_path / "memory"
    path.mkdir()
    (path / "self.mem").write_text(MEM_SOURCE, encoding="utf-8")
    return path


@pytest.fixture
def server(workspace_dir):
    return build_mcp_server(service=MemdslMCPService([str(workspace_dir)]))


def test_tools_registered(server):
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert set(TOOL_NAMES) <= names


def test_memory_propose_tool_does_not_accept_attestation_fields(server):
    tools = asyncio.run(server.list_tools())
    tool = next(item for item in tools if item.name == "memory_propose")
    properties = tool.inputSchema.get("properties", {})
    assert set(properties) == {"source", "reason"}
    assert not ({"client", "trusted", "verified", "verifier", "scopes"}
                & set(properties))


def test_resources_registered(server):
    resources = asyncio.run(server.list_resources())
    uris = {str(r.uri) for r in resources}
    assert "memdsl://status" in uris
    assert "memdsl://map" in uris
    assert "memdsl://types" in uris
    assert "memdsl://files" in uris


def test_call_memory_propose_stages_only(server, workspace_dir):
    source = (
        "preference feedback.direct {\n"
        "  subject: User\n"
        "  claim: \"Prefers direct feedback.\"\n"
        "  force: strong\n"
        "  status: active\n"
        "  evidence {\n"
        "    source: chat\n"
        "    quote: \"Just tell me what is wrong.\"\n"
        "  }\n"
        "}\n"
    )
    result = asyncio.run(server.call_tool("memory_propose", {"source": source}))
    text = json.dumps(_as_jsonable(result), ensure_ascii=False, default=str)
    assert "pending_review" in text
    # staged under .memdsl, not served as workspace memory
    assert (workspace_dir / ".memdsl" / "proposals").is_dir()
    status = asyncio.run(server.read_resource("memdsl://status"))
    payload = json.loads(list(status)[0].content)
    assert payload["declarations"] == 2
    assert payload["pending_proposals"] == 1


def test_call_memory_query(server):
    result = asyncio.run(
        server.call_tool("memory_query", {"query": "meetings tomorrow morning"})
    )
    text = json.dumps(_as_jsonable(result), ensure_ascii=False, default=str)
    assert "boundary:schedule.no_meetings_before_10" in text
    assert "must" in text


def test_call_memory_check(server):
    result = asyncio.run(server.call_tool(
        "memory_check",
        {"task": "schedule a meeting", "candidate": "Meeting at 09:30."},
    ))
    text = json.dumps(_as_jsonable(result), ensure_ascii=False, default=str)
    assert "block" in text
    assert "boundary:schedule.no_meetings_before_10" in text


def test_call_memory_types(server):
    result = asyncio.run(server.call_tool("memory_types", {}))
    text = json.dumps(_as_jsonable(result), ensure_ascii=False, default=str)
    assert "memdsl.mcp.types.v1" in text
    assert '"name": "boundary"' in text or "boundary" in text


def test_read_status_resource(server):
    result = asyncio.run(server.read_resource("memdsl://status"))
    blob = list(result)[0]
    payload = json.loads(blob.content)
    assert payload["ok"] is True
    assert payload["server"] == "memdsl"


def test_main_inspect(workspace_dir, capsys):
    code = main(["--inspect", "--workspace", str(workspace_dir)])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"]["declarations"] == 2
    assert payload["lint"]["errors"] == 0


def test_main_inspect_fails_closed_on_schema_error(tmp_path, capsys):
    workspace = tmp_path / "invalid-schema"
    workspace.mkdir()
    (workspace / "memdsl.json").write_text(json.dumps({
        "schema_version": "memdsl.workspace.v9",
        "schemas": [],
    }), encoding="utf-8")
    (workspace / "memory.mem").write_text(
        'fact x { claim: "x" status: candidate }', encoding="utf-8")
    code = main(["--inspect", "--workspace", str(workspace)])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["status"]["status"] == "schema_error"
    assert payload["lint"]["status"] == "schema_error"


def test_main_requires_workspace(monkeypatch, capsys):
    monkeypatch.delenv("MEMDSL_WORKSPACE", raising=False)
    assert main(["--inspect"]) == 2


def _as_jsonable(result):
    if isinstance(result, tuple):
        return [_as_jsonable(item) for item in result]
    if isinstance(result, list):
        return [_as_jsonable(item) for item in result]
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result
