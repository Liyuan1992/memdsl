# 设计与演进合同：无界 Memory Source、CompiledWorkspace 与有界 Agent View

- 状态：架构提案，尚未实现
- 当前基线：memdsl 0.6.0，commit `72274d9d4f065b76bceaf30f529dcbd47b3f3e18`
- 目标版本：未冻结；必须按本文的阶段门逐步确定
- 读者：memdsl 维护者、宿主集成者、MCP 客户端作者、领域 schema 作者
- 文档语言：中文；公共协议冻结后应同步更新英文 SPEC、PUBLIC_API 和 README

本文档记录 memdsl 从“全量 Memory Map”演进到“Memory Source Code + 编译视图 + 有界任务投影”的完整原因、设计、实施顺序、兼容方案、风险、验证标准和决策记录。

本文不是对现有能力的宣传材料。凡标为“当前事实”的内容均以 0.6.0 源码为准；凡标为“MUST/SHOULD/MAY”的内容都是拟议合同，只有在对应阶段实现、测试、文档和发布门全部完成后，才能成为公开承诺。

文档中的 MUST、MUST NOT、SHOULD、SHOULD NOT、MAY 按规范性要求理解。

---

## 1. 执行摘要

本提案的核心判断不是“Memory 必须保持固定大小”，而是：

> Memory Source 和历史可以持续增长；Agent 每次获得的有效视图和任务上下文必须确定、可审计并受预算约束。

目标架构把现在混在一起的四层彻底分开：

```text
无界、可审、可版本化的 Memory Source / History
                    |
                    v
CompiledWorkspace：确定性编译、链接、诊断、索引后的完整可重建产物
                    |
                    v
面向某个 revision / principal / as_of / scope 的 ResolvedView
                    |
                    v
按任务查询、分页、游标和预算生成的 TaskProjection
                    |
                    v
Agent 本轮实际看到的 Context
```

因此：

1. 不以删除历史、固定声明总量或自动摘要作为扩展性的前提。
2. 不再要求默认 Map 把每条 serviceable declaration 常驻上下文。
3. 不把“active”简单等同于“唯一当前真相”。
4. 不让索引、图、摘要或推断替代源声明及其 evidence。
5. 不让编译器替人判断自然语言事实是否真实；编译器只保证结构、可见性、版本关系和服务边界是确定的。
6. 不在 memdsl 核心中硬编码任何个人方言、私有产品语义、模型提供商、数据库或向量检索设施。

本文建议先冻结 `ResolvedView` 的语义合同，再按“内部索引先行、读取能力渐进增加、执法最后收紧”的顺序实现。这样每一阶段都可以独立发布和回滚。

---

## 2. 问题如何演变：完整讨论记录

### 2.1 起点：Memory Map 会随 workspace 线性增长

0.6.0 的 `build_memory_map()` 会为每一条 serviceable declaration 输出：

- id；
- type；
- runtime role；
- lifecycle status；
- subject；
- scope；
- 截断后的 claim；
- workspace vocabulary。

MCP `memory_map` 还会同时返回结构化 `modules` 和完整 `rendered_text`。当声明持续增加时，默认工具响应、传输体积和常驻 Context 都会线性增加。

最初提出的缓解措施包括：

- 删除结构化数据与文本的重复返回；
- 增加 module/type/subject 过滤；
- 增加分页和游标；
- 将默认 Map 改为模块级摘要；
- 对陈旧内容做归档或摘要。

这些措施中，前四项解决“每次看到多少”；最后一项试图解决“总共存在多少”。

### 2.2 第一轮修正：索引问题与数据总量不是同一个问题

将 Memory 视为 Source Code 后，必须区分：

- Source/History 的总量；
- 当前有效集合；
- 一次任务实际读取的工作集。

Git 历史可以增长，代码仓库的当前树也可以很大；开发者并不会把整个 Linux Kernel 放进工作记忆，而是依靠目录、符号、搜索、引用和局部读取处理具体问题。

因此，Memory 的扩展性目标不应写成“让 Memory 永远很小”，而应写成：

> 让一次任务的可见成本主要由问题范围和明确预算决定，而不是由全部 Memory Source 的大小直接决定。

### 2.3 第二轮修正：Git HEAD 不是 Context Budget

“HEAD 永远只有一个”是有价值的类比，但不能直接作为 memdsl 的最终语义：

- Git HEAD 选择一个 revision，不会让该 revision 的 working tree 自动变小；
- 一个 Git 仓库可以有多个 branch/ref，只是一次 checkout 有一个 HEAD；
- Memory 的有效性还依赖读取主体、时间、scope、review policy 和 access policy；
- 两条冲突记忆可能在不同 scope 或证据条件下同时合法存在。

所以本提案不定义一个全局唯一的 `Memory HEAD`，而定义一个参数化、可复现的有效视图：

```text
ResolvedView = resolve(
    source_revision,
    principal,
    as_of,
    scopes,
    policy_version
)
```

这相当于 Memory Checkout，而不是全局真相指针。

### 2.4 第三轮修正：语义收敛不是控制大小的必要条件

本提案放弃以下前提：

> workspace 超过某个声明数，就必须把多条记忆合成一条摘要。

自动语义合并需要判断哪些内容等价、哪些变化重要、哪些历史仍然有用。memdsl 无法仅凭不完整的人类轨迹可靠完成这种判断。

因此：

- semantic compaction 不是规模正确性的前提；
- semantic refactoring MAY 作为候选提案进入人工审核；
- 重复、矛盾、陈旧、孤立是健康度信号，而不是自动删除条件；
- 物理归档、冷索引和增量编译属于存储工程，不得暗中改变记忆语义。

### 2.5 第四轮修正：图的边也必须可审计

如果未来要让使用者在动态图中验证“A 是否真的支持 B”，只把 `supports: B` 放在 A 的 relations map 中不够。

一条关系本身可能需要：

- 稳定 edge id；
- source/target；
- relation type；
- provenance；
- evidence；
- lifecycle；
- confidence；
- reviewer；
- confirmed/disputed/retracted 状态。

A 节点的 evidence 不能自动证明“A supports B”这条边。因此，本提案把“派生边索引”和“可独立审核的一等边”分成两个阶段，避免一次性扩大语法。

### 2.6 第五轮修正：方言属于 workspace，不属于核心代码

个人记忆天然有长尾语言。核心不应维护“所有人都适用”的固定词汇，而应允许每个 workspace 声明自己的方言：

- 用户如何称呼某个 subject；
- 某个短语在什么 scope 下映射到什么 symbol；
- 哪些短语有歧义；
- 哪些映射是候选、已确认或已否定；
- 这些映射来自哪些 miss -> retry -> hit 样本。

方言表必须是可读、可审、可版本化的 workspace 资产，而不是藏在 Python 代码、数据库或不可见模型状态中的动态补丁。

### 2.7 最终问题陈述

本提案最终要解决的不是一个问题，而是四个彼此独立的问题：

| 问题 | 正确目标 | 不正确的替代目标 |
| --- | --- | --- |
| Context 扩展性 | 每次投影有预算、分页、游标和下钻 | 强制 Memory 总量固定 |
| 当前性 | 产生确定、可解释的 ResolvedView | 把所有 non-excluded 声明都叫 HEAD |
| 导航性 | 目录、索引、trace、incoming/outgoing edges | 常驻每条声明摘要 |
| 真实性 | evidence、事件、反驳和人工审核 | 让编译成功冒充事实真实 |

---

## 3. 当前 0.6.0 源码基线

本节只描述已经存在的行为。

### 3.1 Workspace 加载

当前 `Workspace.load()`：

1. 递归查找所有 `.mem` 文件；
2. 每次构造 Workspace 时解析全部文件；
3. 将所有 declaration 放入一个列表；
4. 不建立持久化符号索引、反向关系索引或 module index；
5. MCP service 仅按文件 mtime + size 缓存整个 Workspace。

因此，当前加载成本与被扫描的源文件和声明总量相关。

### 3.2 `active()` 的真实含义

`Workspace.active()` 当前只排除：

```text
superseded
retracted
archived
```

它仍可能包含：

- `active`；
- `candidate`；
- 未来新增但未排除的其他 lifecycle status。

所以 `active()` 的实际含义是 `serviceable/non-excluded`，不是严格的 lifecycle `status == active`。0.6.0 的 query/compliance 已在关键路径显式检查 status，未来重构不能破坏这一兼容事实。

### 3.3 supersedes 的当前行为

0.6.0 parent baseline 中，`superseded_ids()` 收集每条声明 relations 中所有
`supersedes` target，Map/query 再把这些 raw target 排除。Phase 0A 保留该方法的
兼容观察用途，但所有 authority-bearing 读取面已改用独立的最小 resolver：只有
active source、结构可识别的 edge 和唯一解析 target 才产生排除效果。

当前没有：

- revision family；
- 分叉检测；
- 环检测；
- 唯一 successor；
- relation direction/type compatibility；
- 版本选择算法。

0.6.0 parent baseline 还有一个必须先修的 authority 边界缺陷：
`superseded_ids()` 从**所有** declaration 收集 `supersedes`，不检查发起声明的
lifecycle status、runtime authority、结构有效性或可见性。Phase 0A 已修复其中
不依赖未来 View/visibility 的最小部分。

在 0.6.0 parent baseline 中，这意味着一条 candidate、retracted 或 archived
declaration 也可能隐藏 active target。用该基线源码构造：

```mem
boundary safety.no_foo {
  claim: "Do not use foo."
  scope: global
  evidence { source: "synthetic" quote: "No foo." }
  guard { deny_any: [foo] }
}

fact draft.override {
  claim: "Unconfirmed override."
  lifecycle { status: candidate }
  relations { supersedes: safety.no_foo }
}
```

0.6.0 parent baseline 的实际行为是：

- `safety.no_foo` 从 Map 消失；
- query 不再把它放入 MUST；
- compliance 对包含 `foo` 的 candidate 返回 `allow`；
- lint 只有 `unmarked_supersede_status` warning，没有阻断。

因此第一条待修不变量是：

> 只有在当前 View 中 authoritative、active、结构有效且对该 View 可见的 supersedes edge，才可以改变 authoritative target 的可见性或执行语义。

非权威 lane 不能通过 relation 改变权威 lane。

这是已知 correctness/security defect，不应为了追求“内部重构完全 parity”而长期固化。它可以让本应 BLOCK 的 compliance 变成 ALLOW，必须在 CompiledWorkspace 大规模改造前或同一早期修复阶段处理，并在 release notes/UPGRADING 中明确说明。

两个最小合成行为如下：

#### 分叉

```mem
fact topic.old { ... }

fact topic.left {
  ...
  relations { supersedes: topic.old }
}

fact topic.right {
  ...
  relations { supersedes: topic.old }
}
```

结果：`topic.left` 和 `topic.right` 都会进入默认服务集合。系统没有定义哪个是当前版本，也没有把分叉本身报告为 conflict。

#### 循环

```mem
fact topic.a {
  ...
  relations { supersedes: topic.b }
}

fact topic.b {
  ...
  relations { supersedes: topic.a }
}
```

结果：两者都可能被默认 Map/query 排除。当前 lint 不报告 cycle error。

0.6.0 parent baseline 的不同读取面没有共享一个统一 current set。Phase 0A 已让
Map/query/compliance、默认 `memory_list`、status authority counts 和
`workspace_vocabulary` 共享同一个最小 `current_declarations()` helper；这只是
0.6 兼容集合的一致化，不是 ResolvedView。

`unmarked_supersede_status` warning 与 append-only revision 合同存在张力：它曾建议
把旧节点原地改成 `status: superseded`，而规范修订路径要求追加新 declaration +
supersedes，不静默改写已批准历史。Phase 0A 已停止发出该 warning；旧节点无需
原地改写，排除效果来自 active、唯一解析的 incoming supersedes relation。

### 3.4 Reference resolution 的当前不一致

Phase 0A 只为 supersedes authority effect 增加了最小安全 resolver：full id 必须
精确命中，bare name 只有唯一时才产生 authority effect。除此之外，当前 full id
和 bare name 仍没有覆盖 lint、`by_id()`、explain 和全部 relation 的统一 resolver：

- `by_id("shared")` 返回 declaration list 中第一个 bare-name 命中；
- 不同 kind 可以共享 bare name；
- lint 把 `target.split(":", 1)[-1]` 作为 bare fallback；
- explain incoming checks 仍主要做 exact id/name 对比。

因此除 supersedes authority effect 已 fail safe 外，仍可能出现：

- lint 认为 relation 已解析，但运行时不建立 edge；
- 错误 kind prefix 通过 lint，却不产生 supersede 效果；
- 相同 Source 仅因文件顺序不同而把 bare ref 指向不同 kind。

CompiledWorkspace MUST 提供唯一 reference resolver：full id 优先；bare name 只有在唯一时才解析；错误 kind prefix 不得静默回退，除非明确 compatibility mode 记录该行为。

不同 kind 还可以共享 bare name；当前 `by_id("shared")` 会返回 declarations 列表中的第一个命中，lint 不报告 ambiguous relation target。文件加载顺序因此可能影响 explain/链接结果。

duplicate full id 虽然是 lint error，但 read path 仍可能服务：Map 可以出现两个相同 id，explain 只返回第一个。Compiler 必须保留所有 source occurrences 和 duplicate diagnostic，不能在构造单值 dict 时悄悄覆盖其中一条。

relation name 当前也是固定白名单；nested relations 中拼错的未知 key 可能被 `Declaration.relations()` 忽略，而没有专门 unknown-relation diagnostic。Relation registry 落地时必须显式诊断未知 relation，不能把拼写错误编译成“没有边”。

### 3.5 Module 与 `use`

Parser 会把：

```mem
module projects.aurora
use Project.Aurora
```

保存到 `Document.module` 和 `Document.uses`。

但 `Workspace.add_document()` 当前只复制 declaration 和 module，没有保存或执行 `Document.uses`。所以：

- module 当前是分组标签和阅读边界；
- `use` 当前是已解析但未链接的语法；
- relation/subject 解析仍然使用 workspace 全局可见性；
- 不能把当前 `use` 描述为 import gate。

Parser 还允许同一文件多次出现 `module`，并在文档解析结束后把**最后一个** module 赋给该文件内所有 declarations。所有 `use` 也只是 document-level 扁平列表，没有保留每条声明所在位置的 import context。

未来 strict visibility 不能直接假设当前 AST 已保存 lexical module scope。必须先选择并冻结：

- 一文件只允许一个 module，并由 lint/parser 拒绝重复 module；或
- AST 为每条 declaration 保存当时的 module/use context。

### 3.6 Lint 与读取路径

Lint 当前可以报告：

- duplicate id；
- duplicate content；
- ambiguous alias；
- unresolved subject/relation target；
- schema/field/evidence/lifecycle/access/guard 问题；
- stale memory；
- module reading budget warning。

但 CLI `map/query/explain/check` 和 MCP `memory_map/query/explain/check/list` 不会先执行 lint gate。它们只会对 parse/schema 级失败进行 fail-closed 处理。

因此，一个包含 lint error 的 workspace 目前仍可能被查询和解释。

### 3.7 Map

当前 Map：

- 遍历所有 serviceable declarations；
- 按 module 分组；
- 每条输出最小导航字段；
- claim 默认截断为 120 字符；
- 不带 evidence；
- vocabulary 的 subjects/scopes/modules 默认最多各 50 项，但没有完整的 truncation metadata；
- CLI 只有 `--json`，没有 filter/page/cursor；
- MCP 无参数；
- MCP 同时返回结构化 modules 和 rendered text。

`claim_chars=120` 也不是完整 per-item 上限：symbol summary 会拼接全部 aliases，vocabulary 中一个 subject 可携带完整 aliases list，lifecycle map 也会整体复制。因此少量声明也可能通过超长 alias/lifecycle 字段产生大响应。后续预算必须覆盖单项字节、alias 数量/长度和规范化字段，而不仅仅是 declaration 数量。

SPEC 明确要求 Agent 在查询前把这个 Map 放进 Context。这个契约是本提案要改变的主要公共行为之一。

### 3.8 Query

当前 `build_evidence_pack()`：

