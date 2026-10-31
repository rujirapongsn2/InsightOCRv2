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
  const chart = [...components.slice(0, 3), { id: "approve", component: "Map" }]
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

const analytic = (components, value) => a2ui.parseSurface(messages(components, value))
const column = (...children) => ({ id: "root", component: "Column", children })
const tiles = [
  column("tiles"),
  { id: "tiles", component: "Row", children: ["cost", "saved"] },
  { id: "cost", component: "Metric", label: "ค่าใช้จ่ายรวม", value: { path: "/cost" }, format: "currency", unit: "บาท",
    delta: { value: 12000, direction: "up", sentiment: "bad", label: "เทียบเดือนก่อน" } },
  { id: "saved", component: "Metric", label: "เวลาตรวจเฉลี่ย", value: 4.5, unit: "นาที",
    delta: { value: -1.5, direction: "down", sentiment: "good" } },
]
const tileHtml = (label) => {
  const html = render(analytic(tiles, { cost: 1250000.5 }))
  const start = html.indexOf(label)
  return html.slice(start, html.indexOf("</div>", start))
}

test("a Metric shows the direction glyph and colors by sentiment, not direction", () => {
  const cost = tileHtml("ค่าใช้จ่ายรวม")
  assert.match(cost, /1,250,000\.50 บาท/)
  assert.match(cost, /class="[^"]*text-viz-bad[^"]*"><span aria-hidden="true">▲<\/span><span class="sr-only">เพิ่มขึ้น<\/span>/)
  assert.match(cost, /\+12,000\.00 บาท<\/span><span>\(แย่ลง\)<\/span>/)
  assert.match(cost, /เทียบเดือนก่อน/)
  assert.doesNotMatch(cost, /text-viz-good/)

  const saved = tileHtml("เวลาตรวจเฉลี่ย")
  assert.match(saved, /class="[^"]*text-viz-good[^"]*"><span aria-hidden="true">▼<\/span><span class="sr-only">ลดลง<\/span>/)
  assert.match(saved, /-1\.5 นาที<\/span><span>\(ดีขึ้น\)<\/span>/)
  assert.doesNotMatch(saved, /text-viz-bad/)
})

test("surfaces with computed numbers say the agent computed them", () => {
  assert.match(render(analytic(tiles, { cost: 1 })), new RegExp(a2ui.COMPUTED_NOTE))
  assert.doesNotMatch(render(a2ui.parseSurface(messages(components, data))), new RegExp(a2ui.COMPUTED_NOTE))
  const badge = analytic([column("b"), { id: "b", component: "RiskBadge", level: "critical" }], {})
  assert.doesNotMatch(render(badge), new RegExp(a2ui.COMPUTED_NOTE))
  assert.match(render(badge), /วิกฤต/)

  const table = (type) => [column("t"), { id: "t", component: "DataTable", rows: { path: "/rows" },
    columns: [{ key: "vendor", label: "ผู้ขาย", type: "text" }, { key: "x", label: "x", type }] }]
  for (const type of ["number", "currency", "percent", "delta"]) {
    assert.match(render(analytic(table(type), { rows: [] })), new RegExp(a2ui.COMPUTED_NOTE), type)
  }
  for (const type of ["text", "date", "risk"]) {
    assert.doesNotMatch(render(analytic(table(type), { rows: [] })), new RegExp(a2ui.COMPUTED_NOTE), type)
  }
  const orphanMetric = analytic([column("b"), { id: "b", component: "RiskBadge", level: "low" },
    { id: "lost", component: "Metric", label: "ยอด", value: 1 }], {})
  assert.ok(orphanMetric)
  assert.doesNotMatch(render(orphanMetric), new RegExp(a2ui.COMPUTED_NOTE))
})

