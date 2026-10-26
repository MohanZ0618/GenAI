import { mkdir, writeFile } from "node:fs/promises";
import { buildManualPackets } from "./prepare_openai_manual.ts";
import { packageToCsv, parseCsvPackage } from "../packages/data/src/index.ts";
const directory = ".local/hmem-demo";
await mkdir(directory, { recursive: true });
const packet = buildManualPackets().main;
packet.manifest.name = "H-MEM competition demo";
packet.manifest.focusPaymentIds = ["PAY_DEMO_STALE"];
for (let version = 1; version <= 3; version++) {
  if (version > 1)
    packet.tables.audit_log.push({
      ...packet.tables.audit_log.find(
        (row) => row.entity_id === "PAY_DEMO_STALE",
      )!,
      event_id: `EVT_HMEM_REVIEW_NOTE_${version}`,
      event_type: "review_note_added",
      timestamp: packet.manifest.asOf,
    });
  const bundle = packageToCsv(packet);
  parseCsvPackage(bundle);
  await writeFile(
    `${directory}/0${version}-version.json`,
    JSON.stringify(bundle, null, 2),
  );
}
console.log(
  `Prepared three immutable synthetic demo versions in ${directory}; import in order and explicitly update investigations. No model called.`,
);
