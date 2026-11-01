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

const status = load(path.join(root, "lib/agentToolStatus.ts"))
const AgentToolCalls = load(path.join(root, "components/agent/AgentToolCalls.tsx")).default

// Shapes the backend stores: app.agent.unfinished and app.agent.confirmations.declined_result.
const UNFINISHED = {
  error: "approve_document did not finish: the run was stopped by the user or interrupted before it returned, so it had no result. Do not assume it took effect.",
  unfinished: true,
}
const REJECTED = { error: "User rejected action", declined: "rejected", tool_name: "approve_document" }
const EXPIRED = { error: "The confirmation request expired: the user is away.", declined: "expired", tool_name: "bulk_approve" }

const call = (id, name = "approve_document") => ({ id, name, arguments: { doc_id: id } })
const render = (calls, results, runActive) =>
  renderToStaticMarkup(createElement(AgentToolCalls, { calls, results, runActive }))
const spins = (html) => /role="status"|spinner/i.test(html)

// The class ChatToolCalls gives a red (error) status icon, found by rendering one.
const { ChatToolCalls } = require("@astryxdesign/core/Chat")
const iconClasses = (chipStatus) => new Set(renderToStaticMarkup(createElement(ChatToolCalls, {
  calls: [{ name: "x", status: chipStatus }],
})).match(/<span class="([^"]*)"/)[1].split(" "))
const [RED] = [...iconClasses("error")].filter((name) => !iconClasses("complete").has(name))
const red = (html) => html.split(/\s|"/).includes(RED)

test("a call whose run was stopped is stopped, not running and not a failure", () => {
  assert.equal(status.toolCallState(UNFINISHED, false), "stopped")
  assert.equal(status.toolCallState(UNFINISHED, true), "stopped")
  const html = render([call("a")], { a: UNFINISHED }, false)
  assert.ok(!spins(html), "a stopped call must not spin")
  assert.match(html, /data-tool-state="stopped"[^>]*>หยุดแล้ว</)
  assert.doesNotMatch(html, /title="approve_document did not finish/, "no error tooltip")
  assert.ok(!red(html), "a stopped call is not a red failure")
})

test("a call without a result runs only while a run is active", () => {
  assert.equal(status.toolCallState(undefined, true), "running")
  assert.equal(status.toolCallState(undefined, false), "stopped")
  assert.ok(spins(render([call("a")], {}, true)))
  assert.ok(!spins(render([call("a")], {}, false)))
})

test("a rejected or expired confirmation is declined, not an error", () => {
  assert.equal(status.toolCallState(REJECTED, false), "rejected")
  assert.equal(status.toolCallState(EXPIRED, false), "expired")
  assert.match(render([call("a")], { a: REJECTED }, false), /data-tool-state="rejected"[^>]*>ผู้ใช้ไม่ยืนยัน</)
  const expired = render([call("b", "bulk_approve")], { b: EXPIRED }, false)
  assert.match(expired, /data-tool-state="expired"[^>]*>หมดเวลายืนยัน</)
  assert.doesNotMatch(expired, /title="The confirmation request expired/, "no error tooltip")
  assert.ok(!red(expired) && !red(render([call("a")], { a: REJECTED }, false)), "a declined call is not a red failure")
})

test("a real failure and a success keep their states", () => {
  assert.equal(status.toolCallState({ error: "Document not found" }, false), "error")
  assert.equal(status.toolCallState({ error: { message: "boom" } }, false), "error")
  assert.equal(status.toolCallState({ ok: true }, false), "complete")
  const failed = render([call("a")], { a: { error: "Document not found" } }, false)
  assert.match(failed, /title="Document not found"/)
  assert.ok(red(failed))
  assert.doesNotMatch(failed, /data-tool-state/)
})

test("a group runs only while one of its calls runs", () => {
  assert.equal(status.toolCallGroupState(["complete", "running"]), "running")
  assert.equal(status.toolCallGroupState(["running", "complete"]), "running")
  assert.equal(status.toolCallGroupState(["complete", "complete", "stopped"]), "stopped")
  assert.equal(status.toolCallGroupState(["stopped", "complete"]), "complete")
  assert.equal(status.toolCallGroupState(["complete", "expired"]), "expired")

  // UAT round 2 N4: "approve_document 3" spun after Stop and after a reload.
  const calls = [call("list", "list_documents"), call("a"), call("b")]
  const stopped = render(calls, { list: { documents: [] }, a: REJECTED, b: UNFINISHED }, false)
  assert.ok(!spins(stopped), "the group must not spin")
  assert.match(stopped, /data-tool-group-state="stopped"/)
  const running = render(calls, { list: { documents: [] }, a: REJECTED }, true)
  assert.ok(spins(running))
  assert.match(running, /data-tool-group-state="running"/)
})
