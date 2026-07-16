# memdsl Documentation Index

This index lists the public software contracts, implementation designs,
release boundaries, and reproducibility material shipped with memdsl.

## Version and release boundary

| Item | Status | Authority |
| --- | --- | --- |
| memdsl `0.6.0` | Historical shipped baseline | tag `v0.6.0`, commit `72274d9d4f065b76bceaf30f529dcbd47b3f3e18` |
| memdsl `0.8.0` | Frozen stable/public compatibility contract; not separately released | v1/v2 Source, review, compiled-view, navigation, query, and enforcement contracts |
| memdsl `0.9.0` | Shipped software release | stable 0.8 contracts plus the opt-in workspace-v3 explicit Edge experiment; tag `v0.9.0` |

`CITATION.cff` cites the shipped memdsl software. The stable 0.8 compatibility
line was not released separately.

## Software contracts and design

- [Language and runtime specification](SPEC.md)
- [Python, CLI, and MCP public API](PUBLIC_API.md)
- [Upgrade, compatibility, and rollback guide](UPGRADING.md)
- [Review-policy design and security contract](DESIGN_review_policy.md)
- [Memory Source, CompiledWorkspace, ResolvedView, and bounded projection
  design](DESIGN_memory_source_compiled_view.md)
- [Experimental Phase 6 explicit Edge design and risk matrix](DESIGN_explicit_edges_phase6.md)
- [Phase 6 release matrix and evidence freeze](RELEASE_SCOPE_PHASE6.md)

The practical design describes the frozen Phase -1 through Phase 5 line plus
the explicitly opt-in experimental Phase 6 Edge contract. The release-scope
record classifies stable/public, experimental, planned, and host-excluded
surfaces.

## Reproducibility material

- [Frozen baseline method](baselines/PHASE_MINUS_ONE_SCALE_BASELINE.md)
- [Frozen baseline data](baselines/phase_minus_one_0.6.0.json)
- [Synthetic benchmark harness](../benchmarks/phase_minus_one_baseline.py)

These materials characterize deterministic synthetic fixtures. They are not a
production SLO or a representative performance claim.

## Release records

- [memdsl 0.9.0 published release receipt](releases/0.9.0.md)

Release receipts record remote artifact identity and verification boundaries.
They remain source-repository records and are excluded from wheel and sdist
archives to avoid self-referential artifact identities.
