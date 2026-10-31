import assert from "node:assert/strict"
import test from "node:test"
import { spawn } from "node:child_process"
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import os from "node:os"
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
    fileName: file,
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
const format = load(path.join(root, "lib/a2uiFormat.ts"))
const A2uiSurface = load(path.join(root, "components/agent/a2ui/A2uiSurface.tsx")).default

// Written by the backend (backend/test/test_agent_panels.py): the frontend renders exactly what the tools return.
const fixture = (tool) => JSON.parse(readFileSync(path.join(root, "test/fixtures/a2ui", `${tool}.json`), "utf8"))
const TOOLS = ["show_documents", "show_metrics", "show_table", "show_chart", "show_risks"]
const panel = (tool) => a2ui.surfaceFromToolResult(fixture(tool).result)
const clone = (value) => JSON.parse(JSON.stringify(value))

const render = (surface, props = {}) =>
  renderToStaticMarkup(createElement(A2uiSurface, { surface, fallback: "FALLBACK", onAction: () => {}, ...props }))

/** What a sighted reader sees: markup without tags and without screen-reader-only text. */
const visible = (html) => html.replace(/<span class="sr-only">[^<]*<\/span>/g, "").replace(/<[^>]+>/g, "").replace(/&quot;/g, '"')

/** The visible text of the element that starts at the first occurrence of marker, up to the next tile or row. */
const around = (html, marker, end) => {
  const start = html.indexOf(marker)
  assert.ok(start >= 0, `${marker} not rendered`)
  return visible(html.slice(start, end ? html.indexOf(end, start + marker.length) : undefined))
}

/** A fixture's tool result with one data-model edit, as if the backend had sent it. */
function edited(tool, edit) {
  const result = clone(fixture(tool).result)
  edit(result.a2ui[2].updateDataModel.value, result.a2ui[1].updateComponents.components)
  return a2ui.surfaceFromToolResult(result)
}

test("every backend fixture parses and renders as a panel", () => {
  for (const tool of TOOLS) {
    const surface = panel(tool)
    assert.ok(surface, `${tool} did not parse`)
    assert.equal(surface.catalogId, "https://insightdoc.app/a2ui/catalogs/jobs/v2")
    const html = render(surface, { onOpenDocument: () => {} })
    assert.doesNotMatch(html, /FALLBACK/, tool)
    assert.match(html, new RegExp(`data-surface-id="${surface.surfaceId}"`))
  }
})

// ── Formatting ──────────────────────────────────────────────────────────────

test("values are formatted in Thai with Buddhist-era dates and named currencies", () => {
  assert.equal(format.formatDate("2026-01-31"), "31 ม.ค. 2569")
  assert.equal(format.formatMonth("2025-09"), "ก.ย. 68")
  assert.equal(format.formatX("2026-01", "month"), "ม.ค. 69")
  assert.equal(format.formatX("บริษัท ก", "text"), "บริษัท ก")
  assert.equal(format.formatMeasure(1250, { kind: "money", currency: "THB" }), "1,250.00 บาท")
  assert.equal(format.formatMeasure(1250, { kind: "money", currency: "USD" }), "1,250.00 USD")
  assert.equal(format.formatMeasure(12.5, { kind: "percent" }), "12.5%")
  assert.equal(format.formatMeasure(1234, { kind: "count" }), "1,234")
  assert.equal(format.formatMeasure(1234.567, { kind: "number" }), "1,234.57")
  assert.equal(format.formatTick(1250000, { kind: "money", currency: "THB" }), "1.3M")
  assert.equal(format.formatTick(40, { kind: "percent" }), "40%")
  assert.equal(format.axisUnit({ kind: "money", currency: "THB" }), "บาท")
  assert.equal(format.axisUnit({ kind: "percent" }), undefined)
})

