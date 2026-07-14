# memdsl Documentation Index

This index keeps the practical software contract and the focused research
paper adjacent without treating either as a substitute for the other.

## Version and evidence boundary

| Item | Status | Authority |
| --- | --- | --- |
| memdsl `0.6.0` | Shipped software | tag `v0.6.0`, commit `72274d9d4f065b76bceaf30f529dcbd47b3f3e18` |
| memdsl `0.8.0` | Unreleased local candidate | candidate commit `091b4736e02969ccdd198cfcb30ba9038feb78db` plus the local P6 integration audit |
| memdsl `0.9.0.dev0` | Experimental next-minor line | workspace-v3 first-class explicit Edge contract; not released |
| paper `v0.6` | Unpublished focused position-paper draft | P5 paper commit `5c55948b13029d82974cc12ee3249099b0444f75` |
| paper authority runtime | Planned and unimplemented | the paper contract, not current memdsl behavior |

`CITATION.cff` preserves the same split: its top-level record cites the shipped
software `0.6.0`, while `preferred-citation` cites the unpublished paper
version `0.6`. The local `0.8.0` candidate is not presented as a release.

## Practical software contract

- [Language and runtime specification](SPEC.md)
- [Python, CLI, and MCP public API](PUBLIC_API.md)
- [Upgrade, compatibility, and rollback guide](UPGRADING.md)
- [Review-policy design and security contract](DESIGN_review_policy.md)
- [Memory Source, CompiledWorkspace, ResolvedView, and bounded projection
  design](DESIGN_memory_source_compiled_view.md)
- [Experimental Phase 6 explicit Edge design and risk matrix](DESIGN_explicit_edges_phase6.md)

The practical design describes the frozen Phase -1 through Phase 5 line plus
the explicitly opt-in experimental Phase 6 Edge contract. It does not
implement the paper's authority ledger, digest-bound grants, proof objects,
live reduction closure, or `Verify` sinks.

## Focused position-paper artifact

- [Main manuscript](PAPER_review_gated_authority_source_compiled_contract.md)
- [Related-work claim ledger](PAPER_related_work_claim_ledger.md)
- [Reproducibility and release metadata](PAPER_reproducibility_and_release_metadata.md)
- [P5 publication-readiness audit](PAPER_publication_readiness_audit.md)
- [Paper license](PAPER_LICENSE.md)

The manuscript is locally suitable for focused position-paper integration,
but public or archival submission remains blocked until the author confirms
the scholarly display name, funding statement, and competing-interest
statement. DOI, ORCID, email, institution, venue, and archival status remain
absent and must not be fabricated.

## Reproducibility material

- [Frozen baseline method](baselines/PHASE_MINUS_ONE_SCALE_BASELINE.md)
- [Frozen baseline data](baselines/phase_minus_one_0.6.0.json)
- [Synthetic benchmark harness](../benchmarks/phase_minus_one_baseline.py)

These materials characterize synthetic fixtures. They are not empirical
evidence for the paper's authority contract and are not a production SLO.

## Local P6 receipt

`PAPER_final_integration_audit.md` is the source-repository receipt for the
final local integration, verification results, artifact hashes, member counts,
remaining blockers, and remote actions. It is intentionally excluded from the
built archives because recording an archive's own SHA-256 inside that archive
would create a self-referential artifact identity. The archives instead carry
this index, both companion documents, the P5 readiness record, citation and
license files, and the frozen reproducibility material.
