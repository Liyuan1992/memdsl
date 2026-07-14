"""Install the built wheel outside the repository and exercise CLI/MCP surfaces."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import textwrap
import venv
from pathlib import Path
from typing import List, Optional


PAPER_FILES = {
    "CITATION.cff",
    "LICENSE",
    "DOCUMENTATION_INDEX.md",
    "DESIGN_memory_source_compiled_view.md",
    "DESIGN_explicit_edges_phase6.md",
    "PAPER_LICENSE.md",
    "PAPER_publication_readiness_audit.md",
    "PAPER_related_work_claim_ledger.md",
    "PAPER_reproducibility_and_release_metadata.md",
    "PAPER_review_gated_authority_source_compiled_contract.md",
    "baselines/PHASE_MINUS_ONE_SCALE_BASELINE.md",
    "baselines/phase_minus_one_0.6.0.json",
    "benchmarks/phase_minus_one_baseline.py",
    "PUBLIC_API.md",
    "SPEC.md",
    "UPGRADING.md",
}


STDIO_PROBE = r'''
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def payload(result):
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for item in getattr(result, "content", []):
        text = getattr(item, "text", "")
        if text:
            return json.loads(text)
    raise AssertionError("MCP result did not contain JSON")


async def session(workspace, scopes="", enforced=False):
    args = ["-m", "memdsl.mcp_server", "--workspace", workspace]
    if scopes:
        args.extend(["--scopes", scopes])
    params = StdioServerParameters(command=sys.executable, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            tools = await client.list_tools()
            names = {item.name for item in tools.tools}
            assert len(names) == 11
            assert {"memory_catalog", "memory_map", "memory_query", "memory_trace"} <= names
            status_resource = await client.read_resource("memdsl://status")
            status = json.loads(status_resource.contents[0].text)
            if enforced:
                assert status["schema_version"] == "memdsl.mcp.status.v2"
                query = await client.call_tool("memory_query", {"query": "broken beacon"})
                if scopes:
                    assert query.isError is True
                else:
                    assert payload(query)["status"] == "quarantined"
                return len(names)
            assert status["ok"] is True
            query = await client.call_tool(
                "memory_query", {"query": "draft a public blog post about aurora"}
            )
            if scopes:
                assert query.isError is True
                return len(names)
            assert payload(query)["evidence_pack"]["must"]
            catalog = payload(await client.call_tool(
                "memory_catalog", {"limit": 1, "max_bytes": 4096}
            ))
            assert catalog["schema_version"] == "memdsl.mcp.catalog.v1"
            trace = payload(await client.call_tool(
                "memory_trace",
                {"anchors": ["decision:aurora.pricing_free_tier"], "max_bytes": 4096},
            ))
            assert trace["schema_version"] == "memdsl.mcp.trace.v1"
            return len(names)


async def main():
    alex, enforced = sys.argv[1], sys.argv[2]
    counts = [
        await session(alex),
        await session(alex, "read:summary"),
        await session(enforced, enforced=True),
        await session(enforced, "read:summary", enforced=True),
    ]
    assert counts == [11, 11, 11, 11]
    print(json.dumps({"stdio_tools": counts[0], "scope_denial": "ok", "v2": "ok"}))


asyncio.run(main())
'''


EDGE_STDIO_PROBE = r'''
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def payload(result):
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for item in getattr(result, "content", []):
        text = getattr(item, "text", "")
        if text:
            return json.loads(text)
    raise AssertionError("MCP result did not contain JSON")


async def main():
    workspace = sys.argv[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "memdsl.mcp_server", "--workspace", workspace],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            tools = await client.list_tools()
            names = {item.name for item in tools.tools}
            assert len(names) == 11
            assert not any(name.startswith("edge_") for name in names)
            listed = payload(await client.call_tool(
                "memory_list", {"kind": "relation_edge"}
            ))
            assert listed["total"] == 1
            traced = payload(await client.call_tool(
                "memory_trace", {"anchors": ["fact:graph.alpha"]}
            ))
            assert traced["available_edges"] == 1
            proposed = payload(await client.call_tool(
                "memory_propose",
                {"source": """
