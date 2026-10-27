# 业务验收与参赛要求核对

> **Superseded requirements note — 27 October 2026:** This is a historical test report. Its statement below that Nightshift is not an explicit requirement is outdated. The team's supplied Submission Requirements require Nightshift as the primary AI provider plus a working Meterless Engine. Use [the current English checklist](submission/REQUIREMENTS.md). The historical direct-OpenAI results remain valid only for their recorded path.

核对日期：2026-10-26（America/Chicago）。基线：GitHub main `36acec2`。已执行 fetch / fast-forward 检查，另一远端分支 kerby 落后于 main。应用运行代码与工作目录一致，本次增加可重复验收脚本并更新文档。

## 本次真实服务验收

连接路径：FinTrace → Zetaris → PostgreSQL；OpenAI 选择取证工具，独立规则校验器形成财务结论。数据全部为已注明来源的合成测试数据。

| 场景 | 预期与实际结果 | live 运行次数 |
|---|---|---:|
| 正常付款 | no_anomaly_supported / NO_FAILURE | 3 |
| 重复付款 | anomaly_supported / F06 | 3 |
| 付款使用已失效供应商信息 | anomaly_supported / F11 | 1 |
| 付款未到银行结算，具有处理器证据 | anomaly_supported / F12 | 1 |
| 结算费用缺少对应分录 | anomaly_supported / F14 | 1 |
| 失败事件在观察截止日之后 | insufficient_evidence / EVIDENCE_GAP | 1 |
| 费用分录在观察截止日之后 | anomaly_supported / F14 | 1 |
| 目标记录在大量背景记录之后 | no_anomaly_supported / NO_FAILURE | 1 |
| 银行来源覆盖不完整 | insufficient_evidence / EVIDENCE_GAP | 3 |

15/15 符合预期；引用均可解析，80 次应用取证工具调用均成功。65 次模型 HTTP 请求成功，报告 109989 tokens，不包括先行 preflight。配置模型为 gpt-5.4-mini，返回模型为 gpt-5.4-mini-2026-03-17。原始调查记录及请求标识仅保留在忽略目录，不随源码发布。

离线同一矩阵也通过 15/15。类型检查、82 项单元/集成测试、生产构建、29 项浏览器回归通过。测试中的模拟模型结果与上述 live 结果分开解读。九个场景及其重复运行不是 15 个独立业务样本，不证明真实客户准确率或模型优于规则。

## 数据是否必须真实

