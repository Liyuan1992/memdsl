# Changelog

## 0.9.0.dev0 - 2026-07-15

- Experimental Phase 6 first-class explicit Edge source/model contract with
  stable identities, evidence, lifecycle events, extensible relation registry,
  compiled indexes, Trace provenance, CLI/MCP proposal surfaces, and an
  immutable human-review floor.
- The 0.8.0 authority contract remains frozen: legacy node relations keep their
  existing precedence, explicit `supersedes` does not suppress declarations,
  and review/audit state is not compiled as a digest-bound authority ledger.
- Anonymous single-principal exploratory Pilot result: ADJUST. The first human
  follow-up batch had 7 reviewable accepts (`supports` 4, `depends_on` 1,
  `contradicts` 1, discovery-only `related` 1) and 3 invalid/unreviewable host
  source-contamination rows excluded from the Edge denominator. `supersedes`
  was not human-validated in this batch; every built-in remains experimental.

## 0.8.0 - 2026-07-14

- Skipped an unpublished 0.7.0 and integrated the verified Phase -1 through
  Phase 5 source line into one 0.8.0 release candidate. Phase 6 first-class
  edges and Phase 7 cold-history/incremental compilation remain explicitly
  deferred behind evidence gates.
- Fixed the supersedes authority boundary so candidate, retracted, archived,
  ambiguous, duplicate, dangling, or wrongly prefixed source relations cannot
  hide active memory or remove an applicable hard constraint.
- Added deterministic compiled identity, semantic, lexical, module, and graph
  indexes while keeping `CompiledWorkspace`, cache formats, compiler contract
  strings, complexity constants, and synthetic timings internal.
- Added stable report-only compiler/link diagnostics for duplicate identity,
  dangling/ambiguous/wrong-prefix targets, unknown relations, revision cycles,
  supersede forks, exact-use visibility, multiple module statements, and
  workspace-owned dialect mappings.
- Added bounded Catalog v1 navigation with item/byte budgets, explicit
  truncation, structured-or-text representation, and Source/View-bound opaque
  cursors. Map v1 remains compatible throughout the 0.8 line and will not be
  reconsidered for removal before 1.0.
- Added deterministic indexed query candidate selection, additive search-trace
  diagnostics and lexical retry suggestions, plus bounded incoming/outgoing
  BFS Trace v1. Graph connectivity remains navigation over declared Source,
  not proof.
- Added `memdsl.workspace.v2`, exact module-or-symbol `use`, the generic
  `dialect_mapping` capability, public `ViewContext`/`ResolvedView`, and
  separate v2 query/list/explain/check/Catalog/Trace schemas.
- Kept quarantine and strict rollout quality experimental and explicit opt-in.
  Authorization-before-aggregation, hard-rule completeness, non-authoritative
  edges having no authority, and repair-lane availability remain mandatory
  safety invariants whenever enforcement is enabled.
- Kept dialect candidate learning advisory and review-gated, and kept
  host-attested principal integration an embedding-host contract rather than
  an identity provider or complete multi-tenant authentication system.
- Documented v1/v2 compatibility, report-first migration, feature rollback,
  and the requirement to remove v2-only semantics before downgrading a
  workspace to a 0.6 runtime.
- Expanded CI to core Python 3.9-3.12 and MCP Python 3.10/3.12 representative
  matrices, with explicit real-stdio, scope-denial, v1/v2, quarantine,
  synthetic-scale, differential, and security stop gates.
- Hardened tag publishing to install the MCP extra, run full tests and
  compile/AST gates, inspect and privacy-scan wheel/sdist members, and perform
  an outside-repository fresh-wheel CLI plus real MCP stdio smoke before upload.
- Integrated the separately verified focused paper v0.6 artifact alongside the
  practical 0.8.0 specification without treating the paper authority runtime
  as implemented. Added an explicit documentation index, software/paper
  citation and license split, P5 publication-readiness record, and required
  paper/reproducibility members in both wheel and sdist release checks.

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
