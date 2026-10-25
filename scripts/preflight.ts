import { settings } from "../apps/api/src/config.ts";
import { queryZetaris } from "../apps/api/src/integrations/zetaris.ts";
import {
  createModelProvider,
  modelConfiguration,
} from "../apps/api/src/integrations/model.ts";
import type { Mode } from "../packages/contracts/src/index.ts";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import pg from "pg";

export async function runPreflight(
  mode: Mode,
  connect = false,
  env: NodeJS.ProcessEnv = process.env,
) {
  const modelEnv = { ...env, FINTRACE_MODE: mode };
  let modelConfigured = false;
  try {
    const config = modelConfiguration(modelEnv);
    modelConfigured = !!(config.token?.trim() && config.model?.trim());
  } catch {
    /* Invalid providers are reported as missing configuration below. */
  }
  const configured = {
    database: !!env.DATABASE_URL,
    zetaris: !!(
      env.ZETARIS_BASE_URL &&
      env.ZETARIS_ORG_ID &&
      env.ZETARIS_API_KEY
    ),
    model: modelConfigured,
  };
  const required: (keyof typeof configured)[] =
    mode === "fixture"
      ? []
      : mode === "local-model"
        ? ["model"]
        : ["database", "zetaris", "model"];
  let ok = required.every((key) => configured[key]);
  const checks: Record<string, unknown> = {};
  if (connect && mode === "live") {
    if (configured.database) {
      const pool = new pg.Pool({
        connectionString: env.DATABASE_URL,
        connectionTimeoutMillis: 5000,
      });
      try {
        await pool.query("SELECT 1");
        checks.database = "connected";
      } catch {
        checks.database = "failed";
        ok = false;
      } finally {
        await pool.end();
      }
    }
    if (configured.zetaris) {
      try {
        await queryZetaris("SELECT 1");
        checks.zetaris = "query succeeded";
      } catch {
        checks.zetaris =
          "failed; verify UI origin, key, organisation, and response format";
        ok = false;
      }
    }
  }
  if (connect && mode !== "fixture" && configured.model) {
    try {
      const provider = createModelProvider(modelEnv);
      await provider.next(
        {
          paymentId: "preflight",
          context: { availableTools: ["overview"] },
          history: [],
          memories: [],
        },
        AbortSignal.timeout(90000),
      );
      checks.model = {
        status: "responded",
        provider: provider.name,
        model: provider.model,
      };
    } catch {
      checks.model =
        "failed; verify selected provider credentials, model access, network, and API quota";
      ok = false;
    }
  }
  return {
    ok,
    mode,
    required,
    configured,
    checks,
    notice:
      mode === "fixture"
        ? "Offline fixture mode requires no external services; no connections were attempted."
        : connect
          ? "Only services required by this mode were checked. Model checks make a small billable API call. Credentials are never printed."
          : "Configuration-only check; use --live to connect to services required by this mode. Credentials are never printed.",
  };
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(resolve(process.argv[1])).href
) {
  const result = await runPreflight(
    settings.mode,
    process.argv.includes("--live"),
  );
  console.log(JSON.stringify(result, null, 2));
  if (!result.ok) process.exitCode = 1;
}
