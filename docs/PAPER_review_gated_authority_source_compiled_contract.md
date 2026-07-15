# Review-Gated Authority for Persistent Agent Memory
## A Ratification-Rooted Contract Against Semantic Authority Laundering

**Manuscript version:** working position-paper draft v0.6; metadata revision 2026-07-15<br>
**Author:** liyuan, Independent Researcher; submission display name pending confirmation<br>
**Reference implementation target:** [memdsl](https://github.com/Liyuan1992/memdsl)<br>
**Paper license:** [CC BY 4.0](PAPER_LICENSE.md); software licensing remains separate<br>
**Status:** no comparative experimental results are claimed; Section 7 specifies the evaluation required for an empirical version. Exact implementation and reproducibility status is recorded in the [artifact manifest](PAPER_reproducibility_and_release_metadata.md), and publication blockers are recorded in the [P5 readiness audit](PAPER_publication_readiness_audit.md).

---

## Abstract

Persistent agent memory creates an authority problem: content that was merely observed, inferred, or proposed can later be retrieved as if it were an accepted fact, preference, or standing rule. Write validation, lifecycle policy, versioning, approval, provenance, and origin-bound defenses address adjacent questions. This paper isolates a narrower contract: when stored content becomes part of a principal's accepted persistent state and how that boundary survives retrieval and derivation.

We propose **review-gated authority**, a contract in which `Grant` is the only positive root of persistent declaration authority. A grant is an accountable ratification event bound to an exact semantic revision, an exact review record, and explicit capabilities. `Revoke`, `Supersede`, and `Redact` can only reduce authority or serving eligibility. Compilers, schemas, resolvers, and deterministic operators interpret or verify authority but cannot issue it. Pending proposals are not queryable memory; admitted but unratified declarations may remain discoverable, but cannot enter authority-bearing serving views.

The contract separates three judgments. `RatifiedCap` folds the authority-governance ledger. `ServeEligible` applies structure, currentness, redaction, and schema ceilings inside a named checkout. `Verify` rechecks the proof, checkout identity, and latest reduction frontier at an authority-sensitive sink. A checkout admits grants only through a fixed base prefix while authenticated reductions may advance through a later frontier. Exact projections retain one source proof, mechanically checked computations carry registered proof instances and dependency witnesses, and generative outputs are born unratified.

A conforming implementation must maintain **authority-channel integrity** at structured memory-service and proof-checked sink boundaries. This obligation does not claim cognitive non-interference when discovery content shares a language-model context. Deterministic source compilation is one enforcement strategy, not an authority root. We give a migration path and adversarial evaluation plan; no comparative result is claimed. The source-code analogy is explanatory, not the novelty claim.

## 1. Introduction

An agent that remembers allows past inputs to govern future behavior. The difficult question is not only what it can retrieve, but what retrieved content is entitled to mean.

Consider three stored statements:

1. the principal says once, "maybe I should become vegetarian";
2. an agent extracts a dietary claim from an untrusted web page;
3. the principal explicitly reviews and adopts a standing dietary preference.

The first has trusted origin but no durable standing. The second has untrusted origin and no standing unless reviewed. The third is deliberately accepted. Storage, ranking, summarization, or graph traversal can erase these distinctions and make a retrievable candidate appear settled.

We call this failure **authority laundering**: content acquires the appearance or system-level privileges of accepted persistent memory through a mechanism that was not authorized to grant those privileges.

Memory-poisoning defenses often ask where content came from and whether untrusted influence may authorize an action. TMA-NM, for example, calls transformations that erase an untrusted origin "laundering" and binds action authority to authenticated origin [7]. Our use of **semantic authority laundering** names an orthogonal transition: content gains principal-accepted persistent privileges without the exact ratification required for that use. An authenticated remark may be trusted-origin but unratified; an untrusted-origin claim may later receive an `assert` grant after evidence review while retaining its origin provenance. Origin integrity and semantic ratification require separate roots.

The central position of this paper is:

> Persistence should not imply authority. Persistent declaration authority must be established by an accountable event over an exact semantic revision, and no retrieval, compilation, or derivation mechanism may silently create a second positive authority root.

The paper makes three contributions, in priority order:

1. It defines **semantic authority laundering** as an unauthorized transition from storage, discovery, or derivation into principal-accepted persistent use, and makes an exact `Grant` the sole positive root of persistent declaration authority.
2. It defines a capability-scoped formal contract: separate semantic and review digests; named checkouts with grant prefix `p` and reduction frontier `h`; layered `RatifiedCap`, `ServeEligible`, and `Verify` judgments; and proof-instance reduction closure that separates declaration authority from computed validity.
3. It specifies conformance obligations and a deterministic source-compilation enforcement strategy, then outlines adversarial tests that pair laundering resistance with utility and governance cost.

This is not a theory of all agent authority. Session instructions, organizational policy, access control, and action authorization remain distinct control planes. The contract governs the semantic authority of **persistent memory declarations**.

## 2. Closest Related Work

The comparison below is limited to verified properties of [1]–[14], not an exhaustive priority claim.

**Governed writes and evolving memory.** SSGM gates writes and filters reads before a mutable graph plus immutable episodic log [1]. MemArchitect calls governance active adjudication across lifecycle, consistency, retrieval, and efficiency [2]. GEM defines four state-level operators and six trajectory correctness conditions [3]. These are governed transitions; this contract gives capability-specific ratification a separate role.

**Versioning and belief revision.** Kumiho combines immutable revisions, `Supersedes` and `Depends_On` edges, current-view tags, audit trails, and published-item protection [4]. Here, neither current selection nor protected status issues a semantic capability; an exact `Grant` does.

**Approval and governed selection.** memorywire hides approval-required writes from recall pending review [5]. Governed Collaborative Memory moves ratified candidates into shared institutional state, preserves rejected and superseded outcomes, and separates archive retrieval from ratified lessons [6]. Ratified selection is prior art. Our narrower residual is exact revision/capability binding and use-time proof survival through derivation.

**Origin-bound authority and poisoning.** TMA-NM binds action authority to authenticated origin, propagates untrust, and gates consequential actions with machine-checked separation [7]. Among the cited works, it is the closest formal security neighbor because both make authority non-malleable under transformation. Its roots are origin plus controlled elevation or fresh authorization; ours is exact semantic ratification. A deployment may require both proofs.

**Correction propagation.** MEMOREPAIR separates influence edges from semantic retrieval, withdraws the affected cascade, and republishes validated predecessor-closed successors [8]. Our reduction closure applies a related shape to proof instances while preserving alternative proofs.

**Multi-principal governance.** GateMem jointly evaluates utility, contextual access control, and active forgetting in multi-principal memory [9]. These are complementary; access controls visibility and use, while a semantic grant controls accepted authority.

**Foundational security lineage.** Complete mediation, fail-safe defaults, and least privilege motivate serving and sink checks [12]. Biba and Denning motivate non-amplifying integrity propagation [10,11]. Proof-carrying code motivates consumer-checkable artifact proofs [13]. We claim neither these primitives nor ratification generally, only this exact composition.

The resulting position is narrower than "memory should be source code" and stronger than a status label: a conforming system must show the capability, revision, checkout, and surviving proof for each authority-sensitive use.

## 3. Problem Model

### 3.1 Five roles

The contract separates five frequently conflated roles:

- **Storage:** bytes persist. Storage grants no semantic authority.
- **Discovery:** content can be searched, ranked, or traversed. Discovery grants visibility, not authority.
- **Ratification:** an authenticated and auditable `Grant` event issues selected capabilities to an exact persistent semantic revision.
- **Declaration authority:** the revision is eligible to be used as an accepted assertion, guidance item, or constraint.
- **Serving:** a checked projection exposes authority and discovery lanes to an agent or trusted host.

A pending proposal is not queryable memory. An admitted but unratified declaration may be retained for discovery and review. Admission asks whether content is durable; ratification asks for which semantic use that exact content was accepted.

### 3.2 Root taxonomy

The word *root* is reserved for something that can independently justify a positive conclusion. The contract has four classes:

| class | members | permitted effect |
| --- | --- | --- |
| positive persistent-declaration issuance root | `Grant` | issue named `assert`, `guide`, or `constrain` capabilities for one exact reviewed semantic revision |
| persistent reduction events | `Revoke`, `Supersede`, `Redact` | remove a capability, currentness, or serving eligibility; never issue a capability |
| interpretation trusted computing base | compiler, schema/type descriptors, resolver, registered operators, proof verifier | determine meaning, compatibility, or proof validity; never ratify a declaration |
| non-persistent trusted roots | authenticated current-session input; host completeness attestation | authorize or attest only within the named session/check; never create persistent declaration authority |

`Grant` is the only positive persistent-declaration authority issuance root. Schema allowance is not issuance; compiler validity is not acceptance; operator proof is not ratification. A trusted session instruction may govern the current interaction but does not ratify stored content.

### 3.3 Capabilities, not a scalar score

Authority is a capability set, not a total order:

```text
Capability = { assert, guide, constrain }
```

- `assert` permits a revision to be presented as a principal-accepted assertion.
- `guide` permits it to influence preference-sensitive ranking or recommendations.
- `constrain` permits it to participate in standing-rule and compliance evaluation.

Action authorization is excluded. A fact that may be asserted does not authorize a payment, and guidance does not necessarily constrain behavior.

Schemas define an `AllowedCaps` ceiling. A `Grant` records immutable `issued_caps` that must be within the ceiling bound into its review record. Expanding `AllowedCaps` cannot enlarge an old event or awaken a rejected, dormant, or invalid capability; a new capability requires a new `Grant`.

Direct and delegated ratification use the same event type. A delegated grant names its policy, evaluator version, scope, quota, and actor. Revocation may remove one capability without removing others.

### 3.4 Semantic identity and review identity

Ratification cannot bind only a mutable identifier, and the authority ledger cannot feed source compilation without circularly defining the reviewed object. We therefore separate two digests.

Let `x = (d,r)` be an exact source declaration revision. Deterministic source compilation produces:

```text
SemDigest(Σ,x) = H("memdsl-sem-v1"
                     || canonical_source(x)
                     || exact_resolved_semantic_references(Σ,x)
                     || exact_manifest_revision(Σ,x)
                     || relevant_schema_and_type_digests(Σ,x)
                     || resolver_contract_version
                     || relevant_registered_semantics_versions)

ReviewDigest(Σ,x,C,W) = H("memdsl-review-v1"
                           || SemDigest(Σ,x)
                           || requested_and_issued_caps(C)
                           || evidence_and_provenance_manifest(W)
                           || ratification_policy_and_evaluator_version(W)
                           || review_scope_and_rationale(W))
```

`SemDigest` identifies the proposition under a declared interpretation contract. `ReviewDigest` identifies the capability request, evidence package, and decision policy actually reviewed. A `Grant` binds both. Review records and ledger events do not feed back into `SemDigest`; `Σ = Compile(S,I)` depends on source `S` and versioned interpretation inputs `I`, not authority history.

Resolved semantic references bind exact immutable revisions or manifest entries, not "whatever is current." Currentness is decided later, so supersession does not recursively change referring digests. In v1, exact target-revision references are acyclic; legitimately cyclic relation classes bind stable identities under a versioned contract. A canonical fixpoint digest would require a new digest version.

Only meaning-changing versions or digests belong in `SemDigest`; operators used only for a later view belong in that view's proof. Every digest change must be attributable to an exact source, reference, manifest, schema, resolver, or registered-semantics dependency.

### 3.5 One governance ledger and two frontiers

The authority contract uses one append-only, authenticated authority-governance ledger:

```text
GovEvent ::= Grant(id, SemDigest, ReviewDigest, issued_caps, scope, actor, ...)
           | Revoke(target_grant_or_revision, caps, scope, actor, ...)
           | Supersede(old_exact_revision, new_exact_revision,
                       resolution_witness, actor, ...)
           | Redact(exact_revision, redaction_scope, actor, ...)
```

All event kinds have explicit genesis authority, delegation, signatures, ordering, and replay protection. Supersession and redaction cannot arrive through unnamed side channels.

A named checkout is:

```text
E = (checkout_id, Σσ, p, h, principal, as_of, policy_versions)
```

`Σσ` is the compiled result for exact source/interpretation revision `σ`. The lineage binds `Σσ`, `p`, principal, time, and policy versions; `checkout_id` also binds effective frontier `h`. The **base prefix** `p` admits only grants committed at or before `p`. The **reduction frontier** `h ≥ p` applies valid reductions through `h`. A `Grant` in `(p,h]` is ignored until a new checkout advances `p`, although the same tail may reduce an older proof.

A tail `Supersede` is overlay-admissible only when both revisions and its witness verify against `Σσ`; unseen or ambiguous source cannot suppress an old revision. If withdrawal precedes successor compilation, exact `Revoke` or `Redact` reduces the old revision and replacement remains a separate grant decision.

Here **immediate** means that after a reduction commits, the next online serve or authority-sensitive sink check must apply an authenticated overlay through the latest frontier or reject the stale checkout. It is not retroactive removal from a completed response and cannot admit a post-`p` grant.

## 4. Review-Gated Authority Contract

### 4.1 Three judgment layers

Let `x = (id(d), SemDigest(Σσ,d,r))`, capability `c`, and trusted task context `q`. For a declaration revision, `digest(x)` denotes the `SemDigest` component of `x`.

First, `RatifiedCap` asks whether an issued capability survives through the checkout's reduction frontier, without claiming structural usability or currentness:

```text
RatifiedCap(E,x,c,q) ⇔ ∃ g = Grant(x, ..., issued_caps, scope, ...) at index i ≤ p
                         such that c ∈ issued_caps
                         ∧ scope_allows(g,q)
                         ∧ valid_event(g)
                         ∧ no matching Revoke after g and at or before h
```

A revoke can target one grant proof or all grants for exact `(x,c,scope)` through a named cut. Other capabilities and independent grants survive.

Second, `ServeEligible` combines that surviving capability with the named compiled checkout:

```text
ServeEligible(E,x,c,q) ⇔ RatifiedCap(E,x,c,q)
                         ∧ present_in(x,Σσ)
                         ∧ structurally_valid(Σσ,x)
                         ∧ current_under_reductions(x,h)
                         ∧ not_redacted(x,h)
                         ∧ c ∈ AllowedCaps(Σσ,x)
```

`AllowedCaps` is a ceiling and veto, never an issuance source. Source `supersedes` may nominate a relation and let compilation construct a witness; only a valid exact `Supersede` event changes `current_under_reductions`.

Third, `Verify` checks one proof instance `π` at an authority-sensitive sink. `Advance(E,h_now)` retains `Σσ`, `p`, principal, and policy versions, validates reductions through `h_now`, and produces `E_now`:

```text
Verify(E,π,o,c,q,h_now) ⇔ E_now = Advance(E,h_now)
                          ∧ h_now ≥ h
                          ∧ checkout_lineage(π) = lineage_id(E)
                          ∧ verified_frontier(π) ≤ h_now
                          ∧ π verifies recursively under E_now
                          ∧ bound_output_digest(π) = digest(o)
                          ∧ every declaration leaf is ServeEligible(E_now,...)
```

If `h_now > h`, the verifier advances only by validating reductions in `(h,h_now]`; grants there remain ineligible because `p` is fixed. Success emits a receipt bound to `checkout_id(E_now)` and `h_now`. If the latest frontier or a valid event cannot be obtained, the sink rejects. Another-lineage or unrechecked proofs are invalid.

Thus an old grant is not automatically servable, a servable declaration is not valid at a stale sink, and a valid computation is not a ratified declaration.

### 4.2 Proof objects: declaration authority versus computed validity

The proof language distinguishes conclusions:

```text
DeclProof ::= GrantProof(grant_event_id, id, SemDigest, ReviewDigest,
                         capability, checkout_lineage_id, verified_frontier)

ViewProof ::= ProjectProof(source_object, source_proof,
                           projection_id_and_version, output_digest)
            | ComputeProof(operator_id_and_version, output_digest,
                           input_proof_ids, complete_read_set,
                           dependency_witness, anti_dependency_witness,
                           schema_policy_dependencies,
                           completeness_witness?)
```

`GrantProof` proves persistent **declaration authority** for one exact revision and capability; it is the only positive root.

For `GrantProof`, the bound object digest is its `SemDigest`; `ProjectProof` and `ComputeProof` bind their explicit `output_digest` fields.

`ProjectProof` presents the same semantic object under the same surviving proof. `Project` is a registered, single-object, semantics-preserving transformation such as complete-field selection or lossless serialization; it cannot omit a qualifier or combine objects. Cross-object sorting, ranking, top-k, aggregation, and joins are `Compute` when fully witnessed, otherwise discovery. A truncated excerpt is discovery-only.

`ComputeProof` proves **computed validity**, not ratification. It binds a registered operator version, output digest, normalized read set, positive dependencies, domain and anti-dependencies, schema/policy versions, and any required closed-domain completeness witness. Supplied inputs are dependency-relevant unless an external checker proves exclusion.

Computed output capabilities are use bounds, not newly issued declaration capabilities:

```text
ComputedCaps(π) ⊆ operator_output_caps
                  ∩ output_schema_caps
                  ∩ capabilities required and supplied by π's valid input proofs
```

An empty input set cannot yield persistent declaration capability. A zero-count, negative, or empty-selection result needs a valid named-domain completeness witness for computed validity. A persisted computed result starts unratified and needs a new `Grant` over its own digests.

### 4.3 Reduction closure over proof instances

Invalidation is defined over a DAG of **proof instances**, not object names. Each `π` records positive `Deps(π)`, domain or `AntiDeps(π)`, and versioned `InterpDeps(π)`.

```text
Invalid(E,π,h) ⇔ checkout_or_frontier_mismatch(E,π,h)
                 ∨ exact_output_digest_mismatch(π)
                 ∨ revoked_capability_leaf(π,h)
                 ∨ superseded_or_redacted_leaf(π,h)
                 ∨ ∃ρ ∈ Deps(π): Invalid(E,ρ,h)
                 ∨ anti_dependency_or_domain_witness_changed(π,E,h)
                 ∨ operator_schema_policy_or_completeness_dependency_invalid(π,E,h)
```

This closure permits capability-specific revocation and explicit replacement proofs: invalidating a `constrain` leaf need not invalidate an independent `assert` proof or another proof instance.

```text
DeclarationAuthority(E,x,c,q,h) ⇔ ∃ π = GrantProof(...) proving (x,c)
                                      such that ServeEligible(E,x,c,q)
                                      ∧ ¬Invalid(E,π,h)
                                      ∧ Verify(E,π,x,c,q,h)

ComputedValid(E,o,c,q,h) ⇔ ∃ π ∈ {ProjectProof, ComputeProof} proving (o,c)
                              such that ¬Invalid(E,π,h)
                              ∧ Verify(E,π,o,c,q,h)
```

The first judgment terminates at `GrantProof`; the second terminates at `ProjectProof` or `ComputeProof` and does not ratify `o`. The existential preserves independent grants and alternative computation proofs. Every replacement must be explicit and independently verifiable; object equality alone creates no proof.

Top-k and absence claims depend on a declared candidate domain, non-selected competitors, ordering contract, and completeness frontier. Changes to those witnesses invalidate the proof until recomputation. Completeness beyond a mechanically closed declared domain is outside the core; a host may add a versioned authenticated attestation bound to the checkout and verifier.

### 4.4 Retrieval, derivation, and path neutrality

Retrieval paths neither grant nor remove authority. An unratified edge may discover a ratified endpoint, and an unratified endpoint remains so when reached through a ratified neighborhood. Source relations enter computation only when the operator admits their class and the dependency witness binds them.

Generative summaries, merges, reinterpretations, and free-form synthesis cannot construct `ProjectProof` or `ComputeProof`. Their outputs are born unratified even when every input was ratified. Provenance does not replace acceptance.

### 4.5 Currentness, redaction, and erasure

Currentness has two steps. Source compilation checks that a `supersedes` nomination names exact revisions without ambiguity, forbidden cycle, or identity error. The nomination alone has no authority effect. An authenticated `Supersede` reduction then names the old and new exact revisions plus that witness. It may remove the old revision from current authoritative views, but it does not grant the successor any capability.

Redaction is also layered:

1. **Semantic acceptance** is expressed only by `Grant` and remains auditable in history.
2. **Logical redaction** is an authenticated `Redact` reduction that removes the exact revision from applicable serving and proof leaves at the next checked use.
3. **Physical erasure** is a storage/retention operation that may destroy bytes while retaining an allowed tombstone and audit linkage.

These operations are not synonyms. Revoking authority need not erase source; redacting serviceability need not prove every copy has been physically erased; physical erasure must not fabricate a new semantic history. Descendant erasure beyond the proof DAG requires an explicit host retention policy and is not claimed automatically.

### 4.6 Invariants

A conforming implementation maintains:

1. **Proposal isolation:** pending proposals are not queryable memory.
2. **Single positive root:** only a valid `Grant` issues persistent declaration capabilities.
3. **No interpretation-root elevation:** compiler, schema, resolver, operator, retrieval, and confidence can veto or verify, but cannot grant.
4. **Checkout-bound use:** every authority-sensitive use verifies a proof against a named checkout, fixed grant prefix, and latest reduction frontier.
5. **Non-amplifying derivation:** projection preserves one source proof; computation yields only computed validity; generative output is unratified.
6. **Proof-instance reduction closure:** reductions and dependency changes invalidate affected proof instances, while an object survives only through another explicit valid proof.
7. **No dormant wake-up:** schema-ceiling expansion, relinking, recompilation, or operator upgrades cannot activate a capability absent from an exact valid grant.

Ratification means "the principal accepted this for the stated capabilities," not "this is objectively true." Freshness and truth maintenance remain separate problems.

## 5. Source Compilation as an Enforcement Strategy

The authority contract does not depend on a unique storage or compiler architecture. The following four-stage design is one deterministic enforcement strategy. Source compilation remains independent of the authority ledger and never becomes an issuance root:

```text
Declaration source Sσ + interpretation inputs Iν
        │ deterministic Compile(Sσ,Iν)
        ▼
CompiledWorkspace Σσ
  - resolved identifiers and exact revision references
  - schema/type checks and SemDigests
  - dependency indexes and diagnostics
        │ combine with L_auth base prefix p and reduction frontier h
        ▼
Named checkout E(Σσ,p,h,...)
  - RatifiedCap fold
  - current/redacted/structural classification
  - declaration and computed proof instances
        │ query + use-time Verify + fixed budget
        ▼
Context slice / proof-checked sink input
  [authority lane] [discovery lane] [proofs, omissions, cursors]
```

`CompiledWorkspace` is a rebuildable interpretation product, not an authority root. At least two passes prevent declaration order from changing reference resolution. Identity ambiguity, forbidden exact-reference cycles, incompatible schemas, and unresolved authority-relevant references quarantine affected identities and proofs; local non-authority errors may remain local.

Serving reads a named checkout, not raw parsed files. Before every authority-bearing response or sink action, `Verify` obtains the latest authenticated reduction frontier. A stale snapshot continues only if intervening state is proven grant-only or availability-only; unresolved reductions fail closed. Tail grants remain beyond `p`, so this path cannot become an incremental grant channel.

Context is budgeted independently from source size. Discovery projections may truncate with omission metadata and dereference actions. The core recognizes completeness only for a mechanically closed declared domain; stronger completeness requires a host attestation naming the domain, checkout, policy, checker, and frontier.

### 5.1 Conformance boundary

A conforming implementation that claims **authority-channel integrity** MUST satisfy these obligations:

- authority lanes MUST contain only declarations with verified `GrantProof` leaves or computed views with surviving proof instances;
- proof-checked sinks MUST reject missing, stale, wrong-checkout, wrong-output, incompatible-capability, or reduced proofs;
- conforming sinks MUST NOT cite or accept an unratified persistent declaration as declaration authority.

These obligations apply to structured service envelopes and proof-checked sink records. They do not imply that free-form model text is semantically faithful. Discovery content sharing a model context may influence behavior even when labeled unratified; labels are prompts, not information-flow control. Architectural separation that keeps untrusted-data processing away from privileged planning and checks data/control-flow policy at execution is a relevant stronger deployment pattern [14]. Adapting that separation into distinct memory discovery, review, and execution phases is future work, not part of the formal core.

### 5.2 Trusted computing base

Conformance is relative to a trusted computing base containing:

- integrity monitoring for source, interpretation inputs, and the append-only governance ledger;
- authenticated grant and reduction actors with versioned delegation rules;
- the compiler, schema/type descriptors, resolver, and registered operator implementations;
- the serving reference monitor and sink proof verifier;
- complete dependency capture for proof-bearing computations;
- authenticated session inputs or completeness attestations when a host uses those non-persistent extensions.

An adversary may author candidates, influence generative outputs, propose malicious revisions, and control some tool returns. It may not forge governance actors or task context, alter committed events, undetectably substitute registered components, or bypass the reference monitor. Outside these assumptions, the contract is only a protocol among honest components.

## 6. Reference Implementation Target: memdsl

The implementation status is deliberately split by immutable tag or commit:

| status | exact evidence | scope |
| --- | --- | --- |
| shipped software | tag `v0.6.0`, commit `72274d9d4f065b76bceaf30f529dcbd47b3f3e18` | public 0.6.0 baseline |
| stable/public implementation line | Phase -1 through Phase 5, integrated by `4ee810833ef0cbd8562e72e3ad202a07c5ce77e8` | Source/review authority boundary, public `CompiledWorkspace`, Catalog, Query, Trace, exact `use`, Dialect, and opt-in quarantine/`ResolvedView` |
| experimental Phase 6 | `6bc3ffd986b1ffe29cefa928642fd0cf47e5c2c9`, reconciled by `4ec9d43fda56a277609dd822c61acdb9a7265655` | opt-in workspace-v3 explicit Edge records/events/evidence/lifecycle and permanent human-review floor; not stable and not paper-authority conformance |
| unreleased local candidate | `0.9.0.dev0` release-scope freeze after `4ec9d43fda56a277609dd822c61acdb9a7265655` | local implementation and release evidence only; no remote release or deployment claim |
| deferred implementation | current release-scope freeze | Phase 7 cold-history/incremental compilation, automatic dialect learning, automatic Edge candidates, and the paper authority runtime |
| planned paper contract | manuscript source `3535bfb9661724818011f4bf2823ed09e895069a` plus this metadata revision | `L_auth`, digest-bound grants, proofs, live reduction closure, and checked sinks |

memdsl is a **reference implementation target**, not a conforming implementation. The candidate lacks the ledger, `(p,h)` checkouts, digest-bound grants, proof objects, live reduction closure, and `Verify` sinks. Legacy `active` declarations are not silently ratified. The [artifact manifest](PAPER_reproducibility_and_release_metadata.md) gives the exact mapping and synthetic baseline; the practical [source/compiled-view design](DESIGN_memory_source_compiled_view.md) remains a separate companion.

### 6.1 Anonymous Phase 6 engineering observation

The reference-implementation line includes one anonymous, single-principal
exploratory follow-up over proposed explicit Edges. The first completed human
batch produced `accept=7`, `uncertain=3`, and `reject=0`. The uncertain items
were invalid or unreviewable source contamination rather than negative Edge
judgments. The observation supports a narrow **ADJUST** conclusion:
independently reviewable Edges can be useful, while automatic candidate
coverage, relation choice, and evidence stability remain insufficient for
automatic activation.

This is not a comparative result, a human-subjects study, a representative
sample, or evidence for the paper's grant/proof contract. Selection and
extraction preceded review; the sample is small and single-principal;
contamination was excluded from the Edge denominator; `supersedes` received no
direct human validation; and no production queue-economics or cross-workspace
generalization is available. Host-specific extraction and sanitization gates
remain outside the memdsl artifact and do not block the generic local release
candidate.

## 7. Evaluation

An empirical version should test synthetic, adversarial, and representative workloads. Leakage metrics must be paired with utility; returning nothing is not a successful defense.

### 7.1 Serving conformance

Tests make admitted unratified declarations maximally relevant to authority-bearing queries and measure:

- **Authority-Lane Leakage:** unratified persistent declarations in the authority lane;
- **Invalid Proof Acceptance:** stale, wrong-revision, wrong-checkout, wrong-output, incompatible-capability, or forged proofs accepted by a sink;
- **Frontier Replay Acceptance:** a proof accepted without the latest authenticated reduction frontier;
- **Grant-Base Bypass:** a post-`p` grant becoming effective before a new checkout;
- **Reduction Latency:** time from committed `Revoke`, `Supersede`, or `Redact` to the next checked serving effect;
- **Dependent-Proof Leakage:** a proof instance remaining valid after a required leaf, anti-dependency, operator, schema, policy, or completeness witness is invalidated;
- **Authoritative Recall** and **False Quarantine Rate**.

Leakage targets are zero by construction. These are conformance tests, not comparative results.

### 7.2 Authority-laundering attacks

The adversarial suite includes:

- summaries over mixed ratified and unratified inputs;
- persistence of a computed result as if it were already a ratified declaration;
- single-object `Project` claims that secretly omit qualifiers or combine objects;
- cross-object top-k without a complete read set or anti-dependency witness;
- empty-input or negative-result computations without a completeness witness;
- ratify-then-change, ratify-then-relink, and ratify-then-change-schema attacks;
- schema-ceiling expansion intended to wake an old invalid capability;
- capability-specific revocation with both dependent and independent alternative proofs;
- source `supersedes` nomination without an authenticated exact reduction.

Primary metrics are **Authority Laundering Rate**, computed-view availability, authoritative recall, and ratification turnaround.

### 7.3 Deployment and secondary engineering evaluation

For standing-rule creation, preference modification, and compliance verdicts, measure unauthorized citation or constraint adoption, task success, sink availability, and review load. Compare labels-only and phase-separated deployments separately; visible discovery influence is a cognitive-interference diagnostic, not automatically an authority-channel violation.

Baselines should include plain RAG, labels without enforcement, admission approval, automated write validation without a ratification root, lifecycle-only compiled views, and the full contract. Phase separation is a separate comparison; reimplementations need an explicit capability checklist.

Scale, compile/query and proof-verification latency, context size, and projection recall are secondary measures. Host completeness attestations remain a separately identified extension.

## 8. Limitations

**Ratified does not mean true.** A principal may accept a false or stale proposition. Freshness can prioritize re-review, but silence after use is not a correctness verdict.

**Dependency capture is part of conformance.** Uninstrumented derivation or raw-file access can bypass proof construction. A conforming high-assurance deployment must route authority-bearing reads and writes through the reference monitor.

**Approval can become ceremonial.** Proposal volume may cause reflexive approval. Delegation, quotas, prioritization, and review-load measurement do not eliminate the attention bottleneck.

**Digest stability is an engineering problem.** `SemDigest` must cover meaning-changing dependencies without reacting to unrelated registry changes. `ReviewDigest` must bind what was reviewed without making routine audit metadata constitutive. No universal canonicalization algorithm is claimed.

**Completeness is relative.** The core recognizes only mechanically named closed domains. Stronger attestations are host extensions bound to a checkout, frontier, policy, and verifier; no completeness over the external world is claimed.

**Redaction is not automatic lineage erasure.** Copied text, independent declarations, and prior generative summaries may require separate retention policy.

**The contract governs persistent memory only.** Equivalent content can re-enter through conversation, model weights, or tools. Session and action authorization remain separate roots.

## 9. Discussion: Memory as Source Code

The architecture admits a source-code reading: declarations are reviewable source; semantic and review digests bind meaning and decision packets; compilation gates interpretation; governance events preserve accountable history; and bounded queries replace whole-store maps.

The analogy is not the contribution. Memory can become false while its bytes remain unchanged, and memory links cost a present writer for a future reader. Compilation therefore cannot establish truth; review, freshness pressure, and governance economics remain necessary.

## 10. Conclusion

**Persistence should not imply authority.** An admitted declaration may remain discoverable without becoming a principal-accepted assertion, preference, or constraint. `Grant` is the only positive root of persistent declaration authority. Reductions only reduce; interpretation components only interpret or verify; session inputs and completeness attestations remain non-persistent roots.

`RatifiedCap`, `ServeEligible`, and `Verify` make the boundary operational across ledger history, compiled checkout state, and use-time proof checks. Projection preserves one proof; computation yields proof-bearing validity rather than a second authority root; generation remains unratified. Computed validity survives only through an explicit surviving proof instance.

Source compilation does not prove memory true or issue authority; it is an enforcement strategy that makes stored, discoverable, accepted, current, and computed states deterministic and auditable. The semantic authority a principal grants to persistent memory deserves a non-malleability discipline analogous to origin-bound action authority [7].

## Declarations

`liyuan` and Independent Researcher are placeholders; no institution, email, ORCID, DOI, funding, or COI conclusion is asserted pending author confirmation. OpenAI Codex assisted with repository inspection, drafting, consistency checks, and local verification; the human author remains responsible for claims and publication. No human-subjects study is reported. The only human-reviewed engineering observation is the anonymous aggregate in Section 6.1; the artifact contains no private memory workspace, row-level evidence, identifier mapping, or personal dataset.

## References

[1] Chingkwun Lam, Jiaxin Li, Lingfei Zhang, and Kuo Zhao. “Governing Evolving Memory in LLM Agents: Risks, Mechanisms, and the Stability and Safety Governed Memory (SSGM) Framework.” arXiv:2603.11768, 2026.

[2] Lingavasan Suresh Kumar, Yang Ba, and Rong Pan. “MemArchitect: A Policy Driven Memory Governance Layer.” arXiv:2603.18330, 2026.

[3] Abdelghny Orogat and Essam Mansour. “Is Agent Memory a Database? Rethinking Data Foundations for Long-Term AI Agent Memory.” arXiv:2605.26252, 2026.

[4] Young Bin Park. “Graph-Native Cognitive Memory for AI Agents: Formal Belief Revision Semantics for Versioned Memory Architectures.” arXiv:2603.17244, 2026.

[5] Thamilvendhan Munirathinam. “memorywire: A Vendor-Neutral Wire Format for Agent Memory Operations.” arXiv:2606.01138, 2026.

[6] Diego F. Cuadros, Abdoul-Aziz Maiga, Helen Meskhidze, and Andre Curtis-Trudel. “Governed Collaborative Memory as Artificial Selection in LLM-Based Multi-Agent Systems.” arXiv:2605.04264, 2026.

[7] Yedidel Louck. “Securing LLM-Agent Long-Term Memory Against Poisoning: Non-Malleable, Origin-Bound Authority with Machine-Checked Guarantees.” arXiv:2606.24322, 2026.

[8] Yang Zhao, Chengxiao Dai, Mengying Kou, and Yue Xiu. “MEMOREPAIR: Barrier-First Cascade Repair in Agentic Memory.” arXiv:2605.07242, 2026.

[9] Zhe Ren, Yibo Yang, Yimeng Chen, Zijun Zhao, Benshuo Fu, Zhihao Shu, Bingjie Zhang, Yangyang Xu, Dandan Guo, and Shuicheng Yan. “GateMem: Benchmarking Memory Governance in Multi-Principal Shared-Memory Agents.” arXiv:2606.18829, 2026.

[10] Kenneth J. Biba. “Integrity Considerations for Secure Computer Systems.” MITRE Technical Report MTR-3153-REV-1 / ESD-TR-76-372, DTIC ADA039324, 1977.

[11] Dorothy E. Denning. “A Lattice Model of Secure Information Flow.” Communications of the ACM 19(5):236–243, 1976. doi:10.1145/360051.360056.

[12] Jerome H. Saltzer and Michael D. Schroeder. “The Protection of Information in Computer Systems.” Proceedings of the IEEE 63(9):1278–1308, 1975. doi:10.1109/PROC.1975.9939.

[13] George C. Necula. “Proof-Carrying Code.” Proceedings of the 24th ACM SIGPLAN-SIGACT Symposium on Principles of Programming Languages (POPL '97), pp. 106–119, 1997. doi:10.1145/263699.263712.

[14] Edoardo Debenedetti, Ilia Shumailov, Tianqi Fan, Jamie Hayes, Nicholas Carlini, Daniel Fabian, Christoph Kern, Chongyang Shi, Andreas Terzis, and Florian Tramèr. “Defeating Prompt Injections by Design.” arXiv:2503.18813, 2025.
