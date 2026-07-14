# memdsl

[English](#english) | [中文](#中文)

## English

**Agent memory as source code the agent reads itself.**

### 0.8.0 release scope

Version 0.8.0 combines the previously unpublished navigation and View work in
one release line; there is no separate 0.7.0 release. Stable public contracts
include the v1 compatibility/authority surfaces, Catalog v1, Trace v1, indexed
query/search trace, report diagnostics, `memdsl.workspace.v2`, exact `use`, the
generic `dialect_mapping` capability, `ViewContext`/`ResolvedView`, and the
explicit opt-in v2 read schemas. Map v1 remains supported throughout the 0.8
line and will not be reconsidered for removal before 1.0.

This repository state is still an unreleased local `0.8.0` candidate. The
shipped software remains `0.6.0`; no remote CI result, tag, GitHub Release, or
PyPI `0.8.0` publication is implied by the candidate documentation.

The real-world rollout quality of `quarantine`/`strict`, dialect-candidate
learning, and host-attested principal integration is still experimental and
opt-in. Their safety invariants are not experimental: authorization happens
before aggregation, incomplete hard-rule evaluation never becomes ALLOW,
non-authoritative edges never gain authority, and repair paths remain open.
`CompiledWorkspace`, cache/index layout, compiler contract strings, and
synthetic timing constants are implementation details. First-class reviewed
edges and cold-history/incremental compilation are not part of 0.8.0.

The repository also carries a focused, unpublished position-paper draft,
[Review-Gated Authority for Persistent Agent Memory](docs/PAPER_review_gated_authority_source_compiled_contract.md).
It is a companion research contract, not a description of shipped runtime
conformance: memdsl does not yet implement its authority ledger, digest-bound
grants, proof objects, live reduction closure, or `Verify` sinks. Start with
the [documentation index](docs/DOCUMENTATION_INDEX.md) for the exact software,
paper, citation, license, and publication-readiness boundaries.

memdsl started with a retrieval failure. A memory system built on RAG failed
to recall a memory it certainly had; a coding agent pointed at the same raw
memory files traced it down in a few steps. Same model — the difference was
the context contract. The agent knew the memory existed and could keep
reading toward it; the retriever got exactly one similarity guess, and a
miss looked identical to absence.

memdsl turns that difference into the product. Long-term memory lives in
readable, lintable, reviewable `.mem` source files, and every runtime
surface is built for an agent that reads memory itself:

- **A bounded memory Catalog** (`memdsl catalog`, MCP `memory_catalog` /
  `memdsl://catalog`, Python `build_memory_catalog`): paged module/type/subject/
  status navigation with item and byte budgets, revision-bound cursors, and no
  duplicated structured/text representation. It is the recommended
  session-start surface for large workspaces.
- **A compatible memory map** (`memdsl map`, MCP `memory_map` /
  `memdsl://map`): the existing v1 full index remains available for older
  clients and is not silently changed into Catalog.
- **Indexed queries that explain their misses** (`search_trace` in every
  serialized pack): deterministic lexical postings preserve the v1
  EvidencePack ordering and authority lanes while exposing View/source
  identity, candidate-pool counts, filter-hidden matches, bounded vocabulary
  suggestions, and safe retry queries. Suggestions never write aliases or let
  candidate symbols redirect retrieval.
- **A bounded relation Trace** (`memdsl trace`, MCP `memory_trace`, Python
  `trace_memory`): deterministic incoming/outgoing/both BFS navigation with
  relation filters, explicit cycle/back/cross edges, hard depth/node/edge/byte
  budgets, and revision-bound cursors. Connectivity is navigation, not proof.
- **Report-only link diagnostics** (`memdsl lint`, MCP `memory_lint` and
  `memdsl://status`): duplicate ids, ambiguous/wrong-prefix/dangling targets,
  unknown relations, revision cycles, and supersede forks are explicit. Cycle
  edges cannot make every participant disappear, forks never select a winner,
  and default Map/query authority remains v1-compatible.
- **Raw source as the floor** (`memdsl://file/{file_id}`): the agent can
  always drop down and read the actual declarations, the way a coding agent
  reads code.

The failure mode that started the project now fails loud — the memory
exists, a filter hid it, and the trace says exactly that:

```console
$ memdsl query examples/domains/coding -q "force push main" \
    --type coding.bug_pattern --json
  "missing": [
    "no active declarations matched query terms: ['force', 'push', 'main']",
    "1 active declaration(s) matched the query but were excluded by type/subject filters"
  ],
  "search_trace": {
    "excluded_by_filters": [
      {"id": "coding.project_rule:git.no_force_push", ...}
    ], ...
  }

$ memdsl query examples/domains/coding -q "force push main"
MUST
- [coding.project_rule:git.no_force_push] Never force-push the main branch. (exceptions: []) [status=active; runtime_role=constraint; lifecycle={"status":"active"}]
```

### Try it with Claude Code in two minutes

The core library and CLI support Python 3.9+. The MCP extra and
`memdsl-mcp` server require Python 3.10+ because the upstream MCP SDK does.

```console
# Python 3.10+
pip install "memdsl[mcp]"
claude mcp add memdsl -- memdsl-mcp --workspace ~/memory   # or an examples/ dir
```

The server instructs the agent to read `memory_catalog` first, continue only
with a cursor bound to the same Source/View and filters, treat `no_match` as a
retry signal, use `memory_trace` only for bounded explicit-relation navigation,
and preflight consequential drafts against MUST constraints with
`memory_check`. Legacy `memory_map` remains registered for compatible clients.

### Governed, typed memory

The second pillar: memory you can review like code, **without forcing one
author's ontology on every user**. Version 0.8 preserves the two-layer type
architecture introduced in 0.5 and the lifecycle-safe review contract from
0.6, then adds bounded compiled navigation and explicit workspace-v2 Views:

```text
core memory record     claim / evidence / scope / confidence / lifecycle /
                       access policy / relations

domain type system     coding.project_rule / assistant.commitment /
                       writing.voice_preference / your own memory types
```

The core owns the stable behavioral contract. A workspace owns its vocabulary.
A coding agent, personal assistant, and writing system should not have to call
the same thing a `preference`, `boundary`, or `fact` just because memdsl's
author chose those words.

### Two layers

The **core layer** provides universal fields and five stable runtime roles:

| Runtime role | EvidencePack behavior |
| --- | --- |
| `symbol` | Defines a subject that other memories can reference |
| `constraint` | Active declarations surface in MUST and participate in compliance |
| `guidance` | Active declarations surface in SHOULD |
| `assertion` | Active declarations surface in CONTEXT when relevant |
| `question` | Active declarations surface in MISSING rather than as fact |

Every searchable non-active hit is isolated under PROVISIONAL, regardless of
runtime role. Candidate symbols cannot redirect queries, and candidate
constraints cannot enter MUST or compliance.

The same authority boundary applies to relations. A `supersedes` relation can
hide a target only when its source is active and its full-id or unique bare
target resolves exactly. Candidate, retracted, archived, ambiguous, duplicate,
or wrongly prefixed superseders cannot change query, MUST, or compliance. This
is the v1 compatibility authority rule retained by 0.8. The opt-in
ResolvedView path uses the same fail-safe base and adds only explicit v2
quarantine enforcement.

The core also understands capabilities such as `requires_evidence`,
`searchable`, `temporal`, `enforceable`, `guardable`,
`exceptions_recommended`, and the explicit review opt-in
`auto_approvable`.

The **domain layer** defines meaningful memory types and compiles each one to
a runtime role. The shipped examples include:

- coding: `coding.project_rule`, `coding.bug_pattern`, `coding.tool_preference`
- personal assistant: `assistant.routine`, `assistant.commitment`,
  `assistant.relationship_context`
- writing: `writing.voice_preference`, `writing.taboo_topic`,
  `writing.style_example`

The built-in `memdsl.standard@1` pack keeps existing `entity`, `fact`,
`preference`, `boundary`, `principle`, `decision`, `state`, and `open_issue`
workspaces working. Those names are compatibility defaults, not the universal
ontology of human memory.

### Define a domain vocabulary

A workspace opts into schemas with `memdsl.json`:

```json
{
  "schema_version": "memdsl.workspace.v1",
  "schemas": ["coding.memschema.json"]
}
```

The schema defines domain types, fields, roles, and capabilities:

```json
{
  "name": "coding",
  "version": "1",
  "types": {
    "project_rule": {
      "runtime_role": "constraint",
      "required_fields": ["claim", "evidence", "scope"],
      "optional_fields": ["rationale", "owner"],
      "search_fields": ["rationale", "owner"],
      "capabilities": [
        "requires_evidence",
        "searchable",
        "enforceable",
        "guardable",
        "exceptions_recommended"
      ],
      "defaults": {"force": "hard", "status": "active"},
      "allowed_forces": ["hard"],
      "allow_extra_fields": false
    }
  }
}
```

`project_rule` becomes the namespaced type `coding.project_rule`:

```mem
module coding.memory

entity Repository.Memdsl {
  canonical_name: "memdsl"
  status: active
}

coding.project_rule git.no_force_push {
  subject: Repository.Memdsl
  claim: "Never force-push the main branch."
  scope: repository("memdsl")
  confidence: high
  exceptions: []
  rationale: "Published history must remain auditable."
  guard {
    when_any: ["push", "git", "main"]
    deny_any: ["force-push", "--force", "--force-with-lease"]
  }
  lifecycle { status: active }
  access_policy {
    readers: [developer, coding_agent]
    writers: [maintainer]
    reviewers: [maintainer]
    export: internal
  }
  evidence {
    source: AGENTS.md
    quote: "Do not force-push unless the user explicitly asks."
  }
}
```

Strict schemas reject undeclared fields. Unknown memory types fail lint with
`unknown_memory_type`; they do not silently acquire ad-hoc behavior.

### Exact imports and workspace-owned dialect

Existing workspaces stay compatible: no manifest and
`memdsl.workspace.v1` keep legacy global linking. A workspace can explicitly
audit or enforce imports with v2:

```json
{
  "schema_version": "memdsl.workspace.v2",
  "schemas": ["workspace-dialect.memschema.json"],
  "linking": {"visibility": "report"}
}
```

`use X` is resolved after the whole workspace is indexed, so declaration order
does not matter. `X` is one exact module or one exact active symbol name. There
is no wildcard, prefix, alias, or module-over-symbol precedence. Report mode
keeps legacy links and emits migration diagnostics; strict mode removes
unimported relation, subject-routing, and dialect-routing effects. Strict is
never inferred for a v1 workspace.

Dialect remains Source owned by the workspace. A schema type opts in through
the generic `dialect_mapping` capability; the fictional runnable example is
`examples/dialect/`. Only active, public, valid, unambiguous positive mappings
route. Candidate, pending, private, ambiguous, and negative mappings do not.
A no-match may return a `search_trace.dialect_candidate` template, but it does
not write anything: evidence, proposal, review, approval, and recompilation are
still required.

### Opt-in quarantine enforcement

Workspace v2 can independently enable the v2 read gate:

```json
{
  "schema_version": "memdsl.workspace.v2",
  "schemas": ["workspace-dialect.memschema.json"],
  "linking": {"visibility": "report"},
  "enforcement": {"mode": "quarantine"}
}
```

Omitting `enforcement`, or selecting `report`, preserves the v1 read behavior.
`quarantine` and `strict` are explicit opt-ins; they classify Source as
authoritative, provisional, quarantined, or excluded and use new v2
query/list/explain/check/Catalog/Trace envelopes. Empty results distinguish
`no_match`, `quarantined`, `unauthorized`, `compiler_error`, and budget limits.
Identity-critical errors fail closed, while relation/use/dialect/type errors
are quarantined at the smallest safe declaration, file, or revision-family
scope. Lint, source edits, proposals, review, and audit remain available for
repair.

Map stays a v1 compatibility surface and returns `unsupported_view` under
explicit enforcement. Use Catalog, query, list, explain, or Trace instead.
Pending proposals still do not enter a durable View, and candidate/private/
ambiguous dialect mappings never gain routing authority through quarantine.

### Install and inspect

The base package supports Python 3.9+:

```console
pip install memdsl                 # or: pip install -e . from a checkout
memdsl --version
memdsl types examples/domains/coding
memdsl lint examples/domains/coding
memdsl catalog examples/domains/coding --json
memdsl map examples/domains/coding
memdsl query examples/domains/coding -q "force push main"
memdsl trace examples/alex decision:aurora.pricing_free_tier --both --depth 2 --json
memdsl check examples/domains/coding \
  -t "push main" \
  -c "git push --force origin main"
```

`memdsl types` shows every loaded standard and domain type together with its
runtime role, required fields, capabilities, schema version, and source. Use
`--json` when another tool needs to discover the type system.

The custom coding rule behaves exactly like a MUST constraint without any
Python code knowing the name `coding.project_rule`:

```text
MUST
- [coding.project_rule:git.no_force_push] Never force-push the main branch. [status=active; runtime_role=constraint; lifecycle={"status":"active"}]
```

The compliance check returns `BLOCK` and cites the same domain declaration.
An unguarded or non-enforceable constraint fails safely to `NEEDS_REVIEW`
instead of being guessed at.

### Layered query contract

Queries return an **EvidencePack**, not a flat hit list:

- `MUST`: applicable `constraint` declarations
- `SHOULD`: relevant `guidance` declarations
- `CONTEXT`: relevant `assertion` declarations
- `PROVISIONAL`: scored non-active searchable declarations
- `CONFLICT`: declared conflicts among selected memories
- `MISSING`: relevant `question` declarations and known gaps

Every item carries a stable declaration id, type, runtime role, capabilities,
claim, subject, scope, confidence, lifecycle, access policy, evidence, and
source location. Domain semantics stay expressive while runtime behavior stays
predictable.

JSON output remains `memdsl.evidence_pack.v1`; the `provisional` field added in
0.6 remains additive in 0.8. Scored CONTEXT and PROVISIONAL entries include `score` and
`matched_terms`, and every declaration item carries explicit lifecycle
status and runtime role.

The reference retriever is deliberately lexical and uses a rebuildable
inverted term index. Production systems can put BM25, embeddings, graphs, or
database indexes behind the same EvidencePack contract.

### Navigation: bounded Catalog first, then query and drill down

memdsl exists because agent-driven reading beats blind similarity matching:
an agent that knows a memory exists can drill down to it, while a retriever
that misses just returns nothing. Four surfaces support that loop:

- **Bounded Catalog** (`memdsl catalog`, MCP `memory_catalog` /
  `memdsl://catalog`, Python `build_memory_catalog`): module summaries filtered
  by module/type/subject/status. The default page is 20 items / 8192 canonical
  compact UTF-8 JSON bytes. `truncated`, `next_cursor`, `returned_items`, exact
  totals, and vocabulary total/truncated metadata are explicit. Cursors bind
  Source fingerprint, report-only View, filters, order, and representation;
  changed Source returns `cursor_stale`.
- **Map v1 compatibility** (`memdsl map`, MCP `memory_map` / `memdsl://map`,
  Python `build_memory_map`): still returns the full serviceable declaration
  index for existing clients. It is not the recommended large-workspace
  session-start surface. Under explicit workspace-v2 enforcement it returns
  `unsupported_view`; Map and Catalog are navigation, not citation.
- **Search trace** (`search_trace` in serialized packs): how the query was
  interpreted, which indexes ran, the candidate pool before/after filters, and
  which matching declarations a type/subject filter excluded. A no-match may
  add bounded lexical `vocabulary_suggestions` and `retry_queries`; candidate,
  ambiguous, or access-restricted vocabulary never becomes an automatic route.
- **Bounded Trace** (`memdsl trace`, MCP `memory_trace`, Python
  `trace_memory`): follows explicit resolved relations with deterministic BFS.
  Defaults are depth 3, 20 nodes, 40 edges, and 8192 bytes. Stateless cursors
  bind Source/View, anchors, direction, relation filters, depth, and
  provisional visibility. Back/cycle/cross edges are explicit; graph
  connectivity is not evidence or proof.

### Preflight constraints

Any schema-defined `constraint` can participate in `memdsl check`. To run a
deterministic guard, its type must declare both `enforceable` and `guardable`.
Phrase and regex guards produce `ALLOW` or `BLOCK`; natural-language-only
constraints produce `NEEDS_REVIEW`. Declared exceptions must be asserted
explicitly with `--exception`.

The standard v0.4 `boundary` type follows this same generic path. Its old JSON
aliases such as `boundary_id` and `applicable_must` remain available for
client compatibility.

Run the reproducible standard or custom-domain suites:

```console
memdsl eval compliance examples/compliance \
  --cases examples/compliance/cases.jsonl --json

memdsl eval compliance examples/domains/coding \
  --cases examples/domains/coding/cases.jsonl --json
```

### Use as an MCP server

The MCP server requires Python 3.10+:

```console
# Python 3.10+
pip install "memdsl[mcp]"
memdsl-mcp --workspace examples/domains/coding --inspect
memdsl-mcp --workspace ~/memory
```

The MCP server exposes:

- tools: `memory_catalog`, `memory_map`, `memory_types`, `memory_query`, `memory_trace`, `memory_check`,
  `memory_explain`, `memory_list`, `memory_lint`, `memory_propose`,
  `memory_review_list`
- resources: `memdsl://status`, `memdsl://catalog`, `memdsl://map`, `memdsl://types`,
  `memdsl://files`, `memdsl://file/{file_id}`

Agents should read `memory_catalog` at session start so navigation remains
bounded as the workspace grows, then use `memory_query` and bounded
`memory_trace` for local drill-down. `memory_map` remains for v1 clients. Before
proposing a declaration, call `memory_types` or read `memdsl://types`. This
discovers the workspace's vocabulary instead of inventing a type or assuming
the standard pack is the only valid worldview.

Access can be narrowed with `--scopes` or `MEMDSL_MCP_SCOPES` (default:
`read:summary,read:search,write:candidate`). The core represents and transports
declaration-level `access_policy`. For an enforced View, an embedding host may
inject a trusted principal and roles only when constructing
`MemdslMCPService`; MCP tool arguments cannot self-assert identity. Filtering
happens before counts, vocabulary, diagnostics, graph traversal, and raw-file
resources. memdsl does not provide an identity provider, so the host must
authenticate the principal and map roles.

### Gated writes

Every MCP write is still a proposal. It must use a loaded type, parse, and
pass lint against the live workspace. Invalid proposals are rejected; exact
pending/approved duplicates return `no_op`; everything else is either queued
or narrowly auto-approved by host-attested policy.

The default remains all-human. Initialize a valid but disabled policy:

```console
memdsl review policy init memory
memdsl review policy show memory
memdsl review policy validate memory
```

The generated JSON has empty clients/rules and a zero daily limit. To enable
automation, a workspace owner must explicitly add `auto_approvable` to one
candidate assertion type, configure an exact-kind rule and trusted host
client, set a positive daily limit, and grant the non-default `write:auto`
scope:

```console
memdsl-mcp --workspace memory \
  --scopes read:summary,read:search,write:candidate,write:auto
```

The built-in `workspace_file_quote` verifier requires
`evidence.source` to resolve inside a loaded workspace root and
`evidence.quote` to occur exactly in that UTF-8 file. Question, guidance,
constraint, symbol, active, global, warned, destructive, or unverified
proposals always stay queued. Without `write:auto`, a valid policy runs in
shadow posture: the write remains pending while `eligible_route` records
what policy would have done.

Human operations and quality feedback remain explicit:

```console
memdsl review list memory
memdsl review approve memory PROPOSAL_ID --into memory/approved.mem
memdsl review reject memory PROPOSAL_ID --reason "not durable"
memdsl review digest memory
memdsl review stats memory
memdsl review audit memory PROPOSAL_ID --verdict confirm
```

In-process hosts use authoritative paths:

```python
from memdsl import (
    ProposalContext,
    ReviewStore,
    Workspace,
    load_policy,
    staging_dir_for,
)

workspace = Workspace.load(["memory"])
store = ReviewStore(staging_dir_for(["memory"]))
policy = load_policy(store.staging_dir, registry=workspace.registry)
assert policy is not None
context = ProposalContext(client_id="mcp-client")

result = store.submit(
    ["memory"],
    proposal_source,
    policy=policy,
    context=context,
    write_auto_granted=True,
)
```

Automatic approval reloads and fingerprints memory, manifest, and schema
inputs, re-verifies evidence, enforces a finite UTC daily limit, writes only
to a non-symlink `.mem` target inside the primary workspace root, and never
uses `force`. Route assessments, decisions, post-review results, digest
cursors, and no-op events remain append-only.

A post-review `flag` does not silently delete memory. Promotion, revision,
and retraction require a new human-reviewed declaration with a new id and
`supersedes` (optionally `revision_of`) pointing to the old declaration. The
successor must be lifecycle `active` before the relation has authority; the old
declaration does not need an in-place `status: superseded` rewrite.
ReviewStore does not create Git commits; hosts may add Git integration without
making core correctness depend on it.

### What's in the box

- A domain-neutral `.mem` record with provenance, scope, confidence,
  lifecycle, access policy, relations, and stable ids.
- An extensible, namespaced `.memschema.json` type system and workspace
  manifest.
- A backward-compatible standard type pack for pre-v0.5 workspaces.
- A schema-driven linter, layered query executor, explainer, and deterministic
  Compliance Gate.
- Type discovery through CLI and MCP.
- A default-safe, host-attested review pipeline with human queueing,
  deterministic narrow auto-approval, no-op detection, digest/stats, and
  append-only audit.
- Reproducible compliance benchmarks and coding/assistant/writing domain packs.
- Fictional standard examples for Alex and Mira plus a deliberately broken
  linter workspace.

Full grammar and semantics are in [docs/SPEC.md](docs/SPEC.md). In-process hosts
should also read [docs/PUBLIC_API.md](docs/PUBLIC_API.md) and
[docs/UPGRADING.md](docs/UPGRADING.md). The review-policy security contract is
in [docs/DESIGN_review_policy.md](docs/DESIGN_review_policy.md). The
[documentation index](docs/DOCUMENTATION_INDEX.md) keeps the practical
source/compiled-view design, focused paper, claim ledger, reproducibility
record, readiness audit, citation, and license boundaries together.

### What memdsl is not

- It is not a replacement for retrieval/extraction systems such as Mem0, Zep,
  Graphiti, or LangMem. It is the governed source format and behavioral
  contract above those systems.
- It is not a universal taxonomy of people or memory. Domain owners define
  their own types.
- It is not a semantic policy oracle. Constraints that cannot be evaluated
  deterministically remain `NEEDS_REVIEW`.
- It is not an unrestricted automatic memory writer. Only explicitly
  opted-in candidate assertions with trusted identity and verified evidence
  can be auto-approved; every higher-risk or uncertain proposal remains human
  reviewed.

### Current evidence and limits

Early evidence from the private single-user system this project was extracted
from showed higher retrieval precision than that system's tuned RAG baseline
on its internal evaluation. That result is encouraging, but it is not evidence
that one ontology generalizes to everyone. The v0.8 architecture makes that
limitation explicit: memdsl standardizes the record and runtime contract while
letting each domain own its vocabulary.

The bundled suites are contract-level, deterministic tests. Cross-model
behavioral claims still require separately recorded model runs.

### Roadmap

- ~~Two-layer core + extensible domain type system~~ — shipped in v0.5
- ~~Lifecycle-safe provisional serving + tiered review policy~~ — shipped in v0.6
- ~~Internal compiled indexes + bounded Catalog pagination/budgets~~ — included in the unreleased 0.8.0 candidate
- ~~Indexed query + bounded Trace + exact use/report/strict + reviewed Dialect~~ — included in the unreleased 0.8.0 candidate
- ~~Opt-in quarantine enforcement with explicit v2 envelopes~~ — included in the unreleased 0.8.0 candidate; rollout remains experimental
- First-class reviewed edges — deferred until published Trace has real consumers and edge-review evidence
- Cold history/incremental compilation — deferred until representative scale, SLO, and production bottleneck evidence exists
- Schema package distribution, dependency/version constraints, and migrations
- Richer field validators and domain-defined diagnostic rules
- Pluggable retrieval backends behind the EvidencePack contract
- Identity-provider adapters for enforcing represented access policies
- Semantic conflict reviewers and per-client/per-rule quotas, gated by
  measured shadow/sample/post-review evidence

### License

Code: [MIT](LICENSE). Specification ([docs/SPEC.md](docs/SPEC.md)): CC-BY-4.0.
The focused paper artifacts are separately licensed under
[CC BY 4.0](docs/PAPER_LICENSE.md).

---

## 中文

**把 Agent 记忆写成 agent 自己会去读的源代码。**

### 0.8.0 发布范围

0.8.0 把此前未单独发布的导航能力与 View 能力统一成一个 release line；不会另发
0.7.0。正式公共合同包括 v1 兼容/authority surface、Catalog v1、Trace v1、
indexed query/search trace、report diagnostics、`memdsl.workspace.v2`、exact
`use`、通用 `dialect_mapping` capability、`ViewContext`/`ResolvedView` 与显式
opt-in 的 v2 read schemas。Map v1 在整个 0.8 line 继续保留，不早于 1.0 才重新
评估删除。

当前仓库状态仍是未发布的本地 `0.8.0` candidate。已发布软件仍为 `0.6.0`；候选
文档不代表远端 CI、tag、GitHub Release 或 PyPI `0.8.0` 发布已经发生。

`quarantine`/`strict` 的真实 rollout 质量、dialect candidate 学习闭环和宿主证明
principal 的集成仍是 experimental/opt-in；但 authorization-before-aggregation、
hard rule 不完整时不得 ALLOW、非权威 edge 不得获得 authority、repair lane 必须
可用等安全不变量不是实验性的。`CompiledWorkspace`、cache/index 布局、compiler
contract 字符串和 synthetic timing 都是内部实现事实。一等可审 Edge 与冷历史/
增量编译不在 0.8.0 范围内。

仓库还并列保存一份未发表的聚焦立场论文草稿
[Review-Gated Authority for Persistent Agent Memory](docs/PAPER_review_gated_authority_source_compiled_contract.md)。
它是配套研究合同，不代表当前 runtime 已符合论文：memdsl 尚未实现论文中的
authority ledger、digest-bound grants、proof objects、live reduction closure 或
`Verify` sinks。软件、论文、引用、许可和发表就绪边界以
[文档索引](docs/DOCUMENTATION_INDEX.md) 为准。

memdsl 起源于一次召回失败。一个基于 RAG 的记忆系统没能召回一条确实存在的
记忆；而一个 coding agent 拿到同样的原始记忆文件，几步就把它找了出来。
同一个模型——差别在上下文契约：agent 知道那条记忆存在，可以一层层读过去；
检索器只有一次相似度猜测，而且"没命中"和"不存在"看起来一模一样。

memdsl 把这个差别做成了产品。长期记忆保存在可读、可 lint、可审查的 `.mem`
源文件里，每个运行时 surface 都为"agent 自己读记忆"而设计：

- **有界记忆目录 Catalog**（`memdsl catalog`、MCP `memory_catalog` /
  `memdsl://catalog`、Python `build_memory_catalog`）：按 module/type/subject/
  status 分页导航，具备 item/byte 硬预算、绑定 revision 的稳定 cursor，并避免
  structured/text 双份返回；这是大型 workspace 推荐的会话起始 surface。
- **兼容记忆地图**（`memdsl map`、MCP `memory_map` / `memdsl://map`）：旧的
  v1 全量索引继续保留，不会被原地改成 Catalog。
- **带倒排索引、会解释 miss 的查询**（序列化 pack 中的 `search_trace`）：
  确定性的词法 postings 保持 v1 EvidencePack 排序与 authority lane，同时返回
  View/source、候选池、filter-hidden match、受限词汇建议和安全 retry query；建议
  不会写 alias，也不会让 candidate symbol 改写路由。
- **有界关系 Trace**（`memdsl trace`、MCP `memory_trace`、Python
  `trace_memory`）：确定性的 incoming/outgoing/both BFS、relation filter、显式
  cycle/back/cross edge、depth/node/edge/byte 硬预算与 revision-bound cursor。
  连通性只是导航，不是证明。
- **原始源码兜底**（`memdsl://file/{file_id}`）：agent 随时可以下钻去读
  真正的声明，就像 coding agent 读代码一样。

当年启动这个项目的那种失败，现在会大声报错——记忆存在，是过滤器藏了它，
trace 会把话说明白：

```console
$ memdsl query examples/domains/coding -q "force push main" \
    --type coding.bug_pattern --json
  "missing": [
    "no active declarations matched query terms: ['force', 'push', 'main']",
    "1 active declaration(s) matched the query but were excluded by type/subject filters"
  ],
  "search_trace": {
    "excluded_by_filters": [
      {"id": "coding.project_rule:git.no_force_push", ...}
    ], ...
  }

$ memdsl query examples/domains/coding -q "force push main"
MUST
- [coding.project_rule:git.no_force_push] Never force-push the main branch. (exceptions: []) [status=active; runtime_role=constraint; lifecycle={"status":"active"}]
```

### 两分钟在 Claude Code 里跑起来

底层库和 CLI 支持 Python 3.9+。由于上游 MCP SDK 的要求，MCP extra 和
`memdsl-mcp` server 需要 Python 3.10+。

```console
# Python 3.10+
pip install "memdsl[mcp]"
claude mcp add memdsl -- memdsl-mcp --workspace ~/memory   # 或任意 examples/ 目录
```

server 会指示 agent 先读 `memory_catalog`，只在 Source/View 和过滤条件不变时
继续 cursor，把 `no_match` 当作重试信号，只用 `memory_trace` 做有界的显式关系
导航，并在产出重要草稿前用
`memory_check` 对照 MUST 约束做预检。旧客户端仍可调用 `memory_map`。

### 受治理的类型化记忆

第二根支柱：像审代码一样审记忆，**但不要求所有用户接受作者的一套世界观**。
v0.8 保留 v0.5 引入的两层类型架构与 v0.6 的 lifecycle 安全审核合同，并加入
有界编译导航与显式 workspace-v2 View：

```text
底层通用记录        claim / evidence / scope / confidence / lifecycle /
                    access policy / relations

上层领域类型系统    coding.project_rule / assistant.commitment /
                    writing.voice_preference / 用户自定义类型
```

底层负责稳定的行为契约，workspace 负责自己的词汇。编程 Agent、个人助理和
写作系统不应该仅仅因为 memdsl 作者选择了 `preference`、`boundary`、`fact`
这些词，就被迫用同一套分类描述自己的记忆。

### 两层架构

**底层**提供通用字段和五种稳定的 runtime role：

| Runtime role | 在 EvidencePack 中的行为 |
| --- | --- |
| `symbol` | 定义其他记忆可以引用的主体 |
| `constraint` | 只有 active 声明进入 MUST 并参与合规检查 |
| `guidance` | 只有 active 声明进入 SHOULD |
| `assertion` | 只有 active 声明相关时进入 CONTEXT |
| `question` | 只有 active 声明进入 MISSING，而不是伪装成事实 |

任何 searchable 的非 active 命中都只进入 PROVISIONAL，不论 runtime role。
candidate symbol 不能重定向查询，candidate constraint 不能进入 MUST 或
compliance。

同一 authority 边界也适用于关系。只有 source 为 active，且 full id 精确匹配或
bare ref 唯一解析时，`supersedes` 才能隐藏 target。candidate、retracted、
archived、歧义、重复或错误 kind 前缀的 superseder 都不能改变 query、MUST 或
compliance。这是 0.8 继续保留的 v1 correctness/security authority 规则。
ResolvedView 复用这个安全基础，只在显式 v2 opt-in 时增加 quarantine enforcement。

底层还识别 `requires_evidence`、`searchable`、`temporal`、
`enforceable`、`guardable`、`exceptions_recommended`，以及显式审核
opt-in 的 `auto_approvable` 等 capability。

**上层**定义领域真正关心的 memory type，并把每种类型编译到一个稳定 role。
仓库自带三个示例领域：

- 编程：`coding.project_rule`、`coding.bug_pattern`、
  `coding.tool_preference`
- 个人助理：`assistant.routine`、`assistant.commitment`、
  `assistant.relationship_context`
- 写作：`writing.voice_preference`、`writing.taboo_topic`、
  `writing.style_example`

内置的 `memdsl.standard@1` 兼容包会继续加载 `entity`、`fact`、
`preference`、`boundary`、`principle`、`decision`、`state`、
`open_issue` 等旧类型。它们是向后兼容的默认词汇，不是人类记忆的唯一分类法。

### 定义自己的领域词汇

workspace 通过 `memdsl.json` 引入 schema：

```json
{
  "schema_version": "memdsl.workspace.v1",
  "schemas": ["coding.memschema.json"]
}
```

`.memschema.json` 定义类型的字段、role 和 capability：

```json
{
  "name": "coding",
  "version": "1",
  "types": {
    "project_rule": {
      "runtime_role": "constraint",
      "required_fields": ["claim", "evidence", "scope"],
      "optional_fields": ["rationale", "owner"],
      "search_fields": ["rationale", "owner"],
      "capabilities": [
        "requires_evidence",
        "searchable",
        "enforceable",
        "guardable",
        "exceptions_recommended"
      ],
      "defaults": {"force": "hard", "status": "active"},
      "allowed_forces": ["hard"],
      "allow_extra_fields": false
    }
  }
}
```

加载后，`project_rule` 的完整名字是 `coding.project_rule`：

```mem
coding.project_rule git.no_force_push {
  subject: Repository.Memdsl
  claim: "绝不对 main 分支执行 force-push。"
  scope: repository("memdsl")
  confidence: high
  exceptions: []
  rationale: "已发布的历史必须保持可审计。"
  guard {
    when_any: ["push", "git", "main"]
    deny_any: ["force-push", "--force", "--force-with-lease"]
  }
  lifecycle { status: active }
  access_policy {
    readers: [developer, coding_agent]
    writers: [maintainer]
    reviewers: [maintainer]
    export: internal
  }
  evidence {
    source: AGENTS.md
    quote: "除非用户明确要求，否则不要 force-push。"
  }
}
```

严格 schema 会拒绝未声明字段。未知类型会产生 `unknown_memory_type` lint
错误，不会悄悄获得一套临时行为。

### 精确 use 与 workspace 自有方言

旧 workspace 保持兼容：没有 manifest 或使用 `memdsl.workspace.v1` 时仍是
legacy 全局链接。只有显式使用 v2，才会进入 report 或 strict：

```json
{
  "schema_version": "memdsl.workspace.v2",
  "schemas": ["workspace-dialect.memschema.json"],
  "linking": {"visibility": "report"}
}
```

compiler 会先建立整库 module/symbol 表，再解析 `use X`，所以声明顺序不影响结果。
`X` 只能精确命中一个 module 或一个 active symbol name；不支持通配符、前缀、
alias，也不设置 module 优先或 symbol 优先。report 保留 legacy 链接并给迁移诊断；
strict 会去掉未导入 relation、subject 路由和 dialect 路由的效果。v1 绝不会因为
出现了 `use` 就被暗中切成 strict。

方言仍是 workspace 自己拥有、可版本化、可审核的 Source。schema type 通过通用
`dialect_mapping` capability opt in，仓库提供了完全虚构、可运行的
`examples/dialect/`。只有 active、公开、结构有效、无歧义的 positive mapping
才会路由；candidate、pending、private、ambiguous 和 negative mapping 都不会。
no-match 可以返回 `search_trace.dialect_candidate` 模板，但不会自动写 Source；
仍需 evidence、proposal、人工审核、批准和重新编译。

### 显式 opt-in 的 quarantine enforcement

workspace v2 可以独立开启 v2 读取 gate：

```json
{
  "schema_version": "memdsl.workspace.v2",
  "schemas": ["workspace-dialect.memschema.json"],
  "linking": {"visibility": "report"},
  "enforcement": {"mode": "quarantine"}
}
```

省略 `enforcement` 或选择 `report`，仍保持 v1 读取行为。`quarantine` 与
`strict` 必须显式 opt in；它们把 Source 分成 authoritative、provisional、
quarantined、excluded，并使用新的 query/list/explain/check/Catalog/Trace v2
envelope。空结果会明确区分 `no_match`、`quarantined`、`unauthorized`、
`compiler_error` 与预算不足。identity-critical 错误 fail closed，relation/use/
dialect/type 错误则尽量只隔离最小安全的 declaration、文件或 revision family。
lint、直接编辑 Source、proposal、review 和 audit 修复通道仍然开放。

Map 保持 v1 兼容面，在显式 enforcement 下返回 `unsupported_view`；应改用
Catalog、query、list、explain 或 Trace。pending proposal 仍不会进入 durable
View，candidate/private/ambiguous dialect 也不会借 quarantine 获得路由权。

### 安装与类型发现

基础包支持 Python 3.9+：

```console
pip install memdsl                 # 或在 checkout 中运行 pip install -e .
memdsl --version
memdsl types examples/domains/coding
memdsl lint examples/domains/coding
memdsl catalog examples/domains/coding --json
memdsl map examples/domains/coding
memdsl query examples/domains/coding -q "force push main"
memdsl trace examples/alex decision:aurora.pricing_free_tier --both --depth 2 --json
memdsl check examples/domains/coding \
  -t "push main" \
  -c "git push --force origin main"
```

`memdsl types` 会列出已加载的标准类型和领域类型，以及各自的 runtime role、
必填字段、capability、schema 版本和来源。需要给其他工具消费时可加 `--json`。

上面的自定义类型不需要在 Python 代码里写死 `coding.project_rule`，依然会作为
MUST 约束出现：

```text
MUST
- [coding.project_rule:git.no_force_push] Never force-push the main branch. [status=active; runtime_role=constraint; lifecycle={"status":"active"}]
```

合规检查会返回 `BLOCK` 并引用同一个领域声明。没有 guard 或不具备执行能力的
约束会安全返回 `NEEDS_REVIEW`，不会假装已经理解。

### 分层查询契约

查询返回的是 **EvidencePack**，而不是扁平命中列表：

- `MUST`：适用的 `constraint`
- `SHOULD`：相关的 `guidance`
- `CONTEXT`：相关的 `assertion`
- `PROVISIONAL`：带分数的非 active searchable 声明
- `CONFLICT`：已声明的冲突
- `MISSING`：相关的 `question` 和已知信息缺口

每一项都携带稳定 id、类型、runtime role、capability、claim、subject、scope、
confidence、lifecycle、access policy、evidence 和源码位置。这样领域语义可以扩展，
运行时行为仍然稳定。

JSON 输出仍为 `memdsl.evidence_pack.v1`；v0.6 加入的 `provisional` 在 v0.8
继续保持 additive。带分数的 CONTEXT 和 PROVISIONAL 条目都包含 `score`、
`matched_terms`，每个 declaration item 还明确携带 lifecycle status 和
runtime role。

参考实现使用可重建的词法倒排索引。生产系统可以在同一个 EvidencePack 契约
后面替换成 BM25、embedding、图或数据库索引。

### 导航：先读有界 Catalog，再查询和下钻

memdsl 的出发点是"让 agent 自己读记忆"胜过"让相似度匹配替 agent 决定"：
知道某条记忆存在的 agent 可以一层层钻下去，而检索器一旦没命中就什么都没有。
四个 surface 支撑这个闭环：

- **有界 Catalog**（`memdsl catalog`、MCP `memory_catalog` /
  `memdsl://catalog`、Python `build_memory_catalog`）：按 module 汇总，并可按
  module/type/subject/status 过滤。默认 20 items / 8192 canonical compact UTF-8
  JSON bytes；`truncated`、`next_cursor`、`returned_items`、精确 total 和词表
  total/truncated metadata 都显式返回。cursor 绑定 Source fingerprint、
  report-only View、过滤条件、顺序和 representation；Source 改变会返回
  `cursor_stale`。
- **Map v1 兼容面**（`memdsl map`、MCP `memory_map` / `memdsl://map`、Python
  `build_memory_map`）：继续为旧客户端返回全量可服务声明索引，但不再推荐作为
  大型 workspace 的会话起始 surface。显式 workspace-v2 enforcement 下会返回
  `unsupported_view`。Map 与 Catalog 都只是导航，不是引用来源。
- **检索痕迹**（序列化 pack 中的 `search_trace`）：记录查询被如何解释，以及
  使用了哪些 index、过滤前后候选池，以及 type/subject filter 排除了哪些本来
  匹配的声明。no-match 可返回有界 `vocabulary_suggestions` 与
  `retry_queries`；candidate、歧义或 access-restricted 词汇不会成为自动路由。
- **有界 Trace**（`memdsl trace`、MCP `memory_trace`、Python
  `trace_memory`）：沿已解析的显式关系做确定性 BFS。默认 depth 3、20 nodes、
  40 edges、8192 bytes；cursor 绑定 Source/View、anchor、direction、relation、
  depth 与 provisional visibility。back/cycle/cross edge 显式返回，但连通性不是
  evidence 或 proof。
- **只报告、不隔离的链接诊断**（`memdsl lint`、MCP `memory_lint` 与
  `memdsl://status`）：duplicate id、歧义/错误前缀/dangling target、未知 relation、
  revision cycle 和 supersede fork 都会显式出现。cycle edge 不会让参与节点全部
  消失，fork 不会暗选 winner，而默认 Map/query authority 仍保持 v1 兼容。

### 执行前约束检查

任何被 schema 编译为 `constraint` 的类型都可以参与 `memdsl check`。要执行
确定性的 guard，该类型必须同时声明 `enforceable` 和 `guardable`。短语与正则
guard 返回 `ALLOW` 或 `BLOCK`；只有自然语言的约束返回 `NEEDS_REVIEW`。
例外必须由调用方通过 `--exception` 显式声明。

v0.4 的标准 `boundary` 也走同一条通用链路。`boundary_id`、
`applicable_must` 等旧 JSON 字段仍作为兼容别名保留。

```console
memdsl eval compliance examples/compliance \
  --cases examples/compliance/cases.jsonl --json

memdsl eval compliance examples/domains/coding \
  --cases examples/domains/coding/cases.jsonl --json
```

### 作为 MCP server 使用

MCP server 需要 Python 3.10+：

```console
# Python 3.10+
pip install "memdsl[mcp]"
memdsl-mcp --workspace examples/domains/coding --inspect
memdsl-mcp --workspace ~/memory
```

MCP server 提供：

- tools：`memory_catalog`、`memory_map`、`memory_types`、`memory_query`、`memory_trace`、`memory_check`、
  `memory_explain`、`memory_list`、`memory_lint`、`memory_propose`、
  `memory_review_list`
- resources：`memdsl://status`、`memdsl://catalog`、`memdsl://map`、`memdsl://types`、
  `memdsl://files`、`memdsl://file/{file_id}`

Agent 应该在会话开始时读取 `memory_catalog`，让导航成本不随 workspace 总量
线性膨胀，再用 `memory_query` 与有界 `memory_trace` 局部下钻；`memory_map`
继续服务 v1 客户端。在提出新声明前，应该先调用
`memory_types` 或读取 `memdsl://types`，发现当前 workspace 的词汇，而不是自己
发明类型，也不是默认标准兼容包就是唯一世界观。

可通过 `--scopes` 或 `MEMDSL_MCP_SCOPES` 缩小 MCP 权限范围，默认值为
`read:summary,read:search,write:candidate`。底层会表示、验证并传输声明级
`access_policy`。在 enforced View 中，嵌入式宿主只能在构造
`MemdslMCPService` 时注入可信 principal 与 roles；MCP tool 参数不能自报身份。
过滤发生在 count、vocabulary、diagnostics、graph traversal 和 raw-file resource
之前。memdsl 不提供身份提供商；宿主仍需认证 principal 并映射 roles。

### 受审查的写入

每次 MCP 写入仍然先成为 proposal。新声明必须使用已加载类型，能够解析，并
通过当前 workspace 的 lint。非法 proposal 会被拒绝；与 pending/approved 内容
完全相同的提交返回 `no_op`；其余 proposal 要么排队，要么由宿主证明过的窄
策略自动批准。

默认仍然全部人审。先生成一份合法但禁用自动批准的 policy：

```console
memdsl review policy init memory
memdsl review policy show memory
memdsl review policy validate memory
```

生成的 JSON 里 trusted clients 和 rules 都为空，日限额为 0。要开启自动化，
workspace owner 必须给一个 candidate assertion 类型显式加入
`auto_approvable`，配置精确 kind 规则和可信宿主 client，设置正数日限额，
再授予默认不包含的 `write:auto` scope：

```console
memdsl-mcp --workspace memory \
  --scopes read:summary,read:search,write:candidate,write:auto
```

内置 `workspace_file_quote` verifier 要求 `evidence.source` 解析到已加载
workspace root 内，且 `evidence.quote` 必须逐字出现在该 UTF-8 文件中。
question、guidance、constraint、symbol、active、global、带 warning、带破坏性
关系或证据未验证的 proposal 始终排队。没有 `write:auto` 时，合法 policy
处于 shadow 姿态：写入仍 pending，但 `eligible_route` 会记录策略原本会怎么做。

人工操作与质量反馈保持显式：

```console
memdsl review list memory
memdsl review approve memory PROPOSAL_ID --into memory/approved.mem
memdsl review reject memory PROPOSAL_ID --reason "not durable"
memdsl review digest memory
memdsl review stats memory
memdsl review audit memory PROPOSAL_ID --verdict confirm
```

进程内宿主应传入权威 workspace paths：

```python
from memdsl import (
    ProposalContext,
    ReviewStore,
    Workspace,
    load_policy,
    staging_dir_for,
)

workspace = Workspace.load(["memory"])
store = ReviewStore(staging_dir_for(["memory"]))
policy = load_policy(store.staging_dir, registry=workspace.registry)
assert policy is not None
context = ProposalContext(client_id="mcp-client")

result = store.submit(
    ["memory"],
    proposal_source,
    policy=policy,
    context=context,
    write_auto_granted=True,
)
```

自动批准前会重新加载并 fingerprint 记忆、manifest 和 schema，重新验证证据，
执行有限 UTC 日配额，只写入主 workspace root 内的非 symlink `.mem` 目标，
且绝不使用 `force`。路由 assessment、decision、post-review 结果、digest
cursor 和 no-op 事件都保持 append-only。

post-review `flag` 不会静默删除记忆。晋升、修订和撤销都要提交一条新 id 的
人工审核声明，用 `supersedes`（可同时用 `revision_of`）指向旧声明。successor
必须是 lifecycle `active` 才获得关系 authority；旧声明不需要原地改成
`status: superseded`。
ReviewStore 不创建 Git commit；宿主可以增加 Git 集成，但核心正确性不依赖 Git。

### 包里有什么

- 与领域无关的 `.mem` 通用记录：来源、scope、confidence、lifecycle、
  access policy、relations 和稳定 id。
- 可扩展、带 namespace 的 `.memschema.json` 类型系统和 workspace manifest。
- 面向 v0.5 之前 workspace 的标准兼容类型包。
- schema 驱动的 linter、分层查询、explain 和确定性 Compliance Gate。
- CLI 与 MCP 的类型发现能力。
- 默认安全、宿主证明的审核链路：人工队列、确定性的窄范围自动批准、no-op
  检测、digest/stats 和 append-only audit。
- 可复现合规 benchmark，以及 coding、assistant、writing 三个领域包。
- Alex、Mira 两个虚构标准示例和一个故意损坏的 lint 示例。

完整语法与语义见 [docs/SPEC.md](docs/SPEC.md)。进程内宿主还应阅读
[docs/PUBLIC_API.md](docs/PUBLIC_API.md) 和 [docs/UPGRADING.md](docs/UPGRADING.md)。
审核策略的安全合同见
[docs/DESIGN_review_policy.md](docs/DESIGN_review_policy.md)。
[文档索引](docs/DOCUMENTATION_INDEX.md) 把实践设计、聚焦论文、claim ledger、
复现记录、就绪审计、引用与许可边界集中在一起。

### memdsl 不是什么

- 它不是 Mem0、Zep、Graphiti、LangMem 等检索/抽取系统的替代品，而是位于
  这些系统之上的受治理源格式和行为契约。
- 它不是人或记忆的通用分类法；领域所有者定义自己的类型。
- 它不是语义策略裁判；无法确定性执行的约束会保持 `NEEDS_REVIEW`。
- 它不是不受限制的自动记忆写入器。只有显式 opt-in、身份可信且证据已验证的
  candidate assertion 才可能自动批准；所有高风险或不确定 proposal 仍由人审。

### 当前证据与边界

这个项目来自一个私有的单用户系统。该系统的内部评测曾显示，DSL 结构化检索的
precision 高于它自己的调优 RAG baseline。这个结果值得继续验证，但不能证明一套
ontology 对所有人都通用。v0.8 正面承认这个限制：memdsl 标准化记录结构和运行
契约，把领域词汇的所有权交还给使用者。

仓库内置的是确定性的契约级测试。跨模型行为结论仍需单独记录真实模型运行。

### Roadmap

- ~~两层 core + 可扩展领域类型系统~~ — v0.5 已完成
- ~~lifecycle 安全的 provisional 服务 + 分级审核策略~~ — v0.6 已完成
- ~~内部编译索引 + 有界 Catalog 分页/预算~~ — 未发布 0.8.0 candidate 已包含
- ~~倒排查询 + 有界 Trace + exact use/report/strict + 受审核 Dialect~~ — 未发布 0.8.0 candidate 已包含
- ~~显式 v2 envelope 下的 opt-in quarantine enforcement~~ — 未发布 0.8.0 candidate 已包含，真实 rollout 仍为 experimental
- 一等可审核 Edge — 等待已发布 Trace 的真实 consumer 与 edge review 证据
- 冷历史/增量编译 — 等待代表性规模、SLO 与生产瓶颈证据
- Schema 包分发、依赖/版本约束和迁移机制
- 更丰富的字段验证器和领域诊断规则
- EvidencePack 后面的可插拔检索后端
- 执行 access policy 的身份提供商适配器
- 基于 shadow/sample/post-review 数据的语义冲突 reviewer 与 per-client/per-rule
  配额

### 许可证

代码：[MIT](LICENSE)。规范（[docs/SPEC.md](docs/SPEC.md)）：CC-BY-4.0。
聚焦论文材料另按 [CC BY 4.0](docs/PAPER_LICENSE.md) 授权。