1. 对 query 做词法分词；
2. 扫描 active symbol aliases；
3. 构造所有 serviceable searchable declarations 的 pool；
4. 按 type/subject 过滤；
5. 对候选逐条做词法评分；
6. 独立限制 active 和 provisional 结果；
7. 再扫描 constraints 组装 MUST；
8. 返回 search_trace。

结果条数已经有 `limit`，所以输出 Context 可以有界；但候选计算、alias map 和 constraint 扫描目前仍与 workspace 总量相关。

### 3.9 Explain 与关系图

`memory_explain` 已返回：

- 当前声明的 outgoing relations；
- `referenced_by` incoming relations。

但 `referenced_by` 是每次 explain 时扫描全部 declarations 和 relations 现算的。它证明 incoming edge 已经有真实需求，也证明 CompiledWorkspace 中建立 incoming index 是合理的内部优化。

`memory_explain` 当前还会无分页地返回完整 evidence、fields 和全部 incoming `referenced_by`；高入度节点或超大 evidence 可以让一次响应线性膨胀。Query 也同时返回结构化 EvidencePack 和 rendered text，且 evidence 没有统一 byte budget。读取预算不能只覆盖 Catalog/List/Trace，必须覆盖 Explain 和 Query v2。

### 3.10 Review 与写入

0.6.0 已具备：

- proposal；
- pending/approved/rejected；
- append-only audit；
- policy-aware `ReviewStore.submit()`；
- 狭窄的 candidate assertion 自动批准；
- PROVISIONAL 隔离；
- 人工 revision/supersedes 路径。

这些机制必须复用。未来的 dialect candidate、edge confirmation、refactoring proposal、staleness review 都不应绕过现有 review lane。

### 3.11 Access policy 与 raw source

0.6.0 会表示、验证和传输 access_policy，但 reference runtime 不认证 principal，也没有在 map/query/list/explain/vocabulary 中执行 declaration-level read filtering。

此外，MCP source resources 当前：

- `list_files` 返回实际文件路径；
- `read_file` 返回整份 `.mem` 内容。

如果一份文件混有不同 access policy 的 declarations，仅对 query 结果做过滤仍然会被 raw file、path、count、vocabulary、incoming refs 或 diagnostics 旁路。

未来 access-aware View 必须覆盖**全部读取面**，而不是只给 `memory_query` 增加 principal 参数。若无法安全提供原始混合文件，必须拒绝 raw-file read、提供按 declaration 的授权 source projection，或由宿主划分物理文件边界。

同样，`valid_until`/staleness 当前主要是 lint warning，不会自动让声明退出 Map/query。未来让 `as_of` 或 `valid_until` 改变服务集合属于真实语义变化，必须通过 compatibility mode、新 schema 和 UPGRADING 迁移，不能把它伪装成纯内部优化。

### 3.12 当前复杂度概览

以下只描述参考实现的主要趋势，不是微基准承诺：

| 操作 | 当前主要成本趋势 |
| --- | --- |
| Workspace load | O(files + declarations) 全量解析 |
| `by_id` | O(declarations) |
| alias map | O(declarations + aliases) |
| query candidate scoring | O(serviceable searchable declarations) |
| explain incoming refs | O(declarations x relations) |
| full memory map | O(serviceable declarations) 输出 |
| lint | 多次全量扫描；常见近线性，但线性 `by_id` 嵌套在 target/alias 检查中时最坏可超线性或接近 O(N²) |

---

## 4. 目标、非目标与边界

### 4.1 目标

完整方案 MUST：

1. 允许 Source 和语义历史持续增长，不以固定声明总量作为正确性条件。
2. 为每次服务产生确定、可复现、带 revision/context 的 ResolvedView。
3. 将默认 session-start 导航成本从“每条声明”改为“有硬预算的目录投影”。
4. 为 module/type/subject/status/runtime_role 提供索引和按需下钻。
5. 为 outgoing/incoming relations 提供稳定索引和确定性 trace。
6. 显式检测 dangling、duplicate identity、supersede fork、cycle 和 visibility violation。
7. 在不让整个 workspace 全盲的前提下隔离局部污染。
8. 让每个响应明确暴露 served、provisional、quarantined、excluded 和 diagnostics。
9. 允许 workspace 用声明式资产维护自己的方言。
10. 保持所有权威写入经过 proposal/review/approval。
11. 保持 memdsl 核心与特定用户、产品、模型、数据库和 UI 解耦。
12. 提供兼容旧 workspace、Python API、CLI 和 MCP 客户端的渐进迁移路径。

### 4.2 非目标

第一轮完整实现不做：

- 自动判断自然语言事实真实或虚假；
- 自动把多条记忆不可逆地摘要成一条；
- 自动把 candidate 提升为 active；
- 在核心中运行 embedding 模型；
- 内置向量数据库、图数据库或外部搜索服务；
- 自动创建 Git commit 或用 Git history 替代语义 revision chain；
- 定义一个所有人共享的个人记忆分类体系；
- 内置动态图 UI；
- 强迫第三方 Agent 一定遵循推荐读取协议；
- 把 access_policy 的身份认证责任从宿主移到 memdsl 核心。

### 4.3 开源中立边界

可以进入 memdsl 核心的能力：

- 通用 parser/compiler/index/view contract；
- 通用 relation registry 和 trace；
- 通用 dialect declaration contract；
- 通用诊断、隔离、分页、游标、预算和 review 接口；
- 小型、明确合成的公开 fixture。

必须留在宿主或领域 schema 的能力：

- 某个具体人的 aliases 和方言数据；
- 私有 memory workspace；
- 特定产品的 revision identity 规则；
- 模型生成 candidate 的 prompt 和业务触发逻辑；
- UI、数据库、embedding、事件采集和用户身份绑定；
- 私有 review policy。

### 4.4 Python 兼容边界

- dependency-free core 和 CLI MUST 继续支持 Python 3.9+，除非单独发布并记录 breaking decision；
- MCP extra/server 继续要求 Python 3.10+，因为上游 MCP SDK 的约束；
- compiler/view/index 的实现不能无意使用仅 Python 3.10/3.11 可用的语法或标准库 API；
- CI 必须覆盖 core 的受支持 Python 矩阵，并至少在一个受支持版本上跑 MCP 真实 round-trip。

---

## 5. 术语

### 5.1 Memory Source

用户可读、可审、可版本化的 `.mem`、schema、manifest 和 policy 文件。Source 是规范性权威。

### 5.2 Source History

Source 的历史版本以及 declaration 之间显式的 revision/supersedes 关系。Git history 和语义 revision graph 是两件不同的事：

- Git history 记录文件如何变化；
- 语义 revision graph 记录一个记忆声明如何被另一个声明替代、修订或反驳。

### 5.3 CompiledWorkspace

由 Source 确定性构建的内存或可缓存产物，包含：

- declarations；
- symbols；
- indexes；
- normalized edges；
- diagnostics；
- source fingerprint；
- compilation metadata。

CompiledWorkspace 不是权威存储；删除后必须能从 Source 重建。

### 5.4 ViewContext

产生一次有效视图所需的宿主上下文，至少包括：

- source revision/fingerprint；
- principal（若宿主已认证）；
- as_of 时间；
- granted scopes；
- policy/schema versions；
- feature/compatibility mode。

### 5.5 ResolvedView

CompiledWorkspace 在给定 ViewContext 下解析得到的确定性可服务视图。它不是摘要，而是带原因分类的集合：

- authoritative；
- provisional；
- quarantined；
- excluded。

### 5.6 TaskProjection

从 ResolvedView 按任务、过滤条件、budget、page/cursor 投影出的实际响应。Agent Context 只接收 TaskProjection，而不是整个 Source 或整个 ResolvedView。

### 5.7 Catalog

有硬预算的高层导航投影，默认按 module/type/role 提供摘要和计数，不枚举所有 declarations。

### 5.8 Trace

从一个或多个 anchor 沿显式或结构性关系进行的确定性、受预算约束的图遍历结果。

### 5.9 Dialect

某个 workspace 自己声明的 phrase、symbol、intent、scope 和消歧规则。Dialect 是 Source 资产，不是核心代码中的用户特例。

### 5.10 Semantic refactoring

通过新 proposal 修订、合并、拆分、反驳或重新组织记忆，以改善一致性和检索信号。它不以缩小总量为唯一目的，也不物理删除历史。

### 5.11 Physical compaction

对缓存、索引、冷历史或物理存储布局做整理。它不得改变声明的逻辑含义、权威状态或审计历史。

---

## 6. 规范性设计原则

### 6.1 Source authority

- Source declarations MUST 是规范性权威。
- Index、catalog、trace、summary、compiled cache MUST 是可重建投影。
- 任何运行时投影 MUST 能追溯到 source file、line、declaration id 和 source fingerprint。

### 6.2 Human authority

- 编译成功 MUST NOT 被描述为“声明内容真实”。
- relation target 存在 MUST NOT 被描述为“A 真的支持 B”。
- 模型生成的 alias、edge、summary、refactoring MUST 先进入 candidate/review lane。
- 人工批准仍是高影响语义变更的最终权威。

### 6.3 Explicit currentness

- 系统 MUST NOT 仅凭更新时间、文件顺序或 lexical order 自动选择当前声明。
- supersedes/revision semantics MUST 由显式关系和稳定规则决定。
- 分叉、环、断链 MUST 显式诊断，不得静默挑选赢家。
- 非权威、非 active、结构无效或对当前 View 不可见的 edge MUST NOT 改变 authoritative lane、MUST 或 compliance。

### 6.4 Bounded projection

- 每个导航、query、explain、trace、list 和 source-projection 响应 MUST 有 item/byte 或等价的硬预算。
- 达到预算 MUST 返回 `truncated: true` 和稳定 cursor/next action。
- vocabulary 截断 MUST 可见，不能静默切片。
- 默认 session-start 响应 MUST NOT 与 declaration 总量线性等比例输出。

预算不能制造“假完整性”：

- 普通导航/上下文可以截断，但必须标记 completeness；
- 适用的 hard constraint/compliance rule 不得因普通 result limit 静默遗漏；
- 若权威规则无法在当前预算或授权条件下完整处理，响应 MUST fail loud，例如 `needs_review`、`completeness: budget_limited` 或宿主等价状态；
- 不能返回一个看似完整的小 Context，却省略会改变行动许可的规则。

### 6.5 Determinism

在相同 Source、ViewContext 和请求参数下：

- 编译 diagnostics；
- indexes；
- ResolvedView 分类；
- 排序；
- cursor；
- trace tree；
- JSON serialization

MUST 确定一致，不依赖文件系统遍历偶然顺序、Python hash seed 或并发完成顺序。

### 6.6 Visible degradation

- 局部错误导致隔离时，响应 MUST 暴露 quarantined ids 和原因。
- 整体拒服时，响应 MUST 暴露 blocking diagnostics。
- 系统 MUST NOT 通过返回空结果伪装成“没有记忆”。

### 6.7 Authorization before aggregation

- access filtering MUST 发生在 counts、catalog、vocabulary、trace、incoming refs、diagnostics 和 raw source 输出之前；
- 未授权内容不能通过数量、模块名、文件路径、alias、edge 或错误消息泄露存在性；
- `readable`、`applicable` 和 `enforceable` SHOULD 被区分：一条规则可能由可信宿主执行，但正文不能向当前 Agent 暴露；
- core 只能在宿主提供可信 principal/role 后应用声明策略，不能自行完成身份认证。

### 6.8 Compatibility before enforcement

- 新编译器和索引 SHOULD 先以 behavior-preserving 模式替换内部扫描。
- 新 diagnostics SHOULD 先 shadow/report，再 opt-in enforcement，最后才考虑默认收紧。
- 旧 schema envelope MUST 在明确 deprecation window 内继续工作。

---

## 7. 目标架构

```text
                   +-------------------------+
                   | .mem / schema / manifest|
                   | policy / approved source|
                   +------------+------------+
                                |
                                v
                   +-------------------------+
                   | WorkspaceCompiler       |
                   | parse / normalize / link|
                   | diagnose / index        |
                   +------------+------------+
                                |
                                v
                   +-------------------------+
                   | CompiledWorkspace       |
                   | symbol + module indexes |
                   | outgoing/incoming edges |
                   | revision graph          |
                   | diagnostics + fingerprint|
                   +------------+------------+
                                |
                 ViewContext    |
          principal/as_of/scope |
                                v
                   +-------------------------+
                   | ViewResolver            |
                   | authority / provisional |
                   | quarantine / exclusion  |
                   +------------+------------+
                                |
                                v
                   +-------------------------+
                   | ResolvedView            |
                   +---+----------+----------+
                       |          |          |
                       v          v          v
                    Catalog     Query      Trace/Explain
                       |          |          |
                       +----------+----------+
                                  |
                         budget/page/cursor
                                  |
                                  v
                           TaskProjection
```

写入路径与读取路径分离：

```text
query/trace现场 -> host生成候选草稿 -> memory_propose
                                      |
                                      v
                            policy / queue / audit
                                      |
                                      v
                              human approve/reject
                                      |
                                      v
                                append Source
```

编译器不能直接修改 Source；读取发现问题也不能静默修复 Source。

---

## 8. CompiledWorkspace 设计

### 8.1 建议公共形状

第一阶段可以保持内部类型，稳定后再考虑从包根导出：

```python
@dataclass(frozen=True)
class CompiledWorkspace:
    source_fingerprint: str
    declarations: tuple[Declaration, ...]
    occurrences_by_id: Mapping[str, tuple[Declaration, ...]]
    resolved_by_id: Mapping[str, Declaration]
    by_name: Mapping[str, tuple[str, ...]]
    by_module: Mapping[str, tuple[str, ...]]
    by_type: Mapping[str, tuple[str, ...]]
    by_runtime_role: Mapping[str, tuple[str, ...]]
    by_subject: Mapping[str, tuple[str, ...]]
    by_scope: Mapping[str, tuple[str, ...]]
    aliases: Mapping[str, tuple[str, ...]]
    outgoing: Mapping[str, tuple[CompiledEdge, ...]]
    incoming: Mapping[str, tuple[CompiledEdge, ...]]
    revision_families: Mapping[str, RevisionFamily]
    diagnostics: tuple[Diagnostic, ...]
    metadata: CompilationMetadata
```

真实实现可使用普通 dict/list，但对外观察必须不可变且确定排序。

### 8.2 必需索引

#### Identity index

- 完整 declaration id -> 所有 source occurrences；
- 仅在唯一时提供 resolved full-id lookup；
- bare name -> 所有候选完整 id；
- duplicate full id 诊断；
- ambiguous bare name 诊断。

#### Module index

- module -> declaration ids；
- document/file -> module；
- module -> declared `use` symbols/modules；
- module-level counts 和 lifecycle summary。

#### Semantic indexes

- type；
- runtime role；
- lifecycle status；
- subject；
- scope；
- capability；
- alias/phrase。

#### Graph indexes

- source id -> outgoing edges；
- target id -> incoming edges；
- relation type -> edges；
- revision/supersede families；
- detected cycles/forks。

### 8.3 `CompiledEdge`

第一阶段从现有 `relations` 字段派生：

```python
@dataclass(frozen=True)
class CompiledEdge:
    edge_id: str
    source_id: str
    relation: str
    target_ref: str
    target_id: str | None
    provenance: str       # explicit | structural | inferred
    file: str
    line: int
    status: str           # resolved | dangling | ambiguous | quarantined
```

第一阶段只允许：

- `explicit`：来自 `.mem` relations；
- `structural`：由 compiler 从 module/revision 等确定结构派生。

`inferred` edge MUST 延后。除非未来有独立 proposal、evidence、review 和可关闭的 capability，否则不得把 embedding/LLM 推断边混入权威图。

### 8.4 Source fingerprint

fingerprint SHOULD 覆盖：

- 所有 `.mem` 文件的规范路径、大小、mtime 和内容 hash；
- schema 文件内容；
- `memdsl.json`；
- 影响 View 语义的 policy/config；
- compiler contract version。

仅使用 mtime + size 可作为快速 invalidation hint，但不能作为跨进程、审计或持久化 cache 的唯一内容身份。

### 8.5 缓存

缓存必须满足：

