# memdsl 0.9.0 Software Release and Publication-Boundary Audit

**Audit date:** 2026-07-16<br>
**Release line:** `0.9.0` software release; experimental Edge remains opt-in<br>
**Paper/candidate baseline:** `4ee810833ef0cbd8562e72e3ad202a07c5ce77e8`<br>
**Experimental Edge implementation:** `6bc3ffd986b1ffe29cefa928642fd0cf47e5c2c9`<br>
**Human-review reconciliation:** `4ec9d43fda56a277609dd822c61acdb9a7265655`<br>
**LF exact-byte remediation:** canonical clean-checkout baseline hashes were
re-frozen in the final local commit containing this receipt

## Scope and ancestry

This audit supersedes the old local artifact receipt as the current release
boundary without rewriting its history. The three commits above form a direct
linear parent chain. The earlier paper integration correctly kept practical
Phase 6 out of the 0.8 candidate at that time; the later Phase 6 implementation
was separately authorized and remains an opt-in experiment.

The practical source/compiled-view specification and the focused authority
paper remain side by side. The experimental Edge implementation does not add
the paper's authority ledger, digest-bound grants, proof objects, live
reduction closure, or proof-checked `Verify` sinks. memdsl remains a reference
implementation target rather than a conforming paper-authority runtime.

## Frozen release matrix

| Classification | Current release |
| --- | --- |
| Stable/public | Source authority; proposal/review/approval; append-only audit and pending isolation; public rebuildable `CompiledWorkspace` / `compile_workspace`; v1/v2 Catalog, Query, List, Explain, Check, Trace, Map compatibility, workspace schemas, and existing public API contracts |
| Experimental | workspace v3; `features.explicit_edges="experimental-v1"`; `relation_edge` / `explicit_edge`; Edge events, evidence, lifecycle, list/explain/Trace, and dedicated CLI confirmation; all four built-in Edge descriptors |
| Hard floor | `relation_edge`, `explicit_edge`, `relation_edge_event`, `explicit_edge_event`, and `edge_lifecycle` always require a person; schemas/policies cannot auto-approve them; `related` is discovery-only; explicit `supersedes` is graph-only |
| Planned / not shipped | automatic dialect learning, automatic Edge candidates, inferred authoritative edges, stable Edge promotion, Phase 7 cold-history/incremental compilation, and the paper authority runtime |
| Host-specific / excluded | extraction and sanitization pipelines, private schemas/policies/samples/workbooks, identifiers and path mappings, UI, and runtime adapters; host shadow activation is not a memdsl release gate |

The complete normative matrix is
[RELEASE_SCOPE_PHASE6.md](RELEASE_SCOPE_PHASE6.md).

## Anonymous exploratory evidence and limits

The first completed human follow-up batch produced `accept=7`, `uncertain=3`,
and `reject=0`. The uncertain items were invalid or unreviewable source
contamination, not Edge negatives. The evidence supports an **ADJUST** outcome:
independently reviewable Edges can be useful, but automatic candidate coverage,
relation selection, and evidence stability are not ready for automatic
activation.

Threats to validity include the single-principal setting, ten-item batch,
pre-review host selection/extraction, exclusion of contamination from the Edge
denominator, no direct human validation of `supersedes`, no representative
cross-workspace sample, and no production queue-economics evidence. No claim of
automatic extraction, automatic Edge generation, complete private-memory
understanding, comparative effectiveness, or mechanized security follows.

## Local verification record

