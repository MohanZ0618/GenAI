import { createServer } from "node:http";
import { readFile } from "node:fs/promises";

const rawPort = process.env.ZETARIS_POLICY_PORT || "4315";
if (!/^\d+$/.test(rawPort) || Number(rawPort) < 1 || Number(rawPort) > 65535)
  throw new Error("ZETARIS_POLICY_PORT must be an integer from 1 to 65535");
const policies: unknown = JSON.parse(
  await readFile(
    new URL("../data/zetaris-scoring/vendor_policy.json", import.meta.url),
    "utf8",
  ),
);
if (
  !Array.isArray(policies) ||
  policies.length !== 8 ||
  policies.some(
    (row) =>
      !row ||
      typeof row.vendor_id !== "string" ||
      !row.vendor_id.trim() ||
      typeof row.policy_id !== "string" ||
      !/^[A-Z]{3}$/.test(row.currency || ""),
  ) ||
  new Set(policies.map((row) => row.vendor_id)).size !== policies.length
)
  throw new Error(
    "Prepare and validate the eight synthetic vendor policies first",
  );

const policyBody = JSON.stringify({ data: policies });
const healthBody = JSON.stringify({
  status: "ok",
  service: "fintrace-vendor-policy",
  syntheticDataOnly: true,
  policyCount: policies.length,
});
const server = createServer((request, response) => {
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.setHeader("Cache-Control", "no-store");
  response.setHeader("X-Content-Type-Options", "nosniff");
  let body: string;
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.statusCode = 405;
    response.setHeader("Allow", "GET, HEAD");
    body = JSON.stringify({ error: "Method not allowed" });
  } else {
    let path: string;
    try {
      path = new URL(request.url || "/", "http://127.0.0.1").pathname;
    } catch {
      path = "";
    }
    if (path === "/health") body = healthBody;
    else if (path === "/vendor-policy") body = policyBody;
    else {
      response.statusCode = 404;
      body = JSON.stringify({ error: "Not found" });
    }
  }
  response.setHeader("Content-Length", Buffer.byteLength(body));
  response.end(request.method === "HEAD" ? undefined : body);
});
server.listen(Number(rawPort), "127.0.0.1", () => {
  console.log(
    JSON.stringify({
      service: "fintrace-vendor-policy",
      origin: `http://127.0.0.1:${rawPort}`,
      syntheticDataOnly: true,
      policyCount: policies.length,
    }),
  );
});
for (const signal of ["SIGINT", "SIGTERM"] as const)
  process.once(signal, () => server.close(() => process.exit(0)));
