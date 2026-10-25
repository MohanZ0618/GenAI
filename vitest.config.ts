import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    env: { FINTRACE_MODE: "fixture", MODEL_PROVIDER: "openai" },
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.ts", "packages/data/**/*.test.ts"],
    testTimeout: 15000,
    fileParallelism: false,
  },
});
