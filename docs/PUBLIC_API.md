# memdsl 0.6 Public Python API

Release date: 2026-07-14

The dependency-free core API supports Python 3.9+. The optional
`memdsl[mcp]` extra and `memdsl-mcp` server require Python 3.10+ because
`mcp>=1.2` does. In-process Python 3.9 hosts can use every API documented
below except the MCP SDK/server surface.

Import stable entry points from the package root:

```python
from memdsl import (
    AUTO_APPROVABLE_CAPABILITY,
    CATALOG_SCHEMA,
    EVIDENCE_PACK_SCHEMA,
    POLICY_VERSION,
    AuditLogError,
    CatalogCursorError,
    CompliancePack,
    Declaration,
    EvidencePack,
    EvidenceVerification,
    ParseError,
    PolicyError,
    PolicyRule,
    Proposal,
    ProposalContext,
    ReviewPolicy,
    ReviewStore,
    RoutingAssessment,
    RoutingDecision,
    SchemaError,
    TypeDescriptor,
    TypeRegistry,
    TRACE_SCHEMA,
    TraceAnchorError,
    TraceCursorError,
    ValidationResult,
    Workspace,
    build_evidence_pack,
    build_memory_catalog,
    build_memory_map,
    check_compliance,
    declaration_content_hash,
    lint,
    load_policy,
    parse_file,
    parse_text,
    proposal_review_metadata,
    record_post_review,
    render_memory_map_text,
    review_digest,
    review_stats,
    staging_dir_for,
    trace_memory,
    verify_workspace_file_quote,
    workspace_fingerprint,
    workspace_vocabulary,
)
```

## Read path

```python
workspace = Workspace.load(["memory"])
diagnostics = lint(workspace)
pack = build_evidence_pack(workspace, "project release rules")
payload = pack.as_dict()

assert payload["schema_version"] == "memdsl.evidence_pack.v1"
active_context = payload["context"]
candidate_hits = payload["provisional"]
```

The schema id remains `memdsl.evidence_pack.v1`. Version 0.6 additively
adds `provisional`. Only active declarations enter `must`, `should`,
`context`, and `missing`; scored non-active searchable hits enter
`provisional` with `score`, `matched_terms`, `status`,
`runtime_role`, and lifecycle.

Candidate symbols cannot affect alias resolution, and candidate constraints
cannot enter MUST or deterministic compliance. Candidate, retracted, and
archived declarations also cannot use `supersedes` to hide an active target.
The v0.6 read functions share one narrow authority resolver: full ids match
exactly, bare references must be unique, and only an active source relation can
exclude the resolved target. Active `supersedes`/`revision_of` cycle edges do
not apply exclusion authority; cycle participants remain visible and lint
reports `revision_cycle`. A report-mode fork never selects one successor.

Serialized packs also expose `search_trace` so a miss carries enough
information to retry instead of looking like absence. Phase 3 additively adds
the report-only `view_id`/`source_fingerprint`, `indexes_used`, exact lexical
candidate-pool counts, permission-safe `quarantined_matches`, bounded
`vocabulary_suggestions`, deterministic `retry_queries`, and `truncated`.
The legacy trace fields and EvidencePack authority layers are unchanged.

Vocabulary suggestions are lexical hints only. They use active symbols and
unrestricted vocabulary, never write aliases, never route through candidate
symbols, and do not auto-retry an ambiguous phrase.

`lint(workspace)` also reports deterministic compiler/link codes:
`ambiguous_relation_target`, `relation_target_kind_mismatch`,
`unknown_relation`, `revision_cycle`, and `supersedes_fork`, while dangling
targets retain the existing `unresolved_symbol` code. Codes are stable; message
wording is not a parsing contract. `supersedes_fork` is a report-mode warning;
the other new structural diagnostics are errors.

The internal `memdsl.compiler.CompiledWorkspace` and
`memdsl.view.ViewContext`/`ResolvedView` types are implementation modules, not
package-root exports or stable public Python API in this phase.

## Navigation path

```python
catalog = build_memory_catalog(
    workspace,
    module="projects.aurora",
    types=["decision", "state"],
    statuses=["active"],
    limit=20,
    max_bytes=8192,
    representation="structured",
)
assert catalog["schema_version"] == CATALOG_SCHEMA

while catalog["next_cursor"]:
    catalog = build_memory_catalog(
        workspace,
        module="projects.aurora",
        types=["decision", "state"],
        statuses=["active"],
        limit=20,
        max_bytes=8192,
        cursor=catalog["next_cursor"],
        representation="structured",
    )

map_data = build_memory_map(workspace)
text = render_memory_map_text(map_data)
vocab = workspace_vocabulary(workspace)

trace = trace_memory(
    workspace,
    ["decision:aurora.pricing_free_tier"],
    direction="both",
    relations=["supports", "revision_of"],
    max_depth=2,
    max_nodes=20,
    max_edges=40,
    max_bytes=8192,
)
assert trace["schema_version"] == TRACE_SCHEMA
```

