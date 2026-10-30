import assert from "node:assert/strict"
import test from "node:test"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"
import vm from "node:vm"

const require = createRequire(import.meta.url)
const ts = require("typescript")
const source = readFileSync(new URL("../lib/schema-studio.ts", import.meta.url), "utf8")
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } })
const exports = {}
vm.runInNewContext(compiled.outputText, { exports, module: { exports } })
const serialize = (field) => JSON.parse(JSON.stringify(exports.toSchemaPayloadField(field)))
const table = {
  id: "temporary", name: "rows", type: "array", description: "Transactions", required: true,
  array_config: { item_type: "object", row_detection: "line", header_rows: 3,
    columns: [{ name: "detail", type: "text" }, { name: "amount", type: "currency" }] },
  table_columns: [{ name: "detail", type: "text" }, { name: "amount", type: "currency" }],
}

test("editing a text table preserves its existing row settings", () => {
  assert.deepEqual(serialize(table).array_config, table.array_config)
})
test("removing all columns does not resurrect old columns", () => {
  assert.equal(serialize({ ...table, table_columns: [] }).array_config, undefined)
})
test("changing an array to a scalar removes array-only configuration", () => {
  const result = serialize({ ...table, type: "text", items: { type: "object" } })
  assert.equal(result.array_config, undefined)
  assert.equal(result.items, undefined)
  assert.equal(result.id, undefined)
  assert.equal(result.table_columns, undefined)
})
test("positioned tables retain exact geometry, anchor and cleanup settings", () => {
  const locator = { type: "bbox", page: 2, x: 12.34, y: 20, width: 70, height: 30, clean_placeholders: false }
  const config = { ...table.array_config, row_detection: "anchor_column", anchor_column: "detail",
    columns: [{ name: "detail", type: "text", x: 0, width: 60 }, { name: "amount", type: "currency", x: 60, width: 40 }] }
  const result = serialize({ ...table, locator, array_config: config })
  assert.deepEqual(result.locator, locator)
  assert.deepEqual(result.array_config, config)
})
