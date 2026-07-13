# 设计与实现合同：分级写入审核

- 状态：0.6.0 实现合同
- 基线：memdsl 0.5.1，commit e8596aa
- 目标版本：0.6.0
- 读者：实现、审核和发布 memdsl 0.6.0 的维护者

本文档是 0.6.0 的完整执行合同。实现不能只满足示例路径；下文的信任边界、不可绕过底线、审计快照、CLI/MCP 契约、测试矩阵和验收标准都属于发布范围。

文档中的 MUST、MUST NOT、SHOULD 按规范性要求理解。实现前仍需以当前工作树复核文件位置；如果代码已经移动，语义要求不随行号变化。

---

## 1. 问题与结论

memdsl 0.5.x 对所有 proposal 使用同一条路径：验证后进入 pending 队列，只有人工 approve 才写入记忆源文件。这保证了早期安全性，但把机械校验、低风险观察和真正改变行为边界的写入都交给了人。

0.6.0 不取消审核，而是把审核拆成四种结果：

| 结果 | 含义 | 是否创建新 proposal |
| --- | --- | --- |
| invalid | 解析、schema 或 lint 失败，拒绝提交 | 否 |
| no_op | 规范化内容与 pending 或已存在内容重复 | 否，返回既有记录 |
| auto_approved | 低风险 proposal 同时通过类型、宿主身份、证据、策略和限额检查 | 是 |
| queued | 任何不确定、高风险、抽样、限额或缺少自动化授权的 proposal | 是 |

核心结论：

1. proposal 文本不是信任根。client、证据是否真实、证据来源和授权 scope 必须由宿主提供。
2. 自动批准是双重类型 opt-in：策略必须精确列出 kind，该 kind 的 TypeDescriptor 还必须显式包含 auto_approvable capability。
3. v1 只允许 candidate assertion 自动批准。question、guidance、constraint、symbol 和 unknown 一律人工审核。
4. candidate 不是已确认记忆。所有可服务的非 active 命中只进入独立 PROVISIONAL 层。
5. ReviewStore 只保证原子文件更新和 append-only audit，不创建 Git commit，也不承诺可以按 proposal 做 git revert。
6. 自动项的晋升、修订和撤销都通过新的普通 declaration proposal 表达，并强制人工审核；不得静默改写或物理删除已批准源声明。

## 2. 目标与非目标

### 2.1 目标

0.6.0 MUST：

1. 提供声明式 ReviewPolicy 和确定性的 RoutingAssessment。
2. 保持默认全人工：无 policy、trusted_clients 为空、日限额为 0、无 write:auto scope 或证据未验证时都不能自动批准。
3. 将宿主可信上下文与 proposal 自述字段分离。
4. 为 candidate 声明提供 PROVISIONAL 查询层，并保证 candidate constraint 不进入 MUST 或 compliance。
5. 提供规范化去重、稳定抽样、基本日限额和完整路由审计。
6. 在自动批准前重新加载 workspace、校验内容指纹，并限制写入目标位于主 workspace root 内。
7. 提供异步人工复核、digest 和 stats，使自动批准质量可度量。
8. 保持 append-only 的 proposal、decision 和 post-review 历史。
9. 完成 CLI、MCP、Python public API、规范、升级说明、测试、构建和发布闭环。

### 2.2 非目标

0.6.0 不做：

- LLM 语义二审。
- 自动解决自然语言冲突。
- 自动晋升 candidate 为 active。
- 自动撤销被 flag 的记忆。
- 物理删除或原地改写已批准 declaration。
- 由 memdsl 核心创建 Git commit、Git tag 或执行 git revert。
- 依赖 DigitalSelf、rawmem、某个用户身份、某个私有 schema 或固定文件布局。
- 接受 MCP tool 调用者传入的 trusted client、evidence verified 或 verifier attestation。

## 3. 现有代码边界

需要复用而不是绕开的现有机制：

| 事实 | 当前实现 |
| --- | --- |
| proposal 必须恰好包含一条 declaration，并与 live workspace 合并 lint | [src/memdsl/review.py](../src/memdsl/review.py) |
| approve 使用锁、原子替换、provenance marker 和幂等恢复 | [src/memdsl/review.py](../src/memdsl/review.py) |
| audit.log 是 append-only JSONL | [src/memdsl/review.py](../src/memdsl/review.py) |
| runtime_role、status、force、scope、evidence、access_policy 和 relations 来自 Declaration/TypeDescriptor | [src/memdsl/model.py](../src/memdsl/model.py)、[src/memdsl/schema.py](../src/memdsl/schema.py) |
| Workspace.active() 当前实际含义是 non-excluded/serviceable，即只排除 superseded、retracted、archived | [src/memdsl/model.py](../src/memdsl/model.py) |
| query 当前按 runtime_role 将命中分入 MUST、SHOULD、CONTEXT、MISSING | [src/memdsl/query.py](../src/memdsl/query.py) |
| compliance 当前从 serviceable declarations 选择 constraint | [src/memdsl/compliance.py](../src/memdsl/compliance.py) |
| MCP 的 write:candidate 只授权提出 proposal | [src/memdsl/mcp_service.py](../src/memdsl/mcp_service.py) |

Workspace.active() 在 0.6.0 保留兼容语义，不改名也不缩窄返回集合。查询与 compliance 必须显式检查 declaration.status；任何代码都不能把 Workspace.active() 的返回值等同于 lifecycle.status == active。

## 4. 信任模型

### 4.1 两类输入

路由器同时读取两类输入：

