import assert from "node:assert/strict"
import test from "node:test"
import { readFileSync } from "node:fs"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const readJson = (p, paths) => JSON.parse(readFileSync(require.resolve(p, paths && { paths }), "utf8"))

test("the pdf.js worker bundled with the app matches the pdfjs-dist react-pdf requires", () => {
  const reactPdf = require.resolve("react-pdf")
  const required = readJson("react-pdf/package.json").dependencies["pdfjs-dist"]
  const declared = readJson("../package.json").dependencies["pdfjs-dist"]
  const installed = readJson("pdfjs-dist/package.json").version
  const seenByReactPdf = readJson("pdfjs-dist/package.json", [reactPdf]).version
  assert.equal(declared, required, "package.json must pin pdfjs-dist to react-pdf's exact dependency")
  assert.equal(installed, required)
  assert.equal(seenByReactPdf, installed, "react-pdf must resolve the same pdfjs-dist as the app")
})
