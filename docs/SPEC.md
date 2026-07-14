# Memory DSL Specification

Version: 0.6
Status: reference specification for the `memdsl` v0.6 implementation
Release date: 2026-07-14
License: [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)

## 1. Core thesis

Memory DSL is an LLM-first, declarative source language for governed
long-term memory. Memory gets stable ids, evidence, scope, confidence,
lifecycle, access policy, relations, diagnostics, and behavioral roles so an
agent can read memory the way it reads code.

Version 0.6 retains the two-layer type architecture introduced in 0.5 and
adds lifecycle-safe provisional serving plus host-attested, risk-tiered review:

```text
core memory record     claim / evidence / scope / confidence / lifecycle /
                       access policy / relations

domain type system     coding.project_rule / assistant.commitment /
                       writing.voice_preference / any workspace-defined type
```

The core does not own a universal taxonomy of human memory. A coding agent,
personal assistant, writing system, and research tool may define different
types without changing memdsl Python code.

Domain types compile to a small stable set of **runtime roles**. Runtime roles
tell query and compliance how to behave; domain types tell users what a
memory means in their own field.

### 1.1 Python compatibility

The dependency-free core library and `memdsl` CLI support Python 3.9 and
newer. The optional MCP SDK dependency, `mcp>=1.2`, requires Python 3.10 or
newer; therefore the `mcp` extra is guarded by a
`python_version >= "3.10"` dependency marker and `memdsl-mcp` is a
Python 3.10+ surface. Python 3.9 deployments are core-only.

## 2. Non-goals

Version 0.6 deliberately does not attempt:

- Turing completeness, loops, functions, or arbitrary runtime computation.
- Replacing databases, vector stores, or knowledge graphs.
- Defining one correct ontology for all people and domains.
- Unrestricted automatic writing. Only explicitly opted-in, narrowly scoped
  candidate assertions may be policy-approved; every uncertain or
  higher-impact write remains queued for a person.
- Identity-provider integration or complete multi-tenant authorization.
  Access policy is represented, validated, and transported, while external
  runtimes remain responsible for binding identities to it.
- Pretending arbitrary natural-language constraints can be checked
  deterministically. Unexecutable constraints produce `needs_review`.

## 3. Workspace and schema model

### 3.1 Workspace

A workspace is one or more `.mem` files or directories. A directory may
contain `memdsl.json`:

```json
{
  "schema_version": "memdsl.workspace.v1",
  "schemas": [
    "coding.memschema.json",
    "company-policy.memschema.json"
  ]
}
```

Schema paths are relative to the manifest. The built-in
`memdsl.standard@1` type pack is always loaded for backward compatibility.
Workspace schemas add namespaced domain types to the same `TypeRegistry`.
`schema_version` is required. `memdsl.workspace.v1` keeps legacy global
linking. `memdsl.workspace.v2` is an explicit visibility opt-in and requires:

```json
{
  "schema_version": "memdsl.workspace.v2",
  "schemas": [],
  "linking": {"visibility": "report"}
}
```

`linking.visibility` is `report` or `strict`. A v1 manifest that declares
`linking`, an unsupported version, or unknown v2 linking semantics fails
closed. This prevents an older runtime from silently ignoring visibility
rules.

Schema parse errors, missing files, incompatible duplicate type names, and
invalid runtime roles fail closed before memory files are served.

### 3.2 Modules

A module is a local reading boundary declared in `.mem` source:

```mem
module projects.aurora
use Project.Aurora
```

Modules group declarations that answer related questions. Sources belong in
evidence; they should not become one module per chat session or day.

`use X` is document-wide and order-independent. The compiler builds all module
and symbol indexes before linking. `X` must exactly name either one module or
one active symbol declaration name. Module imports expose every declaration in
that module; symbol imports expose only that symbol. Full declaration ids,
aliases, canonical names, namespace prefixes, and wildcards are not use
targets. A module/symbol collision or multiple matching symbol occurrences is
ambiguous and imports nothing.