1. 不可信的 proposal 内容：declaration kind、fields、lifecycle、scope、evidence map、relations，以及 reason。
2. 宿主可信上下文：已认证 client、部署授予的 scopes、证据验证结果和 workspace 路径。部署 scopes 由 MCP/ReviewStore 编排层处理，不从 proposal 读取。

proposal 可以声称自己来自任何 client，可以填写任意 evidence.source 和 evidence.quote，也可以把 status 写成 candidate。上述内容只能作为待验证声明，不能直接成为自动批准依据。

### 4.2 ProposalContext

新增不可从 proposal source/header 反序列化的宿主对象：

~~~python
@dataclass(frozen=True)
class EvidenceVerification:
    verified: bool
    verifier: str = ""
    source_digest: str = ""   # 已读取证据源内容的 sha256
    quote_digest: str = ""    # 已验证 quote 的 sha256
    evidence_digest: str = "" # 完整 evidence map 的规范 sha256
    reason: str = ""          # 未通过时的稳定 reason code


@dataclass(frozen=True)
class ProposalContext:
    client_id: str            # 宿主认证的稳定 client id
    evidence_verification: Optional[EvidenceVerification] = None
~~~

约束：

- ProposalContext MUST 由宿主创建。
- ReviewStore.submit 的 context 缺失时必须把 None 作为未认证状态交给安全底线，结果只能 queue；不得凭空构造一个可被 policy 信任的默认 client。
- Proposal.client 和 proposal 文件中的 client header 仅用于显示与追踪；即使它们保存了 context.client_id 的副本，路由时也不得重新读取它们作为信任证据。
- MCP memory_propose 的参数中不得出现 client、trusted、verified、verifier、scopes 等 attestation 字段。
- Python 宿主可注入自定义 verifier，但 verifier 的返回值必须通过 ProposalContext 进入路由器。
- write:auto 等部署 scope 不放进 ProposalContext；编排层以显式 blocking reason 传给 policy assessment，避免身份/证据对象与部署授权混为一谈。

### 4.3 内置 workspace_file_quote verifier

0.6.0 提供可实际使用的内置 verifier，标识固定为 workspace_file_quote。

验证规则：

1. evidence 必须是 map，并包含非空 source 与 quote。
2. 相对 source 分别在每个 workspace root 下解析；绝对 source 只有在 realpath 仍位于某个 workspace root 内时才可验证。
3. 目标必须是 workspace root 内的普通文件；任何 symlink 都按 unverified 处理。
4. 绝对外部路径、路径穿越、目录、无法读取、歧义匹配或非 UTF-8 文件均返回 unverified。
5. quote 必须作为完整 Unicode 字符串逐字出现在 UTF-8 文件内容中；不做模糊匹配、语义匹配或大小写折叠。
6. 成功后记录 source_digest、quote_digest 和绑定完整 evidence map 的 evidence_digest；audit 不保存证据文件全文或 quote 原文。

自动写入仍只使用 §9.2 定义的主 workspace root；内置 verifier 可以在调用方显式传入的任一 workspace root 内验证证据，但不能越出这些 root。

证据未验证不等于 proposal 非法。只要 declaration 本身通过 lint，它仍可进入人工队列；它只是不能自动批准。

## 5. 类型与 lifecycle 合同

### 5.1 类型双重 opt-in

TypeDescriptor 继续使用 capabilities 表达通用运行时能力。0.6.0 新增保留 capability：

    auto_approvable

自动批准必须同时满足：

1. policy rule 的 match.kind 是非空的精确类型列表，并命中 declaration.kind。
2. 当前 workspace registry 中对应 TypeDescriptor 显式含 auto_approvable capability。

任一条件缺失都不能自动批准。标准兼容包中的类型默认不获得该 capability；workspace/domain schema 必须显式开启。

类型发现接口必须展示该 capability，因此 memdsl types、memory_types 和 TypeDescriptor.as_dict 不需要增加另一套布尔字段。

### 5.2 v1 唯一可自动类型

即使类型和策略 opt-in，v1 仍只允许：

- runtime_role == assertion
- lifecycle.status == candidate

question 和 guidance 默认并永久落入人工队列，不能通过 policy 放宽。理由：

- question 会改变 MISSING 与 agent 的问题空间，仍可能造成提示注入。
- guidance 会改变 SHOULD，即使不是 hard，也会影响 agent 决策。

constraint、symbol、unknown 的风险更高，同样不可自动批准。

### 5.3 PROVISIONAL 层

EvidencePack 增加独立 PROVISIONAL 层。memdsl.evidence_pack.v1 保持 schema id，新增字段是兼容性 additive extension：

~~~text
MUST          active constraint
SHOULD        active guidance
CONTEXT       active assertion
PROVISIONAL   status != active 且仍 serviceable/searchable 的 scored hit
CONFLICT      active selected declarations 的显式冲突
MISSING       active question 与显式检索缺口
~~~

实现要求：

- query 的 active 语义层只接受 declaration.status == active。
- candidate assertion 不进入 CONTEXT。
- candidate guidance 不进入 SHOULD。
- candidate question 不进入 MISSING。
- candidate constraint 不进入 MUST。
- 任何 status != active、未被 superseded/retracted/archived 排除、具有 searchable capability 且命中的 declaration，只能进入 PROVISIONAL。
- PROVISIONAL item 与 CONTEXT 一样保留 score 和 matched_terms，同时必须携带 id、type、runtime_role、status、完整 lifecycle、evidence 和位置。
- render_text 总是输出 PROVISIONAL 标题，即使为空。
- 文本渲染的每条 declaration 必须明确显示 status 和 runtime_role；非 active 项必须显示完整 lifecycle，避免宿主把 provisional 内容当已确认事实。
- alias resolution、MUST/SHOULD/CONTEXT/CONFLICT/MISSING 的有效语义不能由 candidate symbol 或其他 candidate 声明改变。
- memory map 可以继续统计全部 serviceable declarations，但每项必须携带 status/lifecycle；任何名为 active_declarations 的计数都只能计算 status == active。

