/**
 * Generates styled HTML from LLM validation report output.
 * Mirrors the visual layout of LlmResultRenderer for Export Docs / Export PDF.
 */

interface ValidationRule {
  rule_id: string
  rule_name: string
  category: string
  status: string
  documents_compared?: string[]
  expected_value?: any
  actual_values?: any
  detail: string
  financial_impact_thb?: number | null
  recommendation?: string
}

interface DocumentReviewed {
  type: string
  doc_number: string
  date: string
}

interface ValidationSummary {
  total_rules: number
  passed: number
  failed: number
  warnings: number
  overall_status: string
  total_financial_risk_thb?: number
  risk_level?: string
}

interface ValidationReport {
  validation_summary: ValidationSummary
  validation_results: ValidationRule[]
  executive_summary?: string
  documents_reviewed?: DocumentReviewed[]
}

function tryParseReport(text: string): ValidationReport | null {
  try {
    const trimmed = text.trim()
    const jsonMatch = trimmed.match(/^```(?:json)?\s*\n?([\s\S]*?)\n?```$/)
    const raw = jsonMatch ? jsonMatch[1] : trimmed
    const parsed = JSON.parse(raw)
    if (parsed && parsed.validation_summary && Array.isArray(parsed.validation_results)) {
      return parsed as ValidationReport
    }
  } catch {
    // not valid JSON
  }
  return null
}

function fmtThb(amount: number): string {
  return new Intl.NumberFormat("th-TH", { style: "currency", currency: "THB", maximumFractionDigits: 0 }).format(amount)
}

function statusBadgeStyle(status: string): string {
  const s = status.toUpperCase()
  if (s === "PASS") return "background:#f0fff4;color:#276749;padding:2px 8px;border-radius:12px;font-weight:bold;font-size:12px;"
  if (s === "FAIL") return "background:#fff5f5;color:#c53030;padding:2px 8px;border-radius:12px;font-weight:bold;font-size:12px;"
  if (s === "WARNING" || s === "WARN") return "background:#fffaf0;color:#c05621;padding:2px 8px;border-radius:12px;font-weight:bold;font-size:12px;"
  return "background:#f7fafc;color:#718096;padding:2px 8px;border-radius:12px;font-weight:bold;font-size:12px;"
}