Use visibility applies to relation targets, subject symbols, and dialect
mapping targets. Scope strings remain domain-defined opaque applicability
tokens. In legacy v1, use is retained but global linking is unchanged. In v2
report mode, a globally resolvable but unimported reference remains linked and
emits `visibility_violation`. In v2 strict mode it emits an error and does not
enter compiled relation, subject-alias, or dialect routing. Strict linking does
not yet imply the Phase 5 declaration/family quarantine envelope.

Workspace v2 permits at most one `module` statement per source file. Report
mode emits a migration warning while preserving the legacy last-module
projection; strict mode emits an error and the file's uses do not grant strict
imports. Workspace v1 retains its existing last-module-wins behavior.

### 3.3 Schema files

A `.memschema.json` file defines domain types:

```json
{
  "name": "coding",
  "version": "1",
  "types": {
    "project_rule": {
      "runtime_role": "constraint",
      "required_fields": ["claim", "evidence", "scope"],
      "optional_fields": ["rationale", "owner"],
      "search_fields": ["rationale", "owner"],
      "capabilities": [
        "requires_evidence",
        "searchable",
        "enforceable",
        "guardable"
      ],
      "defaults": {"force": "hard", "status": "active"},
      "allowed_forces": ["hard"],
      "allow_extra_fields": false
    }
  }
}
```

The registered type name is `coding.project_rule`. Namespaces prevent two
domain packs from accidentally redefining each other's vocabulary.

Schemas may also be registered programmatically with `TypeRegistry` and
`TypeDescriptor`.

## 4. Universal memory record

A declaration is the smallest independently citable and reviewable memory:

```mem
coding.project_rule git.no_force_push {
  subject: Repository.Memdsl
  claim: "Never force-push the main branch."
  scope: repository("memdsl")
  confidence: high
  lifecycle { status: active }
  access_policy {
    readers: [owner, coding_agent]
    writers: [maintainer]
    reviewers: [maintainer]
    export: internal
  }
  evidence {
    source: AGENTS.md
    quote: "Do not force-push."
  }
}
```

Universal fields:

| Field | Meaning |
| --- | --- |
| `subject` | Stable symbol this memory is about |
| `claim` | Primary human-readable assertion or rule |
| `evidence` | Provenance and verbatim source material |
| `scope` | Where the memory applies |
| `confidence` | Confidence supplied by the author or extraction process |
| `lifecycle` | Status and temporal validity |
| `access_policy` | Readers, writers, reviewers, and export posture |
| `relations` | Typed links to other memories |
| `force` | Optional binding strength used by type schemas |
| `guard` / `exceptions` | Optional deterministic compliance data |

Type schemas may add domain fields such as `symptoms`, `fix`, `cadence`,
`counterparty`, `traits`, or `example`.

### 4.1 Evidence

Evidence is a source map, not a conclusion:

```mem
evidence {
  source: issue_tracker
  quote: "The duplicate write occurred under concurrent approval."
}
```

Types with the `requires_evidence` capability fail lint when an active
declaration lacks evidence. Candidate memories may remain unconfirmed, but
query can expose them only under PROVISIONAL.

### 4.2 Scope

Scope prevents local rules from leaking globally:

```text
global
calendar
repository("memdsl")
component("review")
relationship("Person.Editor")
publication("team_blog")
```

Scopes are domain values. The core stores and compares them without owning
their ontology.

### 4.3 Confidence

Confidence is part of the universal record. The reference lexical retriever
uses `high` as a small tie-break boost; domain runtimes may interpret richer
confidence policies behind the same record contract.

### 4.4 Lifecycle

Preferred v0.6 form:

```mem
lifecycle {
  status: active
  as_of: 2026-07-14
  valid_until: 2026-12-31
}
```

Lifecycle statuses include `candidate`, `active`, `superseded`, `retracted`,
and `archived`. For backward compatibility, top-level `status`, `as_of`, and
`valid_until` still compile into the same lifecycle record.

Types with the `temporal` capability receive staleness diagnostics.