### 5.4 candidate constraint 与 compliance

applicable_constraints 以及所有 compliance 入口必须显式要求：

    declaration.runtime_role == "constraint"
    and declaration.status == "active"

candidate constraint 不产生 allow、block 或 needs_review 的约束判定。它可以作为 searchable hit 出现在 PROVISIONAL，但不具有执行力。

## 6. ReviewPolicy 文件

### 6.1 位置与错误语义

策略位置固定为：

    <staging_dir>/policy.json

默认 staging_dir 仍为主 workspace root 下的 .memdsl。

load_policy 的行为：

- 文件不存在：返回 None，全部 queue。
- 文件存在且合法：返回 ReviewPolicy。
- 文件存在但 JSON、字段、类型、范围、version 或 rule 非法：抛 PolicyError。

PolicyError 是配置硬错误，绝不能静默降级为 queue。CLI 必须以非零退出，MCP 必须返回 policy_invalid。原因是静默降级会让部署者误以为自动化策略正在工作。

### 6.2 封闭 JSON schema

顶层字段：

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| version | string | 只允许 memdsl.policy.v1 |
| default_route | string | 只允许 queue |
| auto_merge_into | string | 相对主 workspace root 的 .mem 路径 |
| sample_to_queue_percent | integer | 0 到 100 |
| max_auto_approve_per_day | integer | 大于等于 0；0 表示禁用自动批准 |
| trusted_clients | list[string] | 元素必须非空且唯一；空列表表示全部 queue |
| rules | list[PolicyRule] | 按声明顺序评估 |

未知顶层字段必须 PolicyError。

PolicyRule：

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| name | string | 非空、在文件内唯一 |
| route | string | 只允许 auto_approve |
| tier | string | 可选的展示分组，不参与安全判断 |
| match | object | 使用下表封闭键集合 |

match 支持：

| 键 | 类型 | 来源 | 语义 |
| --- | --- | --- | --- |
| kind | list[string] | declaration | 必填、非空、精确类型名 |
| scope | list[string] | declaration | scope 白名单 |
| scope_not | list[string] | declaration | scope 黑名单 |
| client | list[string] | ProposalContext | 可信 client 白名单，只能收紧 trusted_clients |
| evidence_verifier | list[string] | EvidenceVerification | verifier id 白名单 |
| force_not | list[string] | declaration | force 黑名单，只能进一步收紧 |

未知 match 键、空列表、非字符串元素或互相矛盾的值必须 PolicyError。kind 是每条 auto_approve rule 的必填项，避免一条宽泛规则意外覆盖未来新增类型。

### 6.3 安全初始化

memdsl review policy init 生成合法但禁用自动批准的纯 JSON：

~~~json
{
  "version": "memdsl.policy.v1",
  "default_route": "queue",
  "auto_merge_into": "auto-approved.mem",
  "sample_to_queue_percent": 10,
  "max_auto_approve_per_day": 0,
  "trusted_clients": [],
  "rules": []
}
~~~

JSON 中不得写注释，也不得生成伪装成注释的未知字段。命令在 stdout 解释下一步：为 domain type 添加 auto_approvable capability、配置可信 client、添加精确 kind rule、设置正数日限额，并在部署侧授予 write:auto。

一个完整但仍属 fictional 的示例：

~~~json
{
  "version": "memdsl.policy.v1",
  "default_route": "queue",
  "auto_merge_into": "generated/observations.mem",
  "sample_to_queue_percent": 10,
  "max_auto_approve_per_day": 20,
  "trusted_clients": ["mcp:fictional-collector"],
  "rules": [
    {
      "name": "verified-project-observations",
      "route": "auto_approve",
      "match": {
        "kind": ["example.observation"],
        "scope": ["project:fictional"],
        "client": ["mcp:fictional-collector"],
        "evidence_verifier": ["workspace_file_quote"],
        "force_not": ["hard", "strong"]
      }
    }
  ]
}
~~~

这个示例只有在 example.observation 的 TypeDescriptor 也声明 auto_approvable 时才可能自动批准。

## 7. 路由底线与算法

### 7.1 不可配置安全底线

任一条件成立，effective route 必须是 queue：

1. runtime_role 不是 assertion。
2. lifecycle.status 不是 candidate。
3. TypeDescriptor 不存在或不含 auto_approvable capability。
4. scope 为空或为 global。
5. access_policy 非空。
6. force 为 hard 或 strong。
7. relations 中 supersedes、conflicts_with 或 revision_of 任一非空。
8. validation 有任何 warning。
9. ProposalContext.client_id 为空或不在 policy.trusted_clients。
10. EvidenceVerification.verified 不是 true。
11. verifier、source_digest、quote_digest 或 evidence_digest 缺失，或者 attestation digest 与当前 declaration.evidence 不一致。
12. policy 不存在。
13. 部署未授予 write:auto。
14. policy.max_auto_approve_per_day == 0。

底线只能由未来 major/minor 设计合同修改，policy rule 只能收紧，不能放宽。

### 7.2 RoutingAssessment

路由不得只返回一个字符串。新增完整快照：