test("a change reads relative when the backend computed a percent, in points for a percent value", () => {
  const view = (change, measure) => clone(format.describeChange(change, measure))
  assert.deepEqual(view({ delta: 409.5, percent: 12.5, direction: "up", sentiment: "bad" }, { kind: "money", currency: "THB" }),
    { glyph: "▲", direction: "เพิ่มขึ้น", amount: "+12.5%", detail: "+409.50 บาท", sentiment: "แย่ลง" })
  assert.deepEqual(view({ delta: -1.5, percent: null, direction: "down", sentiment: "bad" }, { kind: "percent" }),
    { glyph: "▼", direction: "ลดลง", amount: "-1.5 จุด", sentiment: "แย่ลง" })
  assert.deepEqual(view({ delta: 5, percent: null, direction: "up", sentiment: "neutral" }, { kind: "count" }),
    { glyph: "▲", direction: "เพิ่มขึ้น", amount: "+5", sentiment: "" })
})

// ── Metrics ─────────────────────────────────────────────────────────────────

test("a metric shows the backend's comparison with glyph, sentiment word and color", () => {
  const html = render(panel("show_metrics"))
  const cost = around(html, "ค่าใช้จ่ายรวม", "จำนวนใบแจ้งหนี้")
  assert.match(cost, /3,685\.50 บาท/)
  assert.match(cost, /▲\+12\.5%\(แย่ลง\)\+409\.50 บาท/)
  assert.match(cost, /เทียบ ธ\.ค\. 2568: 3,276\.00 บาท/)
  assert.match(html, /class="[^"]*text-viz-bad[^"]*"><span aria-hidden="true">▲<\/span><span class="sr-only">เพิ่มขึ้น<\/span>/)

  assert.match(around(html, "จำนวนใบแจ้งหนี้", "ส่วนลดเฉลี่ย"), /12▬0%เทียบ ธ\.ค\. 2568: 12/)
  assert.match(around(html, "ส่วนลดเฉลี่ย", "AI คำนวณ"), /4\.5%▼-1\.5 จุด\(แย่ลง\)/)
})

test("the direction comes from the backend, not from the model or the renderer", () => {
  const html = render(edited("show_metrics", (data) => {
    data.metrics[0].change = { delta: 409.5, percent: 12.5, direction: "down", sentiment: "good" }
  }))
  assert.match(around(html, "ค่าใช้จ่ายรวม", "จำนวนใบแจ้งหนี้"), /▼\+12\.5%\(ดีขึ้น\)/)
  assert.equal(edited("show_metrics", (data) => { data.metrics[0].change.direction = "sideways" }), null)
})

test("panels with computed numbers list their sources instead of a generic note", () => {
  const html = render(panel("show_metrics"), { onOpenDocument: () => {} })
  assert.match(html, /<details[^>]*><summary[^>]*>AI คำนวณจาก (<!-- -->)?3(<!-- -->)? เอกสาร<\/summary>/)
  for (const filename of ["ใบแจ้งหนี้-บริษัทสยามคลีน-ม.ค.69.pdf", "ใบแจ้งหนี้-บริษัทสยามคลีน-ธ.ค.68.pdf", "ใบแจ้งหนี้-ออฟฟิศเมท-ม.ค.69.pdf"]) {
    assert.match(around(html, "AI คำนวณ"), new RegExp(`${filename.replace(/\./g, "\\.")}เปิดดู`))
  }
  assert.doesNotMatch(html, /ตัวเลขในแผงนี้ AI คำนวณ/)
  assert.doesNotMatch(render(panel("show_documents")), /AI คำนวณ/)
})

// ── Tables ──────────────────────────────────────────────────────────────────

test("a table formats each column by its kind and opens each row's document", () => {
  const html = render(panel("show_table"), { onOpenDocument: () => {} })
  const first = around(html, "บริษัท สยามคลีน จำกัด", "</tr>")
  assert.equal(first, "บริษัท สยามคลีน จำกัดใบแจ้งหนี้-บริษัทสยามคลีน-ม.ค.69.pdfเปิดดู31 ม.ค. 25692,450.50 บาท2,000.00 บาท▲+22.5%(แย่ลง)+450.50 บาท")
  const second = around(html, "ออฟฟิศเมท<", "</tr>")
  assert.match(second, /15 ม\.ค\. 2569/)
  assert.match(second, /▼-17\.7%\(ดีขึ้น\)-265\.00 บาท/)
  assert.equal(render(panel("show_table")).match(/เปิดดู/g), null)
})

