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


def test_resources_registered(server):
    resources = asyncio.run(server.list_resources())
    uris = {str(r.uri) for r in resources}
    assert "memdsl://status" in uris
    assert "memdsl://files" in uris


def test_call_memory_query(server):
    result = asyncio.run(
        server.call_tool("memory_query", {"query": "meetings tomorrow morning"})
    )
    text = json.dumps(_as_jsonable(result), ensure_ascii=False, default=str)
    assert "boundary:schedule.no_meetings_before_10" in text
    assert "must" in text


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