Lifecycle status is an authority boundary. Only `active` declarations may
enter MUST, SHOULD, CONTEXT, MISSING, alias resolution, or deterministic
compliance. A non-active declaration that remains serviceable and searchable
may appear only under PROVISIONAL. In particular, a candidate constraint is
never an enforceable MUST rule, and relations declared by candidate,
retracted, or archived declarations cannot change active authority.

### 4.5 Access policy

```mem
access_policy {
  readers: [owner, coding_agent]
  writers: [owner]
  reviewers: [owner, maintainer]
  export: denied
}
```

v0.6 validates and exposes access policy through Python, JSON, CLI, and MCP.
The reference runtime does not claim to authenticate these identities; an
embedding application must bind its principals to the policy.

### 4.6 Relations

Built-in relation names:

```text
supports  refines  depends_on  part_of  supersedes
conflicts_with  derived_from  related_to  revision_of
```

`supersedes` removes the target from default read results only when the source
declaration is lifecycle `active`, the source identity and target resolve
uniquely, and the edge is not part of an active `supersedes`/`revision_of`
cycle. A full id must match exactly; a bare name resolves only when exactly one
declaration has that name. Ambiguous, duplicate, dangling, wrongly prefixed,
or cyclic targets have no authority effect. Cycle participants remain visible
and lint reports `revision_cycle` instead of silently excluding every node.

When multiple valid active declarations supersede one target, report mode does
not choose a winner: all successors remain visible and lint reports
`supersedes_fork`; the old target remains superseded. `conflicts_with` keeps
both declarations visible under CONFLICT.
`conflicts_with` keeps both declarations visible under CONFLICT.

## 5. Extensible type system

### 5.1 Runtime roles

Every memory type maps to one of five stable roles:

| Runtime role | EvidencePack behavior |
| --- | --- |
| `symbol` | Active declarations enter symbol/alias resolution; excluded from ordinary hits |
| `constraint` | Active declarations surface under MUST when applicable |
| `guidance` | Active declarations surface under SHOULD |
| `assertion` | Active declarations surface under CONTEXT |
| `question` | Active declarations surface under MISSING, never as fact |

Runtime roles are execution protocol, not a domain ontology. For example,
`coding.project_rule`, `assistant.commitment`, and `writing.taboo_topic` may
all compile to `constraint` while retaining different fields and validators.

### 5.2 Type descriptor

A `TypeDescriptor` defines:

```text
name
runtime_role
required_fields / optional_fields
claim_fields / search_fields
capabilities
defaults
allowed_forces
role_field / role_map
allow_extra_fields
schema name and version
```

`role_field` and `role_map` support types whose runtime behavior depends on a
field. The standard `preference` type, for example, maps `force: strong` to
`guidance` while advisory preferences remain assertions.

Fields referenced by `claim_fields`, `search_fields`, `defaults`, or
`role_field` are part of the descriptor's allowed field contract even when
they are not repeated in `optional_fields`.

### 5.3 Capabilities

Capabilities recognized by the reference runtime include:

| Capability | Effect |
| --- | --- |
| `symbol` | Defines canonical symbols and aliases |
| `searchable` | Eligible for query scoring |
| `requires_evidence` | Active declarations need evidence |
| `temporal` | Lifecycle receives staleness checks |
| `enforceable` | Constraint may enter deterministic compliance |
| `guardable` | Type may declare a `guard` block |
| `exceptions_recommended` | Linter asks for explicit exceptions |
| `auto_approvable` | Type explicitly permits policy consideration; the v0.6 safety floor still restricts automatic approval to candidate assertions |

Unknown capabilities may be carried for external runtimes. Core behavior is
only attached to capabilities the runtime understands.

No standard compatibility type is automatically trusted merely because of
its name. A workspace schema must explicitly add `auto_approvable`, and a
review policy must separately name that exact kind before it can be considered
for automatic approval.

### 5.4 Standard compatibility pack

Pre-v0.5 workspaces continue to load unchanged through
`memdsl.standard@1`:

| Standard type | Runtime role |
| --- | --- |
| `entity` | symbol |
| `fact`, `decision`, `state`, `goal` | assertion |
| `preference` | assertion or guidance according to force |
| `principle` | guidance |
| `boundary` | constraint |
| `open_issue` | question |

