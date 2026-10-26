import { createHash } from "node:crypto";
import { join } from "node:path";
import { HMEM } from "../../../../third_party/meterless/engines/hmem/reference/src/index.ts";
import type {
  ApprovedMemory,
  MemoryScope,
  ToolName,
} from "../../../../packages/contracts/src/index.ts";
import type { MemoryRecord } from "../../../../third_party/meterless/engines/hmem/reference/src/types.ts";
type Metadata = Omit<ApprovedMemory, "id" | "content" | "source" | "namespace">;
const prefix = "fintrace-meta:";
function metadata(record: MemoryRecord): Metadata {
  const tag = record.tags.find((t) => t.startsWith(prefix));
  const defaults: Metadata = {
    status: "active",
    scope: "workspace",
    approvedAt: new Date(record.timestamp).toISOString(),
    generationSource: "manual",
    conditions: "",
    suggestedTools: [],
    evidenceIds: [],
  };
  return { ...defaults, ...(tag ? JSON.parse(tag.slice(prefix.length)) : {}) };
}
const concepts: Record<string, string[]> = {
  payment: ["付款", "支付"],
  invoice: ["发票"],
  vendor: ["供应商"],
  history: ["变更", "历史"],
  ledger: ["账本", "分录", "总账"],
  settlement: ["结算", "清算"],
  review: ["审核", "复核", "检查"],
  fee: ["费用", "手续费"],
  duplicate: ["重复", "多付"],
  allocation: ["分配"],
  investigation: ["调查", "取证"],
};
function searchTerms(text: string) {
  const normalized = text.normalize("NFKC").toLowerCase();
  const terms = new Set(normalized.match(/[a-z0-9]+/g) || []);
  for (const [concept, translations] of Object.entries(concepts))
    if (translations.some((word) => normalized.includes(word)))
      terms.add(concept);
  for (const part of normalized.match(/[\p{Script=Han}]+/gu) || [])
    for (let i = 0; i < part.length - 1; i++) terms.add(part.slice(i, i + 2));
  return terms;
}
export class MemoryService {
  private engines = new Map<string, HMEM>();
  constructor(private storageDir: string) {}
  private engine(namespace: string) {
    let e = this.engines.get(namespace);
    if (!e) {
      e = new HMEM({
        persistDir: join(
          this.storageDir,
          createHash("sha256").update(namespace).digest("hex"),
        ),
        actor: "fintrace-reviewer",
      });
      this.engines.set(namespace, e);
    }
    return e;
  }
  list(namespace = "workspace"): ApprovedMemory[] {
    return this.engine(namespace)
      .store.all()
      .filter(
        (m) =>
          m.tags.includes("approved-playbook") &&
          m.provenance.origin === "manual",
      )
      .map((m) => ({
        id: m.id,
        content: m.content,
        source: m.source,
        namespace,
        ...metadata(m),
      }));
  }
  setStatus(namespace: string, id: string, status: "active" | "inactive") {
    const engine = this.engine(namespace),
      m = engine.store.get(id);
    if (!m || !m.tags.includes("approved-playbook"))
      throw new Error("Memory not found");
    engine.store.update(id, {
      tags: [
        ...m.tags.filter((t) => !t.startsWith(prefix)),
        prefix + JSON.stringify({ ...metadata(m), status }),
      ],
    });
    engine.ledger.log(
      id,
      status === "active" ? "restore" : "feedback",
      "fintrace-reviewer",
      { details: { status } },
    );
    return this.list(namespace).find((r) => r.id === id)!;
  }
  async recall(namespace: string, query: string, vendorId?: string) {
    const engine = this.engine(namespace);
    const eligible = engine.store.all().filter((m) => {
      const meta = metadata(m);
      return (
        !m.supersededBy &&
        m.tags.includes("approved-playbook") &&
        m.provenance.origin === "manual" &&
        meta.status === "active" &&
        (meta.scope === "workspace" ||
          (!!vendorId && meta.vendorId === vendorId))
      );
    });
    // Score only eligible records: excluded entries must not receive read ledger events.
    const hashed = eligible.map((memory) => ({
      memory,
      relevance: engine.retrieval.scoreOne(memory, query),
    }));
    const terms = searchTerms(query);
    const selected = eligible
      .map((memory) => {
        const meta = metadata(memory),
          words = searchTerms(
            [memory.content, meta.conditions, ...meta.suggestedTools].join(" "),
          );
        const matchedTerms = [...terms].filter((t) => words.has(t));
        const hashScore =
          hashed.find((r) => r.memory.id === memory.id)?.relevance || 0;
        return {
          memory,
          meta,
          matchedTerms,
          hashScore,
          relevance: Math.max(
            hashScore,
            matchedTerms.length / Math.max(1, Math.min(terms.size, words.size)),
          ),
        };
      })
      .filter((r) => r.relevance >= 0.15)
      .sort(
        (a, b) =>
          b.relevance - a.relevance || a.memory.id.localeCompare(b.memory.id),
      )
      .slice(0, 5);
    const snapshots = selected.map(
      ({ memory, meta, matchedTerms, relevance, hashScore }) => {
        engine.store.touch(memory.id);
        const explanation = {
          matchedTerms,
          scope: meta.scope,
          vendorId: meta.vendorId,
          suggestedTools: meta.suggestedTools,
          retrieval: "local-hash-and-bilingual-keywords",
          hashMatched: hashScore >= 0.15,
        };
        engine.ledger.log(memory.id, "read", "fintrace-planner", {
          details: { query, ...explanation },
        });
        return {
          id: memory.id,
          content: memory.content,
          source: memory.source,
          provenance: memory.provenance,
          relevance,
          ...meta,
          explanation,
          providedToPlanner: true,
        };
      },
    );
    engine.store.persist();
    return structuredClone(snapshots);
  }
  async approve(
    namespace: string,
    content: string,
    source: string,
    options: {
      scope?: MemoryScope;
      vendorId?: string;
      draftId?: string;
      generationSource?: Metadata["generationSource"];
      conditions?: string;
      suggestedTools?: ToolName[];
      evidenceIds?: string[];
    } = {},
  ) {
    const engine = this.engine(namespace);
    const meta: Metadata = {
      status: "active",
      scope: options.scope || "workspace",
      vendorId: options.vendorId,
      approvedAt: new Date().toISOString(),
      generationSource: options.generationSource || "manual",
      draftId: options.draftId,
      conditions: options.conditions || "",
      suggestedTools: options.suggestedTools || [],
      evidenceIds: options.evidenceIds || [],
    };
    const existing = this.list(namespace).find(
      (m) =>
        m.source === source &&
        m.content === content &&
        m.scope === meta.scope &&
        m.vendorId === meta.vendorId,
    );
    if (existing) return engine.store.get(existing.id)!;
    const record = engine.add({
      content,
      type: "preference",
      layer: "long_term",
      tags: [
        "finance",
        "review",
        "approved-playbook",
        prefix + JSON.stringify(meta),
      ],
      confidence: 1,
      source,
      provenance: {
        origin: "manual",
        learnedAt: Date.now(),
        label: "Explicitly approved by a human reviewer",
        refs: [source, ...(options.draftId ? [options.draftId] : [])],
      },
    });
    engine.ledger.log(record.id, "feedback", "fintrace-reviewer", {
      details: { approval: "explicit", ...meta },
    });
    return record;
  }
}
