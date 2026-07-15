# Upgrading to memdsl 0.9.0

## Stable 0.8 contracts to the 0.9.0 experimental Edge line

No automatic migration is performed. Existing v1/v2 workspaces retain exact
0.8 semantics. To experiment with first-class Edges, create a branch, change
the manifest to `memdsl.workspace.v3`, retain the explicit linking/enforcement
objects, and add:

```json
"features": {"explicit_edges": "experimental-v1"}
```

Author new records in `edges.mem` or `*.edges.mem`; do not rewrite legacy node
relations or approved history. Duplicate triples coexist and Trace coalesces
them while retaining all origins. Explicit `supersedes` is graph-only and does
not replace legacy node authority.

Rollback requires restoring a v1/v2 manifest and removing the v3 Edge source
from that branch, or appending reviewed lifecycle events before returning to a
v3 state. Review/audit logs are preserved. Old 0.8 runtimes fail closed on the
v3 manifest rather than silently ignoring Edge semantics.

`CompiledWorkspace` and `compile_workspace` are now package-root public
contracts for deterministic, rebuildable compilation. This is additive: code
that passes `Workspace` directly to Catalog, Query, Trace, or `resolve_view()`
continues to work. Cache/index container layout remains an implementation
detail and must not be persisted as authority.

Automatic dialect learning, automatic Edge candidate generation, inferred
authoritative edges, stable Edge promotion, and Phase 7 remain unshipped.
Host-specific extraction/sanitization, private schemas/policies/samples, and
runtime adapters are excluded rather than migration targets. See
[the Phase 6 release matrix](RELEASE_SCOPE_PHASE6.md).

Release: memdsl `0.9.0`, 2026-07-16. The previous published baseline was
0.6.0; 0.7.0 and 0.8.0 were not separately published, and the 0.8 contract is
the stable/public compatibility surface carried by 0.9.0.

The v1 compatibility/authority surfaces, Catalog v1, Trace v1, indexed
query/search trace, report diagnostics, workspace v2, exact `use`,
`dialect_mapping`, `ViewContext`/`ResolvedView`, and explicit v2 read schemas
are public 0.8 contracts. Real-workspace quarantine/strict rollout quality,
dialect-candidate learning, and host-attested principal integration remain
experimental and opt-in. `CompiledWorkspace` is public and rebuildable;
compiler/cache/index layouts, contract strings, complexity constants, and
synthetic timings remain internal.

## Python compatibility

The core package and `memdsl` CLI continue to support Python 3.9+. The
optional `mcp>=1.2` SDK requires Python 3.10+, so 0.8 keeps the MCP
dependency with `python_version >= "3.10"`.

- On Python 3.9, install `memdsl` or `memdsl[dev]`; the deployment is
  core-only.
- To run `memdsl-mcp` or install `memdsl[mcp]`, upgrade that environment
  to Python 3.10 or newer.
- Do not interpret a Python 3.9 base-package installation as providing the MCP
  SDK/server runtime.

## From 0.6 to the 0.8-compatible surface in 0.9.0

Install `memdsl==0.9.0` only after reviewing the migration mode that applies to
the workspace. Existing no-manifest and `memdsl.workspace.v1` workspaces do
not require a `.mem` rewrite and keep legacy v1 read behavior. New clients
should adopt bounded Catalog/Trace incrementally; Map v1 remains available for
the entire 0.8 line and is not eligible for removal before 1.0.

| Scenario | Upgrade and rollback contract |
| --- | --- |
| Stay on v1/no manifest | Keep existing Source; adopt Catalog/Trace without changing authority semantics |
| Opt in workspace-v2 linking | Start with `linking.visibility=report`, repair exact-use and one-module-per-file diagnostics, then let the owner choose `strict` |
| Opt in read enforcement | Start with or return to `enforcement.mode=report`; only explicit `quarantine|strict` selects v2 read envelopes |
| Roll back a 0.8 feature | Change linking/enforcement back to `report`; do not delete Source, proposals, review stores, or append-only audit history |
| Downgrade runtime to 0.6 | First remove v2-only fields or migrate to v1/no manifest and prove the workspace does not depend on strict linking/quarantine; pinning the wheel alone is unsafe because 0.6 correctly fails closed on workspace v2 |
| Retry pagination after Source change | Discard the stale cursor and restart from the first page; never combine pages across Source/View revisions |