`build_memory_catalog()` is the Phase 2 bounded navigation API. It returns
module summaries rather than declarations, supports module/type/subject/status
filters, and enforces both item and canonical compact UTF-8 JSON byte budgets.
The default is 20 items / 8192 bytes. Use `representation="structured"` for
`items`, or `representation="text"` for `rendered_text`; the two forms are not
duplicated in one payload.

Catalog cursors are opaque. Reuse them only with the same filters, order, and
representation. `CatalogCursorError.code` is `invalid_cursor`,
`cursor_mismatch`, or `cursor_stale`; stale means the source fingerprint or
report-only view id changed and pagination must restart. `CompiledWorkspace`,
`ViewContext`, and `ResolvedView` remain internal even though Catalog payloads
carry their stable report metadata.

The map is a navigation projection. It includes the shared current service set
after lifecycle-safe supersede exclusion and makes lifecycle status explicit;
candidate entries are provisional, not active authority. `workspace_vocabulary`
uses the same set and now exposes total/truncated metadata when its compatibility
slice is actually incomplete. Items carry no evidence and claims are truncated,
so neither Map nor Catalog is a citation source. Map v1 remains available for
existing clients and is not changed into Catalog.

`trace_memory()` is the Phase 3 bounded graph-navigation API. It emits a
deterministic BFS tree plus explicit back/cycle/cross edges and supports
incoming, outgoing, or bidirectional traversal, exact relation filters,
depth/node/edge/byte budgets, stateless pagination, and opt-in provisional
visibility. Defaults are depth 3, 20 nodes, 40 edges, and 8192 canonical compact
UTF-8 JSON bytes. `TraceCursorError.code` is `invalid_cursor`,
`cursor_mismatch`, or `cursor_stale`; `TraceAnchorError.code` distinguishes
missing, ambiguous, unauthorized, and non-serviceable anchors. Trace omits
declarations with non-empty access policy in Phase 3 and never represents graph
connectivity as proof. `CompiledWorkspace`, `ViewContext`, and `ResolvedView`
remain internal rather than new package-root types.

## Governed write path

`ReviewStore.create()` remains the compatibility propose-only entry point:

```python
paths = ["memory"]
workspace = Workspace.load(paths)
store = ReviewStore(staging_dir_for(paths))

queued = store.create(
    workspace,
    proposal_source,
    client="host-display-name",
)
```

For policy routing, use `submit()` with authoritative paths:

```python
policy = load_policy(store.staging_dir, registry=workspace.registry)
assert policy is not None
context = ProposalContext(client_id="mcp-client")

result = store.submit(
    paths,
    proposal_source,
    reason="captured from a verified workspace document",
    policy=policy,
    context=context,
    write_auto_granted=True,
)

assert result["status"] in {
    "pending_review",
    "auto_approved",
    "no_op",
    "invalid",
}
```

`ProposalContext.client_id` is host-authenticated identity. Proposal source,
proposal headers, and tool arguments cannot set it. If the context has no
evidence attestation, `submit()` uses the built-in
`workspace_file_quote` verifier against the authoritative workspace paths.
The declaration's `evidence.source` must resolve to a non-symlink UTF-8 file
inside a workspace root and its `evidence.quote` must occur exactly.

Automatic approval additionally requires:

- a valid `memdsl.policy.v1` policy;
- host `write:auto` authority;
- an exact-kind rule and trusted client;
- a candidate assertion type with `auto_approvable`;
- narrow scope, zero warnings, verified evidence, and no high-risk fields;
- a positive, unexhausted daily limit and a non-sampled route.

With no policy, no `write:auto`, or any uncertainty, `submit()` stages the
proposal for a person and records a full route assessment. A valid policy
without `write:auto` is useful as shadow mode: `eligible_route` records
what the policy would have done.

`submit()` reloads and fingerprints authoritative paths before automatic
approval. Its policy target must be a non-symlink `.mem` file inside the
primary workspace root and outside `.memdsl`; the automatic path never uses
`force`.

Compatibility overload:

```python
result = store.submit(
    workspace,
    proposal_source,
    workspace_paths=paths,
    policy=policy,
    context=context,
    write_auto_granted=True,
)
```

The paths form is preferred because automatic approval must be able to reload
current source and schema state.

## In-process MCP host attestation

`MemdslMCPService` exposes two host-only injection points:

```python
from typing import Callable, Mapping, Optional, Sequence

from memdsl import EvidenceVerification, ProposalContext
from memdsl.mcp_service import MemdslMCPService


TRUSTED_SOURCES = {
    "ticket://fictional/42": "The fictional build is green.",
}


def context_factory(client_id: str) -> ProposalContext:
    # Authentication/configuration happened in the host, outside the MCP tool.
    if client_id != "mcp:fictional-collector":
        raise ValueError("unrecognized host client")
    return ProposalContext(client_id=client_id)


def evidence_verifier(
    evidence: Optional[Mapping[str, object]],
    workspace_paths: Sequence[str],
) -> EvidenceVerification:
    if not isinstance(evidence, Mapping):
        return EvidenceVerification.unverified("missing_evidence")
    source = evidence.get("source")
    quote = evidence.get("quote")
    content = TRUSTED_SOURCES.get(source) if isinstance(source, str) else None
    if not isinstance(quote, str) or content is None or quote not in content:
        return EvidenceVerification.unverified(
            "host_source_or_quote_not_verified",
            verifier="fictional_ticket_connector",
            evidence=evidence,
            source_content=content,
        )
    return EvidenceVerification.verified_content(
        verifier="fictional_ticket_connector",
        evidence=evidence,
        source_content=content,
    )


service = MemdslMCPService(
    ["memory"],
    scopes="read:summary,read:search,write:candidate,write:auto",
    client_name="mcp:fictional-collector",
    context_factory=context_factory,
    evidence_verifier=evidence_verifier,
)
```

