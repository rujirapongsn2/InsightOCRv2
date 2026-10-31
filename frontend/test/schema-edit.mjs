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
  const referenceFiles = new Map()
  const pdfBytes = await readFile(sample)
  let referenceWrites = 0
  let failReferenceUpload = false
  let failReferenceRead = false
  let waitForDelete = null
  let deleteStarted = null
  const creates = []
  await context.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/\/$/, "")
    const reference = path.match(/^\/api\/v1\/schemas\/([^/]+)\/reference-pdf(\/file)?$/)
    if (reference) {
      const id = reference[1]
      const method = route.request().method()
      if (method === "PUT") {
        if (failReferenceUpload) return route.fulfill({ status: 503, json: { detail: "Storage unavailable" } })
        assert.match(route.request().postDataBuffer().toString(), /name="consent"\r\n\r\ntrue/)
        const info = { filename: "Contract_A_Expiring.pdf", size: pdfBytes.length, uploaded_at: new Date().toISOString() }
        referenceFiles.set(id, info)
        referenceWrites += 1
        return route.fulfill({ json: info })
      }
      if (method === "DELETE") {
        deleteStarted?.()
        if (waitForDelete) await waitForDelete
        referenceFiles.delete(id)
        return route.fulfill({ status: 204 })
      }
      const info = referenceFiles.get(id)
      if (!info) return route.fulfill({ status: 404, json: { detail: "No reference PDF" } })
      if (reference[2] && failReferenceRead) return route.fulfill({ status: 404, json: { detail: "File unavailable" } })
      return reference[2] ? route.fulfill({ body: pdfBytes, contentType: "application/pdf" }) : route.fulfill({ json: info })
    }
    let body = {}
    if (path.endsWith("login/test-token")) body = user
    else if (path === "/api/v1/schemas") {
      if (route.request().method() === "POST") {
        const payload = route.request().postDataJSON()
        creates.push(payload)
        current = { ...payload, id: "created-schema", can_manage: true, created_by: user.id }
        body = current
      } else body = [current]
    }
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
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).count(), 1)
  assert.equal(await page.getByRole("textbox", { name: "Text in document", exact: true }).count(), 0)
  await page.getByLabel("Sample PDF", { exact: true }).setInputFiles(sample)
  await page.locator("canvas").waitFor()
  await page.getByRole("button", { name: "Move subject box", exact: true }).waitFor()
  await pdfReady(page)
  // Selecting a partially visible box must not scroll the coordinate system mid-drag.
  await page.getByRole("button", { name: "Edit rows", exact: true }).click()
  await page.getByText("Advanced position", { exact: true }).click()
  await page.getByRole("spinbutton", { name: "rows page", exact: true }).fill("1")
  await page.getByRole("spinbutton", { name: "rows y", exact: true }).fill("60")
  await page.getByRole("button", { name: "Edit subject", exact: true }).click()
  await pdfReady(page)
  const partialBox = page.getByRole("button", { name: "Move rows box", exact: true })
  const beforePartialDrag = await partialBox.evaluate((element) => {
    const container = element.closest("section").querySelector(".overflow-auto")
    container.scrollIntoView({ block: "center" })
    const box = element.getBoundingClientRect(), bounds = container.getBoundingClientRect()
    container.scrollTop += box.top - bounds.bottom + 60
    const visibleBox = element.getBoundingClientRect(), visibleContainer = container.getBoundingClientRect()
    return { top: parseFloat(element.parentElement.style.top), scroll: container.scrollTop,
      x: visibleBox.left + 30, y: Math.max(visibleBox.top, visibleContainer.top) + 10 }
  })
  await page.mouse.move(beforePartialDrag.x, beforePartialDrag.y)
  await page.mouse.down()
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  assert.equal(await partialBox.evaluate((element) => element.closest("section").querySelector(".overflow-auto").scrollTop), beforePartialDrag.scroll, "Selecting a box must not scroll while the pointer is captured")
  await page.mouse.move(beforePartialDrag.x + 1, beforePartialDrag.y + 1)
  await page.mouse.up()
  assert.ok(Math.abs(await partialBox.evaluate((element) => parseFloat(element.parentElement.style.top)) - beforePartialDrag.top) < 0.3, "A one-pixel drag must not move a box by ten percent")
  await page.getByText("Advanced position", { exact: true }).click()
  await page.getByRole("spinbutton", { name: "rows x", exact: true }).fill("10")
  await page.getByRole("spinbutton", { name: "rows y", exact: true }).fill("40")
  await page.getByRole("spinbutton", { name: "rows page", exact: true }).fill("2")
  await page.getByRole("button", { name: "Edit subject", exact: true }).click()
  await pdfReady(page)
  await page.getByRole("button", { name: "Add field", exact: true }).click()
  await page.getByRole("textbox", { name: "New field name", exact: true }).fill("pending_field")
  assert.equal(await page.getByRole("button", { name: "All fields", exact: true }).isDisabled(), true, "All fields must not bypass a pending fixed-field draft")
  assert.equal(await page.getByRole("button", { name: "Next", exact: true }).isDisabled(), true)
  await page.getByRole("button", { name: "Cancel field", exact: true }).click()
  assert.equal(await page.getByRole("button", { name: "All fields", exact: true }).isDisabled(), false)
  assert.equal(writes.length, 0)
  await page.getByRole("button", { name: "Edit subject", exact: true }).click()
  await page.getByLabel("More field methods", { exact: true }).click()
  await page.getByRole("heading", { name: "Fixed-position fields", exact: true }).click()
  assert.equal(await page.getByRole("button", { name: "Enter coordinates", exact: true }).isVisible(), false)
  await page.getByLabel("More field methods", { exact: true }).click()
  await page.getByRole("button", { name: "Enter coordinates", exact: true }).focus()
  await page.keyboard.press("Tab")
  assert.equal(await page.getByRole("button", { name: "Enter coordinates", exact: true }).isVisible(), false, "Keyboard focus leaving the menu must dismiss it")
  await page.getByRole("button", { name: "Edit rows", exact: true }).click()
  await page.getByRole("button", { name: "Move rows box", exact: true }).waitFor()
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).inputValue(), "rows")
  await page.getByRole("button", { name: "Edit subject", exact: true }).click()
  await page.getByRole("button", { name: "Move subject box", exact: true }).waitFor()
  await pdfReady(page)
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).count(), 1)
  await page.getByRole("button", { name: "Test extraction", exact: true }).click()
  await page.getByText("Sample subject", { exact: false }).waitFor()
  await page.screenshot({ path: `${screenshotDir}/desktop.png`, fullPage: true, animations: "disabled" })

  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("button", { name: "Back to fields" }).click()
  await page.getByRole("button", { name: "Move subject box", exact: true }).waitFor()
  await page.getByLabel("Sample PDF", { exact: true }).setInputFiles(sample)
  await page.getByRole("textbox", { name: "Field name", exact: true }).first().waitFor()
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).count(), 1)
  await page.getByRole("button", { name: "Next", exact: true }).click()
  assert.equal(await page.getByRole("radio", { name: /^Keep this PDF with the schema/ }).isChecked(), true)
  assert.equal(writes.length, 0, "Selecting a PDF must not save before the user presses Save")
  assert.equal(referenceWrites, 0)
  await page.screenshot({ path: `${screenshotDir}/desktop-save-consent.png`, fullPage: true, animations: "disabled" })
  await page.getByRole("radio", { name: "Do not attach this PDF", exact: true }).check()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("heading", { name: /^(Edit Schema|Create New Schema)/ }).waitFor({ state: "hidden" })
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  assert.equal(writes.length, 1)
  assert.deepEqual(writes[0].fields.map(({ order, ...field }) => field), original.fields)
  assert.equal(writes[0].ocr_engine, "softnix")
  assert.equal(referenceWrites, 0, "PDFs must not be stored without consent")

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
  await page.getByRole("radio", { name: "Do not attach this PDF", exact: true }).check()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("heading", { name: /^(Edit Schema|Create New Schema)/ }).waitFor({ state: "hidden" })
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
  await page.getByLabel("More field methods", { exact: true }).click()
  await page.getByLabel("More field methods", { exact: true }).evaluate((element) => element.blur())
  assert.equal(await page.getByRole("button", { name: "Enter coordinates", exact: true }).isVisible(), true, "Losing summary focus must not dismiss the menu before Safari delivers the item click")
  const mobileMethod = await page.getByRole("button", { name: "Enter coordinates", exact: true }).boundingBox()
  assert.ok(mobileMethod.x >= 0 && mobileMethod.x + mobileMethod.width <= 390, "Method menu must stay inside the mobile viewport")
  await page.screenshot({ path: `${screenshotDir}/mobile-methods.png`, fullPage: true, animations: "disabled" })
  await page.getByRole("button", { name: "Enter coordinates", exact: true }).click()
  await page.getByRole("textbox", { name: "New field name", exact: true }).waitFor()
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false)
  await page.screenshot({ path: `${screenshotDir}/mobile-new-field.png`, fullPage: true, animations: "disabled" })
  await page.getByRole("button", { name: "Cancel field", exact: true }).click()
  await page.getByRole("button", { name: "Edit subject", exact: true }).click()
  await page.screenshot({ path: `${screenshotDir}/mobile.png`, fullPage: true, animations: "disabled" })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false)
  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("textbox", { name: "Schema Name *", exact: true }).fill("Renamed form")
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false)
  await page.screenshot({ path: `${screenshotDir}/mobile-save-consent.png`, fullPage: true, animations: "disabled" })
  await page.getByRole("radio", { name: "Do not attach this PDF", exact: true }).check()
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
  await page.getByRole("heading", { name: /^(Edit Schema|Create New Schema)/ }).waitFor({ state: "hidden" })
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  assert.equal(writes[2].name, "Renamed form")
  await page.getByRole("button", { name: "Edit", exact: true }).click()
  await page.getByRole("button", { name: "All fields", exact: true }).click()
  await page.getByTitle("Field type", { exact: true }).nth(3).selectOption("text")
  await page.getByRole("button", { name: /^Next/ }).click()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("heading", { name: /^(Edit Schema|Create New Schema)/ }).waitFor({ state: "hidden" })
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  assert.equal(writes[3].fields[3].type, "text")
  assert.equal(writes[3].fields[3].array_config, undefined)
  await page.goto(`${base}/schemas/${original.id}/edit`)
  await page.getByRole("textbox", { name: "Field name", exact: true }).first().waitFor()
  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("heading", { name: /^(Edit Schema|Create New Schema)/ }).waitFor({ state: "hidden" })
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  // Attach a reference to an old schema, then reopen without selecting a file.
  await page.getByRole("button", { name: "Edit", exact: true }).click()
  await page.getByLabel("Sample PDF", { exact: true }).setInputFiles(sample)
  assert.equal(await page.getByRole("checkbox", { name: /^Keep this PDF/ }).isChecked(), true)
  await page.getByRole("button", { name: "Next", exact: true }).click()
  assert.equal(referenceWrites, 0)
  assert.equal(await page.getByRole("radio", { name: /^Keep this PDF with the schema/ }).isChecked(), true)
  await page.getByText(/Will be attached when saved/).waitFor()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("heading", { name: /^(Edit Schema|Create New Schema)/ }).waitFor({ state: "hidden" })
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  assert.equal(referenceWrites, 1)
  await page.getByRole("button", { name: "Edit", exact: true }).click()
  await page.getByText("Saved PDF", { exact: true }).waitFor()
  await page.getByRole("button", { name: "Move subject box", exact: true }).waitFor()
  await pdfReady(page)
  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("heading", { name: /^(Edit Schema|Create New Schema)/ }).waitFor({ state: "hidden" })
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  assert.equal(referenceWrites, 1, "An unchanged saved PDF must not upload again")
  await page.getByRole("button", { name: "Edit", exact: true }).click()
  await page.getByText("Saved PDF", { exact: true }).waitFor()
  await page.getByLabel("Sample PDF", { exact: true }).setInputFiles({ name: "preview-only.pdf", mimeType: "application/pdf", buffer: pdfBytes })
  await page.getByText(/Saved attachment: Contract_A_Expiring.pdf/).waitFor()
  assert.equal(await page.getByRole("checkbox", { name: /^Keep this PDF/ }).isChecked(), true)
  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("radio", { name: /^Do not attach this PDF/ }).check()
  await page.getByText(/saved Contract_A_Expiring.pdf remains attached/).waitFor()
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("heading", { name: /^Edit Schema/ }).waitFor({ state: "hidden" })
  assert.equal(referenceWrites, 1)
  failReferenceRead = true
  await page.getByRole("button", { name: "Edit", exact: true }).click()
  await page.getByRole("alert").filter({ hasText: "saved PDF is unavailable" }).waitFor()
  let releaseDelete
  waitForDelete = new Promise((resolve) => { releaseDelete = resolve })
  const started = new Promise((resolve) => { deleteStarted = resolve })
  page.once("dialog", (dialog) => dialog.accept())
  await page.getByRole("button", { name: "Remove saved PDF", exact: true }).click()
  await started
  assert.equal(await page.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), true)
  releaseDelete()
  await page.getByRole("button", { name: "Choose PDF form", exact: true }).waitFor()
  await page.getByRole("button", { name: "Cancel", exact: true }).click()
  waitForDelete = null
  failReferenceRead = false
  assert.equal(referenceFiles.has(original.id), false)
  await page.getByRole("heading", { name: /^(Edit Schema|Create New Schema)/ }).waitFor({ state: "hidden" })
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  current.can_manage = false
  await page.goto(`${base}/schemas/${original.id}/edit`)
  await page.getByRole("alert").filter({ hasText: "permission" }).waitFor()
  await page.goto(`${base}/schemas`)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole("button", { name: "Create Schema", exact: true }).click()
  await page.getByRole("button", { name: /Fixed-position PDF/ }).click()
  await page.getByLabel("More field methods", { exact: true }).click()
  await page.getByRole("button", { name: "Enter coordinates", exact: true }).click()
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).count(), 0)
  await page.getByRole("button", { name: "Cancel field", exact: true }).click()
  await page.getByLabel("Sample PDF", { exact: true }).setInputFiles(sample)
  await pdfReady(page)
  await page.getByLabel("More field methods", { exact: true }).click()
  await page.getByRole("button", { name: "Enter coordinates", exact: true }).click()
  await page.getByRole("textbox", { name: "New field name", exact: true }).waitFor()
  await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "New field name")
  await page.getByRole("spinbutton", { name: "New field width", exact: true }).fill("101")
  assert.equal(await page.getByRole("button", { name: "Add", exact: true }).isDisabled(), true)
  await page.getByRole("spinbutton", { name: "New field width", exact: true }).fill("10")
  await page.getByRole("button", { name: "Add", exact: true }).click()
  await page.getByRole("textbox", { name: "Field name", exact: true }).waitFor()
  assert.equal(await page.getByRole("textbox", { name: "Field name", exact: true }).inputValue(), "field_1")
  // Drawing and search produce drafts, using the same Add/Cancel controls.
  await page.getByRole("button", { name: "Add field", exact: true }).click()
  assert.equal(await page.getByRole("button", { name: "Next", exact: true }).isDisabled(), true)
  const canvas = await page.locator("canvas").boundingBox()
  await page.mouse.move(canvas.x + canvas.width * 0.2, canvas.y + canvas.height * 0.2)
  await page.mouse.down()
  await page.mouse.move(canvas.x + canvas.width * 0.5, canvas.y + canvas.height * 0.25, { steps: 8 })
  await page.mouse.up()
  await page.getByRole("button", { name: "Move new field box", exact: true }).waitFor()
  const draftBox = page.getByRole("button", { name: "Move new field box", exact: true })
  const beforeResize = await draftBox.boundingBox()
  const draftHandle = await page.getByRole("button", { name: "Resize new field box", exact: true }).boundingBox()
  await page.mouse.move(draftHandle.x + draftHandle.width / 2, draftHandle.y + draftHandle.height / 2)
  await page.mouse.down()
  await page.mouse.move(draftHandle.x + draftHandle.width / 2 + 15, draftHandle.y + draftHandle.height / 2 + 10, { steps: 5 })
  await page.mouse.up()
  assert.ok((await draftBox.boundingBox()).width > beforeResize.width)
  assert.equal(await page.getByRole("button", { name: "Edit field_2", exact: true }).count(), 0)
  await page.getByRole("textbox", { name: "New field name", exact: true }).fill("field_1")
  assert.equal(await page.getByRole("button", { name: "Add", exact: true }).isDisabled(), true)
  await page.getByRole("textbox", { name: "New field name", exact: true }).fill("drawn_field")
  await page.screenshot({ path: `${screenshotDir}/draw-draft.png`, fullPage: true, animations: "disabled" })
  await page.getByRole("button", { name: "Add", exact: true }).click()
  await page.getByRole("button", { name: "Move drawn_field box", exact: true }).waitFor()
  await page.getByRole("button", { name: "Remove drawn_field", exact: true }).click()
  await page.getByLabel("More field methods", { exact: true }).click()
  await page.getByLabel("More field methods", { exact: true }).evaluate((element) => element.blur())
  assert.equal(await page.getByRole("button", { name: "Find text to place box", exact: true }).isVisible(), true)
  await page.getByRole("button", { name: "Find text to place box", exact: true }).click()
  await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "Text in document")
  await page.getByRole("textbox", { name: "Text in document", exact: true }).fill("0105558076541")
  await page.getByRole("button", { name: "Find text", exact: true }).click()
  await page.getByText("Found on page 1", { exact: true }).waitFor()
  await page.getByRole("textbox", { name: "New field name", exact: true }).fill("tax_id")
  await page.getByRole("button", { name: "Add", exact: true }).click()
  await page.getByRole("button", { name: "Edit tax_id", exact: true }).waitFor()
  await page.getByRole("button", { name: "Remove tax_id", exact: true }).click()
  await page.getByRole("button", { name: "Add field", exact: true }).click()
  await page.getByRole("textbox", { name: "New field name", exact: true }).focus()
  await page.keyboard.press("Escape")
  assert.equal(await page.getByRole("textbox", { name: "New field name", exact: true }).count(), 0)
  await page.getByRole("button", { name: "Edit field_1", exact: true }).click()
  await page.getByRole("checkbox", { name: /^Keep this PDF/ }).check()
  await page.getByRole("button", { name: "Next", exact: true }).click()
  await page.getByRole("textbox", { name: "Schema Name *", exact: true }).fill("New fixed form")
  failReferenceUpload = true
  const attachmentError = page.waitForEvent("dialog").then(async (dialog) => {
    assert.match(dialog.message(), /Schema saved, but the PDF was not attached/)
    await dialog.accept()
  })
  await page.getByRole("button", { name: "Save Schema", exact: true }).click()
  await attachmentError
  assert.equal(creates.length, 1)
  failReferenceUpload = false
  await page.getByRole("button", { name: "Save Changes", exact: true }).click()
  await page.getByRole("heading", { name: /^(Edit Schema|Create New Schema)/ }).waitFor({ state: "hidden" })
  await page.getByRole("button", { name: "Edit", exact: true }).waitFor()
  assert.equal(creates.length, 1, "Retrying an attachment must not create another schema")
  assert.equal(referenceFiles.has("created-schema"), true)
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
