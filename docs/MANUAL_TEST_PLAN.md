# FinTrace 手动功能测试

最新的独立合成数据与逐步网页预期见 [八例 OpenAI 验收清单](../data/openai-manual/EXPECTED_RESULTS.zh-CN.md)。第一次只上传该目录的 `01-main-bundle.json`。以下内容保留为原有功能清单；不要把历史“已准备配置”的说明当作实时连通证明。

这轮先测全部功能是否可用，再用你的 OpenAI API 测真实模型。先不做压力测试、大规模评估或生产部署。样例都是合成数据。

## 1. 启动和填写 API

在项目根目录打开 PowerShell：

```powershell
npm run build
npm run dev
```

打开 http://localhost:4310 。也可以双击 `start-fintrace.cmd`。新环境先执行 `npm ci`。修改页面代码后重新 build，启动脚本只会在构建不存在时自动 build。

发布包不包含 `.env.local`。默认 `FINTRACE_MODE=fixture`，无需 Key；如需配置，复制 `.env.example`。先完成下面的离线清单。

**你的 OpenAI Key 填在项目根目录的 `.env.local`，不是网页或 NVIDIA 配置：**

```dotenv
FINTRACE_MODE=local-model
MODEL_PROVIDER=openai
OPENAI_API_KEY=在你本机填写真实Key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
PORT=4310
HOST=127.0.0.1
FINTRACE_STORAGE_DIR=
```

上面的 Key 是说明文字，请替换。不要把真实 Key 发到聊天、截图或报告中。`.env.local` 已被 Git 忽略。

`FINTRACE_STORAGE_DIR` 留空时：fixture 保存在 `.local/app`，local-model 保存在 `.local/manual-openai`。若显式设置路径，以设置值为准。配置修改后在服务终端按 Ctrl+C，再运行 `npm run dev`。

```powershell
npm run preflight
npm run preflight -- --live
```

第一条仅检查配置；第二条在 local-model 模式实际请求所选模型，会产生少量 API 用量，结果应为 `ok: true`、`checks.model.status: responded`。此模式不需要 PostgreSQL、Zetaris 或 NVIDIA Key。仅填 Key、不把模式改为 local-model，仍然不会调用模型。

切换模式后上次调查可能属于另一存储目录；出现“previous investigation is unavailable”时，从 Case inbox 选择案例重新开始。页面集成状态里的 configured/not verified 只代表配置存在，真实连通以 preflight 和调查结果为准。

## 2. 离线全功能清单

每项完成后勾选；未通过时在末尾问题表记录。页面以英文按钮名为准。

| 完成 | 功能与操作 | 应看到的结果 |
|---|---|---|
| [ ] | 进入 Case inbox、Investigation、Datasets、How FinTrace works | 页面能打开；顶部为 Offline fixture；无未处理错误 |
| [ ] | Active dataset 切换数据集，搜索付款编号/供应商，再清空搜索 | 对应列表和数量更新；搜索不存在的编号有 No matching cases |
| [ ] | 切换 All cases / Unreviewed / Reviewed | 与已保存审核状态一致 |
| [ ] | 选择付款并点 Start investigation，也试一下行尾调查按钮 | 进入调查页，最终 Completed；等待期间不会重复发起 |
| [ ] | 跑下一节六个代表案例 | 四类异常、正常、证据不足均符合预期 |
| [ ] | 点 Finding 和证据编号，切换 Record detail / Provenance、证据下拉框 | 来源表、原始记录、版本、Query ID 可追溯 |
| [ ] | 查看 Source timeline、Activity log、Validation，点击校验证据 | 时间线、事件、校验和证据相互对应 |
| [ ] | 查看 Proposed actions | 是建议和人工前提，没有实际付款或改账记录 |
| [ ] | Review findings → Request changes，填备注并保存 | 显示 Needs Changes；刷新后仍在 |
| [ ] | 再审核，选择 Accept findings，填备注；不批准记忆 | 显示 Accepted；收件箱 Reviewed 能找到；JSON 中 review 没有 memoryId |
| [ ] | 再审核，勾选 Approve a reusable memory | 未填 Confirmed lesson 时不能保存；填入“Inspect ledger before settlements during payment review.”后保存成功 |
| [ ] | 新发起一次调查，查看 Activity log；导出 JSON | 显示读取已批准记忆；JSON 有 memories，先前审核有 review.memoryId；结论仍由证据决定 |
| [ ] | 分别导出 HTML report、JSON、Evidence CSV | 文件非空可打开；证据一致；HTML/JSON 含审核；CSV 含模式、模型及证据字段 |
| [ ] | 刷新浏览器；关闭并重启服务后再打开原调查 URL | 调查结果、证据和审核保留 |
| [ ] | Datasets → Get template | 下载 JSON，包含 manifest 和九张 CSV 的表头；空模板没有可调查付款是正常的 |
| [ ] | 导入 `data/manual-test/valid-bundle.json`，再进入 Case inbox | 新数据集已选中；有 PAY_0426017；能调查出重复付款 |
| [ ] | 导入 `data/manual-test/csv/` 下 manifest.json + 全部九张 CSV | 成功且与 bundle 是同一数据集版本，不重复生成版本 |
| [ ] | 导入 `data/manual-test/invalid-missing-payments.json` | 明确提示 payments.csv 缺失，原数据集仍可用 |
| [ ] | 导入 `data/manual-test/revised-bundle.json` | 同名新版本、ID/版本不同；旧调查 URL 仍指向旧数据集 |
| [ ] | 打开导入/审核弹窗，试 Cancel、右上角关闭和 Esc | 弹窗关闭，页面可继续操作；未保存内容不产生审核 |
| [ ] | 手机或开发者工具切换到 390px 宽度，操作导航、证据和导入 | 页面无整体横向溢出；主要按钮及菜单可用 |
| [ ] | 保持网页打开，停掉服务；点刷新连接或发起请求，再重启服务并刷新连接 | 有可理解的连接错误；重启后可恢复 |

