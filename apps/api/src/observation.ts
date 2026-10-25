import {
  parseTime,
  type EvidenceReference,
  type TableName,
} from "../../../packages/contracts/src/index.ts";

const observationFields: Record<TableName, string[]> = {
  payments: ["payment_date", "created_at"],
  invoices: ["invoice_date", "received_date", "created_at"],
  payment_allocations: ["allocation_date"],
  bank_transactions: ["transaction_date", "posted_date"],
  gl_entries: ["posting_date"],
  audit_log: ["timestamp"],
  vendor_change_log: ["changed_at"],
  vendors: ["created_at"],
  bank_statements: ["statement_date"],
};

export function observe(evidence: EvidenceReference[], asOf: string) {
  const cutoff = parseTime(asOf);
  const visible: EvidenceReference[] = [];
  const excluded: EvidenceReference[] = [];
  for (const item of evidence) {
    const withinCutoff = observationFields[item.table].every((field) => {
      const value = item.record[field];
      return !value || parseTime(value) <= cutoff;
    });
    (withinCutoff ? visible : excluded).push(item);
  }
  return { visible, excluded };
}

// Follow obligation links in both directions so a second disbursement is retained.
export function relatedEvidence(
  evidence: EvidenceReference[],
  paymentId: string,
): EvidenceReference[] {
  const payment = evidence.find(
    (e) => e.table === "payments" && e.record.payment_id === paymentId,
  )?.record;
  if (!payment) return [];
  const allocations = evidence.filter((e) => e.table === "payment_allocations");
  const invoiceIds = new Set(
    allocations
      .filter((e) => e.record.payment_id === paymentId)
      .map((e) => e.record.invoice_id),
  );
  const paymentIds = new Set([
    paymentId,
    ...allocations
      .filter((e) => invoiceIds.has(e.record.invoice_id))
      .map((e) => e.record.payment_id),
  ]);
  const payments = evidence.filter(
    (e) => e.table === "payments" && paymentIds.has(e.record.payment_id),
  );
  const references = new Set(payments.map((e) => e.record.reference_number));
  const vendorIds = new Set(payments.map((e) => e.record.vendor_id));
  const bankIds = new Set(
    evidence
      .filter(
        (e) =>
          e.table === "bank_transactions" &&
          references.has(e.record.payment_reference),
      )
      .map((e) => e.record.bank_transaction_id),
  );
  return evidence.filter(({ table, record: r }) => {
    switch (table) {
      case "payments":
        return paymentIds.has(r.payment_id);
      case "payment_allocations":
        return paymentIds.has(r.payment_id) || invoiceIds.has(r.invoice_id);
      case "invoices":
        return (
          invoiceIds.has(r.invoice_id) ||
          (!allocations.length && vendorIds.has(r.vendor_id))
        );
      case "vendors":
      case "vendor_change_log":
        return vendorIds.has(r.vendor_id);
      case "bank_transactions":
        return references.has(r.payment_reference);
      case "gl_entries":
        return (
          paymentIds.has(r.source_transaction_id) ||
          bankIds.has(r.source_transaction_id)
        );
      case "audit_log":
        return paymentIds.has(r.entity_id) || bankIds.has(r.entity_id);
      default:
        return false;
    }
  });
}
