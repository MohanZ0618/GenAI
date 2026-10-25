# 当前 Agent 架构与代码定位

本文依据当前源码整理；总图与循环图见 [README](../README.md)。旧的 `ARCHITECTURE_REVIEW.zh-CN.md` 是修复前审核快照，旧行号与行为不应用作现状说明。

## 从用户点击到调查结果

1. [App.tsx](../apps/web/src/App.tsx) 通过 [api.ts](../apps/web/src/api.ts) 请求后端。批量界面和总览使用 [investigationQueue.ts](../apps/web/src/investigationQueue.ts) 与 [ResultsOverview.tsx](../apps/web/src/ResultsOverview.tsx)。
2. [server.ts](../apps/api/src/server.ts) 的 `POST /api/investigations` 校验输入，调用 `InvestigationService.start()`。`POST /api/investigations/batch` 为批量入口。
3. [service.ts](../apps/api/src/service.ts) 的 `startOrReuse()` 依数据集、付款、模式和记忆命名空间复用运行；否则持久化 queued 记录。`drain()` 允许同一进程最多 3 个并发调查。
4. `execute()` 召回审批记忆，调用 `assess()` 获取缺少的工具。首轮固定 `overview`；后续由真实模型或 fixture 逻辑选择工具。
5. [context.ts](../apps/api/src/context.ts) 的 `planningEvidence()` 结合 [observation.ts](../apps/api/src/observation.ts)，选择相关记录、过滤观察截止时间后的证据、应用字段白名单和 24 KiB 证据预算。预算针对 evidence 部分，不是整个模型请求。
6. [model.ts](../apps/api/src/integrations/model.ts) 的 `createModelProvider().next()` 发送系统提示词及 JSON 上下文。`requestJson()` 实际调用配置端点的 `/chat/completions`，解析结构化 JSON，并用 Zod 校验。
7. [evidence.ts](../apps/api/src/evidence.ts) 的 `retrieve()` 按固定工具映射读取快照或调用 Zetaris。证据携带表名、记录 ID、查询 ID 和数据版本。
8. [verifier.ts](../apps/api/src/verifier.ts) 的 `assess()` 反馈缺口；循环结束后产生最终结果。编排器检查发现引用是否均能解析，并保存运行轨迹。
9. review 路由接受人工审核。只有接受审核、明确请求批准记忆并提供内容时，才调用 [memory.ts](../apps/api/src/integrations/memory.ts) 写入经验。`needs_changes` 只记录意见，不自动启动修订循环。

## 模型真正收到和返回的内容

| 输入字段 | 内容 |
|---|---|
| `paymentId` | 当前调查付款 ID，工具不能任意更改目标 |
| `context.verification` | 校验器当前反馈 |
| `context.availableTools` | 校验器当前指出缺少的工具 |
| `context.evidence` | 经相关性、时间、字段和大小限制后的记录 |
| `context.observationCutoff` | 数据集观察截止时间 |
| `context.contextCoverage` | 预算省略条数、未来记录排除条数 |
| `history` | 最近 10 条运行事件 |
| `memories` | 最多 5 条已批准经验 |

输出格式示例（非真实模型记录）：

```json
{"tool":"settlements","reason":"Inspect bank settlement evidence before evaluating the payment.","finish":false}
```

或 `{"tool":null,"reason":"Stop investigation.","finish":true}`。

系统提示词位于 `createModelProvider().next()`：限定六个工具，把来源记录和记忆视为不可信数据，要求补齐证据、避免重复、禁止裁定财务真相或输出 SQL。应用另行验证结构并拒绝重复工具。`availableTools` 没有实现为动态枚举，因此它是规划提示；实际硬权限边界是六种固定工具。

`onePassBaseline()` 是 [cli.ts](../apps/api/src/cli.ts) 评估路径的独立一次性模型基线，不是网页调查的最终裁判。非 fixture 评估可能额外产生模型费用。

## 外部 API 边界

| 调用方 | 目标 | 何时发生 |
|---|---|---|
| 浏览器 `api.ts` | 同源 `/api/*` | 页面操作、数据与调查请求 |
| 浏览器 EventSource | `/api/investigations/:id/events` | 实时事件流 |
| `model.ts::requestJson()` | 所选模型提供方 `/chat/completions` | local-model/live 规划、显式模型预检/评估 |
| `evidence.ts` → `zetaris.ts::queryZetaris()` | Zetaris HTTP 查询接口 | live 调查取证 |
| `store.ts::PostgresStore` | PostgreSQL，SQL 协议 | live 导入、列表和状态存取 |
| `memory.ts` → vendored H-MEM | 本地文件 | 召回与人工批准经验；无远程 embedding API |

模型密钥仅在后端读取。

## 可靠性与当前限制

- 6 轮循环包含固定首轮；最多 5 次逻辑模型规划。每次逻辑请求最多 2 次 HTTP 尝试，重试会影响费用。
- 执行开始后 5 分钟总时限，排队时间不在此预算内。超时、取消、接口错误保留轨迹，设为 failed/cancelled，清空财务 outcome 和动作。
- 查询槽位按表数量计数，不是工具次数；六个工具共读取 8 张表。live 每表最多验证 1000 行，并核对快照哈希。工具读取整个 dataset 的表，相关付款记录在后续上下文/校验层筛选。
- 队列在进程内；持久运行记录不等于持久消息队列。重启把未完成运行标为 failed，不自动续跑。
- `completed` 是技术状态，`outcome` 是财务判断，`review` 是人工审核状态，三者分别存储。
- 记忆是审批经验复用，不是模型训练或自动自我改进。每次仍需重新读取当前证据。
- 上游 RAG、GraphRAG 和 classical-ML 模块未接入本应用执行链。系统未证明 Agent 优于固定规则。
