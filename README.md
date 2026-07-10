# memdsl

[English](#english) | [中文](#中文)

## English

**Agent memory as normative source code.**

Most agent memory systems store what you said. Almost none of them
distinguish what an agent *must obey* from what it *may consider*. memdsl
treats long-term memory as a small, typed, lintable source language —
`.mem` files you can read, review, diff, version, and test — where a
`boundary` is a rule to enforce, not a fact to recall.

```mem
preference schedule.deep_work_mornings {
  subject: User
  claim: "Prefers deep work in the morning; meetings after 2pm."
  force: strong
  scope: scheduling
  evidence { source: chat quote: "Stop booking me into morning meetings." }
}

boundary privacy.no_family_in_public {
  subject: User
  rule: "Never include family member names or details in public-facing content."
  force: hard
  scope: global
  exceptions: [user_explicit_override]
  guard {
    when_any: ["public", "blog", "social media"]
    deny_any: ["family", "wife", "daughter", "son"]
  }
  evidence { source: chat quote: "Anything about my family stays out of blog posts. Always." }
}
```

The difference matters: a preference shapes suggestions; a boundary binds.
Flat embeddings of "user said X" erase exactly this distinction, which is
why agents violate rules their memory technically "contains".

### 30 seconds: same question, one declaration apart

Ask an agent to *"draft a public blog post about building Aurora as a
working parent."* A similarity-ranked memory gives it the old chats where
the kids' names appear — and nothing that ranks a rule above a reminiscence.
The retrieved snippets are all just CONTEXT, so the names end up in the post:

```text
retrieved: "...shipped the sync fix after bedtime, Theo finally sleeping..."
retrieved: "aurora beta feedback thread..."
```

With the boundary declared, the evidence pack puts the rule where it cannot
be missed — in MUST, above every piece of context, whether or not the query
lexically matched it:

```console
$ memdsl query examples/alex/ -q "draft a public blog post about aurora"
MUST
- [boundary:privacy.no_family_in_public] Never include family member names
  or details in public-facing content. (exceptions: ['user_explicit_override'])

CONTEXT
- [state:aurora.beta_progress] Private beta with 40 testers; ...
```

Feed the pack to the LLM as context and the compliant behavior is to write
the post *without* family details — and to be able to cite
`boundary:privacy.no_family_in_public` as the reason. The pack is the
prompt; the MUST layer is what changes the answer.

### Lint it, query it

Memory that can be wrong deserves a linter:

```console
$ memdsl lint examples/lint-demo/
broken.mem:7:  error[unresolved_symbol]        subject 'User.Barista' is not a declared entity
broken.mem:20: error[missing_evidence]         active fact 'home.timezone' has no evidence block
broken.mem:28: warning[type_force_mismatch]    preference uses force: hard; promote it to a boundary
broken.mem:41: warning[boundary_without_exception]  confirm it is truly unconditional
broken.mem:53: warning[stale_state]            as_of 2025-11-02 is older than 180 days

6 declarations, 2 error(s), 3 warning(s)
```

Queries return a **layered evidence pack**, not a hit list. Hard
boundaries surface even when the query doesn't lexically match them;
declared conflicts are shown, not averaged away; open issues surface as
gaps instead of being hallucinated over:

```console
$ memdsl query examples/alex/ -q "should aurora keep the free tier"
# resolved subjects: Project.Aurora
MUST
- [boundary:privacy.no_family_in_public] Never include family member names ...

SHOULD
- (none)

CONTEXT
- [decision:aurora.pricing_free_tier] Keep a permanent free tier.
- [state:aurora.beta_progress] Private beta with 40 testers; sync is the top complaint. (as_of 2026-06-20)
- [goal:aurora.revenue_target_2026] Reach $2k MRR from Aurora by end of 2026.

CONFLICT
- [decision:aurora.pricing_free_tier] conflicts_with [aurora.revenue_target_2026]

MISSING
- open issue [open_issue:aurora.pricing_undecided]: Paid tier pricing is undecided: $5 flat vs usage-based.
```

Feed that pack — MUST/SHOULD/CONTEXT/CONFLICT/MISSING — to your LLM as
context. Every line carries a declaration id, so answers are citable and
auditable back to source and evidence.

### Install

```console
pip install memdsl        # or: pip install -e . from a checkout
memdsl lint examples/alex/
memdsl query examples/alex/ -q "plan tomorrow morning"
memdsl explain examples/alex/ decision:aurora.db_postgres_migration
memdsl check examples/compliance/ -t "draft a public blog post" \
  -c "My family helped me build this product."
memdsl eval compliance examples/compliance/ \
  --cases examples/compliance/cases.jsonl
```

Zero core runtime dependencies. Python 3.9+; the current optional MCP SDK
requires Python 3.10+.

Note: `memdsl lint examples/alex/` reports **one intentional warning** —
Alex's `schedule.no_meetings_before_10` boundary declares no `exceptions`,
and the linter asks you to confirm it is truly unconditional. That nudge
is the feature; a clean run is `examples/mira/`.

### Preflight MUST rules

v0.4 boundaries can include a transparent, machine-readable `guard` block.
`memdsl check` returns `ALLOW`, `BLOCK`, or `NEEDS_REVIEW`, always citing the
applicable boundary ids. Phrase/regex guards are deterministic; a natural-
language boundary without a guard fails safely to `NEEDS_REVIEW` instead of
being guessed at. Declared exceptions must be asserted explicitly with
`--exception`.

The shipped `examples/compliance/cases.jsonl` suite is reproducible:

```console
memdsl eval compliance examples/compliance/ \
  --cases examples/compliance/cases.jsonl --json
```

It compares no-memory, flat-context, EvidencePack-only, and Compliance Gate
modes and reports verdict accuracy, unsafe allows, false blocks, MUST recall,
and citation accuracy.

### Use as an MCP server

memdsl ships an optional [MCP](https://modelcontextprotocol.io) server, so
any MCP client (Claude Code, Claude Desktop, ...) can mount a `.mem`
workspace as governed memory:

```console
pip install "memdsl[mcp]"
memdsl-mcp --workspace examples/alex --inspect   # status + lint, no transport
memdsl-mcp --workspace ~/memory                  # stdio MCP server
```

Register with Claude Code:

```console
claude mcp add memdsl -- memdsl-mcp --workspace ~/memory
```

Tools: `memory_query` (layered evidence pack), `memory_check` (preflight a
candidate against MUST rules), `memory_explain` (one
declaration with evidence and relations), `memory_list`, `memory_lint`,
`memory_propose` (stage one declaration for review), `memory_review_list`.
Resources expose the raw `.mem` source (`memdsl://status`, `memdsl://files`,
`memdsl://file/{file_id}`). Access can be narrowed with `--scopes` or
`MEMDSL_MCP_SCOPES` (default `read:summary,read:search,write:candidate`).

The server preserves the layered contract in every tool result — MUST items
stay typed rules with their evidence attached, never flattened into a
relevance-ranked list. `memory_check` adds a CompliancePack with a verdict,
violations, applied exceptions, and unresolved rules.

**Writes are gated (SPEC §10).** An agent can only *propose*: the
declaration must parse and pass lint against the live workspace (verbatim
evidence quote required), then it waits in `.memdsl/proposals/` — same
syntax, different extension, never loaded as memory. A human decides:

```console
memdsl review list ~/memory
memdsl review show ~/memory p-20260708-142530-a1b2c3
memdsl review approve ~/memory p-20260708-142530-a1b2c3 --into ~/memory/self.mem
memdsl review reject ~/memory p-20260708-142530-a1b2c3 --reason "not durable"
```

Approval re-validates against the current workspace, atomically updates the
target `.mem` file, and logs to `.memdsl/audit.log`. File locking plus
idempotent source/audit markers make concurrent or interrupted retries safe.
Until then, `memory_query` never serves it.

### What's in the box

- **A tiny declarative language** (`.mem`): typed declarations
  (`entity`, `fact`, `preference`, `boundary`, `principle`, `decision`,
  `state`, `open_issue`) with force, scope, evidence, relations
  (`supersedes`, `conflicts_with`, `refines`, ...), and lifecycle status.
  Full grammar and semantics in [docs/SPEC.md](docs/SPEC.md).
- **A linter** with code-style diagnostics: dangling symbols, missing evidence,
  ambiguous aliases, stale states, boundaries without exceptions,
  preferences masquerading as laws, unmarked supersede chains.
- **A query executor** implementing the EvidencePack contract, plus
  `explain` for tracing one declaration's relations and provenance.
- **A Compliance Gate** implementing `allow` / `block` / `needs_review`
  preflight over executable boundary guards, with cited violations and
  explicit exception handling.
- **A reproducible compliance benchmark** comparing no-memory, flat-context,
  EvidencePack-only, and Compliance Gate modes on JSONL cases.
- **An MCP server** (optional extra: `pip install "memdsl[mcp]"`) exposing
  the same contract as `memory_query` / `memory_check` / `memory_explain` / `memory_list` /
  `memory_lint` tools plus raw-source resources over stdio.
- **A gated write pipeline**: agents propose (`memory_propose`), proposals
  are linted fail-closed and staged in `.memdsl/proposals/`, and a human
  approves or rejects with `memdsl review` — every step audit-logged.
- **Synthetic example personas** (`examples/`) — fictional users "Alex"
  and "Mira" — and a deliberately broken file for the linter demo.

### What memdsl is *not*

- **Not a replacement for [Mem0](https://github.com/mem0ai/mem0),
  [Zep](https://www.getzep.com/), or
  [LangMem](https://langchain-ai.github.io/langmem/).** Those are
  retrieval/extraction platforms. memdsl is a *source format and
  contract* for the layer above: what memory means, how strongly it
  binds, and how it is maintained. You could compile `.mem` files into
  any of them.
- **Not a retrieval engine.** The reference executor is deliberately
  naive lexical matching — enough to demonstrate the contract. Production
  use should plug BM25/embeddings behind the same EvidencePack interface.
  Do not benchmark toy retrieval and conclude the format failed.
- **Not an auto-writer.** Writes are propose-only: every LLM-proposed
  declaration goes through lint and a human review queue (`memdsl review`)
  before it becomes memory, exactly as the spec (§10) prescribes for early
  deployments. Automation should be earned with audited gate metrics, not
  assumed.

### Does the approach work?

Early evidence from the private system this was extracted from
(DigitalSelf, single-user): on a 100-question eval over the author's real
long-term memory, DSL-structured retrieval nearly doubled top-1 precision
against the same system's tuned RAG baseline (**0.57 vs 0.30**; hit rate
0.67 vs 0.53). On public conversational benchmarks (LongMemEval, LoCoMo)
it performs at parity with baselines under a retrieval-only harness whose
target mapping is still being audited — we explicitly do *not* claim
public-benchmark wins. Current honest costs: seconds-level query latency
at scale in the private implementation (being moved to write-time
compilation), and n=1 personalization. A reproducible benchmark report
will be published separately.

The interesting dimension — and the reason this exists — is **compliance,
not recall**: existing memory benchmarks test whether an agent can *find* a
fact, not whether it *respects* a boundary. v0.4 ships a reproducible
contract-level benchmark and deterministic Compliance Gate. Cross-model
behavioral claims still require separately recorded model runs; the bundled
suite does not pretend otherwise.

### Related work

Typed/structured agent memory is converging fast:
[MemIR](https://arxiv.org/abs/2605.25869) (typed memory IR, provenance-role
separation), [Zep/Graphiti](https://www.getzep.com/) (temporal knowledge
graphs with fact validity windows), [A-Mem](https://arxiv.org/abs/2502.12110)
(Zettelkasten-style linked notes), [MemOS](https://arxiv.org/abs/2507.03724)
(memory scheduling), and the `CLAUDE.md`/`AGENTS.md` culture of local,
reviewable context files. memdsl's position in that landscape: local-first
plain-text source, an explicit **normative layer** (force + boundaries +
exceptions + MUST/SHOULD rendering), and code-style diagnostics as a
first-class surface.

### Roadmap

- Target-mapping audit + reproducible benchmark report
- ~~Deterministic Compliance Gate + reproducible boundary-compliance suite~~ — shipped in v0.4 (`memdsl check`, `memory_check`, `memdsl eval compliance`)
- Pluggable retrieval backends (BM25, embeddings) behind the EvidencePack contract
- Module directory compilation for query planning
- ~~Gated write pipeline with review queue~~ — shipped in v0.3 (`memory_propose` + `memdsl review`)
- ~~Atomic, idempotent review approval~~ — shipped in v0.4
- Worth-remembering gate metrics (false positive rate, wrong kind/force/subject) to earn write automation

---

Today, memdsl defines memory as typed, auditable source code. Future
runtimes can navigate these declarations the way developers navigate
code — following relations, inspecting evidence, tracing history, and
asking for missing information instead of guessing.

### License

Code: [MIT](LICENSE). Specification ([docs/SPEC.md](docs/SPEC.md)): CC-BY-4.0.

---

## 中文

**把 Agent 记忆当作规范性的源代码。**

大多数 Agent 记忆系统会存储你说过什么。几乎没有系统会区分：哪些内容是 Agent **必须遵守** 的，哪些只是它 **可以参考** 的。memdsl 把长期记忆视为一种小型的、有类型的、可 lint 的源语言：也就是你可以阅读、审查、diff、版本管理和测试的 `.mem` 文件。在这里，`boundary` 是需要执行的规则，而不是要回想起来的事实。

```mem
preference schedule.deep_work_mornings {
  subject: User
  claim: "偏好在早晨进行深度工作；会议安排在下午 2 点之后。"
  force: strong
  scope: scheduling
  evidence { source: chat quote: "不要再把会议塞进我的早上了。" }
}

boundary privacy.no_family_in_public {
  subject: User
  rule: "绝不要在公开内容中包含家庭成员的姓名或细节。"
  force: hard
  scope: global
  exceptions: [user_explicit_override]
  guard {
    when_any: ["公开", "博客", "社交媒体"]
    deny_any: ["家人", "妻子", "女儿", "儿子"]
  }
  evidence { source: chat quote: "任何关于我家人的事情都不要出现在博客里。永远不要。" }
}
```

这种差异很关键：偏好会影响建议；边界会形成约束。把“用户说过 X”扁平地塞进 embedding，会抹掉这种区分，所以 Agent 明明“记得”一条规则，却仍然可能违反它。

### 30 秒示例：只差一条声明，答案就不同

让 Agent **“写一篇公开博客，讲讲作为一名有孩子的父母如何构建 Aurora。”** 如果只用相似度排序的记忆，它可能取回过去聊天中出现孩子名字的片段，却没有任何机制把规则排在回忆之上。取回的片段全都只是 CONTEXT，于是名字就会进入文章：

```text
retrieved: "...shipped the sync fix after bedtime, Theo finally sleeping..."
retrieved: "aurora beta feedback thread..."
```

声明了边界之后，证据包会把规则放到 Agent 无法错过的位置：在 MUST 层，位于所有上下文之上。即使查询文本本身没有词面匹配这条规则，它也会出现：

```console
$ memdsl query examples/alex/ -q "draft a public blog post about aurora"
MUST
- [boundary:privacy.no_family_in_public] Never include family member names
  or details in public-facing content. (exceptions: ['user_explicit_override'])

CONTEXT
- [state:aurora.beta_progress] Private beta with 40 testers; ...
```

把这个 evidence pack 作为上下文交给 LLM，合规行为就是写一篇 **不包含** 家庭细节的文章，并且能够引用 `boundary:privacy.no_family_in_public` 说明原因。这个 pack 就是 prompt；MUST 层才是改变答案的部分。

### Lint 它，查询它

会出错的记忆，就应该有 linter：

```console
$ memdsl lint examples/lint-demo/
broken.mem:7:  error[unresolved_symbol]        subject 'User.Barista' is not a declared entity
broken.mem:20: error[missing_evidence]         active fact 'home.timezone' has no evidence block
broken.mem:28: warning[type_force_mismatch]    preference uses force: hard; promote it to a boundary
broken.mem:41: warning[boundary_without_exception]  confirm it is truly unconditional
broken.mem:53: warning[stale_state]            as_of 2025-11-02 is older than 180 days

6 declarations, 2 error(s), 3 warning(s)
```

查询返回的是 **分层 evidence pack**，而不是命中列表。硬边界即使没有与查询词面匹配，也会浮现；声明过的冲突会被展示出来，而不是被平均掉；未解决问题会作为缺口出现，而不是被模型编造过去：

```console
$ memdsl query examples/alex/ -q "should aurora keep the free tier"
# resolved subjects: Project.Aurora
MUST
- [boundary:privacy.no_family_in_public] Never include family member names ...

SHOULD
- (none)

CONTEXT
- [decision:aurora.pricing_free_tier] Keep a permanent free tier.
- [state:aurora.beta_progress] Private beta with 40 testers; sync is the top complaint. (as_of 2026-06-20)
- [goal:aurora.revenue_target_2026] Reach $2k MRR from Aurora by end of 2026.

CONFLICT
- [decision:aurora.pricing_free_tier] conflicts_with [aurora.revenue_target_2026]

MISSING
- open issue [open_issue:aurora.pricing_undecided]: Paid tier pricing is undecided: $5 flat vs usage-based.
```

把这个 pack，即 MUST/SHOULD/CONTEXT/CONFLICT/MISSING，作为上下文喂给你的 LLM。每一行都带有声明 id，因此答案可以回溯、引用和审计到源文件与证据。

### 安装

```console
pip install memdsl        # 或者在 checkout 中运行: pip install -e .
memdsl lint examples/alex/
memdsl query examples/alex/ -q "plan tomorrow morning"
memdsl explain examples/alex/ decision:aurora.db_postgres_migration
memdsl check examples/compliance/ -t "draft a public blog post" \
  -c "My family helped me build this product."
memdsl eval compliance examples/compliance/ \
  --cases examples/compliance/cases.jsonl
```

核心包零运行时依赖，需要 Python 3.9+；当前可选 MCP SDK 需要 Python 3.10+。

注意：`memdsl lint examples/alex/` 会报告 **一个有意保留的 warning**：Alex 的 `schedule.no_meetings_before_10` boundary 没有声明 `exceptions`，linter 会要求你确认它是否真的是无条件规则。这个提醒就是功能本身；如果想看完全干净的运行结果，可以使用 `examples/mira/`。

### 在执行前检查 MUST 规则

v0.4 的 boundary 可以声明透明、机器可读的 `guard` 块。`memdsl check`
返回 `ALLOW`、`BLOCK` 或 `NEEDS_REVIEW`，并始终引用适用的 boundary id。
短语/正则 guard 是确定性的；没有 guard 的自然语言 boundary 会安全降级为
`NEEDS_REVIEW`，而不是假装已经理解。声明过的例外也必须由调用方通过
`--exception` 显式给出。

仓库自带可复现用例集：

```console
memdsl eval compliance examples/compliance/ \
  --cases examples/compliance/cases.jsonl --json
```

它比较 no-memory、flat-context、EvidencePack-only 与 Compliance Gate，
报告 verdict accuracy、unsafe allow、false block、MUST recall 和引用准确率。

### 作为 MCP server 使用

memdsl 提供一个可选的 [MCP](https://modelcontextprotocol.io) server，任何 MCP 客户端（Claude Code、Claude Desktop 等）都可以把一个 `.mem` workspace 挂载为受治理的记忆层：

```console
pip install "memdsl[mcp]"
memdsl-mcp --workspace examples/alex --inspect   # 打印 status + lint，不启动传输
memdsl-mcp --workspace ~/memory                  # stdio MCP server
```

在 Claude Code 中注册：

```console
claude mcp add memdsl -- memdsl-mcp --workspace ~/memory
```

工具：`memory_query`（分层 evidence pack）、`memory_check`（针对 MUST 规则预检候选动作/草稿）、`memory_explain`（单条声明及其证据与关系）、`memory_list`、`memory_lint`、`memory_propose`（提交一条声明进入审查队列）、`memory_review_list`。资源以原始 `.mem` 源码形式暴露（`memdsl://status`、`memdsl://files`、`memdsl://file/{file_id}`）。可以通过 `--scopes` 或 `MEMDSL_MCP_SCOPES` 收窄权限（默认 `read:summary,read:search,write:candidate`）。

server 在每个工具返回值中都保留分层契约——MUST 项始终是携带证据的有类型规则，绝不会被拍扁成一个按相关性排序的列表。`memory_check` 额外返回带 verdict、违规、已应用例外和未决规则的 CompliancePack。

**写入是门控的（SPEC 第 10 节）。** Agent 只能 *提议*：声明必须能解析，并且要通过针对当前 workspace 的 lint（必须携带逐字 evidence quote），然后停在 `.memdsl/proposals/` 里等待——同样的语法、不同的扩展名，绝不会被当作记忆加载。由人来决定：

```console
memdsl review list ~/memory
memdsl review show ~/memory p-20260708-142530-a1b2c3
memdsl review approve ~/memory p-20260708-142530-a1b2c3 --into ~/memory/self.mem
memdsl review reject ~/memory p-20260708-142530-a1b2c3 --reason "不值得长期记住"
```

审批时会针对当前 workspace 重新校验，原子更新目标 `.mem` 文件，并写入 `.memdsl/audit.log`。文件锁和幂等的源码/审计标记保证并发审批或中断后的重试不会重复写入。在那之前，`memory_query` 永远不会提供它。

### 包里有什么

- **一种小型声明式语言**（`.mem`）：有类型声明（`entity`、`fact`、`preference`、`boundary`、`principle`、`decision`、`state`、`open_issue`），支持 force、scope、evidence、relations（`supersedes`、`conflicts_with`、`refines` 等）以及 lifecycle status。完整语法和语义见 [docs/SPEC.md](docs/SPEC.md)。
- **一个 linter**，提供代码式诊断：悬空符号、缺失证据、别名歧义、过期状态、无例外的边界、无效 guard 正则、未标记的 supersede 链等。
- **一个查询执行器**，实现 EvidencePack 契约，并提供 `explain` 来追踪单条声明的关系和来源。
- **一个 Compliance Gate**，针对可执行 boundary guard 实现 `allow` / `block` / `needs_review` 预检，并输出带引用的违规和显式例外。
- **一个可复现的合规 benchmark**，用 JSONL 用例比较 no-memory、flat-context、EvidencePack-only 与 Compliance Gate。
- **一个 MCP server**（可选 extra：`pip install "memdsl[mcp]"`），以 `memory_query` / `memory_check` / `memory_explain` / `memory_list` / `memory_lint` 工具和原始源码资源的形式，通过 stdio 暴露同一套契约。
- **一条门控写入流水线**：agent 提议（`memory_propose`），提案经过 fail-closed 的 lint 校验后暂存在 `.memdsl/proposals/`，由人用 `memdsl review` 批准或拒绝——每一步都写入审计日志。
- **合成示例人格**（`examples/`）：虚构用户 “Alex” 和 “Mira”，以及一个用于 linter 演示的故意损坏文件。

### memdsl 不是什么

- **不是 [Mem0](https://github.com/mem0ai/mem0)、[Zep](https://www.getzep.com/) 或 [LangMem](https://langchain-ai.github.io/langmem/) 的替代品。** 它们是检索/抽取平台。memdsl 是更上层的 **源格式和契约**：记忆意味着什么、约束强度如何、以及如何维护。你完全可以把 `.mem` 文件编译进这些系统。
- **不是检索引擎。** 参考执行器刻意使用了很朴素的词面匹配，只够演示契约。生产环境应该在同一个 EvidencePack 接口背后接入 BM25/embedding。不要拿玩具检索做 benchmark，然后断言格式失败。
- **不是自动写入器。** 写入只能走提议路径：每条 LLM 提议的声明都要经过 lint 和人工审查队列（`memdsl review`）才能成为记忆，与规格文档第 10 节对早期部署的要求完全一致。自动化应该通过审计过的门控指标逐步获得，而不是默认存在。

### 这种方法有效吗？

来自它所抽取自的私有系统（DigitalSelf，单用户）的早期证据显示：在作者真实长期记忆上的 100 问 eval 中，DSL 结构化检索相对于同一系统调优后的 RAG baseline，top-1 precision 接近翻倍（**0.57 vs 0.30**；hit rate 为 0.67 vs 0.53）。在公开对话 benchmark（LongMemEval、LoCoMo）上，它在一个仍在审计 target mapping 的 retrieval-only harness 下与 baseline 大致持平；我们明确 **不声称** 在公开 benchmark 上取得胜利。当前诚实成本包括：私有实现中规模化查询仍是秒级延迟（正在迁移到写入时编译），以及 n=1 个性化样本。可复现 benchmark 报告会单独发布。

真正有意思的维度，也是这个项目存在的原因，是 **合规性，而不是召回率**：现有记忆 benchmark 测试 Agent 是否能 **找到** 一个事实，却很少测试它是否会 **尊重** 一个边界。v0.4 已提供可复现的契约级 benchmark 和确定性 Compliance Gate；跨模型行为结论仍必须来自单独记录的模型运行，内置用例不会冒充这种证据。

### 相关工作

有类型/结构化 Agent 记忆正在快速汇合：
[MemIR](https://arxiv.org/abs/2605.25869)（有类型 memory IR，区分 provenance 与 role）、[Zep/Graphiti](https://www.getzep.com/)（带事实有效期的时序知识图谱）、[A-Mem](https://arxiv.org/abs/2502.12110)（Zettelkasten 风格的链接笔记）、[MemOS](https://arxiv.org/abs/2507.03724)（记忆调度），以及 `CLAUDE.md`/`AGENTS.md` 这种本地、可审查上下文文件的文化。memdsl 在这个版图中的位置是：local-first 的纯文本源、显式的 **规范层**（force + boundaries + exceptions + MUST/SHOULD 渲染），以及把代码式诊断作为一等产品表面。

### Roadmap

- Target mapping 审计 + 可复现 benchmark 报告
- ~~确定性 Compliance Gate + 可复现边界合规用例集~~——已在 v0.4 交付（`memdsl check`、`memory_check`、`memdsl eval compliance`）
- EvidencePack 契约背后的可插拔检索后端（BM25、embedding）
- 用于查询规划的模块目录编译
- ~~带 review queue 的门控写入流水线~~——已在 v0.3 交付（`memory_propose` + `memdsl review`）
- ~~原子、幂等的审批写入~~——已在 v0.4 交付
- worth-remembering 门控指标（误报率、kind/force/subject 判错率），用指标为写入自动化背书

---

今天，memdsl 把记忆定义为有类型、可审计的源代码。未来的 runtime 可以像开发者浏览代码一样浏览这些声明：沿着关系跳转、检查证据、追踪历史，并在信息缺失时主动询问，而不是猜测。

### 许可证

代码：[MIT](LICENSE)。规格文档（[docs/SPEC.md](docs/SPEC.md)）：CC-BY-4.0。
