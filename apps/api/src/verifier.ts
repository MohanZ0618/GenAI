import Decimal from "decimal.js";
import { observe, relatedEvidence } from "./observation.ts";
import { parseTime } from "../../../packages/contracts/src/index.ts";
import type {
  Dataset,
  EvidenceReference,
  Finding,
  Outcome,
  VerificationCheck,
  ActionProposal,
  ToolName,
  Row,
} from "../../../packages/contracts/src/index.ts";
export const TOOL_ORDER: ToolName[] = [
  "overview",
  "allocations",
  "settlements",
  "vendor_history",
  "ledger",
  "processor_events",
];
export type Assessment = {
  outcome: Outcome;
  findings: Finding[];
  checks: VerificationCheck[];
  actions: ActionProposal[];
  neededTools: ToolName[];
};
export function businessDays(from: string, to: string) {
  let n = 0;
  const date = new Date(from.slice(0, 10) + "T00:00:00Z");
  const end = new Date(parseTime(to));
  while (date < end && n < 10000) {
    date.setUTCDate(date.getUTCDate() + 1);
    if (date <= end && date.getUTCDay() !== 0 && date.getUTCDay() !== 6) n++;
  }
  return n;
}
export function assess(
  dataset: Dataset,
  paymentId: string,
  evidence: EvidenceReference[],
  completed: Set<ToolName>,
): Assessment {
  const rawEvidence = evidence;
  const observation = observe(evidence, dataset.asOf);
  evidence = observation.visible;
  const by = (table: string) => evidence.filter((e) => e.table === table);
  const rows = (table: string) => by(table).map((e) => e.record);
  const ids = (records: Row[]) =>
    evidence.filter((e) => records.includes(e.record)).map((e) => e.id);
  const checks: VerificationCheck[] = [];
  const findings: Finding[] = [];
  const actions: ActionProposal[] = [];
  const excluded = relatedEvidence(rawEvidence, paymentId).filter((e) =>
    observation.excluded.includes(e),
  );
  if (excluded.length)
    checks.push({
      id: "observation-cutoff",
      label: "Future evidence excluded from the assessment",
      status: "passed",
      detail: `${excluded.length} related records after ${dataset.asOf} were retained for audit but excluded from financial reasoning.`,
      evidenceIds: excluded.map((e) => e.id),
    });
  const neededTools = TOOL_ORDER.filter(
    (t) => t !== "processor_events" && !completed.has(t),
  );
  if (!neededTools.length && !completed.has("processor_events")) {
    const payment = rows("payments").find((r) => r.payment_id === paymentId);
    if (payment) {
      const matches = rows("bank_transactions").filter(
        (b) =>
          b.payment_reference === payment.reference_number &&
          b.transaction_type !== "bank fee",
      );
      const missingBeyondWindow =
        !matches.length &&
        businessDays(payment.payment_date, dataset.asOf) > dataset.clearingDays;
      let unexplainedDifference = false;
      if (matches.length === 1) {
        const bank = matches[0];
        const difference = new Decimal(payment.payment_amount).minus(
          bank.amount,
        );
        if (!difference.isZero()) {
          const fee = rows("gl_entries").filter(
            (g) =>
              g.transaction_type === "bank_fee" &&
              (g.source_transaction_id === bank.bank_transaction_id ||
                g.source_transaction_id === paymentId),
          );
          const debit = fee.reduce((s, g) => s.plus(g.debit), new Decimal(0)),
            credit = fee.reduce((s, g) => s.plus(g.credit), new Decimal(0));
          unexplainedDifference = !(
            difference.gt(0) &&
            debit.eq(difference) &&
            credit.eq(difference)
          );
        }
      }
      if (
        missingBeyondWindow ||
        unexplainedDifference ||
        matches.some((b) => b.status === "returned")
      )
        neededTools.push("processor_events");
    }
  }
  const check = (
    id: string,
    label: string,
    status: VerificationCheck["status"],
    detail: string,
    records: Row[] = [],
  ) => checks.push({ id, label, status, detail, evidenceIds: ids(records) });
  if (neededTools.length) {
    check(
      "evidence-ready",
      "Required sources retrieved",
      "unknown",
      `Still need: ${neededTools.join(", ")}. ${neededTools.includes("processor_events") ? "The reconciliation checks do not yet establish a cause; obtain independent processor evidence before concluding." : "Missing queries are not evidence of missing records."}`,
    );
    return {
      outcome: "insufficient_evidence",
      findings,
      checks,
      actions,
      neededTools,
    };
  }
  const p = rows("payments").find((r) => r.payment_id === paymentId);
  if (!p) {
    check(
      "payment",
      "Payment exists",
      "failed",
      "The selected payment was not returned by the evidence source.",
    );
    return {
      outcome: "insufficient_evidence",
      findings,
      checks,
      actions,
      neededTools,
    };
  }
  const futureVendor = evidence.find(
    (e) =>
      e.table === "vendors" &&
      e.record.vendor_id === p.vendor_id &&
      e.record.updated_at &&
      parseTime(e.record.updated_at) > parseTime(dataset.asOf),
  );
  const knownVendor = rows("vendors").find((r) => r.vendor_id === p.vendor_id);
  if (futureVendor || !knownVendor) {
    check(
      "vendor-snapshot",
      "Vendor snapshot is within the observation cutoff",
      "unknown",
      "A vendor snapshot valid at the observation cutoff cannot be established.",
      [p, ...(futureVendor ? [futureVendor.record] : [])],
    );
    return {
      outcome: "insufficient_evidence",
      findings: [
        {
          id: "finding-vendor-snapshot",
          title: "Historical vendor snapshot required",
          category: "EVIDENCE_GAP",
          summary:
            "The supplier record is missing or was updated after the observation cutoff.",
          evidenceIds: ids([p]),
          contradictions: [],
          uncertainty: [
            "Obtain the vendor version valid at the observation cutoff.",
          ],
        },
      ],
      checks,
      actions,
      neededTools,
    };
  }
  const required = [
    "payments",
    "invoices",
    "payment_allocations",
    "vendors",
    "vendor_change_log",
    "bank_transactions",
    "gl_entries",
    "audit_log",
  ];
  const gaps = required.filter((t) => {
    const c = dataset.coverage[t];
    return (
      !c ||
      c.status !== "complete" ||
      parseTime(c.from) > parseTime(p.payment_date) ||
      parseTime(c.to) < parseTime(dataset.asOf)
    );
  });
  check(
    "coverage",
    "Source coverage supports absence checks",
    gaps.length ? "unknown" : "passed",
    gaps.length
      ? `Incomplete sources: ${gaps.join(", ")}. A missing row cannot establish absence.`
      : "Required sources cover the payment date through the observation cutoff.",
  );
  if (gaps.length)
    return {
      outcome: "insufficient_evidence",
      findings: [
        {
          id: "finding-coverage",
          title: "Additional source coverage required",
          category: "EVIDENCE_GAP",
          summary:
            "A supported financial conclusion requires complete source coverage.",
          evidenceIds: ids([p]),
          contradictions: [],
          uncertainty: gaps.map((t) => `Confirm ${t} coverage and rerun.`),
        },
      ],
      checks,
      actions,
      neededTools,
    };
  const bank = rows("bank_transactions").filter(
    (r) =>
      r.payment_reference === p.reference_number &&
      r.transaction_type !== "bank fee",
  );
  const allocations = rows("payment_allocations").filter(
    (r) => r.payment_id === paymentId,
  );
  const invoiceIds = new Set(allocations.map((r) => r.invoice_id));
  const invoices = rows("invoices").filter((r) => invoiceIds.has(r.invoice_id));
  const gl = rows("gl_entries").filter(
    (r) => r.source_transaction_id === paymentId,
  );
  const events = rows("audit_log").filter((r) => r.entity_id === paymentId);
  const changes = rows("vendor_change_log").filter(
    (r) =>
      r.vendor_id === p.vendor_id && r.field_changed === "bank_account_token",
  );
  const vendor = rows("vendors").find((r) => r.vendor_id === p.vendor_id);
  const currencyConflict =
    bank.some((r) => r.currency !== p.payment_currency) ||
    invoices.some((r) => r.currency !== p.payment_currency) ||
    gl.some((r) => r.currency !== p.payment_currency);
  check(
    "currency",
    "Comparable currencies",
    currencyConflict ? "unknown" : "passed",
    currencyConflict
      ? "Amounts use different currencies; no FX rate contract is supplied."
      : "All compared source amounts use the payment currency.",
    [p, ...bank, ...invoices],
  );
  const relationConflict =
    invoices.some((r) => r.vendor_id !== p.vendor_id) ||
    bank.some(
      (r) =>
        r.direction !== "debit" || !["posted", "returned"].includes(r.status),
    ) ||
    !["completed", "submitted"].includes(p.payment_status);
  if (currencyConflict || relationConflict) {
    return {
      outcome: "insufficient_evidence",
      findings: [
        {
          id: "finding-boundary",
          title: "Observation boundaries prevent comparison",
          category: "EVIDENCE_GAP",
          summary: currencyConflict
            ? "An explicit FX accounting explanation is needed."
            : "Source vendor, settlement status or direction needs further investigation.",
          evidenceIds: ids([p, ...bank]),
          contradictions: [],
          uncertainty: [
            "Confirm the observation period and comparable currency.",
          ],
        },
      ],
      checks,
      actions,
      neededTools,
    };
  }
  const add = (
    category: string,
    title: string,
    summary: string,
    records: Row[],
    action: string,
    prerequisites: string[],
    contradictions: string[] = [],
  ) => {
    findings.push({
      id: `finding-${findings.length + 1}`,
      title,
      category,
      summary,
      evidenceIds: ids(records),
      contradictions,
      uncertainty: [],
    });
    actions.push({
      id: `action-${actions.length + 1}`,
      title: action,
      description:
        "Prepare this step for finance review; FinTrace does not execute or modify payments.",
      prerequisites,
      verified: true,
    });
  };
  let anomaly = false;
  let unresolved = false;
  for (const inv of invoices) {
    const aa = rows("payment_allocations").filter(
      (a) => a.invoice_id === inv.invoice_id,
    );
    const paid = aa.filter((a) =>
      rows("payments").some(
        (q) =>
          q.payment_id === a.payment_id &&
          q.payment_status === "completed" &&
          q.settlement_status === "settled",
      ),
    );
    const total = paid.reduce(
      (s, a) => s.plus(a.allocated_amount),
      new Decimal(0),
    );
    if (total.gt(inv.invoice_total)) {
      const pp = rows("payments").filter((q) =>
        paid.some((a) => a.payment_id === q.payment_id),
      );
      const bb = rows("bank_transactions").filter(
        (b) =>
          pp.some((q) => q.reference_number === b.payment_reference) &&
          b.status === "posted" &&
          b.transaction_type !== "bank fee",
      );
      const supported =
        pp.length >= 2 &&
        pp.every((q) =>
          bb.some(
            (b) =>
              b.payment_reference === q.reference_number &&
              b.currency === q.payment_currency,
          ),
        );
      check(
        "duplicate",
        "Successful allocations do not exceed the obligation",
        supported ? "failed" : "unknown",
        `Successful allocations ${total.toFixed()} versus invoice ${inv.invoice_total}.`,
        [inv, ...paid, ...pp, ...bb],
      );
      if (supported) {
        anomaly = true;
        add(
          "F06",
          "The invoice was paid more than once",
          `Successful allocations exceed invoice ${inv.invoice_id} by ${total.minus(inv.invoice_total).toFixed()} ${inv.currency}. Distinct disbursement records support an overpayment.`,
          [inv, ...paid, ...pp, ...bb],
          "Review recovery of the excess disbursement",
          [
            "Confirm both settlements with the bank",
            "Obtain approval before any recovery or reversal",
          ],
          [
            "Multiple payments alone can be legitimate installments; the combined settled allocation exceeds the obligation.",
          ],
        );
      } else unresolved = true;
    }
  }
  const stale = changes.find(
    (c) =>
      parseTime(c.changed_at) <= parseTime(p.created_at) &&
      c.old_value === p.bank_account_id &&
      c.new_value === vendor?.bank_account_token &&
      bank.some(
        (b) => b.counterparty_token === c.old_value && b.status === "returned",
      ),
  );
  if (stale) {
    const returned = events.filter(
      (e) => e.event_type === "processor_return_received",
    );
    check(
      "vendor-version",
      "Effective vendor instructions used",
      returned.length ? "failed" : "unknown",
      "A verified banking change predates payment creation, while the returned settlement used the superseded token.",
      [p, stale, ...bank, ...returned],
    );
    if (returned.length) {
      anomaly = true;
      add(
        "F11",
        "Superseded vendor instructions caused a return",
        "The vendor history, returned settlement, and processor event support a stale payment snapshot.",
        [p, stale, ...(vendor ? [vendor] : []), ...bank, ...returned],
        "Review corrected payment instructions",
        [
          "Confirm the returned payment is not settled",
          "Re-verify vendor instructions independently",
          "Require approval before creating a replacement",
        ],
        [
          "An old token is legitimate for a payment created before its effective change; this change preceded creation.",
        ],
      );
    } else unresolved = true;
  }
  const debit = gl.reduce((s, r) => s.plus(r.debit), new Decimal(0)),
    credit = gl.reduce((s, r) => s.plus(r.credit), new Decimal(0));
  const balanced = gl.length > 0 && debit.eq(credit);
  if (!balanced) unresolved = true;
  check(
    "ledger-balance",
    "Payment journal is balanced",
    balanced ? "passed" : "unknown",
    balanced
      ? `Debit and credit both ${debit.toFixed()}.`
      : "A complete balanced payment journal has not been established.",
    gl,
  );
  if (bank.length === 0) {
    const elapsed = businessDays(p.payment_date, dataset.asOf);
    const failure = events.find((e) =>
      [
        "payment_file_not_transmitted",
        "processor_batch_rejected",
        "release_queue_timeout",
      ].includes(e.event_type),
    );
    check(
      "clearing",
      "Clearing-window explanation checked",
      elapsed > dataset.clearingDays ? "failed" : "passed",
      `${elapsed} business days observed; configured window ${dataset.clearingDays}. Bank absence is established by the successful settlement query and complete coverage.`,
      [p, ...events],
    );
    if (elapsed > dataset.clearingDays && failure && balanced) {
      anomaly = true;
      add(
        "F12",
        "Payment did not reach bank settlement",
        `The ERP payment has no bank match beyond its clearing window. Processor evidence records ${failure.event_type.replaceAll("_", " ")}.`,
        [p, ...gl, failure],
        "Review settlement state and transmission failure",
        [
          "Confirm absence with the bank",
          "Correct the documented transmission problem",
          "Obtain approval before resubmission",
        ],
        [
          "A missing bank match alone can mean normal clearing; the elapsed window and processor failure rule out that explanation.",
        ],
      );
    } else if (elapsed > dataset.clearingDays || failure || !balanced)
      unresolved = true;
  }
  if (bank.length > 1) {
    unresolved = true;
    check(
      "unique-match",
      "Unambiguous settlement link",
      "unknown",
      "Multiple ordinary settlements carry this payment reference; resolve the matching ambiguity.",
      bank,
    );
  }
  if (bank.length === 1 && !stale) {
    const b = bank[0];
    const diff = new Decimal(p.payment_amount).minus(b.amount);
    if (!diff.isZero()) {
      const fee = rows("gl_entries").filter(
        (g) =>
          g.transaction_type === "bank_fee" &&
          (g.source_transaction_id === b.bank_transaction_id ||
            g.source_transaction_id === paymentId),
      );
      const fd = fee.reduce((s, g) => s.plus(g.debit), new Decimal(0)),
        fc = fee.reduce((s, g) => s.plus(g.credit), new Decimal(0));
      const accounted = diff.gt(0) && fd.eq(diff) && fc.eq(diff);
      const net = events.find(
        (e) => e.event_type === "net_settlement_received",
      );
      check(
        "fee",
        "Settlement difference has balanced fee accounting",
        accounted ? "passed" : net ? "failed" : "unknown",
        `Payment ${p.payment_amount}; bank ${b.amount}; difference ${diff.toFixed()}.`,
        [p, b, ...fee, ...(net ? [net] : [])],
      );
      if (!accounted && net && diff.gt(0)) {
        anomaly = true;
        add(
          "F14",
          "Settlement fee has no supporting journal",
          `The processor records a net settlement difference of ${diff.toFixed()} ${p.payment_currency}, but no matching balanced fee journal exists.`,
          [p, b, net, ...gl],
          "Prepare fee-accounting review",
          [
            "Validate the processor fee",
            "Obtain approval for the fee entry",
            "Review settlement configuration",
          ],
          [
            "A net amount is legitimate when an appropriate balanced fee journal exists; none was returned in the complete ledger query.",
          ],
        );
      } else if (!accounted) unresolved = true;
    }
  }
  if (!allocations.length || !invoices.length) {
    unresolved = true;
    check(
      "allocation-link",
      "Payment has a supported obligation",
      "unknown",
      "A payment-to-invoice allocation chain is required.",
      [p, ...allocations],
    );
  }
  if (bank.some((b) => ["returned", "failed"].includes(b.status)) && !stale)
    unresolved = true;
  if (!anomaly && !unresolved) {
    check(
      "controls",
      "Selected reconciliation checks satisfied",
      "passed",
      "No supported anomaly in the four supported categories. This is not an audit of every possible financial risk.",
      [p, ...bank, ...allocations, ...gl],
    );
    findings.push({
      id: "finding-normal",
      title: bank.length
        ? "The evidence supports normal processing"
        : "The payment remains within its clearing window",
      category: "NO_FAILURE",
      summary: bank.length
        ? "Settlement, allocations, effective vendor history, and ledger checks do not establish a supported anomaly."
        : "The absent bank match is consistent with the configured clearing policy at the observation cutoff.",
      evidenceIds: ids([p, ...bank, ...allocations, ...invoices, ...gl]),
      contradictions: [
        "An initial exception or multiple payment records do not by themselves prove a failure.",
      ],
      uncertainty: [],
    });
    actions.push({
      id: "action-retain",
      title: "Retain evidence and monitor settlement",
      description:
        "Keep the investigation for review and recheck at the next observation cutoff.",
      prerequisites: ["Human review of findings"],
      verified: true,
    });
  }
  if (!anomaly && unresolved)
    findings.push({
      id: "finding-unresolved",
      title: "The available evidence does not establish a cause",
      category: "EVIDENCE_GAP",
      summary:
        "One or more financial checks could not be resolved. Do not infer a failure from a missing or contradictory record.",
      evidenceIds: ids([p, ...bank, ...events]),
      contradictions: [],
      uncertainty: checks
        .filter((c) => c.status === "unknown")
        .map((c) => c.detail),
    });
  return {
    outcome: anomaly
      ? "anomaly_supported"
      : unresolved
        ? "insufficient_evidence"
        : "no_anomaly_supported",
    findings,
    checks,
    actions,
    neededTools,
  };
}
