import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import {
  loadBuiltinDatasets,
  packageToCsv,
  parseCsvPackage,
} from "../packages/data/src/index.ts";

const root = "data/manual-test";
const packet = (await loadBuiltinDatasets()).find(
  (p) => p.manifest.name === "Review packet 001",
)!;
const bundle = packageToCsv({
  ...packet,
  manifest: { ...packet.manifest, name: "Manual import sample" },
});
parseCsvPackage(bundle);
await mkdir(join(root, "csv"), { recursive: true });
await writeFile(
  join(root, "valid-bundle.json"),
  JSON.stringify(bundle, null, 2) + "\n",
);
await writeFile(
  join(root, "csv", "manifest.json"),
  JSON.stringify(bundle.manifest, null, 2) + "\n",
);
for (const [name, text] of Object.entries(bundle.files))
  await writeFile(join(root, "csv", name), text);
const revised = structuredClone(bundle);
revised.manifest.clearingDays += 1;
parseCsvPackage(revised);
await writeFile(
  join(root, "revised-bundle.json"),
  JSON.stringify(revised, null, 2) + "\n",
);
const invalid = structuredClone(bundle);
delete invalid.files["payments.csv"];
await writeFile(
  join(root, "invalid-missing-payments.json"),
  JSON.stringify(invalid, null, 2) + "\n",
);
console.log(
  `Prepared synthetic import samples in ${root}; focus payment PAY_0426017.`,
);
