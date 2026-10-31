import { pdfjs } from "react-pdf"

// The bundler emits the worker as a same-origin asset and rewrites this URL.
pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString()
