# Phase 6 Release Scope and Evidence Freeze

Status: memdsl `0.9.0` software release scope. Tag `v0.9.0` anchors the package
version without promoting the opt-in Edge surface beyond experimental.

This record freezes the product boundary after the stable 0.8 integration,
the experimental explicit-Edge implementation, and the anonymous human-review
follow-up. It does not make host-specific extraction or sanitization behavior
part of memdsl.

## Ancestry and evidence anchors

- Stable 0.8 integration baseline: `4ee810833ef0cbd8562e72e3ad202a07c5ce77e8`.
- Experimental explicit-Edge implementation:
  `6bc3ffd986b1ffe29cefa928642fd0cf47e5c2c9`.
- Anonymous human-review reconciliation:
  `4ec9d43fda56a277609dd822c61acdb9a7265655`.
- The commits form a direct linear parent chain in that order.

## Release matrix

| Classification | Included contract | Release meaning |
| --- | --- | --- |
| Stable/public | Source declarations as normative authority; explicit proposal/review/approval; append-only audit; pending isolation | Existing v1 authority and review behavior remains compatible. Review history is an audit record, not a second runtime authority root. |
| Stable/public | `CompiledWorkspace` / `compile_workspace`; Catalog, Query, Explain, List, Check, Trace, Map compatibility, cursors, budgets, and v1/v2 schemas | Compiled state and projections are deterministic and rebuildable from Source. Public construction does not make compiler caches authoritative. |
| Stable/public | `memdsl.workspace.v1` / `v2`, exact `use`, `dialect_mapping`, `ViewContext`, `ResolvedView`, and opt-in v2 enforcement | Existing schema and API meanings remain frozen; v2 enforcement stays explicit and fail-closed. |
| Experimental | `memdsl.workspace.v3` with `features.explicit_edges="experimental-v1"` | The feature must be explicitly enabled; v1/v2 workspaces and envelopes retain their existing behavior. |
| Experimental | `relation_edge` plus `explicit_edge` authoring alias; `relation_edge_event` plus `explicit_edge_event`; Edge evidence, lifecycle, review, list/explain/Trace, and CLI confirmation | Canonical ids use `relation_edge:<name>`. MCP keeps the existing 11 tools and scopes. |
| Experimental | Built-in Edge relations `supports`, `depends_on`, `contradicts`, and `supersedes` | Every descriptor remains experimental. `supersedes` is graph-only in Phase 6 and does not change declaration authority. |
| Planned / not shipped | Automatic dialect learning, automatic Edge candidate generation, inferred authoritative graph edges, stable Edge promotion, and Phase 7 cold-history/incremental compilation | These capabilities require new evidence and separate contracts. They are not implied by the current parser, compiler, or review APIs. |
| Host-specific / excluded | Extraction prompts, sanitizers, private schemas, private policies, private samples, workbooks, path mappings, identifiers, user workflows, and runtime adapters | They belong to consuming applications. Host acceptance or shadow activation is not a memdsl release gate and cannot be used as evidence that the generic Edge contract failed. |

## Non-configurable Edge review floor

The following reserved capabilities always require a person:

```text
relation_edge
explicit_edge
relation_edge_event
explicit_edge_event
edge_lifecycle
```

They cannot be combined with `auto_approvable`, cannot be selected by an
automatic policy rule, and cannot gain durable authority from an AI or host
recommendation. Pending Edge proposals are never loaded, compiled, counted,
queried, explained, or traced as durable memory.

`related` remains discovery-only. It is not an authoritative built-in Edge
relation. AI recommendation alone cannot promote `supersedes` or any other
experimental relation to stable.

## Anonymous exploratory evidence

The first completed human follow-up batch produced:

```text
accept=7
uncertain=3
reject=0
```

The three uncertain items were invalid or unreviewable source contamination,
not negative Edge judgments. The seven accepted comparisons provide limited
evidence that independently reviewable Edges can be useful. They do not show
that automatic candidate coverage, type selection, or evidence stability is
ready for automatic activation.

The evidence decision is **ADJUST**: retain the explicit, human-reviewed Edge
experiment while narrowing any future candidate generator at the host layer.
memdsl core does not ship such a generator.

## Threats to validity

- The evidence is one anonymous, single-principal exploratory batch rather
  than a representative or controlled study.
- Selection and extraction preceded human review, so coverage and error rates
  cannot be generalized to other workspaces or domains.
- Contamination was excluded from the Edge precision denominator; this is the
  correct review disposition but does not establish end-to-end extraction
  quality.
- `supports`, `depends_on`, and `contradicts` received sample support;
  `supersedes` did not receive direct human validation in this batch.
- The observations do not validate automatic extraction, automatic Edge
  generation, complete private-memory understanding, production queue
  economics, or a non-bypassable authorization runtime.

## Exact-commit build contract

A release source tree is canonical only when it is a fresh checkout of the
exact commit and passes `python scripts/release_checks.py source-tree`.
`.gitattributes` fixes tracked text to LF on every platform. The repository has
no tracked Windows batch or PowerShell scripts; future `.bat` and `.cmd`
launchers are explicitly reserved as CRLF, while PowerShell and shell sources
remain LF. Manual conversion in one worktree is not release evidence.

Hatchling `1.31.0` is the component that produces release wheel and sdist
bytes. It is pinned for Python 3.10+ in both the PEP 517 build-system
requirements and the release development environment. Python 3.9 source/dev
setup uses the last compatible pinned backend, Hatchling `1.27.0`; that path
may test the supported core runtime but is not authorized to produce release
archives. Release builds first run
`release_checks.py build-toolchain`, then invoke
`python -m build --no-isolation`, so the checked backend is the backend that
performs the build. The `build` frontend only invokes that backend, and `wheel`, installers,
Twine, and pip do not generate the Hatchling archive bytes; they remain
verification or installation tools and are not part of the byte-producing
pin.

The fixed `SOURCE_DATE_EPOCH`, canonical source digest, backend version, and
artifact hashes must agree across two new, independent clean source roots from
the final commit before the receipt can authorize another independent review.

## Release boundary

The release may be accepted only if the full synthetic CLI/MCP,
scoped-denial, gated-write, build, artifact-membership, privacy, reproducible
build, and outside-repository fresh-wheel gates pass. Host-specific sanitizer
or extraction activation remains excluded from that decision.

The `v0.9.0` software release may publish the verified package without changing
the classifications above. Host deployment, private-data activation, and any
authority-semantic expansion remain separate, explicitly authorized actions.