- cache miss 时可从 Source 完整重建；
- cache corruption 不影响 Source；
- cache format 有独立 version；
- cache 不进入 wheel/sdist；
- cache 默认不包含不必要的原始 evidence 副本；
- workspace path 和真实用户内容不得出现在公开 fixture。

第一阶段 MAY 只做进程内 cache，不应为性能预期过早引入数据库。

### 8.6 确定性排序

所有 index value 和 edge list SHOULD 使用稳定 key，例如：

```text
(declaration.id, declaration.file, declaration.line)
(relation, target_id_or_ref, source_id, file, line)
```

不能依赖：

- `os.walk()` 偶然顺序；
- dict/set 非合同顺序；
- Python hash seed；
- 并行任务完成顺序。

### 8.7 第一阶段行为要求

CompiledWorkspace 首次落地 MUST：

- 保持现有 query/map/explain/list/compliance 结果语义；
- 只替换内部 O(N) lookup 和 incoming scan；
- 不引入新的默认拒服；
- 新 diagnostics 可采集但只能 shadow 输出或测试使用；
- 提供 parity tests，证明旧实现与索引实现对既有 fixture 等价。

---

## 9. ResolvedView：真正的 Memory Checkout

### 9.1 为什么不能只有一个全局 HEAD

一份 Memory Source 可以同时支持多个合法读取视图：

- owner 可见、public agent 不可见；
- 某条 state 在过去有效、现在过期；
- 某个项目 scope 下有效、global scope 下不适用；
- candidate 对 reviewer 可见，但不能进入 authoritative lane；
- 冲突声明需要同时展示给审阅者，而不是静默选一个。

因此，ResolvedView 是一次带上下文的 checkout，不是 workspace 的永久单例。

### 9.2 `ViewContext`

建议形状：

```python
@dataclass(frozen=True)
class ViewContext:
    source_fingerprint: str
    as_of: date
    principal: str | None = None
    granted_scopes: frozenset[str] = frozenset()
    policy_version: str = ""
    compatibility_mode: str = "v0.6"
    enforcement_mode: str = "report"  # report | quarantine | strict
```

约束：

- `principal` MUST 来自宿主认证上下文，不能由 query 参数自报后直接信任；
- `as_of` MUST 显式记录在 View metadata 中；
- 同一个 View MUST 固定 source fingerprint，分页期间不能悄悄跨 revision；
- cursor 请求若发现 source fingerprint 已变化，MUST 返回 `cursor_stale`，不能把两次 revision 拼成一页。

### 9.3 View 分类

每条 declaration 最终进入且只进入以下主分类之一：

| 分类 | 含义 |
| --- | --- |
| authoritative | 在当前 View 中具有对应 runtime authority |
| provisional | 可作为线索，但不具有 active authority |
| quarantined | Source 中存在，但局部结构错误使其不能安全服务 |
| excluded | 因 lifecycle、access、supersedes、scope 或其他确定规则不进入本 View |

响应 SHOULD 提供计数，并允许在授权范围内查看原因：

```json
{
  "view": {
    "view_id": "...",
    "source_fingerprint": "...",
    "as_of": "2026-07-14",
    "mode": "report"
  },
  "counts": {
    "authoritative": 120,
    "provisional": 8,
    "quarantined": 2,
    "excluded": 44
  }
}
```

### 9.4 View id

`view_id` SHOULD 是以下规范内容的稳定 hash：

- source fingerprint；
- compiler/view contract version；
- as_of；
- principal identity digest 或匿名标记；
- granted scopes；
- policy version；
- enforcement mode。

响应不得泄露未经授权的 principal 原文。必要时只输出宿主提供的 opaque principal id 或 digest。

### 9.5 currentness 与 revision family

#### 最小安全规则

第一版 MUST 遵循：

1. 只有显式 `supersedes` 才能让 target 退出默认 authoritative view；
2. 文件顺序、line、mtime、`as_of` 新旧和 id lexical order 都不能自动决定 successor；
3. `revision_of` 只表达历史关系，不自动排除 target；
4. 一条 successor 可以 supersede 多个旧声明；
5. 多条 successor supersede 同一 target 时形成 fork diagnostic；
6. supersedes/revision_of cycle 必须检测；
7. dangling/ambiguous target 不能被当作成功 supersede；
8. 冲突不得通过“只返回排序第一条”隐藏。

#### Fork 处理

默认建议：

- `report` mode：两个 successor 都可服务，但返回 `revision_fork` diagnostic；
- `quarantine` mode：只隔离参与不允许分叉关系的声明，不影响无关声明；
- `strict` mode：若 schema/registry 把该 revision relation 标记为 identity-critical，可阻止整个受污染 family 服务。

不得在没有 schema 合同的情况下把所有领域声明都强制成单值变量。记忆可能天然允许多条并存观察。

#### Cycle 处理

- supersedes cycle MUST 至少是 error；
- cycle 中的排除效果 MUST 不生效，避免 A/B 都静默消失；
- cycle 节点 SHOULD 进入 quarantine；
- 响应 MUST 暴露 cycle path；
- 修复只能通过新 proposal/人工编辑完成。

### 9.6 逻辑 identity 不能由核心猜测

“同一 subject + type + scope”不一定代表同一个可覆盖槽位。例如，同一项目可以同时有多条不同事实。

因此核心不应默认推导 logical identity。未来 schema MAY 声明类似：

```json
{
  "revision_policy": {
    "family_key_fields": ["subject", "scope", "topic"],
    "allow_forks": false,
    "acyclic_relations": ["supersedes", "revision_of"]
  }
}
```

但该能力必须经过单独设计和版本化。第一版以显式 edge 为准，不自动创建 revision family。

### 9.7 Access policy

memdsl 可以：

- 表示和验证 access_policy；
- 在宿主提供可信 principal/roles 后做确定过滤；
- 在 View metadata 中记录应用的 policy version；
- 返回“不具备权限”而不是“没有记忆”的可控错误。

memdsl 不能：

- 自己认证调用者身份；
- 信任调用者在 tool 参数中自报 role；
- 在错误响应中泄露无权查看的 declaration id、subject、claim 或计数。

隔离/诊断的可见程度也必须经过 access filtering。

还必须区分三个概念：

| 概念 | 含义 |
| --- | --- |
| readable | 当前 principal 是否可以看到规则正文、evidence 和 source |
| applicable | 规则是否作用于当前 task/subject/scope |
| enforceable | 可信宿主是否可以在不暴露正文时执行或返回 opaque verdict |

如果一条 constraint 对 Agent 适用但正文不可读，简单排除会导致规则被绕过，直接返回正文又会泄露信息。第一版可以安全地返回 opaque `block/needs_review`，但必须把身份绑定和隐藏执行明确留给可信宿主，不能由 core 假装解决。

### 9.8 Fail-closed 与隔离区

错误按污染范围分级，而不是一律全库拒服。

#### Workspace-blocking

建议包括：

- parse error；
- schema/manifest 无法加载；
- incompatible duplicate type definition；
- compiler contract 不支持；
- duplicate full declaration id 导致 identity 歧义；
- 无法确定安全 access policy 语义。

这些错误可能让任何引用都不可信，应阻止受影响 workspace/view。

#### Family/module-blocking

建议包括：

- identity-critical revision fork；
- revision cycle；
- module import cycle（若未来规则禁止）；
- module visibility contract 无法确定。

#### Declaration-local

建议包括：

- dangling non-authority relation；
- relation type 不兼容；
- 单条声明缺少非身份字段；
- 一条 temporal declaration 的日期非法。

局部错误 SHOULD 隔离声明并继续服务其余 View。

### 9.9 读取 gate 与修复 lane 必须分离

ResolvedView 可以因 link/authority 错误拒绝或隔离读取，但 SourceWorkspace、lint 和 review/repair path 仍必须可用。否则一个 dangling target 会让用户连“补上 target”的修复 proposal 都无法提交。

现有 `ReviewStore.validate()` 故意只把 proposal 自己引入的 diagnostics 归责给 proposal，忽略 workspace 已有 diagnostics。未来 compiler gate 必须保留这个修复能力：

- read serving 使用 ResolvedView；
- lint/diagnose 使用 CompiledWorkspace 全量 diagnostics；
- propose/repair 在 parse/schema 可用时继续工作；
- approval 前重新验证 proposal 没有新增不可接受问题；
- workspace-blocking identity corruption 也必须返回明确的人工/source-edit 修复路径。

### 9.10 不允许“空结果撒谎”

如果结果为空是因为：

- 权限；
- quarantine；
- cursor stale；
- filters；
- unsupported view；
- compiler error；
- provisional-only match

响应必须使用不同 status/reason。不能把这些情况都表示成普通 `no_match`。

---

## 10. Module 与 `use` 可见性

### 10.1 目标

将当前“已解析但未执行”的 `use` 变为真正的显式可见性合同，同时保持声明式文件不依赖声明顺序。

### 10.2 不采用“必须先声明”

`.mem` 文件应被视为声明集合，而不是 C 风格逐行执行程序。因此：

- declaration 在文件中的先后 MUST NOT 决定是否可引用；
- compiler SHOULD 两遍处理：先建立符号表，再解析引用；
- 文件重排、格式化和拆分不应改变链接结果。

### 10.3 拟议可见性规则

第一版建议：

1. declaration 可以引用本 module 中定义的 symbol/declaration；
2. 可以引用通过 `use` 明确导入的 symbol/module；
3. 是否保留 legacy global visibility 由 compatibility mode 决定；
4. 未导入但全局存在的 target 在 report mode 产生 `visibility_violation`；
5. 新 workspace MAY opt in strict visibility；
6. 旧 workspace 不得在一次小版本升级中突然全部断链。

### 10.4 `use` 的目标对象

需要在 SPEC 冻结以下问题：

- `use Project.Aurora` 导入 symbol、module 还是 namespace？
- 一个 symbol 被多个 module 定义时如何消歧？
- 是否支持 `use projects.aurora.*`？第一版建议不支持通配符。
- module 名和 symbol 名冲突时如何解析？
- `use` 是否影响 relation、subject、scope、dialect，还是只影响 symbol？

在这些问题冻结前，不能把 strict visibility 设为默认。

### 10.5 迁移模式

建议三个阶段：

| 模式 | 行为 |
| --- | --- |
| legacy | workspace 全局可见，`use` 仅记录 |
| report | 全局仍可解析，但未导入引用产生 warning |
| strict | 未通过本地或 `use` 可见性解析的引用被 quarantine/error |

manifest 可在未来声明：

```json
{
  "linking": {
    "visibility": "report"
  }
}
```

---

## 11. 导航与 Map v2

### 11.1 默认行为必须从“全量条目”改为“有界目录”

新的 session-start 导航 SHOULD 默认返回 Catalog：

- source/view identity；
- module 列表或首批 module；
- 每个 module 的 declaration counts；
- active/provisional/quarantined 摘要；
- type/runtime-role 分布；
- vocabulary 摘要；
- 推荐下钻 action；
- truncation/cursor metadata。

默认 Catalog MUST 有硬预算，即使 module 数本身持续增长也不能无限输出。

### 11.2 Map v1 兼容

不能直接让 `memdsl.mcp.map.v1` 改变形状或含义。建议：

- 保留 `memory_map` v1 一段 deprecation window；
- 新增 `memory_catalog` 或让 `memory_map` 支持明确的 `mode="catalog"`，但返回新 schema；
- Python `build_memory_map()` 保持 v1；
- 新增 `build_memory_catalog()`；
- README/MCP prompt 在新版本中推荐 catalog；
- 只有 major/明确 breaking release 才考虑删除 v1。

### 11.3 建议 Catalog envelope

```json
{
  "schema_version": "memdsl.mcp.catalog.v1",
  "status": "ok",
  "view": {
    "view_id": "...",
    "source_fingerprint": "...",
    "as_of": "2026-07-14"
  },
  "summary": {
    "modules_total": 24,
    "declarations_authoritative": 860,
    "declarations_provisional": 14,
    "declarations_quarantined": 2
  },
  "modules": [
    {
      "module": "projects.aurora",
      "counts": {"assertion": 18, "constraint": 3},
      "subjects": ["Project.Aurora"],
      "summary": "..."
    }
  ],
  "truncated": true,
  "next_cursor": "...",
  "next_actions": [
    "Call memory_list with module=projects.aurora",
    "Call memory_query with the task vocabulary"
  ]
}
```

`summary` 的生成必须是确定性投影。第一版不应依赖 LLM 动态摘要；可以使用计数、显式 module metadata 和截断词汇。

当前 module 只有名称，没有 module metadata 合同。如果要显示人工语义摘要，必须另行冻结来源，例如普通 `module_metadata` declaration、manifest metadata 或新版 module syntax。实现不能临时调用 LLM 生成文本，再把它当作稳定 Catalog 内容。

### 11.4 List/down-drill

`memory_list` SHOULD 扩展：

- module；
- type/runtime role；
- subject；
- scope；
- lifecycle/authority lane；
- relation presence；
- limit；
- cursor；
- fields/representation selection。

所有 filter 必须进入 cursor identity，防止换 filter 后继续使用旧 cursor。

### 11.5 Representation selection

MCP 不应默认把同一批数据同时返回两份。新接口 SHOULD 支持：

```text
representation = structured | text
```

或只返回结构化数据，由客户端选择是否渲染。若为了兼容继续双份返回，必须有明确 budget 计算且不能让 rendered_text 绕过预算。

### 11.6 预算

每个读取接口至少需要：

- `limit`：条目数；
- `max_bytes` 或宿主等价限制；
- `truncated`；
- `next_cursor`；
- `returned_items`；
- `available_estimate` 或精确 total（只有成本可控时）。

Token 数依赖模型 tokenizer，不应成为核心唯一预算单位。宿主 MAY 在 byte/item 预算之外增加 token budget。

### 11.7 Vocabulary truncation

当前 subjects/scopes/modules 静默取前 50 项。新接口 MUST 返回：

```json
{
  "subjects": [...],
  "subjects_total": 128,
  "subjects_truncated": true
}
```

或者使用统一 page/cursor 结构。

### 11.8 Map/Catalog 不是 citation source

新 Catalog 仍然只用于发现和导航：

- 不带完整 evidence；
- 不允许 Agent 把 module summary 当作事实引用；
- next_actions 必须引导 query/explain/raw source；
- 每个条目必须能回到 declaration ids 或进一步 list。

---

## 12. Query、Search Trace 与词法召回

### 12.1 Query 目标

Query 的输出语义继续使用 EvidencePack 分层：

- MUST；
- SHOULD；
- CONTEXT；
- PROVISIONAL；
- CONFLICT；
- MISSING。

CompiledWorkspace 首先优化候选选择和引用解析，不应改变这套权威语义。

### 12.2 索引化候选选择

第一版可以按 query terms 访问词法倒排索引，减少全量扫描。必须保证：

- 评分与 0.6 行为在兼容模式下等价；
- deterministic tie-break 不变；
- candidate/provisional 不抢 active result slots；
- filter-hidden matches 仍进入 search_trace；
- global constraints 仍正确进入 MUST。

普通 scored context 可以按 limit 截断，但适用的 hard constraint/compliance evaluation 必须使用独立的 completeness 规则。若适用规则无法完整评估，系统必须返回 incomplete/needs_review，不能因为 Context budget 把规则静默丢掉。

### 12.3 Search trace 扩展

建议新增：

- `view_id`；
- `source_fingerprint`；
- `indexes_used`；
- `candidate_pool_total`；
- `candidate_pool_after_filters`；
- `quarantined_matches`（按权限裁剪）；
- `vocabulary_suggestions`；
- `retry_queries`；
- `truncated`。

不得输出内部敏感词汇或无权访问的 declaration ids。

### 12.4 Vocabulary suggest

`vocabulary_suggest` 可以先保持纯词法：

- 将 query term 与 workspace symbols/aliases/types/modules 比较；
- 返回最可能的 workspace 词汇；
- 每个建议说明来源和匹配理由；
- 不自动写入 aliases；
- 不让 candidate symbol 改变 authoritative routing。

### 12.5 不把 embedding 作为第一阶段地基

embedding MAY 作为宿主可替换 retrieval backend，但第一轮核心合同不依赖它：