The Phase 0A supersedes fix has no legacy opt-out: non-authoritative relations
must not hide active memory or hard constraints. Experimental rollout labels
also do not relax authorization-before-aggregation, hard-rule completeness,
repair-lane availability, or non-authoritative-edge safety.

## From 0.5

Install `memdsl==0.9.0` and review both the 0.6 write-policy changes and the 0.8
read-path changes before enabling any write automation or v2 enforcement.

### EvidencePack lifecycle authority

`memdsl.evidence_pack.v1` keeps the same schema id and additively gains a
`provisional` array.

- Only lifecycle `active` declarations enter MUST, SHOULD, CONTEXT, and
  MISSING.
- Searchable serviceable declarations with any other status enter
  PROVISIONAL.
- Candidate symbols no longer resolve aliases or activate constraints.
- Candidate hits cannot indirectly make an active constraint relevant.
- Candidate constraints no longer participate in `memdsl check` or
  `memory_check`.
- Text output now shows status, runtime role, and lifecycle explicitly.
- Memory-map items expose status and lifecycle; candidate items are
  provisional navigation entries, not active authority.

Hosts that assumed every item returned by `Workspace.active()` had
`status == "active"` must change. That method retains its compatibility
meaning of serviceable/non-excluded. Apply an explicit status check when
building an authority-bearing projection.

### Supersedes authority correctness fix

The 0.6 line now enforces the lifecycle boundary for authority-changing
`supersedes` relations. This is a correctness/security fix to the existing
PROVISIONAL contract, not a CompiledWorkspace or ResolvedView release.

- Only lifecycle `active` source declarations can create supersede authority.
- Candidate, retracted, and archived sources cannot hide an active target or
  remove it from MUST, query, or compliance.
- Full target ids must match exactly. Bare references have authority only when
  exactly one declaration has that name. Ambiguous, duplicate, dangling, and
  wrongly prefixed targets have no authority effect.
- Map, query, compliance, default list, status authority counts, and workspace
  vocabulary use the same current service set.
- `unmarked_supersede_status` is no longer emitted. Append-only correction does
  not require rewriting the old declaration to `status: superseded`.

An active, structurally valid successor with a uniquely resolved target keeps
the existing append-only behavior: it hides the old declaration from default
read surfaces while preserving source and audit history. Human approval does
not itself promote `status: candidate`; the approved successor must be active
to gain this authority.

Workspaces that relied on a non-active or ambiguous superseder changing read or
compliance results will observe a deliberate behavior correction. There is no
source migration and no legacy flag: make the reviewed successor active and
use an exact full id or unique bare reference.

### Compiled link diagnostics and report-only View

Version 0.8 adds report-only compiler/link diagnostics without
changing default Map v1, EvidencePack v1, list, or compliance authority:

- `supersedes`/`revision_of` cycles emit `revision_cycle` errors. Active cycle
  edges do not exclude their targets, so the participating declarations remain
  visible instead of all disappearing.
- Multiple valid active successors emit `supersedes_fork` warnings. No winner
  is selected; both successors remain visible.
- Ambiguous targets emit `ambiguous_relation_target`; wrong full-id prefixes
  emit `relation_target_kind_mismatch`; unknown nested relation keys emit
  `unknown_relation`. Dangling targets retain `unresolved_symbol`.
- Duplicate full ids still appear as separate source occurrences in collection
  surfaces, but single explain resolution returns ambiguity rather than the
  first occurrence.
- MCP status/lint v1 payloads add optional report-only View and diagnostic
  summaries. Clients should ignore unknown additive fields.

These diagnostics can make an already structurally broken workspace fail
`memdsl lint` where the old linter was silent. Fix the source relation or id;
there is no `.mem` syntax migration. Compiler implementation types remain
internal; only the resolved read types documented below are public.

### Bounded Catalog navigation (0.8)

Version 0.8 adds a new surface instead of changing Map v1:

- Python: `build_memory_catalog()` and `CATALOG_SCHEMA = "memdsl.catalog.v1"`;
- CLI: `memdsl catalog PATH...`;
- MCP: `memory_catalog` and `memdsl://catalog`, using
  `memdsl.mcp.catalog.v1`.