| Gate | Result |
| --- | --- |
| Full regression | `404 passed`; `0 xfail` |
| Focused Phase 6 | `47 passed` |
| Focused release/static/public API | `7 passed` (`54 passed` when run together with Phase 6) |
| Compile | `compileall -q src tests scripts` passed |
| Python compatibility | Python 3.9 AST gate passed for 22 source files |
| Dependency integrity | `pip check`: no broken requirements |
| Version contract | `0.9.0` across project, runtime, tests, and CI |
| Fixed build epoch | `SOURCE_DATE_EPOCH=1784077269` |
| Exact-commit source bytes | Two new independent clean roots from the commit containing this receipt reported the same tracked-source digest; all 109 tracked files used canonical LF bytes |
| Build backend | Hatchling `1.31.0` exactly pinned in build-system and release environment; both builds used `python -m build --no-isolation` after the toolchain gate |
| CLI / MCP inspect / real stdio | lint-demo produced the expected 2 errors / 3 warnings / exit 1; Query, Explain, Catalog, Trace, MCP inspect, and Phase 3-6 stdio passed |
| Scoped denial and gated write | 23 targeted stdio, denial, pending-isolation, approval/confirmation, and review-floor cases passed |
| Synthetic scale/security gates | 20 targeted bounded-scale, fail-closed, hidden-data, invalid-event, and no-auto-approval cases passed |
| Canonical frozen baselines | Exact LF-byte SHA-256 values are `fad66899ce0e795efdbd0d3691d24d4b85414f4627c75d06abe826e165dbeca8`, `acb80fb9413f58944597b9f71b4f8e5ff71dd4a94ca91479c12982cb226c855d`, and `6d37c9f3eb55e35e8a8a7e40d6cd20bc59654b6d3f2d7d822c2b9d2a1b25b574`; no normalized-hash substitution is used |
| CFF / paper / links / privacy | isolated `cffconvert==2.0.0` validation passed; 14 references, 24 claim rows, 5,250 manuscript words, links, license, privacy, and frozen paper plus exact-byte LF baseline hashes passed |
| Twine and archive membership/privacy | Twine passed; wheel 44 members, sdist 108 members; required-member, host-marker, and privacy scans passed |
| Reproducible double build | two independent final-commit clean roots with the same source digest and fixed epoch produced byte-identical wheel and sdist SHA-256 values |
| Fresh wheel | imported from temporary `Lib/site-packages`; 17 installed docs; dependency, CLI, MCP inspect, v1/v2 stdio, scope denial, and workspace-v3 Edge CLI/MCP/stdio passed |
| Diff and clean-state checks | `git diff --check` passed; protected launch article absent from this worktree and staging; the release commit left the worktree clean |

The fresh-wheel gate must prove that `memdsl.__file__` is inside the temporary
environment's `site-packages`, not the repository or editable source tree. It
must also verify the installed documentation set and the workspace-v3 Edge
CLI/MCP/stdio contract.

## Final local archives

The final wheel and sdist were built in two new, independent clean source roots
from the commit containing this receipt. Both roots passed the canonical
source-byte and exact-backend gates, used the frozen epoch, and matched byte
for byte. This receipt remains excluded from both archives, so recording the
result does not create a self-referential artifact hash.

| Archive | Bytes | Members | SHA-256 |
| --- | ---: | ---: | --- |
| `memdsl-0.9.0-py3-none-any.whl` | 330,980 | 44 | `a2c488b5e67c71b4d660a42ec64aa5d70fb27377c5bab3a43b0d0f7a19ec10ae` |
| `memdsl-0.9.0.tar.gz` | 428,649 | 108 | `039d4736d2cd0d3670174d837eca0dd9fbaeb43fb7e06306f482705eb750c752` |

Both archives must include the documentation index, practical design, explicit
Edge design, release-scope freeze, SPEC, PUBLIC_API, UPGRADING, focused paper,
claim ledger, reproducibility metadata, readiness audit, paper license,
`CITATION.cff`, software license, frozen baselines, and synthetic benchmark.

Both archives must exclude this receipt, repository-local agent instructions,
the protected checkout-only launch article, real memory workspaces outside
explicit synthetic fixtures, review stores, approved memory, workbooks,
environment files, credentials, keys, caches, databases, backups, logs, and
machine-specific absolute paths.

## Protected-file and privacy result

The checkout-only launch article remains outside this worktree's modifications,
staging set, commit, and archives. No private source text, row-level evidence,
identifier mapping, workbook content, private schema/policy, or host-specific
runtime path is included in this audit or the release artifacts.

## Decision

- **GO:** the `0.9.0` software release passes the
  frozen implementation, canonical LF exact-byte baselines, compatibility,
  paper-boundary, exact-commit reproducibility, archive, privacy, and
  fresh-install gates in this window.
- **GO after explicit user authorization:** fast-forward main, tag `v0.9.0`,
  GitHub Release, and PyPI software publication may proceed only after the
  final exact-commit verification in this receipt.
- **NO-GO:** Zenodo, DOI, deployment, private-data activation, or public paper
  submission in this software-release scope.
- **NO-GO:** describing experimental Edges as stable, automatic, or proof that
  private-memory extraction is solved.
- **NO-GO:** describing memdsl as implementing the paper authority runtime.

Remote software state is external evidence and must be verified after push;
this source receipt does not claim that a remote action succeeded merely
because it was authorized.
