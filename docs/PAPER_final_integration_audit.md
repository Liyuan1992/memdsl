# Phase 6 Mainline Local Release and Publication-Boundary Audit

**Audit date:** 2026-07-15<br>
**Release line:** local `0.9.0.dev0` candidate<br>
**Paper/candidate baseline:** `4ee810833ef0cbd8562e72e3ad202a07c5ce77e8`<br>
**Experimental Edge implementation:** `6bc3ffd986b1ffe29cefa928642fd0cf47e5c2c9`<br>
**Human-review reconciliation:** `4ec9d43fda56a277609dd822c61acdb9a7265655`

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

| Classification | Current local candidate |
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
| Full regression | `403 passed`; `0 xfail` |
| Focused Phase 6 | `47 passed` |
| Focused release/static/public API | `6 passed` (`53 passed` when run together with Phase 6) |
| Compile | `compileall -q src tests scripts` passed |
| Python compatibility | Python 3.9 AST gate passed for 22 source files |
| Dependency integrity | `pip check`: no broken requirements |
| Version contract | `0.9.0.dev0` across project, runtime, tests, and CI |
| Fixed build epoch | `SOURCE_DATE_EPOCH=1784077269` |
| CLI / MCP inspect / real stdio | lint-demo produced the expected 2 errors / 3 warnings / exit 1; Query, Explain, Catalog, Trace, MCP inspect, and Phase 3-6 stdio passed |
| Scoped denial and gated write | 23 targeted stdio, denial, pending-isolation, approval/confirmation, and review-floor cases passed |
| Synthetic scale/security gates | 20 targeted bounded-scale, fail-closed, hidden-data, invalid-event, and no-auto-approval cases passed |
| CFF / paper / links / privacy | isolated `cffconvert==2.0.0` validation passed; 14 references, 24 claim rows, 5,250 manuscript words, links, license, privacy, and frozen hashes passed |
| Twine and archive membership/privacy | Twine passed; wheel 44 members, sdist 107 members; required-member, host-marker, and privacy scans passed |
| Reproducible double build | two fixed-epoch builds produced byte-identical wheel and sdist SHA-256 values |
| Fresh wheel | imported from temporary `Lib/site-packages`; 17 installed docs; dependency, CLI, MCP inspect, v1/v2 stdio, scope denial, and workspace-v3 Edge CLI/MCP/stdio passed |
| Diff and clean-state checks | `git diff --check` passed; protected launch article absent from this worktree and staging; the release commit left the worktree clean |

The fresh-wheel gate must prove that `memdsl.__file__` is inside the temporary
environment's `site-packages`, not the repository or editable source tree. It
must also verify the installed documentation set and the workspace-v3 Edge
CLI/MCP/stdio contract.

## Final local archives

The final wheel and sdist were built twice with the frozen epoch. Both builds
matched byte for byte.

| Archive | Bytes | Members | SHA-256 |
| --- | ---: | ---: | --- |
| `memdsl-0.9.0.dev0-py3-none-any.whl` | 332,519 | 44 | `662233cc14d4688de728f61d162e7403f1cdd898780f0114d2f976eb0e51aaac` |
| `memdsl-0.9.0.dev0.tar.gz` | 429,685 | 107 | `ba94d0281f0a870d5f228b6d4143d974caf7918f0d4c0299f76dd117e8155a14` |

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

- **GO:** the local `0.9.0.dev0` Phase 6 mainline release candidate passes the
  frozen implementation, compatibility, paper-boundary, reproducibility,
  archive, privacy, and fresh-install gates in this window.
- **NO-GO:** push, tag, GitHub Release, PyPI, Zenodo, DOI, deployment, or public
  paper submission in this window.
- **NO-GO:** describing experimental Edges as stable, automatic, or proof that
  private-memory extraction is solved.
- **NO-GO:** describing memdsl as implementing the paper authority runtime.

No remote publication or deployment action occurred during this audit.
