# FinTrace Demo：逐步操作清单

配套口播：[英文录制稿](DEMO_NARRATION_EN.md)。默认成片 **3 分 40 秒**，使用本机已完成并通过验收的真实 live 调查记录。录制时说明是在回看已保存的真实调查；打开历史详情不会重新调用模型，也不要把回放说成正在实时计算。

## 一、录制前先准备好

1. 打开 **Docker Desktop**，保持已配置的 PostgreSQL、Zetaris 容器运行。打开 **Nightshift M1-M4** 并保持应用窗口开启。已有容器、账号和密钥继续使用，不需要重新安装或创建。
2. 打开当前 live 页面：[Investigation 列表](http://127.0.0.1:4316/?view=investigations)。确认右上角是 **API connected**。若仍在加载，等页面完成；必要时点刷新图标 **Refresh API connection**。
3. 如 API 没有运行，在原项目根目录的终端执行以下命令，保持终端开启。此私有配置不在 GitHub 中；不要打开它录屏，也不要把密钥粘到画面里。

   ```sh
   node --env-file=.env.nightshift-live.local --import tsx apps/api/src/server.ts
   ```

4. 如果计划展示独立 USL 页面，还需保持已启动的 supplier-policy 服务运行。只有端口 4315 没有服务时，才在另一个项目终端运行：

   ```sh
   node --import tsx scripts/serve_zetaris_policy.ts
   ```

5. 用电脑浏览器录制。关闭通知、聊天软件浮窗和无关标签页；只录应用内容或指定窗口。不要录 Nightshift 的 **Setup → Providers**、API Keys 页面、登录过程、私有配置或完整桌面上的个人信息。
6. 先试录 10 秒，检查英文声音、鼠标和文字清晰度。录制鼠标动作后停留约 1–2 秒，再切下一画面。无需把 900 多条证据全部滚完。

如果服务重启或页面不可用，先恢复现有服务并重新打开这四个记录。不要为了录屏重新跑整个验收脚本；它会消耗 API 配额并创建新记录。服务配置见 [NIGHTSHIFT_SETUP.md](NIGHTSHIFT_SETUP.md)。

## 二、提前打开四个准确的调查

这些链接属于当前电脑的 live 工作区，付款编号相同也可能有多次调查，所以按 **run ID** 区分。新克隆仓库的 fixture 演示与这些 live 历史分开。

| 代号 | 用途 | 直接打开 |
|---|---|---|
| A | 后续异常调查，已召回 `mem-1` | [PAY_DEMO_DUP](http://127.0.0.1:4316/?investigation=run-2a344a72-dfe6-4aca-9189-e55b717b67b4&from=investigations) |
| B | 独立 lesson，已有脚本化合成审核和批准记忆 | [PAY_NIGHTSHIFT_LESSON_DUP](http://127.0.0.1:4316/?investigation=run-0eed9ff7-31f3-4ad9-ac28-15d4c1de1dc0&from=investigations) |
| C | 正常付款 | [PAY_DEMO_NORMAL：正常](http://127.0.0.1:4316/?investigation=run-20c7b6e1-3cb5-43db-ad6e-7555fc9445d8&from=investigations) |
| D | 证据覆盖不足 | [PAY_DEMO_NORMAL：证据不足](http://127.0.0.1:4316/?investigation=run-202402fd-745a-4310-ae24-f56379bc1045&from=investigations) |

另准备好 Nightshift 应用的 **Console → Proof**，以及[脱敏验收记录](../../data/nightshift-acceptance/results.json)。优先找目标 A 较新的最后一条规划调用 `req_08kjoxo3`；它的第一条规划调用为 `req_q954p7bd`，B 的记忆草稿调用为 `req_94mnt1wa`。实际模型为 `gemini-3.5-flash-lite`，provider 为 `google`，应用上下文为 `fintrace`。

## 三、按这个顺序录：3 分 40 秒

下面的时间是最终成片时间。可以分段录制，再按顺序拼接；剪短等待时用 **Recorded live investigation** 或 **Waiting time shortened** 标注，不拼造不存在的调用或审批。

### 0:00–0:20｜介绍问题

1. 打开 Investigation 列表，停留在列表标题及最新记录处。
2. 鼠标指一下付款对象、Snapshot、Status / conclusion 和 Human review 四处。
3. 读英文稿第 1 段。字幕保留 **Synthetic demonstration data**。

应看到：每次实际调查独占一行；同一付款可以有不同版本或不同次调查。

### 0:20–0:50｜打开真实异常结果

1. 在 A 对应的那一行点 **View investigation**；也可以切到预先打开的 A 标签页。
2. 停在顶部 **Completed / Issues found / Awaiting review**。A 当前没有人工复核，不能说它已经被人工接受。
3. 如果 **Investigation activity** 已展开，先点一次收起，露出结论 **The invoice was paid more than once**。
4. 在 Findings 中点一条相关证据，如 `PAY_DEMO_DUP_OTHER`。展示 **Original record** 的 **Source table**、**Source record ID**、**Dataset version**，以及原始字段。
5. 关闭证据窗口，读英文稿第 2 段。

不要把 **Review findings** 误当作“重新调查”；它打开的是复核界面。

### 0:50–1:25｜解释取证与独立校验

1. 点开 **Investigation activity**。
2. 依次指一下 **Check payment allocations**、**Review bank settlements**、**Check ledger and fee entries**，不用逐条展开全部证据。
3. 展开其中一项的 **Source and execution details**，展示 Tables、Query ID 和 Recorded duration。
4. 向下找到并展开 **Validation**，展示检查通过、标记异常及未知项的区别。
5. 读英文稿第 3 段。

画面中的 Query ID 是应用生成的追踪 ID，不要称它为 Zetaris 平台签发 ID。当前应用不会在这里展示原始 SQL；不要在口播中说“这里显示 SQL”。

### 1:25–1:50｜证明经过 Nightshift

1. 切到 Nightshift 窗口，按 **⌘5** 打开 Console，选择 **Proof**。
2. 打开属于 `fintrace`、模型为 Gemini 3.5 Flash Lite 的对应历史记录；如有 **View stored race**，点开查看实际 winner。
3. 与已准备的脱敏结果记录核对 `req_08kjoxo3`、`google`、`gemini-3.5-flash-lite` 和 `fintrace`，展示相同的一笔调用。若选择同一调查的另一条调用，就同步改用它自己的准确 decision ID。
4. 读英文稿第 4 段。

前端的 **Activity log → Model API requests** 会显示模型、状态和 token 等信息，但当前不会把 `meterlessDecisionId` 单独画出来；HTTP Request ID 可能显示 **Not returned**。关联 ID 以脱敏结果和 Runtime 记录为准，不要拿 Chat Completion ID 代替。若找不到那条历史记录，先停止该段录制并重新核对，不能用另一条调用冒充。这里的元数据未签名，不说“密码学签名已验证”。

### 1:50–2:40｜展示批准的记忆与后续召回

1. 切到 B，向下找到 **Human review** 和 **Investigation memory**。展示已有 **Accepted**、审核说明和 **Memory approved**。
2. 说明这一份验收中的批准由 **scripted synthetic reviewer** 完成；这是已保存的审核记录，不是假装录制者此刻刚批准。
3. 点左侧 **Investigation memories**，找到 `mem-1 · active`，展示过程性内容、Scope、Suggested tools 和 **Open source investigation**。不要点 **Deactivate**、**Remove** 或 **Restore**。
4. 切回 A，展开 **Investigation activity**，指向 **Find approved investigation experience**，展示找到 1 条批准记忆的记录。
5. 向下展开 **Activity log**，找到 **Memories provided to planner**，展示程序性内容和 **Source run** 链接。它应指向 B。
6. 读英文稿第 5 段。画面太长时，预先录成“B 审核 → mem-1 → A 召回”三段后顺序剪接。

不要再次批准 B 的同一记忆，也不要说 A 的“Not approved”代表没有召回：A 右侧的 Investigation memory 指的是“是否为 A 批准新记忆”，召回历史在 activity/diagnostics 中。

### 2:40–3:05｜展示正常和证据不足

1. 切到 C，收起 activity，停在 **No anomaly supported** 的结论。
2. 切到 D，停在 **Insufficient evidence** 的详情结论；列表中同类结论显示 **More evidence needed**。
3. 点一下证据缺口或展开 **Next steps & evidence gaps**，只展示最相关的一条。
4. 读英文稿第 6 段。

### 3:05–3:25｜导出保留证据的报告

1. 切回 A，向下找到 **Human review** 区域。
2. 指一下 **Reviewer note**、**Accept findings** 和 **Request changes**，默认录制只展示控制权，不保存新的审批。
3. 在 **Export the recorded investigation** 下点 **Export → HTML report**，打开下载的报告，展示 Findings、引用和记录信息。
4. 读英文稿第 7 段。导出会生成文件，不发起模型调用。

### 3:25–3:40｜结果、局限和项目链接

1. 切到总结页/PPT，显示 **4 synthetic cases · 20 Zetaris queries · 17 Nightshift-correlated calls**。
2. 显示仓库地址 [github.com/MohanZ0618/GenAI](https://github.com/MohanZ0618/GenAI)。
3. 读英文稿第 8 段后停留 2 秒结束，不用加长尾动画。

## 四、如果想额外录一次“我亲手复核”

这是一段可选操作，会改变当前合成调查的复核状态，新增记忆草稿还会消耗真实 API 配额。默认 3:40 版本已经可以用上面的历史回看完成，不必临时重跑。

1. 在尚未接受的 A 中点顶部 **Review findings**（或右侧 **Review memory suggestion**），打开完整复核界面。
2. 只做普通复核时，选择 **Accept findings**，在 **Review notes** 写下实际检查内容，保持 **Approve a reusable memory** 未勾选，点 **Save human review**。这时才能说“我保存了这次复核”。
3. 要录完整新记忆流程时，先点 **Suggest memory**，等待 **Draft: ready · meterless / gemini-3.5-flash-lite**。失败时先停止录制、检查错误，不能把手填内容称作模型生成。
4. 选择 **Accept findings**，勾选 **Approve a reusable memory**，检查 **Memory scope**，编辑 **Confirmed lesson**，只保留取证步骤。
5. 点 **Save human review**，确认页面出现 Accepted / Memory approved。不能把当前目标的金额、分类答案写成供下一次使用的“记忆”。
6. 如果要接着展示这条新记忆被使用，必须再发起另一笔真实的新调查并确认其召回快照；刷新原来的 A 不会改写其历史记忆。这一步需要额外准备，不能用旧的 `mem-1` 召回来代替新记忆。

内嵌 Human review 区域的 **Accept findings** 只保存普通复核，不会自动批准记忆；记忆必须通过完整复核界面单独勾选批准。

## 五、USL／数据质量的可选补充镜头

若想在视频中展示独立 USL，建议替换约 10–15 秒介绍镜头，并让总时长仍小于 4 分钟。也可把这些内容放在 deck 和评分材料中。

1. 打开现有 Zetaris 页面 `http://localhost:3000/`，录屏前完成登录。
2. 打开已保存的 **FinTrace_USL_policy_review** 查询；展示已有两条超过人工复核阈值的结果，或实际运行该只读查询后展示结果。
3. 打开已部署 `lightning.metastore.fintrace_scoring.payment_review` 的模型/数据质量结果，或使用材料里的真实平台截图。
4. 口播可用：“Our separate USL demonstration connects three simulated feeds and executes seven native quality rules.”

这三路是 PostgreSQL ERP、bank CSV 和 supplier-policy HTTP。它们都是合成演示数据；主调查仍走 FINTRACE 不可变快照证据路径。不要说“主调查已联邦连接三家真实企业”，也不要把七个重叠规则的通过数称为“100% 财务准确率”。详见 [ZETARIS_USL.md](ZETARIS_USL.md)。

## 六、录完后检查

- 成片 1–4 分钟；建议保留约 3:40，不靠加速口播硬塞内容。
- 画面中的付款、run ID、Runtime 记录和旁白对应；回看历史明确标注。
- 没有露出 API key、Runtime token、密码、私有配置或个人通知。
- 合成数据、脚本化验收审核、未签名元数据和原型范围的说明准确。
- 视频链接退出登录后可播放；不要把 `localhost` 当作评委可访问的线上部署链接。
- 保留原始录屏。上传成片后，再把可访问链接填入 HackOS；录制稿本身不是成片。
