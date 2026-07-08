---
name: verify
description: How to build, run, and verify memdsl (CLI and MCP server) end-to-end.
---

# Verifying memdsl

## Setup

```console
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,mcp]"   # POSIX: .venv/bin/...
```

## Surfaces

**CLI** (`memdsl`): drive against the shipped example workspaces.

```console
memdsl lint examples/lint-demo/          # expect 2 errors, 3 warnings
memdsl query examples/alex/ -q "draft a public blog post about aurora"
memdsl explain examples/alex/ boundary:privacy.no_family_in_public
```

`examples/alex` lints with one intentional warning; `examples/mira` is clean.

**MCP server** (`memdsl-mcp`): first check without transport, then drive
real stdio with an MCP client session.

```console
memdsl-mcp --inspect -w examples/alex    # status + lint JSON, exit 0
memdsl-mcp                               # no workspace -> stderr + exit 2
```

For a true stdio round-trip, use `mcp.client.stdio.stdio_client` +
`ClientSession` pointed at the `memdsl-mcp` executable: initialize, list
tools (expect memory_query/memory_explain/memory_list/memory_lint), call
`memory_query` and check MUST ids surface global boundaries, read
`memdsl://status` and `memdsl://file/{0}` resources.

## Gotchas

- Scope probe: `--scopes read:summary` must make `memory_query` /
  `memory_explain` return isError tool results while resources still read.
- `init.serverInfo.version` reports the MCP SDK version, not memdsl's.
- Workspace reload is mtime+size based; tests bump mtime with `os.utime`.