- 不增加模型/provider 依赖；
- 不产生不可解释 inferred edges；
- 不让向量召回改变 EvidencePack authority lanes；
- 不把不可重建外部 index 变成 Source authority。

### 12.6 Query/Explain v2 预算

新 envelope SHOULD 允许：

- representation selection，避免结构化数据和 rendered text 默认双份；
- evidence summary 与按需 evidence expansion；
- per-item/per-evidence byte limit；
- incoming/outgoing edge pagination；
- fields selection；
- `completeness`、`truncated` 和 cursor。

旧 EvidencePack v1 和 explain v1 在兼容窗口内保持，但不能被描述为严格有界。

---

## 13. Trace 与图遍历

### 13.1 输出 BFS 生成树，不枚举所有路径

任意路径枚举可能组合爆炸。第一版 Trace SHOULD：

1. 接受一个或多个 anchor id；
2. 按确定性 BFS 遍历；
3. 每个节点第一次发现时记录 parent edge；
4. 输出一棵规范生成树；
5. 单独报告 back-edge/cycle/cross-edge；
6. 使用 depth、nodes、edges、bytes 多重预算。

底层数据模型仍应是 directed multigraph：同一 source/target 之间可以有不同 relation、evidence 和 lifecycle。BFS tree 只是一次响应/UI 投影，不能把底层关系强行压成树。

### 13.2 确定性邻接顺序

建议 key：

```text
(relation, target_id, edge_id)
```

若同时遍历 incoming/outgoing，direction 必须进入排序和输出。

### 13.3 建议参数

```text
anchors
direction = outgoing | incoming | both
relations = [...]
max_depth
max_nodes
max_edges
cursor
include_provisional
include_quarantined_metadata
```

### 13.4 Relation registry

关系类型需要声明结构属性，而不是核心散落 if/else：

```python
@dataclass(frozen=True)
class RelationDescriptor:
    name: str
    acyclic: bool = False
    symmetric: bool = False
    transitive: bool = False
    authority_effect: str = "none"
    allowed_source_roles: frozenset[str] = frozenset()
    allowed_target_roles: frozenset[str] = frozenset()
```

第一版内置关系可保持兼容，但属性冻结前不要声称：

- `supports` 一定无环；
- `related_to` 有方向；
- `revision_of` 自动替代；
- `part_of` 必然传递。

任何未注册 relation key MUST 产生稳定 diagnostic。Compiler 不得像当前 `relations()` normalization 一样把未知 key 静默丢弃，否则拼写错误会伪装成“没有关系”。

### 13.5 Trace 不是证明

Trace 只能说明：

- Source 声明了哪些边；
- 编译器派生了哪些结构边；
- 每条边来自哪里；
- 哪些边被人确认、争议或撤回（未来一等边阶段）。

它不能仅凭连通性证明自然语言结论。

编译器还能发现“坏链接”，却无法证明“该写但没写的链接”存在。一个 100% lint-clean 的 workspace 仍可能是一组孤岛。因此 graph orphan ratio、link coverage 和 trace usefulness 是产品/质量指标，不是 compiler correctness 的自然结果。

---

## 14. 一等关系边

### 14.1 当前 relation map 的限制

当前：

```mem
relations {
  supports: memory.b
}
```

只能表达“声明 A 写了一个 supports target”。它不能给这条边独立添加 evidence/lifecycle/reviewer。

### 14.2 分两阶段实施

#### 阶段 A：派生 `CompiledEdge`

- 不改语法；
- 每个 relation item 生成稳定 edge id；
- provenance 指向 source declaration/file/line；
- 建 incoming/outgoing index；
- 支持 trace、cycle 和 dangling diagnostics；
- edge authority 仍继承 source declaration 的显式关系声明，不增加独立审核状态。

#### 阶段 B：可审核的一等 edge source

在真实使用证明有需要后，再选择：

- 新的通用 link declaration；或
- 版本化 richer relation syntax；或
- workspace-defined relation assertion type。

不得在没有迁移和 parser/spec 设计的情况下直接改变现有 `relations` map 的值类型。

一等 edge 不应为了实现方便直接增加第六种 runtime role；现有 role 集合是稳定关闭合同。更兼容的选择是普通 declaration + `relation_edge` capability，或仅存在于 compiler 的独立 edge object，具体方案需单独冻结。

### 14.3 一等 edge 最小字段

如果进入阶段 B，合同至少需要：

```text
id
source
relation
target
claim/meaning（可选，但若 relation 名不足以解释则必需）
evidence
lifecycle
confidence
access_policy
review provenance
```

### 14.4 Edge review

- 新 edge 默认 candidate；
- inferred edge 必须标记 provenance；
- 人工确认产生新的 active revision，不能原地覆盖 candidate；
- disputed/retracted edge 保留审计历史；
- relation 的 authority effect 只有 active、结构有效且可见的 edge 才能产生。

### 14.5 最大风险

一等 edge 会显著增加写入成本和 schema 复杂度。若没有真实 trace/审核需求，不应为了“看起来像知识图谱”提前实现。

---

## 15. Workspace Dialect

### 15.1 设计原则

Dialect MUST：

- 属于 workspace Source；
- 可版本化；
- 可 review；
- 可通过 `use` 或等价 manifest 显式引入；
- 不把具体用户方言内容、私有分类或个人映射硬编码进 memdsl Python 核心；核心 MAY 提供通用 dialect compiler/capability；
- 不因一次模型猜测直接获得 active authority。

### 15.2 现有基础

现有 symbol declaration 的 `canonical_name` 和 `aliases` 已能表达简单同义词。第一阶段应复用它，而不是立即发明复杂方言语言。

### 15.3 平面 aliases 不够的情况

未来扩展 MAY 需要表达：

- phrase -> subject；
- phrase -> intent/type/module；
- scope-specific mapping；
- negative mapping；
- disambiguation；
- examples；
- observed count；
- last confirmed；
- provenance；
- confidence/lifecycle。

这些字段应通过通用 domain schema 扩展，而不是加入固定个人分类枚举。

### 15.4 学习闭环

宿主可以观察：

```text
no-match("那个小生意")
    -> vocabulary suggestion / retry
    -> hit(Project.Aurora)
    -> 形成 dialect candidate
    -> memory_propose
    -> human review
    -> active alias/mapping
```

核心只需要提供：

- 可序列化 search trace；
- candidate declaration 验证；
- proposal/review lane；
- dialect type/schema 的通用表达能力。

核心不应保存隐式“用户模型”或自动从遥测写入 Source。

原始 query/retry telemetry 可能包含高度私密的健康、关系、身份和生活信息，因此宿主 SHOULD：

- 默认不持久化原始查询日志；
- 学习功能显式 opt-in；
- 优先本地处理；
- 有保留期和删除能力；
- 写入 Source 的是提炼后的候选映射，不是完整聊天原文；
- 公开测试只使用虚构 phrase 和身份。

### 15.5 方言污染风险

必须防止：

- 单次误重试学习错误 alias；
- candidate alias 提前改变 authoritative routing；
- 恶意输入注入高权重词汇；
- 同一 phrase 映射多个 symbol 后静默随机选择；
- 私有 phrase 出现在无权查看的 vocabulary 响应。

所以 active alias 仍需人工确认；ambiguous alias 必须显式报告。

---

## 16. 健康度、陈旧性与“收敛”

### 16.1 不设固定 Memory 上限

本设计不规定：

- workspace 最多只能有多少声明；
- 超过 50 条必须摘要；
- 半年前的记忆必须归档；
- 未被引用的声明自动删除。

当前 `module_too_large` 可以继续作为阅读和组织 warning，但不能被解释为全库硬上限。

### 16.2 健康度信号

编译器或辅助分析 MAY 报告：

- exact duplicate；
- near duplicate candidate；
- contradictory active declarations；
- revision fork；
- dangling relation；
- isolated declaration；
- stale temporal declaration；
- never-confirmed candidate；
- frequently contradicted memory；
- module navigation overload。

其中自然语言 near duplicate/contradiction 不能被核心纯结构编译器冒充确定事实。若使用模型或 embedding，必须标记 inferred，并只产生 review candidate/diagnostic。

### 16.3 Semantic refactoring

可选流程：

```text
健康信号 -> 宿主生成重构候选 -> 人工审核
       -> 新 declaration/edge proposal
       -> approve 后显式 supersede/revision
```

重构错误仍可通过新 revision 修正，旧 Source 和 audit 保留。

### 16.4 陈旧内容

时间只能触发注意力，不自动证明内容错误：

- `valid_until` 到期可确定地影响 View；
- `as_of` 过旧只能产生 staleness warning；
- “最近被使用”不能自动刷新真实性；
- 使用事件、用户纠正、外部 evidence 变化可作为 review signal；
- 人工确认可以产生新 revision 或确认事件，但不能静默改旧 declaration。

### 16.5 统一策展收件箱属于宿主能力

陈旧提醒、dialect candidate、edge confirmation、refactoring proposal、contradiction alert 都会竞争人的注意力。宿主 SHOULD 可以把它们汇入一个排序后的策展队列。

memdsl 核心应提供通用 proposal/diagnostic/review metadata，但不应内置某个产品的收件箱 UI、排序模型或每日工作流。

### 16.6 物理冷历史

当前 superseded declaration 仍需留在被加载 workspace 中，relation target 才能通过 lint。因此，“把旧段落移出热路径”不是单纯移动文件：

- compiler 仍需解析或索引历史 id；
- explain/trace 可能需要访问旧节点；
- revision target 不能变成 dangling；
- raw source resource 需要能定位冷历史；
- package/privacy 边界必须明确。

只有在定义版本化 object/cold-history contract 后，才可以把历史物理分层。该工作不属于第一轮导航改造。

物理归档前后的相同 ViewContext SHOULD 产生语义等价的 ResolvedView；若某些 history-only nodes 只在显式 history mode 可见，也必须由版本化合同说明，而不能因文件被移动就偶然断链。

---

## 17. 读取与写入如何连接

### 17.1 写入应从锚点现场发生

为了降低关系和 subject 的填写成本，宿主 SHOULD 允许从 query/trace/explain 现场发起 proposal：

- 预填 subject；
- 预填 module/scope；
- 预填显式 relation anchors；
- 记录触发 query/trace 的 source fingerprint；
- 记录建议 reason；
- 仍由用户确认 source 文本。

但 `module` 和 `use` 当前是 document-level syntax，不是 declaration field。`memory_propose` 又只保证 proposal 中恰好有一条 declaration，并在批准时把 source 原样追加到目标文件。不能把“预填 module/use”简单写入 proposal source：它可能改变目标文档中其他 declaration 的 module 归属。

安全选择包括：

- 由 reviewer 选择已知 target file/module；
- 通过宿主可信 metadata 传递 anchor/module，但不让 proposal 文本自报 authority；
- 设计单独的 governed source-edit lane；
- 若扩展 MCP propose input，使用新 schema（例如 propose v3）并保持现有 source/reason v2 兼容。

### 17.2 预填不是批准

- 预填字段仍是不可信 proposal 内容；
- 模型或宿主建议的 relation 不获得 authority；
- evidence verification 仍来自宿主可信上下文；
- 现有 policy hard floor 继续适用；
- destructive relations 如 supersedes/revision_of/conflicts_with 继续进入人工审核。

### 17.3 防止 stale-anchor 写入

proposal metadata SHOULD 记录起草时的 `source_fingerprint/view_id`。提交或批准前：

- workspace 已变化时重新编译；
- target 已被替代/隔离时提示 reviewer；
- 不得因旧 trace 中存在一个 id 就假定当前仍可见；
- approval 必须重新 lint/link proposed declaration against live Source。

---

## 18. Python、CLI 与 MCP 契约

### 18.1 Python API 演进

建议新增但不立即删除旧 API：

```python
compiled = compile_workspace(paths)
# 也必须支持测试、嵌入式宿主和 parse_text 场景：
compiled_in_memory = compile_workspace(workspace)
view = resolve_view(compiled, context)
catalog = build_memory_catalog(view, ...)
pack = build_evidence_pack(view, query, ...)
trace = trace_memory(view, anchors, ...)
```

兼容路径：

```python
workspace = Workspace.load(paths)
pack = build_evidence_pack(workspace, query)
```

旧函数内部 MAY 临时编译 Workspace，但必须避免每个函数重复构建索引。公共迁移文档应推荐显式复用 CompiledWorkspace/ResolvedView。

当前公共 API 大量支持 `Workspace()` + `parse_text()` 构造的纯内存对象，所以 path-only compiler 不能成为唯一入口。无文件 Workspace 也必须有确定 fingerprint；可以基于规范化 declaration/schema 内容，而不能要求伪造本地路径。

### 18.2 是否让 `Workspace` 继承编译能力

不建议把所有 index/view 状态继续塞进现有 `Workspace`：

- Workspace 当前是简单 Source model；
- 编译 diagnostics/cache/context 会让生命周期混乱；
- 同一个 CompiledWorkspace 可以产生多个 ResolvedView；
- 分离类型更能保持 Source 与 projection 边界。

### 18.3 CLI

建议新增：

```console
memdsl compile PATH... --json
memdsl catalog PATH... [--module ...] [--limit ...] [--cursor ...]
memdsl trace PATH... ID [--incoming|--outgoing|--both] [--depth N]
```

现有命令：

- `memdsl map` 保持 v1 或增加明确 deprecation 提示；
- `memdsl query` 保持结果层语义；
- `memdsl explain` 改用 incoming index，但文本默认兼容；
- `memdsl lint` 可增加 compiler/link diagnostics；
- `memdsl review` 继续作为权威写入路径。

是否公开 `compile` 命令需要真实用户需求验证。内部 compiler 不一定必须对应 CLI。

### 18.4 MCP 新工具

建议最小新增：

- `memory_catalog`；
- `memory_trace`；
- `memory_vocabulary_suggest`（可合并到 query no-match）；
- 可选 `memory_compile_status`。

不建议一次发布过多工具。工具描述本身会增加 Agent 选择成本。可以优先发布 catalog + trace，并把 vocabulary suggestion 合入 query。

建议 scope：

| 能力 | 建议 scope |
| --- | --- |
| catalog / compile summary | `read:summary` |
| trace / vocabulary suggest | `read:search` |
| 完整 diagnostics/quarantine/history | 评估新增非默认 `read:diagnostics` / `read:history` |

principal/role 仍由宿主可信上下文提供，不能作为普通 tool 参数自报。

底层原语之外，真实评估若证明中位客户端无法稳定完成：

```text
catalog -> query -> retry -> trace -> explain
```

则 SHOULD 考虑提供一个安全的一调用 facade，例如：

```text
memory_context(task, budget, subject?, scope?)
```

它由服务内部完成 View resolution、检索、必要的显式图扩散、constraint completeness 检查和预算裁剪，同时仍返回 selection reasons/search trace。Facade 不能隐藏 incomplete/quarantine，也不能替代专家级原语。

### 18.5 MCP schema version

新增 envelope 使用新 schema id：

```text
memdsl.mcp.catalog.v1
memdsl.mcp.trace.v1
memdsl.mcp.compile_status.v1
```

若改变现有 map/query/explain 字段的含义，必须 bump 对应 schema version；不能只因为字段“看起来兼容”就复用 v1。

### 18.6 通用 View envelope

新读取响应 SHOULD 统一携带：

```json
{
  "schema_version": "...",
  "status": "ok",
  "view": {
    "view_id": "...",
    "source_fingerprint": "...",
    "as_of": "...",
    "enforcement_mode": "report"
  },
  "diagnostic_summary": {
    "blocking": 0,
    "quarantined": 2,
    "warnings": 5
  },
  "truncated": false,
  "next_cursor": null
}
```

旧客户端不知道这些字段时应能忽略；但 authority 语义改变时仍必须使用新 schema。

### 18.7 MCP prompt/description

当前 prompt 要求 session start 调用全量 `memory_map`。迁移后应改为：

1. 读取有界 catalog；
2. 用 task nouns 查询；
3. no-match 时读取 search trace/vocabulary suggestions；
4. 用 trace/explain 下钻；
5. 引用前读取 evidence/source；
6. consequential draft 调用 memory_check。

