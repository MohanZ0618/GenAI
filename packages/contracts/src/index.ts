import { z } from "zod";
// The upstream generator emits naive ISO timestamps. This application contract
// interprets them as UTC, independent of the host computer's timezone.
export function parseTime(value: string) {
  return Date.parse(
    value.includes("T") && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
      ? value + "Z"
      : value,
  );
}

export const TABLES = [
  "vendors",
  "vendor_change_log",
  "invoices",
  "payments",
  "payment_allocations",
  "gl_entries",
  "bank_transactions",
  "bank_statements",
  "audit_log",
] as const;
export type TableName = (typeof TABLES)[number];
export type Row = Record<string, string>;
export const toolSchema = z.enum([
  "overview",
  "allocations",
  "settlements",
  "vendor_history",
  "ledger",
  "processor_events",
]);
export type ToolName = z.infer<typeof toolSchema>;
export type Mode = "fixture" | "local-model" | "live";
export type Outcome =
  | "anomaly_supported"
  | "no_anomaly_supported"
  | "insufficient_evidence";
export type Coverage = {
  status: "complete" | "partial" | "unavailable";
  from: string;
  to: string;
};
export type Dataset = {
  focusPaymentIds?: string[];
  tableHashes?: Record<string, string>;
  id: string;
  name: string;
  version: string;
  asOf: string;
  caseCount: number;
  coverage: Record<string, Coverage>;
  clearingDays: number;
  currency: string;
  createdAt: string;
  builtin: boolean;
};
export type Case = {
  id: string;
  paymentId: string;
  datasetId: string;
  vendor: string;
  amount: string;
  currency: string;
  date: string;
  symptom: string;
  status?: string;
  investigationId?: string;
  outcome?: Outcome | null;
  updateAvailable?: boolean;
};
export type EvidenceReference = {
  id: string;
  table: TableName;
  recordId: string;
  queryId: string;
  datasetVersion: string;
  record: Row;
};
export type Finding = {
  id: string;
  title: string;
  category: string;
  summary: string;
  evidenceIds: string[];
  contradictions: string[];
  uncertainty: string[];
};
export type VerificationCheck = {
  id: string;
  label: string;
  status: "passed" | "failed" | "unknown";
  detail: string;
  evidenceIds: string[];
};
export type ActionProposal = {
  id: string;
  title: string;
  description: string;
  prerequisites: string[];
  verified: boolean;
};
export type QueryTrace = {
  id: string;
  tool: ToolName;
  tables: TableName[];
  at: string;
  durationMs: number;
  rowCount: number;
  status: "succeeded" | "failed";
  error?: string;
  coverage: Record<string, Coverage>;
};
export type RunEvent = {
  id: string;
  at: string;
  type: string;
  message: string;
  tool?: ToolName;
};
export type Review = {
  decision: "accepted" | "needs_changes";
  notes: string;
  at: string;
  memoryId?: string;
};
export type ModelRequestTrace = {
  id: string;
  at: string;
  provider: string;
  model: string;
  attempt: number;
  status: "succeeded" | "failed" | "cancelled";
  durationMs: number;
  httpStatus?: number;
  requestId?: string;
  returnedModel?: string;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  errorCode?: string;
};
export const memorySuggestionSchema = z
  .object({
    hasSuggestion: z.boolean(),
    content: z.string().max(2000),
    conditions: z.string().max(2000),
    suggestedTools: z.array(toolSchema).max(6),
    evidenceIds: z.array(z.string()).max(30),
    reason: z.string().max(1000),
  })
  .strict()
  .superRefine((v, ctx) => {
    if (
      v.hasSuggestion &&
      (!v.content.trim() || !v.conditions.trim() || !v.evidenceIds.length)
    )
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Suggestion requires content, conditions and citations",
      });
  });
export type MemorySuggestion = z.infer<typeof memorySuggestionSchema>;
export type MemoryScope = "workspace" | "vendor";
export type MemoryDraft = Partial<MemorySuggestion> & {
  id: string;
  status: "generating" | "ready" | "none" | "failed";
  source: "fixture" | "model";
  provider: string;
  model: string;
  createdAt: string;
  error?: string;
};
export type ApprovedMemory = {
  id: string;
  content: string;
  source: string;
  namespace: string;
  status: "active" | "inactive";
  scope: MemoryScope;
  vendorId?: string;
  approvedAt: string;
  generationSource: "manual" | "model" | "fixture";
  draftId?: string;
  conditions: string;
  suggestedTools: ToolName[];
  evidenceIds: string[];
};
export type Investigation = {
  id: string;
  memoryNamespace?: string;
  datasetId: string;
  paymentId: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  mode: Mode;
  provider: string;
  model: string;
  createdAt: string;
  updatedAt: string;
  outcome: Outcome | null;
  findings: Finding[];
  checks: VerificationCheck[];
  actions: ActionProposal[];
  evidence: EvidenceReference[];
  events: RunEvent[];
  queries: QueryTrace[];
  error?: string;
  memories: unknown[];
  memoryDraft?: MemoryDraft;
  memoryDraftRequests?: ModelRequestTrace[];
  review?: Review;
  modelTurns: number;
  modelRequests?: ModelRequestTrace[];
};
export const startSchema = z
  .object({
    datasetId: z.string().min(1).max(100),
    paymentId: z.string().min(1).max(100),
  })
  .strict();
export const batchStartSchema = z
  .object({
    cases: z.array(startSchema).min(1).max(10000),
  })
  .strict();
export type BatchStartResult = {
  datasetId: string;
  paymentId: string;
  investigationId?: string;
  status?: Investigation["status"];
  error?: string;
};
export type BatchStartResponse = {
  results: BatchStartResult[];
  concurrency: number;
};
export const reviewSchema = z
  .object({
    decision: z.enum(["accepted", "needs_changes"]),
    notes: z.string().max(4000).default(""),
    approveMemory: z.boolean().default(false),
    memoryContent: z.string().max(2000).optional(),
    memoryDraftId: z.string().max(100).optional(),
    memoryScope: z.enum(["workspace", "vendor"]).default("workspace"),
  })
  .strict()
  .superRefine((v, ctx) => {
    if (
      v.approveMemory &&
      (!v.memoryContent?.trim() || v.decision !== "accepted")
    )
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Memory requires an accepted review and explicit content.",
      });
  });
