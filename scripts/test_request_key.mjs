import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { webcrypto } from "node:crypto";
import ts from "../apps/web/node_modules/typescript/lib/typescript.js";

const source = ts.transpileModule(readFileSync(new URL("../apps/web/src/requestKey.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const http = { exports: {}, crypto: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) }, Uint8Array };
runInNewContext(source, http);
const keys = Array.from({ length: 1000 }, () => http.exports.requestKey());
assert.equal(new Set(keys).size, 1000);
for (const key of keys) assert.match(key, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
const https = { exports: {}, crypto: { randomUUID: () => "native-request-key" } };
runInNewContext(source, https);
assert.equal(https.exports.requestKey(), "native-request-key");
console.log("通过：HTTP安全随机数兼容、重复提交标记唯一性与HTTPS原生路径。");