The Catalog groups the report-only service set by module and supports exact
module/type/subject/lifecycle-status filters. Defaults are `limit=20` and
`max_bytes=8192`, where bytes mean canonical compact UTF-8 JSON. Structured and
text representations are mutually exclusive, so `rendered_text` cannot bypass
the byte budget by duplicating structured items.

Catalog cursors are opaque and stateless. They bind source fingerprint,
report-only view id, normalized filters, order, and representation. A Source or
View change returns `cursor_stale`; changing request identity returns
`cursor_mismatch`. Restart at the first page rather than combining pages from
different revisions.

`workspace_vocabulary()` remains v1-compatible when its old 50-item slice is
complete. When subjects, scopes, or modules are truncated it now additively
returns `<name>_total` and `<name>_truncated`, eliminating silent truncation.

No `.mem` migration is required. `memory_map`, `memdsl://map`, CLI `memdsl map`,
and Python `build_memory_map()` remain available with v1 semantics. Update new
clients to start with Catalog; legacy clients may continue using Map. Catalog
does not alter query or compliance: hard constraints are still evaluated by the
complete authority path, independent of Catalog item/byte budgets.

### Indexed query, vocabulary suggestions, and Trace (0.8)

Version 0.8 changes candidate selection internally from a full scoring scan to a
deterministic lexical inverted index. EvidencePack remains
`memdsl.evidence_pack.v1`: existing layers, scores, tie-breaks, independent
active/provisional result limits, filter-hidden diagnostics, global MUST rules,
and compliance completeness are unchanged. `search_trace` additively exposes
View/source identity, indexes used, exact candidate-pool counts, bounded
vocabulary suggestions/retry queries, quarantine visibility, and truncation.
Clients must ignore unknown additive fields as before.

Vocabulary suggestions are folded into query misses rather than published as a
separate MCP tool. They are lexical and advisory: no Source or alias is written,
candidate symbols do not redirect, restricted vocabulary is omitted, and an
ambiguous suggestion produces no automatic retry query.

Trace is an independent new surface:

- Python: `trace_memory()`, `TRACE_SCHEMA = "memdsl.trace.v1"`,
  `TraceAnchorError`, and `TraceCursorError`;
- CLI: `memdsl trace PATH... ID [--incoming|--outgoing|--both]`;
- MCP: `memory_trace`, returning `memdsl.mcp.trace.v1` under `read:search`.

Trace defaults to depth 3, 20 nodes, 40 edges, and 8192 canonical compact UTF-8
JSON bytes. Stateless cursors bind Source/View, anchors, direction, relation
filter, depth, provisional visibility, and schema; do not combine pages after
`cursor_stale` or reuse a cursor with changed request identity. Trace is a BFS
navigation projection over explicit relations, not proof. No `.mem`, manifest,
or review-store migration is required. Map v1, query/list/explain/check v1,
Catalog cursors/budgets, proposal/review/audit, and pending isolation
remain compatible.

### Exact `use` visibility and Workspace Dialect (0.8)

No-manifest and `memdsl.workspace.v1` workspaces keep legacy global linking.
The runtime does not infer strictness merely because a file contains `use`.
To audit imports without changing links, opt in with workspace v2 report mode:

```json
{
  "schema_version": "memdsl.workspace.v2",
  "schemas": [],
  "linking": {"visibility": "report"}
}
```

After fixing every report diagnostic, an owner may explicitly change
`visibility` to `strict`. A v1 manifest that contains `linking` now fails
closed; this is intentional because older runtimes would ignore the field.
Old runtimes already reject the v2 version rather than serving it as v1.

Use is document-wide and two-pass. `use X` imports one exact module or one
exact active symbol declaration name. It does not accept wildcards, prefixes,
aliases, canonical names, or full declaration ids. Module/symbol collisions and
multiple matching symbols import nothing. Module imports expose the module;
symbol imports expose only the symbol. Use applies to relation targets, subject
symbols, and dialect targets, not opaque scope strings.

Workspace v2 allows at most one module statement per file. Report mode emits
`multiple_module_statements` with a split/keep-one migration message; strict
mode makes it an error and the file's uses do not grant strict imports. V1
keeps the historical last-module-wins behavior.

