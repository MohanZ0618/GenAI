import { randomUUID } from "node:crypto";
import type {
  EvidenceReference,
  QueryTrace,
  Row,
  TableName,
  ToolName,
  Mode,
} from "../../../packages/contracts/src/index.ts";
import { recordId, tableHash, type StoredDataset } from "./store.ts";
import { queryZetaris } from "./integrations/zetaris.ts";
const tablesByTool: Record<ToolName, TableName[]> = {
  overview: ["payments", "invoices", "vendors"],
  allocations: ["payment_allocations"],
  settlements: ["bank_transactions"],
  vendor_history: ["vendor_change_log"],
  ledger: ["gl_entries"],
  processor_events: ["audit_log"],
};
export async function retrieve(
  tool: ToolName,
  dataset: StoredDataset,
  paymentId: string,
  mode: Mode,
  signal: AbortSignal,
): Promise<{ evidence: EvidenceReference[]; query: QueryTrace }> {
  const at = new Date().toISOString(),
    start = Date.now(),
    qid = randomUUID();
  const tables = tablesByTool[tool];
  const data: Partial<Record<TableName, Row[]>> = {};
  for (const table of tables) {
    signal.throwIfAborted();
    if (mode !== "live") data[table] = dataset.data.tables[table];
    else {
      const prefix = process.env.ZETARIS_TABLE_PREFIX || "FINTRACE.";
      if (!/^[A-Za-z_][A-Za-z0-9_.]*\.$/.test(prefix))
        throw new Error("Invalid Zetaris table prefix");
      const escaped = dataset.info.id.replaceAll("'", "''");
      const result = await queryZetaris(
        `SELECT record_id, payload FROM ${prefix}${table} WHERE dataset_id = '${escaped}' LIMIT 1001`,
        signal,
      );
      if (result.length > 1000)
        throw new Error(
          `Evidence query for ${table} exceeds the verified 1000-row bound; narrow the imported dataset.`,
        );
      data[table] = result.map((r) => {
        const raw = r.payload ?? r.PAYLOAD;
        if (typeof raw === "string") return JSON.parse(raw) as Row;
        if (raw && typeof raw === "object") return raw as Row;
        throw new Error("Zetaris evidence row has no valid payload");
      });
      const expected = dataset.info.tableHashes?.[table];
      if (!expected)
        throw new Error(
          "Live source integrity metadata is missing; re-import the dataset into the current application.",
        );
      if (tableHash(data[table]!) !== expected)
        throw new Error(
          `The Zetaris ${table} source does not match the immutable imported snapshot. No absence inference was made.`,
        );
    }
  }
  if (!paymentId) throw new Error("A payment identifier is required");
  // No financial facts are read from the import store in live mode. The dataset
  // identifier scopes all queries; relationships are verified from returned rows.
  const evidence: EvidenceReference[] = [];
  for (const table of tables)
    for (const [index, row] of (data[table] || []).entries()) {
      const rid = recordId(table, row, index);
      evidence.push({
        id: `${table}:${rid}`,
        table,
        recordId: rid,
        queryId: qid,
        datasetVersion: dataset.info.version,
        record: row,
      });
    }
  return {
    evidence,
    query: {
      id: qid,
      tool,
      tables,
      at,
      durationMs: Date.now() - start,
      rowCount: evidence.length,
      status: "succeeded",
      coverage: Object.fromEntries(
        tables.map((t) => [t, dataset.info.coverage[t]]),
      ),
    },
  };
}