~~~python
@dataclass(frozen=True)
class RoutingAssessment:
    decision: RoutingDecision            # auto_approve | queue | no_op
    rule: str
    reason_codes: Tuple[str, ...]
    policy_hash: str
    content_hash: str
    input_snapshot: Mapping[str, object]
    tier: str = ""
    sample_bucket: Optional[int] = None
~~~

RoutingAssessment.as_dict 是 route audit 的规范 policy-core 快照。input_snapshot 至少包含：

- declaration：id、kind、runtime_role、capabilities、status、scope、force、完整非空 relations、has_access_policy、warnings_count 和 content_hash。
- context：序列化键 client 与 evidence；evidence 内含 verified、verifier、source_digest、quote_digest、evidence_digest。它们分别来自 ProposalContext.client_id 与 ProposalContext.evidence_verification，而不是 proposal header。
- policy：version、source hash、auto_approved_today 和 max_auto_approve_per_day。

ReviewStore 的 route audit envelope 在 assessment 之外还必须保存 workspace fingerprint、部署 write:auto 是否授予、最终 effective route，以及对 assessment.as_dict 的 assessment_hash。快照不得保存 evidence.quote 原文、证据文件内容、凭据或任意秘密。assessment_hash 是对规范 assessment JSON 做 sha256。

### 7.3 shadow 运行

policy schema 不增加 mode 字段。shadow 由部署钥匙表达：

- policy 存在且合法；
- write:auto 未授予。

这种情况下编排层先执行一次不含部署阻断项的 policy assess，得到 eligible assessment；再以 write_auto_not_granted 作为 blocking reason 得到 effective queue assessment。route audit 同时保存 eligible_assessment 与 effective assessment，stats 因而可以统计 would-auto-approve 与人工结果。

因此可以先部署 policy 收集 shadow 数据，再显式加入 write:auto，不需要修改策略格式。

### 7.4 评估顺序

规范顺序：

~~~text
load policy
  -> reload workspace and registry
  -> parse exactly one declaration
  -> lint against current workspace
  -> normalize declaration and compute content_hash
  -> deduplicate/no-op check
  -> build host ProposalContext and verify evidence
  -> ReviewPolicy.assess without deployment blocking reasons
       -> hard floor -> first-match rule -> UTC daily limit -> stable sampling
       -> eligible assessment
  -> orchestration deployment-key check
       -> granted: effective assessment = eligible assessment
       -> missing: assess again with write_auto_not_granted blocking reason
  -> persist effective RoutingAssessment
~~~

PolicyError 在 create proposal 前返回。declaration invalid 也不创建 proposal。其余有效提交都必须生成 proposal、propose audit 和 effective route assessment，除非命中 no_op。

## 8. 规范化、去重、抽样与日限额

### 8.1 content_hash

抽样与去重不能使用随机 proposal id。新增确定性的 canonical_declaration_hash：

1. parse source 为一条 RawDeclaration。
2. 取 kind、name、module 和完整 fields。
3. map key 按 Unicode code point 排序。
4. list 保留 DSL 原始顺序。
5. number、bool、null、string 使用稳定 JSON 表示。
6. 不包含空白、注释、proposal header、reason、client、文件路径或行号。
7. 对 UTF-8 规范 JSON 计算完整 sha256。

等价 declaration 只因格式、缩进或字段顺序不同，content_hash 仍必须相同。

### 8.2 no_op

在 ReviewStore 锁内检查 content_hash：

- 若已有相同 content_hash 的 pending proposal，返回 no_op 和 existing proposal id；不创建第二个 proposal。
- 若相同 declaration 已批准且当前 workspace 已包含等价内容，返回 no_op；不重复写入。
- 若已有 rejected proposal，可以重新提交，但抽样结果仍保持稳定。
- no_op 追加轻量 audit，记录 existing proposal id、content_hash 和可信 client_id；不把它计为新 proposal 或自动批准。

这样被抽样回流的 client 不能通过重复提交获得新的随机 id 来绕过人工队列。

### 8.3 稳定抽样

抽样输入固定为：

    sha256(content_hash + ":" + policy_hash)

取前 8 个 hex 转为整数，再对 100 取模。bucket 小于 sample_to_queue_percent 时 route 为 queue，reason 为 sampled_to_queue。

同一声明在同一 policy 下永远得到相同结果；policy 内容变化后允许重新采样，因为风险合同已经变化。

### 8.4 日限额

max_auto_approve_per_day 是 workspace policy 的全局 UTC 日限额。

- count 来源是 audit 中当日实际 auto approve decision，不从目标文件推测。
- 在最终写入前、ReviewStore 锁内重新计数。
- 达到限额后 proposal 保持 pending，effective route 改为 queue，reason 为 daily_limit_reached。
- audit 无法严格解析或计数不确定时 fail closed，不能自动批准。
- v1 不提供 unlimited 值；部署者必须选择有限正整数。

## 9. ReviewStore 集成与并发

### 9.1 新 public orchestration

保留现有 create 和 approve 的兼容行为；自动化只允许通过新 submit 入口：

~~~python
class ReviewStore:
    def submit(
        self,
        workspace_or_paths,
        source: str,
        *,
        reason: str = "",
        client: str = "",
        context: Optional[ProposalContext] = None,
        policy: Optional[ReviewPolicy] = None,
        blocking_reasons: Sequence[str] = (),
        write_auto_granted: Optional[bool] = None,
        workspace_paths: Sequence[str] = (),
    ) -> dict:
        ...
~~~