Other previously reserved standard names also remain generic assertions.
There is no implicit `User` symbol in v0.6; a workspace must declare every
subject it references.

## 6. DSL grammar

```text
document    := (module_stmt | use_stmt | declaration)*
module_stmt := 'module' DOTTED_NAME
use_stmt    := 'use' DOTTED_NAME
declaration := TYPE MEMORY_NAME block
block       := '{' entry* '}'
entry       := FIELD ':' value | FIELD block
value       := STRING | ATOM | list
list        := '[' (value (',' value)*)? ']'
```

`TYPE` may be a standard name (`boundary`) or a namespaced domain type
(`coding.project_rule`). Parsing accepts the syntax; linting fails closed if
no loaded schema defines the type.

Nested maps such as `evidence`, `lifecycle`, `access_policy`, `relations`,
and `guard` are single-level blocks in v0.6.

## 7. Querying: EvidencePack

A query returns a layered pack:

```text
MUST      applicable constraint memories
SHOULD    guidance memories
CONTEXT   scored assertion memories
PROVISIONAL scored non-active searchable memories
CONFLICT  declared conflicts among selected memories
MISSING   question memories and explicit gaps
```

Layering depends on runtime role and lifecycle, never on a hard-coded domain
type name. MUST, SHOULD, CONTEXT, and MISSING accept only `active`
declarations. Superseded, retracted, and archived memories do not surface by
default. Candidate symbols cannot resolve aliases or make an active constraint
applicable; relevance for active semantic layers is computed only from active
hits.
Every item carries its id, type, runtime role, capabilities, evidence,
lifecycle, confidence, and access policy.

The stable JSON envelope remains `memdsl.evidence_pack.v1`. Version 0.6
additively adds `provisional`; scored CONTEXT and PROVISIONAL entries expose
`score` and `matched_terms`. Every declaration item includes `status`,
`runtime_role`, and lifecycle, and text rendering makes those fields visible.
Hosts may add their own runtime projection fields, but must preserve the
layers and declaration ids.

The reference scorer remains lexical plus alias resolution, but Phase 3 uses
a deterministic inverted term index to select scoring candidates. The
compatibility scorer, tie-break, authority lanes, active/provisional limits,
global-constraint handling, and filter-hidden diagnostics remain unchanged.
Retrieval backends may be replaced without changing EvidencePack semantics.

### 7.1 Retry guidance: search_trace

A miss must be a retry signal, not a dead end. Serialized packs additively
expose `search_trace`, which records how the query was interpreted and what
the filters excluded:

```text
query_terms                 terms after stopword stripping
matched_aliases             alias -> resolved symbols found in the query
filters                     the type/subject filters that were applied
view_id / source_fingerprint report-only checkout identity
indexes_used                candidate indexes used by the request
candidate_pool_total        nonzero lexical candidates before filters
candidate_pool_after_filters nonzero candidates after filters
candidates_considered       legacy-compatible searchable count after filtering
hits                        declarations that scored above zero
excluded_by_filters         matching declarations a filter hid (up to 5)
excluded_by_filters_total   total count of filter-hidden matches
quarantined_matches         permission-safe quarantined matches (empty in report mode)
vocabulary_suggestions      bounded lexical corrections with source/reason
retry_queries               deterministic safe retry queries
dialect_candidate           optional non-writing proposal template
truncated                   whether a trace sub-list or result limit truncated detail
```

When a filter hides a matching declaration, the pack also reports it under
MISSING instead of returning a silent no-match. Consumers should treat a
no-match with non-empty `excluded_by_filters` as "the memory exists; the
filter hid it".

PROVISIONAL hits do not suppress active-gap diagnostics. If only provisional
declarations match, MISSING still reports that no active declaration matched;
filter-hidden counts and wording likewise refer explicitly to active
declarations.

