# Phase 6 Experimental Explicit Edge Contract

Status: experimental contract for `0.9.0.dev0`; not part of the frozen 0.8
candidate semantics.

## Pilot basis

The evidence basis is an anonymous, single-principal exploratory pilot, not a
formal empirical conclusion. The primary 40-item AI pre-review produced 5
suggested accepts, 16 suggested rejects, and 19 items still requiring a
person. Across all 100 items the counts were 15, 40, and 45.

The first completed human follow-up batch contained 10 items. Seven were
reviewable and accepted: four `supports`, one `depends_on`, one `contradicts`,
and one discovery-only `related` comparison. The other three were invalid or
unreviewable source contamination (one evidence-summary mismatch and two
runtime/command/attachment metadata captures), not Edge negatives; they are
excluded from the Edge precision denominator and belong in the host extraction
repair queue. All seven accepted comparisons had sufficient evidence. The
three typed built-in relations accounted for six authoritative Edge candidates
with independent lifecycle and standalone-management value. The `related`
comparison had neither and remains discovery-only. The decision is **ADJUST**:
explicit Edges are useful, while automatic candidate type/evidence stability
must be narrower.

The built-in relation set remains `supports`, `depends_on`, `supersedes`, and
`contradicts`. The human follow-up sample supports first-class value for
`supports`, `depends_on`, and `contradicts`; it did not validate `supersedes`,
which therefore cannot be promoted to stable from AI recommendation alone.
`related` is not a built-in authoritative relation. `refines` is not a
built-in either. A workspace may register a namespaced relation such as
`research.refines` with `stability: experimental`.
The four built-ins themselves also report `stability: experimental` in this
Phase 6 line. Built-in availability does not turn the exploratory Pilot into a
formal empirical validation claim.

Candidate generation remains a host/experiment responsibility. Core accepts
review proposals; it does not ship a private generator, infer user semantics,
approve candidates, or activate graph/authority from model output.

## Source opt-in and old-runtime fail-closed behavior

First-class Edge syntax is legal only in a workspace with this manifest:

```json
{
  "schema_version": "memdsl.workspace.v3",
  "schemas": [],
  "linking": {"visibility": "report"},
  "enforcement": {"mode": "report"},
  "features": {"explicit_edges": "experimental-v1"}
}
```

An 0.8 runtime recognizes only workspace v1/v2 and therefore rejects v3 before
loading `.mem` files. The 0.9 runtime also rejects Edge syntax in v1/v2 or a v3
manifest without the exact feature value. Empty v1/v2 workspaces retain their
existing schemas, tool set, cursor contracts, fingerprints, and envelopes.

## Record and endpoint model

```mem
relation_edge graph.alpha_supports_beta {
  declared_by: "entity:Reviewer"
  source: "fact:graph.alpha"
  target: "fact:graph.beta"
  relation: supports
  lifecycle { status: active }
  evidence {
    source: synthetic_fixture
    quote: "Alpha supports beta in this fictional example."
  }
}
```

The canonical record identity is
`relation_edge:graph.alpha_supports_beta`. `explicit_edge` is accepted as an
authoring alias but compiles to the same `relation_edge:` record namespace.
Identity depends only on the record id, never file, line, ordinal, traversal
order, or `PYTHONHASHSEED`.

The compiler keeps these identities separate:

- `record_id`: the Edge record E that owns lifecycle, evidence, and access.
- `declared_by_id`: the declaration credited with authoring the record.
- `source_id`: graph endpoint A.
- `target_id`: graph endpoint B.

Operational readability is computed before counts, filters, diagnostics, or
traversal:

```text
readable(E) AND readable(A) AND readable(B)
```

If any member is hidden, MCP list/explain/status/lint/Trace exposes neither the
Edge id nor degree, count, relation, diagnostic, or endpoint existence.

## Lifecycle and review floor

`relation_edge_event` / `explicit_edge_event` are append-only source events:

```mem
relation_edge_event event.retract_alpha_support {
  edge: "relation_edge:graph.alpha_supports_beta"
  action: retract
  event_at: "2026-07-15T00:00:00+00:00"
  lifecycle { status: active }
  evidence {
    source: synthetic_fixture
    quote: "The fictional relation was withdrawn."
  }
}
```

Actions are `confirm`, `dispute`, `retract`, and `supersede`; supersede also
requires a replacement Edge id. Events never mutate endpoint declarations.
Later reviewed events may confirm a disputed/retracted record without deleting
history.

The review-policy hard floor is not workspace-configurable:

