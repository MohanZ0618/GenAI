import {
  TABLES,
  type EvidenceReference,
  type TableName,
} from "../../../packages/contracts/src/index.ts";
import { observe, relatedEvidence } from "./observation.ts";

export const CONTEXT_BUDGET_BYTES = 24 * 1024;
const fields: Record<TableName, string[]> = {
  payments: [
    "payment_id",
    "vendor_id",
    "payment_date",
    "created_at",
    "payment_currency",
    "payment_amount",
    "payment_status",
    "settlement_status",
    "reference_number",
    "bank_account_id",
  ],
  invoices: [
    "invoice_id",
    "vendor_id",
    "invoice_date",
    "created_at",
    "invoice_total",
    "currency",
  ],
  vendors: ["vendor_id", "bank_account_token", "created_at", "updated_at"],
  payment_allocations: [
    "payment_id",
    "invoice_id",
    "allocated_amount",
    "allocation_date",
  ],
  bank_transactions: [
    "bank_transaction_id",
    "payment_reference",
    "transaction_date",
    "posted_date",
    "amount",
    "currency",
    "direction",
    "status",
    "counterparty_token",
    "transaction_type",
  ],
  vendor_change_log: [
    "change_id",
    "vendor_id",
    "field_changed",
    "old_value",
    "new_value",
    "changed_at",
  ],
  gl_entries: [
    "journal_line_id",
    "journal_id",
    "source_transaction_id",
    "transaction_type",
    "posting_date",
    "debit",
    "credit",
    "currency",
  ],
  audit_log: [
    "event_id",
    "entity_id",
    "entity_type",
    "event_type",
    "timestamp",
  ],
  bank_statements: [],
};

export function planningEvidence(
  evidence: EvidenceReference[],
  paymentId: string,
  asOf: string,
) {
  const related = relatedEvidence(evidence, paymentId);
  const { visible, excluded } = observe(related, asOf);
  const groups = TABLES.map((table) =>
    visible.filter((e) => e.table === table),
  );
  const selected: EvidenceReference[] = [];
  let bytes = 2;
  // Round-robin prevents a large payment table from starving other sources.
  while (groups.some((group) => group.length)) {
    for (const group of groups) {
      const item = group.shift();
      if (!item) continue;
      const candidate = {
        ...item,
        record: Object.fromEntries(
          fields[item.table]
            .filter((key) => key in item.record)
            .map((key) => [key, item.record[key]]),
        ),
      };
      const size =
        Buffer.byteLength(JSON.stringify(candidate), "utf8") +
        (selected.length ? 1 : 0);
      if (bytes + size <= CONTEXT_BUDGET_BYTES) {
        selected.push(candidate);
        bytes += size;
      }
    }
  }
  return {
    evidence: selected,
    bytes,
    related: related.length,
    sent: selected.length,
    omitted: visible.length - selected.length,
    excludedFuture: excluded.length,
  };
}
