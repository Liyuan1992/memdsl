# P5 Publication-Readiness Audit for Review-Gated Authority

**Audit date:** 2026-07-15<br>
**Manuscript:** [Review-Gated Authority for Persistent Agent Memory: A
Ratification-Rooted Contract Against Semantic Authority
Laundering](PAPER_review_gated_authority_source_compiled_contract.md)<br>
**Manuscript version:** working position-paper draft v0.6; metadata revision
2026-07-15<br>
**P5 branch:** `codex/paper-v06-publication-readiness`<br>
**P5 starting commit:** `ce18a95eede73949c27648fb3262bb9b480a3561`<br>
**Scope:** independent reviewer-lens audit, formal consistency, related-work
mapping, implementation-status accuracy, focus, metadata, licensing, privacy,
and local publication readiness. This is not external peer review.

**Phase 6 mainline addendum:** the original P5 decision remains a historical
paper audit. The current implementation-status rows below have been reconciled
to the later experimental Edge commits `6bc3ffd986b1ffe29cefa928642fd0cf47e5c2c9`
and `4ec9d43fda56a277609dd822c61acdb9a7265655`. This addendum does not change the
paper's nonconforming status or authorize publication.

## Executive decision

- **Focused position paper:** locally ready for P6 integration after the
  deterministic corrections recorded below.
- **Empirical systems or evaluated security paper:** not ready. The manuscript
  reports an evaluation plan, not comparative results, and memdsl does not yet
  implement the paper authority runtime.
- **Public or archival publication:** **no-go** until the author confirms the
  scholarly display name, funding statement, and competing-interest statement.
  DOI, ORCID, email, and institution remain absent and must not be invented.
- **Software release:** `0.9.0.dev0` is an unreleased local candidate. Stable
  0.8 contracts remain public; workspace-v3 explicit Edges remain experimental.
  No local evidence is a remote CI run, tag, GitHub Release, Zenodo record,
  DOI, PyPI release, production rollout, or comparative empirical result.

## Evidence boundary

The audit distinguishes these immutable states:

| State | Exact evidence | P5 interpretation |
| --- | --- | --- |
| Shipped software | tag `v0.6.0`, commit `72274d9d4f065b76bceaf30f529dcbd47b3f3e18` | Public software baseline only |
| Implemented source line | Phase -1 through Phase 5 ending at `8e7c84815897ad13f89522e9e3b1edd0fcdb37b0` | `CompiledWorkspace`, Catalog, Trace, exact `use`, workspace Dialect, and opt-in quarantine/`ResolvedView` |
| Historical Phase 6/7 gate | `ff9ff8a7dfe983a9db3caaf221d7315cfda8eba6` | Correctly deferred both phases at the 0.8 evidence gate; this remains historical evidence, not the current Phase 6 state |
| Experimental Phase 6 | `6bc3ffd986b1ffe29cefa928642fd0cf47e5c2c9`, reconciled by `4ec9d43fda56a277609dd822c61acdb9a7265655` | workspace-v3 first-class Edge source/lifecycle/review contract with a permanent human-review floor; not stable and not paper-authority conformance |
| Unreleased local candidate | `0.9.0.dev0` scope freeze after `4ec9d43fda56a277609dd822c61acdb9a7265655` | Stable 0.8 contracts plus experimental Phase 6 and local release-gate evidence only |
| Deferred practical work | current release-scope freeze | Phase 7, automatic dialect learning, automatic Edge candidates, and stable Edge promotion remain planned/not shipped |
| Paper authority contract | P4 commit `ce18a95eede73949c27648fb3262bb9b480a3561`, refined by this P5 audit | Planned `L_auth`, digest-bound grants, `(p,h)` checkouts, proof objects, live reduction closure, and proof-checked `Verify` sinks |

At the exact candidate commit, a source search outside planning documents finds
no `SemDigest`, `ReviewDigest`, `RatifiedCap`, `GrantProof`, `ProjectProof`,
`ComputeProof`, `L_auth`, checkout-lineage, or governance-ledger runtime. This
supports the manuscript's statement that memdsl is a reference implementation
target rather than a conforming implementation.

## Reviewer lens 1: position and vision

**Disposition:** ready as a focused position paper after author metadata and
disclosure blockers are resolved.

The manuscript has a recognizable residual thesis: persistence, discovery,
compilation, current selection, and derivation do not themselves create
principal-accepted persistent authority. The contribution is bounded to the
composition of an exact capability-scoped `Grant`, separate semantic/review
digests, two checkout frontiers, and proof survival at authority-sensitive
sinks. The text explicitly concedes prior art in governed writes, approval,
ratification, origin-bound authority, dependency repair, access control, and
foundational security mechanisms.

The source-code analogy remains subordinate to the authority contract. The
paper also avoids presenting the evaluation plan as a result. P5 shortened
repetition and retained the position-paper scope rather than restoring the
full practical source/compiled-view specification.

**Reported but not implemented:** a later submission may simplify the formal
core for a broader venue, add one running end-to-end example, or expand the
literature search beyond the audited corpus. Those are editorial or research
directions, not deterministic P5 corrections.

