import assert from "node:assert/strict"
import { createRequire } from "node:module"
import { mkdir, readFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"
const require = createRequire(import.meta.url)
const { chromium } = require("playwright")

const base = process.env.SCHEMA_TEST_URL || "http://127.0.0.1:3012"
const screenshotDir = process.env.SCHEMA_SCREENSHOTS || "/tmp/insightdoc-schema-edit"
const user = { id: "admin", role: "admin", email: "admin@example.test", full_name: "Test Admin" }
const original = {
  id: "fixed-edit-test", name: "Appointment form", description: "Existing form", document_type: "other",
  ocr_engine: "softnix", extraction_profile: "anydoc_hybrid", can_manage: true, created_by: "admin",
  fields: [
    { name: "subject", type: "text", description: "Keep subject prompt", required: true,
      validation_rules: { pattern: "^.*$" }, locator: { type: "bbox", page: 1, x: 15, y: 15, width: 40, height: 8, clean_placeholders: false } },
    { name: "rows", type: "array", description: "Keep table prompt", required: false,
      locator: { type: "bbox", page: 2, x: 10, y: 40, width: 80, height: 30, clean_placeholders: true },
      array_config: { item_type: "object", row_detection: "anchor_column", anchor_column: "item", header_rows: 2,
        columns: [{ name: "item", type: "text", x: 0, width: 60 }, { name: "amount", type: "currency", x: 60, width: 40 }] } },
    { name: "notes", type: "text", description: "Non-positioned field", required: false },
    { name: "free_rows", type: "array", description: "Non-positioned table", required: false,
      array_config: { item_type: "object", row_detection: "line", header_rows: 3,
        columns: [{ name: "detail", type: "text" }, { name: "total", type: "currency" }] } },
  ],
}
const sample = fileURLToPath(new URL("../../test/Demo Use Case/Contract_A_Expiring.pdf", import.meta.url))
const worker = await readFile(require.resolve("pdfjs-dist/build/pdf.worker.min.mjs", { paths: [require.resolve("react-pdf")] }))
await mkdir(screenshotDir, { recursive: true })
const browser = await chromium.launch({ headless: true, ...(process.env.SCHEMA_BROWSER_CHANNEL ? { channel: process.env.SCHEMA_BROWSER_CHANNEL } : {}) })
async function pdfReady(page) {
  await page.waitForFunction(() => {
    const canvas = document.querySelector("canvas")
    if (!canvas?.width || !canvas.height) return false
    const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data
    let ink = 0
    for (let index = 0; index < pixels.length; index += 64) if (pixels[index] < 200 && pixels[index + 3] > 200) ink += 1
    return ink > 20
  })
}
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  await context.addInitScript(() => {
    localStorage.setItem("token", "test.session.token")
    window.schemaEvents = []
    for (const name of ["click", "cancel", "change"]) document.addEventListener(name, (event) => window.schemaEvents.push(`${name}: ${event.target.tagName} ${event.target.textContent?.slice(0, 50)}`), true)
  })
  await context.route("**/pdf.worker.min.mjs", (route) => route.fulfill({ body: worker, contentType: "text/javascript" }))
  let current = structuredClone(original)
  const writes = []
  let failSave = false
  await context.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/\/$/, "")
    let body = {}
    if (path.endsWith("login/test-token")) body = user
    else if (path === "/api/v1/schemas") body = [current]
    else if (path === `/api/v1/schemas/${current.id}`) {
      if (route.request().method() === "PUT") {
        if (failSave) return route.fulfill({ status: 403, json: { detail: "Permission denied" } })
        const payload = route.request().postDataJSON()
        writes.push(payload)
        current = { ...current, ...payload }
      }
      body = current
    } else if (path.endsWith("preview-fixed-fields")) body = { values: { subject: "Sample subject" }, raw_values: { subject: "Sample subject" } }
    return route.fulfill({ json: body })
  })
  const page = await context.newPage()
  const pageErrors = []
  page.on("pageerror", (error) => pageErrors.push(error.message))
  await page.goto(`${base}/schemas`)
  await page.getByRole("button", { name: "Edit", exact: true }).click()
  await page.getByRole("textbox", { name: "Field name", exact: true }).first().waitFor()
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).count(), 2)
  await page.getByLabel("Sample PDF", { exact: true }).setInputFiles(sample)
  await page.locator("canvas").waitFor()
  await page.getByRole("button", { name: "Move subject box", exact: true }).waitFor()
  await pdfReady(page)
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).count(), 2)
  await page.getByRole("button", { name: "Read sample", exact: true }).click()
  await page.getByText("Sample subject", { exact: false }).waitFor()
  await page.screenshot({ path: `${screenshotDir}/desktop.png`, fullPage: true, animations: "disabled" })

  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("button", { name: "Back to fields" }).click()
  await page.getByRole("button", { name: "Move subject box", exact: true }).waitFor()
  await page.getByLabel("Sample PDF", { exact: true }).setInputFiles(sample)
  await page.getByRole("textbox", { name: "Field name", exact: true }).first().waitFor()
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).count(), 2)
  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  assert.equal(writes.length, 1)
  assert.deepEqual(writes[0].fields.map(({ order, ...field }) => field), original.fields)
  assert.equal(writes[0].ocr_engine, "softnix")

  await page.getByRole("button", { name: "Edit", exact: true }).click()
  await page.getByRole("textbox", { name: "Field name", exact: true }).first().fill("temporary_subject")
  const discard = page.waitForEvent("dialog").then(async (dialog) => {
    assert.match(dialog.message(), /Discard unsaved/)
    await dialog.dismiss()
  })
  await page.keyboard.press("Escape")
  await discard
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).first().inputValue(), "temporary_subject")
  await page.getByRole("textbox", { name: "Field name", exact: true }).first().fill("subject")
  await page.getByLabel("Sample PDF", { exact: true }).setInputFiles(sample)
  const box = page.getByRole("button", { name: "Move subject box", exact: true })
  await box.waitFor()
  await pdfReady(page)
  const bounds = await box.boundingBox()
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2)
  await page.mouse.down()
  await page.mouse.move(bounds.x + bounds.width / 2 + 30, bounds.y + bounds.height / 2 + 20, { steps: 8 })
  await page.mouse.up()
  const resized = page.getByRole("button", { name: "Resize subject box", exact: true })
  await resized.focus()
  await resized.press("ArrowRight")
  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  assert.equal(writes.length, 2)
  assert.ok(writes[1].fields[0].locator.x > original.fields[0].locator.x)
  assert.ok(writes[1].fields[0].locator.width > original.fields[0].locator.width)
  assert.equal(writes[1].fields[0].locator.clean_placeholders, false)
  assert.deepEqual(writes[1].fields.slice(1).map(({ order, ...field }) => field), original.fields.slice(1))

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole("button", { name: "Edit", exact: true }).click()
  await page.getByRole("textbox", { name: "Field name", exact: true }).first().waitFor()
  await page.getByLabel("Sample PDF", { exact: true }).setInputFiles(sample)
  await page.getByRole("button", { name: "Move subject box", exact: true }).waitFor()
  await pdfReady(page)
  assert.ok((await page.locator("canvas").boundingBox()).width < 390)
  await page.screenshot({ path: `${screenshotDir}/mobile.png`, fullPage: true, animations: "disabled" })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false)
  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("textbox", { name: "Schema Name *", exact: true }).fill("Renamed form")
  failSave = true
  const dialogPromise = page.waitForEvent("dialog").then(async (alert) => {
    assert.match(alert.message(), /Permission denied/)
    await alert.accept()
  })
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await dialogPromise
  assert.equal(writes.length, 2)
  assert.equal(await page.getByRole("textbox", { name: "Schema Name *", exact: true }).inputValue(), "Renamed form")
  failSave = false
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  assert.equal(writes[2].name, "Renamed form")
  await page.getByRole("button", { name: "Edit", exact: true }).click()
  await page.getByRole("button", { name: "All fields", exact: true }).click()
  await page.getByTitle("Field type", { exact: true }).nth(3).selectOption("text")
  await page.getByRole("button", { name: /^Next/ }).click()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  assert.equal(writes[3].fields[3].type, "text")
  assert.equal(writes[3].fields[3].array_config, undefined)
  await page.goto(`${base}/schemas/${original.id}/edit`)
  await page.getByRole("textbox", { name: "Field name", exact: true }).first().waitFor()
  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  current.can_manage = false
  await page.goto(`${base}/schemas/${original.id}/edit`)
  await page.getByRole("alert").filter({ hasText: "permission" }).waitFor()
  await page.goto(`${base}/schemas`)
  await page.getByRole("button", { name: "Create Schema", exact: true }).click()
  await page.getByRole("button", { name: /Fixed-position PDF/ }).click()
  await page.getByRole("button", { name: "Add by coordinates", exact: true }).click()
  await page.getByLabel("Sample PDF", { exact: true }).setInputFiles(sample)
  await page.getByRole("textbox", { name: "Field name", exact: true }).waitFor()
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).inputValue(), "field_1")
  assert.deepEqual(pageErrors, [])
  console.log("PASS: edit round-trip, upload/replacement retention, mixed fields, bbox move/resize, save error recovery, desktop/mobile")
} catch (error) {
  const page = browser.contexts()[0]?.pages()[0]
  if (page) {
    await page.screenshot({ path: `${screenshotDir}/failure.png`, fullPage: true })
    console.error((await page.locator("body").innerText()).slice(-3000))
    console.error(await page.evaluate(() => window.schemaEvents))
  }
  throw error
} finally {
  await browser.close()
}
