import { mkdir, readFile, writeFile, rename, readdir } from "node:fs/promises";
import { join } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { setTimeout as delay } from "node:timers/promises";
import pg from "pg";
import type {
  Dataset,
  Investigation,
  Row,
  TableName,
} from "../../../packages/contracts/src/index.ts";
import { TABLES } from "../../../packages/contracts/src/index.ts";
import type { DatasetPackage } from "../../../packages/data/src/index.ts";

export type StoredDataset = { info: Dataset; data: DatasetPackage };
export interface Store {
  init(): Promise<void>;
  datasets(): Promise<StoredDataset[]>;
  dataset(id: string): Promise<StoredDataset | undefined>;
  setDatasetRemoved(id: string, removed: boolean): Promise<void>;
  saveDataset(data: DatasetPackage, builtin?: boolean): Promise<StoredDataset>;
  saveRun(run: Investigation): Promise<void>;
  run(id: string): Promise<Investigation | undefined>;
  runs(): Promise<Investigation[]>;
  close(): Promise<void>;
}
function metadata(data: DatasetPackage, builtin: boolean): Dataset {
  const version = createHash("sha256")
    .update(JSON.stringify(data))
    .digest("hex");
  return {
    id: `ds-${version.slice(0, 16)}`,
    version,
    name: data.manifest.name,
    asOf: data.manifest.asOf,
    clearingDays: data.manifest.clearingDays,
    currency: data.manifest.currency,
    coverage: data.manifest.coverage,
    caseCount: data.tables.payments.length,
    createdAt: new Date().toISOString(),
    builtin,
    focusPaymentIds: data.manifest.focusPaymentIds,
    tableHashes: Object.fromEntries(
      TABLES.map((t) => [t, tableHash(data.tables[t])]),
    ),
  };
}
export function tableHash(rows: Row[]) {
  const canonical = rows
    .map((row) =>
      JSON.stringify(
        Object.fromEntries(
          Object.entries(row).sort(([a], [b]) => a.localeCompare(b)),
        ),
      ),
    )
    .sort()
    .join("\n");
  return createHash("sha256").update(canonical).digest("hex");
}
const safeId = (id: string) => {
  if (!/^[a-zA-Z0-9_-]{1,100}$/.test(id))
    throw new Error("Invalid object identifier");
  return id;
};
export class FileStore implements Store {
  private writes = new Map<string, Promise<void>>();
  constructor(readonly root: string) {}
  async init() {
    await Promise.all(
      ["datasets", "runs"].map((p) =>
        mkdir(join(this.root, p), { recursive: true }),
      ),
    );
  }
  async get<T>(kind: string, id: string): Promise<T | undefined> {
    try {
      return JSON.parse(
        await readFile(join(this.root, kind, safeId(id) + ".json"), "utf8"),
      );
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code === "ENOENT") return undefined;
      throw e;
    }
  }
  async all<T>(kind: string): Promise<T[]> {
    const names = await readdir(join(this.root, kind));
    return Promise.all(
      names
        .filter((n) => n.endsWith(".json"))
        .sort()
        .map((n) => this.get<T>(kind, n.slice(0, -5)) as Promise<T>),
    );
  }
  async put(kind: string, id: string, value: unknown) {
    const path = join(this.root, kind, safeId(id) + ".json");
    const serialized = JSON.stringify(value, null, 2);
    const previous = this.writes.get(path) || Promise.resolve();
    const writing = previous
      .catch(() => {})
      .then(async () => {
        const temp = path + "." + randomUUID() + ".tmp";
        await writeFile(temp, serialized);
        for (let attempt = 0; ; attempt++) {
          try {
            await rename(temp, path);
            break;
          } catch (e) {
            if (
              attempt >= 7 ||
              !["EPERM", "EACCES", "EBUSY"].includes(
                (e as NodeJS.ErrnoException).code || "",
              )
            )
              throw e;
            await delay(10 * 2 ** attempt);
          }
        }
      });
    this.writes.set(path, writing);
    try {
      await writing;
    } finally {
      if (this.writes.get(path) === writing) this.writes.delete(path);
    }
  }
  datasets() {
    return this.all<StoredDataset>("datasets");
  }
  dataset(id: string) {
    return this.get<StoredDataset>("datasets", id);
  }
  async setDatasetRemoved(id: string, removed: boolean) {
    const dataset = await this.dataset(id);
    if (!dataset) throw new Error("Dataset not found");
    dataset.info.removedAt = removed
      ? dataset.info.removedAt || new Date().toISOString()
      : null;
    await this.put("datasets", id, dataset);
  }
  async saveDataset(data: DatasetPackage, builtin = false) {
    const info = metadata(data, builtin);
    const existing = await this.dataset(info.id);
    if (existing) return existing;
    const item = { info, data };
    await this.put("datasets", info.id, item);
    return item;
  }
  saveRun(run: Investigation) {
    return this.put("runs", run.id, run);
  }
  run(id: string) {
    return this.get<Investigation>("runs", id);
  }
  runs() {
    return this.all<Investigation>("runs");
  }
  async close() {}
}
export class PostgresStore implements Store {
  readonly pool: pg.Pool;
  constructor(url: string) {
    this.pool = new pg.Pool({
      connectionString: url,
      connectionTimeoutMillis: 5000,
    });
  }
  async init() {
    await this.pool.query(
      "CREATE SCHEMA IF NOT EXISTS fintrace_app; CREATE SCHEMA IF NOT EXISTS fintrace_finance; CREATE SCHEMA IF NOT EXISTS fintrace_source; CREATE TABLE IF NOT EXISTS fintrace_app.datasets(id text PRIMARY KEY, info jsonb NOT NULL); CREATE TABLE IF NOT EXISTS fintrace_app.runs(id text PRIMARY KEY, payload jsonb NOT NULL)",
    );
    for (const table of TABLES) {
      await this.pool.query(
        `CREATE TABLE IF NOT EXISTS fintrace_finance.${table}(dataset_id text NOT NULL REFERENCES fintrace_app.datasets(id),record_id text NOT NULL,payload jsonb NOT NULL,PRIMARY KEY(dataset_id,record_id)); CREATE OR REPLACE VIEW fintrace_source.${table} AS SELECT dataset_id,record_id,payload::text AS payload FROM fintrace_finance.${table}`,
      );
    }
  }
  async datasets() {
    const result = await this.pool.query(
      "SELECT id FROM fintrace_app.datasets ORDER BY id",
    );
    return Promise.all(
      result.rows.map((r) => this.dataset(r.id) as Promise<StoredDataset>),
    );
  }
  async setDatasetRemoved(id: string, removed: boolean) {
    const result = await this.pool.query(
      "UPDATE fintrace_app.datasets SET info=jsonb_set(info,'{removedAt}', CASE WHEN $2::boolean THEN COALESCE(NULLIF(info->'removedAt','null'::jsonb),to_jsonb($3::text)) ELSE 'null'::jsonb END) WHERE id=$1",
      [id, removed, new Date().toISOString()],
    );
    if (!result.rowCount) throw new Error("Dataset not found");
  }
  async dataset(id: string): Promise<StoredDataset | undefined> {
    const r = await this.pool.query(
      "SELECT info FROM fintrace_app.datasets WHERE id=$1",
      [id],
    );
    if (!r.rowCount) return undefined;
    const tables: Record<string, Row[]> = {};
    for (const t of TABLES) {
      tables[t] = (
        await this.pool.query(
          `SELECT payload FROM fintrace_finance.${t} WHERE dataset_id=$1 ORDER BY record_id`,
          [id],
        )
      ).rows.map((r) => r.payload);
    }
    const info = r.rows[0].info as Dataset;
    return {
      info,
      data: {
        manifest: {
          focusPaymentIds: info.focusPaymentIds,
          name: info.name,
          asOf: info.asOf,
          clearingDays: info.clearingDays,
          currency: info.currency,
          coverage: info.coverage,
        },
        tables,
      },
    };
  }
  async saveDataset(data: DatasetPackage, builtin = false) {
    const info = metadata(data, builtin);
    const client = await this.pool.connect();
    try {
      await client.query("BEGIN");
      const inserted = await client.query(
        "INSERT INTO fintrace_app.datasets(id,info) VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING id",
        [info.id, info],
      );
      if (inserted.rowCount)
        for (const table of TABLES) {
          const records = data.tables[table].map((row, index) => ({
            record_id: recordId(table, row, index),
            payload: row,
          }));
          await client.query(
            `INSERT INTO fintrace_finance.${table}(dataset_id,record_id,payload) SELECT $1, entry.record_id, entry.payload FROM jsonb_to_recordset($2::jsonb) AS entry(record_id text,payload jsonb)`,
            [info.id, JSON.stringify(records)],
          );
        }
      await client.query("COMMIT");
      return (await this.dataset(info.id))!;
    } catch (e) {
      await client.query("ROLLBACK");
      throw e;
    } finally {
      client.release();
    }
  }
  async saveRun(run: Investigation) {
    await this.pool.query(
      "INSERT INTO fintrace_app.runs(id,payload) VALUES($1,$2) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
      [run.id, run],
    );
  }
  async run(id: string) {
    return (
      await this.pool.query(
        "SELECT payload FROM fintrace_app.runs WHERE id=$1",
        [id],
      )
    ).rows[0]?.payload as Investigation | undefined;
  }
  async runs() {
    return (
      await this.pool.query("SELECT payload FROM fintrace_app.runs")
    ).rows.map((r) => r.payload as Investigation);
  }
  async close() {
    await this.pool.end();
  }
}
export function recordId(table: TableName, row: Row, index = 0) {
  const keys: Record<TableName, string> = {
    vendors: "vendor_id",
    vendor_change_log: "change_id",
    invoices: "invoice_id",
    payments: "payment_id",
    payment_allocations: "",
    gl_entries: "journal_line_id",
    bank_transactions: "bank_transaction_id",
    bank_statements: "bank_statement_id",
    audit_log: "event_id",
  };
  return table === "payment_allocations"
    ? `${row.payment_id}:${row.invoice_id}:${row.allocation_date}`
    : row[keys[table]] || `row-${index}`;
}
