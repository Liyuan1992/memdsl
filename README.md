# memdsl

[English](#english) | [中文](#中文)

## English

**Agent memory as source code the agent reads itself.**

memdsl started with a retrieval failure. A memory system built on RAG failed
to recall a memory it certainly had; a coding agent pointed at the same raw
memory files traced it down in a few steps. Same model — the difference was
the context contract. The agent knew the memory existed and could keep
reading toward it; the retriever got exactly one similarity guess, and a
miss looked identical to absence.

memdsl turns that difference into the product. Long-term memory lives in
readable, lintable, reviewable `.mem` source files, and every runtime
surface is built for an agent that reads memory itself:

- **A memory map** (`memdsl map`, MCP `memory_map` / `memdsl://map`): a
  compact index of every active memory plus the workspace vocabulary,
  loaded at session start, so the agent knows what exists before it ever
  queries.
- **Queries that explain their misses** (`search_trace` in every serialized
  pack): a no-match reports which matching memories a filter hid and which
  vocabulary the workspace speaks, so a miss is a retry signal instead of a
  dead end.
- **Raw source as the floor** (`memdsl://file/{file_id}`): the agent can
  always drop down and read the actual declarations, the way a coding agent
  reads code.

The failure mode that started the project now fails loud — the memory
exists, a filter hid it, and the trace says exactly that:

```console
$ memdsl query examples/domains/coding -q "force push main" \
    --type coding.bug_pattern --json
  "missing": [
    "no declarations matched query terms: ['force', 'push', 'main']",
    "1 declaration(s) matched the query but were excluded by type/subject filters"
  ],
  "search_trace": {
    "excluded_by_filters": [
      {"id": "coding.project_rule:git.no_force_push", ...}
    ], ...
  }

$ memdsl query examples/domains/coding -q "force push main"
MUST
- [coding.project_rule:git.no_force_push] Never force-push the main branch. (exceptions: [])
```

### Try it with Claude Code in two minutes

```console
pip install "memdsl[mcp]"
claude mcp add memdsl -- memdsl-mcp --workspace ~/memory   # or an examples/ dir
```

The server instructs the agent to read `memory_map` first, treat `no_match`
as a retry signal, and preflight consequential drafts against MUST
constraints with `memory_check`.

### Governed, typed memory

The second pillar: memory you can review like code, **without forcing one
author's ontology on every user**. Version 0.5 separates two concerns that
are easy to conflate:

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
| `constraint` | Surfaces in MUST and participates in compliance checks |
| `guidance` | Surfaces in SHOULD |
| `assertion` | Surfaces in CONTEXT when relevant |
| `question` | Surfaces in MISSING rather than being presented as fact |

The core also understands capabilities such as `requires_evidence`,
`searchable`, `temporal`, `enforceable`, `guardable`, and
`exceptions_recommended`.

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

### Install and inspect

```console
pip install memdsl                 # or: pip install -e . from a checkout
memdsl --version
memdsl types examples/domains/coding
memdsl lint examples/domains/coding
memdsl map examples/domains/coding
memdsl query examples/domains/coding -q "force push main"
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
- [coding.project_rule:git.no_force_push] Never force-push the main branch.
```

The compliance check returns `BLOCK` and cites the same domain declaration.
An unguarded or non-enforceable constraint fails safely to `NEEDS_REVIEW`
instead of being guessed at.

### Layered query contract

Queries return an **EvidencePack**, not a flat hit list:

- `MUST`: applicable `constraint` declarations
- `SHOULD`: relevant `guidance` declarations
- `CONTEXT`: relevant `assertion` declarations
- `CONFLICT`: declared conflicts among selected memories
- `MISSING`: relevant `question` declarations and known gaps

Every item carries a stable declaration id, type, runtime role, capabilities,
claim, subject, scope, confidence, lifecycle, access policy, evidence, and
source location. Domain semantics stay expressive while runtime behavior stays
predictable.

JSON output is versioned as `memdsl.evidence_pack.v1`; scored CONTEXT entries
also include `score` and `matched_terms`.

The reference retriever is deliberately lexical. Production systems can put
BM25, embeddings, graphs, or database indexes behind the same EvidencePack
contract.

### Navigation: a miss is a retry signal, not an answer

memdsl exists because agent-driven reading beats blind similarity matching:
an agent that knows a memory exists can drill down to it, while a retriever
that misses just returns nothing. Two surfaces support that loop:

- **Memory map** (`memdsl map`, MCP `memory_map` / `memdsl://map`, Python
  `build_memory_map`): a compact per-module index of every active
  declaration plus the workspace vocabulary. Load it at session start so the
  agent knows what memory exists before it queries. It is a navigation
  projection, not a citation source: claims are truncated and carry no
  evidence.
- **Search trace** (`search_trace` in serialized packs): how the query was
  interpreted and, crucially, which matching declarations a type/subject
  filter excluded. A no-match with non-empty `excluded_by_filters` means
  "the memory exists; your filter hid it". No-match MCP queries also return
  the workspace vocabulary so the agent can re-ask in the workspace's own
  words.

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

```console
pip install "memdsl[mcp]"
memdsl-mcp --workspace examples/domains/coding --inspect
memdsl-mcp --workspace ~/memory
```

The MCP server exposes:

- tools: `memory_map`, `memory_types`, `memory_query`, `memory_check`,
  `memory_explain`, `memory_list`, `memory_lint`, `memory_propose`,
  `memory_review_list`
- resources: `memdsl://status`, `memdsl://map`, `memdsl://types`,
  `memdsl://files`, `memdsl://file/{file_id}`

Agents should read `memory_map` at session start so they know what memory
exists before querying, and call `memory_types` or read `memdsl://types`
before proposing a declaration. This lets them discover the workspace's
vocabulary instead of inventing a type or assuming the standard pack is the
only valid worldview.

Access can be narrowed with `--scopes` or `MEMDSL_MCP_SCOPES` (default:
`read:summary,read:search,write:candidate`). The core represents and transports
declaration-level `access_policy`, but v0.5 does not claim identity-provider or
multi-tenant policy enforcement; the hosting runtime must bind identities to
those policies.

### Gated writes

MCP writes are propose-only. A proposed declaration must use a loaded type,
parse, and pass lint against the live workspace. Types with
`requires_evidence` require a verbatim evidence quote. Valid proposals wait in
`.memdsl/proposals/` and are never served by `memory_query` until a human
approves them:

```console
memdsl review list ~/memory
memdsl review show ~/memory p-20260710-142530-a1b2c3
memdsl review approve ~/memory p-20260710-142530-a1b2c3 \
  --into ~/memory/approved.mem
memdsl review reject ~/memory p-20260710-142530-a1b2c3 \
  --reason "not durable"
```

Approval revalidates the custom type against the current schema, updates the
target atomically, and records an audit event. File locking and idempotent
markers make concurrent or interrupted retries safe.

### What's in the box

- A domain-neutral `.mem` record with provenance, scope, confidence,
  lifecycle, access policy, relations, and stable ids.
- An extensible, namespaced `.memschema.json` type system and workspace
  manifest.
- A backward-compatible standard type pack for pre-v0.5 workspaces.
- A schema-driven linter, layered query executor, explainer, and deterministic
  Compliance Gate.
- Type discovery through CLI and MCP.
- A human-reviewed, atomic, audit-logged write pipeline.
- Reproducible compliance benchmarks and coding/assistant/writing domain packs.
- Fictional standard examples for Alex and Mira plus a deliberately broken
  linter workspace.

Full grammar and semantics are in [docs/SPEC.md](docs/SPEC.md). In-process hosts
should also read [docs/PUBLIC_API.md](docs/PUBLIC_API.md) and
[docs/UPGRADING.md](docs/UPGRADING.md).

### What memdsl is not

- It is not a replacement for retrieval/extraction systems such as Mem0, Zep,
  Graphiti, or LangMem. It is the governed source format and behavioral
  contract above those systems.
- It is not a universal taxonomy of people or memory. Domain owners define
  their own types.
- It is not a semantic policy oracle. Constraints that cannot be evaluated
  deterministically remain `NEEDS_REVIEW`.
- It is not an automatic memory writer. Agent proposals remain human-reviewed.

### Current evidence and limits

Early evidence from the private single-user system this project was extracted
from showed higher retrieval precision than that system's tuned RAG baseline
on its internal evaluation. That result is encouraging, but it is not evidence
that one ontology generalizes to everyone. The v0.5 architecture makes that
limitation explicit: memdsl standardizes the record and runtime contract while
letting each domain own its vocabulary.

The bundled suites are contract-level, deterministic tests. Cross-model
behavioral claims still require separately recorded model runs.

### Roadmap

- ~~Two-layer core + extensible domain type system~~ — shipped in v0.5
- Schema package distribution, dependency/version constraints, and migrations
- Richer field validators and domain-defined diagnostic rules
- Pluggable retrieval backends behind the EvidencePack contract
- Compiled module indexes for larger workspaces
- Identity-provider adapters for enforcing represented access policies
- Worth-remembering gate metrics to earn progressively safer write automation

### License

Code: [MIT](LICENSE). Specification ([docs/SPEC.md](docs/SPEC.md)): CC-BY-4.0.

---

## 中文

**把 Agent 记忆写成 agent 自己会去读的源代码。**

memdsl 起源于一次召回失败。一个基于 RAG 的记忆系统没能召回一条确实存在的
记忆；而一个 coding agent 拿到同样的原始记忆文件，几步就把它找了出来。
同一个模型——差别在上下文契约：agent 知道那条记忆存在，可以一层层读过去；
检索器只有一次相似度猜测，而且"没命中"和"不存在"看起来一模一样。

memdsl 把这个差别做成了产品。长期记忆保存在可读、可 lint、可审查的 `.mem`
源文件里，每个运行时 surface 都为"agent 自己读记忆"而设计：

- **记忆地图**（`memdsl map`、MCP `memory_map` / `memdsl://map`）：覆盖所有
  活跃记忆的紧凑索引，附带 workspace 词表，会话开始时加载——agent 在提问
  之前就知道记忆库里有什么。
- **会解释自己为什么没命中的查询**（序列化 pack 中的 `search_trace`）：
  no_match 会报告过滤器藏起了哪些本来匹配的记忆、这个 workspace 说什么
  语言——miss 是重试信号，不是死胡同。
- **原始源码兜底**（`memdsl://file/{file_id}`）：agent 随时可以下钻去读
  真正的声明，就像 coding agent 读代码一样。

当年启动这个项目的那种失败，现在会大声报错——记忆存在，是过滤器藏了它，
trace 会把话说明白：

```console
$ memdsl query examples/domains/coding -q "force push main" \
    --type coding.bug_pattern --json
  "missing": [
    "no declarations matched query terms: ['force', 'push', 'main']",
    "1 declaration(s) matched the query but were excluded by type/subject filters"
  ],
  "search_trace": {
    "excluded_by_filters": [
      {"id": "coding.project_rule:git.no_force_push", ...}
    ], ...
  }

$ memdsl query examples/domains/coding -q "force push main"
MUST
- [coding.project_rule:git.no_force_push] Never force-push the main branch. (exceptions: [])
```

### 两分钟在 Claude Code 里跑起来

```console
pip install "memdsl[mcp]"
claude mcp add memdsl -- memdsl-mcp --workspace ~/memory   # 或任意 examples/ 目录
```

server 会指示 agent 先读 `memory_map`、把 `no_match` 当作重试信号，并在
产出重要草稿前用 `memory_check` 对照 MUST 约束做预检。

### 受治理的类型化记忆

第二根支柱：像审代码一样审记忆，**但不要求所有用户接受作者的一套世界观**。
v0.5 把过去容易混在一起的两件事拆成了两层：

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
| `constraint` | 进入 MUST，并参与合规检查 |
| `guidance` | 进入 SHOULD |
| `assertion` | 相关时进入 CONTEXT |
| `question` | 进入 MISSING，而不是伪装成事实 |

底层还识别 `requires_evidence`、`searchable`、`temporal`、
`enforceable`、`guardable`、`exceptions_recommended` 等 capability。

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

### 安装与类型发现

```console
pip install memdsl                 # 或在 checkout 中运行 pip install -e .
memdsl --version
memdsl types examples/domains/coding
memdsl lint examples/domains/coding
memdsl map examples/domains/coding
memdsl query examples/domains/coding -q "force push main"
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
- [coding.project_rule:git.no_force_push] Never force-push the main branch.
```

合规检查会返回 `BLOCK` 并引用同一个领域声明。没有 guard 或不具备执行能力的
约束会安全返回 `NEEDS_REVIEW`，不会假装已经理解。

### 分层查询契约

查询返回的是 **EvidencePack**，而不是扁平命中列表：

- `MUST`：适用的 `constraint`
- `SHOULD`：相关的 `guidance`
- `CONTEXT`：相关的 `assertion`
- `CONFLICT`：已声明的冲突
- `MISSING`：相关的 `question` 和已知信息缺口

每一项都携带稳定 id、类型、runtime role、capability、claim、subject、scope、
confidence、lifecycle、access policy、evidence 和源码位置。这样领域语义可以扩展，
运行时行为仍然稳定。

JSON 输出固定为 `memdsl.evidence_pack.v1`；带分数的 CONTEXT 条目还包含
`score` 和 `matched_terms`。

参考实现目前使用简单的词法检索。生产系统可以在同一个 EvidencePack 契约后面
替换成 BM25、embedding、图或数据库索引。

### 导航：没找到是重试信号，不是最终答案

memdsl 的出发点是"让 agent 自己读记忆"胜过"让相似度匹配替 agent 决定"：
知道某条记忆存在的 agent 可以一层层钻下去，而检索器一旦没命中就什么都没有。
两个 surface 支撑这个闭环：

- **记忆地图**（`memdsl map`、MCP `memory_map` / `memdsl://map`、Python
  `build_memory_map`）：按 module 组织的紧凑索引，覆盖所有活跃声明，并附带
  workspace 词表。会话开始时先加载它，agent 在提问之前就知道记忆库里有什么。
  地图是导航投影，不是引用来源：claim 被截断且不携带 evidence。
- **检索痕迹**（序列化 pack 中的 `search_trace`）：记录查询被如何解释，以及
  最关键的——type/subject 过滤器排除了哪些本来匹配的声明。`no_match` 但
  `excluded_by_filters` 非空意味着"记忆存在，是你的过滤器把它藏起来了"。
  MCP 查询没命中时还会返回 workspace 词表，agent 可以换用记忆库自己的语言
  重新提问。

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

```console
pip install "memdsl[mcp]"
memdsl-mcp --workspace examples/domains/coding --inspect
memdsl-mcp --workspace ~/memory
```

MCP server 提供：

- tools：`memory_map`、`memory_types`、`memory_query`、`memory_check`、
  `memory_explain`、`memory_list`、`memory_lint`、`memory_propose`、
  `memory_review_list`
- resources：`memdsl://status`、`memdsl://map`、`memdsl://types`、
  `memdsl://files`、`memdsl://file/{file_id}`

Agent 应该在会话开始时读取 `memory_map`，先知道记忆库里有什么再提问；在提出
新声明前，应该先调用 `memory_types` 或读取 `memdsl://types`，发现当前
workspace 的词汇，而不是自己发明类型，也不是默认标准兼容包就是唯一世界观。

可通过 `--scopes` 或 `MEMDSL_MCP_SCOPES` 缩小 MCP 权限范围，默认值为
`read:summary,read:search,write:candidate`。底层会表示、验证并传输声明级
`access_policy`，但 v0.5 不声称已经实现身份提供商或完整多租户授权；宿主运行时
仍需负责把真实身份绑定到这些策略。

### 受审查的写入

MCP 只能 propose。新声明必须使用已加载类型，能够解析，并通过当前 workspace
的 lint。具有 `requires_evidence` capability 的类型必须包含逐字证据。合法提案
会进入 `.memdsl/proposals/`，在人工批准前绝不会被 `memory_query` 返回：

```console
memdsl review list ~/memory
memdsl review show ~/memory p-20260710-142530-a1b2c3
memdsl review approve ~/memory p-20260710-142530-a1b2c3 \
  --into ~/memory/approved.mem
memdsl review reject ~/memory p-20260710-142530-a1b2c3 \
  --reason "not durable"
```

批准时会使用当前 schema 重新验证自定义类型，原子更新目标文件并写入审计事件。
文件锁和幂等 marker 使并发或中断后的重试保持安全。

### 包里有什么

- 与领域无关的 `.mem` 通用记录：来源、scope、confidence、lifecycle、
  access policy、relations 和稳定 id。
- 可扩展、带 namespace 的 `.memschema.json` 类型系统和 workspace manifest。
- 面向 v0.5 之前 workspace 的标准兼容类型包。
- schema 驱动的 linter、分层查询、explain 和确定性 Compliance Gate。
- CLI 与 MCP 的类型发现能力。
- 人工审查、原子更新、带审计日志的写入链路。
- 可复现合规 benchmark，以及 coding、assistant、writing 三个领域包。
- Alex、Mira 两个虚构标准示例和一个故意损坏的 lint 示例。

完整语法与语义见 [docs/SPEC.md](docs/SPEC.md)。进程内宿主还应阅读
[docs/PUBLIC_API.md](docs/PUBLIC_API.md) 和 [docs/UPGRADING.md](docs/UPGRADING.md)。

### memdsl 不是什么

- 它不是 Mem0、Zep、Graphiti、LangMem 等检索/抽取系统的替代品，而是位于
  这些系统之上的受治理源格式和行为契约。
- 它不是人或记忆的通用分类法；领域所有者定义自己的类型。
- 它不是语义策略裁判；无法确定性执行的约束会保持 `NEEDS_REVIEW`。
- 它不是自动记忆写入器；Agent 提案仍需人工审查。

### 当前证据与边界

这个项目来自一个私有的单用户系统。该系统的内部评测曾显示，DSL 结构化检索的
precision 高于它自己的调优 RAG baseline。这个结果值得继续验证，但不能证明一套
ontology 对所有人都通用。v0.5 正面承认这个限制：memdsl 标准化记录结构和运行
契约，把领域词汇的所有权交还给使用者。

仓库内置的是确定性的契约级测试。跨模型行为结论仍需单独记录真实模型运行。

### Roadmap

- ~~两层 core + 可扩展领域类型系统~~ — v0.5 已完成
- Schema 包分发、依赖/版本约束和迁移机制
- 更丰富的字段验证器和领域诊断规则
- EvidencePack 后面的可插拔检索后端
- 面向大型 workspace 的编译索引
- 执行 access policy 的身份提供商适配器
- 通过 worth-remembering gate 指标逐步提高写入自动化程度

### 许可证

代码：[MIT](LICENSE)。规范（[docs/SPEC.md](docs/SPEC.md)）：CC-BY-4.0。