旧 `memory_map` 在兼容期不能同时被描述为“必须常驻”与“已弃用”。prompt 必须根据 server capability/version 生成一致建议。

---

## 19. 实施阶段与每阶段变更合同

实现顺序遵循一个原则：

> 语义先在 SPEC 冻结；代码先落内部索引；读取能力渐进增加；执法和 breaking behavior 最后收紧。

### 19.1 暂定版本映射（未冻结）

为了避免一次 release 同时承担内部重构和 authority breaking change，建议：

| 版本 | 建议范围 |
| --- | --- |
| 0.6.x | 文档、测试、明确 correctness/security fix；不引入新的默认 View 语义 |
| 0.7.0 | CompiledWorkspace 内部重构、indexed parity、新 Catalog/Trace/Suggest、report-only diagnostics；保留全部 v1 surface |
| 0.8.0 | `memdsl.workspace.v2`、ResolvedView、strict use/link/quarantine、EvidencePack/MCP v2 opt-in |
| 0.9+/条件 | 一等 edge、rich dialect、cold history/incremental compiler |

Map v1 建议至少保留两个 minor release 的 deprecation window，并且不早于 1.0 再评估删除。这个表是实施建议，不是已经承诺的 release roadmap；owner 决策后才能进入公开路线图。

### Phase -1：冻结语义与基准

#### 改什么

- 在本设计文档中完成术语、View 分类、fork/cycle/quarantine 的决策；
- 增加合成 fixtures 和 characterization tests；
- 建立当前 map/query/explain 的 payload snapshots；
- 建立规模基准脚本，但不提交任何真实 workspace；
- 记录 v0.6 输出、时间和内存基线。

#### 为什么

没有 characterization，内部重构很容易把 authority lane、candidate 隔离或 deterministic ordering 改坏。

#### 可能问题

- 把当前 bug 固化成永久合同；
- fixture 太小，无法暴露分叉、环、分页和规模问题；
- Windows/POSIX 路径造成 snapshot 漂移。

#### 防护

- 明确区分“兼容行为”和“已知缺陷”；
- path 规范化；
- synthetic-only fixtures；
- snapshot 之外保留语义断言。

#### 退出条件

- fork/cycle/dangling/duplicate/access/as_of/candidate fixtures 齐全；
- 现有示例 CLI/MCP 行为有可重复基线；
- SPEC open questions 有 owner 决策或明确延期。

#### 回滚

仅文档和测试，无运行时变化；可以单独回滚新增 characterization，但不应删除已确认的缺陷样例。

#### 2026-07-14 实际固化结果

本次 Phase -1 没有修改 `src/memdsl/`，也没有实现任何未来读取 API。它把
0.6.0 当前行为、已知缺陷和后续目标不变量分开记录：

1. `Workspace.active()` 的冻结术语是 **serviceable/non-excluded**；它不是
   `status == active` 的权威集合。
2. **authoritative** 在 0.6 公共契约中仍只表示 lifecycle `active` 能进入
   MUST/SHOULD/CONTEXT/MISSING、alias routing 和 compliance。candidate、
   retracted、archived 发起的 authority-changing relation 属于已知缺陷，
   不属于 indexed parity 必须保留的兼容行为。
3. “0.6 current set” 不是一个已经存在的统一公共对象。Map/query/compliance、
   list/status/vocabulary 当前各自计算集合；测试只能记录这种分裂，不能把任一
   surface 偶然选为未来 ResolvedView 的定义。
4. fork 的最小冻结语义是：不得自动选 winner；report mode 中两个结构有效、
   active successor 都保持可见并伴随显式诊断。quarantine/strict 的精确污染
   范围继续留在开放问题。
5. supersedes cycle 的最小冻结语义是：cycle edge 不产生排除 authority，
   参与节点不得无提示全部消失，并且必须 fail loud。未来使用何种 diagnostic
   code、是否 quarantine 整个 family 仍由 Phase 1 冻结。
6. workspace v2 冻结为**每个 source file 最多一个 `module` statement**。
   0.6/v1 的“最后一个 module 覆盖整份文件”只作为 characterization 保留；
   report-only diagnostic、迁移期和 strict enforcement 时点仍需后续决定。
7. read gate 与 repair lane 的不变量冻结为：读取拒服不能同时堵死修复入口。
   当前 lint error 不阻断 read，也允许 proposal 修复 pre-existing diagnostic；
   当前 parse/schema error 同时阻断 MCP read/propose，是已记录的现有限制，
   不是未来 repair contract。
8. `valid_until` 和 `access_policy` 在 0.6 中仍只被表示/诊断/传输，不改变
   serving。Phase -1 不通过测试替未来 `as_of`、principal 或 opaque enforcement
   选择 API 形状。

证据落在：

- `tests/fixtures/phase_minus_one/`：小型、虚构、可公开的反例；
- `tests/snapshots/phase_minus_one/`：当前 MCP Map/query/explain v1 payload；
- `tests/test_phase_minus_one_characterization.py`：当前行为断言与 strict xfail；
- `benchmarks/phase_minus_one_baseline.py`：不读取真实 workspace 的规模生成器；
- `docs/baselines/phase_minus_one_0.6.0.json`：五次原始样本；
- `docs/baselines/PHASE_MINUS_ONE_SCALE_BASELINE.md`：复现方法、结果和解释。

strict xfail 只冻结“不变量必须转正”，不冻结尚未决定的 diagnostic code、
错误 envelope、budget 字段名或 cursor 形状。Phase 0A 必须转正非 active
superseder、global constraint bypass 和跨 surface current-set 三组；Phase 1/2
再按对应阶段转正 graph/link/identity/vocabulary 项。

### Phase 0A：修复 authority invariant

#### 改什么

- 增加 candidate/retracted/archived source edge 不得产生 supersede authority 的回归测试；
- 统一 Map、query、compliance 对 supersedes source authority 的判断；
- 至少要求发起 supersedes 的 declaration 为 active、serviceable、target 唯一解析且 edge 结构有效；
- 明确 normal append-only revision 不要求原地改旧节点 status；
- 更新 `unmarked_supersede_status` 的语义、严重级别或废弃计划；
- 在 UPGRADING/release notes 记录这是 correctness/security fix。

#### 为什么

当前 candidate relation 可以让 active constraint 从 compliance 中消失，使 BLOCK 变 ALLOW。这直接违反 PROVISIONAL 不具有 authority 的既有公开边界，不能延期到 quarantine 全面落地后再修。

#### 可能问题

- 某些 workspace 可能曾依赖 candidate supersedes 的非预期行为；
- 只检查 `status == active` 仍未解决 cycle/fork/visibility；
- Map/query/compliance/list/status 可能继续使用不同 current-set 逻辑。

#### 防护

- 把 supersede effect 集中到单一 resolver/helper；
- full id/bare ref 统一解析；
- 增加跨读取面的 current-view consistency tests；
- 将该修复作为 Phase 0B compiler authority resolver 的最小前身。

#### 退出条件

- candidate/retracted/archived supersedes 均不能抑制 active authority；
- active valid supersedes 继续保持兼容；
- compliance hard rule 不会被非权威 edge 绕过；
- Map/query/compliance 对同一 target 的排除原因一致；
- 公共变更说明完成。

#### 回滚

安全边界修复不应默认回滚。若兼容影响超出预期，应提供短期 legacy flag，但默认仍必须保持非权威 edge 无 authority。

#### 2026-07-14 实际完成结果

Phase 0A 以一个窄的内部 helper 完成，没有创建 CompiledWorkspace、ResolvedView、
revision family 或新公开 envelope：

1. `src/memdsl/authority.py` 集中提供 exact full-id / unique bare-ref 解析、
   authoritative superseded id 计算和共享 current declaration 集合。
2. Map、query、MUST、compliance、benchmark flat-context、默认 list、status authority
   counts 和 vocabulary 都使用同一集合。
3. candidate、retracted、archived superseder 的 3 个 strict xfail 实例，以及
   global constraint bypass 和 current-set consistency 各 1 个 strict xfail，已转成
   普通回归测试；Phase -1 的 10 个 xfail 实例现剩 5 个后续阶段 xfail。
4. active、结构可识别、唯一解析的 full-id/bare-ref supersedes 保持 append-only
   revision 兼容；ambiguous、duplicate、dangling 和 wrong-prefix target 不产生
   authority effect，但完整 diagnostics 仍留给 Phase 0B/1。
5. `unmarked_supersede_status` 不再发出；旧 declaration 不需要原地改写 status。
6. proposal/review/audit 没有改变；pending proposal 仍不进入 durable read path。

### Phase 0B：内部 CompiledWorkspace

#### 改什么

- 新增 `compiler.py` 或等价模块；
- 构建 identity/module/type/subject/scope/alias/edge indexes；
- `MemdslMCPService.workspace()` 或等价加载层缓存 compiled result；
- `by_id`、explain incoming refs 改走 index；
- query/list/map 可逐步接受 compiled input；
- 除 Phase 0A 已明确的 authority defect fix 外，保持所有外部 schema 和默认结果不变。

#### 为什么

这是后续所有功能的共享地基，也是最低风险、立即减少重复扫描的改动。

#### 可能问题

- cache invalidation 错误导致服务陈旧记忆；
- index 和 declaration list 不一致；
- bare name/complete id 兼容差异；
- order 改变导致测试和客户端行为漂移；
- compile 一次占用更多内存。

#### 防护

- parity/property tests；
- 每个 index 可从 declarations 独立重算并校验；
- source fingerprint；
- deterministic sorting；
- debug mode 可比较 indexed 与 legacy result。

#### 退出条件

- 全套现有测试通过；
- explain incoming refs 不再全量扫描；
- query/map payload 除 Phase 0A 安全修复外与 v0.6 characterization 等价；
- cache reload 在 mtime/size/content 变化下正确；
- no new public API commitment unless documented。

#### 回滚

保留 legacy path feature flag；若 indexed parity 失败，可退回旧扫描，不改 Source。

#### 2026-07-14 实际完成结果

Phase 0B 已以内部分层落地，没有从包根导出新类型，也没有创建 ResolvedView、
Catalog、Trace、workspace v2 或新的 MCP/CLI schema：

1. `src/memdsl/compiler.py` 新增内部 `CompiledWorkspace`，保留完整 declaration
   occurrences，并建立 full-id/name、module、type、runtime role、lifecycle status、
   subject、scope、alias、outgoing 和 incoming indexes。所有 mapping value 使用稳定
   key 冻结为 tuple；duplicate full id 不进入 `resolved_by_id`，不会被单值 dict 覆盖。
2. compiler resolver 对 full id 只做 exact match，对 bare name 只在唯一 occurrence 时
   解析，错误 kind prefix 不回退到 suffix。v0.6 `by_id`/explain 的首 occurrence 行为
   通过独立 compatibility index 保留，因此 duplicate-id serving gate 和完整 reference
   diagnostics 仍未提前进入 Phase 1 enforcement。
3. 每个已识别 relation occurrence 编译为稳定 `CompiledEdge`。resolved outgoing edge
   与 target incoming index 一一对应；MCP/Python explain 的 `referenced_by` 改用预建的
   v0.6 compatibility incoming index，不再在每次请求中扫描全部 declarations/relations。
4. `Workspace.load(paths)` 规范化 path 输入并排序目录遍历；纯内存
   `Workspace()` + `parse_text()` 也能编译，并基于规范 declaration/type 内容产生稳定
   fingerprint。path-backed fingerprint 复用现有 content-based
   `workspace_fingerprint()`，再绑定 compiler contract version。
5. `MemdslMCPService` 缓存 Workspace 与 CompiledWorkspace。reload signature 同时覆盖
   path/membership、mtime、size 和 content hash，并跟踪 manifest/schema，因此同 size +
   同 mtime 内容变化、文件新增/删除/改名、manifest retarget 和 schema 内容变化都不会
   继续服务旧 compile。
6. query/map/list/explain/compliance/status/types/lint 读取层复用同一 compiled result；
   旧 Python Workspace 输入仍可用，v0.6 JSON/text/schema/sorting/exit code 和默认结果由
   Phase -1 snapshots、Workspace-vs-Compiled differential tests 与全套回归保持。
7. Phase 0A authority invariant 保持：candidate/retracted/archived superseder 无 authority，
   pending proposal 仍不进入 durable read path，proposal/review/audit 行为未改变。
8. 新增 13 个 compiler/cache/parity/property tests；全套结果为 `236 passed, 5 xfailed`。
   保留的 strict xfail 是 fork、cycle、完整 reference diagnostics、duplicate-ID serving
   gate 和 vocabulary budget，分别等待 Phase 1/2。

本阶段没有改变公共合同，因此没有修改 SPEC、PUBLIC_API、UPGRADING、README，也没有
把内部 `CompiledWorkspace` 描述为已稳定公开 API。

### Phase 1：编译 diagnostics 与 report-only View

#### 改什么

- 检测 supersedes/revision cycle；
- 检测 fork、dangling、ambiguous targets；
- 建立 `ViewContext/ResolvedView` 内部类型；
- 首先使用 `enforcement_mode=report`；
- MCP status/lint 可暴露 diagnostic summary；
- 不改变默认 query/map serving。

#### 为什么

在改变服务语义前，需要用真实、公开合成 workspace 验证错误分布和污染范围。

#### 可能问题

- 新 diagnostics 噪声太高；
- relation 语义不清导致误报；
- 用户把 warning 当 error；
- diagnostics 泄露无权访问的 id。

#### 防护

- severity 和 enforcement 分离；
- relation registry 明确属性；
- access-aware rendering；
- diagnostic codes 稳定、message 可变；
- report-only 不阻断服务。

#### 退出条件

- synthetic fork/cycle 结果确定；
- false-positive review 完成；
- diagnostic codes 进入 SPEC；
- 不改变 v1 query/map authority 输出。

#### 回滚

关闭 report feature，不影响旧服务结果。

### Phase 2：Catalog、分页与预算

#### 改什么

- 新增 `build_memory_catalog`；
- 新增 CLI/MCP catalog surface；
- module/type/subject/status filters；
- limit/max_bytes/cursor；
- truncation metadata；
- representation selection；
- MCP prompt 推荐 catalog，而 v1 map 保持兼容。

#### 为什么

这是直接解决 Context 线性膨胀的阶段，使 session-start 输出与总声明数解耦。

#### 可能问题

- module 数量本身也无界；
- cursor 在 Source 变化时重复/遗漏；
- summary 太少导致 Agent 不知道下钻哪里；
- 新旧 prompt/工具同时存在让 Agent 选择混乱；
- total count 计算抵消分页性能收益。

#### 防护

- catalog 自身硬预算；
- cursor 绑定 view_id/filter/order；
- cursor stale 明确失败；
- summary 使用确定计数和显式 metadata；
- MCP capability-driven prompt；
- total 可为 estimate/omitted。

#### 退出条件

- 规模 fixture 中默认 catalog 输出保持预算内；
- 每页无重复、无遗漏；
- Source 变化使旧 cursor 可靠失效；
- v1 map 测试继续通过；
- no-match -> catalog/list/query 的导航 eval 可走通。

#### 回滚

新工具可从 prompt 暂时撤回，旧 map 继续服务；Source 无迁移。

### Phase 3：Indexed Query、Vocabulary Suggest 与 Trace

#### 改什么

- 词法倒排候选 index；
- search_trace 扩展；
- vocabulary suggestions；
- incoming/outgoing BFS trace；
- cycle/back-edge 显式输出；
- trace budgets/cursors。

#### 为什么

使 Agent 能从目录进入局部声明，再沿显式关系扩散，而不是依赖一次相似度猜测。

#### 可能问题

- 新索引改变召回排序；
- trace 图分支爆炸；
- relation 过滤错误隐藏关键边；
- Agent 把 trace 当证明；
- vocabulary suggestion 暴露私有术语。

#### 防护

- compatibility scorer；
- BFS tree + multi-budget；
- deterministic adjacency；
- provenance/boundary 文案；
- access filtering；
- query differential tests。

#### 退出条件

- 既有 EvidencePack 层语义不变；
- indexed/legacy query 在兼容 fixture 等价；
- trace cycle、depth、cursor、direction 测试齐全；
- tool descriptions 不夸大真实性。

