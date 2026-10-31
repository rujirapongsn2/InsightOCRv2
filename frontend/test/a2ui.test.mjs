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

// Transpile frontend modules on demand, resolving "@/" like Next does and relative imports.
function load(file) {
  if (cache.has(file)) return cache.get(file)
  const mod = { exports: {} }
  cache.set(file, mod.exports)
  const { outputText } = ts.transpileModule(readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  })
  const localRequire = (id) => {
    const relative = id.startsWith("./") || id.startsWith("../")
    if (!id.startsWith("@/") && !relative) return require(id)
    const base = relative ? path.resolve(path.dirname(file), id) : path.join(root, id.slice(2))
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

test("pointers through arrays are not rendered as surfaces", () => {
  const grouped = [components[0], components[1],
    { ...components[2], documents: { path: "/groups/0/docs" } }, components[3]]
  assert.equal(a2ui.parseSurface(messages(grouped, { ...data, groups: [{ docs: data.documents }] })), null)
  const inside = [components[0], components[1], { ...components[2], selection: "/documents/sel" }, components[3]]
  assert.equal(a2ui.parseSurface(messages(inside, data)), null)
  assert.notEqual(a2ui.parseSurface(messages(components, data)), null)
})

const toolResult = (id, value = data) => ({
  ok: true,
  surface_id: id,
  a2ui: [
    { version: "v0.9", createSurface: { surfaceId: id, catalogId: a2ui.JOBS_CATALOG_ID } },
    { version: "v0.9", updateComponents: { surfaceId: id, components } },
    { version: "v0.9", updateDataModel: { surfaceId: id, path: "/", value } },
  ],
})

test("only the newest unanswered surface keeps working buttons", () => {
  const latest = a2ui.latestSurfaceId([toolResult("jobs-old"), { ok: true, rows: [] }, toolResult("jobs-new"), { ok: false }])
  assert.equal(latest, "jobs-new")
  assert.equal(a2ui.latestSurfaceId([{ ok: false, error: "render_ui was not shown" }]), null)

  const clicked = a2ui.actionMessage({ name: "approve_documents", surfaceId: "jobs-old", sourceComponentId: "approve",
    timestamp: "t", context: { document_ids: ["d1"] } }, "อนุมัติ")
  const answered = a2ui.answeredSurfaceIds(["สวัสดี", clicked, "x\n\n```a2ui-action\nnot json\n```"])
  assert.deepEqual([...answered], ["jobs-old"])

  const idle = { latestSurfaceId: latest, answered, runActive: false }
  const availability = (id, conversation) => JSON.parse(JSON.stringify(a2ui.surfaceAvailability(id, conversation)))
  assert.deepEqual(availability("jobs-new", idle), { actionable: true, notes: [] })
  assert.deepEqual(availability("jobs-old", idle),
    { actionable: false, notes: [a2ui.SURFACE_NOTES.answered, a2ui.SURFACE_NOTES.outdated] })
  assert.equal(availability("jobs-new", { ...idle, runActive: true }).actionable, false)
  assert.deepEqual(availability("jobs-new", { ...idle, answered: new Set(["jobs-new"]) }),
    { actionable: false, notes: ["ส่งคำสั่งแล้ว"] })
})

test("a surface shows why its buttons are off", () => {
  const html = render(a2ui.parseSurface(messages(components, { ...data, selected: ["d1"] })),
    { actionsDisabled: true, notes: ["ส่งคำสั่งแล้ว"] })
  assert.match(html, /<button[^>]*disabled=""[^>]*>อนุมัติ<\/button>/)
  assert.match(html, /ส่งคำสั่งแล้ว/)
})

test("tool calls render only the newest surface with enabled buttons", () => {
  const AgentToolCalls = load(path.join(root, "components/agent/AgentToolCalls.tsx")).default
  const selected = { ...data, selected: ["d1"] }
  const html = renderToStaticMarkup(createElement(AgentToolCalls, {
    calls: [{ id: "c1", name: "render_ui", arguments: {} }, { id: "c2", name: "render_ui", arguments: {} }],
    results: { c1: toolResult("jobs-old", selected), c2: toolResult("jobs-new", selected) },
    onSurfaceAction: () => {},
    surfaceConversation: { latestSurfaceId: "jobs-new", answered: new Set(), runActive: false },
  }))
  const [older, newer] = html.split('data-surface-id="jobs-new"')
  assert.match(older, /data-surface-id="jobs-old"/)
  assert.match(older, /<button[^>]*disabled=""[^>]*>อนุมัติ<\/button>/)
  assert.match(older, /สถานะเอกสารอาจไม่เป็นปัจจุบัน/)
  assert.match(newer, />อนุมัติ<\/button>/)
  assert.doesNotMatch(newer, /disabled=""[^>]*>อนุมัติ/)
  assert.doesNotMatch(newer, /สถานะเอกสารอาจไม่เป็นปัจจุบัน/)
})

test("the confirmation names the documents it will change", () => {
  const ConfirmationDialog = load(path.join(root, "components/agent/ConfirmationDialog.tsx")).default
  const action = {
    pending_action_id: "p1", tool_name: "bulk_approve", description: "อนุมัติเอกสารที่รอตรวจ 2 รายการ",
    arguments: { doc_ids: ["d1", "d2"] },
  }
  const confirm = (props) => renderToStaticMarkup(createElement(ConfirmationDialog, {
    action: { ...action, ...props }, onConfirm: () => {}, onReject: () => {} }))

  const named = confirm({ documents: [
    { id: "d1", filename: "invoice-01.pdf", status: "extraction_completed" },
    { id: "d2", filename: "receipt-07.pdf", status: "reviewed" },
  ] })
  assert.match(named, /เอกสาร 2 รายการ/)
  assert.match(named, /invoice-01\.pdf<\/span><span[^>]*>รอตรวจ</)
  assert.match(named, /receipt-07\.pdf<\/span><span[^>]*>อนุมัติแล้ว</)
  assert.match(named, /<details/)

  const plain = confirm({})
  assert.match(plain, /อนุมัติเอกสารที่รอตรวจ 2 รายการ/)
  assert.match(plain, /bulk_approve/)
  assert.doesNotMatch(plain, /<ul/)
})
