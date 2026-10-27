import type {
  Investigation,
  InvestigationActivity,
  QueryTrace,
  ToolName,
} from "../../../packages/contracts/src/index";

export type InvestigationStep = Omit<InvestigationActivity, "status"> & {
  status: InvestigationActivity["status"] | "unconfirmed";
  tool?: ToolName;
  title: string;
  startedAt: string;
  updatedAt: string;
  legacy?: boolean;
};

export type ProgressDisclosure = { key: string; open: boolean } | null;

export function progressIsOpen(
  preference: ProgressDisclosure,
  run: Pick<Investigation, "id" | "status">,
) {
  return preference?.key === run.id
    ? preference.open
    : run.status === "queued" || run.status === "running";
}

const tools: Record<ToolName, { title: string; purpose: string }> = {
  overview: {
    title: "Understand this payment",
    purpose:
      "Check payment, vendor and invoice records to establish the investigation context.",
  },
  allocations: {
    title: "Check payment allocations",
    purpose:
      "Trace payment-to-invoice allocations to gather evidence for duplicate-payment checks.",
  },
  settlements: {
    title: "Review bank settlements",
    purpose:
      "Check settlement and return records and amounts for this payment.",
  },
  vendor_history: {
    title: "Review vendor changes",
    purpose: "Check changes to bank details and their effective dates.",
  },
  ledger: {
    title: "Check ledger and fee entries",
    purpose:
      "Retrieve payment and fee entries for amount and fee reconciliation.",
  },
  processor_events: {
    title: "Review payment processing events",
    purpose: "Retrieve event evidence from the payment processing history.",
  },
};

export const sourceTableLabels: Record<string, string> = {
  payments: "Payments",
  invoices: "Invoices",
  vendors: "Vendors",
  payment_allocations: "Payment allocations",
  bank_transactions: "Bank transactions",
  vendor_change_log: "Vendor changes",
  gl_entries: "Ledger entries",
  audit_log: "Processing events",
  bank_statements: "Bank statements",
};

const historicalToolLabels: Record<string, string> = {
  付款概况: "payment overview",
  发票分配: "invoice allocations",
  银行结算: "bank settlements",
  供应商变更: "vendor changes",
  总账分录: "ledger entries",
  处理方事件: "processor events",
};

const historicalActivityText: Record<string, string> = {
  "读取付款、供应商和发票，建立调查的基础背景。":
    "Read payment, vendor and invoice records to establish the investigation context.",
  "核对付款与发票的分配关系，查找同一义务关联的付款。":
    "Check payment-to-invoice allocations and find payments linked to the same obligation.",
  "查询银行结算记录，核对付款的到账情况。":
    "Query bank settlement records to check whether this payment was posted.",
  "查询供应商变更历史，核对付款时有效的收款信息。":
    "Review vendor changes to check which payment instructions were effective at the time.",
  "查询总账分录，核对金额差异及费用记账证据。":
    "Query ledger entries to check amount differences and fee-accounting evidence.",
  "查询处理方事件，补充解释尚未解决的结算问题。":
    "Query processor events to investigate unresolved settlement questions.",
  "先核对付款、供应商和发票，建立调查上下文。": tools.overview.purpose,
  "查看付款如何分配到发票，补充重复付款判断所需的证据。":
    tools.allocations.purpose,
  "核对这笔付款的结算、退回记录与金额。": tools.settlements.purpose,
  "核对银行信息变更及生效时间。": tools.vendor_history.purpose,
  "补充付款及费用分录，供金额与费用核对使用。": tools.ledger.purpose,
  "补充付款处理过程中的事件证据。": tools.processor_events.purpose,
  "补充独立校验仍缺少的来源证据。":
    "Retrieve source evidence still required by the independent verifier.",
  "参照已批准的调查经验，优先补充这一类证据。":
    "Use approved investigation experience to prioritize this evidence tool.",
  "使用独立规则检查证据完整性、时点与财务关系。":
    "Check evidence completeness, timing, and financial relationships using independent rules.",
  "请模型从独立校验器允许的待查工具中选择下一步。":
    "Ask the model to select the next tool from those allowed by the independent verifier.",
  "根据独立校验器的证据缺口安排下一步取证。":
    "Plan the next evidence retrieval from the independent verifier's remaining gaps.",
  "模型请求结束取证；未满足的证据要求将保留为缺口。":
    "The model requested an end to evidence retrieval. Unmet evidence requirements remain unresolved.",
  "查询已取消；未据此判断来源中是否存在记录。":
    "The query was cancelled. No inference was made about whether source records exist.",
  "证据查询未完成；请求失败不代表来源中没有记录。":
    "The evidence query did not complete. A failed request does not establish that source records are missing.",
  "来源查询失败，尚不能据此判断是否存在记录。":
    "The source query failed; it does not establish whether records are present.",
  "检索已批准且适用的调查经验，辅助安排后续工具顺序。":
    "Retrieve applicable approved investigation experience to help prioritize subsequent tools.",
  "暂时没有可复用的已批准经验，继续从当前资料中查证。":
    "No reusable approved experience was found. Continue investigating the current evidence.",
  "步骤已取消；未产生财务结论。":
    "The step was cancelled. No financial conclusion was produced.",
  "步骤未完成；未产生财务结论，可查看已保留的证据。":
    "The step did not complete. No financial conclusion was produced; retained evidence remains available.",
  "步骤意外中断；未产生财务结论。":
    "The step was unexpectedly interrupted. No financial conclusion was produced.",
  "进程重启导致此步骤中断；已保留的证据可供检查。":
    "A process restart interrupted this step. Retained evidence remains available for inspection.",
  "查询成功，这次没有返回来源记录；还需核对资料是否完整。":
    "The query succeeded but returned no source records. Source coverage still needs to be checked.",
  "返回记录中未找到与本次付款关联的分配记录。":
    "No allocations related to this payment were matched in the returned records.",
  "返回记录中未匹配到与本次付款关联的普通银行交易。":
    "No non-fee bank transaction related to this payment was matched in the returned records.",
  "来源记录已取得。": "Source records retrieved.",
  "证据尚不完整，继续补充来源后再判断。":
    "The evidence is incomplete. Retrieve additional sources before drawing a conclusion.",
  "已记录一次证据校验；详细结果见校验记录。":
    "An evidence check was recorded. See Validation for the detailed result.",
  "已记录经验检索；不代表模型采用了经验。":
    "A memory lookup was recorded; this does not establish that the model used a memory.",
};