本次展开读取的[正式活动规则](https://hackathon.genai.works/event/open-agent-hackathon-2026#rules)没有要求真实客户交易数据。项目已有 FAQ 资料要求合法、可获取的数据，并提醒避免私人、专有、受限数据及真实个人数据。结合这些材料，合成数据适合可复现测试和演示；必须明确标注来源及限制。此判断不表示主办方对本项目作过个别资格确认。

比赛强调真实问题和用户价值。真实业务数据不是当前发现的准入门槛；财务人员反馈、任务耗时比较和独立评估仍可加强 Impact 的证据。不要为赶交付引入未经授权的财务数据。

## Sponsor 要求与项目位置

当前公开正式规则第 5.1 条：Zetaris、Meterless 必须集成，Cursor 开发为可选；第 5.2 条：NVIDIA 在对项目、工作流或用例有贡献时使用。第 5.3 条允许任意模型及闭源 API。旧材料中 Cursor 必须使用的说法已过时。

| 工具 | 项目实际使用 | 仍需展示或补充 |
|---|---|---|
| Zetaris | live 调查实际经其查询 PostgreSQL 只读来源视图 | 演示查询、来源和证据链；目前是一套 PostgreSQL 上的多表，不是多个独立系统的实测联邦接入 |
| Meterless H-MEM | 已接入本地参考引擎，保存人工批准的调查经验、来源和审计记录，后续调查召回 | 演示批准 → 新调查召回 → 仍由事实证据决定结果；不要把 mock embedding 描述为生产语义检索 |
| Meterless Runtime / Nightshift | 有 provider 适配，未做 live 验证；当前推理使用 OpenAI | 公开规则及用户提供的 Sponsor overview 没有明确要求同时使用 Runtime；不把它自行增加为硬性门槛 |
| NVIDIA / Nemotron | 有适配器，未完成 live 验证 | 有实际价值或争取 Best use of NVIDIA Nemotron 专项时再接入，并保留调用与对比证据 |
| Cursor | 本次工作由 Codex 完成；不据此声称 Cursor 开发 | 当前为可选；如果团队实际使用过，准确说明做了什么 |

用户提供的 Meterless Sponsor overview 明确列出 open-source engines、模板提示词和 GitHub 入口，并要求说明使用哪个 engine、位于哪里；它没有要求所有 engines 或 Runtime 全部接入。它与 H-MEM 的使用方向一致，但最终资格由主办方判定。

## H-MEM 是做什么的

H-MEM 是 hierarchical memory（分层记忆）。[官方引擎说明](https://github.com/Meterless/Meterless/tree/main/engines/hmem)把它定位为带来源与审计的 Agent 记忆系统；[Runtime 架构](https://github.com/Meterless/Meterless/blob/main/docs/architecture/stack-overview.md)则是模型服务、任务执行和调度的另一层。

本项目流程：人工接受调查，并明确勾选批准经验 → `MemoryService.approve()` 保存原文、来源调查及 provenance → 后续调查 `recall()` 取最多五条相关经验 → 规划器将其作为上下文选择工具。供应商账户和付款状态仍重新取证，记忆不能覆盖校验规则。

例如保存“先检查供应商变更历史，再复核付款分录”，供下一次调查参考。现有测试验证中文召回、重启持久化、namespace 隔离，以及 fixture 下记忆改变工具顺序而不改变独立财务验证。当前 15 次 live 验收未单独做有无记忆的效果对照。

实现边界：使用参考引擎的确定性 hash mock embedding，并补充本地中英关键词召回；未接入生产语义 embedding、自动 dreaming 或 sleep cycle。不能将完整 H-MEM 官方能力都宣称为本项目已启用。

## 用户提供的 Zetaris Quick-start 目录

以下是本次提供资料的适用性判断，不是本机接入结果；目录的 Verified 指作者实例上的验证，不能直接算作 FinTrace 的运行证据。这些目录没有要求参赛者接入全部列出的数据源。

| 资料 | 当前状态 | 对 FinTrace 的作用与限制 |
|---|---|---|
| Parquet / CSV：NOAA、PUDL、Foursquare、Overture、Ookla、GBIF、Blockchain | 仅参考，未接入 | 可用于连接器练习；天气、地图、物种等不能覆盖付款调查的关键证据缺口，链上交易也不能替代本项目的发票、AP 付款及银行结算链路 |
| REST：EDGAR、company_dns SIC/NACE/日本行业分类 | 仅参考，未接入 | 可能补充企业身份和行业背景；上市公司公开财报及行业编码不提供逐笔供应商付款、银行退回、账户变更和内部账务事实 |
| REST：食品、NASA、宏观统计等 | 仅参考，未接入 | 不支持当前四类财务异常的关键判断，不建议为增加数据源数量而接入 |
| USL：sic_usl、sic_edgar_usl | 仅参考，未接入 | 可参考关系模型、外键与数据质量检查；本项目当前使用受限 SQL 读取来源视图，尚未接入 USL/DQ |

USL 示例中最相关的设计启示是：INNER JOIN 可能隐藏未匹配记录，外键检查能发现关联缺口；这可用于未来增强来源质量检查。用户提供的目录记录了 IBM 行业编码缺失示例，但本次没有在本机重跑它。

目录中另有 Known to fail、deprecated、许可未确认和延后 materialization 的项目。不要将这些标成可直接使用或已验证。本次不下载这些额外数据，不对目录中的许可判断作独立法律确认。

## 按评分还应优先补什么

官方评分：Impact 30、Technical 20、Innovation 15、Demo 15、Product & UX 10、Sponsor Tech 10。

1. Impact：说明财务人员面对的具体调查任务、输出如何使用；量化人工对照或收集用户反馈，避免没有依据的节省时间声明。
2. Technical：保留本次 live 验收，补完整保留集及同模型一次性分析对比；正常、异常、证据不足和故障边界都可复现。
3. Innovation：证明受限取证、验证反馈、来源覆盖和审核记忆的实际价值；如实称为单一编排器加模型规划和独立规则，不包装成多个自主 Agent。
4. Demo / UX：录制 1–4 分钟主流程，展示一次异常、一次拒绝过度结论、一次经验批准及召回，并导出可审核结果。
5. Sponsor Tech：说明 Zetaris 和 H-MEM 在核心链路中完成了什么，而不只展示 logo 或配置。无需为了工具数量牺牲稳定性。

提交仍需要视频、slides、源代码与 README、Sponsor 使用说明，并披露预先存在的组件。Sponsor overview 提到 metadata.json，但本次未获得官方字段 schema，不据此杜撰提交格式。当前公开截止为 2026-10-27 23:45 UTC，即 America/Chicago 2026-10-27 18:45。

## 复现

```powershell
$env:FINTRACE_MODE = "fixture"
npm run verify:business -- --repeat=3
```

配置好本机 `.env.local`、启动 PostgreSQL 和 Zetaris 后：

```powershell
$env:FINTRACE_MODE = "live"
npm run preflight -- --live
npm run verify:business -- --connect --repeat=3
```

live 会产生真实模型调用费用，并把新的调查保存在配置的数据库中。脚本使用新的 namespace，避免复用旧结果；输出位于 `.local/business-cases-*`。不要公开本机配置和原始运行轨迹。