#### 回滚

query 可切回 legacy scorer；trace 是新增 surface，可独立关闭。

### Phase 4：`use` 可见性与 Dialect

#### 改什么

- Workspace/CompiledWorkspace 保留 Document uses；
- 定义 use target 和 two-pass linking；
- legacy/report/strict visibility；
- 提供 user-owned dialect schema 示例；
- no-match -> dialect candidate 的通用 proposal 示例；
- ambiguous/negative mapping diagnostics。

#### 为什么

显式可见性比声明顺序约束更适合声明式语言；方言可以提高个人长尾召回而不污染核心代码。

#### 可能问题

- 旧 workspace 大量未写 use；
- module/symbol namespace 冲突；
- 方言错误映射改变检索；
- 方言 schema 变成私有产品模板；
- strict mode 产生迁移负担。

#### 防护

- report-first；
- migration linter/suggested use，不自动改 Source；
- active alias 必须 review；
- generic fictional examples；
- strict opt-in，breaking release 再评估默认。

#### 退出条件

- use 语义进入 grammar/SPEC；
- legacy workspace 不改文件仍可运行；
- strict fixture 能捕获越界引用；
- dialect candidate 不影响 active alias routing。

#### 回滚

切回 legacy visibility；dialect declarations 仍只是普通 Source，不丢数据。

### Phase 5：Quarantine enforcement

#### 改什么

- 启用 declaration/family/workspace 污染分级；
- 新 View envelope 暴露 quarantined/excluded；
- query/catalog/trace 只在授权下显示 quarantine metadata；
- identity-critical 错误 fail closed；
- 提供 opt-in enforcement，观察后再决定默认。

#### 为什么

读取路径不能永远咨询式 lint；但整库 fail-closed 会产生过大失忆爆炸半径。

#### 可能问题

- 隔离过严造成记忆缺失；
- 隔离过松让坏边继续影响 authority；
- 空结果被误解为没有记忆；
- 客户端忽略 quarantine 字段；
- 新语义破坏 v1 envelope。

#### 防护

- 新 schema；
- explicit status/reason；
- report shadow 数据；
- per-diagnostic enforcement table；
- compatibility mode；
- agent prompt 和 PUBLIC_API 同步。

#### 退出条件

- 每种错误有污染范围测试；
- v1 clients 仍可使用 legacy mode；
- empty/no-match/quarantined/unauthorized 明确区分；
-真实公开合成规模下无不可接受误隔离。

#### 回滚

退回 report mode；Source 和 diagnostics 保留，不需要逆向迁移。

### Phase 6：一等 Edge（条件阶段）

#### 触发条件

只有以下证据同时成立才进入：

- trace/graph 被真实使用；
- 用户需要单独确认或反驳边；
- relation-field provenance 不足；
- review 队列能承受额外写入成本。

#### 改什么

- 选择并冻结 explicit edge source contract；
- edge lifecycle/evidence/review；
- parser/schema/public API/MCP 支持；
- migration from derived edges；
- graph-specific review reporting。

#### 为什么

只有一等边才能让“A 是否真的支持 B”成为可单独审核的对象。

#### 可能问题

- 语言和写入复杂度激增；
- 节点和边产生双重历史；
- old relations 与 new edge 重复；
- 宿主不愿填写 edge evidence；
- memdsl 被误解为通用图数据库。

#### 防护

- derived edge 与 explicit edge 明确 precedence；
- 不物理改写旧 relations；
- migration diagnostics；
- core 保持存储中立；
- 先在 domain schema 验证，再考虑 core syntax。

#### 回滚

explicit edge 仍是普通 Source declaration 时可以继续保留；运行时可退回只索引 legacy relations。

### Phase 7：冷历史/增量编译（条件阶段）

#### 触发条件

- 全量 parse/index 已被基准证明是实际瓶颈；
- Source/semantic history 达到可重复的规模阈值；
- catalog/query Context 已经有界，确认问题来自存储计算而非输出。

#### 改什么

- content-addressed source objects 或版本化 cold-history index；
- incremental compiler；
- stable historical id resolution；
- cold source resource；
- cache/package/privacy contract。

#### 为什么

让历史增长不再要求每次重新解析全部旧声明，同时保留 explain/trace/audit 可达性。

#### 可能问题

- Source 与 cache/object store 分叉；
- 冷历史丢失使 revision target dangling；
- 跨平台 path/content hash 差异；
- 发布包意外包含真实 history；
- 引入数据库式运维复杂度。

#### 防护

- Source/objects 可重建或可校验；
- content hash 和 fsck；
- 明确 archive/export/import；
- artifact privacy scan；
- 保持纯文件 fallback。

#### 回滚

只要热 Source 保持规范权威，可删除 cache 并全量重建；若历史只存在 cold store，则必须先提供安全导出，不得直接回滚删除。

---

## 20. 兼容与迁移策略

### 20.1 Workspace 文件

- 早期 Phase 0A-3 不要求用户修改 `.mem`；
- `use` strict 之前必须提供 report/migration diagnostics；
- 一等 edge 不得强迫现有 relations 立即重写；
- historical/cold storage 必须有显式 opt-in/export。

### 20.2 Python API

- `Workspace`、`build_evidence_pack`、`build_memory_map` 保持兼容窗口；
- 新类型先在模块路径暴露，稳定后再从包根导出；
- deprecation warning 必须给替代代码；
- 不在小版本中更改返回 dict 的已有字段含义。

### 20.3 CLI

- 现有命令和 exit code 保持；
- 新 diagnostics 默认 report 时不改变 query/map exit code；
- strict compile/lint 可使用新 flag/command；
- breaking default 必须进入 UPGRADING。

### 20.4 MCP

- 新工具用新 schema；
- 旧工具在 deprecation window 内保留；
- server prompt 根据已注册工具生成；
- scope 要求不能意外扩大；
- 声明级 access filtering 与 MCP capability scope 分开说明。

### 20.5 Schema/manifest

- relation registry、visibility mode、revision policy 都需要 versioned manifest/schema 字段；
- 未知版本继续 fail closed；
- 缺省字段保持 legacy 行为；
- strict 行为只在显式 opt-in 或 breaking release 启用。

规范性 visibility/revision/quarantine 语义不应只作为 `memdsl.workspace.v1` 的未知可选字段加入。0.6 runtime 对未知 manifest 字段可能继续按旧语义服务，造成新 workspace 被旧 runtime 错误读取。建议：

- 纯索引/cache hint 可以留在实现内部；
- 改变 authority/visibility 的 workspace 必须声明 `memdsl.workspace.v2` 或等价新版本；
- 旧 runtime 看到 v2 时 fail closed；
- v2 migration tool/report 说明旧 workspace 如何 opt in；
- `evidence_pack`、MCP query/check/map 若 authority 语义改变，也使用新 envelope version。

### 20.6 Envelope versioning

原则：

- 新增不改变旧含义的可选字段 MAY 保持 schema id；
- authority、visibility、pagination、status 语义改变 MUST bump schema；
- `map.v1` 不能被原地变成 catalog；
- cursor token 格式是 opaque，不承诺客户端解析；
- cursor contract version 必须进入 token 或 server-side state identity。

建议矩阵：

| Surface | 兼容合同 | 新语义合同 |
| --- | --- | --- |
| Workspace manifest | `memdsl.workspace.v1` | `memdsl.workspace.v2` |
| Python navigation | `build_memory_map()` | `build_memory_catalog()` |
| CLI navigation | `memdsl.map.v1` | `memdsl.catalog.v1` |
| MCP navigation | `memdsl.mcp.map.v1` / `memdsl://map` | `memdsl.mcp.catalog.v1` / 可选 `memdsl://catalog` |
| EvidencePack | `memdsl.evidence_pack.v1` | `memdsl.evidence_pack.v2`（authority/View 改变时） |
| MCP query | `memdsl.mcp.query.v1` | `memdsl.mcp.query.v2` |
| MCP list | `memdsl.mcp.list.v1` | `memdsl.mcp.list.v2`（canonical page/View filtering） |
| MCP explain | v1 indexed parity | v2（edge/quarantine/budget 语义改变时） |
| MCP lint | v1 report-compatible | v2（severity/ok 含义改变时） |
| MCP propose | `memdsl.mcp.propose.v2` | v3（anchor/view/module trusted metadata） |
| MCP trace | 无 | `memdsl.mcp.trace.v1` |
| ResolvedView | 无 | `memdsl.resolved_view.v1` |

---

## 21. 风险登记表

| ID | 风险 | 概率 | 影响 | 主要防护 | 停止/降级条件 |
| --- | --- | --- | --- | --- | --- |
| R1 | 把“编译通过”误当“内容真实” | 中 | 高 | boundary、provenance、人审 | 文档/工具开始使用 verified truth 等错误措辞 |
| R2 | currentness 规则过严，抹平合法多元记忆 | 中 | 高 | explicit-only、fork report、schema opt-in | 大量合法声明被 quarantine |
| R3 | currentness 规则过松，ResolvedView 仍无意义 | 中 | 高 | fork/cycle/conflict diagnostics | 同一 revision family 长期多头且无提示 |
| R4 | Catalog 太抽象，Agent 无法找到入口 | 中 | 高 | module metadata、next_actions、导航 eval | no-match/retry 成功率低于 v1 map |
| R5 | Map v1 与 Catalog 并存导致 Agent 选择混乱 | 高 | 中 | capability-aware prompt、deprecation | Agent 重复调用两个全量工具 |
| R6 | 索引改变 query 排序或 authority lanes | 中 | 高 | differential/parity tests | MUST/CONTEXT 与 v0.6 不一致 |
| R7 | cache invalidation 错误服务陈旧记忆 | 低到中 | 极高 | fingerprint、reload tests、debug compare | source 变化后 view_id/结果未变化 |
| R8 | 分页跨 revision 重复或遗漏 | 中 | 高 | cursor 绑定 view_id | cursor 在 Source 改变后继续成功 |
| R9 | quarantine 爆炸造成“结构正确但实际失忆” | 中 | 高 | report-first、污染分级 | 隔离率超过约定观察阈值 |
| R10 | quarantine/diagnostics 泄露私有记忆存在 | 中 | 极高 | access-aware rendering | 无权主体看到 id/subject/count |
| R11 | Dialect 被误学或恶意污染 | 中 | 高 | candidate lane、人工确认、歧义诊断 | 单次 miss 自动改变 routing |
| R12 | 一等 edge 让写入成本过高 | 高 | 中到高 | 条件阶段、现场预填 | edge 使用率低、孤岛图增加 |
| R13 | 图遍历组合爆炸 | 中 | 高 | BFS tree、多重预算 | trace latency/size 超过预算 |
| R14 | inferred edge 混入权威图 | 中 | 高 | v1 禁止、provenance lane | 用户无法区分 declared/inferred |
| R15 | 语义重构被误用于删历史 | 低到中 | 极高 | append-only proposal/revision | 已批准 Source 被原地改写/删除 |
| R16 | 冷历史造成 target 不可达 | 中 | 高 | object contract/fsck/fallback | explain revision chain 断裂 |
| R17 | 核心硬编码个人/产品语义 | 中 | 高 | AGENTS boundary、domain schemas | core 出现私有 type/workflow/import |
| R18 | 工具数量过多增加 Agent 调用失败 | 高 | 中 | 最小 surface、合并 suggestions | 中位客户端不知该调用哪个工具 |
| R19 | 中位 Agent 不遵循重试/下钻协议 | 高 | 中到高 | in-band descriptions、prompt、eval | 一次 no-match 后直接停止 |
| R20 | 项目过早扩张成图数据库/记忆平台 | 中 | 高 | 非目标、阶段门、真实需求触发 | 基础导航未稳定就引入基础设施依赖 |
| R21 | 有界 Context 产生假完整性并漏掉 hard rule | 中 | 极高 | completeness、独立 compliance、fail loud | 任何适用 hard constraint 被静默省略 |

风险概率不是统计结论；每次发布前必须基于测试和真实公开反馈更新。

---

## 22. 事前验尸：如果最终失败，最可能怎样失败

### 22.1 最可能的架构失败

系统先实现精美的 index/catalog/trace，却没有冻结 ResolvedView/currentness 语义。结果是：

1. 图能快速导航；
2. 但分叉、环、access、candidate、stale 的服务语义不确定；
3. Agent 更快地找到一组互相矛盾的“当前”声明；
4. 用户开始不信任 compiled/map/trace；
5. 所有复杂基础设施退化成一次普通全文搜索的包装。

预防：先冻结 checkout 合同，再实现执法；index 可以先写，但不能先承诺它代表“当前真相”。

### 22.2 最可能的产品失败

读取端越来越强，写入端却越来越重：

1. 用户需要填写 subject/scope/use/relation/evidence/lifecycle；
2. 为避免麻烦，用户写无链接、弱证据声明，或干脆不写；
3. trace 进入大量孤岛；
4. dialect 和 graph 没有足够数据；
5. Agent 仍退化为一次 query；
6. 项目不是报错死亡，而是无人持续维护自己的 Memory Source。

预防：写入从 query/trace 锚点现场发起、自动预填、只让人确认；但不能绕过 review。

### 22.3 最可能的长期技术失败

把“Source 可以无限增长”误解成“任何层的增长都免费”：

1. `.mem` 中同时保存热声明和全部语义历史；
2. 每次 reload/compile 扫描全量；
3. Context 已经有界，但启动和查询延迟持续上升；
4. 为救性能临时引入不可审计数据库；
5. Source 与 index 分叉，重建不再可靠。

预防：持续基准；只有证明确实需要时才设计 versioned cold-history/incremental compiler，并保持纯 Source 可验证性。

### 22.4 最没有把握的研究问题

最没有把握的不是分页或索引，而是：

> 能否定义一个足够通用、又不会替领域做错误判断的 currentness/revision contract。

过于通用会没有约束；过于具体会把某个产品的记忆模型硬编码进核心。第一版必须保守：explicit relation、no automatic winner、visible fork/cycle、schema opt-in。

---

## 23. 验证矩阵

### 23.1 单元测试

#### Compiler/index

- duplicate full id；
- bare name ambiguity；
- deterministic index order；
- incoming/outgoing parity；
- module/type/role/subject/scope indexes；
- fingerprint changes；
- corrupted cache fallback。
- `Workspace()` + `parse_text()` 纯内存编译和 deterministic fingerprint；
- duplicate occurrences 不被单值 index 覆盖；
- full id、bare name、错误 kind prefix 使用同一 resolver；
- unknown relation typo 产生 diagnostic。

#### Revision graph

- linear supersedes；
- revision_of without supersedes；
- fork；
- two-node cycle；
- multi-node cycle；
- dangling target；
- ambiguous bare target；
- mixed relation types。
- candidate/retracted/archived superseder 不产生 authority effect；
- candidate supersedes active constraint 不能使 compliance 从 BLOCK 变 ALLOW；
- Map/query/list/status/vocabulary current-set consistency。

#### View

- active/candidate/superseded/retracted/archived；
- valid_until before/after as_of；
- principal/access filtering；
- report/quarantine/strict；
- no empty-result ambiguity；
- stable view_id。

#### Pagination

- first/middle/last page；
- empty page；
- exact boundary；
- cursor filter mismatch；
- stale cursor after Source change；
- deterministic order under reversed file load。

#### Trace

- outgoing/incoming/both；
- depth 0/1/N；
- cycle/back-edge；
- max nodes/edges/bytes；
- relation filters；
- unauthorized targets；
- provisional/quarantine visibility。

#### Dialect

- active alias；
- candidate alias cannot redirect；
- ambiguous aliases；
- scope-specific mapping；
- negative mapping（若实现）；
- no-match -> suggestion；
- private vocabulary filtering。

#### Manifest/version compatibility

- v1 manifest 在新 runtime 中保持 legacy parity；
- v2 manifest 在不支持 v2 的旧 runtime 中 fail closed；
- strict visibility/quarantine 只在明确 v2/opt-in 生效；
- old Map/EvidencePack schemas 不被原地改变。

### 23.2 Characterization/differential tests

对 0.6 fixtures：

