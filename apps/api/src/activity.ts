import type {
  EvidenceReference,
  Investigation,
  InvestigationActivity,
  ToolName,
} from "../../../packages/contracts/src/index.ts";
import { observe, relatedEvidence } from "./observation.ts";
import { tablesByTool } from "./evidence.ts";
import type { Assessment } from "./verifier.ts";

// Public descriptions of the tool's purpose, never a model's private reasoning.
export const toolPurpose: Record<ToolName, string> = {
  overview:
    "Read payment, vendor and invoice records to establish the investigation context.",
  allocations:
    "Check payment-to-invoice allocations and find payments linked to the same obligation.",
  settlements:
    "Query bank settlement records to check whether this payment was posted.",
  vendor_history:
    "Review vendor changes to check which payment instructions were effective at the time.",
  ledger:
    "Query ledger entries to check amount differences and fee-accounting evidence.",
  processor_events:
    "Query processor events to investigate unresolved settlement questions.",
};
export const toolTables = tablesByTool;
const toolLabel: Record<ToolName, string> = {
  overview: "payment overview",
  allocations: "invoice allocations",
  settlements: "bank settlements",
  vendor_history: "vendor changes",
  ledger: "ledger entries",
  processor_events: "processor events",
};

export function toolResultActivity(
  returned: EvidenceReference[],
  allEvidence: EvidenceReference[],
  paymentId: string,
  asOf: string,
  tool?: ToolName,
) {
  const relevantIds = new Set(
    relatedEvidence(observe(allEvidence, asOf).visible, paymentId).map(
      (item) => item.id,
    ),
  );
  const related = returned.filter((item) => relevantIds.has(item.id));
  let summary = returned.length
    ? `Read ${returned.length} source ${returned.length === 1 ? "record" : "records"}, ${related.length} related to this payment.`
    : "The query succeeded but returned no source records. Source coverage still needs to be checked.";
  if (returned.length && tool === "allocations") {
    const allocations = related.filter(
      (item) => item.table === "payment_allocations",
    );
    const distinct = (field: string) =>
      new Set(allocations.map((item) => item.record[field]).filter(Boolean))
        .size;
    summary += allocations.length
      ? ` The returned allocations link ${distinct("invoice_id")} ${distinct("invoice_id") === 1 ? "invoice" : "invoices"} and ${distinct("payment_id")} ${distinct("payment_id") === 1 ? "payment" : "payments"}.`
      : " No allocations related to this payment were matched in the returned records.";
  } else if (returned.length && tool === "settlements") {
    const ordinary = related.filter(
      (item) =>
        item.table === "bank_transactions" &&
        item.record.transaction_type !== "bank fee",
    );
    const posted = ordinary.filter(
      (item) => item.record.status === "posted",
    ).length;
    const returnedCount = ordinary.filter(
      (item) => item.record.status === "returned",
    ).length;
    summary += ordinary.length
      ? ` Matched ${ordinary.length} non-fee bank ${ordinary.length === 1 ? "transaction" : "transactions"} in the returned records: ${posted} marked posted and ${returnedCount} marked returned.`
      : " No non-fee bank transaction related to this payment was matched in the returned records.";
  }
  return {
    rowCount: returned.length,
    relatedCount: related.length,
    evidenceIds: related.slice(0, 12).map((item) => item.id),
    summary,
  };
}

export function verificationActivity(result: Assessment) {
  const count = (status: "passed" | "failed" | "unknown") =>
    result.checks.filter((check) => check.status === status).length;
  return {
    evidenceIds: [
      ...new Set(result.checks.flatMap((check) => check.evidenceIds)),
    ].slice(0, 12),
    summary:
      `Ran ${result.checks.length} rule ${result.checks.length === 1 ? "check" : "checks"}: ${count("passed")} passed, ${count("failed")} failed, ${count("unknown")} unresolved.` +
      (result.neededTools.length
        ? ` Next, retrieve: ${result.neededTools.map((tool) => toolLabel[tool]).join(", ")}.`
        : " No additional tools are required by this check."),
  };
}

export function unfinishedActivities(run: Investigation) {
  const latest = new Map<
    string,
    { activity: InvestigationActivity; tool?: ToolName; startedAt: string }
  >();
  for (const event of run.events) {
    if (!event.activity) continue;
    latest.set(event.activity.id, {
      activity: event.activity,
      tool: event.tool,
      startedAt: latest.get(event.activity.id)?.startedAt || event.at,
    });
  }
  return [...latest.values()].filter(
    ({ activity }) => activity.status === "running",
  );
}