/** Localize known generated history without rewriting arbitrary source/model text. */
export function localizeRecordedActivityText(value: string): string {
  const exact = Object.hasOwn(historicalActivityText, value)
    ? historicalActivityText[value]
    : undefined;
  if (exact) return exact;
  const selection =
    /^已选择工具 (overview|allocations|settlements|vendor_history|ledger|processor_events)。(.+)$/.exec(
      value,
    );
  if (selection)
    return `Selected tool ${selection[1]}. ${localizeRecordedActivityText(selection[2])}`;
  const memorySuffix = "根据已批准经验安排取证顺序。";
  if (value.endsWith(memorySuffix))
    return `${localizeRecordedActivityText(value.slice(0, -memorySuffix.length))} Use approved experience to prioritize evidence retrieval.`;
  const read = /^读取 (\d+) 条来源记录，(\d+) 条与本次付款相关。/.exec(value);
  if (read) {
    const suffix = value.slice(read[0].length);
    return `Read ${read[1]} source ${read[1] === "1" ? "record" : "records"}, ${read[2]} related to this payment.${suffix ? ` ${localizeRecordedActivityText(suffix)}` : ""}`;
  }
  const found =
    /^查到 (\d+) 条来源记录(?:，其中 (\d+) 条与本次付款相关)?。$/.exec(value);
  if (found)
    return `Found ${found[1]} source ${found[1] === "1" ? "record" : "records"}${found[2] === undefined ? "" : `, ${found[2]} related to this payment`}.`;
  const retrieved = /^取得 (\d+) 条来源记录。$/.exec(value);
  if (retrieved)
    return `Retrieved ${retrieved[1]} source ${retrieved[1] === "1" ? "record" : "records"}.`;
  const allocations = /^关联到 (\d+) 张发票、(\d+) 笔付款的分配记录。$/.exec(
    value,
  );
  if (allocations)
    return `The returned allocations link ${allocations[1]} ${allocations[1] === "1" ? "invoice" : "invoices"} and ${allocations[2]} ${allocations[2] === "1" ? "payment" : "payments"}.`;
  const settlements =
    /^返回记录中匹配到 (\d+) 条普通银行交易，其中 (\d+) 条标记为已入账、(\d+) 条标记为退回。$/.exec(
      value,
    );
  if (settlements)
    return `Matched ${settlements[1]} non-fee bank ${settlements[1] === "1" ? "transaction" : "transactions"} in the returned records: ${settlements[2]} marked posted and ${settlements[3]} marked returned.`;
  const checks =
    /^已执行 (\d+) 项规则检查：(\d+) 项通过，(\d+) 项未通过，(\d+) 项待确认。/.exec(
      value,
    );
  if (checks) {
    const suffix = value.slice(checks[0].length);
    const needed = /^接下来补查([^。]+)。$/.exec(suffix)?.[1].split("、");
    const detail =
      suffix === "本轮没有新增的待查工具。"
        ? "No additional tools are required by this check."
        : needed?.every((tool) => Object.hasOwn(historicalToolLabels, tool))
          ? `Next, retrieve: ${needed.map((tool) => historicalToolLabels[tool]).join(", ")}.`
          : suffix;
    return `Ran ${checks[1]} rule ${checks[1] === "1" ? "check" : "checks"}: ${checks[2]} passed, ${checks[3]} failed, ${checks[4]} unresolved.${detail ? ` ${detail}` : ""}`;
  }
  const memories =
    /^找到 (\d+) 条可参考的已批准经验，接下来继续核对本次资料。$/.exec(value);
  if (memories)
    return `Found ${memories[1]} approved ${memories[1] === "1" ? "memory" : "memories"} for reference. Continue checking the current evidence.`;
  const provided =
    /^已向规划器提供 (\d+) 条已批准的经验；是否采用由后续查证决定。$/.exec(
      value,
    );
  if (provided)
    return `Provided ${provided[1]} approved ${provided[1] === "1" ? "memory" : "memories"} to the planner. Later evidence determines whether they apply.`;
  return value;
}