## Reviewer lens 2: systems

**Disposition:** coherent systems position and artifact plan; not an evaluated
systems result.

The paper separates normative source, rebuildable compilation products,
authenticated governance state, checked serving, and sink verification. It
also names the trusted computing base, budget/completeness boundary, migration
strategy, and failure behavior. The artifact manifest accurately distinguishes
shipped `0.6.0`, stable/public Phase -1 through 5, experimental Phase 6, planned
Phase 7, the local `0.9.0.dev0` candidate, and the unimplemented paper contract.

The systems evidence is local and synthetic. There is no implemented authority
ledger, proof store, frontier-advance protocol, proof verifier, or production
deployment. There are no comparative measurements of authority leakage,
utility, review load, or reduction latency. These absences are correctly
framed as future implementation and evaluation work.

**Reported but not implemented:** concurrency and ledger-consistency rules,
proof storage and garbage collection, canonicalization costs, availability
trade-offs under unavailable frontiers, and operational key/delegation
management require a future design and implementation window.

## Reviewer lens 3: security

**Disposition:** internally consistent security position under its stated
trusted-computing-base assumptions; not a proved or empirically validated
security system.

The single-positive-root invariant is preserved: `Grant` issues persistent
declaration capabilities, reductions only remove authority/currentness/serving
eligibility, interpretation components only interpret or verify, and session
or completeness attestations do not create persistent authority. The threat
model distinguishes semantic ratification from origin integrity and action
authorization. The conformance boundary is limited to structured authority
lanes and proof-checked sinks, avoiding a false claim of cognitive
non-interference in shared model context.

The `p`/`h` split prevents post-base grants from entering an old checkout while
allowing later authenticated reductions to invalidate old proofs. Projection
preserves one proof, computation concludes computed validity, generation is
unratified, and existential proof-instance closure preserves independent
alternative proofs.

**Reported but not implemented:** the paper has no mechanized soundness proof,
cryptographic event format, rollback/fork-consistency protocol, or adversarial
implementation results. A security-venue submission making stronger assurance
claims would require those additions; P5 does not create them.

## Formal-consistency audit

| Element | Result | Audit finding |
| --- | --- | --- |
| `Grant` as sole positive root | Pass | Root taxonomy, `RatifiedCap`, proof language, invariants, conformance boundary, and conclusion agree. Schema, compiler, resolver, operators, retrieval, confidence, and session inputs do not issue persistent declaration capability. |
| Base prefix `p` and reduction frontier `h` | Pass after deterministic clarification | Grants are admitted only at indices `≤ p`; reductions apply through `h ≥ p`; grants in `(p,h]` remain ignored. `Verify` now states `h_now ≥ h` explicitly. |
| `RatifiedCap` / `ServeEligible` / `Verify` | Pass | The judgments respectively fold surviving grants, apply compiled/current/redacted/schema conditions, and recheck proof/output/lineage/latest reductions at a sink. |
| `SemDigest` / `ReviewDigest` | Pass | Meaning-changing source and interpretation dependencies remain separate from the reviewed capability/evidence/policy packet. Ledger history does not feed back into `SemDigest`. |
| Declaration digest binding | Pass after deterministic clarification | For a declaration revision `x`, `digest(x)` is now explicitly the `SemDigest` component used by `GrantProof` and `Verify`. |
| `ProjectProof` conclusion | Pass | A registered single-object semantics-preserving projection retains one source proof and cannot omit qualifiers, combine objects, or turn a truncated excerpt into authority. |
| `ComputeProof` conclusion | Pass after deterministic clarification | `ComputedValid` now explicitly requires a top-level `ProjectProof` or `ComputeProof`; it cannot be satisfied directly by `GrantProof` and does not ratify the output. |
| Proof-instance existential reduction closure | Pass | Invalidation ranges over proof instances and their positive, anti-, interpretation, schema/policy, and completeness dependencies. Independent grants or alternative proofs survive only when separately valid. |
| Currentness and supersession | Pass | Source `supersedes` only nominates an exact relation/witness. An authenticated exact `Supersede` reduction changes currentness but does not grant the successor. |
| Redaction and erasure | Pass | Semantic acceptance, logical serving redaction, and physical erasure remain distinct; no automatic descendant or copy erasure is claimed. |

## Related-work and claim-ledger audit

- The manuscript has 14 numbered reference entries, `[1]` through `[14]`.
- Every reference number appears in the manuscript body.
- The claim ledger has 24 rows:
  `A-01`, `I-01`, `I-02`, `RW-01` through `RW-19`, `CB-01`, and `C-01`.
- Each row maps to identifiable manuscript wording and retains the ledger's
  `direct`, `partial`, or replaced/unsupported disposition.
- The main text does not restore field-wide novelty language. “Closest” remains
  bounded to the cited corpus, ratification and laundering are acknowledged as
  prior terms, and the source-code analogy is not presented as the novelty.
- The ledger still does not establish that no uncited work has proposed the
  same combination. A broader systematic search remains future publication
  work, not a blocker that P5 may claim to have closed.

## Publication-readiness matrix

