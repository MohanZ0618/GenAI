# H-MEM 比赛版验收与一分钟演示

验证日期：2026-10-26。修改源为 `release/GenAI`。本轮是单实例实现；第三方 Meterless 参考引擎未修改。

## 已实现

- 已完成调查可按需生成一条经验候选或无建议；真实 provider 与 fixture 示例明确区分。草稿状态、引用、生成来源及独立请求轨迹持久化；同调查并发合并，成功/无建议/失败均缓存，失败仅显式重试。
- 人工编辑正文、工作区/供应商范围、接受调查和显式批准后才写入 H-MEM；旧审核请求兼容。相同批准幂等。正文不可 PATCH，纠正时先停用旧条目再批准新正文，历史保留。
- 经验面板显示有效/停用、来源、范围、生成来源及批准时间，支持停用/恢复。调查 Activity log 显示召回解释与不可变快照；JSON/HTML 导出保留快照。
- overview 之后根据实际付款/供应商及校验器待查工具召回。先统一过滤批准、状态、被替代及范围，再结合 H-MEM 本地 hash 评分与中英关键词最多选五条。解释记录匹配词、范围、建议工具与 hash 匹配指示。
- 经验只影响合法待查工具优先顺序；不能赋予新工具、改变覆盖判定或覆盖独立校验器结果。新证据继续手动导入不可变修订版本，用户点击 Update investigation 才运行。

## 证据分层

| 层级 | 本轮结果 | 能证明的范围 |
|---|---|---|
| 离线单元/API | 93/93 通过；类型检查、构建通过 | 草稿并发/缓存、拒绝/超时/无效结构/未知引用、人工回退、幂等、命名空间/供应商隔离、停用恢复、历史快照、恶意经验不能改变财务结果 |
| fixture 对照 | 三场景各两次有/无记忆，共 12/12；生命周期通过 | 确定性示例与本地存储闭环，无真实模型/Zetaris/PostgreSQL |
| 浏览器 | 31/31 通过（原有 29 + 新增 2） | 生成/编辑/批准、刷新与重复点击、范围选择、管理/来源跳转、手机布局、模型错误后人工填写；错误响应测试使用浏览器 mock |
| 真实模型 + 合成数据 | OpenAI / gpt-5.4-mini；12/12 对照结果及引用通过 | 真实模型规划/草稿，独立校验器判断；本地合成证据，无 Zetaris/PostgreSQL live 取证 |
| 独立进程恢复 | 3 条 ready 模型草稿与请求轨迹、来源、批准时间及 inactive 状态从磁盘恢复 | 本地进程重建读取验证；不等于多实例并发或数据库故障恢复 |

最初两次准备失败分别为发布目录无凭据和受限网络连接失败。随后从根目录已有环境配置载入进程，并获准使用网络，完整运行一次三场景十二次对照；没有挑选成功调查替代失败结果，也没有降级到 fixture。原有浏览器套件第一轮新增用例因可访问标签匹配失败；已补充明确标签并重跑通过。Windows 托管服务器收尾曾等待不退出，最终使用独立 fixture 服务与临时复用配置完整重跑，31 条通过并正常退出。

## 真实模型十二次小型对照

固定同一目标数据快照、provider、模型及 temperature=0；每次采用独立命名空间，避免缓存复用。经验来自独立合成示例（不同 ID 和金额，金额按 1.37 缩放），与目标采用相同场景生成模板。先由真实模型生成，再由脚本扮演审核员改成不含测试结论/金额/答案的取证程序，经审核 API 显式批准。此自动化步骤证明审核接口闭环，不冒充真实客户或用户实际批准。网页人工操作另由浏览器交互验证。

工具缩写：O=overview，A=allocations，S=settlements，V=vendor_history，L=ledger，P=processor_events。请求数为 HTTP 尝试；token 为 provider 返回 usage 的总数。耗时含本地取证/持久化。

