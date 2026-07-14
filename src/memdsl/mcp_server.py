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
    "memory_catalog at session start for bounded module/type/subject/status "
    "navigation, then call memory_query with the task's key "
    "nouns and obey the layered contract: MUST items are active hard "
    "constraints, SHOULD items are active guidance, CONTEXT items are active "
    "assertions, and PROVISIONAL items are non-active, unconfirmed candidates "
    "that never carry MUST/SHOULD/CONTEXT/MISSING/compliance authority. "
    "CONFLICT items must be surfaced to the user, and MISSING items are known "
    "gaps. A no_match result is a retry signal, not "
    "proof of absence: check search_trace for filter exclusions, re-query "
    "with the returned workspace vocabulary, continue the Catalog cursor, or "
    "browse memory_list and the "
    "raw memdsl://file/{file_id} sources. Call memory_explain on a "
    "declaration id before citing it as evidence. Before returning or acting "
    "on a consequential draft, call memory_check; BLOCK forbids the draft and "
    "NEEDS_REVIEW is not approval. memory_propose always passes through the "
    "review gate. Pending proposals remain invisible. A deployment may grant "
    "write:auto, but only an explicitly opted-in candidate assertion with a "
    "trusted host client, verified workspace evidence, a matching policy, "
    "quota, and sampling approval can enter PROVISIONAL automatically. Never "
    "present pending or provisional memory as human-confirmed authority."
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
        """memdsl workspace status: files, memory types, schemas, and scopes."""
        return _json(svc.status())

    @mcp.resource("memdsl://map", mime_type="application/json")
    def memdsl_map() -> str:
        """Compact index of serviceable active and provisional lifecycle memory."""
        return _json(svc.memory_map())

    @mcp.resource("memdsl://catalog", mime_type="application/json")
    def memdsl_catalog() -> str:
        """Bounded module/type/subject/status navigation Catalog."""
        return _json(svc.catalog())

    @mcp.resource("memdsl://files", mime_type="application/json")
    def memdsl_files() -> str:
        """List .mem source files with their file ids."""
        return _json(svc.list_files())

    @mcp.resource("memdsl://types", mime_type="application/json")
    def memdsl_types() -> str:
        """Loaded standard and domain memory types."""
        return _json(svc.list_types())

    @mcp.resource("memdsl://file/{file_id}", mime_type="text/plain")
    def memdsl_file(file_id: str) -> str:
        """Raw .mem source for one file id (memory as source code)."""
        payload = svc.read_file(file_id)
        if not payload.get("ok"):
            return _json(payload)
        return str(payload.get("content", ""))

    @mcp.tool(name="memory_map")
    def memory_map() -> dict:
        """Legacy v1 full Map retained for compatibility; prefer memory_catalog for bounded session-start navigation."""
        return svc.memory_map()

    @mcp.tool(name="memory_catalog")
    def memory_catalog(
        module: str = "",
        types: Optional[List[str]] = None,
        subject: str = "",
        statuses: Optional[List[str]] = None,
        limit: int = 20,
        max_bytes: int = 8192,
        cursor: str = "",
        order: str = "asc",
        representation: str = "structured",
    ) -> dict:
        """Read bounded Catalog pages filtered by module, type, subject, or lifecycle status."""
        return svc.catalog(
            module=module or None,
            types=types,
            subject=subject or None,
            statuses=statuses,
            limit=limit,
            max_bytes=max_bytes,
            cursor=cursor or None,
            order=order,
            representation=representation,
        )

    @mcp.tool(name="memory_query")
    def memory_query(
        query: str,
        kinds: Optional[List[str]] = None,
        types: Optional[List[str]] = None,
        subject: str = "",
        limit: int = 8,
    ) -> dict:
        """Query memory into MUST/SHOULD/CONTEXT/PROVISIONAL/CONFLICT/MISSING layers."""
        return svc.query(
            query, kinds=kinds, types=types,
            subject=subject or None, limit=limit)

    @mcp.tool(name="memory_check")
    def memory_check(
        task: str,
        candidate: str,
        subject: str = "",
        scope: str = "",
        exceptions: Optional[List[str]] = None,
    ) -> dict:
        """Preflight a proposed action or draft against applicable MUST constraints."""
        return svc.check(
            task, candidate,
            subject=subject or None,
            scope=scope or None,
            exceptions=exceptions,
        )

    @mcp.tool(name="memory_types")
    def memory_types() -> dict:
        """List loaded domain memory types, runtime roles, capabilities, and required fields."""
        return svc.list_types()

    @mcp.tool(name="memory_explain")
    def memory_explain(id: str) -> dict:
        """Show one declaration with its evidence, relations, and reverse references."""
        return svc.explain(id)

    @mcp.tool(name="memory_list")
    def memory_list(
        kind: str = "",
        memory_type: str = "",
        subject: str = "",
        include_inactive: bool = False,
        limit: int = 100,
    ) -> dict:
        """Browse declarations, optionally filtered by memory type or subject."""
        return svc.list_declarations(
            kind=kind or None,
            memory_type=memory_type or None,
            subject=subject or None,
            include_inactive=include_inactive,
            limit=limit,
        )

    @mcp.tool(name="memory_lint")
    def memory_lint() -> dict:
        """Lint the memory workspace and report diagnostics."""
        return svc.lint_workspace()

    @mcp.tool(name="memory_propose")
    def memory_propose(source: str, reason: str = "") -> dict:
        """Submit one declaration to governed review. Pending writes stay invisible; narrowly opted-in candidate assertions may be policy-approved only from host-verified evidence."""
        return svc.propose(source, reason=reason)

    @mcp.tool(name="memory_review_list")
    def memory_review_list(status: str = "pending", limit: int = 50) -> dict:
        """List review proposals and routing metadata (pending/approved/rejected/all). High-risk, sampled, and superseding decisions remain human-reviewed."""
        return svc.list_proposals(status=status, limit=limit)

    @mcp.prompt(name="memdsl_task_brief")
    def memdsl_task_brief(task: str = "") -> str:
        """Brief an agent on how to use memdsl memory for a task."""
        return (
            "Start by calling memory_catalog for a bounded view of modules, "
            "types, subjects, and statuses. Continue next_cursor only with the "
            "same filters/order/representation. Then call memory_query with the "
            "task's key nouns. Treat MUST items as constraints you enforce "
            "even when they seem irrelevant, SHOULD items as guidance, and "
            "CONTEXT items as active assertions, and PROVISIONAL items as "
            "unconfirmed non-active candidates that cannot control behavior. "
            "Surface CONFLICT items to the "
            "user instead of resolving them silently, and state MISSING gaps "
            "rather than guessing. If a query returns no_match, do not "
            "conclude the memory is absent: check search_trace for filter "
            "exclusions, re-query with the returned vocabulary, continue or "
            "refine memory_catalog, or browse "
            "memory_list and the raw sources. Call memory_explain before "
            "citing any declaration. Before returning a consequential draft, "
            "call memory_check and treat NEEDS_REVIEW as unresolved, not "
            "allowed.\n\n"
            f"Task: {task}"
        )

    @mcp.prompt(name="memdsl_write_declaration")
    def memdsl_write_declaration(fact: str = "") -> str:
        """Template for turning an observation into a lint-clean .mem proposal."""
        return (
            "Turn the observation below into ONE .mem declaration and submit "
            "it with memory_propose. Rules:\n"
            "- Call memory_types first. Pick a loaded standard or domain type "
            "whose runtime_role and required_fields match the observation.\n"
            "- Include a verbatim evidence quote from the source "
            "conversation; never invent or paraphrase quotes.\n"
            "- Use an existing symbol declaration as subject. Call "
            "memory_types to find types with runtime_role=symbol, then browse "
            "that type with memory_list; declare the symbol separately if needed.\n"
            "- If it replaces an existing declaration, add "
            "supersedes: <old_id> instead of contradicting it.\n"
            "- The declaration starts with the exact loaded type name, then "
            "a stable memory id and a field block. Do not invent a type that "
            "memory_types did not return.\n\n"
            f"Observation: {fact}"
        )

    return mcp


def inspection_payload(service: MemdslMCPService) -> dict:
    status = service.status()
    lint_result = service.lint_workspace()
    return {
        "ok": bool(status.get("ok") and lint_result.get("ok")),
        "server": SERVER_NAME,
        "tools": list(TOOL_NAMES),
        "status": status,
        "lint": lint_result,
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
        help=("comma-separated scopes (default: read:summary,read:search,"
              "write:candidate; add write:auto explicitly for policy routing)"))
    parser.add_argument(
        "--client", default="",
        help=("host-authenticated client id used by review policy "
              "(default: MEMDSL_MCP_CLIENT or mcp-client)"))
    parser.add_argument(
        "--staging", default="",
        help="review-queue staging dir (default: <workspace>/.memdsl)")
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
        service = MemdslMCPService(
            workspaces,
            scopes=args.scopes or None,
            staging=args.staging or None,
            client_name=args.client or "",
        )
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.inspect:
        payload = inspection_payload(service)
        print(_json(payload))
        return 0 if payload["ok"] else 1

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
