# Reproducibility and Release Metadata for Review-Gated Authority

## Citation identity

- **Full title:** *Review-Gated Authority for Persistent Agent Memory: A
  Ratification-Rooted Contract Against Semantic Authority Laundering*
- **Manuscript version:** working position-paper draft v0.6
- **Metadata revision:** 2026-07-15
- **Author:** `liyuan`, Independent Researcher. This is the repository's
  current public software-author name; the final scholarly display name must
  be author-confirmed before submission.
- **Canonical repository:** <https://github.com/Liyuan1992/memdsl>
- **Paper license:** [CC BY 4.0](PAPER_LICENSE.md)
- **Software license:** [MIT](../LICENSE)
- **Identifiers intentionally absent:** DOI, ORCID, institutional affiliation,
  email address, journal, conference, and archival publication status have not
  been supplied or created.

`CITATION.cff` describes the shipped software in its top-level record and the
unpublished paper draft in `preferred-citation`. The two citations must not be
collapsed: software version `0.6.0` is shipped, while paper version `0.6` is a
working manuscript and the local software `0.8.0` state is only a candidate.
The independent P5 reviewer-lens findings and publication blockers are recorded
in the [publication-readiness audit](PAPER_publication_readiness_audit.md).

## Immutable implementation-status table

| State | Exact tag or commit | What the evidence supports | What it does not support |
| --- | --- | --- | --- |
| Shipped memdsl | tag `v0.6.0`; `72274d9d4f065b76bceaf30f529dcbd47b3f3e18` | Public 0.6.0 software baseline: typed declarative memory, schemas, lifecycle/provisional lanes, evidence, relations, proposal/review/audit, CLI, and MCP | The paper's authority ledger, semantic authority digest, proof objects, live reduction frontier, or proof-checked sinks |
| Phase -1 baseline | `cf8c2bc0f1d338de0154c9c5129ad92c68279025` | Synthetic characterization files and the benchmark harness over unmodified 0.6.0 runtime semantics | A performance SLA, real-workspace result, or research conclusion |
| Phase 0A | `244e8d25bb71731f31a60a9dbabd74f6f48ed2fb` | Non-authoritative `supersedes` relations cannot suppress active authority; shared v1 current-set behavior | A paper-style `Grant` root or governance ledger |
| Phase 0B | `226e0110546df9f477030a6baf87e84e1e1a806f` | Internal deterministic `CompiledWorkspace`, indexes, resolver, and content-aware cache | A stable public compiler API or semantic ratification |
| Phase 1 | `cf11bf898514c4c2fcb00d6540cc2505159e7a7e` | Compiler/link diagnostics and report-only View | Quarantine enforcement or proof-bearing authority |
| Phase 2 | `c13d1e392bfb459f436f2075a7c0b8a25c3a9063` | Bounded Catalog, paging, byte budgets, and revision-bound cursor | Authority completeness derived from a truncated Catalog |
| Phase 3 | `c67fcc76dd66c7abe81916084a5e6b29b5536cca` | Indexed lexical candidate selection, suggestions, and bounded BFS Trace | Graph connectivity as proof |
| Phase 4 | `e128d351b670bfb1aabe04fa36f5bcdaa4d0b1cb` | Exact `use`, workspace-v2 linking, and review-gated workspace Dialect | Automatic dialect authority or negative-mapping semantics |
| Phase 5 | `8e7c84815897ad13f89522e9e3b1edd0fcdb37b0` | Opt-in quarantine/strict enforcement, public `ResolvedView`, v2 reads, and trusted-host principal filtering | `L_auth`, `SemDigest` authority binding, proof objects, or live frontier closure |
| Phase 6/7 audit | `ff9ff8a7dfe983a9db3caaf221d7315cfda8eba6` | Evidence-gate audit; first-class edges and cold-history/incremental compilation explicitly deferred | An implementation of either deferred phase |
| Local 0.8.0 candidate | `091b4736e02969ccdd198cfcb30ba9038feb78db` | Integration of Phase -1 through 5 plus local version, documentation, CI, publish-gate, package, and fresh-install evidence | A shipped release, remote CI result, GitHub Release, PyPI 0.8.0 publication, production rollout result, or comparative study |
| Paper authority contract | manuscript source `3535bfb9661724818011f4bf2823ed09e895069a` plus the current metadata revision | Planned `Grant` root, `L_auth`, `(p,h)` checkout, `SemDigest`/`ReviewDigest`, `Project`/`Compute` proofs, reduction closure, and `Verify` sinks | Current memdsl behavior or conformance |