When no active scored declaration matches, Phase 3 may add pure-lexical
vocabulary suggestions from active, unrestricted workspace symbols, aliases,
types, and modules. Suggestions explain the query term, proposed phrase,
category, reason, and any symbol ambiguity. They do not edit Source, create an
alias, or redirect a query automatically. Candidate symbols and declarations
with a non-empty `access_policy` do not enter this suggestion vocabulary;
ambiguous suggestions never produce an automatic `retry_query`.

When exactly one loaded schema type declares the `dialect_mapping` capability
and a no-match suggestion uniquely identifies a symbol, search trace may add a
structured `dialect_candidate`. It is an advisory template only. The host must
add trusted evidence and submit it through the normal proposal/review/approval
lane; pending mappings never route.

### 7.2 Workspace Dialect

A workspace may define a generic mapping type with the `dialect_mapping`
capability. The core does not reserve a type name. A mapping uses `target`,
`phrases`, optional `polarity` (default `positive`), evidence, and lifecycle.
The fictional example lives under `examples/dialect/`.

Only an active, unrestricted, structurally valid positive mapping whose target
is one unique active, unrestricted, visible symbol can extend alias routing.
Candidate, pending, retracted, archived, restricted, invalid, or ambiguous
mappings do not route and do not enter the new suggestion vocabulary. If a
phrase maps to multiple symbols, or conflicts with an existing active alias,
lint reports `ambiguous_dialect_mapping` and the new mapping does not redirect.

Negative mapping precedence is not defined in Phase 4. A non-positive
`polarity` reports `unsupported_dialect_polarity` and has no routing effect.

### 7.3 Navigation: bounded Catalog, legacy memory map, and vocabulary

Agent-driven reading starts with the bounded Catalog. `build_memory_catalog`
returns `memdsl.catalog.v1`; CLI `memdsl catalog` uses the same schema and MCP
`memory_catalog` / `memdsl://catalog` return `memdsl.mcp.catalog.v1`.

Catalog pages summarize modules instead of enumerating declarations. They can
filter by exact module, memory type, subject, and lifecycle status. Each module
item contains exact declaration/authority counts plus bounded type,
runtime-role, status, and subject dimensions. The response always carries:

```text
returned_items / available_items
truncated / next_cursor / completeness
view_id / source_fingerprint
representation = structured | text
```

The default page uses `limit=20` and `max_bytes=8192`. `max_bytes` is measured
over canonical compact UTF-8 JSON, including `rendered_text` in text mode.
Structured mode returns `items` and no rendered text; text mode returns
`rendered_text` and no duplicate structured items. Module/dimension labels and
dimension counts are independently bounded, so a declaration with very large
aliases or lifecycle metadata cannot bypass the page budget.

The opaque stateless cursor binds the source fingerprint, report-only view id,
normalized filters, order, representation, schema, and Catalog contract.
Changing Source/View returns `cursor_stale`; changing filters, order, or
representation returns `cursor_mismatch`. Page totals are exact because the
reference implementation performs one deterministic pass over the report-only
service set; they are not a promise of sublinear total-count cost.

Catalog vocabulary dimensions always expose `<name>_total` and
`<name>_truncated`. The legacy `workspace_vocabulary` v1 shape remains
unchanged when complete, but additively exposes matching metadata whenever its
50-item compatibility slice truncates subjects, scopes, or modules.

`build_memory_map`, CLI `memdsl map`, MCP `memory_map`, and `memdsl://map`
remain the legacy v1 full navigation surface. They still enumerate the shared
current service set after lifecycle-safe supersede exclusion (id, type,
runtime role, lifecycle status, subject, scope, truncated claim) and include
workspace vocabulary with aliases. Candidate entries are visibly provisional;
they are not active authority and their relations cannot hide active entries.
Map and Catalog are navigation projections, never citation sources.

### 7.4 Deterministic bounded Trace

`trace_memory()` and CLI `memdsl trace` return `memdsl.trace.v1`; MCP
`memory_trace` returns `memdsl.mcp.trace.v1`. Trace accepts one or more anchors,
`direction = outgoing | incoming | both`, an optional exact relation filter,
maximum depth, node/edge/byte budgets, an opaque cursor, and an opt-in
`include_provisional` flag.

