# Changelog

## 0.6.0 - 2026-07-14

- Kept the dependency-free core on Python 3.9+ while marking the optional
  `mcp>=1.2` dependency for Python 3.10+; MCP CI remains on Python 3.12.
- Added lifecycle-safe PROVISIONAL query results while keeping
  `memdsl.evidence_pack.v1` additive: only active declarations enter
  MUST/SHOULD/CONTEXT/MISSING, candidate aliases cannot redirect queries, and
  candidate constraints no longer participate in compliance.
- Added strict `memdsl.policy.v1` review policies, explicit
  `auto_approvable` type capability, host-owned `ProposalContext`, and the
  exact-quote `workspace_file_quote` evidence verifier.
- Added `ReviewStore.submit` with default-safe queueing, shadow
  `eligible_route`, normalized-content no-op detection, deterministic
  sampling, finite daily limits, workspace reload/fingerprints, bounded
  automatic targets, and never-force automatic approval.
- Added append-only route assessment snapshots, strict audit reading,
  post-review confirm/flag events, replayable digest/stats, and route metadata
  on review list/show.
- Added `memdsl review policy init/show/validate`, `review digest`,
  `review stats`, and `review audit`. Policy initialization writes a valid
  disabled JSON template with no comments.
- Updated MCP proposing to `memdsl.mcp.propose.v2` and added non-default
  `write:auto`; configured invalid policy now fails explicitly instead of
  silently queueing.
- Defined append-only correction: promotion, revision, and retraction use a
  new human-reviewed declaration with `supersedes` and optional
  `revision_of`. ReviewStore does not depend on Git commits.

## 0.5.1 - 2026-07-13

- Added agent navigation surfaces: `memdsl map` CLI command, `memory_map`
  MCP tool, `memdsl://map` resource, and `build_memory_map` /
  `render_memory_map_text` / `workspace_vocabulary` Python exports.
- EvidencePack JSON additively exposes `search_trace` (query interpretation,
  applied filters, and matches a type/subject filter excluded).
- `memory_query` no-match responses now return the workspace vocabulary and
  adaptive retry guidance instead of a static browse hint; filter-hidden
  matches are reported under MISSING rather than failing silently.

## 0.5.0 - 2026-07-10

- Added schema-extensible domain types and stable runtime roles.
- Added `memdsl.workspace.v1` schema loading and type discovery surfaces.
- Versioned EvidencePack JSON as `memdsl.evidence_pack.v1`.
- Stabilized top-level Python exports for workspace/query and reviewed writes.
- Added push and pull-request CI on Python 3.9-3.12 for Windows and Linux.
- Preserved human-reviewed, atomic, audit-logged approval semantics.

## 0.4.0 - 2026-07-09

- Added deterministic compliance checks and benchmark support.

## 0.3.0 - 2026-07-08

- Added proposal staging, ReviewStore, audit logging, and atomic approval.

## 0.2.0 - 2026-07-08

- Added the read-only stdio MCP server and service layer.

## 0.1.0 - 2026-07-04

- Initial parser, linter, query executor, CLI, and examples.