- indexed query vs legacy query；
- indexed explain vs scan explain；
- old map v1 payload；
- compliance MUST behavior；
- PROVISIONAL isolation；
- candidate symbol cannot redirect；
- deterministic JSON/text rendering。

### 23.3 Property tests

建议性质：

- index 中每个 id 恰好对应 declarations 中一条 declaration，duplicate 除外；
- incoming/outgoing edge 双向一致；
- page 合并等于同一 View 的完整稳定序列；
- cursor 不跨 view_id；
- excluded/quarantined declaration 不进入 authoritative lanes；
- cycle detection 与输入顺序无关；
- compile(Source) 重复执行结果相同。

缓存/失效还必须覆盖：

- 内容改变但 size/mtime 相同；
- 文件新增、删除、改名；
- manifest/schema 改变；
- path 输入顺序反转；
- Windows/POSIX path normalization；
- 不同 Python hash seed；
- external schema path 在跨机器 fingerprint 中的明确稳定性边界。

现有 review 层已有 content-based `workspace_fingerprint()`，应优先评估复用，而不是只依赖 MCP 当前 mtime + size signature。

### 23.4 规模测试

只使用合成、虚构 fixture。至少覆盖：

- 100 / 1,000 / 10,000 declarations；
- 多 module 和单超大 module；
- 高 alias 密度；
- 高 edge density；
- 深链和宽图；
- 大量 superseded history；
- 多页 catalog/list/trace。

必须分别测量：

- Source parse/compile time；
- incremental reload time（若实现）；
- peak memory；
- query latency；
- explain latency；
- catalog response bytes；
- trace response bytes；
- v1 map response bytes（作为比较，不作为目标）。

不能只报告 token 估算；应保留 byte/item/time/memory 的可复现原始数据。

### 23.5 CLI 验证

继续执行项目 verify skill 的现有命令，并增加已发布的新 surface：

```console
memdsl lint examples/lint-demo/
memdsl query examples/alex/ -q "draft a public blog post about aurora"
memdsl explain examples/alex/ boundary:privacy.no_family_in_public
memdsl-mcp --inspect -w examples/alex
```

未来新增后再加入：

```console
memdsl catalog examples/alex/ --json
memdsl trace examples/alex/ decision:aurora.db_postgres_migration --depth 2 --json
```

命令和 id 必须以实际公开 fixture 为准，不能在 SPEC 中承诺尚不存在的示例。

### 23.6 MCP stdio

真实 MCP client session 必须验证：

- initialize/list tools；
- old map/query/explain；
- new catalog/trace；
- resource access；
- scope denial；
- cursor round trip；
- cursor stale；
- quarantine envelope；
- prompt 根据 capability 变化；
- tool result size 不超过测试预算。
- snapshot 新旧 tool input schemas；
- `memory_map` 继续无参兼容，`memdsl://map` 继续返回 v1；
- 新 `memdsl://catalog`（若采用）与 tool 输出一致；
- diagnostics/counts/vocabulary/trace/raw resources 均不泄露 unauthorized id/path/count。

### 23.7 Gated write path

在 disposable temp workspace：

1. propose dialect/edge/refactor candidate；
2. query/trace 不得把 pending proposal 当 durable memory；
3. approve 后重新 compile；
4. view_id/source fingerprint 改变；
5. 新 declaration 按 lifecycle/authority 进入正确 lane；
6. audit actions 保持 append-only；
7. stale-anchor proposal 得到明确 review 提示。
8. 有 dangling relation 的 workspace 仍可提交补 target 的 repair proposal；
9. proposal 中携带 document-level module/use 必须被拒绝或通过新 governed metadata 安全处理；
10. pending dialect/edge 不改变 alias routing、trace authority 或 supersede effect。

### 23.8 Packaging/privacy

每个 release 必须：

- 全套 pytest；
- compileall；
- `git diff --check`；
- build wheel/sdist；
- inspect artifact members；
- 扫描真实用户名、绝对路径、`.memdsl`、approved workspace、cache、数据库、日志、credentials；
- fresh install smoke；
- MCP optional dependency smoke。
- core Python 3.9-3.12 代表矩阵；
- MCP Python 3.10 和 3.12 代表矩阵；
- 真正列出 wheel/sdist members 并做隐私扫描，而不只运行 `twine check`。

### 23.9 评估指标

除“命令能运行”外，应持续记录：

- required-memory recall under budget；
- hard-rule omission count（目标为 0）；
- no-match retry recovery rate；
- p50/p95 TaskProjection bytes/items，以及宿主可选 token 估算；
- p50/p95 compile/query/explain/trace latency；
- peak compile memory；
- graph orphan ratio；
- explicit/inferred edge human acceptance rate（若实现 inferred）；
- dialect candidate acceptance/retraction rate；
- review backlog age 和 oldest pending；
- Agent 多步协议完成率；
- cross-principal differential leakage count（目标为 0）；
- archive 前后 ResolvedView 等价率；
- Source fingerprint/View determinism；
- non-authoritative edge 改变 authority 的次数（目标为 0）。

### 23.10 强制停止条件

出现以下任一情况，应停止 rollout、切回 report/legacy mode 并调查：

- 任何跨 principal 信息泄露；
- 任何适用 hard constraint 被预算或查询排序静默遗漏；
- candidate/provisional/retracted/archived edge 改变 active authority；
- 同一 Source + ViewContext 产生非确定性 View；
- cursor 跨 Source revision 拼接数据；
- Catalog/ContextSlice recall 明显低于 v1 且没有 incomplete 信号；
- review backlog 超过宿主约定 SLA，系统仍持续自动产生同类 candidate；
- cache 与 Source 不一致且无法自动检测/重建。

---

## 24. 发布门

每个 Phase 只有同时满足以下条件才能称为完成：

1. 实现与本文阶段合同一致；
2. SPEC/PUBLIC_API/README/UPGRADING 同步；
3. 旧兼容行为和新行为都有测试；
4. CLI + MCP stdio + gated write path 验证通过；
5. 合成规模和隐私检查通过；
6. breaking/default change 有明确 migration 和 rollback；
7. 未把宿主/个人语义引入核心；
8. wheel/sdist 内容安全；
9. 真实发布时完成 clean-tree build、远端 CI、tag 和 fresh install 验证。

文档完成、单元测试通过或本地 diff 正确，任何一个都不能单独代表发布完成。

### 24.1 当前 CI 基线缺口

0.6.0 当前 CI 已覆盖 core 的 Python 3.9-3.12、Windows/Linux、pytest、CLI smoke 和 build/twine check；MCP job 当前主要在 Python 3.12 上运行 `--inspect`。

在本方案进入发布前仍需补齐：

- MCP Python 3.10/3.12 代表矩阵；
- 真正 MCP stdio client round-trip；
- wheel/sdist member listing 和私密路径/Source/cache 扫描；
- outside-repo fresh wheel install；
- synthetic scale benchmark；
- v1/v2 side-by-side differential；
- access/quarantine/cursor/security stop-condition tests。

CI job 名称包含 “inspect wheel” 不等于已经检查 artifact members；`twine check` 也不能证明发布包没有真实 workspace 或机器路径。

---

## 25. 建议文件影响矩阵

以下是规划，不代表必须采用这些具体文件名：

| 区域 | 可能新增/修改 | 原因 |
| --- | --- | --- |
| compiler | `src/memdsl/compiler.py` | CompiledWorkspace、indexes、diagnostics |
| view | `src/memdsl/view.py` | ViewContext、ResolvedView、quarantine |
| graph | `src/memdsl/graph.py` | CompiledEdge、revision graph、trace |
| navigation | `src/memdsl/navigation.py` | Catalog、pagination、cursor |
| model | `src/memdsl/model.py` | 保留 uses/source metadata，兼容入口 |
| parser | `src/memdsl/parser.py` | 仅在 use/edge syntax 冻结后修改 |
| schema | `src/memdsl/schema.py` | relation/revision/dialect descriptors |
| linter | `src/memdsl/linter.py` | compiler/link/view diagnostics |
| query | `src/memdsl/query.py` | compiled indexes、suggestions、view input |
| compliance | `src/memdsl/compliance.py` | authoritative ResolvedView input |
| service | `src/memdsl/mcp_service.py` | compiled cache、catalog/trace/envelopes |
| server | `src/memdsl/mcp_server.py` | 新工具、prompt、capability descriptions |
| CLI | `src/memdsl/cli.py` | catalog/trace/compile surfaces |
| API | `src/memdsl/__init__.py` | 只在合同稳定后导出新公共类型 |
| tests | `tests/test_compiler.py` 等 | parity、graph、view、pagination、privacy |
| examples | `examples/` fictional fixtures | use/dialect/trace 的安全演示 |
| docs | SPEC/PUBLIC_API/UPGRADING/README | 公共合同和迁移 |

不要仅为了匹配此表创建空模块。实际拆分应以职责和可测试性为准。

---

## 26. 决策记录

| ID | 决策 | 原因 | 被否决/延期方案 | 状态 |
| --- | --- | --- | --- | --- |
| D-001 | Memory Source/History 不设固定总量 | 总量与单次可见成本是不同问题 | 超过阈值强制摘要 | 接受 |
| D-002 | 每次 TaskProjection 必须有硬预算 | Context window 和工具输出有限 | 只做常数项压缩 | 接受 |
| D-003 | 使用 ResolvedView/Checkout，不定义全局唯一 HEAD | View 依赖 principal/time/scope/policy | 所有 active 直接等于 HEAD | 接受 |
| D-004 | 语义收敛是可选重构，不是扩展性前提 | 不完整轨迹不足以自动合并 | 按年龄/数量自动 supersede | 接受 |
| D-005 | Source 权威，index/projection 可重建 | 保持可审计和存储中立 | 数据库/index 成为权威 | 接受 |
| D-006 | 编译器保证结构，不保证事实真实 | 自然语言真实性需 evidence/人审 | compiled = verified truth | 接受 |
| D-007 | `use` 可见性优于“必须先声明” | 声明式集合不应依赖文件顺序 | C 风格声明顺序 | 接受 |
| D-008 | 索引实现先行，执法最后收紧 | 降低兼容和失忆风险 | 一次性 fail-closed rewrite | 接受 |
| D-009 | 局部错误优先 quarantine | 整库拒服爆炸半径过大 | 任意 lint error 全库拒服 | 接受，identity 例外 |
| D-010 | Trace 使用确定性 BFS 生成树 | 避免路径组合爆炸 | 返回所有路径 | 接受 |
| D-011 | v1 只建 explicit/structural edges | inferred graph 需额外基础设施与审计 | 第一版 embedding inferred edges | 延期 |
| D-012 | Dialect 属于 workspace Source | 每个人的语言不同，核心应中立 | 在 Python 代码动态维护用户 aliases | 接受 |
| D-013 | active dialect mapping 仍需 review | 防止误学和注入 | 一次 retry 自动写 active | 接受 |
| D-014 | 一等 edge 分条件阶段实现 | 边审核重要但写入成本高 | 立即重写 relation syntax | 延期 |
| D-015 | Map v1 不原地改成 Catalog | schema/语义兼容 | 沿用 map.v1 id 改含义 | 接受 |
| D-016 | 冷历史在性能证据后设计 | 当前首先要解 Context，不宜过早引入存储系统 | 立即数据库化 | 延期 |
| D-017 | 非权威 edge 不得改变 authoritative lane | candidate supersedes 当前可绕过 MUST/compliance | 所有声明的 supersedes 都立即生效 | 接受，优先修复 |
| D-018 | 授权过滤先于聚合和图遍历 | counts/vocabulary/path/edge 也会泄露 | 只过滤 query items | 接受 |
| D-019 | 权威规则不得被 Context budget 静默截断 | 小而整洁的结果可能产生假完整性 | 所有 lane 共享普通 result limit | 接受 |
| D-020 | 保留底层原语，并以评估决定是否增加一调用 facade | 中位 Agent 可能不执行多步协议 | 只发布越来越多独立工具 | 条件接受 |
| D-021 | workspace v2 每个 source file 最多一个 module statement | 当前 parser 的 last-module-wins 会破坏 lexical visibility，保留多 module 又要求扩充 AST | 继续允许多 module 且不保存逐声明 context | 接受；v1 仅 characterization |
| D-022 | fork 不选 winner；cycle edge 不产生排除 authority | 文件顺序/排序选 winner 会隐藏冲突，cycle 当前会让双方消失 | 保留 0.6 静默排除作为 parity | 接受最小语义；quarantine/strict 细节延期 |
| D-023 | 已知缺陷用 strict xfail 与当前行为断言成对保存，不进入兼容合同 | characterization 不能把 security/correctness bug 永久固化 | 只做 golden snapshot 或只写未来测试 | 接受 |
| D-024 | read gate 必须保留独立 repair lane | 坏链接若同时堵死修复写入会形成不可恢复拒服 | 所有 compiler error 同时关闭 read/propose | 接受；parse/schema repair API 形状延期 |
| D-025 | Phase 0A 停止发出 `unmarked_supersede_status`，currentness 由 active incoming supersedes relation 派生 | 要求原地改旧 status 违反 append-only correction；warning 会诱导静默改写历史 | 降低 severity 或继续建议 `status: superseded` | 接受并已实现 |

---

## 27. 尚未冻结的开放问题

以下问题在进入对应实现阶段前必须决策：

1. `use X` 精确导入 symbol、module 还是 namespace？
2. relation descriptor 属于 core registry、schema 还是 manifest？
3. 哪些 relation 默认必须 acyclic？
4. revision fork 的 report mode 已冻结为“不选 winner、两个有效 successor 保持可见并报告”；quarantine/strict 中的精确污染范围是什么？
5. duplicate full id 是否永远 workspace-blocking？
6. access-policy filtering 的公共 Python API 形状？
7. `view_id` 是否包含 principal digest，如何避免侧信道？
8. Catalog 是新工具还是 map mode？本文倾向新 schema/new tool。
9. cursor 是完全无状态签名 token，还是 server-side opaque handle？
10. 默认 item/byte budgets 是多少？必须通过 MCP client 和规模测试确定。
11. vocabulary suggestion 是否独立工具？本文倾向先合入 query。
12. logical revision family 是否需要 schema `family_key_fields`？
13. 一等 edge 最终采用 core syntax 还是 domain declaration？
14. 语义历史是否永久留在热 Source，何时需要 cold-history contract？
15. 新能力的目标版本和 deprecation window 多长？
16. raw `.mem` 文件混合不同 access policy 时，是否拒绝整文件读取、提供授权 source projection，还是要求物理文件分区？
17. hard constraint 正文不可读但可 enforce 时，opaque verdict 的公共 envelope 如何定义？
18. v1 多 module 文件的 report diagnostic 严重级别、deprecation window 和自动迁移建议是什么？
19. parse/schema 已损坏时，repair lane 只允许直接 source edit，还是需要独立的 governed source-patch proposal？

开放问题不得由实现代码偶然决定。每项冻结后应更新决策表和变更记录。

---

## 28. 文档与实现变更记录

后续每次改变本合同，都必须追加一行；不能只改正文而不记录原因。