The projection is a deterministic BFS tree over resolved explicit compiler
edges. Each node is emitted once with its depth, parent edge, lifecycle lane,
type, role, module, and subject. Non-tree edges are emitted separately as
`back_edges` (including cycle-closing edges) or `cross_edges`. Adjacency order
is stable and independent of filesystem order or Python hash seed.

Defaults are depth 3, 20 nodes, 40 edges, and 8192 canonical compact UTF-8 JSON
bytes. `returned_nodes`, `returned_edges`, exact available counts,
`truncated`, `completeness`, and `next_cursor` are explicit. The stateless
cursor binds source fingerprint, view id, anchors, direction, relation filter,
depth, provisional visibility, schema, and Trace contract. Source/View changes
return `cursor_stale`; request identity changes return `cursor_mismatch`.

Trace v1 omits declarations with non-empty `access_policy` because Phase 3 has
no trusted principal API. Provisional nodes are omitted unless explicitly
requested and remain labeled provisional. Report mode has no quarantined nodes;
Phase 5 owns enforcement and permission-aware quarantine metadata. Trace
connectivity records what Source declares; it is not proof of a natural-
language conclusion and is never a replacement for evidence or explain.

## 8. CompliancePack

`memdsl check` and MCP `memory_check` preflight a candidate against
applicable active `constraint` memories. Candidate constraints are excluded
before guard evaluation and cannot produce ALLOW, BLOCK, or NEEDS_REVIEW.

```text
verdict                  allow | block | needs_review
applicable_constraints   constraint memories considered
violations               failed guards, cited by memory id and type
asserted_exceptions      exception names supplied by the caller
exceptions_applied       declared exceptions that actually fired
unknowns                 constraints that cannot be checked deterministically
```

Deterministic execution requires both `enforceable` and `guardable`
capabilities. A constraint without those capabilities remains a MUST item but
produces `needs_review` rather than being ignored.

Supported guard fields:

| Field | Meaning |
| --- | --- |
| `when_any` | Trigger when a phrase occurs in task or candidate |
| `deny_any` | Violate when a phrase occurs in candidate |
| `deny_regex` | Violate when a regex matches candidate |
| `require_any` | Violate unless one phrase occurs in candidate |
| `require_regex` | Violate unless one regex matches candidate |

`applicable_must` and `boundary_id` remain deprecated JSON aliases for v0.4
clients. New clients should use generic memory ids and
`applicable_constraints`.

## 9. Diagnostics

Universal diagnostics include:

| Code | Meaning |
| --- | --- |
| `unknown_memory_type` | No loaded schema defines the declaration type |
| `missing_required_field` | Type schema requires a missing field |
| `unknown_type_field` | Strict type schema rejects a field |
| `missing_evidence` | Active evidence-required memory lacks evidence |
| `unresolved_symbol` | Subject or relation target is unknown |
| `ambiguous_relation_target` | A bare or duplicate relation target has multiple source occurrences |
| `relation_target_kind_mismatch` | A full relation id uses the wrong type prefix; no suffix fallback occurs |
| `unknown_relation` | A nested `relations` key is not registered |
| `revision_cycle` | A resolved `supersedes`/`revision_of` edge participates in a cycle |
| `supersedes_fork` | Multiple active successors supersede one target (report-mode warning) |
| `duplicate_declaration_id` | Stable id is declared twice |
| `duplicate_declaration` | Type/subject/scope/claim duplicate another memory |
| `type_force_mismatch` | Force is outside the type descriptor policy |
| `stale_memory` | Temporal memory is expired, old, or undated |
| `invalid_guard_regex` | Guard regex is invalid |
| `invalid_access_policy` | Access policy is not a nested map |
| `module_too_large` | Module exceeds the reading budget |

The standard compatibility pack may preserve older diagnostic aliases such
as `boundary_without_exception` and `stale_state`.

The former `unmarked_supersede_status` warning is not emitted. Append-only
correction intentionally leaves the old declaration unchanged; currentness is
derived from an authoritative incoming `supersedes` relation rather than an
in-place `status: superseded` rewrite.