function buildReportHtml(report: ValidationReport, title: string): string {
  const s = report.validation_summary

  // Summary boxes
  const summaryHtml = `
    <h2 style="color:#2b6cb0;border-left:4px solid #2b6cb0;padding-left:12px;margin:24px 0 16px;">สรุปภาพรวม</h2>
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
      <tr>
        <td style="text-align:center;padding:20px;border:1px solid #c6f6d5;background:#f0fff4;border-radius:8px;width:33%;">
          <div style="font-size:32px;font-weight:800;color:#276749;">${s.passed}</div>
          <div style="font-size:13px;color:#718096;margin-top:4px;">PASSED</div>
        </td>
        <td style="text-align:center;padding:20px;border:1px solid #fed7d7;background:#fff5f5;border-radius:8px;width:33%;">
          <div style="font-size:32px;font-weight:800;color:#c53030;">${s.failed}</div>
          <div style="font-size:13px;color:#718096;margin-top:4px;">FAILED</div>
        </td>
        <td style="text-align:center;padding:20px;border:1px solid #feebc8;background:#fffaf0;border-radius:8px;width:33%;">
          <div style="font-size:32px;font-weight:800;color:#c05621;">${s.warnings ?? 0}</div>
          <div style="font-size:13px;color:#718096;margin-top:4px;">WARNING</div>
        </td>
      </tr>
    </table>`

  // Validation table
  const rows = report.validation_results.map((rule, idx) => {
    const st = rule.status.toUpperCase()
    const docsStr = rule.documents_compared ? rule.documents_compared.join(" ↔ ") : ""
    const bgColor = idx % 2 === 0 ? "#ffffff" : "#f7fafc"
    const catAbbr = rule.category.split(" ").map(w => w[0]).join("")
    const detailStyle = (st === "FAIL" || st === "WARN" || st === "WARNING") ? "font-weight:600;color:#2d3748;" : "color:#718096;"
    const checkmark = st === "PASS" ? " ✓" : ""
    return `<tr style="background:${bgColor};">
      <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#718096;font-size:12px;vertical-align:top;">${idx + 1}</td>
      <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#2d3748;vertical-align:top;">${escHtml(rule.rule_name)} <span style="color:#718096;font-size:11px;background:#edf2f7;padding:1px 6px;border-radius:4px;">(${catAbbr})</span></td>
      <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#718096;font-size:12px;vertical-align:top;">${escHtml(docsStr)}</td>
      <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:center;vertical-align:top;"><span style="${statusBadgeStyle(st)}">${st}</span></td>
      <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;vertical-align:top;${detailStyle}">${escHtml(rule.detail)}${checkmark}</td>
    </tr>`
  }).join("")

  const tableHtml = `
    <h2 style="color:#2b6cb0;border-left:4px solid #2b6cb0;padding-left:12px;margin:24px 0 16px;">ผลการตรวจสอบรายข้อ</h2>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="background:#1a365d;color:white;">
          <th style="padding:10px 12px;text-align:left;font-weight:600;width:40px;">#</th>
          <th style="padding:10px 12px;text-align:left;font-weight:600;min-width:180px;">Validation Rule</th>
          <th style="padding:10px 12px;text-align:left;font-weight:600;min-width:120px;">เอกสาร</th>
          <th style="padding:10px 12px;text-align:center;font-weight:600;width:80px;">ผลลัพธ์</th>
          <th style="padding:10px 12px;text-align:left;font-weight:600;">รายละเอียด</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`

  // Business Impact
  let impactHtml = ""
  const impactRules = report.validation_results.filter(
    r => (r.financial_impact_thb != null && r.financial_impact_thb !== 0) || ["FAIL", "WARN", "WARNING"].includes(r.status.toUpperCase())
  )
  const totalRisk = s.total_financial_risk_thb

  if (impactRules.length > 0 || report.executive_summary) {
    const items = impactRules.map(r => {
      let line = `<li style="margin-bottom:8px;"><strong style="color:#1a365d;">${escHtml(r.rule_name)}</strong>`
      if (r.financial_impact_thb != null && r.financial_impact_thb !== 0) {
        line += ` <span style="color:#c53030;font-weight:bold;">(มูลค่า ${fmtThb(Math.abs(r.financial_impact_thb))})</span>`
      }
      if (r.recommendation) {
        line += ` <span style="color:#718096;"> — ${escHtml(r.recommendation)}</span>`
      }
      line += `</li>`
      return line
    }).join("")

    impactHtml = `
      <h2 style="color:#2b6cb0;border-left:4px solid #2b6cb0;padding-left:12px;margin:24px 0 16px;">สรุป Business Impact</h2>
      <div style="background:#ebf8ff;border-left:4px solid #2b6cb0;border-radius:8px;padding:20px;">
        <div style="font-weight:bold;color:#1a365d;margin-bottom:12px;font-size:15px;">ความเสี่ยงทางการเงินที่ตรวจพบ</div>
        ${report.executive_summary ? `<p style="color:#2d3748;line-height:1.6;margin-bottom:12px;">${escHtml(report.executive_summary)}</p>` : ""}
        ${items ? `<ul style="padding-left:20px;color:#2d3748;margin-bottom:12px;">${items}</ul>` : ""}
        ${totalRisk != null && totalRisk > 0 ? `<div style="font-weight:bold;color:#1a365d;font-size:15px;border-top:1px solid rgba(43,108,192,0.3);padding-top:12px;">รวมความเสี่ยงทางการเงิน: ${fmtThb(totalRisk)} ต่อ transaction เดียว</div>` : ""}
      </div>`
  }

  // Documents Reviewed
  let docsHtml = ""
  if (report.documents_reviewed && report.documents_reviewed.length > 0) {
    const docItems = report.documents_reviewed.map(d =>
      `<span style="display:inline-block;padding:6px 12px;background:#f7fafc;border:1px solid #e2e8f0;border-radius:8px;margin:4px;font-size:13px;">
        <strong style="color:#1a365d;">${escHtml(d.type)}</strong>
        <span style="color:#2d3748;margin:0 4px;">${escHtml(d.doc_number)}</span>
        <span style="color:#718096;font-size:11px;">${escHtml(d.date)}</span>
      </span>`
    ).join("")

    docsHtml = `
      <h2 style="color:#2b6cb0;border-left:4px solid #2b6cb0;padding-left:12px;margin:24px 0 12px;">Documents Reviewed</h2>
      <div>${docItems}</div>`
  }

  return `<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <title>${escHtml(title)}</title>
  <style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #2d3748; line-height: 1.5; max-width: 960px; margin: 0 auto; padding: 24px; }
    @media print { body { padding: 12px; } }
  </style>
</head>
<body>
  <h1 style="color:#1a365d;font-size:22px;margin-bottom:4px;">${escHtml(title)}</h1>
  <div style="color:#718096;font-size:13px;margin-bottom:20px;">Generated: ${new Date().toLocaleString("th-TH")}</div>
  ${summaryHtml}
  ${tableHtml}
  ${impactHtml}
  ${docsHtml}
</body>
</html>`
}

function escHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

// ── Plain-text version for Copy All ──
function buildReportPlainText(report: ValidationReport, title: string): string {
  const s = report.validation_summary
  const lines: string[] = []

  lines.push(`=== ${title} ===`)
  lines.push(`Generated: ${new Date().toLocaleString("th-TH")}`)
  lines.push("")
  lines.push("── สรุปภาพรวม ──")
  lines.push(`  PASSED: ${s.passed}    FAILED: ${s.failed}    WARNING: ${s.warnings ?? 0}`)
  lines.push("")
  lines.push("── ผลการตรวจสอบรายข้อ ──")

  report.validation_results.forEach((r, idx) => {
    const st = r.status.toUpperCase()
    const docs = r.documents_compared ? r.documents_compared.join(" ↔ ") : ""
    lines.push(`${idx + 1}. [${st}] ${r.rule_name} (${docs})`)
    lines.push(`   ${r.detail}`)
    if (r.financial_impact_thb != null && r.financial_impact_thb !== 0) {
      lines.push(`   มูลค่า: ${fmtThb(Math.abs(r.financial_impact_thb))}`)
    }
    if (r.recommendation) {
      lines.push(`   แนะนำ: ${r.recommendation}`)
    }
    lines.push("")
  })

  const impactRules = report.validation_results.filter(
    r => (r.financial_impact_thb != null && r.financial_impact_thb !== 0) || ["FAIL", "WARN", "WARNING"].includes(r.status.toUpperCase())
  )

  if (impactRules.length > 0 || report.executive_summary) {
    lines.push("── สรุป Business Impact ──")
    if (report.executive_summary) {
      lines.push(report.executive_summary)
      lines.push("")
    }
    impactRules.forEach(r => {
      let line = `• ${r.rule_name}`
      if (r.financial_impact_thb != null && r.financial_impact_thb !== 0) line += ` (มูลค่า ${fmtThb(Math.abs(r.financial_impact_thb))})`
      if (r.recommendation) line += ` — ${r.recommendation}`
      lines.push(line)
    })
    if (s.total_financial_risk_thb != null && s.total_financial_risk_thb > 0) {
      lines.push("")
      lines.push(`รวมความเสี่ยงทางการเงิน: ${fmtThb(s.total_financial_risk_thb)} ต่อ transaction เดียว`)
    }
    lines.push("")
  }

  if (report.documents_reviewed && report.documents_reviewed.length > 0) {
    lines.push("── Documents Reviewed ──")
    report.documents_reviewed.forEach(d => {
      lines.push(`  ${d.type}  ${d.doc_number}  ${d.date}`)
    })
  }

  return lines.join("\n")
}

// ── Public API ──

/**
 * Generate full styled HTML for a single result output.
 * Falls back to simple HTML if the output is not a valid validation report JSON.
 */
export function generateExportHtml(output: string, title: string): string {
  const report = tryParseReport(output)
  if (report) {
    return buildReportHtml(report, title)
  }
  // Fallback: wrap plain text / markdown in basic HTML
  return `<!DOCTYPE html>
<html lang="th">
<head><meta charset="UTF-8"><title>${escHtml(title)}</title>
<style>body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;color:#2d3748;line-height:1.6;max-width:960px;margin:0 auto;padding:24px;white-space:pre-wrap;}</style>
</head><body>
<h1 style="color:#1a365d;font-size:22px;">${escHtml(title)}</h1>
<div style="color:#718096;font-size:13px;margin-bottom:20px;">Generated: ${new Date().toLocaleString("th-TH")}</div>
<pre style="font-family:inherit;">${escHtml(output)}</pre>
</body></html>`
}

/**
 * Generate readable plain text for clipboard copy.
 */
export function generateExportText(output: string, title: string): string {
  const report = tryParseReport(output)
  if (report) {
    return buildReportPlainText(report, title)
  }
  return `=== ${title} ===\n${output}`
}
