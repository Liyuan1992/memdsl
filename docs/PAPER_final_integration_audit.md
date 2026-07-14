# P6 Final Local Integration and Publication Audit

**Audit date:** 2026-07-15<br>
**Integration branch:** `codex/paper-v06-final-integration-audit`<br>
**Software candidate base:** `091b4736e02969ccdd198cfcb30ba9038feb78db`<br>
**Paper source:** `5c55948b13029d82974cc12ee3249099b0444f75`<br>
**P5 parent / P4:** `ce18a95eede73949c27648fb3262bb9b480a3561`

## Scope and integration result

P6 integrated the final P5 paper artifact into the `0.8.0` candidate without
merging the paper branch's older runtime ancestry. The candidate runtime,
Phase -1 through Phase 5 implementation, version metadata, CI hardening, and
release scripts remain authoritative for the software tree. The P5 main
manuscript, claim ledger, reproducibility metadata, publication-readiness
audit, and software/paper citation split remain authoritative for the focused
paper artifact.

The practical source/compiled-view design and the focused authority paper are
kept side by side and cross-referenced through `README.md`,
`docs/DOCUMENTATION_INDEX.md`, and both companion documents. They are not
collapsed into one specification.

No practical Phase 6/7 implementation was added. No authority ledger,
`L_auth`, digest-bound grant, proof object, live reduction closure, or
proof-checked `Verify` sink was added. memdsl remains a reference
implementation target rather than a conforming paper-authority runtime.

## Version, citation, and license boundary

| Artifact | Status |
| --- | --- |
| memdsl `0.6.0` | shipped software cited by the top-level `CITATION.cff` record |
| memdsl `0.8.0` | unreleased local candidate; no remote release evidence |
| paper `v0.6` | unpublished focused position-paper draft in `preferred-citation` |
| software | MIT |
| specification | separate CC-BY-4.0 statement in `docs/SPEC.md` |
| paper artifacts and P6 receipt | CC BY 4.0 under `docs/PAPER_LICENSE.md` |

P6 did not create or infer a DOI, ORCID, email address, institution, venue, or
archival publication status.

## Frozen-source verification

Before integration, all supplied P5 committed-blob SHA-256 values matched the
specified commit. P6 preserves the exact committed content and hashes of:

- `CITATION.cff`;
- `docs/PAPER_publication_readiness_audit.md`;
- `docs/PAPER_related_work_claim_ledger.md`;
- `docs/PAPER_reproducibility_and_release_metadata.md`;
- `docs/PAPER_review_gated_authority_source_compiled_contract.md`.

`LICENSE` and `docs/PAPER_LICENSE.md` were intentionally extended only to
cover this final integration receipt. The three frozen Phase -1 baseline files
retain their supplied SHA-256 values.

The paper audit reports:

- 5,052 whitespace-delimited manuscript words;
- 14/14 numbered references cited in the body;
- 24/24 unique claim-ledger rows;
- valid internal Markdown targets;
- CFF schema 1.2.0 validity;
- preserved software/paper license separation;
- no private workspace, credential, machine path, proposal store, audit log,
  database, cache, or personal dataset in the paper sources.

## Local verification record

| Gate | Result |
| --- | --- |
| Full regression | `356 passed` |
| Focused Phase -1/2/3/4/5 files | `116 passed` |
| Real stdio, scope denial, gated write, pending isolation, approval, and scale selection | `9 passed` |
| Compile | `compileall` passed for `src`, `tests`, and `scripts` |
| Python compatibility | Python 3.9 AST grammar passed for 21 core source files |
| Dependency integrity | `pip check` reported no broken requirements |
| Version contract | project and runtime both `0.8.0` |
| CLI lint demo | 2 errors, 3 warnings, exit 1 |
| CLI query/explain | passed; expected global MUST constraints were present |
| CLI Catalog/Trace | `memdsl.catalog.v1` / `memdsl.trace.v1`, status `ok` |
| MCP inspect | 11 tools, status and lint readable |
| MCP real stdio | v1/v2, resources, cursor behavior, scope denial, and quarantine passed |
| Gated write | invalid missing-evidence proposal rejected; pending stayed unserved; human approval made the declaration queryable; audit remained append-only |
| Synthetic scale | 100/1,000/10,000 bounded Catalog/query/Trace/list gates passed |
| CFF | `cffconvert 2.0.0 --validate` passed in an isolated environment |
| Twine | wheel and sdist passed |
| Member/privacy scanner | passed for both archives |
| Fresh wheel | installed outside the repository from `site-packages`; CLI, MCP, v1/v2, scope denial, real stdio, and installed paper files passed |
| Diff checks | working and staged `git diff --check` passed |