Compiler/link diagnostic codes are stable; human-readable messages may become
clearer. `revision_cycle`, ambiguous/wrong-prefix/unknown relation targets, and
duplicate ids are errors. `supersedes_fork` is a warning in report mode because
quarantine/strict pollution scope is not yet a public default.

Duplicate ids remain visible as source occurrences in collection surfaces, but
single-declaration explain resolution fails with an ambiguous result instead
of selecting the first file occurrence. MCP `status.v1` and `lint.v1` may add
report-only View/diagnostic summaries; v1 map/query authority and payloads do
not change.

## 10. Gated writing and review

MCP `memory_propose` accepts exactly one declaration and validates it against
the live workspace's `TypeRegistry`. A proposal using an unknown domain type
or missing a schema-required field fails before staging.

Pending proposals live under `.memdsl/proposals/` and are never served as
memory. Version 0.6 adds deterministic routing after validation:

| Result | Meaning |
| --- | --- |
| `invalid` | Parse, schema, or lint failure; no proposal is staged |
| `no_op` | Canonically identical pending or approved content already exists |
| `queued` | A person must approve or reject the staged proposal |
| `auto_approved` | A narrowly eligible candidate assertion passed every policy and host-attestation check |

### 10.1 Trust boundary

Proposal text is never a trust root. The host supplies a `ProposalContext`
containing an authenticated `client_id` and an optional
`EvidenceVerification`. Proposal headers and MCP tool arguments cannot
assert trusted identity, scopes, or verified evidence.

The built-in `workspace_file_quote` verifier resolves `evidence.source`
inside the explicitly loaded workspace roots, rejects symlinks and path
escapes, reads an ordinary UTF-8 file, and requires the declared quote to
occur exactly. Audit records store source, quote, and complete-evidence
digests, never the source contents or quote text. An embedding host may inject
another verifier; verifier failure or absence can only route to a person.

### 10.2 Non-configurable safety floor

Version 0.6 can automatically approve only a declaration that satisfies all
of these conditions:

- runtime role is `assertion`;
- lifecycle status is `candidate`;
- the type descriptor explicitly has `auto_approvable`;
- scope is non-empty and not `global`;
- lint produced no warnings;
- access policy is empty and force is neither `hard` nor `strong`;
- `supersedes`, `revision_of`, and `conflicts_with` are absent;
- host client is trusted and the evidence attestation matches the current
  declaration evidence.

`question`, `guidance`, `constraint`, `symbol`, unknown types, active
declarations, and every uncertain case are always queued. Policy rules can
only narrow this floor.

### 10.3 ReviewPolicy and deployment keys

The optional strict JSON policy is `<staging>/policy.json`, versioned as
`memdsl.policy.v1`. It names a workspace-contained `.mem` target, stable
sampling percentage, finite UTC daily limit, trusted clients, and ordered
rules. Every automatic rule must name at least one exact kind. Unknown fields,
unknown kinds, invalid targets, malformed JSON, and unsupported versions raise
`PolicyError`; a configured invalid policy is never silently treated as
ordinary queueing.

`memdsl review policy init` writes a valid disabled template:
`trusted_clients` and `rules` are empty and
`max_auto_approve_per_day` is zero. Enabling automation requires all of:

1. a schema type with `auto_approvable`;
2. an exact-kind rule and trusted host client in the policy;
3. a positive daily limit;
4. host deployment scope `write:auto`, which is not a default MCP scope.

A valid policy without `write:auto` runs in shadow posture: the proposal is
queued, while audit retains both the eligible policy assessment and the
effective `write_auto_not_granted` result.

### 10.4 Determinism, concurrency, and audit

Canonical declaration JSON produces a stable `content_hash`. Duplicate
pending/approved content returns `no_op`, and sampling uses
`content_hash + policy_hash`, not a random proposal id, so retries cannot
evade the human sample. Actual automatic approvals are bounded by the policy's
UTC daily limit.