workspace_or_paths 接受新的 paths 形式，也兼容旧 Workspace + workspace_paths overload；自动路径必须拥有可重新加载的 workspace paths。write_auto_granted 为 None 时按 False 处理。submit 复用现有验证、proposal 文件、原子写入、provenance marker、幂等 decision 和 audit 机制。自动 actor 格式固定为：

    policy:<rule-name>@<policy-hash>

自动 actor 永远不能传 force=True。

create/approve 仍可被人工兼容调用，但它们接收的 Workspace 对象可能已经陈旧；文档和 public API 必须明确，只有 submit 的 workspace_paths 重载路径满足自动批准的并发合同。

ReviewStore 还公开：

- validate_policy_target(policy, paths)：返回已验证、位于 workspace root 内的绝对 .mem 目标。
- workspace_fingerprint(paths, workspace=None)：计算内容级 workspace/schema 指纹。
- audit_entries(strict=True)：严格读取 audit；损坏行抛 AuditLogError，并带 line 信息。

### 9.2 主 workspace root 与目标路径

主 workspace root：

- 第一个 workspace path 是目录时，root 为该目录的 realpath。
- 第一个 workspace path 是文件时，root 为其父目录的 realpath。

auto_merge_into 必须：

1. 是相对路径。
2. 后缀为 .mem。
3. 与 root join 后的 realpath 位于 root 内。
4. 不位于 staging_dir、.memdsl、proposals 或其他内部状态目录内。
5. 不是目录；父目录可以由实现创建。
6. 即使存在 symlink，也不能解析到 root 外。

违反任一项是 PolicyError 或 policy_target_invalid 硬错误，不得改写成普通 queue，也不得写文件。

### 9.3 workspace fingerprint

fingerprint 是内容级 sha256，输入至少包括：

- 所有加载的 .mem 文件的 root-relative 路径与内容 digest。
- memdsl.json。
- registry 实际加载的 schema 文件路径与内容 digest。

只看 mtime/size 不足以作为自动批准证明。

submit 的自动路径：

1. 第一次加载 workspace，验证、计算 fingerprint A、评估并创建 proposal。
2. 准备 approve 时获取 ReviewStore lock。
3. 在锁内从 workspace_paths 重新执行 Workspace.load，计算 fingerprint B。
4. 重新 lint proposal，并重新解析 TypeDescriptor。
5. 重新校验目标路径和当日日限额。
6. 若 A != B，保持 proposal pending，追加 workspace_changed route/decision audit；不自动重试、不 force。
7. 只有 A == B 且重验证仍通过，才调用与现有 approve 共享的 locked/idempotent 写入 helper。

ReviewStore lock 只能串行化 memdsl review writer，不能阻止外部编辑器修改文件；fingerprint 检查是 fail-closed 检测，不声称提供跨所有进程的数据库事务隔离。

### 9.4 decision 顺序

自动批准仍保持：

    target source -> approve audit -> proposal state

新增 route assessment 必须在 approve 前 durable append。崩溃恢复不得重复 source block、propose、route 或 approve 事件。

## 10. 修订、晋升与撤销

ReviewStore 不物理删除已批准 declaration，不创建 Git commit，也不保证一条 proposal 对应一个 Git commit。

宿主可以自行在 approval 后创建 Git commit，也可以按批次提交，但这是可选 adapter 行为，不属于核心正确性或验收依据。

### 10.1 普通 revision proposal

修订自动项必须提交一条新的、schema 合法且 id 不同的 declaration：

~~~mem
example.observation project_phase_confirmed {
  subject: Project.Fictional
  claim: "The project is in implementation."
  scope: project:fictional
  lifecycle { status: active }
  relations {
    revision_of: [example.observation:project_phase_candidate]
    supersedes: [example.observation:project_phase_candidate]
  }
  evidence {
    source: evidence/project-status.txt
    quote: "The project is in implementation."
  }
}
~~~

这也是 candidate -> active 的唯一规范路径：创建新的 active revision，不能直接编辑原 candidate。

### 10.2 retraction proposal

撤销不要求核心新增固定 tombstone type。使用 domain 中任意合适、schema 合法的新 declaration，令 supersedes 指向被撤销项；可同时使用 revision_of 表示审计关系。标准兼容包的 counter_evidence 可作为示例，但核心不硬编码该类型。

~~~mem
counter_evidence project_phase_retracted {
  subject: Project.Fictional
  claim: "The earlier project phase observation is not reliable."
  scope: project:fictional
  lifecycle { status: active }
  relations {
    revision_of: [example.observation:project_phase_candidate]
    supersedes: [example.observation:project_phase_candidate]
  }
  evidence {
    source: evidence/project-status-correction.txt
    quote: "The earlier status report was incorrect."
  }
}
~~~

supersedes、revision_of 和 conflicts_with 都命中 hard floor，因此 revision/retraction proposal 必须进入人工队列。人工 approve 后，现有 superseded_ids 语义使旧 declaration 默认查询不可见，同时保留完整源历史。

### 10.3 异步 flag 不等于撤销

post-review flag 只记录质量结论，不能偷偷改变源记忆。flag 命令必须提示维护者继续提交 superseding proposal。在该 proposal 人工批准前，原自动项仍按 candidate/PROVISIONAL 语义服务。

## 11. 审计合同

### 11.1 事件

audit.log 新增或扩展以下 action：

| action | 含义 |
| --- | --- |
| propose | 新 proposal durable 落盘 |
| route | 保存完整 RoutingAssessment snapshot |
| approve | 人工或 policy actor 批准 |
| reject | 人工拒绝 |
| no_op | 重复提交未创建新 proposal |
| post_review | 人工对自动项给出 confirm 或 flag |
| digest | digest 游标事件 |