Strict mode removes unimported relation edges and subject/dialect routing
effects. Declaration/family quarantine is a separate enforcement opt-in; strict
linking alone does not enable it. Map/query/list/explain/check/compliance v1,
Catalog/Trace schemas and budgets, and review/audit behavior are unchanged
while enforcement remains `report`.

Workspaces may add a schema type with capability `dialect_mapping`. See the
fictional `examples/dialect/` workspace. Only active, unrestricted, valid,
unambiguous positive mappings route. Candidate/pending/private/ambiguous
mappings do not route. Negative precedence is deliberately unavailable and
returns `unsupported_dialect_polarity`.

A unique no-match suggestion may add `search_trace.dialect_candidate`. It is a
structured template, not a write. Add trusted evidence and submit it through
the existing proposal/review/approval path. Pending mappings remain invisible;
approval only activates routing after the declaration is appended to Source
with the correct module/use context and the workspace recompiles.

### Opt-in quarantine enforcement and ResolvedView (0.8 experimental rollout)

Version 0.8 is report-first and does not change existing workspaces. No manifest,
`memdsl.workspace.v1`, and workspace-v2 manifests with omitted or explicit
`enforcement.mode=report` continue to use the legacy/v1 read contracts.

After repairing report diagnostics and updating clients for the v2 envelopes,
an owner may opt in:

```json
{
  "schema_version": "memdsl.workspace.v2",
  "schemas": [],
  "linking": {"visibility": "report"},
  "enforcement": {"mode": "quarantine"}
}
```

`enforcement.mode` is `report`, `quarantine`, or `strict`; it is independent of
`linking.visibility`. A v1 manifest that declares `enforcement` fails closed,
as do unknown enforcement fields and modes. Do not add the field to v1 in
place.

The public Python additions are `ViewContext`, `ResolvedView`,
`resolve_view()`, `RESOLVED_VIEW_SCHEMA`, `ENFORCEMENT_TABLE`,
`build_resolved_evidence_pack()` with `RESOLVED_EVIDENCE_PACK_SCHEMA`,
`build_resolved_query/list/explain/check()`, `ResolvedCursorError`, and the
v2 Catalog/Trace schema constants. Version 0.9.0 additionally exports
the rebuildable `CompiledWorkspace` handle and `compile_workspace()` without
changing these v2 serialized contracts.

Enforced reads classify Source as authoritative, provisional, quarantined, or
excluded and use new schemas:

- `memdsl.query.v2`, `memdsl.list.v2`, `memdsl.explain.v2`, and
  `memdsl.check.v2`;
- `memdsl.catalog.v2` and `memdsl.trace.v2`;
- corresponding `memdsl.mcp.*.v2` payloads from the existing 11 MCP tools.

Query distinguishes `ok`, `no_match`, `provisional_only`, `quarantined`,
`unauthorized`, `compiler_error`, and `budget_limited`. Exact explain/Trace
also expose quarantined/excluded/unauthorized states. List cursors remain
opaque and distinguish `invalid_cursor`, `cursor_mismatch`, and
`cursor_stale`. Check returns `NEEDS_REVIEW` whenever potentially applicable
authority is unreadable, quarantined, or blocked by compiler identity errors;
it never treats an incomplete rule set as ALLOW.

Identity-critical duplicate full ids block the enforced workspace. Cycle and
fork diagnostics quarantine explicit revision families according to mode.
Use/multiple-module failures quarantine a source file. Relation, subject,
dialect, type, guard, access, and date errors are declaration-local where
possible. Health warnings such as ordinary staleness remain report-only.
Quarantined or unauthorized supersede edges have no authority, so they cannot
hide a readable target.

Map v1 cannot represent these authority lanes. In an enforced workspace,
CLI/MCP Map returns `status: unsupported_view` and directs callers to Catalog,
query, list, explain, or Trace. This is not a Map v1 schema change for legacy or
report clients.

CLI exit behavior under explicit enforcement is intentional:

- `map` returns 2 for `unsupported_view`;
- `query`, `trace`, and `explain` return 1 for a non-success read status;
- `catalog` returns 1 for cursor errors and 2 for invalid requests;
- `check` remains 0/1/2 for ALLOW/BLOCK/NEEDS_REVIEW.