The CFF validator is intentionally isolated from the main MCP environment:
`cffconvert 2.0.0` constrains an older `jsonschema`, while the current MCP SDK
uses the modern dependency line. CI and publish definitions now validate CFF
in a separate environment rather than silently downgrading MCP.

## Final local archives

The local archives were built with
`SOURCE_DATE_EPOCH=1784034855`, the timestamp of the candidate base commit, so
the P6 receipt can be excluded while the package identity remains
reproducible. These hashes identify local candidate artifacts only:

| Archive | Bytes | Members | SHA-256 |
| --- | ---: | ---: | --- |
| `memdsl-0.8.0-py3-none-any.whl` | 264,973 | 38 | `d406c89060027c22cf917d95d7ffdd227c39931158b829b841e443be94cbbde1` |
| `memdsl-0.8.0.tar.gz` | 388,242 | 104 | `5909bd78ec6c09b4254696e21f28f849f7d428c6c6b4c835ee4cc7a3a12757f3` |

Both archives include the documentation index, practical design, main paper,
claim ledger, reproducibility metadata, P5 readiness audit, paper license,
`CITATION.cff`, software license, frozen baseline files, and synthetic
benchmark harness. The wheel installs 12 paper/reproducibility files under
`share/doc/memdsl`.

Both archives exclude:

- `docs/launch_article_zh.md`;
- this P6 receipt, because embedding an archive's own SHA-256 inside the same
  archive would make its identity self-referential;
- real memory workspaces or memory source outside explicit synthetic
  `examples/` and `tests/fixtures/` roots;
- `.memdsl`, `approved.mem`, proposals, audit logs, environment files,
  credentials, private keys, caches, databases, backups, and logs;
- machine-specific absolute paths.

The earlier candidate hashes
`ddd59f921b74a8df06b254ca9fef6e46f13d0c75c5b2ab94853cb891facb10c7`
and
`639a08d92fd233bcb0b9f702f7426329a58dccf82d43e79f99401b11a3ae318d`
remain historical pre-paper candidate evidence and are not the P6 archive
identities.

## Protected original checkout

The original checkout remains on `codex/phase-minus-1-baseline` at
`244e8d25bb71731f31a60a9dbabd74f6f48ed2fb`. Its only dirty path remains the
untracked `docs/launch_article_zh.md`, with size 19,640 bytes and SHA-256
`38b2c7ebf94be266bde1ad9aad577c99000bcd0740b29607d213268987410568`.
P6 did not modify, stage, commit, copy, or package that file.

## Final decision

- **GO:** local integration of the practical `0.8.0` candidate and focused
  paper `v0.6` artifact.
- **GO:** local release-candidate verification and archive inspection.
- **NO-GO:** push, tag, GitHub Release, PyPI `0.8.0`, Zenodo record, DOI, or
  public/archival paper submission in this window.
- **NO-GO:** describing the manuscript as an empirical systems result, an
  evaluated security system, or a mechanized soundness result.
- **NO-GO:** describing memdsl as implementing the paper authority runtime.

Public or archival paper submission remains blocked until the author confirms
the scholarly display name, funding statement, and competing-interest
statement. No empirical comparison or mechanized soundness proof exists.

## Exact remaining remote actions

All actions below require renewed explicit user authorization:

1. Confirm the scholarly display name, funding statement, and
   competing-interest statement; optionally supply, but never infer, ORCID,
   email, institution, venue, or other publication metadata.
2. Authorize a push of the exact clean P6 integration commit and wait for the
   full remote core, MCP, CFF, paper, phase/security, build, member/privacy, and
   fresh-install CI gates on that commit.
3. If releasing software, authorize creation of `v0.8.0` at the verified
   commit. Rebuild from the clean tag, record new tag-build hashes, run Twine
   and outside-repository fresh install again, then separately authorize the
   GitHub Release and PyPI upload. Do not reuse the local P6 hashes as remote
   release evidence.
4. If publishing the paper, choose the venue, complete the broader novelty and
   submission review, generate and inspect the submission PDF, then separately
   authorize any Zenodo record or DOI creation. Update citation metadata only
   after identifiers and archival status actually exist.
5. After any PyPI publication, install `memdsl==0.8.0` into a new environment
   from the public index and repeat CLI, MCP, paper-member, and version checks.

No remote publication action occurred during P6.
