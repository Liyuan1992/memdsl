# Changelog

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
