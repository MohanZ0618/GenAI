import { createHash } from "node:crypto";
import { join } from "node:path";
import { HMEM } from "../../../../third_party/meterless/engines/hmem/reference/src/index.ts";
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
  async recall(namespace: string, query: string) {
    const engine = this.engine(namespace);
    const matches = engine.query(query, { topN: 5, threshold: 0.15 }).memories;
    const existing = new Set(matches.map((r) => r.memory.id));
    const terms = searchTerms(query);
    const supplemental = engine.store
      .all()
      .filter(
        (m) =>
          !existing.has(m.id) &&
          !m.supersededBy &&
          m.tags.includes("approved-playbook") &&
          m.provenance.origin === "manual",
      )
      .map((memory) => {
        const words = searchTerms(memory.content);
        const overlap = [...terms].filter((word) => words.has(word)).length;
        return {
          memory,
          relevance: overlap / Math.max(1, Math.min(terms.size, words.size)),
        };
      })
      .filter((r) => r.relevance >= 0.15);
    const selected = [...matches, ...supplemental]
      .sort(
        (a, b) =>
          b.relevance - a.relevance || a.memory.id.localeCompare(b.memory.id),
      )
      .slice(0, 5);
    for (const { memory } of selected.filter(
      (r) => !existing.has(r.memory.id),
    )) {
      engine.store.touch(memory.id);
      engine.ledger.log(memory.id, "read", "fintrace-reviewer", {
        details: { query, retrieval: "local-bilingual-keywords" },
      });
    }
    return selected.map((r) => ({
      id: r.memory.id,
      content: r.memory.content,
      source: r.memory.source,
      provenance: r.memory.provenance,
      relevance: r.relevance,
    }));
  }
  async approve(namespace: string, content: string, source: string) {
    return this.engine(namespace).add({
      content,
      type: "preference",
      layer: "long_term",
      tags: ["finance", "review", "approved-playbook"],
      confidence: 1,
      source,
      provenance: {
        origin: "manual",
        learnedAt: Date.now(),
        label: "Explicitly approved by a human reviewer",
        refs: [source],
      },
    });
  }
}