| 日期 | 版本/commit | 变更 | 为什么改变 | 可能影响 | 验证/迁移 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-07-14 | 基线 0.6.0 / `72274d9` | 最初把 Map 扩展问题描述为全量输出线性增长 | 当前 Map 枚举每条 serviceable declaration，MCP 还返回结构化数据和 rendered text | Map/filter/page/representation 设计 | Map v1 源码和 CLI/MCP 实测 | 已确认问题 |
| 2026-07-14 | 同上 | 从“必须让 Memory/active set 保持固定大小”改为“Source/History 可无界，TaskProjection 必须有界” | Git/源码类比说明总量与一次可见成本不是同一变量；强制摘要会引入不可靠语义判断 | compaction 从必需能力降为可选 refactoring；增加 Catalog/预算/游标 | 讨论推演、源码复杂度审计 | 接受 |
| 2026-07-14 | 同上 | 从“全局唯一 Memory HEAD”改为参数化 ResolvedView/Checkout | Git HEAD 只选 revision；Memory 还依赖 principal、as_of、scope、policy 和冲突状态 | 新增 ViewContext、view_id、authority/provisional/quarantine/excluded 分类 | 分叉/循环/时间/access 反例 | 接受 |
| 2026-07-14 | 同上 | 将 CompiledWorkspace 拆成“数据结构地基”，将 gate/quarantine 视为后续 policy | incoming refs、by_id、query 候选已有索引需求；执法会改变公开服务语义 | 索引先行、report shadow、enforcement 后置 | explain 全量扫描和 read-path 无 lint gate 的源码审计 | 接受 |
| 2026-07-14 | 同上 | `use` 不采用声明顺序，改为 two-pass 可见性；strict 需 workspace v2 | 声明式文件不应依赖顺序；当前 parser 保存 use 但 Workspace 丢弃，且多 module 文件最后一个覆盖全部声明 | parser/AST、manifest v2、legacy/report/strict migration | parser/model 源码和合成多 module 反例 | 接受，语义未实现 |
| 2026-07-14 | 同上 | 图从“节点 relations 足够”改为“先派生 CompiledEdge，真实需要后再做一等可审边” | 节点 evidence 不能证明某条 A->B 关系；但立即重写语法会显著增加写入成本 | relation registry、edge provenance、BFS trace；一等 edge 条件延期 | model/linter/explain 源码审计 | 分阶段接受 |
| 2026-07-14 | 同上 | 方言从核心动态维护改为 workspace-owned、candidate/review-gated Source | 个人语言长尾且私密；核心不能维护统一个人词表，单次重试也不足以直接转正 | dialect schema/use、隐私保留期、candidate alias 不得 redirect | alias/search_trace/review 现有能力审计 | 接受 |
| 2026-07-14 | 同上 | 新增 Phase 0A authority hotfix：非权威 supersedes 不得影响 active | 实测 candidate supersedes 能隐藏 active boundary，并让 compliance 从 BLOCK 变 ALLOW | supersede resolver、MUST/compliance、UPGRADING、安全回归 | 当前 0.6.0 合成 workspace 实测 | 最高优先级缺陷 |
| 2026-07-14 | 同上 | 将授权和完整性提升为 Context budget 的硬前提 | 有界响应可能通过 counts/path/trace 泄露私密内容，也可能静默遗漏 hard constraint | authorization-before-aggregation、completeness、opaque enforce、停止条件 | MCP raw resource/status/list 源码审计与事前验尸 | 接受 |
| 2026-07-14 | 同上 | Map/Query/View breaking semantics 不复用 v1，建议 0.7 兼容导航、0.8 workspace v2 | 0.6 compatibility promise 要求 breaking JSON 新 schema；v1 loader 会忽略未知字段语义 | v1/v2 并存、deprecation、迁移矩阵 | PUBLIC_API/schema/MCP/CLI 兼容审计 | 暂定，版本未冻结 |
| 2026-07-14 | Phase -1（本提交）/ 源码基线 `72274d9` | 增加 Map/query/explain payload snapshots、19 个当前行为断言和 10 个 strict xfail 实例 | 需要区分 0.6 兼容事实、已知 authority 缺陷和尚未实现的新合同 | 后续 indexed parity、Phase 0A/1/2 转正门 | `tests/test_phase_minus_one_characterization.py` 与纯合成 fixtures | Phase -1 完成 |
| 2026-07-14 | 同上 | 固化 100/1,000/10,000 declarations 的 parse/map/query/explain 合成基线 | 需要用可复现数据区分输出膨胀与计算膨胀，且不得读取真实 workspace | 为后续 index/catalog/budget 提供比较基线，不构成性能承诺 | 五次原始样本；10k 中 Map 3,070,788 bytes、Query 扫描 10,000、Explain 911,061 bytes/9,999 incoming refs | 已记录 |
| 2026-07-14 | 同上 | 冻结 workspace v2 一文件一 module；v1 last-module-wins 只做 characterization | 当前 AST 不保存 lexical module/use context，无法安全直接启用 strict visibility | Phase 4 需 report/migration，再由 v2 strict enforcement | `multiple_modules.mem` parser characterization | 语义冻结，未实现 |
| 2026-07-14 | 同上 | 冻结 fork/cycle 最小语义，并明确 strict xfail 不冻结 diagnostic/envelope 字段名 | 测试必须表达 fail-loud/无静默 winner 或全消失，又不能让测试代码偶然决定未来 API | Phase 1 仍需冻结 diagnostic codes、污染范围和响应 schema | fork/cycle fixture + current/desired 成对测试 | 最小语义冻结 |
| 2026-07-14 | 同上 | 记录 lint-error 可读可修、parse/schema-error 同时阻断 read/propose 的现有 repair boundary | ResolvedView gate 不能让 workspace 失去修复通道；当前 parse failure 仍缺 governed repair lane | Phase 1/后续需设计 parse/schema repair 入口 | disposable temp-workspace MCP characterization | 当前事实确认；未来形状开放 |
| 2026-07-14 | Phase 0A（本提交）/ 起点 `cf8c2bc` | 增加最小 supersedes authority resolver，统一 Map/query/compliance/list/status/vocabulary，停止 `unmarked_supersede_status` | candidate supersedes 可绕过 active hard constraint；各 surface current set 不一致；旧 warning 违反 append-only correction | 非 active、歧义、重复、dangling、wrong-prefix supersedes 不再产生 authority effect；依赖缺陷的 workspace 行为被纠正 | 5 个 Phase 0A strict xfail 转正，5 个后续 xfail 保留；全套 CLI/MCP/gated-write 验证 | Phase 0A 完成；correctness/security fix |
| 2026-07-14 | Phase 0B（本提交）/ 起点 `244e8d2` | 增加内部 CompiledWorkspace、确定 resolver、identity/semantic/edge indexes、content-aware compiled cache，并让 v1 读取面复用 compile | 后续 diagnostics/View/Catalog/Trace 需要共享地基；旧 explain 每次全量扫描 incoming，MCP 仅 mtime+size 可能服务陈旧内容 | 内部 lookup/cache/遍历变为确定且可复用；公共 v0.6 envelope、authority、review lane 不变 | 13 个 compiler/parity/property/reload tests；全套 `236 passed, 5 xfailed`；CLI/MCP/gated-write 验证 | Phase 0B 完成；内部 indexed parity |

建议每条记录额外回答：

1. 原方案是什么？
2. 哪个源码事实、测试结果或用户反馈推翻了它？
3. 新方案改变哪条不变量？
4. 哪些客户端/workspace 会受影响？
5. 如何验证？
6. 如何回滚？

---

## 29. 实施检查表

### 设计冻结前

- [ ] 决策表和开放问题完成 owner review。
- [ ] 所有当前源码事实重新核对行号和行为。
- [ ] 明确 target version 和 compatibility window。
- [ ] 明确哪些阶段属于同一 release，避免一次发布过大。

### 每个编码阶段

- [ ] 保持 Source/projection 边界。
- [ ] 不触碰真实/private workspace。
- [ ] synthetic fixtures 使用虚构身份和 fake evidence。
- [ ] 先加 characterization，再改实现。
- [ ] 新 diagnostics 有稳定 code。
- [ ] 新 envelope 有 schema version。
- [ ] 新 cursor 绑定 view/filter/order。
- [ ] 新 cache 可删除重建。
- [ ] 新写入仍经过 review/audit。
- [ ] access filtering 覆盖 diagnostics、counts、vocabulary 和 graph。

### 发布前

- [ ] pytest/compileall/diff-check。
- [ ] CLI 示例。
- [ ] MCP inspect + stdio round-trip。
- [ ] scope denial。
- [ ] gated write temp-workspace loop。
- [ ] scale benchmark。
- [ ] wheel/sdist inspection。
- [ ] fresh install。
- [ ] README/SPEC/PUBLIC_API/UPGRADING 同步。
- [ ] 变更记录、迁移、回滚完成。

---

## 30. 最终架构立场

本文最终确立以下立场：

> Memory 可以像 Source Code 一样持续增长，但不能把“像源码”理解成“把所有源码永久塞进 Agent Context”。

> 真正的地基不是更小的 Map，而是从规范 Source 到确定 ResolvedView，再到有界 TaskProjection 的可审计编译链。

> 编译器可以证明 id 唯一、引用可达、关系无环、视图可复现；它不能证明某条自然语言记忆仍然真实，也不能证明 A 在现实中真的支持 B。

> 真实性由 evidence、事件、反驳和人审维护；扩展性由目录、索引、分页、游标、预算和按需下钻维护；二者不能互相冒充。

如果未来模型更强、成本更低，这套架构不需要推翻：变化的是 candidate 质量、自动化比例和宿主能力，而 Source authority、review boundary、View determinism 和 projection budget 仍然成立。

---

## 附录 A：0.6.0 源码证据索引

以下位置用于复核本文“当前事实”；实现移动后应按符号重新查找，不能只依赖旧行号。

| 事实 | 当前证据 |
| --- | --- |
| Workspace 全量加载和 add_document | [model.py](../src/memdsl/model.py#L157) |
| 线性 by_id、active、superseded_ids | [model.py](../src/memdsl/model.py#L194) |
| Phase 0A supersedes authority resolver 与 shared current set | [authority.py](../src/memdsl/authority.py) |
| relations 固定字段和字符串列表 | [model.py](../src/memdsl/model.py#L12)、[model.py](../src/memdsl/model.py#L123) |
| parser 的 Document.module/uses 和最终 module 覆盖 | [parser.py](../src/memdsl/parser.py#L115)、[parser.py](../src/memdsl/parser.py#L146) |
| query 全量候选/评分与 MUST 扫描 | [query.py](../src/memdsl/query.py#L208)、[query.py](../src/memdsl/query.py#L231) |
| vocabulary 静默 limit | [query.py](../src/memdsl/query.py#L402) |
| 全量 Memory Map | [query.py](../src/memdsl/query.py#L432) |
| MCP Workspace mtime+size cache | [mcp_service.py](../src/memdsl/mcp_service.py#L169) |
| MCP Map v1 双份响应 | [mcp_service.py](../src/memdsl/mcp_service.py#L412) |
| MCP explain incoming 全量扫描 | [mcp_service.py](../src/memdsl/mcp_service.py#L517) |
| MCP list/status 使用共享 Phase 0A current set | [mcp_service.py](../src/memdsl/mcp_service.py#L317)、[mcp_service.py](../src/memdsl/mcp_service.py#L641) |
| MCP raw files/path/content | [mcp_service.py](../src/memdsl/mcp_service.py#L932) |
| compliance 使用共享 Phase 0A current set | [compliance.py](../src/memdsl/compliance.py#L169) |
| lint relation target（完整统一 diagnostics 尚未实现） | [linter.py](../src/memdsl/linter.py#L153) |
| proposal 忽略 pre-existing diagnostics | [review.py](../src/memdsl/review.py#L216) |
| content-based workspace fingerprint | [review.py](../src/memdsl/review.py#L1947) |
| workspace manifest v1 loader | [schema.py](../src/memdsl/schema.py#L370) |
| Python/MCP 兼容版本 | [pyproject.toml](../pyproject.toml#L5)、[PUBLIC_API.md](PUBLIC_API.md#L1) |
| append-only correction 与 compatibility promise | [PUBLIC_API.md](PUBLIC_API.md#L310) |
| core/MCP CI matrix | [ci.yml](../.github/workflows/ci.yml#L7) |
| publish workflow | [publish.yml](../.github/workflows/publish.yml#L1) |

---

## 附录 B：Phase -1 必须固化的合成反例

所有 fixture 必须使用虚构内容和 fake evidence。

1. 两个 active successors supersede 同一个 target：fork 不得静默选赢家。
2. A/B 互相 supersede：cycle 不得让双方无提示消失。
3. candidate supersedes active fact：candidate 不得隐藏 active。
4. candidate supersedes active global constraint：compliance 不得从 BLOCK 变 ALLOW。
5. retracted/archived declaration 发起 supersedes：无 authority effect。
6. `fact:shared` 与 `decision:shared`，relation target 使用 bare `shared`：必须 ambiguous。
7. target 写成错误 kind prefix：lint/runtime 必须使用同一 resolver。
8. unknown relation 拼写：必须 diagnostic，不能静默丢边。
9. duplicate full id：保留 occurrences，读取不能随机解释第一条。
10. 一个文件出现两个 module：冻结一文件一 module 或保留 lexical context。
11. unresolved subject/relation：report、quarantine、repair lane 行为明确。
12. 51+ vocabulary subjects：truncation/total/cursor 可见。
13. 单 symbol 含大量 aliases：per-item byte budget 生效。
14. 高入度节点：explain incoming 分页/预算生效。
15. 超大 evidence：query/explain representation 和 byte budget 生效。
16. expired valid_until：legacy 与 v2 View 行为分别明确。
17. owner-only declaration：所有读取面、counts、paths、trace 均不向其他 principal 泄露。
18. cursor 期间 Source 改变：返回 cursor_stale。
19. broken workspace 提交 repair proposal：读取 gate 不得堵死修复 lane。
20. v2 manifest 交给旧 runtime：必须 fail closed，而不是忽略新语义。

---

## 附录 C：Phase -1 证据矩阵

本附录记录 2026-07-14 实际完成的当前基线。`当前断言` 表示测试应继续通过；
`strict xfail` 表示目标不变量尚未实现，XPASS 会强制实施窗口转成普通回归测试。

| 合同/反例 | 当前 0.6 characterization | 目标测试状态 | 转正阶段 |
| --- | --- | --- | --- |
| Map/query/explain v1 shape、双份 representation | 三份 JSON snapshot | 当前断言 | indexed parity 后继续保留 v1 |
| candidate/retracted/archived supersedes active | active target 保持 Map/query authority | 普通回归，共 3 实例 | Phase 0A 已转正 |
| candidate supersedes global constraint | compliance 保持 `block` | 普通回归 | Phase 0A 已转正 |
| Map/list/status/vocabulary current-set | authority-bearing counts 一致 | 普通回归 | Phase 0A 已转正 |
| supersedes fork | 两个 successor 可见，无 fork diagnostic | strict xfail（不冻结 code） | Phase 1 |
| supersedes cycle | 两个节点都消失，无 cycle diagnostic | strict xfail（不冻结 code） | Phase 1 |
| ambiguous bare ref | 内部 resolver 已拒绝；尚无 ambiguous diagnostic | 合并 strict xfail（不冻结 diagnostic envelope） | resolver Phase 0B；diagnostic Phase 1 |
| wrong kind prefix | 内部 resolver 不做 suffix fallback；lint 尚未 fail loud | 同上 | resolver Phase 0B；diagnostic Phase 1 |
| unknown relation typo | nested key 仍被静默丢弃 | 同上 | Phase 1 relation diagnostic |
| duplicate full id | compiler 保留两 occurrence 且不建立 resolved id；v1 explain 仍取第一条 | strict xfail（只要求不返回普通 ok） | occurrence index Phase 0B；serving gate Phase 1 |
| 一个文件两个 module | 最后 module 覆盖全部 declarations | 当前断言；v2 一文件一 module 已冻结 | Phase 4 |
| 51 subjects | subjects 静默只返回 50，无 completeness metadata | strict xfail（不冻结字段名） | Phase 2 |
| 大 aliases/lifecycle | `claim_chars` 不限制 symbol summary/lifecycle/aliases | 当前断言 | Phase 2 |
| 大 evidence/高入度 explain | full evidence、32 incoming refs、双份文本，无 budget metadata | 当前断言 | Phase 2/3 |
| expired valid_until/owner-only access | lint warning，但 Map/query/list/explain 继续服务 | 当前断言，不选择未来 API | workspace v2/View 阶段 |
| lint-error repair lane | read 继续服务；补 symbol proposal 可进入 review | 当前断言 | 后续 gate 必须保持 |
| parse-error repair lane | MCP read/propose 都返回 parse_error | 当前断言；未来入口开放 | 后续 source-repair 设计 |
| 100/1,000/10,000 scale | parse/map/query/explain 五次原始样本 | 合成基线 | 各性能阶段 differential |

附录 B 中尚无 API 可执行的 cursor-stale、v2 manifest fail-closed、跨 principal
差分泄漏、Catalog/Trace pagination 等项目，本窗口没有伪造实现。它们保留在
第 23 节验证矩阵和开放问题中，待对应 schema/API 存在后转成正式测试。