| 场景 | 轮次 | 经验 | 财务类别/结果 | 引用 | 工具顺序 | 请求 | token | 耗时 ms |
|---|---:|---|---|---|---|---:|---:|---:|
| DUP | 1 | 无 | F06 / anomaly_supported | 有效 | O → A → S → V → L | 4 | 7552 | 3984 |
| DUP | 1 | 有 | F06 / anomaly_supported | 有效 | O → A → S → V → L | 4 | 9551 | 3864 |
| DUP | 2 | 无 | F06 / anomaly_supported | 有效 | O → A → S → V → L | 4 | 7585 | 3833 |
| DUP | 2 | 有 | F06 / anomaly_supported | 有效 | O → A → S → V → L | 4 | 9494 | 4050 |
| STALE | 1 | 无 | F11 / anomaly_supported | 有效 | O → A → S → V → L → P | 5 | 8733 | 4396 |
| STALE | 1 | 有 | F11 / anomaly_supported | 有效 | O → V → A → S → L → P | 5 | 10836 | 4748 |
| STALE | 2 | 无 | F11 / anomaly_supported | 有效 | O → A → S → V → L → P | 5 | 8680 | 4816 |
| STALE | 2 | 有 | F11 / anomaly_supported | 有效 | O → V → A → S → L → P | 5 | 10776 | 4617 |
| FEE | 1 | 无 | F14 / anomaly_supported | 有效 | O → A → S → V → L → P | 5 | 8473 | 4351 |
| FEE | 1 | 有 | F14 / anomaly_supported | 有效 | O → A → S → V → L → P | 5 | 10264 | 4729 |
| FEE | 2 | 无 | F14 / anomaly_supported | 有效 | O → A → S → V → L → P | 5 | 8460 | 6082 |
| FEE | 2 | 有 | F14 / anomaly_supported | 有效 | O → A → S → V → L → P | 5 | 10193 | 4862 |

| 条件 | 正确结果/有效引用 | 请求总数 | token 总数 | 总耗时 ms |
|---|---:|---:|---:|---:|
| 无经验 | 6/6 | 28 | 49483 | 27462 |
| 有经验 | 6/6 | 28 | 61114 | 26870 |

供应商变更场景两次都把 V 提前；另外两个场景工具顺序未变。请求总数均为 28，有经验组 token 从 49,483 增加至 61,114（约 +23.5%）。本轮没有证据证明节省请求或 token，也不据此声称统计显著准确率/成本收益。三次草稿调用另计 6,621 token，不混入上述规划对照成本。

真实模型生命周期另包含三个示例调查/草稿，及“召回一次 → 停用 → 导入修订版本 → 显式新调查不召回”；不计入十二次对照。新调查结果仍正确；旧调查经验快照在停用后保持原样。重建 MemoryService/InvestigationService 后继续验证，再用独立 Node 进程读取草稿、请求及状态。

## 复现和本地证据

```powershell
# 离线验证，防止本地环境文件切到真实模型
$env:FINTRACE_MODE='fixture'
npm test
npm run typecheck
npm run build
npm run test:browser
npm run verify:hmem

# 已通过环境变量提供真实模型配置时，以下命令会收费
$env:FINTRACE_MODE='local-model'
npm run verify:hmem -- --connect
```

运行轨迹仅保存在忽略目录，不加入发布清单：

- fixture：`.local/hmem-acceptance-fixture-pmR0fm/report.json`
- 真实模型：`.local/hmem-acceptance-local-model-mHJCRq/report.json`，对应 `state/runs/` 保存调查和独立草稿请求，`memory/<namespace-hash>/state.json` 与 `ledger.jsonl` 保存经验/审计。
- 浏览器截图和 trace：`test-results/`（忽略目录）。

## 约一分钟视频步骤

先运行 `npm run prepare:hmem-demo`，依次导入 `.local/hmem-demo/01-version.json`、`02-version.json`、`03-version.json`。三份数据名称相同，聚焦 `PAY_DEMO_STALE`，后两个版本分别增加一条合成审核证据；同一供应商和财务场景保持可比较。生成过程不调用模型。第一版完成后批准经验，第二版手动更新后展示召回；停用后导入第三版，再手动更新展示不再召回。

1. **0–10 秒**：打开一个已完成调查，展示证据/独立校验结果，点 Review findings → Suggest memory。屏幕保留真实模型或 fixture 标签。
2. **10–25 秒**：展示适用条件、建议工具和依据引用；编辑正文，选当前工作区，勾选批准经验，保存接受审核。强调“草稿不参与召回，必须人工批准”。
3. **25–40 秒**：导入预先准备的修订数据版本，展示 Update available，点击 Update investigation。打开 Activity log，展示提供给规划器的经验、匹配词、范围和来源。强调“已提供不代表模型采用”。
4. **40–50 秒**：进入 Investigation memories，查看来源/批准时间，停用条目。展示旧报告快照仍在。
5. **50–60 秒**：再导入一个预备修订版本并手动启动，展示新调查不再召回该条；面板 Restore 可恢复。收尾字幕：“只指导取证优先顺序，财务判断由独立校验器决定”。

可提前录制模型等待部分并加速剪辑；不得把 fixture 镜头标成真实模型。正式界面里仍由人完成批准；自动验收中的脚本审核只是测试夹具。

## 尚未证明

真实客户效果、生产级语义检索、统计显著收益、租户鉴权、多实例安全写入、故障注入恢复，以及本轮 H-MEM 修改在真实 PostgreSQL/Zetaris 下的端到端运行尚未证明。本轮不新增关系图、跨案件影响传播、后台监控或自动付费重跑。
