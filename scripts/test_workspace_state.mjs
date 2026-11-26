import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "../apps/web/node_modules/typescript/lib/typescript.js";

const code = ts.transpileModule(
  readFileSync(
    new URL("../apps/web/src/workspaceState.ts", import.meta.url),
    "utf8",
  ),
  {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
    },
  },
).outputText;
const { readSelection, selectionChange, selectionUrl, defaultSelection } =
  await import(
    "data:text/javascript;base64," + Buffer.from(code).toString("base64")
  );
const old = readSelection(
  "?workspace=site&tab=rsi&ml_model=model_foreign&ml_prediction=prediction_foreign&ml_date=2026-01-20&ml_slot=48",
);
assert.equal(old.source, "station:lanneng:synthetic");
for (const field of ["date", "model", "record"]) assert.equal(old[field], "");
assert.equal(old.slot, null);
assert.equal(readSelection("?workspace=site&tab=connections").tab, "flow");
assert.equal(readSelection("?tab=removed-page").tab, "overview");
const selected = {
  ...defaultSelection,
  date: "2026-01-20",
  model: "private-model",
  record: "private-record",
  slot: 48,
};
const taskChanged = selectionChange(
  { ...selected, task: "rt_price_day_ahead_reference" },
  { type: "task", task: "pv_day_ahead_reference" },
);
assert.equal(taskChanged.model, "");
assert.equal(taskChanged.record, "");
assert.equal(taskChanged.date, "");
assert.equal(taskChanged.slot, null);
const switched = selectionChange(selected, {
  type: "source",
  source: "station:lanneng:synthetic",
});
assert.equal(switched.date, "");
assert.equal(switched.model, "");
assert.equal(switched.record, "");
assert.equal(switched.slot, null);
for (const change of [
  { type: "date", date: "2026-01-21" },
  { type: "model", model: "another" },
  { type: "view", mode: "replay", until: "12:00" },
]) {
  const result = selectionChange(selected, change);
  assert.equal(result.record, "");
  assert.equal(result.slot, null);
}
const restored = readSelection("?source=station:lanneng:synthetic", selected);
assert.equal(restored.model, "");
assert.equal(restored.record, "");
assert.ok(!selectionUrl(selected).includes("private-"));
assert.ok(!selectionUrl(selected).includes("ml_"));
console.log(
  "通过：旧链接、跨来源切换、日期/模型/时点切换及地址栏私有引用回归检查",
);