// ── Charts ──────────────────────────────────────────────────────────────────

test("a line chart labels months by name in the Buddhist era, in the backend's order", () => {
  const html = render(panel("show_chart"))
  const labels = [...html.matchAll(/data-x-label=""[^>]*>([^<]*)</g)].map(([, text]) => text)
  assert.deepEqual(labels, ["ก.ย. 68", "ต.ค. 68", "พ.ย. 68", "ธ.ค. 68", "ม.ค. 69"])
  assert.doesNotMatch(visible(html), /2025-|2026-/)
  assert.match(html, /data-axis-title=""[^>]*>บาท</)
  const ticks = [...html.matchAll(/data-tick=""[^>]*>([^<]*)</g)].map(([, text]) => text)
  assert.ok(ticks.length > 1 && ticks.every((tick) => /^[\d.,]+K?$/.test(tick)), ticks.join(","))
  assert.match(html, /ทำความสะอาด<\/li>/)
  assert.match(html, /<summary[^>]*>ดูข้อมูลเป็นตาราง<\/summary>/)
  assert.match(around(html, "ดูข้อมูลเป็นตาราง"), /ม\.ค\. 692,450\.50 บาท1,235\.00 บาท/)
  assert.match(around(html, "ดูข้อมูลเป็นตาราง"), /พ\.ย\. 682,105\.00 บาท–/)
})

test("a bar chart labels each bar with its formatted value", () => {
  const surface = edited("show_chart", (data, components) => {
    const chart = components.find((c) => c.id === "chart")
    Object.assign(chart, { type: "bar", value_kind: "percent", x: { key: "month", label: "เดือน", kind: "month" } })
    delete chart.currency
  })
  const html = render(surface)
  assert.equal(html.match(/data-bar=""/g).length, 9)
  assert.match(html, /title="ม\.ค\. 69"/)
  assert.match(html, />2,450\.5%</)
  assert.doesNotMatch(html, /data-axis-title/)
})

test("line chart x labels keep the first and last and never crowd them", () => {
  const { xLabelIndices } = load(path.join(root, "components/agent/a2ui/analytics.tsx"))
  const cases = { 0: [], 1: [0], 2: [0, 1], 5: [0, 1, 2, 3, 4], 6: [0, 2, 5], 60: [0, 15, 30, 59] }
  for (const [count, expected] of Object.entries(cases)) assert.deepEqual([...xLabelIndices(Number(count), 5)], expected, `count ${count}`)
})

// ── Risks ───────────────────────────────────────────────────────────────────

