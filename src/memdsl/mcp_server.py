"""FastMCP entrypoint for the memdsl memory server.

Requires the optional `mcp` extra:

    pip install memdsl[mcp]

Run over one or more workspaces of `.mem` files:

    memdsl-mcp --workspace ~/memory
    memdsl-mcp -w examples/alex -w examples/mira --inspect

Or register with an MCP client, e.g. Claude Code:

    claude mcp add memdsl -- memdsl-mcp --workspace ~/memory
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, List, Optional

from memdsl.mcp_service import MemdslMCPService, TOOL_NAMES

SERVER_NAME = "memdsl"
SERVER_INSTRUCTIONS = (
    "memdsl serves agent memory written as .mem source files. Call "
    "memory_query first and obey the layered contract: MUST items are hard "
    "rules to enforce, SHOULD items are strong preferences, CONTEXT items "
    "are scored candidate facts, CONFLICT items must be surfaced to the "
    "user, and MISSING items are known gaps. Call memory_explain on a "
    "declaration id before citing it as evidence. This server is "
    "read-only: it never writes or approves memory."
)


def build_mcp_server(service: Optional[MemdslMCPService] = None, **service_kwargs: Any):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised without the extra
        raise RuntimeError(
            "MCP Python SDK is not installed. Install the optional extra, "
            "for example: pip install memdsl[mcp]"
        ) from exc

    svc = service or MemdslMCPService(**service_kwargs)
    mcp = FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

    @mcp.resource("memdsl://status", mime_type="application/json")
    def memdsl_status() -> str:
        """memdsl workspace status: files, declaration kinds, scopes."""
        return _json(svc.status())

    @mcp.resource("memdsl://files", mime_type="application/json")
    def memdsl_files() -> str:
        """List .mem source files with their file ids."""
        return _json(svc.list_files())

    @mcp.resource("memdsl://file/{file_id}", mime_type="text/plain")
    def memdsl_file(file_id: str) -> str:
        """Raw .mem source for one file id (memory as source code)."""
        payload = svc.read_file(file_id)
        if not payload.get("ok"):
            return _json(payload)
        return str(payload.get("content", ""))

    @mcp.tool(name="memory_query")
    def memory_query(
        query: str,
        kinds: Optional[List[str]] = None,
        subject: str = "",
        limit: int = 8,
    ) -> dict:
        """Query memory into a layered evidence pack (MUST/SHOULD/CONTEXT/CONFLICT/MISSING)."""
        return svc.query(query, kinds=kinds, subject=subject or None, limit=limit)

    @mcp.tool(name="memory_explain")
    def memory_explain(id: str) -> dict:
        """Show one declaration with its evidence, relations, and reverse references."""
        return svc.explain(id)

    @mcp.tool(name="memory_list")
    def memory_list(
        kind: str = "",
        subject: str = "",
        include_inactive: bool = False,
        limit: int = 100,
    ) -> dict:
        """Browse declarations, optionally filtered by kind or subject."""
        return svc.list_declarations(
            kind=kind or None,
            subject=subject or None,
            include_inactive=include_inactive,
            limit=limit,
        )

    @mcp.tool(name="memory_lint")
    def memory_lint() -> dict:
        """Lint the memory workspace and report diagnostics."""
        return svc.lint_workspace()

    @mcp.prompt(name="memdsl_task_brief")
    def memdsl_task_brief(task: str = "") -> str:
        """Brief an agent on how to use memdsl memory for a task."""
        return (
            "Before acting, call memory_query with the task's key nouns. "
            "Treat MUST items as rules you enforce even when they seem "
            "irrelevant, SHOULD items as strong preferences, and CONTEXT "
            "items as candidate facts. Surface CONFLICT items to the user "
            "instead of resolving them silently, and state MISSING gaps "
            "rather than guessing. Call memory_explain before citing any "
            "declaration.\n\n"
            f"Task: {task}"
        )

    return mcp


def inspection_payload(service: MemdslMCPService) -> dict:
    return {
        "ok": True,
        "server": SERVER_NAME,
        "tools": list(TOOL_NAMES),
        "status": service.status(),
        "lint": service.lint_workspace(),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="memdsl-mcp",
        description="Run the memdsl memory MCP server (stdio)")
    parser.add_argument(
        "-w", "--workspace", action="append", default=[],
        help=".mem file or directory (repeatable; default: MEMDSL_WORKSPACE)")
    parser.add_argument(
        "--scopes", default="",
        help="comma-separated scopes (default: read:summary,read:search)")
    parser.add_argument(
        "--inspect", action="store_true",
        help="print status and lint results without starting the MCP transport")
    args = parser.parse_args(argv)

    workspaces = list(args.workspace)
    if not workspaces:
        env = os.getenv("MEMDSL_WORKSPACE", "")
        workspaces = [p for p in env.split(os.pathsep) if p.strip()]
    if not workspaces:
        print("no workspace given: pass --workspace or set MEMDSL_WORKSPACE",
              file=sys.stderr)
        return 2

    try:
        service = MemdslMCPService(workspaces, scopes=args.scopes or None)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.inspect:
        print(_json(inspection_payload(service)))
        return 0

    try:
        server = build_mcp_server(service=service)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    server.run(transport="stdio")
    return 0


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