| Area | Status | Evidence and remaining action |
| --- | --- | --- |
| Claim scope | Ready for position-paper framing | Contributions are bounded; no field-wide priority claim or comparative result is asserted. |
| Formal consistency | Ready after minor P5 corrections | Single root, frontiers, judgment layers, digest split, proof conclusions, existential reduction closure, and currentness/redaction agree. No soundness theorem is claimed. |
| Related work | Ready within audited corpus | 14/14 references are cited; 24/24 ledger rows map to the manuscript. Broader search remains future work. |
| Implementation status | Accurate but nonconforming | Shipped `0.6.0`, stable/public Phase -1 through 5, experimental Phase 6, planned Phase 7, local `0.9.0.dev0` candidate, and planned paper runtime remain distinct. |
| Reproducibility | Locally ready; remotely incomplete | Frozen synthetic baseline and local candidate artifacts are hash-bound. No paper PDF was generated. Remote CI/tag/release/PyPI evidence does not exist. |
| Metadata | Blocked for submission | Scholarly display name is unconfirmed. DOI, ORCID, email, institution, venue, and archival status are absent and must not be fabricated. |
| License | Ready locally | Paper artifacts, including this audit, are CC BY 4.0; software remains MIT; `docs/SPEC.md` retains its separate statement. |
| Privacy | Ready for the audited local sources | Paper artifacts contain public/synthetic material plus only the anonymous Phase 6 aggregate; no private memory workspace, row-level evidence, identifier mapping, proposal store, audit log, credential, or personal dataset is included. Artifact and machine-path scans remain mandatory. |
| Disclosures | Blocked for submission | AI assistance and human-subjects/data scope are stated. Funding and competing-interest statements require author confirmation. |
| Remote publication | Blocked / not authorized | No push, tag, GitHub Release, Zenodo/DOI action, or PyPI publication is permitted in P5. Future remote actions require explicit user authorization and fresh verification. |

## Immutable hashes carried into P5

P4 committed-blob SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `CITATION.cff` | `10d97f3146253555f06b52edc85dcf45053f39c55a3530ac55e060eca7a97499` |
| `LICENSE` | `7b64093a521a565706777df93250fc51aaa761f452c10b96b3ec32a19a117795` |
| `docs/PAPER_LICENSE.md` | `73914dec74744242784cf4fce5dbea735712b441cf58f589a4a917042eb91888` |
| `docs/PAPER_related_work_claim_ledger.md` | `902f348f719dd085d9ad816f73354ac609b4657edac0426bfb909a07008cb009` |
| `docs/PAPER_reproducibility_and_release_metadata.md` | `daa9c683564d5fab3ebabe840354c060d183d50cb9959518468d6267991370dd` |
| `docs/PAPER_review_gated_authority_source_compiled_contract.md` | `7272fcf9aa80983869df454c48adb47c47a7d816683c867a3a6ee4f45015a26f` |

Frozen baseline and unreleased-candidate hashes remain those recorded in the
[artifact manifest](PAPER_reproducibility_and_release_metadata.md). P5 verified
the candidate archives as
`ddd59f921b74a8df06b254ca9fef6e46f13d0c75c5b2ab94853cb891facb10c7`
for the wheel and
`639a08d92fd233bcb0b9f702f7426329a58dccf82d43e79f99401b11a3ae318d`
for the sdist. These are local candidate hashes, not public-release hashes.

## Remaining blockers

1. Author confirmation of the scholarly display name.
2. Author confirmation of the funding statement.
3. Author confirmation of the competing-interest statement.
4. DOI, ORCID, email, and institution remain absent; none may be created or
   inferred in P5.
5. The paper authority runtime remains unimplemented.
6. The `0.9.0.dev0` candidate remains local; remote CI, tag, GitHub Release,
   Zenodo, DOI, and PyPI publication have not occurred.
7. Any empirical comparison, mechanized proof, or security-evaluation claim
   requires a later authorized research and implementation effort.

## P5 verification record

- Main-manuscript whitespace word count: **5,052**, reduced from 5,138.
- Proportional regression: `compileall` passed and full `pytest` reported
  **277 passed**.
- Verify-skill surface smoke: lint-demo remained **2 errors / 3 warnings,
  exit 1**; Alex query and explain passed; MCP inspect reported **10 tools**;
  `pip check` reported no broken requirements.
- CFF validation: `cffconvert 2.0.0 --validate` reported validity under
  **CFF schema 1.2.0**. The top-level software `0.6.0` record and the generic
  paper `0.6` preferred citation remain distinct.
- Markdown/internal links: all checked local targets resolved.
- Reference and claim structure: **14/14** reference entries were cited in the
  body and **24/24** claim-ledger rows were present and unique.
- Public reference reachability: 13 of 14 audited full-text URLs returned HTTP
  2xx; the DTIC page for `[10]` returned HTTP 429 rate limiting rather than a
  content or metadata contradiction.
- Privacy and machine-path scan: passed for the manuscript, ledger, artifact
  manifest, paper license, this audit, and root license.
- `git diff --check`: passed. No PDF was generated.
- Final branch/commit/clean state is recorded in the P5 closeout and P6
  handoff.