function title(kind: InvestigationActivity["kind"], tool?: ToolName) {
  if (kind === "tool")
    return tool ? tools[tool].title : "Review source records";
  if (kind === "planning") return "Plan the next evidence check";
  if (kind === "memory") return "Find approved investigation experience";
  return "Validate the collected evidence";
}

function publicReason(reason: string | undefined, tool?: ToolName) {
  if (!reason) return undefined;
  if (
    reason ===
      "Establish the payment, vendor, and invoice context before forming a conclusion." ||
    reason === "Retrieve the next source required by the independent verifier."
  )
    return tool
      ? tools[tool].purpose
      : "Retrieve source evidence still required by the independent verifier.";
  if (
    reason ===
    "Apply a reviewer-approved investigation playbook to prioritize this evidence tool."
  )
    return "Use approved investigation experience to prioritize this evidence tool.";
  return localizeRecordedActivityText(reason);
}

function querySummary(query: QueryTrace, relatedCount?: number) {
  if (query.status === "failed")
    return "The source query failed; it does not establish whether records are present.";
  return relatedCount === undefined
    ? `Found ${query.rowCount} source ${query.rowCount === 1 ? "record" : "records"}.`
    : `Found ${query.rowCount} source ${query.rowCount === 1 ? "record" : "records"}, ${relatedCount} related to this payment.`;
}

function withQuery(
  step: InvestigationStep,
  query: QueryTrace | undefined,
  run: Investigation,
): InvestigationStep {
  const knownIds = new Set(run.evidence.map((record) => record.id));
  const evidenceIds =
    step.evidenceIds ??
    (query
      ? run.evidence
          .filter((record) => record.queryId === query.id)
          .map((record) => record.id)
      : []);
  return {
    ...step,
    tables: step.tables ?? query?.tables,
    rowCount: step.rowCount ?? query?.rowCount,
    durationMs: step.durationMs ?? query?.durationMs,
    evidenceIds: [...new Set(evidenceIds)].filter((id) => knownIds.has(id)),
    summary:
      (step.summary ? localizeRecordedActivityText(step.summary) : undefined) ??
      (query ? querySummary(query, step.relatedCount) : undefined),
  };
}

function timestamp(value: string) {
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : 0;
}