- Both Edge spellings and both lifecycle-event spellings intersect the unified
  reserved capability set: `relation_edge`, `explicit_edge`,
  `relation_edge_event`, `explicit_edge_event`, and `edge_lifecycle`.
- Any proposal carrying any reserved Edge capability receives
  `explicit_edge_human_review_required` and cannot auto-approve.
- Workspace schemas cannot define the reserved kinds or combine any reserved
  Edge capability with `auto_approvable`.
- Policy rules naming a reserved Edge kind are invalid.
- Pending proposals are not loaded by `Workspace`, compiled, counted, traced,
  or served.

Human confirmation writes only to `edges.mem` or `*.edges.mem`. Approval
re-parses the proposal appended to the actual target document, preserving its
module/use context, and rejects a target containing ordinary declarations.
Generic approval without target-context validation fails.

## Legacy coexistence, precedence, migration, and rollback

Legacy node relations remain source-compatible and retain 0.8 authority.
When a legacy relation and an explicit Edge describe the same
`(source, relation, target)` triple, Trace emits one traversal edge with every
`origin_id` and provenance kind. Retracting the explicit record leaves the
legacy assertion intact.

Phase 6 precedence is deliberately narrow:

1. Legacy active `supersedes` continues to control declaration exclusion.
2. Active explicit Edges enter the authoritative graph only.
3. Explicit `supersedes` does **not** exclude a declaration or weaken MUST/BLOCK.
4. Candidate, private, quarantined, disputed, retracted, or superseded explicit
   Edges have no operational graph effect.

Migration is opt-in: add the v3 manifest, register extension relations, author
new Edge records, and review them. Existing legacy relations are not rewritten.
Rollback is changing/removing the v3 feature together with the Edge source on
a branch that restores a v1/v2 manifest, or appending a reviewed lifecycle
event. Approved history and audit logs are never silently rewritten.

## Authority limitation

Current strong runtime authority still comes from Source. The review/audit
store is not an input to `CompiledWorkspace`, `ResolvedView`, graph reduction,
or access authorization. A person or process with filesystem write access can
manually add an active Edge or lifecycle event to Source and bypass the
proposal workflow.

Therefore Phase 6 may be described only as a **Source-authority +
review-gated workflow contract**. It is not a digest-bound grant, authority
ledger, proof object, or non-bypassable reviewed authorization claim.

## Public-surface decision

MCP keeps the existing 11 tools and scopes:

- `memory_propose` accepts one Edge or lifecycle-event proposal.
- `memory_list(kind="relation_edge")` lists readable Edge records.
- `memory_explain("relation_edge:...")` explains one readable record.
- `memory_trace` traverses coalesced legacy/explicit graph edges.

No Edge-specific MCP tool or scope is added. This preserves old clients,
discovery budgets, scope denial, and rollback. The CLI adds experimental
`memdsl edge` commands because human confirmation needs target-context
validation and lifecycle-source construction not provided by the read-focused
MCP surface.

## Risk matrix

| Risk | Failure | Mitigation and regression gate | Residual limit |
| --- | --- | --- | --- |
| Old runtime ignores Edge semantics | New kind parsed as an ordinary declaration | v3 + exact feature opt-in; v1/v2 Edge load rejected | A tool that ignores manifests is outside contract |
| Record/endpoint confusion | Edge owner mistaken for graph source | Separate `record_id`, `declared_by_id`, `source_id`, `target_id` | Host UIs must label them correctly |
| Access side channel | Hidden Edge inferred from count/degree/diagnostic | Three-way readability before list/status/lint/explain/Trace | Raw Source readers still see authorized files |
| Unstable identity | Move/reorder/hash seed changes id | Record-id-only identity tests across moves/order/seeds | Renaming the record intentionally changes identity |
| Duplicate traversal | Legacy + explicit triple counted twice | Trace coalesces triples and retains all origins | Other projections must use the same rule when added |
| Authority regression | Explicit supersedes weakens MUST/BLOCK | Explicit relations have no node-exclusion authority in Phase 6 | Future authority opt-in requires a new contract |
| Context-free approval | Proposal passes outside final module/use | Dedicated Edge file plus final-target reparse/compile/lint | Direct Source writes remain bypassable |
| Policy downgrade | Schema/policy enables auto approval | Reserved kinds/capabilities plus immutable floor | Human confirmation quality is operational, not cryptographic |
| API sprawl | Old clients face new tools/scopes | Reuse existing 11 MCP tools; experimental CLI only | Python Edge helpers are explicitly experimental |
| Overclaim | Docs imply reviewed proof is non-bypassable | SPEC/API/tests require Source-authority limitation text | Digest-bound grants remain future work |
