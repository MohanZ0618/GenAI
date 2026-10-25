import { config } from "dotenv";
import { resolve } from "node:path";
import type { Mode } from "../../../packages/contracts/src/index.ts";
if (process.env.VITEST !== "true")
  config({ path: ".env.local", quiet: true } as Parameters<typeof config>[0]);
if (
  process.env.FINTRACE_MODE &&
  !["fixture", "local-model", "live"].includes(process.env.FINTRACE_MODE)
)
  throw new Error(
    "FINTRACE_MODE must be fixture, local-model, or live; execution mode will not be selected implicitly.",
  );
export const settings = {
  mode: (process.env.FINTRACE_MODE || "fixture") as Mode,
  storageDir: resolve(
    process.env.FINTRACE_STORAGE_DIR ||
      (process.env.FINTRACE_MODE === "local-model"
        ? ".local/manual-openai"
        : ".local/app"),
  ),
  port: Number(process.env.PORT || 4310),
  host: process.env.HOST || "127.0.0.1",
};
