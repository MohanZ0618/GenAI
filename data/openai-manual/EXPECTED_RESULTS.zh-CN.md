# OpenAI 网页人工验收：导入什么、点击什么、应该看到什么

本目录是专门构造的合成验收数据。预期答案只在本文和验证脚本中，不在导入包中。八例已完成离线与模拟 OpenAI 验证；另已使用你的配置完成一次真实 OpenAI 连通检查及 NORMAL 调查（四次 HTTP 请求，结果正常）。这是历史本地验证摘要；原始 `live-smoke.json` 不随源码发布。其余七例仍需真实模型人工验收。

## 1. 先启动

项目已经设置为 `FINTRACE_MODE=local-model`、`MODEL_PROVIDER=openai`，保留原来的 Key、模型和存储路径。Key 只放在本机 `.env.local`，不要填进导入文件或浏览器。

在项目根目录运行：

```powershell
npm run build
npm run dev
```

新电脑先运行 `npm ci`。打开 [FinTrace 本地网页](http://localhost:4310)。已有服务需先停止再启动，配置和构建才会生效。

**页面预期：** 顶部显示 **OpenAI + local data**。数据来自本地快照，不要求 PostgreSQL、Docker 或 Zetaris。集成状态中的 configured 只代表配置存在，不保证已经连通。

可选：`npm run preflight` 只检查配置；`npm run preflight -- --live` 会实际调用模型，消耗 API 用量。后一条成功应显示 `ok: true` 与模型 `responded`。本轮已通过一次真实连通检查，你无需为了开始手测重复执行。

## 2. 导入主包，先核对 Cases

只上传 **01-main-bundle.json**。它已经装入 manifest 和全部九张 CSV，不要同时上传另外三个包、本文或 validation.json。

1. 左侧 **Datasets** → **Import dataset**。
2. **Browse files / Choose dataset files**，选择本目录 `01-main-bundle.json`。
3. 点 **Validate & import**。
4. 弹窗关闭，数据集列表出现 **FinTrace OpenAI manual - 8 cases**。
5. 左侧 **Case inbox**，在 **Active dataset** 选中这个数据集。
6. 点 **All cases**，清空 **Search cases**。列表应恰好有 **8 个案例**。

包内包含 120 笔背景付款及其关联记录，也包含重复付款的另一笔付款。这些是取证素材，不应额外出现在待调查列表。若看到别的案例，先确认没有选择 All review packets。

## 3. 每一例都这样操作

在 **Search cases** 输入下面的完整付款编号，选中该行，点 **Start investigation**。等待生命周期从 Queued/Running 变为 **Completed**。

然后按顺序核对：

1. **Findings**：结果横幅、Finding 标题、金额和引用。
2. 点 Finding 或证据编号：在右侧 **Record detail** 看字段，切 **Provenance** 看来源表、版本和 Query ID。
3. **Validation**：看 Passed、Failed、Unknown 检查。财务异常的检查为 Failed 是预期；它与整个调查的 Failed 不同。
4. **Activity log**：看 **Model API requests**、**Evidence queries**、**Approved memories** 和事件时间线。
5. 返回 **Case inbox**，清空搜索，再运行下一例。

成功的真实模型调查应有 `openai / 你的模型名` 和实际 HTTP 请求记录。Fixture 显示“No model API calls”；旧调查显示未记录轨迹，不能当作这次真实调用证据。工具调用顺序、解释措辞、耗时和 token 数允许不同；业务分类、金额和证据依据应与下表一致。

## 4. 八个主案例的预期

| 勾选 | Payment ID / 页面金额 | Findings 预期 | Validation 与证据核对 |
|---|---|---|---|
| [ ] | PAY_DEMO_NORMAL / USD 600 | **No anomaly supported**；**The evidence supports normal processing** | 发票 600、付款 600、银行 600；Payment journal is balanced 为 Passed |
| [ ] | PAY_DEMO_DUP / USD 1000 | **Anomaly supported by evidence**；**The invoice was paid more than once**；F06，多付 **USD 1000** | 同一张 1000 发票，对应 PAY_DEMO_DUP 与 PAY_DEMO_DUP_OTHER 两笔 1000，银行两笔已结算；Successful allocations do not exceed the obligation 为 Failed |
| [ ] | PAY_DEMO_STALE / USD 900 | **Anomaly supported by evidence**；**Superseded vendor instructions caused a return**；F11 | 供应商 8/25 变更账户；9/7 付款仍用旧 token；银行 returned；processor_return_received 事件在截止日前；Effective vendor instructions used 为 Failed |
| [ ] | PAY_DEMO_MISSING / USD 800 | **Anomaly supported by evidence**；**Payment did not reach bank settlement**；F12 | 银行无匹配，已超过 10 个工作日；付款分录平衡；payment_file_not_transmitted 事件在截止日前；不能只有“没找到银行记录”而没有处理器依据 |
| [ ] | PAY_DEMO_FEE / USD 1200 | **Anomaly supported by evidence**；**Settlement fee has no supporting journal**；F14，差额 **USD 20** | 银行 1180；net_settlement_received 事件；没有截止日前已入账的 20 元费用分录；Settlement difference has balanced fee accounting 为 Failed |
| [ ] | PAY_DEMO_FUTURE_EVENT / USD 700 | **More evidence is needed**；**The available evidence does not establish a cause**；EVIDENCE_GAP；**不得输出已证实 F12** | 传输失败事件在 **2026-11-01**，超过 **2026-10-22** 截止日；Validation 显示 Future evidence excluded from the assessment；原始事件仍可在审计证据中查看 |
| [ ] | PAY_DEMO_FUTURE_FEE / USD 1200 | **Anomaly supported by evidence**；F14，差额 **USD 20**；不得误判为正常 | 20 元费用分录到 **2026-11-01** 才补记，不能解释 10/22 截止日前的缺口；Validation 应显示排除了未来记录 |
| [ ] | PAY_DEMO_CONTEXT_TAIL / USD 350 | **No anomaly supported**；正常处理 | 目标在超过 100 条背景记录后面，仍能找到付款、发票、银行和分录；Activity log 的 Model context 显示发送相关记录；不发送背景付款 |

所有案例观察截止时间为 **2026-10-22T23:59:59Z**，覆盖从 2026-08-01 开始。付款通常为 2026-09-07。建议先跑 NORMAL 确认 OpenAI 能工作，再跑其余案例，避免配置失败时反复请求。

## 5. 在网页确认 API 到底做了什么

打开任一新调查的 **Activity log**：

- **Model API requests**：有 Succeeded/Failed、attempt、耗时、HTTP 状态、Request ID、返回模型和 token 数。服务不返回的字段显示 Not returned / not reported，不编造用量。
- **Evidence queries**：能看到 overview、allocations、settlements 等实际工具、表名、行数及 Query ID。local-model 的这些取证读取本地文件，不访问 Zetaris。
- **Model context** 事件：显示相关记录发送数、UTF-8 字节数、因 24 KiB 预算省略的记录数，以及排除的未来记录数。该预算针对证据部分，不是整个请求 token 上限。
- 模型只选择取证工具；最终 Finding 和金额判断仍来自独立校验器。

普通正常例通常有四次逻辑规划，需处理器证据的案例最多五次；一次请求重试会多一条 HTTP 记录。模型主动提前停止时可能得到证据不足，这算该例人工验收未达到目标，不能改成离线成功。

## 6. 人工审核与中文记忆

在 NORMAL 或 DUP 完成后：

1. **Review findings** → **Request changes**，备注填“人工要求补充核对”，保存。
2. **Findings** 下方应显示 **Human review · Needs Changes**，刷新后仍存在；不会自动新建调查。
3. 再点 **Review findings** → **Accept findings**，备注填“已核对来源记录”。
4. 勾选 **Approve a reusable memory**。未填 **Confirmed lesson** 时，保存按钮应禁用。
5. 填入：**请先检查供应商变更历史，再复核付款分录。** 保存。
6. **Findings** 下方显示 **Accepted**；到 Case inbox 的 **Reviewed** 筛选中能找到该案例。
7. 返回同一付款，按钮应为 **View result**，打开原调查 ID；Memory 更新不会触发重跑，原调查保留当时召回的记忆。要验证新记忆，请调查另一个尚未运行的付款，或导入新数据版本后点 **Update investigation**。新调查的 **Activity log → Approved memories** 应看到上面的中文原文及来源 Run ID。

新调查结论必须继续依据证据，记忆不能覆盖财务规则。记忆结果最多五条；若你之前批准了很多记忆，需要结合来源 Run ID 核对，不要把旧运行当作新调用结果。

## 7. 另外三个包分别验证什么

### 02-partial-coverage.json

单独导入，选择 **FinTrace OpenAI manual - partial coverage**。Case inbox 恰好一例 PAY_DEMO_NORMAL。

调查应 **Completed → More evidence is needed**，Finding 为 **Additional source coverage required**。Validation 的 Source coverage supports absence checks 为 Unknown，并指出 bank_transactions 覆盖不完整。即使看见匹配银行记录，也不应显示完整核查通过。

### 03-invalid-missing-payments.json

导入应失败，弹窗明确显示 **payments.csv: required file missing**。不得新增可用数据集。关闭弹窗后，之前的数据集和调查仍可使用。

### 04-revised-bundle.json

名称与主包相同，但 clearingDays 从 10 改为 11。导入后应出现不同的数据集 ID/版本；在下拉框选中新版本仍有八例。旧版本已完成的付款，在新版本中标记 **Update available**，点 **Update investigation** 才分析新数据。打开旧调查也会看到更新提示和按钮。旧调查 URL 继续引用旧版本。相同主包再次导入应复用相同版本，不不断新增副本。当前本地模式通过重新导入识别数据变化，不监视外部文件。

## 8. 取消、导出、刷新与错误

| 勾选 | 操作 | 网页预期 |
|---|---|---|
| [ ] | 对尚未分析的付款新发起调查，等待时点 Cancel run | Cancelled；无业务结论，建议动作清空，Review findings 禁用。若已经完成，则选另一付款或新数据版本；已完成结果会复用 |
| [ ] | 已完成调查 → Export → HTML report / JSON / CSV | 三个文件均可打开；HTML、JSON 有结论与审核；CSV 有模式、模型及证据来源；JSON 含 modelRequests 轨迹 |
| [ ] | 刷新已完成调查 | 结果、证据、审核保留，刷新不会再请求模型 |
| [ ] | 停止服务、重新 npm run dev，打开旧调查 URL | 完成记录恢复；不自动重发已完成模型调用 |
| [ ] | 运行中停止并重启服务 | 原调查 Failed，保留已有轨迹；需要人工重新发起 |
| [ ] | 导入超过 1000 行的任一 CSV 表 | 指出具体表和 maximum 1000 rows；不激活该数据集 |

若 API 返回 401/403/404、429、连接超时或拒绝，页面应 **Failed** 并显示可理解的错误，不能显示伪造的正常/异常结论。先排查配置、权限或配额，勿连续重试八例。无需为手测故意改坏真实 Key；错误和取消路径已有模拟自动测试。

## 9. 记录结果

| Payment ID / 功能 | 通过 / 失败 / 未测 | Run ID | 实际 Finding、关键差异或截图路径 |
|---|---|---|---|
| PAY_DEMO_NORMAL | 未测 | | |
| PAY_DEMO_DUP | 未测 | | |
| PAY_DEMO_STALE | 未测 | | |
| PAY_DEMO_MISSING | 未测 | | |
| PAY_DEMO_FEE | 未测 | | |
| PAY_DEMO_FUTURE_EVENT | 未测 | | |
| PAY_DEMO_FUTURE_FEE | 未测 | | |
| PAY_DEMO_CONTEXT_TAIL | 未测 | | |
| 覆盖不足 / 无效导入 / 修订版本 | 未测 | | |
| 审核 / 中文记忆 / 导出 / 取消 / 重启 | 未测 | | |

只记录必要信息，不记录 Key 或完整敏感配置。`validation.json` 是自动验证记录，不能代替这张真实 OpenAI 人工验收表。

重建包并运行离线与模拟验证：`npm run prepare:manual`。这个命令不会调用真实 OpenAI，也不导入你的手测工作区；会写入隔离的 `.local/openai-manual-validation-*`。

`npm run verify:openai` 是独立的**真实收费检查命令**：只运行 NORMAL 一例，在隔离目录保存状态并更新 `live-smoke.json`。它不属于普通测试，不批量运行其他案例。历史截图不随源码发布。