取消另在 OpenAI 模式等待期间验证，因为离线调查可能来不及点取消。运行中重启服务时，原调查应标为 Failed 并保留轨迹；完成的调查应原样恢复。

## 3. 六个代表案例

先从 Active dataset 选择数据集，再按付款编号确认。每例离线跑一次；真实模型先跑 001、049、Coverage 001，再补其余三例。

| 数据集 | 付款编号 | 预期 | 离线 | OpenAI |
|---|---|---|---|---|
| Review packet 001 | PAY_0426017 | Anomaly supported by evidence，重复付款 F06 | [ ] | [ ] |
| Review packet 013 | PAY_0424562 | Anomaly supported by evidence，付款信息冲突 F11 | [ ] | [ ] |
| Review packet 025 | PAY_0420886 | Anomaly supported by evidence，银行结算缺失 F12 | [ ] | [ ] |
| Review packet 037 | PAY_0425100 | Anomaly supported by evidence，金额/费用差异 F14 | [ ] | [ ] |
| Review packet 049 | PAY_0422142 | No anomaly supported | [ ] | [ ] |
| Coverage packet 001 | PAY_0426017 | More evidence is needed | [ ] | [ ] |

同一个付款编号可出现在不同覆盖范围的数据集中，要同时核对数据集名称。

## 4. OpenAI 额外验收

- [ ] 按第 1 节配置并重启；顶部显示 **OpenAI + local data**、实际模型名，以及无 Zetaris/PostgreSQL 的说明。
- [ ] preflight 实际连通通过，跑六个代表案例；每次应有 `provider: openai`、`mode: local-model` 和实际模型。JSON 的 modelTurns 大于 0 才能证明该调查进入过模型规划。
- [ ] 点证据确认来自本地数据；重新导出三种格式，模式说明准确。
- [ ] 发起调查后点 Cancel run：Cancelled，JSON outcome 为 null、actions 为空，不能审核。
- [ ] 用临时错误 Key 重启测试一次：调查或连通检查失败，有明确提示，不生成离线成功结果；之后恢复正确 Key 并重启。
- [ ] 模型请求等待期间重启服务：旧调查 Failed，轨迹保留；不会自动重发模型请求。重新发起可恢复。

Key 无效/无模型权限通常会出现 401/403/404；429 可能是配额或限流。以实际返回状态和账户设置排查，错误不会被当作“证据不足”的业务结论。

## 5. 测试记录

本次自动验证的结果见 `docs/TEST_RESULTS.md`。自动浏览器用测试桩验证 OpenAI 流程，不代表真实账户连通。本表供你手测，默认全部未测。

| 项目 | 结果（通过/失败/未测） | 备注 |
|---|---|---|
| 离线全功能 | 未测 | |
| OpenAI 实际连通 | 未测 | |
| OpenAI 六个代表案例 | 未测 | |
| 取消、重启、错误恢复 | 未测 | |
| 手机布局 | 未测 | |

问题记录只保留必要信息，不包含 Key：

| 编号 | 数据集 / Run ID | 操作步骤 | 预期 | 实际 / 截图 | 处理结果 |
|---|---|---|---|---|---|
| 1 | | | | | |