The public callable contracts are:

```python
EvidenceVerifier = Callable[
    [Optional[Mapping[str, object]], Sequence[str]],
    EvidenceVerification,
]
ProposalContextFactory = Callable[[str], ProposalContext]
```

The default `evidence_verifier` is `workspace_file_quote`.
`context_factory=None` creates a host-owned context from the configured
`client_name`. A missing verifier, exception, or return value that is not an
`EvidenceVerification` becomes an unverified proof and can only queue.
Likewise, an exception or invalid value from `context_factory` fails closed.

If a context factory returns a `ProposalContext` that already contains
`evidence_verification`, the service may use that attestation for routing, but
automatic approval still requires a matching `evidence_verifier` callback.
Inside the approval lock, memdsl reloads the authoritative workspace, parses
the fresh declaration, invokes the callback again, and requires `verified`,
`verifier`, `source_digest`, `quote_digest`, and `evidence_digest` to match the
routing attestation exactly. A missing or failing callback, an unverified or
invalid return value, or any digest change falls back to the human queue before
the target file is written. The default `workspace_file_quote` proof follows
the same two-pass rule.

The MCP `memory_propose` tool does not accept client identity, scopes,
`verified`, verifier ids, or any other attestation field. Tool callers cannot
select these injection points or promote proposal content into trusted
context; only the process that constructs `MemdslMCPService` can do so.

## Policy helpers

```python
target = store.validate_policy_target(policy, paths)
fingerprint = workspace_fingerprint(paths, workspace=workspace)
declaration = workspace.by_id("example.observation:phase")
assert declaration is not None
proof = verify_workspace_file_quote(declaration.evidence, paths)
attested_context = context.with_evidence(proof)
assessment = policy.assess(
    declaration,
    warnings_count=0,
    context=attested_context,
    auto_approved_today=0,
    write_auto_granted=True,
)
```

`ReviewPolicy.assess()` is deterministic and returns a
`RoutingAssessment` with an `assessment_hash`, normalized
`content_hash`, rule, reason codes, input snapshot, tier, and optional sample
bucket. Policy rules can only narrow the built-in safety floor.

`load_policy()` returns `None` only when no policy file exists. Malformed
or unsafe configured policy raises `PolicyError`; callers must not silently
convert that error to ordinary queueing.

## Audit, digest, and statistics

```python
entries = store.audit_entries(strict=True)
metadata = proposal_review_metadata(entries)
digest = review_digest(entries)
stats = review_stats(entries)

post_review = record_post_review(
    store,
    result["proposal_id"],
    verdict="confirm",  # or "flag"
    reason="checked against the cited source",
)
```

`audit_entries(strict=True)` raises `AuditLogError` with a line number when
the append-only JSONL ledger is damaged. Reporting functions replay stored
route snapshots and do not use the current `TypeRegistry` to reinterpret
historical decisions.

A post-review `flag` records a human quality result but does not edit source.
Correction requires a new schema-valid declaration proposal whose
`supersedes` relation points to the old declaration. Promotion and revision
use the same append-only mechanism, optionally adding `revision_of`. The new
declaration must be lifecycle `active` before its uniquely resolved
`supersedes` relation has authority; human approval does not silently rewrite
candidate lifecycle state or the old declaration's status.

ReviewStore does not create Git commits. Hosts may integrate Git, but atomic
approval, audit replay, and correction semantics do not depend on it.

## Compatibility promise

Patch releases in the 0.6 line will not remove these root exports or change
the authority meaning of EvidencePack layers. `provisional` and the Phase 3
search-trace metadata are additive to
`memdsl.evidence_pack.v1`; breaking serialized schema changes require a new
schema id. Trace uses separate `memdsl.trace.v1` / `memdsl.mcp.trace.v1`
schemas rather than changing Map/query/explain authority. The lifecycle-safe
supersede resolver is a correctness/security fix
to that existing authority promise: code that relied on candidate, retracted,
archived, ambiguous, duplicate, or wrongly prefixed supersedes hiding a target
was relying on unintended behavior.

Collection reads continue to preserve duplicate source occurrences for
diagnosis. A single-declaration explain request no longer resolves a duplicate
full id or ambiguous bare name to the first occurrence; CLI/Python text explain
reports ambiguity and MCP `memory_explain` returns `status: ambiguous`.