The current reference implementation target therefore has
`CompiledWorkspace`, Catalog, Trace, exact `use`, workspace Dialect, and
opt-in quarantine/`ResolvedView`, but it does **not** implement the paper's
authority ledger, digest-bound grants, proof-instance DAG, live reduction
closure, or proof-checked sinks.

## Claim-to-implementation-to-artifact map

| Paper claim or obligation | Implementation status | Exact evidence |
| --- | --- | --- |
| Pending proposals are not durable queryable memory | Implemented in shipped 0.6.0 | tag `v0.6.0`; `docs/DESIGN_review_policy.md`; gated-write tests at `72274d9d...` |
| Source compilation and indexes are rebuildable interpretation products, not truth or ratification | Partially implemented as practical infrastructure | Phase 0B-5 commits; candidate path `091b4736...:docs/DESIGN_memory_source_compiled_view.md` |
| Bounded Catalog/Trace and explicit v1/v2 serving lanes | Implemented only in the unreleased candidate line | Phase 2-5 commits and `091b4736...:docs/PUBLIC_API.md` |
| Exact capability-scoped `Grant` is the sole positive persistent authority root | Planned; not implemented | [main manuscript](PAPER_review_gated_authority_source_compiled_contract.md), §§3-4 |
| `SemDigest` and `ReviewDigest` bind meaning and the reviewed decision packet | Planned; not implemented | main manuscript §3.4 |
| Named checkout separates grant prefix `p` from reduction frontier `h` | Planned; not implemented | main manuscript §§3.5 and 4.1 |
| `ProjectProof`/`ComputeProof` preserve non-amplifying derivation and proof-instance reduction closure | Planned; not implemented | main manuscript §§4.2-4.4 |
| Authority-sensitive sinks recheck the latest reduction frontier | Planned; not implemented | main manuscript §§4.1 and 5.1 |
| Related-work comparisons are bounded to the audited corpus | Literature-verified, not an implementation claim | [24-item claim ledger](PAPER_related_work_claim_ledger.md) and references [1]-[14] |
| Synthetic scale observations characterize one fixture and environment | Reproducible characterization only | [baseline method](baselines/PHASE_MINUS_ONE_SCALE_BASELINE.md) and [raw JSON](baselines/phase_minus_one_0.6.0.json) |

## Frozen synthetic baseline

The baseline uses deterministic fictional declarations generated in memory. It
reads no existing memory workspace and creates no `.memdsl` review store. The
benchmark harness was added at Phase -1 commit
`cf8c2bc0f1d338de0154c9c5129ad92c68279025`; its recorded runtime semantics are
the shipped 0.6.0 source commit
`72274d9d4f065b76bceaf30f529dcbd47b3f3e18`.

Recorded environment:

- CPython 3.12.10;
- Windows 11, AMD64;
- five repetitions;
- `time.perf_counter` wall time and `tracemalloc` peak allocation;
- compact sorted UTF-8 JSON payload bytes;
- recorded 2026-07-14.

Reproduction command from the Phase -1 repository root:

```console
.venv\Scripts\python.exe benchmarks\phase_minus_one_baseline.py --sizes 100 1000 10000 --repeats 5 --output docs\baselines\phase_minus_one_0.6.0.json
```

Frozen file SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `docs/baselines/phase_minus_one_0.6.0.json` | `f34d21a32b033a524240b65002af180aa26e071fbf44385ad8679645d7b58e73` |
| `docs/baselines/PHASE_MINUS_ONE_SCALE_BASELINE.md` | `3c6f1de4efe2a47a6288c72e4e2dddc6f0ffb9d4f86ff431e99eeb32e2389ad2` |
| `benchmarks/phase_minus_one_baseline.py` | `13e7d112b0ebfe339195530311dd4b7ac0e37f60054113753b5e85772aa32ab1` |