route 事件必须包含完整 assessment 对象，不能只存 rule/policy_hash。approve 可以保存 assessment_hash 引用 route snapshot。

### 11.2 post_review

post_review 结构至少包含：

~~~json
{
  "action": "post_review",
  "proposal_id": "p-...",
  "by": "human",
  "verdict": "confirm",
  "reason": "sample checked against source",
  "assessment_hash": "..."
}
~~~

verdict 只允许 confirm 或 flag。同一 proposal 的多次 post_review 事件全部保留，stats 使用最新 verdict，同时报告历史变更次数。

### 11.3 audit 解析

策略限额、digest 和 stats 使用 audit 作为事实源时必须严格解析：

- malformed JSONL 不能静默跳过并给出错误统计。
- CLI 返回非零并指出损坏行号。
- 自动批准在 audit 不可可靠读取时 queue/fail closed。

## 12. CLI 合同

现有 review list/show/approve/reject 保留。review help 不再写 human-only，而应写 governed review queue and policy routing。

新增：

~~~text
memdsl review policy init PATH... [--staging DIR] [--force]
memdsl review policy show PATH... [--staging DIR] [--json]
memdsl review policy validate PATH... [--staging DIR]

memdsl review digest PATH... [--staging DIR] [--since ISO] [--json]
memdsl review stats PATH... [--staging DIR] [--json]

memdsl review audit PATH... PROPOSAL_ID
  --verdict confirm|flag
  [--reason TEXT]
  [--staging DIR]
~~~

行为：

- policy init 写 §6.3 的纯 JSON。文件已存在时拒绝，除非 --force。
- policy show 解析后显示 source_hash、安全禁用原因、trusted clients、rules 和目标路径。
- policy validate 同时绑定当前 registry，检查 rule kind 是否存在，并检查 auto_merge_into 边界；错误退出码 1。
- digest 列出 pending、sampled queue、未 post-review 的 auto approvals、最新 flag 以及需要 revision/retraction 的项。
- 每次无 --since 的 digest 成功运行后追加 digest audit，下一次以最近 digest.ts 为默认游标。
- stats 完全使用 route assessment、decision 和 post_review snapshots；不依赖当前 TypeRegistry 解释历史 proposal。
- review audit 只允许作用于 policy auto-approved proposal；追加 post_review，不改 proposal status 或 .mem。
- flag 输出明确 next action：创建新的 schema-valid declaration proposal，以 supersedes 指向被 flag 的 declaration，并人工 approve。

CLI 人工 approve 的 --force 兼容保留，但 policy actor 和自动路径绝不能使用它。

## 13. MCP 合同

### 13.1 scopes 与宿主身份

新增：

    WRITE_AUTO_SCOPE = "write:auto"

它不加入 DEFAULT_SCOPES。

自动批准需要：

1. 原有 write:candidate。
2. 部署配置授予 write:auto。
3. policy.json 存在且合法。
4. policy 与 type 双重 opt-in。
5. ProposalContext.client_id 来自 MemdslMCPService 构造配置，不来自 tool 参数。
6. workspace_file_quote 或注入 verifier 成功验证 evidence。

MemdslMCPService 默认使用 workspace_file_quote。进程内宿主可以注入自定义 verifier；无 verifier 或 verifier 异常时返回 unverified 并 queue，不允许把异常当验证成功。

### 13.2 policy 加载

memory_propose 与 status 只要发现 policy.json 存在就必须解析：

- 非法 policy 返回 policy_invalid，即使部署没有 write:auto。
- policy 不存在是正常的全部人审状态。
- 合法 policy 但无 write:auto 时执行 shadow assessment 并 queue。

### 13.3 propose payload v2

schema_version 升为 memdsl.mcp.propose.v2。

成功 payload 必须包含：

| 字段 | 值 |
| --- | --- |
| route | auto_approved、queued 或 no_op |
| proposal_id | 新建或 no_op 命中的 proposal id |
| declaration_id | declaration id |
| rule | route rule |
| reason_codes | 稳定 code 列表 |
| assessment_hash | route snapshot hash |
| merged_into | 仅 auto_approved |
| eligible_route | shadow 时可为 auto_approve |
| warnings | validation warnings |

policy_invalid payload：

~~~json
{
  "ok": false,
  "schema_version": "memdsl.mcp.propose.v2",
  "status": "policy_invalid",
  "error": "policy_invalid",
  "details": []
}
~~~

自动批准 boundary：

    This proposal was auto-approved as candidate-status provisional memory.
    It has not been human-confirmed. It never becomes MUST, SHOULD, CONTEXT,
    MISSING, or an enforceable compliance constraint while non-active.
    A human may later confirm or flag it and may supersede it through another
    reviewed declaration proposal.

queued boundary 沿用“pending proposal is not memory”的现有语义，并解释首个 reason code。no_op boundary 必须说明没有创建第二条记忆。

### 13.4 status 与 review list

status payload 增加：

- policy_present
- policy_valid
- policy_hash
- write_auto_granted
- automation_effective
- auto_approvals_today
- max_auto_approve_per_day
- unaudited_auto_approvals

review list 的每项增加 route、rule、assessment_hash、content_hash、post_review_verdict。模块 docstring、FastMCP tool docstring 与 server instructions 必须从“所有写入必须人审”改成准确的分级表述。

## 14. stats 与 digest 的可重放性

stats 不得用当前 registry 重新解释历史 kind。分组轴来自 route assessment snapshot：

- kind
- runtime_role
- rule
- policy_hash
- trusted client
- evidence verifier

