# Upgrading to memdsl 0.6

Release date: 2026-07-14

## Python compatibility

The core package and `memdsl` CLI continue to support Python 3.9+. The
optional `mcp>=1.2` SDK requires Python 3.10+, so 0.6 marks the MCP
dependency with `python_version >= "3.10"`.

- On Python 3.9, install `memdsl` or `memdsl[dev]`; the deployment is
  core-only.
- To run `memdsl-mcp` or install `memdsl[mcp]`, upgrade that environment
  to Python 3.10 or newer.
- Do not interpret a Python 3.9 base-package installation as providing the MCP
  SDK/server runtime.

## From 0.5

Pin `memdsl==0.6.0` and review these behavioral changes before enabling any
write automation.

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

The Phase 1 source line adds report-only compiler/link diagnostics without
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
there is no `.mem` syntax migration. Internal compiler/View classes are not yet
stable package-root Python API.

### Bounded Catalog navigation (Phase 2 source line)

Phase 2 adds a new surface instead of changing Map v1:

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

### Indexed query, vocabulary suggestions, and Trace (Phase 3 source line)

Phase 3 changes candidate selection internally from a full scoring scan to a
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
Catalog Phase 2 cursors/budgets, proposal/review/audit, and pending isolation
remain compatible.

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