/** A view of recorded work only. It never creates tools from expected tool order. */
export function investigationSteps(run: Investigation): InvestigationStep[] {
  const steps: InvestigationStep[] = [];
  const byId = new Map<string, InvestigationStep>();
  const usedQueries = new Set<string>();
  const structuredTools = new Set(
    run.events
      .filter((event) => event.activity?.kind === "tool")
      .map((event) => event.tool),
  );
  const add = (step: InvestigationStep) => {
    steps.push(step);
    byId.set(step.id, step);
    return step;
  };

  for (const event of run.events) {
    if (event.activity) {
      const activity = event.activity;
      const previous = byId.get(activity.id);
      const fields = Object.fromEntries(
        Object.entries(activity).filter(([, value]) => value !== undefined),
      );
      if (previous) {
        const status =
          previous.status !== "running" && activity.status === "running"
            ? previous.status
            : activity.status;
        Object.assign(previous, fields, {
          status,
          tool: event.tool ?? previous.tool,
          updatedAt: event.at,
        });
        previous.reason = publicReason(previous.reason, previous.tool);
      } else {
        add({
          ...activity,
          title: title(activity.kind, event.tool),
          tool: event.tool,
          reason: publicReason(activity.reason, event.tool),
          startedAt: event.at,
          updatedAt: event.at,
        });
      }
      if (activity.queryId) usedQueries.add(activity.queryId);
      continue;
    }

    // Structured tools supersede their legacy messages in mixed saved runs.
    if (event.tool && structuredTools.has(event.tool)) continue;
    if (event.type === "planning" && event.tool) {
      add({
        id: `legacy-${event.id}`,
        kind: "tool",
        status: "running",
        source: run.mode === "fixture" ? "rules" : "model",
        tool: event.tool,
        title: title("tool", event.tool),
        reason: publicReason(event.message, event.tool),
        startedAt: event.at,
        updatedAt: event.at,
        legacy: true,
      });
    } else if (event.type === "evidence" && event.tool) {
      const queryId = /\bQuery\s+([^\s.]+)\.?/.exec(event.message)?.[1];
      const candidates = run.queries.filter(
        (query) => query.tool === event.tool,
      );
      const query =
        run.queries.find((entry) => entry.id === queryId) ??
        (candidates.length === 1 ? candidates[0] : undefined);
      const previous = [...steps]
        .reverse()
        .find(
          (step) =>
            step.legacy &&
            step.tool === event.tool &&
            step.status === "running",
        );
      const count = /^Retrieved (\d+) source records\./.exec(
        event.message,
      )?.[1];
      const result: Partial<InvestigationStep> = {
        status: query?.status === "failed" ? "failed" : "completed",
        queryId: query?.id,
        summary: query
          ? querySummary(query)
          : count
            ? `Retrieved ${count} source ${count === "1" ? "record" : "records"}.`
            : "Source records retrieved.",
        updatedAt: event.at,
      };
      if (previous) Object.assign(previous, result);
      else
        add({
          id: `legacy-${event.id}`,
          kind: "tool",
          status: "completed",
          tool: event.tool,
          title: title("tool", event.tool),
          startedAt: event.at,
          updatedAt: event.at,
          legacy: true,
          ...result,
        });
      if (query) usedQueries.add(query.id);
    } else if (event.type === "verification") {
      add({
        id: `legacy-${event.id}`,
        kind: "verification",
        status: "completed",
        title: title("verification"),
        summary: event.message.startsWith("Conclusion withheld:")
          ? "The evidence is incomplete. Retrieve additional sources before drawing a conclusion."
          : "An evidence check was recorded. See Validation for the detailed result.",
        startedAt: event.at,
        updatedAt: event.at,
        legacy: true,
      });
    } else if (event.type === "memory") {
      const count = /^Provided (\d+) approved memory snapshots/.exec(
        event.message,
      )?.[1];
      add({
        id: `legacy-${event.id}`,
        kind: "memory",
        status: "completed",
        title: title("memory"),
        summary: count
          ? `Provided ${count} approved ${count === "1" ? "memory" : "memories"} to the planner. Later evidence determines whether they apply.`
          : "A memory lookup was recorded; this does not establish that the model used a memory.",
        startedAt: event.at,
        updatedAt: event.at,
        legacy: true,
      });
    }
  }

  // Some older records retained query traces without the matching event.
  for (const query of run.queries) {
    if (usedQueries.has(query.id)) continue;
    const pending = [...steps]
      .reverse()
      .find(
        (step) =>
          step.legacy &&
          step.tool === query.tool &&
          step.status === "running" &&
          !step.queryId,
      );
    if (pending) {
      Object.assign(pending, {
        status: query.status === "failed" ? "failed" : "completed",
        queryId: query.id,
        summary: querySummary(query),
        updatedAt: query.at,
      });
    } else {
      add({
        id: `query-${query.id}`,
        kind: "tool",
        tool: query.tool,
        title: title("tool", query.tool),
        status: query.status === "failed" ? "failed" : "completed",
        queryId: query.id,
        summary: querySummary(query),
        startedAt: query.at,
        updatedAt: query.at,
        legacy: true,
      });
    }
  }

  const terminal = !["queued", "running"].includes(run.status);
  return steps
    .map((step) =>
      withQuery(
        {
          ...step,
          status:
            terminal && step.status === "running" ? "unconfirmed" : step.status,
        },
        run.queries.find((query) => query.id === step.queryId),
        run,
      ),
    )
    .sort((a, b) => timestamp(a.startedAt) - timestamp(b.startedAt));
}

export function investigationProgressSummary(
  run: Investigation,
  steps: InvestigationStep[],
) {
  const toolsDone = steps.filter(
    (step) => step.kind === "tool" && step.status === "completed",
  ).length;
  const count = toolsDone
    ? ` · ${toolsDone} tool ${toolsDone === 1 ? "check" : "checks"} completed`
    : "";
  if (run.status === "queued") return "Waiting to start";
  if (run.status === "running") {
    const current = [...steps]
      .reverse()
      .find((step) => step.status === "running");
    return current
      ? current.title
      : "Investigation in progress; waiting for the next recorded step";
  }
  if (run.status === "completed") return `Investigation completed${count}`;
  if (run.status === "cancelled") return `Investigation cancelled${count}`;
  return `Investigation could not be completed${count}`;
}