每组至少输出：

- proposed
- queued
- would_auto_approve_shadow
- sampled_to_queue
- sampled_human_approved
- sampled_human_rejected
- auto_approved
- post_review_confirmed
- post_review_flagged
- no_op
- confirmation_rate
- flag_rate

0.5.x 的 legacy proposal 没有 route snapshot，统一进入 legacy_unknown 分组；不得拿当前 registry 猜测它当时的 runtime_role。

digest 的“需要关注”排序：

1. post-review flag 但尚无已批准 superseding declaration。
2. 未 post-review 的 auto approval。
3. sampled queue。
4. 其他 pending。

## 15. 代码与文档变更清单

实现完成必须逐项更新：

| 文件 | 变更 |
| --- | --- |
| [src/memdsl/policy.py](../src/memdsl/policy.py) | PolicyError、ProposalContext、EvidenceVerification、ReviewPolicy、PolicyRule、RoutingAssessment、load/assess、canonical hash |
| [src/memdsl/schema.py](../src/memdsl/schema.py) | 识别并发现 auto_approvable capability；schema 校验保持通用 |
| [src/memdsl/query.py](../src/memdsl/query.py) | additive PROVISIONAL 层、active-only semantic layers、显式状态渲染 |
| [src/memdsl/compliance.py](../src/memdsl/compliance.py) | 只执行 active constraint |
| [src/memdsl/review.py](../src/memdsl/review.py) | submit、去重、route snapshot、日限额、post_review、严格 audit、重载与 fingerprint |
| [src/memdsl/cli.py](../src/memdsl/cli.py) | policy init/show/validate、digest、stats、audit |
| [src/memdsl/mcp_service.py](../src/memdsl/mcp_service.py) | write:auto、可信 context、workspace_file_quote、payload v2、status |
| [src/memdsl/mcp_server.py](../src/memdsl/mcp_server.py) | tool 文案、scope 与宿主配置 |
| [src/memdsl/__init__.py](../src/memdsl/__init__.py) | public exports 与 0.6.0 版本 |
| [docs/SPEC.md](SPEC.md) | §7 PROVISIONAL、§10 分级审核、append-only 撤销语义 |
| [docs/PUBLIC_API.md](PUBLIC_API.md) | 新 public dataclass、函数、ReviewStore 方法与 payload |
| [docs/UPGRADING.md](UPGRADING.md) | candidate 行为变化、EvidencePack additive 字段、propose v2 |
| [README.md](../README.md) | governed tiered review 的最小使用示例 |
| [CHANGELOG.md](../CHANGELOG.md) | 0.6.0 条目 |
| [pyproject.toml](../pyproject.toml) | 版本 0.6.0 |
| [.github/workflows/ci.yml](../.github/workflows/ci.yml) | wheel 版本断言 0.6.0 |

所有测试、示例和 policy 使用 fictional 身份与合成 evidence。构建产物不得包含真实 workspace、proposal、audit、绝对机器路径或私有 schema。

## 16. 测试合同

### 16.1 lifecycle 与查询

必须覆盖：

- candidate assertion/guidance/question/constraint 都不进入 active semantic layers。
- 可服务、searchable 的非 active 命中只进入 PROVISIONAL。
- candidate constraint 不进 MUST，不触发 compliance。
- active constraint 恢复 MUST/compliance。
- JSON provisional 含 score、matched_terms、status、runtime_role、lifecycle。
- text 固定渲染 PROVISIONAL，并显式状态。
- memory map 区分 provisional 与 active。
- candidate symbol alias 不能进入 resolved_subjects/matched_aliases，也不能间接激活 MUST；同一 symbol 改为 active 后恢复解析。
- candidate assertion/guidance/question 的 subject、scope 或 id 命中不能作为 active constraint 的 MUST relevance 信号；MUST relevance 只能从 active hits 计算。

### 16.2 policy schema 与底线

表驱动覆盖：

- 只有 assertion + candidate + explicit non-global scope + zero warnings 有资格继续。
- question、guidance、constraint、symbol、unknown 永远 queue。
- 类型缺 auto_approvable capability 时 queue。
- rule 缺 kind 为 PolicyError。
- access_policy、hard/strong force、supersedes、revision_of、conflicts_with 各自 queue。
- untrusted/empty client queue。
- evidence unverified 或 verifier/digest 缺失 queue。
- policy missing queue；policy invalid hard error。
- unknown top-level/match key、bad JSON、bad version、default auto、非法路径、重复 client/rule 都 PolicyError。

### 16.3 evidence verifier

覆盖：

- root 内普通 UTF-8 文件 + exact quote verified。
- quote 不匹配 unverified。
- source 缺失、quote 缺失、目录、非 UTF-8、无法读取 unverified。
- .. 越界、绝对外部路径、symlink 越界 unverified。
- audit 只保存 digest，不保存 quote/file content。
- MCP tool 无法提交 attestation 字段改变结果。

### 16.4 去重、抽样与限额

覆盖：

- 字段顺序/空白不同得到相同 content_hash。
- 相同 pending/approved 返回 no_op，不创建第二文件。
- rejected 重提仍得到相同 sample bucket。
- sampling 输入是 content_hash + policy_hash，不是 proposal id。
- percent 0/100 边界。
- 同一 policy 下重试不能绕过 sample。
- 日限额 0 禁用；达到正数限额后 queue。
- UTC 跨日重新计数。
- malformed audit 阻止 auto approve。

### 16.5 ReviewStore 并发与路径

覆盖：