const tableComponents = [column("t"), { id: "t", component: "DataTable", caption: "เทียบผู้ขาย", rows: { path: "/rows" }, columns: [
  { key: "vendor", label: "ผู้ขาย", type: "text" },
  { key: "amount", label: "ยอด", type: "currency" },
  { key: "share", label: "สัดส่วน", type: "percent" },
  { key: "due", label: "ครบกำหนด", type: "date" },
  { key: "change", label: "เปลี่ยนแปลง", type: "delta" },
  { key: "risk", label: "ความเสี่ยง", type: "risk" },
] }]

test("a DataTable formats Thai numbers, dates, deltas and risk cells", () => {
  const html = render(analytic(tableComponents, { rows: [
    { vendor: "ACME", amount: 1234567.891, share: 12.5, due: "2026-11-30",
      change: { value: -3, direction: "down", sentiment: "good" }, risk: "high", document_id: "d1" },
    { vendor: "Beta", amount: null, share: 3, due: "bad-date", change: null, risk: "low" },
  ] }), { onOpenDocument: () => {} })
  assert.match(html, /<caption[^>]*>เทียบผู้ขาย<\/caption>/)
  assert.match(html, /<td class="[^"]*text-right[^"]*">1,234,567\.89<\/td>/)
  assert.match(html, /<td class="[^"]*text-right[^"]*">12\.5%<\/td>/)
  assert.match(html, /30 พ\.ย\. 2569/)
  assert.match(html, /text-viz-good[^"]*"><span aria-hidden="true">▼/)
  assert.match(html, /<\/svg><span class="sr-only">ความเสี่ยง<\/span>สูง<\/span>/)
  assert.match(html, /ความเสี่ยง<\/span>ต่ำ<\/span>/)
  assert.equal(html.match(/เปิดดู/g).length, 1)
  assert.equal(html.match(/>–</g).length, 3) // missing amount, invalid date, missing delta
  assert.match(html, /max-h-80 overflow-auto/)
})

test("DataTable number and delta cells carry the column's unit and format", () => {
  const columns = [
    { key: "amount", label: "ยอด", type: "currency", unit: "บาท" },
    { key: "change", label: "เปลี่ยนแปลง", type: "delta", format: "currency", unit: "บาท" },
    { key: "rate", label: "อัตรา", type: "delta", format: "percent" },
  ]
  const html = render(analytic([column("t"), { id: "t", component: "DataTable", rows: { path: "/rows" }, columns }], { rows: [
    { amount: 1500, change: { value: 250, direction: "up", sentiment: "bad" }, rate: { value: -2.5, direction: "down", sentiment: "good" } },
  ] }))
  assert.match(html, />1,500\.00 บาท<\/td>/)
  assert.match(html, />\+250\.00 บาท<\/span>/)
  assert.match(html, />-2\.5%<\/span>/)
  assert.equal(analytic([column("t"), { id: "t", component: "DataTable", rows: { path: "/rows" },
    columns: [{ ...columns[1], format: "money" }] }], { rows: [] }), null)
})

const chartComponent = (type, series) => [column("c"), { id: "c", component: "Chart", type, title: "ยอดตามผู้ขาย",
  x: "label", series, data: { path: "/points" }, format: "currency", unit: "บาท" }]
const twoSeries = [{ key: "y2025", label: "2568" }, { key: "y2026", label: "2569" }]

test("a bar Chart draws one bar per value with a legend and a table fallback", () => {
  const html = render(analytic(chartComponent("bar", twoSeries), { points: [
    { label: "ACME", y2025: 100, y2026: 150 }, { label: "Beta", y2025: 80, y2026: null }, { label: "Gamma", y2025: 20, y2026: 30 },
  ] }))
  assert.equal(html.match(/<svg[^>]*aria-hidden="true" class="block/g).length, 3)
  assert.equal(html.match(/<rect data-bar=""/g).length, 5)
  assert.match(html, /<title>ACME · 2569: 150\.00 บาท<\/title>/)
  assert.match(html, /<li[^>]*><span aria-hidden="true" class="[^"]*text-viz-1[^"]*"><\/span>2568<\/li>/)
  assert.match(html, /<details[^>]*><summary[^>]*>ดูข้อมูลเป็นตาราง<\/summary>/)
  assert.match(html, /<th scope="row"[^>]*>Beta<\/th><td[^>]*>80\.00 บาท<\/td><td[^>]*>–<\/td>/)
  assert.match(html, /role="img" aria-label="กราฟแท่ง ยอดตามผู้ขาย 3 รายการ/)
})

test("a line Chart draws a path per series and a marker per point; one series has no legend", () => {
  const points = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย."].map((label, i) => ({ label, y2025: 10 + i, y2026: i === 2 ? null : 20 - i }))
  const two = render(analytic(chartComponent("line", twoSeries), { points }))
  assert.equal(two.match(/<path data-point=""/g).length, 7)
  assert.equal(two.match(/<path d="M[^"]*" fill="none"/g).length, 2)
  assert.match(two, /<path d="M0 [\d.]+L33\.33 [\d.]+M100 [\d.]+" fill="none"/) // a gap where the value is missing
  assert.match(two, /ดูข้อมูลเป็นตาราง/)

  const one = render(analytic(chartComponent("line", twoSeries.slice(0, 1)), { points }))
  assert.equal(one.match(/<path data-point=""/g).length, 4)
  assert.doesNotMatch(one, /bg-current/)

  const many = Array.from({ length: 60 }, (_, i) => ({ label: `d${i}`, y2025: i }))
  const dense = render(analytic(chartComponent("line", twoSeries.slice(0, 1)), { points: many }))
  assert.equal(dense.match(/<path data-point=""/g).length, 1)
})

test("line Chart x labels keep the first and last and never crowd them", () => {
  const { xLabelIndices } = load(path.join(root, "components/agent/a2ui/analytics.tsx"))
  const cases = { 0: [], 1: [0], 2: [0, 1], 3: [0, 1, 2], 5: [0, 1, 2, 3, 4], 6: [0, 2, 5], 7: [0, 2, 4, 6], 9: [0, 2, 4, 6, 8], 60: [0, 15, 30, 59] }
  for (const [count, expected] of Object.entries(cases)) assert.deepEqual([...xLabelIndices(Number(count), 5)], expected, `count ${count}`)
  for (let count = 2; count <= 200; count++) {
    const indices = xLabelIndices(count, 5)
    const step = Math.ceil((count - 1) / 4)
    assert.ok(indices.length <= 5 && indices[0] === 0 && indices.at(-1) === count - 1, `count ${count}: ${indices}`)
    assert.ok(indices.slice(1).every((index, i) => index - indices[i] >= step), `count ${count}: ${indices} crowd at step ${step}`)
  }
})

test("line Chart value ticks carry the percent sign, and the unit as the axis title", () => {
  const points = [{ label: "ม.ค.", y2025: 12.5 }, { label: "ก.พ.", y2025: 40 }]
  const ticks = (html) => [...html.matchAll(/data-tick=""[^>]*>([^<]*)</g)].map(([, text]) => text)
  const percent = render(analytic([column("c"), { ...chartComponent("line", twoSeries.slice(0, 1))[1], format: "percent", unit: "บาท" }], { points }))
  assert.ok(ticks(percent).length > 1 && ticks(percent).every((tick) => /^\d[\d.]*%$/.test(tick)), ticks(percent).join(","))
  assert.doesNotMatch(percent, /data-axis-title/)

  const money = render(analytic(chartComponent("line", twoSeries.slice(0, 1)), { points: [{ label: "ม.ค.", y2025: 1200 }, { label: "ก.พ.", y2025: 250000 }] }))
  assert.match(money, /data-axis-title=""[^>]*>บาท</)
  assert.ok(ticks(money).includes("300K"), ticks(money).join(","))
  assert.ok(ticks(money).every((tick) => !tick.includes("%")))
})

const riskComponents =[column("r"), { id: "r", component: "RiskList", title: "ความเสี่ยงของสัญญา", items: { path: "/risks" } }]
const risk = (title, level, extra = {}) => ({ title, level, description: `คำอธิบาย ${title}`, ...extra })

test("a RiskList counts levels, sorts by severity and marks quote verification", () => {
  const html = render(analytic(riskComponents, { risks: [
    risk("ไม่มีเพดานความรับผิด", "medium"),
    risk("ค่าปรับรายวัน", "high", { quote: "ค่าปรับร้อยละ 0.5 ต่อวัน", quote_verified: true, document_id: "d1", page: 3,
      recommendation: "เจรจาเพดานค่าปรับ" }),
    risk("ต่ออายุอัตโนมัติ", "critical", { quote: "ต่ออายุโดยอัตโนมัติ", quote_verified: false, document_id: "d1" }),
    risk("ไม่มีข้อตกลงรักษาความลับ", "high"),
  ] }), { onOpenDocument: () => {} })
  const counts = Object.fromEntries([...html.matchAll(/data-risk-count="(\w+)">(\d+)</g)].map(([, level, n]) => [level, Number(n)]))
  assert.deepEqual(counts, { critical: 1, high: 2, medium: 1, low: 0 })
  const order = ["ต่ออายุอัตโนมัติ", "ค่าปรับรายวัน", "ไม่มีข้อตกลงรักษาความลับ", "ไม่มีเพดานความรับผิด"].map((t) => html.indexOf(`>${t}<`))
  assert.ok(order.every((at, i) => at > 0 && (i === 0 || at > order[i - 1])), `severity order ${order}`)

  const verified = html.slice(html.indexOf(">ค่าปรับรายวัน<"), html.indexOf(">ไม่มีข้อตกลงรักษาความลับ<"))
  assert.match(verified, /“ค่าปรับร้อยละ 0\.5 ต่อวัน”/)
  assert.match(verified, /text-viz-good[^>]*>.*พบในเอกสาร · หน้า 3/)
  assert.doesNotMatch(verified, /ไม่พบข้อความนี้/)
  assert.match(verified, /ข้อเสนอแนะ: <\/span>เจรจาเพดานค่าปรับ/)
  assert.match(verified, /เปิดดู/)

  const unverified = html.slice(html.indexOf(">ต่ออายุอัตโนมัติ<"), html.indexOf(">ค่าปรับรายวัน<"))
  assert.match(unverified, /text-viz-bad[^>]*>.*ไม่พบข้อความนี้ในเอกสาร ควรตรวจสอบ/)
  assert.doesNotMatch(unverified, />พบในเอกสาร/)
  assert.equal(html.match(/เปิดดู/g).length, 2)
})

test("analytics components with bad props fall back like any unknown component", () => {
  const badTiles = tiles.map((c) => (c.id === "cost" ? { ...c, delta: { value: 1, direction: "sideways", sentiment: "bad" } } : c))
  assert.equal(analytic(badTiles, { cost: 1 }), null)
  const driftingFlat = tiles.map((c) => (c.id === "cost" ? { ...c, delta: { value: 0.4, direction: "flat", sentiment: "neutral" } } : c))
  assert.equal(analytic(driftingFlat, { cost: 1 }), null)
  const flat = tiles.map((c) => (c.id === "cost" ? { ...c, delta: { value: 0, direction: "flat", sentiment: "neutral" } } : c))
  assert.match(render(analytic(flat, { cost: 1 })), /<span aria-hidden="true">▬<\/span><span class="sr-only">คงที่<\/span>/)
  assert.equal(analytic([column("b"), { id: "b", component: "RiskBadge", level: "severe" }], {}), null)
  assert.equal(analytic(chartComponent("pie", twoSeries), { points: [] }), null)
  const nine = Array.from({ length: 9 }, (_, i) => ({ key: `s${i}`, label: `s${i}` }))
  assert.equal(analytic(chartComponent("bar", nine), { points: [] }), null)
  assert.equal(analytic([column("m"), { id: "m", component: "Map" }], {}), null)
  assert.notEqual(analytic(tiles, { cost: 1 }), null)
})