relation_edge graph.second_support {
  declared_by: "entity:Reviewer"
  source: "fact:graph.beta"
  target: "fact:graph.alpha"
  relation: supports
  lifecycle { status: active }
  evidence {
    source: synthetic_fresh_install
    quote: "Beta supports alpha in the fictional fresh-install fixture."
  }
}
"""},
            ))
            assert proposed["status"] == "pending_review"
            assert "explicit_edge_human_review_required" in proposed["reason_codes"]
            print(json.dumps({
                "edge_stdio_tools": len(names),
                "edge_list": listed["total"],
                "edge_trace": traced["available_edges"],
                "edge_proposal": proposed["status"],
            }))


asyncio.run(main())
'''


def _run(command: List[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {command!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return result


def _python_in(env_dir: Path) -> Path:
    if sys.platform == "win32":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--expected", required=True)
    args = parser.parse_args(argv)

    wheel = args.wheel.resolve()
    workspace = args.workspace.resolve()
    if not wheel.is_file():
        raise AssertionError(f"wheel not found: {wheel}")
    if not workspace.is_dir():
        raise AssertionError(f"workspace not found: {workspace}")

    with tempfile.TemporaryDirectory(prefix="memdsl-release-") as temp_text:
        temp_root = Path(temp_text).resolve()
        env_dir = temp_root / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        python = _python_in(env_dir)
        requirement = f"memdsl[mcp] @ {wheel.as_uri()}"
        _run([str(python), "-m", "pip", "install", requirement], cwd=temp_root)

        import_result = _run(
            [
                str(python),
                "-c",
                (
                    "import json, memdsl; "
                    "print(json.dumps({'version': memdsl.__version__, "
                    "'import_path': memdsl.__file__}))"
                ),
            ],
            cwd=temp_root,
        )
        import_payload = json.loads(import_result.stdout.strip().splitlines()[-1])
        import_path = Path(import_payload["import_path"]).resolve()
        if import_payload["version"] != args.expected:
            raise AssertionError(import_payload)
        if not _is_within(import_path, env_dir.resolve()):
            raise AssertionError(f"fresh import escaped venv: {import_path}")

        paper_root = env_dir / "share" / "doc" / "memdsl"
        missing_paper_files = sorted(
            relative for relative in PAPER_FILES if not (paper_root / relative).is_file()
        )
        if missing_paper_files:
            raise AssertionError(
                "fresh wheel is missing paper files: " + ", ".join(missing_paper_files)
            )
        print(f"fresh_paper_files={len(PAPER_FILES)}")

        _run([str(python), "-m", "pip", "check"], cwd=temp_root)
        _run([str(python), "-m", "memdsl.cli", "--version"], cwd=temp_root)
        _run(
            [str(python), "-m", "memdsl.mcp_server", "--inspect", "-w", str(workspace)],
            cwd=temp_root,
        )

        enforced = temp_root / "enforced"
        enforced.mkdir()
        (enforced / "memdsl.json").write_text(
            json.dumps(
                {
                    "schema_version": "memdsl.workspace.v2",
                    "schemas": [],
                    "linking": {"visibility": "report"},
                    "enforcement": {"mode": "quarantine"},
                }
            ),
            encoding="utf-8",
        )
        (enforced / "memory.mem").write_text(
            textwrap.dedent(
                '''
                fact broken.item {
                  claim: "Synthetic broken beacon."
                  relations { supports: missing.item }
                  evidence { source: synthetic quote: "Broken." }
                }
                fact safe.item {
                  claim: "Synthetic safe beacon."
                  evidence { source: synthetic quote: "Safe." }
                }
                '''
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        _run(
            [str(python), "-c", STDIO_PROBE, str(workspace), str(enforced)],
            cwd=temp_root,
        )

        edge_workspace = temp_root / "explicit-edge"
        edge_workspace.mkdir()
        (edge_workspace / "memdsl.json").write_text(
            json.dumps(
                {
                    "schema_version": "memdsl.workspace.v3",
                    "schemas": [],
                    "linking": {"visibility": "report"},
                    "enforcement": {"mode": "report"},
                    "features": {"explicit_edges": "experimental-v1"},
                }
            ),
            encoding="utf-8",
        )
        (edge_workspace / "memory.mem").write_text(
            textwrap.dedent(
                '''
                module fictional.graph

                entity Reviewer {
                  canonical_name: "Fictional reviewer"
                  status: active
                }

                fact graph.alpha {
                  claim: "Synthetic alpha node."
                  status: active
                  evidence { source: synthetic_fresh_install quote: "Alpha." }
                }

                fact graph.beta {
                  claim: "Synthetic beta node."
                  status: active
                  evidence { source: synthetic_fresh_install quote: "Beta." }
                }

                relation_edge graph.alpha_supports_beta {
                  declared_by: "entity:Reviewer"
                  source: "fact:graph.alpha"
                  target: "fact:graph.beta"
                  relation: supports
                  lifecycle { status: active }
                  evidence {
                    source: synthetic_fresh_install
                    quote: "Alpha supports beta in the fictional fresh-install fixture."
                  }
                }
                '''
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        _run(
            [str(python), "-m", "memdsl.cli", "edge", "list",
             str(edge_workspace), "--json"],
            cwd=temp_root,
        )
        _run(
            [str(python), "-m", "memdsl.mcp_server", "--inspect", "-w",
             str(edge_workspace)],
            cwd=temp_root,
        )
        _run(
            [str(python), "-c", EDGE_STDIO_PROBE, str(edge_workspace)],
            cwd=temp_root,
        )
        print(f"fresh_python={python}")
        print(f"fresh_import={import_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
