import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { parse } from "csv-parse/sync";
import { z } from "zod";
import Decimal from "decimal.js";
import schema from "./schema.json";
import { TABLES, type Row, type Coverage } from "../../contracts/src/index.ts";
export const TABLE_NAMES = TABLES;
export type { Row };
const validDate = (s: string) =>
  /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(s) &&
  Number.isFinite(Date.parse(s)) &&
  new Date(s.slice(0, 10) + "T00:00:00Z").toISOString().slice(0, 10) ===
    s.slice(0, 10);
const iso = z.string().refine(validDate, "Expected a valid ISO calendar date");
const coverageSchema = z
  .object({
    status: z.enum(["complete", "partial", "unavailable"]),
    from: iso,
    to: iso,
  })
  .strict()
  .refine(
    (v) => Date.parse(v.from) <= Date.parse(v.to),
    "Coverage dates are reversed",
  );
const manifestSchema = z
  .object({
    name: z.string().min(1).max(120),
    asOf: iso,
    clearingDays: z.number().int().min(0).max(60),
    currency: z.string().regex(/^[A-Z]{3}$/),
    coverage: z.record(coverageSchema),
    focusPaymentIds: z.array(z.string().min(1)).optional(),
  })
  .strict();
export type DatasetPackage = {
  manifest: z.infer<typeof manifestSchema>;
  tables: Record<string, Row[]>;
};
export class ImportError extends Error {
  constructor(public issues: string[]) {
    super(issues.slice(0, 30).join("\n"));
    this.name = "ImportError";
  }
}
export function parseCsvPackage(input: {
  manifest: unknown;
  files: Record<string, string>;
}): DatasetPackage {
  return parsePackage(input, 1000);
}
function parsePackage(
  input: { manifest: unknown; files: Record<string, string> },
  rowLimit: number,
): DatasetPackage {
  const parsed = manifestSchema.safeParse(input.manifest);
  if (!parsed.success)
    throw new ImportError(
      parsed.error.issues.map(
        (i) => `manifest.${i.path.join(".")}: ${i.message}`,
      ),
    );
  const tables: Record<string, Row[]> = {};
  const issues: string[] = [];
  for (const table of TABLES) {
    const spec = schema[table];
    const file = input.files[`${table}.csv`];
    if (typeof file !== "string") {
      issues.push(`${table}.csv: required file missing`);
      continue;
    }
    try {
      const records = parse(file, {
        bom: true,
        skip_empty_lines: true,
        columns: false,
        relax_column_count: false,
      }) as string[][];
      const header = records.shift() || [];
      if (
        header.length !== spec.columns.length ||
        new Set(header).size !== header.length ||
        spec.columns.some((c) => !header.includes(c))
      ) {
        issues.push(`${table}.csv: headers must exactly match the template`);
        continue;
      }
      if (records.length > rowLimit) {
        issues.push(
          `${table}.csv: maximum ${rowLimit} rows exceeded; split the dataset into smaller review packets`,
        );
        continue;
      }
      const keys = new Set<string>();
      tables[table] = records.map((values, index) => {
        const row = Object.fromEntries(header.map((h, i) => [h, values[i]]));
        const line = index + 2;
        const key = spec.primaryKey.map((k) => row[k]).join(":");
        if (spec.primaryKey.some((k) => !row[k]))
          issues.push(`${table}.csv:${line}: missing primary key`);
        if (keys.has(key))
          issues.push(`${table}.csv:${line}: duplicate primary key ${key}`);
        keys.add(key);
        const requiredFields =
          table === "payments"
            ? [
                "vendor_id",
                "payment_date",
                "created_at",
                "payment_currency",
                "reference_number",
                "payment_status",
                "settlement_status",
              ]
            : table === "invoices"
              ? ["vendor_id", "invoice_date", "currency"]
              : table === "bank_transactions"
                ? [
                    "bank_account_id",
                    "transaction_date",
                    "posted_date",
                    "currency",
                    "direction",
                    "status",
                  ]
                : table === "vendor_change_log"
                  ? ["vendor_id", "field_changed", "changed_at"]
                  : table === "audit_log"
                    ? ["entity_id", "entity_type", "event_type", "timestamp"]
                    : table === "gl_entries"
                      ? [
                          "journal_id",
                          "source_transaction_id",
                          "posting_date",
                          "currency",
                        ]
                      : [];
        for (const field of requiredFields)
          if (!row[field]?.trim())
            issues.push(
              `${table}.csv:${line}:${field}: required value is empty`,
            );
        for (const field of spec.money) {
          if (
            !/^-?\d+(?:\.\d{1,2})?$/.test(row[field]) ||
            !new Decimal(row[field]).isFinite()
          )
            issues.push(
              `${table}.csv:${line}:${field}: expected an exact decimal with at most two fractional digits`,
            );
        }
        for (const [key, value] of Object.entries(row)) {
          if (value.length > 4000)
            issues.push(
              `${table}.csv:${line}:${key}: field exceeds 4000 characters`,
            );
          if (
            value &&
            /(?:_date|_at|timestamp)$/.test(key) &&
            !validDate(value)
          )
            issues.push(`${table}.csv:${line}:${key}: invalid ISO date`);
          if (
            value &&
            (key === "currency" || key === "payment_currency") &&
            !/^[A-Z]{3}$/.test(value)
          )
            issues.push(
              `${table}.csv:${line}:${key}: expected uppercase currency code`,
            );
        }
        return row;
      });
    } catch (e) {
      issues.push(
        `${table}.csv: ${e instanceof Error ? e.message : "CSV could not be parsed"}`,
      );
    }
    if (!parsed.data.coverage[table])
      issues.push(`manifest.coverage.${table}: required`);
  }
  if (issues.length) throw new ImportError(issues);
  const ids = (table: string, key: string) =>
    new Set(tables[table].map((r) => r[key]));
  const vendors = ids("vendors", "vendor_id"),
    payments = ids("payments", "payment_id"),
    invoices = ids("invoices", "invoice_id");
  for (const table of ["payments", "invoices", "vendor_change_log"])
    tables[table].forEach((r, i) => {
      if (!vendors.has(r.vendor_id))
        issues.push(`${table}.csv:${i + 2}: unknown vendor_id ${r.vendor_id}`);
    });
  tables.payment_allocations.forEach((r, i) => {
    if (!payments.has(r.payment_id) || !invoices.has(r.invoice_id))
      issues.push(
        `payment_allocations.csv:${i + 2}: missing related payment or invoice`,
      );
  });
  for (const pid of parsed.data.focusPaymentIds || [])
    if (!payments.has(pid))
      issues.push(`manifest.focusPaymentIds: unknown payment ${pid}`);
  for (const key of Object.keys(input.files))
    if (!TABLES.some((t) => key === `${t}.csv`))
      issues.push(`${key}: unsupported table`);
  if (issues.length) throw new ImportError(issues);
  return { manifest: parsed.data, tables };
}
export function csv(rows: Row[], columns: string[]): string {
  const q = (s: string) =>
    /[",\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
  return (
    [
      columns.map(q).join(","),
      ...rows.map((r) => columns.map((c) => q(r[c] ?? "")).join(",")),
    ].join("\r\n") + "\r\n"
  );
}
export function packageToCsv(data: DatasetPackage) {
  return {
    manifest: data.manifest,
    files: Object.fromEntries(
      TABLES.map((t) => [`${t}.csv`, csv(data.tables[t], schema[t].columns)]),
    ),
  };
}
export async function loadBuiltinDatasets(): Promise<DatasetPackage[]> {
  const packets = JSON.parse(
    await readFile(resolve("data/builtin.json"), "utf8"),
  ) as DatasetPackage[];
  // Preserve shipped historical packets; only new user imports use the live-compatible bound.
  return packets.map((p) => parsePackage(packageToCsv(p), 10000));
}
export function getTemplates() {
  const coverage = Object.fromEntries(
    TABLES.map((t) => [
      t,
      {
        status: "unavailable",
        from: "2026-01-01T00:00:00Z",
        to: "2026-06-30T23:59:59Z",
      },
    ]),
  ) as Record<string, Coverage>;
  return {
    manifest: {
      name: "My payment review",
      asOf: "2026-06-30T23:59:59Z",
      clearingDays: 10,
      currency: "USD",
      coverage,
    },
    files: Object.fromEntries(
      TABLES.map((t) => [`${t}.csv`, csv([], schema[t].columns)]),
    ),
  };
}