- submit 无 policy 与旧 create 的 pending 语义兼容。
- 自动路径包含 propose、route、approve，且 route 在 approve 前。
- target 写入、audit、proposal state 的崩溃恢复幂等。
- route 后 workspace 内容变化导致 pending/workspace_changed。
- registry/schema 文件变化也改变 fingerprint。
- auto_merge_into 的绝对路径、非 .mem、..、.memdsl、symlink escape 全部拒绝。
- policy actor 永不 force。

### 16.6 revision/retraction

覆盖：

- 带 supersedes/revision_of 的 proposal 即使规则匹配也 queue。
- 人工 approve superseding proposal 后，旧 candidate 默认查询不可见。
- 新 active revision 进入相应 active semantic layer。
- 原 declaration 仍存在于源文件和 audit，未被物理删除。

### 16.7 CLI/MCP/统计

覆盖：

- policy init 输出可 json.load 的无注释 JSON，且默认禁用。
- show/validate 对 invalid policy 非零退出。
- 有 policy、无 write:auto 时 queued + eligible auto shadow snapshot。
- write:auto + trusted context + verified evidence 才 auto_approved。
- propose v2 的 auto/queue/no_op/policy_invalid payload。
- review audit confirm/flag 只追加事件，不修改 .mem。
- flag 给出 superseding proposal next action。
- stats 在删除/修改当前 type registry 后仍按历史 snapshot 得到相同分组。
- sampled 人工决定与 post-review verdict 可重建。

## 17. 实施里程碑

每个里程碑结束都必须运行相关定向测试；M6 前运行全量 gate。

1. M1 — lifecycle 安全修复
   PROVISIONAL、active-only semantic layers、candidate constraint compliance 修复。

2. M2 — policy 与信任上下文
   policy.py、auto_approvable capability、ProposalContext、workspace_file_quote、policy loader。

3. M3 — ReviewStore 自动路由
   normalization/no_op、assessment snapshot、sampling、daily limit、target boundary、reload/fingerprint。

4. M4 — 人工反馈与可观测性
   post_review、review audit、digest、stats、strict audit replay。

5. M5 — MCP 与 CLI
   write:auto、shadow、payload v2、status/list、policy commands。

6. M6 — 文档、兼容与发布
   §15 全清单、版本 0.6.0、全量验证、构建产物检查、隔离 wheel smoke、提交、推送和 PyPI 发布。

## 18. 验收标准

0.6.0 只有在以下证据全部成立时才算完成：

1. 默认安全
   无 policy 或默认 init policy 时，任何 proposal 都不会自动批准；0.5.1 用户除 PROVISIONAL/candidate 安全修复外行为兼容。

2. 信任边界
   修改 proposal source/header 中的 client、evidence 或 status 不能伪造 ProposalContext；MCP tool 无 attestation 参数。

3. 唯一自动通道
   一个 fictional custom assertion type 同时声明 auto_approvable，policy 精确匹配 kind/trusted client/verifier，proposal 为 candidate、窄 scope、零 warning、workspace_file_quote 验证成功、write:auto 已授予且未超限时，memory_propose 返回 auto_approved。

4. 高风险不可绕过
   同一策略下，question、guidance、constraint、symbol、unknown、active、global、hard/strong、access_policy、supersedes、revision_of、conflicts_with、warning 或 unverified evidence 全部 queue。

5. lifecycle 安全
   自动 candidate 只在 PROVISIONAL 可见，不进入 MUST、SHOULD、CONTEXT、MISSING 或 compliance。

6. 并发与路径
   审批前 workspace/schema 变化会阻止自动写入；自动目标被限制在主 workspace root，内置证据源被限制在调用方显式提供的 workspace roots 内。

7. 防重试绕过
   等价 proposal 产生相同 content_hash 和 sample bucket；重复 pending/approved 返回 no_op；日限额有效。

8. 完整审计
   每条有效新 proposal 有 propose + route；每条 auto approval 有 approve；route 保存完整 assessment snapshot；audit 损坏时不会自动批准或输出静默少算的 stats。

9. 人工质量闭环
   digest 能找到未复核自动项；review audit 能追加 confirm/flag；flag 不直接改 source；人工批准 superseding proposal 后旧项默认不可查询。

10. 可重放 stats
    修改或删除当前 registry 后，历史 policy/rule/client/kind/runtime_role 分组和 post-review 指标保持不变。

11. 发布证明
    项目 verify skill 要求的测试、CLI、MCP 和 gated write 验证全绿；wheel/sdist 内容检查无私有数据；twine check 通过；新建 repo 外 venv 从 wheel 安装并 smoke；Git 提交和远端 ref 可验证；PyPI 0.6.0 可安装且 import path 来自 site-packages。

## 19. 风险与后续版本

- 语义冲突：v1 只做确定性冲突/关系底线，不判断两个 assertion 的自然语言矛盾。未来可增加独立 reviewer，但结果只能收紧。
- 刷量：v1 有 workspace 日限额和稳定 no_op；未来可增加 per-client/per-rule 配额。
- post-review 延迟：flag 在 superseding proposal 批准前不撤销内容。宿主可选择临时隐藏，但这属于显式 host policy，不能由核心静默执行。
- registry 演化：历史 stats 依赖 assessment snapshot；未来 schema 变化不能回写旧 snapshot。
- Git 集成：宿主可实现 approval hook 或 commit adapter，但核心审计、撤销和正确性不能依赖 Git。
- 更广自动化：只有 shadow、sample 和 post-review 数据证明低风险后，未来版本才可讨论 question 或 guidance；0.6.x policy 不得打开这些角色。
