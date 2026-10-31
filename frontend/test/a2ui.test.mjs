import assert from "node:assert/strict"
import test from "node:test"
import { existsSync, readFileSync } from "node:fs"
import { createRequire } from "node:module"
import { fileURLToPath } from "node:url"
import path from "node:path"
import vm from "node:vm"

const require = createRequire(import.meta.url)
const ts = require("typescript")
const { createElement } = require("react")
const { renderToStaticMarkup } = require("react-dom/server")
const root = fileURLToPath(new URL("..", import.meta.url))
const cache = new Map()

// Transpile frontend modules on demand, resolving the "@/" alias like Next does.
function load(file) {
  if (cache.has(file)) return cache.get(file)
  const mod = { exports: {} }
  cache.set(file, mod.exports)
  const { outputText } = ts.transpileModule(readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  })
  const localRequire = (id) => {
    if (!id.startsWith("@/")) return require(id)
    const base = path.join(root, id.slice(2))
    const resolved = [".ts", ".tsx"].map((ext) => base + ext).find(existsSync)
    return load(resolved)
  }
  vm.runInNewContext(outputText, { exports: mod.exports, module: mod, require: localRequire, Object, Array, Set, Date })
  cache.set(file, mod.exports)
  return mod.exports
}

const a2ui = load(path.join(root, "lib/a2ui.ts"))
const A2uiSurface = load(path.join(root, "components/agent/a2ui/A2uiSurface.tsx")).default

const surfaceId = "jobs-abc"
const messages = (components, value) => [
  { version: "v0.9", createSurface: { surfaceId, catalogId: a2ui.JOBS_CATALOG_ID } },
  { version: "v0.9", updateComponents: { surfaceId, components } },
  { version: "v0.9", updateDataModel: { surfaceId, path: "/", value } },
]
const components = [
  { id: "root", component: "Column", children: ["title", "list", "approve"] },
  { id: "title", component: "Text", text: { path: "/heading" }, variant: "heading" },
  { id: "list", component: "DocumentList", documents: { path: "/documents" }, selectable: true, selection: "/selected" },
  { id: "approve", component: "Button", label: "อนุมัติ", variant: "primary",
    action: { event: { name: "approve_documents", context: { document_ids: { path: "/selected" } } } } },
]
const data = {
  heading: "เอกสารรออนุมัติ 2 รายการ",
  documents: [
    { document_id: "d1", filename: "invoice-01.pdf", status: "extraction_completed", note: "ยอดไม่ตรง" },
    { document_id: "d2", filename: "invoice-02.pdf", status: "extraction_completed" },
  ],
  selected: [],
}
const render = (surface, props = {}) =>
  renderToStaticMarkup(createElement(A2uiSurface, { surface, fallback: "FALLBACK", onAction: () => {}, ...props }))

test("renders the surface with bound text and database rows", () => {
  const html = render(a2ui.parseSurface(messages(components, data)))
  assert.match(html, /เอกสารรออนุมัติ 2 รายการ/)
  assert.match(html, /invoice-01\.pdf/)
  assert.match(html, /ยอดไม่ตรง/)
  assert.match(html, /รอตรวจ/)
  assert.doesNotMatch(html, /FALLBACK/)
})

test("a selection-bound button is disabled until something is selected", () => {
  const empty = render(a2ui.parseSurface(messages(components, data)))
  assert.match(empty, /<button[^>]*disabled=""[^>]*>อนุมัติ<\/button>/)
  const chosen = render(a2ui.parseSurface(messages(components, { ...data, selected: ["d1"] })))
  assert.doesNotMatch(chosen, /<button[^>]*disabled=""[^>]*>อนุมัติ<\/button>/)
  const running = render(a2ui.parseSurface(messages(components, { ...data, selected: ["d1"] })), { actionsDisabled: true })
  assert.match(running, /<button[^>]*disabled=""[^>]*>อนุมัติ<\/button>/)
})

test("the open link appears only when the page can open documents", () => {
  const surface = a2ui.parseSurface(messages(components, data))
  assert.doesNotMatch(render(surface), /เปิดดู/)
  assert.match(render(surface, { onOpenDocument: () => {} }), /เปิดดู/)
})

test("unknown components and broken trees are not rendered as surfaces", () => {
  const chart = [...components.slice(0, 3), { id: "approve", component: "Chart" }]
  assert.equal(a2ui.parseSurface(messages(chart, data)), null)
  const dangling = [{ ...components[0], children: ["title", "ghost"] }, ...components.slice(1)]
  assert.equal(a2ui.parseSurface(messages(dangling, data)), null)
  const cycle = [{ id: "root", component: "Column", children: ["a"] }, { id: "a", component: "Column", children: ["root"] }]
  assert.equal(a2ui.parseSurface(messages(cycle, {})), null)
  const badEvent = [...components.slice(0, 3), { ...components[3], action: { event: { name: "delete_all" } } }]
  assert.equal(a2ui.parseSurface(messages(badEvent, data)), null)
  assert.equal(a2ui.surfaceFromToolResult({ ok: false, error: "x" }), null)
  assert.equal(a2ui.parseSurface([{ version: "v0.8", createSurface: { surfaceId, catalogId: a2ui.JOBS_CATALOG_ID } }]), null)
})

test("button actions resolve bindings into an A2UI action message", () => {
  const surface = a2ui.parseSurface(messages(components, data))
  const action = a2ui.buildAction(surface, surface.components.approve, { ...data, selected: ["d1", "d2"] }, "2026-10-31T00:00:00.000Z")
  assert.deepEqual(JSON.parse(JSON.stringify(action)), {
    name: "approve_documents", surfaceId, sourceComponentId: "approve",
    timestamp: "2026-10-31T00:00:00.000Z", context: { document_ids: ["d1", "d2"] },
  })
  const message = a2ui.actionMessage(action, "อนุมัติ")
  assert.ok(message.startsWith("อนุมัติเอกสาร 2 รายการที่เลือก\n\n```a2ui-action\n"))
  assert.deepEqual(JSON.parse(message.split("```a2ui-action\n")[1].split("\n```")[0]), JSON.parse(JSON.stringify(action)))
  assert.equal(a2ui.visibleUserText(message), "อนุมัติเอกสาร 2 รายการที่เลือก")
  assert.equal(a2ui.visibleUserText("hello ```a2ui-action``` text"), "hello ```a2ui-action``` text")
})
