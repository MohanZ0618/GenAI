import { randomUUID } from "node:crypto";
export function parseZetarisResult(body: unknown): Record<string, unknown>[] {
  if (!body || typeof body !== "object" || Array.isArray(body))
    throw new Error("Unexpected Zetaris response envelope");
  const value = body as Record<string, unknown>;
  if (value.error || value.errors || value.success === false)
    throw new Error("Zetaris reported a query error");
  if (!Array.isArray(value.data))
    throw new Error("Zetaris response does not contain a data array");
  if (value.data.length === 0) return [];
  if (
    value.data.every(
      (row) => row !== null && typeof row === "object" && !Array.isArray(row),
    )
  )
    return value.data as Record<string, unknown>[];
  if (!Array.isArray(value.headers) || !value.headers.length)
    throw new Error("Zetaris matrix response has no column headers");
  const headers = value.headers.map((h) =>
    typeof h === "string"
      ? h
      : h &&
          typeof h === "object" &&
          typeof (h as { name?: unknown }).name === "string"
        ? (h as { name: string }).name
        : null,
  );
  if (headers.some((h) => !h))
    throw new Error("Zetaris response contains invalid column headers");
  return value.data.map((row) => {
    if (!Array.isArray(row) || row.length !== headers.length)
      throw new Error("Zetaris result row does not match its headers");
    return Object.fromEntries(headers.map((h, i) => [h!, row[i]]));
  });
}
export async function queryZetaris(
  sql: string,
  signal?: AbortSignal,
): Promise<Record<string, unknown>[]> {
  const base = process.env.ZETARIS_BASE_URL,
    org = process.env.ZETARIS_ORG_ID,
    token = process.env.ZETARIS_API_KEY;
  if (
    !base ||
    !/^https?:\/\/[^/]+\/?$/.test(base) ||
    !org ||
    !/^\d+$/.test(org) ||
    !token
  )
    throw new Error(
      "Zetaris UI origin, numeric organisation ID, and API key must be configured",
    );
  if (!/^SELECT\s/i.test(sql.trim()) || sql.includes(";"))
    throw new Error(
      "Investigation adapter accepts one read-only SELECT statement",
    );
  const combined = signal
    ? AbortSignal.any([signal, AbortSignal.timeout(30000)])
    : AbortSignal.timeout(30000);
  for (let attempt = 0; attempt < 2; attempt++) {
    let response: Response;
    try {
      response = await fetch(
        base.replace(/\/$/, "") + "/api/proxy/sql-editor/sqls/run-query",
        {
          method: "POST",
          signal: combined,
          headers: {
            Authorization: `Bearer ${token}`,
            "X-Org-ID": org,
            "X-Request-ID": randomUUID(),
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            sql,
            limit: 1001,
            ...(process.env.ZETARIS_ENGINE_ID
              ? { engineId: process.env.ZETARIS_ENGINE_ID }
              : {}),
          }),
        },
      );
    } catch (error) {
      if (attempt === 0 && !combined.aborted) continue;
      throw error;
    }
    if ((response.status === 429 || response.status >= 500) && attempt === 0) {
      await response.body?.cancel();
      continue;
    }
    if (!response.ok)
      throw new Error(
        `Zetaris query failed (${response.status}). No missing-record inference was made.`,
      );
    return parseZetarisResult(await response.json());
  }
  throw new Error("Zetaris retry budget exhausted");
}
