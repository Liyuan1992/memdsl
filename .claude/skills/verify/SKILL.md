---
name: verify
description: How to build, run, and verify memdsl (CLI and MCP server) end-to-end.
---

# Verifying memdsl

## Setup

Use the project-local environment and install the current checkout with all
verification extras:

```console
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,mcp]"   # POSIX: .venv/bin/...
```

Confirm that the installed entry points report the checkout version:

```console
memdsl --version                 # v0.5 checkout: memdsl 0.5.0
memdsl-mcp --help
```

## Test suite

```console
.venv/Scripts/python -m pytest
```

Run the entire suite before packaging. Do not treat a small targeted test as
the completion gate for schema, review, or MCP changes.

## Standard compatibility surfaces

The built-in `memdsl.standard@1` pack must keep v0.4 workspaces working:

```console
memdsl lint examples/lint-demo/          # expect 2 errors, 3 warnings
memdsl lint examples/alex/               # one intentional warning
memdsl lint examples/mira/               # clean
memdsl query examples/alex/ -q "draft a public blog post about aurora"
memdsl explain examples/alex/ boundary:privacy.no_family_in_public
memdsl check examples/compliance/ -t "draft a public blog post" -c "My family helped."
memdsl eval compliance examples/compliance/ --cases examples/compliance/cases.jsonl
```

Compatibility JSON may still expose deprecated aliases such as `kind`,
`boundary_id`, and `applicable_must`. New surfaces must also expose generic
`type`, `runtime_role`, `capabilities`, and `applicable_constraints` data.

## v0.5 domain type surfaces

Exercise all shipped schema packs. Each workspace must load its local
`memdsl.json`, resolve its `.memschema.json`, and lint cleanly:

```console
memdsl lint examples/domains/coding
memdsl lint examples/domains/assistant
memdsl lint examples/domains/writing
memdsl types examples/domains/coding
memdsl types examples/domains/coding --json
```

The coding workspace is the primary role/capability proof:

```console
memdsl query examples/domains/coding -q "force push main"
memdsl check examples/domains/coding -t "push main" -c "git push --force origin main"
memdsl eval compliance examples/domains/coding --cases examples/domains/coding/cases.jsonl --json
```

Expect `coding.project_rule:git.no_force_push` in MUST and a `block` verdict
for the force-push candidate. This proves a domain-defined type reaches query
and compliance through `runtime_role=constraint` plus capabilities; the Python
runtime must not special-case the type name.

Also verify that:

- an unknown type produces `unknown_memory_type`;
- a strict schema rejects an undeclared field with `unknown_type_field`;
- a domain constraint lacking `enforceable + guardable` remains visible in
  MUST but returns `needs_review` when checked;
- `memdsl types` reports schema source/version, role, required fields, and
  capabilities.

## MCP server

First inspect without transport, then drive a real stdio client session:

```console
memdsl-mcp --inspect -w examples/domains/coding
memdsl-mcp                               # no workspace -> stderr + exit 2
```

For a true stdio round-trip, use `mcp.client.stdio.stdio_client` and
`ClientSession` pointed at the `memdsl-mcp` executable. Initialize, then:

1. List tools and expect `memory_types`, `memory_query`, `memory_check`,
   `memory_explain`, `memory_list`, `memory_lint`, `memory_propose`, and
   `memory_review_list`.
2. Call `memory_types`; confirm `coding.project_rule`, `coding.bug_pattern`,
   and `coding.tool_preference` include roles and capabilities.
3. Read `memdsl://types`; confirm it returns the same loaded type registry.
4. Call `memory_query`; confirm the custom project rule appears in MUST.
5. Call `memory_check`; confirm the guarded force-push candidate returns
   `block` and cites the custom type.
6. Read `memdsl://status` and `memdsl://file/{file_id}`.

## Custom-type write path (gated)

Drive the full loop in a temporary copy of a domain workspace. Never stage
proposals inside `examples/` because staging lands in `<workspace>/.memdsl/`.

1. Over stdio, call `memory_propose` with a `coding.bug_pattern` missing
   evidence. Expect `invalid` plus `missing_evidence`.
2. Propose a lint-clean `coding.bug_pattern`. Expect `pending_review`.
3. `memory_query` must not serve the pending declaration.
4. Run `memdsl review list/show/approve <ws> <id>`; approval must append the
   domain declaration to `approved.mem` (or `--into`).
5. Double approval exits 1 without duplicating source or audit events.
6. Re-query and confirm the approved custom type appears.
7. Check `.memdsl/audit.log` actions are `['propose', 'approve']`.

Approval must revalidate against the workspace's current schema registry. A
custom type accepted during proposal must not become an unknown type during
review.

## Scope probe

Run the MCP server with `--scopes read:summary`:

- `memory_query`, `memory_check`, and `memory_explain` must return MCP isError
  tool results because they require `read:search`;
- `memory_types` and the resources remain readable because they require
  `read:summary`;
- `memory_propose` remains unavailable without `write:candidate`.

## Packaging gate

```console
.venv/Scripts/python -m build
.venv/Scripts/python -m twine check dist/*
```

Install the wheel into a clean temporary virtual environment, then repeat at
least `memdsl --version`, standard lint, domain lint, `memdsl types`, custom
query, and custom compliance checks from outside the repository import path.

Finish with:

```console
git diff --check
git status --short
```

Preserve unrelated dirty or untracked files. Do not commit, push, or publish
unless the user explicitly requests that delivery step.

## Gotchas

- `init.serverInfo.version` reports the MCP SDK version, not memdsl's version.
- Workspace reload is mtime+size based; tests that mutate files should bump
  mtime with `os.utime`.
- A manifest and its schema files are part of the live workspace contract;
  copy them when creating temporary review or wheel-verification workspaces.
- The parser still calls the declaration token a `kind` internally and JSON
  retains `kind` aliases for v0.4 clients. Runtime behavior must use type
  descriptors, roles, and capabilities rather than fixed type-name branches.