`ReviewStore.submit` records `propose` and a complete `route` assessment
snapshot for every valid new proposal. Before automatic approval it reloads
the authoritative workspace paths, revalidates the declaration and evidence,
checks a content fingerprint covering memory, manifest, and schema files, and
rechecks the daily limit under the review lock. The automatic target must be a
non-symlink `.mem` file inside the primary workspace root and outside
`.memdsl`. Automatic approval never uses `force`.

Approval atomically updates the target source, appends an audit event, and
updates proposal state. Locks and idempotent markers make interrupted approval
safe to retry. `audit_entries(strict=True)` raises `AuditLogError` on a
malformed line; corrupted audit cannot silently undercount quota or quality
statistics.

`memdsl review digest` summarizes pending, sampled, auto-approved, unaudited,
and flagged writes. `review stats` replays historical routing snapshots
without consulting the current registry. The `review audit` command with
`--verdict confirm` or `--verdict flag` appends a human post-review result
but never edits memory source.

### 10.5 Append-only correction

ReviewStore does not create Git commits and does not physically delete or
rewrite approved declarations. Promotion, revision, and retraction use a new,
schema-valid declaration proposal with a new id and `supersedes` (optionally
also `revision_of`) pointing at the old declaration. Those relations always
require human review. Once approved, an `active` successor with a uniquely
resolved target hides the old declaration from default read surfaces while
preserving source and audit history. Approval does not silently promote a
candidate lifecycle status, so a candidate successor remains PROVISIONAL and
has no supersede authority. A host may add Git integration, but core
correctness does not depend on Git.

The supported top-level Python surface includes `ReviewStore`, `Proposal`,
`ValidationResult`, `AuditLogError`, `ReviewPolicy`, `PolicyRule`,
`ProposalContext`, `EvidenceVerification`, `RoutingAssessment`,
`load_policy`, `verify_workspace_file_quote`, `workspace_fingerprint`,
`review_digest`, `review_stats`, `record_post_review`, and
`staging_dir_for`.

## 11. Type discovery surfaces

Loaded types are discoverable through:

```text
Python       Workspace.registry / TypeRegistry
CLI          memdsl types <workspace> [--json]
MCP tool     memory_types
MCP resource memdsl://types
```

The memory itself is navigable through:

```text
Python       build_memory_catalog / build_memory_map / workspace_vocabulary / trace_memory
CLI          memdsl catalog <workspace> [...] / memdsl map <workspace> [--json]
             memdsl trace <workspace> <anchor> [--incoming|--outgoing|--both]
MCP tool     memory_catalog / memory_map / memory_trace
MCP resource memdsl://catalog / memdsl://map
```

Agents should inspect loaded types before proposing memory instead of
inventing a standard taxonomy, and read the bounded Catalog at session start
so retrieval starts from knowledge of what exists rather than from a blind
similarity guess. Map v1 remains available for older clients.

## 12. Compliance evaluation

JSONL compliance cases can reference any type that compiles to
`constraint`. `memdsl eval compliance` compares:

```text
no_memory
flat_context
evidence_pack
compliance_gate
```

Reports include verdict accuracy, unsafe-allow rate, false-block rate,
constraint recall, citation accuracy, and per-case results. The v0.4
`boundary_recall` metric remains as a compatibility alias.

## 13. Design principles

- The core owns memory record semantics, not a universal human ontology.
- Domain types compile to stable runtime roles and capabilities.
- Users learn their domain vocabulary, not the library author's worldview.
- Evidence is a source map.
- Scope prevents behavioral leakage.
- Lifecycle and access policy belong to every domain.
- Unknown types and incompatible schemas fail closed.
- Standard types are a compatibility pack, not the only allowed worldview.
- Types are discoverable and versioned.
- Vector search is a backend, not the memory model.
- Candidate memory is visible only as PROVISIONAL and never acquires active
  behavioral authority; its relations cannot remove active authority either.
- Automation requires independently attested identity and evidence; proposal
  content cannot attest to itself.
- Source declarations and append-only review history are authoritative.
  Corrections supersede prior declarations instead of silently rewriting them.
