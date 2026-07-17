import fs from "node:fs";
import path from "node:path";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const schema = JSON.parse(fs.readFileSync("case-pack.schema.json", "utf8"));
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
const validate = ajv.compile(schema);

for (const filename of fs.readdirSync("cases").filter((name) => name.endsWith(".json")).sort()) {
  const relativePath = path.join("cases", filename);
  const pack = JSON.parse(fs.readFileSync(relativePath, "utf8"));
  if (!validate(pack)) {
    console.error(`${relativePath}: ${ajv.errorsText(validate.errors, { separator: "\n" })}`);
    process.exitCode = 1;
  }
}

if (!process.exitCode) {
  console.log("Ajv validated every case pack against the neutral schema.");
}
