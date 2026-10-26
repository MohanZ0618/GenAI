import { FileStore } from "../apps/api/src/store.ts";
import { MemoryService } from "../apps/api/src/integrations/memory.ts";
import { join } from "node:path";
const directory = process.argv[2];
if (!directory) throw new Error("Provide the isolated acceptance directory");
const store = new FileStore(join(directory, "state"));
await store.init();
const runs = await store.runs();
const memory = new MemoryService(join(directory, "memory"));
console.log(
  JSON.stringify({
    processId: process.pid,
    runCount: runs.length,
    drafts: runs
      .filter((r) => r.memoryDraft)
      .map((r) => ({
        id: r.memoryDraft!.id,
        status: r.memoryDraft!.status,
        source: r.memoryDraft!.source,
        requests: r.memoryDraftRequests?.length || 0,
      })),
    memoryStates: Object.fromEntries(
      ["lesson-DUP", "lesson-STALE", "lesson-FEE"].map((n) => [
        n,
        memory
          .list(n)
          .map((m) => ({
            id: m.id,
            status: m.status,
            source: m.source,
            generationSource: m.generationSource,
            approvedAt: m.approvedAt,
          })),
      ]),
    ),
  }),
);
await store.close();