test("a risk panel states which quotes were found and names the ones that were not", () => {
  const html = render(panel("show_risks"), { onOpenDocument: () => {} })
  assert.equal(around(html, "data-quote-summary", "</p>").replace(/^[^>]*>/, ""),
    "ข้อความอ้างอิงตรวจพบในเอกสาร 3 จาก 4 รายการ · ไม่พบ: ผู้ว่าจ้างรับผิดไม่จำกัด")
  assert.match(html, /สัญญาจ้างบริการทำความสะอาด-2569\.pdf<\/span><button/)
  const marks = [...html.matchAll(/data-quote="([a-z_]+)"/g)].map(([, mark]) => mark)
  assert.deepEqual(marks, ["found", "found", "not_found", "found"])
  const titles = [...html.matchAll(/text-sm font-medium text-ink-navy">([^<]*)</g)].map(([, title]) => title)
  assert.deepEqual(titles, ["ต่ออายุอัตโนมัติ", "ค่าปรับส่งมอบล่าช้า", "ผู้ว่าจ้างรับผิดไม่จำกัด", "ชำระเงินภายใน 30 วัน"])
  assert.deepEqual([...html.matchAll(/data-risk-count="(\w+)">(\d+)</g)].map(([, level, n]) => `${level}:${n}`),
    ["critical:1", "high:1", "medium:1", "low:1"])
})

test("a risk panel whose quotes were all found says so", () => {
  const surface = edited("show_risks", (data) => { for (const item of data.risks) item.quote_verified = true })
  assert.match(render(surface), /ข้อความอ้างอิงตรวจพบในเอกสารครบทั้ง 4 รายการ/)
  assert.equal(edited("show_risks", (data) => { delete data.risks[0].quote_verified }), null)
})

// ── Documents and actions ───────────────────────────────────────────────────

const selecting = (ids) => edited("show_documents", (data) => { data.selected = ids })

test("a document list shows database rows and its buttons need a selection", () => {
  const [first, second] = fixture("show_documents").result.a2ui[2].updateDataModel.value.documents
  const empty = render(panel("show_documents"))
  assert.match(empty, /ใบแจ้งหนี้-บริษัทสยามคลีน-ม\.ค\.69\.pdf/)
  assert.match(empty, /ยอดรวมสูงกว่าเดือนก่อน 12\.5%/)
  assert.match(empty, /รอตรวจ/)
  assert.match(empty, /<button[^>]*disabled=""[^>]*>อนุมัติที่เลือก<\/button>/)
  assert.match(empty, /<button[^>]*disabled=""[^>]*>ปฏิเสธที่เลือก<\/button>/)
  const chosen = render(selecting([first.document_id]))
  assert.doesNotMatch(chosen, /disabled=""[^>]*>อนุมัติที่เลือก/)
  const running = render(selecting([first.document_id]), { actionsDisabled: true, notes: ["ส่งคำสั่งแล้ว"] })
  assert.match(running, /<button[^>]*disabled=""[^>]*>อนุมัติที่เลือก<\/button>/)
  assert.match(running, /ส่งคำสั่งแล้ว/)
  assert.doesNotMatch(empty, /เปิดดู/)
  assert.match(render(panel("show_documents"), { onOpenDocument: () => {} }), /เปิดดู/)

  // A click is a structured request; the server writes the text the chat shows.
  const surface = selecting([first.document_id, second.document_id])
  assert.deepEqual(clone(a2ui.buildAction(surface, surface.components.approve, surface.dataModel)), {
    surface_id: "jobs-show-documents", name: "approve_documents", source_component_id: "approve",
    document_ids: [first.document_id, second.document_id],
  })
})

// ── Server-side surface state ───────────────────────────────────────────────

const GENERATED_AT = "2026-10-31T07:05:00+00:00"
const state = (status, actionable = true) => ({ status, actionable, generatedAt: GENERATED_AT })

test("panel buttons work only while the server keeps the panel active and no run is busy", () => {
  const availability = (value, runActive = false) => clone(a2ui.surfaceAvailability(value, runActive))
  assert.deepEqual(availability(state("active")), { actionable: true, notes: [], generatedAt: GENERATED_AT })
  assert.deepEqual(availability(state("active"), true), { actionable: false, notes: [], generatedAt: GENERATED_AT })
  assert.deepEqual(availability(state("answered")).notes, [a2ui.SURFACE_NOTES.answered])
  assert.deepEqual(availability(state("superseded")).notes, [a2ui.SURFACE_NOTES.superseded])
  assert.equal(availability(state("answered")).actionable || availability(state("superseded")).actionable, false)
  assert.deepEqual(availability(undefined), { actionable: false, notes: [], generatedAt: null })
  for (const status of ["active", "answered", "superseded"]) {
    assert.deepEqual(availability(state(status, false)).notes, [], `analytics panel, ${status}`)
  }
})

test("surface states are parsed from the API and malformed entries are dropped", () => {
  const parsed = a2ui.parseSurfaceStates({
    "jobs-a": { status: "superseded", actionable: true, generated_at: GENERATED_AT },
    "jobs-b": { status: "stale", actionable: true, generated_at: GENERATED_AT },
    "jobs-c": { status: "active", actionable: "yes", generated_at: GENERATED_AT },
  })
  assert.deepEqual(clone(parsed), { "jobs-a": state("superseded") })
  assert.deepEqual(clone(a2ui.parseSurfaceStates(null)), {})
})

test("each panel shows when its data was computed, in the Buddhist era", () => {
  assert.equal(format.formatGeneratedAt(GENERATED_AT, "Asia/Bangkok"), "ข้อมูล ณ 31 ต.ค. 2569 14:05")
  assert.equal(format.formatGeneratedAt("2026-01-01T16:59:00Z", "Asia/Bangkok"), "ข้อมูล ณ 1 ม.ค. 2569 23:59")
})

test("the chat renders each panel from the server's state, not from which panel came last", () => {
  const withId = (tool, id) => {
    const result = clone(fixture(tool).result)
    for (const message of result.a2ui) Object.values(message).find((v) => typeof v === "object").surfaceId = id
    if (tool === "show_documents") {
      result.a2ui[2].updateDataModel.value.selected = [result.a2ui[2].updateDataModel.value.documents[0].document_id]
    }
    return result
  }
  const AgentToolCalls = load(path.join(root, "components/agent/AgentToolCalls.tsx")).default
  const html = renderToStaticMarkup(createElement(AgentToolCalls, {
    calls: [{ id: "c1", name: "show_documents", arguments: {} }, { id: "c2", name: "show_documents", arguments: {} },
      { id: "c3", name: "show_metrics", arguments: {} }],
    results: { c1: withId("show_documents", "jobs-old"), c2: withId("show_documents", "jobs-new"),
      c3: withId("show_metrics", "jobs-metrics") },
    onSurfaceAction: () => {},
    // The metrics panel came last, yet the server keeps the newer document list active.
    surfaceConversation: { runActive: false, states: {
      "jobs-old": state("superseded"), "jobs-new": state("active"), "jobs-metrics": state("active", false) } },
  }))
  const [older, rest] = html.split('data-surface-id="jobs-new"')
  const [newer, metrics] = rest.split('data-surface-id="jobs-metrics"')
  assert.match(older, /<button[^>]*disabled=""[^>]*>อนุมัติที่เลือก<\/button>/)
  assert.match(older, /ไม่ใช่แผงล่าสุด/)
  assert.doesNotMatch(newer, /disabled=""[^>]*>อนุมัติที่เลือก/)
  assert.doesNotMatch(newer, /ไม่ใช่แผงล่าสุด|ส่งคำสั่งแล้ว/)
  assert.doesNotMatch(metrics, /ไม่ใช่แผงล่าสุด|ส่งคำสั่งแล้ว/)
  assert.equal(html.match(/ข้อมูล ณ /g).length, 3)
})

// ── Confirmation and history ────────────────────────────────────────────────

const conversation = load(path.join(root, "lib/agentConversation.ts"))
const request = (status) => ({ pending_action_id: "p1", status, tool_name: "bulk_approve",
  description: "อนุมัติเอกสารที่รอตรวจ 2 รายการ", arguments: { doc_ids: ["d1", "d2"] } })

test("the confirmation follows the polled request: shown while pending, timed out when expired, gone once answered", () => {
  const ConfirmationDialog = load(path.join(root, "components/agent/ConfirmationDialog.tsx")).default
  const dialog = (status) => {
    const shown = conversation.shownConfirmation(request(status))
    return shown && renderToStaticMarkup(createElement(ConfirmationDialog, { action: shown, onConfirm: () => {}, onReject: () => {} }))
  }
  assert.match(dialog("pending"), /Confirm/)
  assert.match(dialog("pending"), /Reject/)
  assert.match(dialog("expired"), /หมดเวลา/)
  assert.doesNotMatch(dialog("expired"), /Confirm|Reject/)
  assert.equal(dialog("confirmed"), null)
  assert.equal(dialog("rejected"), null)
  assert.equal(conversation.shownConfirmation(null), null)
})

test("a reloaded newest page keeps the earlier pages the user loaded", () => {
  const ids = (list) => clone(list.map((m) => m.id))
  const m = (id) => ({ id })
  const loaded = [m("a"), m("b"), m("c"), m("d")]
  const kept = conversation.mergeNewestPage(loaded, false, [m("c"), m("d"), m("e")], true)
  assert.deepEqual(ids(kept.messages), ["a", "b", "c", "d", "e"])
  assert.equal(kept.hasMore, false)
  const apart = conversation.mergeNewestPage(loaded, false, [m("x"), m("y")], true)
  assert.deepEqual(ids(apart.messages), ["x", "y"])
  assert.equal(apart.hasMore, true)
  assert.deepEqual(ids(conversation.mergeNewestPage(loaded, true, [], false).messages), [])
})

// ── Boundary ────────────────────────────────────────────────────────────────

const V1_RESULT = {
  ok: true,
  surface_id: "jobs-v1",
  a2ui: [
    { version: "v0.9", createSurface: { surfaceId: "jobs-v1", catalogId: "https://insightdoc.app/a2ui/catalogs/jobs/v1" } },
    { version: "v0.9", updateComponents: { surfaceId: "jobs-v1", components: [
      { id: "root", component: "Column", children: ["m"] },
      { id: "m", component: "Metric", label: "ค่าใช้จ่าย", value: 1200, format: "currency", unit: "THB",
        delta: { value: 409.5, direction: "up", sentiment: "bad" } },
    ] } },
    { version: "v0.9", updateDataModel: { surfaceId: "jobs-v1", path: "/", value: {} } },
  ],
}

test("an older v1 panel in history falls back to the ordinary tool-call entry", () => {
  assert.equal(a2ui.surfaceFromToolResult(V1_RESULT), null)
  const AgentToolCalls = load(path.join(root, "components/agent/AgentToolCalls.tsx")).default
  const html = renderToStaticMarkup(createElement(AgentToolCalls, {
    calls: [{ id: "c1", name: "render_ui", arguments: {} }],
    results: { c1: V1_RESULT },
    surfaceConversation: { states: {}, runActive: false },
  }))
  assert.doesNotMatch(html, /data-surface-id/)
  assert.match(html, />render_ui</)
})

test("a panel outside the v2 catalog is not rendered", () => {
  const broken = {
    "unknown component": (data, components) => components.push({ id: "x", component: "Map" }),
    "dangling child": (data, components) => components[0].children.push("ghost"),
    "money without a currency": (data, components) => { delete components.find((c) => c.id === "table").columns[3].currency },
    "a formatted value": (data) => { data.rows[0].amount = "2,450.50 บาท" },
    "a non-ISO date": (data) => { data.rows[0].issued = "31/01/2026" },
    "a change without a direction": (data) => { delete data.rows[0].change.direction },
    "a bad action": (data, components) => components.push({ id: "b", component: "Button", label: "x", variant: "primary",
      action: { event: { name: "ask_agent", context: {} } } }),
  }
  for (const [name, edit] of Object.entries(broken)) assert.equal(edited("show_table", edit), null, name)
  assert.equal(a2ui.surfaceFromToolResult({ ok: false, error: "show_table was not shown" }), null)
})

test("the confirmation names the documents it will change", () => {
  const ConfirmationDialog = load(path.join(root, "components/agent/ConfirmationDialog.tsx")).default
  const named = renderToStaticMarkup(createElement(ConfirmationDialog, {
    action: { pending_action_id: "p1", status: "pending", tool_name: "bulk_approve", description: "อนุมัติเอกสารที่รอตรวจ 2 รายการ",
      arguments: { doc_ids: ["d1", "d2"] }, documents: [
        { id: "d1", filename: "invoice-01.pdf", status: "extraction_completed" },
        { id: "d2", filename: "receipt-07.pdf", status: "reviewed" }] },
    onConfirm: () => {}, onReject: () => {} }))
  assert.match(named, /invoice-01\.pdf<\/span><span[^>]*>รอตรวจ</)
  assert.match(named, /receipt-07\.pdf<\/span><span[^>]*>อนุมัติแล้ว</)
})

// ── Layout boundary ─────────────────────────────────────────────────────────

const CHROME = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
const SURFACE_ROOT = "relative mx-3 min-w-0 overflow-x-clip"

/** Drive headless Chrome over the DevTools protocol; its window cannot be narrower than 500px, an emulated viewport can. */
async function withChrome(run) {
  const profile = mkdtempSync(path.join(os.tmpdir(), "a2ui-chrome-"))
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "about:blank"], { stdio: "ignore" })
  try {
    const portFile = path.join(profile, "DevToolsActivePort")
    for (let tries = 0; !existsSync(portFile) || !readFileSync(portFile, "utf8").includes("\n"); tries++) {
      if (tries > 100) throw new Error("Chrome did not start")
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    const port = readFileSync(portFile, "utf8").split("\n")[0]
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
    const socket = new WebSocket(targets.find((target) => target.type === "page").webSocketDebuggerUrl)
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject })
    const waiting = new Map()
    const events = new Map()
    socket.onmessage = ({ data }) => {
      const message = JSON.parse(data)
      if (waiting.has(message.id)) waiting.get(message.id)(message.result)
      if (events.has(message.method)) events.get(message.method)(message.params)
    }
    let nextId = 0
    const send = (method, params = {}) => new Promise((resolve) => {
      const id = ++nextId
      waiting.set(id, resolve)
      socket.send(JSON.stringify({ id, method, params }))
    })
    const once = (method) => new Promise((resolve) => events.set(method, resolve))
    try {
      return await run({ send, once })
    } finally {
      socket.close()
    }
  } finally {
    chrome.kill()
  }
}

