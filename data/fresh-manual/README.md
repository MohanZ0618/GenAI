# 新数据集：逐步手动测试

数据集名称：**Fresh manual test - 2026-10-22**。

这是一份从零构造的小型合成数据，不是原 Review packet 的重命名。包含九张表、四家虚构供应商、四张发票、五笔付款，其中四笔进入待调查列表；重复付款的第一笔作为关联证据保留。

## 要上传哪个文件

只上传同目录下的 **fresh-test-bundle.json**。它已经包含 manifest 和全部九张 CSV。

`csv/` 是等价的分表版本，第一次手测不用它。`validation.json` 是验证记录，不能作为数据集上传。

## 按顺序操作

1. 打开 http://localhost:4310 。如果无法打开，在项目根目录运行 `npm run dev`。
2. 点左侧 **Datasets**。
3. 点右上角 **Import dataset** → **Browse files / Choose dataset files**。
4. 选择 `data/fresh-manual/fresh-test-bundle.json`，只选这个文件。
5. 点 **Validate & import**。成功后弹窗关闭，数据集列表应出现 **Fresh manual test - 2026-10-22**。
6. 点左侧 **Case inbox**。在 **Active dataset** 中确认选中了上面的数据集，点 **All cases** 并清空搜索。应看到 **4 个案例**。
7. 搜索 **PAY_NEW_NORMAL_01**，点击该行，再点 **Start investigation**。等待 **Completed**，应显示 **No anomaly supported**。
8. 点调查页左上角 **Case inbox**，清空搜索，再搜索 **PAY_NEW_DUP_02** 并发起调查。应显示 **Anomaly supported by evidence**，Finding 为 **The invoice was paid more than once**。
9. 同样返回收件箱，分别搜索并调查 **PAY_NEW_MISSING_01**、**PAY_NEW_FEE_01**，对照下面的预期表。
10. 在重复付款结果中点击 Finding 和证据编号，查看 **Record detail / Provenance**；应能找到两笔 1,000 美元付款对应同一张 1,000 美元发票。
11. 点 **Validation**、**Activity log**，确认有校验和取证过程。财务异常对应的校验显示 Failed 可能正是预期，不能把它和调查生命周期的 Failed 混淆；调查本身应是 Completed。
12. 点 **Review findings**，填一条备注并 **Save human review**；本轮可不勾选记忆。再点 **Export → HTML report**，打开下载文件，最后刷新页面确认结果和审核保留。

## 预期结果

| 手测 | 付款编号 | 关键数据 | 预期 |
|---|---|---|---|
| [ ] | PAY_NEW_NORMAL_01 | 发票、付款、银行均为 USD 600，付款分录平衡 | No anomaly supported |
| [ ] | PAY_NEW_DUP_02 | 同一张 USD 1,000 发票被两笔 USD 1,000 付款结清，银行有两笔记录 | 重复付款 F06，多付 USD 1,000 |
| [ ] | PAY_NEW_MISSING_01 | ERP 付款 USD 800，银行无匹配，已超过 10 个工作日；处理器有未传输事件 | 结算缺失 F12 |
| [ ] | PAY_NEW_FEE_01 | 付款 USD 1,200，银行 USD 1,180，处理器记录净额结算；缺少手续费分录 | 手续费未入账 F14，差额 USD 20 |

金额、账户标识、供应商和事件均为合成测试数据。数据集观察截止时间为 2026-10-22。

## 区分离线与 OpenAI 测试

- 顶部 **Offline fixture**：测试导入、调查规则和交互，不消耗 OpenAI API。
- 顶部 **OpenAI + local data**：相同数据会用于真实模型规划，取决于你配置的 Key、模型权限及模型返回值。

建议先离线完成四例，再测试 OpenAI。需切换时，在项目根目录 `.env.local` 填好 `OPENAI_API_KEY`、`MODEL_PROVIDER=openai`、`FINTRACE_MODE=local-model`，重启服务并运行 `npm run preflight -- --live`。此检查会请求模型。两种模式默认使用不同存储目录，因此切换后应在新模式下重新导入本数据集。

## 已执行的验证

通过 `npx tsx scripts/prepare_fresh_dataset.ts` 生成并验证：CSV schema 通过、API 导入返回 201、列表恰好四个案例、四次离线调查 Completed 且类别与预期一致。验证使用独立 `.local/fresh-validation-*` 目录，未导入用户手测工作区，没有调用真实模型。重新执行生成脚本可得到 `validation.json`；历史运行记录不随源码发布。

## 出错时记录

记录付款编号、顶部模式、Run ID、实际提示和截图；不要截图或粘贴 Key。若导入成功但列表混有旧案例，先检查 Active dataset 是否选成了 All review packets。