The raw JSON additionally binds the generated 100-, 1,000-, and
10,000-declaration sources to SHA-256 values
`1ed146fdca5a6d2b20aec6ac698218fcee6a9706cdefd089d3ee1dec26169b49`,
`68eb22a433900b8f81ed5a968587befa401adff045811ae9ee5758186c05911e`,
and `b8ddc894a497bfb3168cdf1a63f68cedf8400281e65ae3368a3392d51091e452`.
These observations are synthetic characterization. They are not a claim about
human memory, production workloads, comparative performance, or the paper's
security effectiveness.

## Shipped 0.6.0 and local 0.8.0 evidence

As checked on 2026-07-14, the public repository's `main` and tag `v0.6.0`
resolve to `72274d9d4f065b76bceaf30f529dcbd47b3f3e18`, and PyPI's latest memdsl
version is 0.6.0. The published files have these PyPI-recorded SHA-256 values:

| Published 0.6.0 artifact | SHA-256 |
| --- | --- |
| `memdsl-0.6.0-py3-none-any.whl` | `506d2891ae02f74872154b0d0764b21b23420a0320f2f60194857891a9f2f959` |
| `memdsl-0.6.0.tar.gz` | `e383e9ff99876524d00dde34aa17ee3cc7df18824d787fa8a5ca146acced0e52` |

The exact 0.8.0 candidate commit records `355 passed`, a 21-file Python 3.9
AST gate, CLI/MCP/gated-write checks, focused phase/security checks, and an
outside-repository fresh-wheel smoke in
`091b4736...:docs/DESIGN_memory_source_compiled_view.md` §24.3. P4 did not
reinterpret those checks as research results. A read-only P4 recheck confirmed
the candidate tree was clean on CPython 3.12.10 / Windows 11 AMD64, version
metadata was 0.8.0, Twine accepted both local artifacts, and the candidate's
member/privacy scanner accepted 26 wheel members and 97 sdist members. The
candidate's recorded full gates and the P4 artifact recheck are represented by:

```console
python -m compileall -q src tests scripts
python scripts/release_checks.py python39-ast
python -m pip check
python -m pytest -q
python -m pytest -q tests/test_phase_minus_one_characterization.py tests/test_phase_two_catalog_budget.py tests/test_phase_three_indexed_query_trace.py tests/test_phase_four_use_dialect.py tests/test_phase_five_quarantine_enforcement.py
python -m twine check dist/*
python scripts/release_checks.py artifacts --dist dist --expected 0.8.0
```

The local candidate artifact hashes were:

| Unreleased local artifact | SHA-256 |
| --- | --- |
| `memdsl-0.8.0-py3-none-any.whl` | `ddd59f921b74a8df06b254ca9fef6e46f13d0c75c5b2ab94853cb891facb10c7` |
| `memdsl-0.8.0.tar.gz` | `639a08d92fd233bcb0b9f702f7426329a58dccf82d43e79f99401b11a3ae318d` |

These 0.8.0 archives are local release-candidate evidence only. Their hashes do
not identify a public release and must not be reused as remote tag-build or
PyPI evidence.

## Publication disclosures and remaining confirmations

- **AI assistance:** OpenAI Codex assisted with repository inspection, prose
  and metadata drafting, consistency checks, and local verification. The human
  author remains responsible for the claims, citations, and publication.
- **Funding:** author confirmation required. No funder, grant, or award is
  inferred from repository metadata.
- **Competing interests:** author confirmation required. No conflict or
  no-conflict statement is inferred without the author's decision.
- **Data and privacy:** the current paper artifact contains only synthetic
  benchmark declarations and public repository/literature metadata. It does
  not include a private memory workspace, user profile, proposal store, audit
  log, credential, or personal dataset.
- **Human subjects:** no human-subjects study and no human-derived empirical
  result are reported. If a future paper adds user studies or private-memory
  evaluation, ethics, consent, retention, and disclosure requirements must be
  reassessed before publication.
- **Remote actions:** no DOI, tag, GitHub Release, Zenodo record, or PyPI 0.8.0
  publication is created or authorized by this metadata record.