/** document.documentElement's scrollWidth and clientWidth with markup in a chat-like column, at a 360px viewport. */
async function pageWidths(markup) {
  const body = `<div class="flex h-screen flex-col"><div class="flex-1 overflow-y-auto py-4 space-y-3">${markup}</div></div>`
  const { compile } = require("@tailwindcss/node")
  const candidates = [...new Set([...body.matchAll(/class="([^"]*)"/g)].flatMap((m) => m[1].split(/\s+/)))]
  const compiler = await compile(readFileSync(path.join(root, "app/globals.css"), "utf8"),
    { base: path.join(root, "app"), onDependency: () => {} })
  const file = path.join(mkdtempSync(path.join(os.tmpdir(), "a2ui-layout-")), "page.html")
  writeFileSync(file, `<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>${compiler.build(candidates)}</style></head>
<body style="margin:0">${body}</body></html>`)
  return withChrome(async ({ send, once }) => {
    await send("Emulation.setDeviceMetricsOverride", { width: 360, height: 800, deviceScaleFactor: 1, mobile: false })
    await send("Page.enable")
    const loaded = once("Page.loadEventFired")
    await send("Page.navigate", { url: `file://${file}` })
    await loaded
    const { result } = await send("Runtime.evaluate", { returnByValue: true,
      expression: "({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth })" })
    return result.value
  })
}

test("no panel widens a 360px page; the surface root is the boundary", { skip: !existsSync(CHROME) && "Chrome not found" }, async () => {
  const markup = TOOLS.map((tool) => render(panel(tool), { onOpenDocument: () => {}, generatedAt: GENERATED_AT })).join("")
  assert.ok(markup.includes(`class="${SURFACE_ROOT} `), "the surface root carries the containment classes")
  const contained = await pageWidths(markup)
  assert.equal(contained.client, 360)
  assert.ok(contained.scroll <= contained.client, `page is ${contained.scroll}px wide at 360px`)
  // The same panels without the root containment do widen the page: the check sees the defect it guards.
  const uncontained = await pageWidths(markup.replaceAll(SURFACE_ROOT, "mx-3"))
  assert.ok(uncontained.scroll > uncontained.client, `without containment the page stays ${uncontained.scroll}px`)
})