Version 0.8 read identity is host-attested. Only the in-process
`MemdslMCPService` constructor can inject `principal`, `principal_trusted`, and
`principal_roles`; MCP callers cannot self-report identity in tool arguments.
An absent/untrusted principal never widens access. Filtering precedes counts,
vocabulary, diagnostics, graph traversal, and raw-file resources. The core
still does not provide an identity provider; hosts must authenticate and map
roles.

The source-edit, lint, proposal, review, and audit repair lanes remain open.
Pending proposals are still absent from durable reads, and approval affects a
View only after Source changes and recompilation. Dialect candidates remain
non-routing until the existing evidence/review/approval requirements are met.

Rollback is changing `enforcement.mode` to `report` or removing the optional
field. Source declarations, review stores, and append-only audit history do not
need reverse migration. Do not delete quarantined Source as a rollback step.

### MCP propose payload

`memory_propose` now returns `memdsl.mcp.propose.v2`. Successful payloads
include route, rule, reason codes, content/assessment hashes, and
`eligible_route`. Routes are `queued`, `auto_approved`, or `no_op`.

A configured invalid policy returns `policy_invalid`; it is not silently
treated as an ordinary queued proposal.

### Review policies are disabled by default

No existing workspace is automatically opted in. Without a valid policy and
host `write:auto`, submissions remain queued.

```console
memdsl review policy init memory
memdsl review policy show memory
memdsl review policy validate memory
```

`policy init` writes plain JSON with no comments, empty trusted clients,
empty rules, and a zero daily limit. It is intentionally disabled.

To enable narrow automation, a workspace owner must separately:

1. add `auto_approvable` to an explicit candidate assertion type;
2. configure a `memdsl.policy.v1` exact-kind rule and trusted host client;
3. set a positive finite daily limit;
4. grant the host `write:auto`;
5. provide evidence whose exact quote can be verified inside a workspace
   file, or inject an equivalent host verifier.

Question, guidance, constraint, symbol, active, global, warned, destructive,
or unverified proposals still require a person.

A valid policy without `write:auto` acts as shadow mode: writes remain
queued, while `eligible_route` and audit snapshots show what the policy
would have done.

### Python write API

`ReviewStore.create()` remains propose-only. New policy-aware hosts should
use authoritative paths with `ReviewStore.submit()`:

```python
paths = ["memory"]
workspace = Workspace.load(paths)
store = ReviewStore(staging_dir_for(paths))
policy = load_policy(store.staging_dir, registry=workspace.registry)
context = ProposalContext(client_id="mcp-client")

result = store.submit(
    paths,
    proposal_source,
    policy=policy,
    context=context,
    write_auto_granted=True,
)
```

The old preloaded-`Workspace` form remains available only when accompanied
by `workspace_paths=paths`. Paths are required for automatic reload,
fingerprint, evidence, and target-boundary checks.

New top-level APIs include the policy/context/assessment types,
`load_policy`, `verify_workspace_file_quote`, `workspace_fingerprint`,
strict audit access, digest/stats replay, and post-review recording. See
[PUBLIC_API.md](PUBLIC_API.md).

### Audit and correction

`ReviewStore.audit_entries(strict=True)` raises `AuditLogError` when audit
JSONL is damaged. This prevents automatic approval, quota checks, digest, or
stats from silently using incomplete history.

```console
memdsl review digest memory
memdsl review stats memory
memdsl review audit memory PROPOSAL_ID --verdict confirm
memdsl review audit memory PROPOSAL_ID --verdict flag \
  --reason "the cited observation was incomplete"
```

A flag is an audit result, not an in-place deletion. To confirm, revise, or
retract memory, submit a new schema-valid declaration with a new id and
`supersedes` pointing to the old declaration; add `revision_of` when
appropriate. That proposal always requires human review, and its supersede
effect begins only when the approved declaration is lifecycle `active`.

ReviewStore does not create Git commits. Do not build rollback correctness on
an assumption that one approval equals one Git commit.

## From 0.4 or earlier

Existing standard workspaces continue to load through the compatibility type
pack; no `.mem` rewrite is required. Also follow the 0.5 migration rules:

- inspect `runtime_role` and `capabilities` instead of routing on a closed
  list of domain type names;
- import stable host entry points from `memdsl`, not private modules;
- keep real identity and access-policy enforcement in the embedding host.

Do not migrate private memory, add `auto_approvable`, populate trusted
clients, or grant `write:auto` automatically during a package upgrade.
