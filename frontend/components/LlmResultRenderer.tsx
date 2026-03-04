"use client"

import React, { useState } from "react"

// ── Types for validation report JSON ──
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

// ── Types for Contract Comparison Report ──
interface ValidationItem {
  item_id?: string
  category?: string
  topic?: string
  contract_a_value?: string
  contract_b_value?: string
  change?: string
  risk_level?: string
  status?: string
  finding?: string
  recommendation?: string
  [key: string]: any
}

interface NegotiationPriority {
  priority?: number
  clause?: string
  current_proposal?: string
  recommended_position?: string
  business_impact?: string
  [key: string]: any
}

interface ComparisonSummaryItem {
  area?: string
  status?: string
  risk_level?: string
  summary?: string
  [key: string]: any
}

interface ContractComparisonReport {
  report_title?: string
  analysis_date?: string
  documents_analyzed?: Array<{ label?: string; reference?: string; status?: string; [key: string]: any }>
  executive_summary?: string
  key_differences?: Array<{ category?: string; aspect?: string; contract_a?: string; contract_b?: string; impact?: string; significance?: string; [key: string]: any }>
  financial_comparison?: { [key: string]: any }
  sla_comparison?: Array<{ [key: string]: any }>
  risks_and_recommendations?: Array<{ risk?: string; description?: string; recommendation?: string; priority?: string; [key: string]: any }>
  validation_items?: ValidationItem[]
  negotiation_priorities?: NegotiationPriority[]
  comparison_summary?: ComparisonSummaryItem[] | { [key: string]: any }
  overall_recommendation?: string
  business_impact?: string
  overall_status?: string
  financial_summary?: {
    contract_a_total_value_thb?: number
    contract_b_total_value_thb?: number
    value_increase_thb?: number
    value_increase_percent?: number
    contract_b_monthly_fee_year1?: number
    fee_increase_from_a_percent?: number
    one_time_costs_thb?: number
    financial_risk_assessment?: string
    [key: string]: any
  }
  risk_matrix?: Array<{ area?: string; status?: string; risk_level?: string; summary?: string; [key: string]: any }>
  [key: string]: any
}

// ── Types for TOR / Spec Verification Report ──
interface TorRequirement {
  id: string | number
  [key: string]: any
}

interface TorVerificationSummary {
  spec_document?: string
  datasheet_document?: string
  total_requirements?: number
  pass_count?: number
  partial_count?: number
  fail_count?: number
  coverage_percent?: number
  overall_verdict?: string
  notes?: string
  [key: string]: any
}

interface TorVerificationReport {
  verification_summary: TorVerificationSummary
  requirements: TorRequirement[]
  [key: string]: any
}

// ── Helpers ──
function tryParseRaw(text: string): any | null {
  try {
    const trimmed = text.trim()
    const jsonMatch = trimmed.match(/^```(?:json)?\s*\n?([\s\S]*?)\n?```$/)
    const raw = jsonMatch ? jsonMatch[1] : trimmed
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function tryParseJson(text: string): ValidationReport | null {
  const parsed = tryParseRaw(text)
  if (parsed && parsed.validation_summary && Array.isArray(parsed.validation_results)) {
    return parsed as ValidationReport
  }
  return null
}

function tryParseTorVerification(text: string): TorVerificationReport | null {
  const parsed = tryParseRaw(text)
  if (parsed && parsed.verification_summary && Array.isArray(parsed.requirements)) {
    return parsed as TorVerificationReport
  }
  return null
}

function tryParseContractComparison(text: string): ContractComparisonReport | null {
  const parsed = tryParseRaw(text)
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    // Detect contract comparison by common keys
    if (
      parsed.report_title ||
      parsed.documents_analyzed ||
      parsed.key_differences ||
      parsed.risks_and_recommendations ||
      parsed.overall_recommendation
    ) {
      return parsed as ContractComparisonReport
    }
  }
  return null
}

function isMarkdown(text: string): boolean {
  const indicators = [/^#{1,6}\s/m, /\*\*[^*]+\*\*/, /^\s*[-*]\s/m, /\|.*\|.*\|/]
  return indicators.filter(r => r.test(text)).length >= 2
}

function isHtml(text: string): boolean {
  const t = text.trim()
  return /^<(!DOCTYPE|html|div|table|ul|ol|p|h[1-6]|section|article|main|body)/i.test(t) || (t.includes("</") && t.includes(">"))
}

// ── Generic JSON renderer for unknown schemas ──
function GenericJsonView({ data }: { data: any }) {
  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="text-[#718096] text-xs">[]</span>
    // Array of objects → table
    const isObjArray = data.every(item => item && typeof item === "object" && !Array.isArray(item))
    if (isObjArray) {
      const keys = Array.from(new Set(data.flatMap(item => Object.keys(item))))
      return (
        <div className="overflow-x-auto rounded-[8px] shadow-sm my-2">
          <table className="min-w-full text-[12px] border-collapse">
            <thead>
              <tr className="bg-[#1a365d] text-white">
                {keys.map(k => (
                  <th key={k} className="px-3 py-2 text-left font-semibold capitalize">{k.replace(/_/g, " ")}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row: any, idx: number) => (
                <tr key={idx} className={`border-b border-[#e2e8f0] ${idx % 2 === 0 ? "bg-white" : "bg-[#f7fafc]"} hover:bg-[#ebf8ff]`}>
                  {keys.map(k => (
                    <td key={k} className="px-3 py-2 text-[#2d3748] align-top">
                      {row[k] == null ? "—" : typeof row[k] === "object" ? <GenericJsonView data={row[k]} /> : String(row[k])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }
    // Array of primitives
    return (
      <ul className="list-disc list-inside space-y-1 text-[13px] text-[#2d3748]">
        {data.map((item: any, idx: number) => (
          <li key={idx}>{typeof item === "object" ? <GenericJsonView data={item} /> : String(item)}</li>
        ))}
      </ul>
    )
  }

  if (data && typeof data === "object") {
    return (
      <div className="space-y-2">
        {Object.entries(data).map(([key, val]) => (
          <div key={key} className="bg-[#f7fafc] border border-[#e2e8f0] rounded-[8px] p-3">
            <div className="text-xs font-semibold text-[#1a365d] capitalize mb-1">{key.replace(/_/g, " ")}</div>
            {val == null ? (
              <span className="text-[#718096] text-xs">—</span>
            ) : typeof val === "object" ? (
              <GenericJsonView data={val} />
            ) : (
              <div className="text-[13px] text-[#2d3748]">{String(val)}</div>
            )}
          </div>
        ))}
      </div>
    )
  }

  return <span className="text-[13px] text-[#2d3748]">{String(data)}</span>
}

function formatThb(amount: number): string {
  return new Intl.NumberFormat("th-TH", { style: "currency", currency: "THB", maximumFractionDigits: 0 }).format(amount)
}

// ── Status badge colors (Design System) ──
function statusColor(status: string) {
  const s = status.toUpperCase()
  if (s === "PASS") return "bg-[#f0fff4] text-[#276749]"
  if (s === "FAIL") return "bg-[#fff5f5] text-[#c53030]"
  if (s === "WARNING" || s === "WARN") return "bg-[#fffaf0] text-[#c05621]"
  return "bg-[#f7fafc] text-[#718096]"
}

// ── Sub-components ──

function StatBoxes({ summary }: { summary: ValidationSummary }) {
  return (
    <div className="mb-5">
      <h3 className="text-[17px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-4">สรุปภาพรวม</h3>
      <div className="flex gap-4">
        <div className="flex-1 rounded-[10px] border border-[#c6f6d5] bg-[#f0fff4] py-5 text-center shadow-[0_2px_10px_rgba(0,0,0,0.05)]">
          <div className="text-4xl font-[800] text-[#276749]">{summary.passed}</div>
          <div className="text-[13px] text-[#718096] mt-1">PASSED</div>
        </div>
        <div className="flex-1 rounded-[10px] border border-[#fed7d7] bg-[#fff5f5] py-5 text-center shadow-[0_2px_10px_rgba(0,0,0,0.05)]">
          <div className="text-4xl font-[800] text-[#c53030]">{summary.failed}</div>
          <div className="text-[13px] text-[#718096] mt-1">FAILED</div>
        </div>
        <div className="flex-1 rounded-[10px] border border-[#feebc8] bg-[#fffaf0] py-5 text-center shadow-[0_2px_10px_rgba(0,0,0,0.05)]">
          <div className="text-4xl font-[800] text-[#c05621]">{summary.warnings ?? 0}</div>
          <div className="text-[13px] text-[#718096] mt-1">WARNING</div>
        </div>
      </div>
    </div>
  )
}

function ValidationTable({ rules }: { rules: ValidationRule[] }) {
  return (
    <div className="mb-5">
      <h3 className="text-[17px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-4">ผลการตรวจสอบรายข้อ</h3>
      <div className="overflow-x-auto rounded-[10px] shadow-[0_2px_10px_rgba(0,0,0,0.05)]">
        <table className="min-w-full text-[13px] border-collapse">
          <thead>
            <tr className="bg-[#1a365d] text-white">
              <th className="px-3 py-2.5 text-left font-semibold w-10">#</th>
              <th className="px-3 py-2.5 text-left font-semibold min-w-[180px]">Validation Rule</th>
              <th className="px-3 py-2.5 text-left font-semibold min-w-[120px]">เอกสาร</th>
              <th className="px-3 py-2.5 text-center font-semibold w-20">ผลลัพธ์</th>
              <th className="px-3 py-2.5 text-left font-semibold">รายละเอียด</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((rule: ValidationRule, idx: number) => {
              const st = rule.status.toUpperCase()
              const isFail = st === "FAIL"
              const isWarn = st === "WARN" || st === "WARNING"
              const docsStr = rule.documents_compared ? rule.documents_compared.join(" \u2194 ") : ""
              return (
                <tr key={rule.rule_id} className={`border-b border-[#e2e8f0] ${idx % 2 === 0 ? "bg-white" : "bg-[#f7fafc]"} hover:bg-[#ebf8ff] transition-colors`}>
                  <td className="px-3 py-[9px] text-[#718096] font-mono text-xs align-top">{idx + 1}</td>
                  <td className="px-3 py-[9px] text-[#2d3748] align-top">{rule.rule_name} <span className="text-[#718096] text-[11px] font-mono bg-[#edf2f7] px-1.5 rounded">({rule.category.split(" ").map((w: string) => w[0]).join("")})</span></td>
                  <td className="px-3 py-[9px] text-[#718096] text-xs align-top">{docsStr}</td>
                  <td className="px-3 py-[9px] text-center align-top">
                    <span className={`inline-block text-xs font-bold px-2.5 py-0.5 rounded-full ${statusColor(rule.status)}`}>
                      {st}
                    </span>
                  </td>
                  <td className="px-3 py-[9px] align-top">
                    {isFail || isWarn ? (
                      <span className="font-semibold text-[#2d3748]">{rule.detail}</span>
                    ) : (
                      <span className="text-[#718096]">{rule.detail} {st === "PASS" ? "\u2713" : ""}</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function BusinessImpact({ report }: { report: ValidationReport }) {
  const impactRules = report.validation_results.filter(
    (r: ValidationRule) => (r.financial_impact_thb != null && r.financial_impact_thb !== 0) || ["FAIL", "WARN", "WARNING"].includes(r.status.toUpperCase())
  )
  const totalRisk = report.validation_summary.total_financial_risk_thb

  if (impactRules.length === 0 && !report.executive_summary) return null

  return (
    <div className="mb-5">
      <h3 className="text-[17px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-4">สรุป Business Impact</h3>
      <div className="bg-[#ebf8ff] border-l-4 border-[#2b6cb0] rounded-[10px] p-5 shadow-[0_2px_10px_rgba(0,0,0,0.05)]">
        <div className="font-bold text-[#1a365d] mb-3 text-[15px]">ความเสี่ยงทางการเงินที่ตรวจพบ</div>
        {report.executive_summary && (
          <p className="text-[14px] text-[#2d3748] leading-[1.6] mb-3">{report.executive_summary}</p>
        )}
        {impactRules.length > 0 && (
          <ul className="space-y-2 text-[14px] text-[#2d3748] mb-4">
            {impactRules.map((r: ValidationRule) => (
              <li key={r.rule_id} className="flex gap-2">
                <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#2b6cb0] flex-shrink-0" />
                <span>
                  <strong className="text-[#1a365d]">{r.rule_name}</strong>
                  {r.financial_impact_thb != null && r.financial_impact_thb !== 0 && (
                    <span className="text-[#c53030] font-bold"> (มูลค่า {formatThb(Math.abs(r.financial_impact_thb))})</span>
                  )}
                  {r.recommendation && <span className="text-[#718096]"> — {r.recommendation}</span>}
                </span>
              </li>
            ))}
          </ul>
        )}
        {totalRisk != null && totalRisk > 0 && (
          <div className="font-bold text-[#1a365d] text-[15px] border-t border-[#2b6cb0]/30 pt-3">
            รวมความเสี่ยงทางการเงิน: {formatThb(totalRisk)} ต่อ transaction เดียว
          </div>
        )}
      </div>
    </div>
  )
}

function DocumentsReviewed({ docs }: { docs: DocumentReviewed[] }) {
  return (
    <div className="mt-5">
      <h3 className="text-[17px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">Documents Reviewed</h3>
      <div className="flex flex-wrap gap-2">
        {docs.map((d, i) => (
          <div key={i} className="flex items-center gap-2 px-3 py-1.5 bg-[#f7fafc] rounded-[8px] border border-[#e2e8f0] text-[13px] shadow-[0_2px_10px_rgba(0,0,0,0.05)]">
            <span className="font-bold text-[#1a365d]">{d.type}</span>
            <span className="text-[#2d3748]">{d.doc_number}</span>
            <span className="text-[11px] text-[#718096]">{d.date}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Markdown renderer (simple) ──
function MarkdownView({ text }: { text: string }) {
  const lines = text.split("\n")
  const elements: React.ReactNode[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Headings
    const headingMatch = line.match(/^(#{1,6})\s+(.+)/)
    if (headingMatch) {
      const level = headingMatch[1].length
      const content = renderInline(headingMatch[2])
      const sizes: Record<number, string> = { 1: "text-2xl font-bold", 2: "text-xl font-bold", 3: "text-lg font-semibold", 4: "text-base font-semibold", 5: "text-sm font-semibold", 6: "text-sm font-medium" }
      elements.push(<div key={i} className={`${sizes[level] || "text-sm"} text-slate-800 mt-4 mb-2`}>{content}</div>)
      i++
      continue
    }

    // Horizontal rule
    if (/^---+$/.test(line.trim())) {
      elements.push(<hr key={i} className="my-3 border-slate-200" />)
      i++
      continue
    }

    // Table detection
    if (line.includes("|") && i + 1 < lines.length && lines[i + 1]?.includes("---")) {
      const tableLines: string[] = []
      let j = i
      while (j < lines.length && lines[j].includes("|")) {
        tableLines.push(lines[j])
        j++
      }
      if (tableLines.length >= 3) {
        const headers = tableLines[0].split("|").filter((c: string) => c.trim()).map((c: string) => c.trim())
        const rows = tableLines.slice(2).map((r: string) => r.split("|").filter((c: string) => c.trim()).map((c: string) => c.trim()))
        elements.push(
          <div key={i} className="overflow-x-auto my-3">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="bg-slate-100">
                  {headers.map((h: string, hi: number) => <th key={hi} className="border border-slate-200 px-3 py-2 text-left font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {rows.map((row: string[], ri: number) => (
                  <tr key={ri} className="hover:bg-slate-50">
                    {row.map((cell: string, ci: number) => <td key={ci} className="border border-slate-200 px-3 py-2">{cell}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
        i = j
        continue
      }
    }

    // Bullet list
    if (/^\s*[-*]\s/.test(line)) {
      const items: string[] = []
      let j = i
      while (j < lines.length && /^\s*[-*]\s/.test(lines[j])) {
        items.push(lines[j].replace(/^\s*[-*]\s/, ""))
        j++
      }
      elements.push(
        <ul key={i} className="list-disc list-inside space-y-1 my-2 text-slate-700">
          {items.map((item, idx) => <li key={idx}>{renderInline(item)}</li>)}
        </ul>
      )
      i = j
      continue
    }

    // Numbered list
    if (/^\s*\d+[.)]\s/.test(line)) {
      const items: string[] = []
      let j = i
      while (j < lines.length && /^\s*\d+[.)]\s/.test(lines[j])) {
        items.push(lines[j].replace(/^\s*\d+[.)]\s/, ""))
        j++
      }
      elements.push(
        <ol key={i} className="list-decimal list-inside space-y-1 my-2 text-slate-700">
          {items.map((item, idx) => <li key={idx}>{renderInline(item)}</li>)}
        </ol>
      )
      i = j
      continue
    }

    // Empty line
    if (!line.trim()) {
      i++
      continue
    }

    // Normal paragraph
    elements.push(<p key={i} className="text-slate-700 leading-relaxed my-1.5">{renderInline(line)}</p>)
    i++
  }

  return <div className="space-y-0.5">{elements}</div>
}

function renderInline(text: string): React.ReactNode {
  // Bold, italic, code
  const parts: React.ReactNode[] = []
  const regex = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g
  let lastIndex = 0
  let match

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    const m = match[0]
    if (m.startsWith("**")) {
      parts.push(<strong key={match.index} className="font-semibold">{m.slice(2, -2)}</strong>)
    } else if (m.startsWith("`")) {
      parts.push(<code key={match.index} className="bg-slate-100 px-1 rounded text-sm font-mono">{m.slice(1, -1)}</code>)
    } else if (m.startsWith("*")) {
      parts.push(<em key={match.index}>{m.slice(1, -1)}</em>)
    }
    lastIndex = match.index + m.length
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts.length === 1 ? parts[0] : <>{parts}</>
}

// ── Contract Comparison Report renderer ──
function priorityColor(priority: string) {
  const p = (priority || "").toUpperCase()
  if (p === "HIGH" || p === "สูง") return "bg-red-50 text-red-700 border-red-200"
  if (p === "MEDIUM" || p === "MODERATE" || p === "ปานกลาง") return "bg-yellow-50 text-yellow-700 border-yellow-200"
  return "bg-slate-50 text-slate-600 border-slate-200"
}

function significanceColor(sig: string) {
  const s = (sig || "").toUpperCase()
  if (s === "HIGH" || s === "สูง") return "text-red-600 font-bold"
  if (s === "MEDIUM" || s === "MODERATE" || s === "ปานกลาง") return "text-yellow-600 font-semibold"
  return "text-slate-500"
}

function ContractComparisonReportView({ report }: { report: ContractComparisonReport }) {
  const [showRaw, setShowRaw] = useState(false)

  return (
    <div className="space-y-5">
      {/* Header */}
      {(report.report_title || report.analysis_date) && (
        <div className="pb-3 border-b border-[#e2e8f0]">
          {report.report_title && (
            <h2 className="text-[18px] font-bold text-[#1a365d]">{report.report_title}</h2>
          )}
          {report.analysis_date && (
            <p className="text-xs text-[#718096] mt-1">วันที่วิเคราะห์: {report.analysis_date}</p>
          )}
        </div>
      )}

      {/* Documents Analyzed */}
      {report.documents_analyzed && report.documents_analyzed.length > 0 && (
        <div>
          <h3 className="text-[15px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">เอกสารที่วิเคราะห์</h3>
          <div className="flex flex-wrap gap-3">
            {report.documents_analyzed.map((doc, i) => (
              <div key={i} className="flex-1 min-w-[200px] bg-[#f7fafc] border border-[#e2e8f0] rounded-lg p-3 text-sm shadow-sm">
                {doc.label && <div className="font-semibold text-[#1a365d]">{doc.label}</div>}
                {doc.reference && <div className="text-[#4a5568] font-mono text-xs mt-0.5">{doc.reference}</div>}
                {doc.status && <div className="text-[#718096] text-xs mt-1">{doc.status}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Executive Summary */}
      {report.executive_summary && (
        <div className="bg-[#ebf8ff] border-l-4 border-[#2b6cb0] rounded-lg p-4">
          <h3 className="text-[14px] font-bold text-[#1a365d] mb-2">สรุปผู้บริหาร</h3>
          <p className="text-[14px] text-[#2d3748] leading-relaxed">{report.executive_summary}</p>
        </div>
      )}

      {/* Key Differences */}
      {report.key_differences && report.key_differences.length > 0 && (
        <div>
          <h3 className="text-[15px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">ความแตกต่างหลัก</h3>
          <div className="overflow-x-auto rounded-lg shadow-sm">
            <table className="min-w-full text-[13px] border-collapse">
              <thead>
                <tr className="bg-[#1a365d] text-white">
                  <th className="px-3 py-2.5 text-left font-semibold min-w-[120px]">หัวข้อ</th>
                  <th className="px-3 py-2.5 text-left font-semibold min-w-[160px]">สัญญา A (ปัจจุบัน)</th>
                  <th className="px-3 py-2.5 text-left font-semibold min-w-[160px]">สัญญา B (ข้อเสนอ)</th>
                  <th className="px-3 py-2.5 text-left font-semibold min-w-[120px]">ผลกระทบ</th>
                  <th className="px-3 py-2.5 text-center font-semibold w-20">ระดับ</th>
                </tr>
              </thead>
              <tbody>
                {report.key_differences.map((diff, idx) => (
                  <tr key={idx} className={`border-b border-[#e2e8f0] ${idx % 2 === 0 ? "bg-white" : "bg-[#f7fafc]"} hover:bg-[#ebf8ff] transition-colors`}>
                    <td className="px-3 py-2 font-semibold text-[#2d3748] align-top">
                      {diff.aspect || diff.category || Object.values(diff)[0]}
                    </td>
                    <td className="px-3 py-2 text-[#4a5568] align-top">{diff.contract_a ?? "—"}</td>
                    <td className="px-3 py-2 text-[#4a5568] align-top">{diff.contract_b ?? "—"}</td>
                    <td className="px-3 py-2 text-[#718096] text-xs align-top">{diff.impact ?? "—"}</td>
                    <td className="px-3 py-2 text-center align-top">
                      {diff.significance && (
                        <span className={`text-xs ${significanceColor(diff.significance)}`}>{diff.significance}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Risks and Recommendations */}
      {report.risks_and_recommendations && report.risks_and_recommendations.length > 0 && (
        <div>
          <h3 className="text-[15px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">ความเสี่ยงและข้อแนะนำ</h3>
          <div className="space-y-2">
            {report.risks_and_recommendations.map((item, idx) => (
              <div key={idx} className={`border rounded-lg p-3 ${priorityColor(item.priority || "")}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1">
                    {item.risk && <div className="font-semibold text-sm">{item.risk}</div>}
                    {item.description && <div className="text-xs mt-0.5 opacity-80">{item.description}</div>}
                    {item.recommendation && (
                      <div className="text-xs mt-1.5 flex gap-1.5">
                        <span className="font-semibold opacity-70">แนะนำ:</span>
                        <span>{item.recommendation}</span>
                      </div>
                    )}
                  </div>
                  {item.priority && (
                    <span className="text-xs font-bold border rounded px-1.5 py-0.5 shrink-0">{item.priority}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Overall Recommendation */}
      {report.overall_recommendation && (
        <div className="bg-[#f0fff4] border border-[#c6f6d5] rounded-lg p-4">
          <h3 className="text-[14px] font-bold text-[#276749] mb-2">ข้อสรุปและคำแนะนำ</h3>
          <p className="text-[14px] text-[#2d3748] leading-relaxed">{report.overall_recommendation}</p>
        </div>
      )}

      {/* Validation Items */}
      {report.validation_items && report.validation_items.length > 0 && (
        <div>
          <h3 className="text-[15px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">รายการตรวจสอบเปรียบเทียบ</h3>
          <div className="space-y-3">
            {report.validation_items.map((item, idx) => {
              const st = (item.status || "").toUpperCase()
              const rl = (item.risk_level || "").toUpperCase()
              const stColor = st === "PASS" ? "bg-green-50 text-green-700 border-green-200" : st === "FAIL" ? "bg-red-50 text-red-700 border-red-200" : "bg-yellow-50 text-yellow-700 border-yellow-200"
              const rlColor = rl === "HIGH" || rl === "CRITICAL" ? "text-red-600 font-bold" : rl === "MEDIUM" ? "text-yellow-600 font-semibold" : "text-slate-500"
              return (
                <div key={idx} className="border border-[#e2e8f0] rounded-lg overflow-hidden shadow-sm">
                  <div className="bg-[#f7fafc] px-3 py-2 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      {item.item_id && <span className="font-mono text-xs text-[#718096] bg-white border border-[#e2e8f0] px-1.5 rounded">{item.item_id}</span>}
                      {item.category && <span className="text-xs text-[#4a5568] font-semibold">[{item.category}]</span>}
                      <span className="text-sm font-semibold text-[#1a365d]">{item.topic}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {item.risk_level && <span className={`text-xs ${rlColor}`}>{item.risk_level}</span>}
                      {item.status && <span className={`text-xs font-bold border rounded px-2 py-0.5 ${stColor}`}>{item.status}</span>}
                    </div>
                  </div>
                  <div className="px-3 py-2 grid grid-cols-2 gap-2 text-xs border-b border-[#e2e8f0]">
                    <div>
                      <div className="text-[#718096] font-semibold mb-0.5">สัญญา A</div>
                      <div className="text-[#2d3748]">{item.contract_a_value || "—"}</div>
                    </div>
                    <div>
                      <div className="text-[#718096] font-semibold mb-0.5">สัญญา B</div>
                      <div className="text-[#2d3748]">{item.contract_b_value || "—"}</div>
                    </div>
                  </div>
                  {item.finding && (
                    <div className="px-3 py-2 text-xs text-[#2d3748] border-b border-[#e2e8f0]">
                      <span className="font-semibold text-[#4a5568]">ผลการตรวจสอบ: </span>{item.finding}
                    </div>
                  )}
                  {item.recommendation && (
                    <div className="px-3 py-2 text-xs bg-[#ebf8ff] text-[#2b6cb0]">
                      <span className="font-semibold">แนะนำ: </span>{item.recommendation}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Comparison Summary */}
      {report.comparison_summary && Array.isArray(report.comparison_summary) && report.comparison_summary.length > 0 && (
        <div>
          <h3 className="text-[15px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">สรุปการเปรียบเทียบรายด้าน</h3>
          <div className="overflow-x-auto rounded-lg shadow-sm">
            <table className="min-w-full text-[13px] border-collapse">
              <thead>
                <tr className="bg-[#1a365d] text-white">
                  <th className="px-3 py-2.5 text-left font-semibold">ด้าน</th>
                  <th className="px-3 py-2.5 text-center font-semibold w-24">สถานะ</th>
                  <th className="px-3 py-2.5 text-center font-semibold w-24">ความเสี่ยง</th>
                  <th className="px-3 py-2.5 text-left font-semibold">สรุป</th>
                </tr>
              </thead>
              <tbody>
                {(report.comparison_summary as ComparisonSummaryItem[]).map((row, idx) => {
                  const st = (row.status || "").toUpperCase()
                  const stColor = st === "PASS" ? "bg-green-50 text-green-700" : st === "FAIL" ? "bg-red-50 text-red-700" : "bg-yellow-50 text-yellow-700"
                  const rl = (row.risk_level || "").toUpperCase()
                  const rlColor = rl === "CRITICAL" || rl === "HIGH" ? "text-red-600 font-bold" : rl === "MEDIUM" ? "text-yellow-600" : "text-slate-500"
                  return (
                    <tr key={idx} className={`border-b border-[#e2e8f0] ${idx % 2 === 0 ? "bg-white" : "bg-[#f7fafc]"}`}>
                      <td className="px-3 py-2 font-semibold text-[#1a365d] align-top">{row.area || "—"}</td>
                      <td className="px-3 py-2 text-center align-top">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${stColor}`}>{st || "—"}</span>
                      </td>
                      <td className={`px-3 py-2 text-center text-xs align-top ${rlColor}`}>{row.risk_level || "—"}</td>
                      <td className="px-3 py-2 text-xs text-[#2d3748] align-top">{row.summary || "—"}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Negotiation Priorities */}
      {report.negotiation_priorities && report.negotiation_priorities.length > 0 && (
        <div>
          <h3 className="text-[15px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">ลำดับความสำคัญในการเจรจา</h3>
          <div className="space-y-3">
            {report.negotiation_priorities.map((item, idx) => (
              <div key={idx} className="border border-[#e2e8f0] rounded-lg overflow-hidden shadow-sm">
                <div className="bg-[#1a365d] text-white px-3 py-2 flex items-center gap-2">
                  <span className="text-xs font-bold bg-white text-[#1a365d] rounded-full w-5 h-5 flex items-center justify-center shrink-0">{item.priority ?? idx + 1}</span>
                  <span className="text-sm font-semibold">{item.clause}</span>
                </div>
                <div className="divide-y divide-[#e2e8f0]">
                  {item.current_proposal && (
                    <div className="px-3 py-2 text-xs">
                      <div className="font-semibold text-[#718096] mb-0.5">ข้อเสนอปัจจุบัน</div>
                      <div className="text-[#2d3748]">{item.current_proposal}</div>
                    </div>
                  )}
                  {item.recommended_position && (
                    <div className="px-3 py-2 text-xs bg-[#ebf8ff]">
                      <div className="font-semibold text-[#2b6cb0] mb-0.5">ท่าทีที่แนะนำ</div>
                      <div className="text-[#2d3748]">{item.recommended_position}</div>
                    </div>
                  )}
                  {item.business_impact && (
                    <div className="px-3 py-2 text-xs bg-[#fffaf0]">
                      <div className="font-semibold text-[#c05621] mb-0.5">ผลกระทบทางธุรกิจ</div>
                      <div className="text-[#2d3748]">{item.business_impact}</div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Financial Summary */}
      {report.financial_summary && (
        <div>
          <h3 className="text-[15px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">สรุปการเงิน</h3>
          <div className="bg-[#f7fafc] border border-[#e2e8f0] rounded-lg overflow-hidden shadow-sm">
            <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-[#e2e8f0] border-b border-[#e2e8f0]">
              {report.financial_summary.contract_a_total_value_thb != null && (
                <div className="px-3 py-3 text-center">
                  <div className="text-xs text-[#718096] mb-1">มูลค่าสัญญา A</div>
                  <div className="font-bold text-[#1a365d] text-sm">{report.financial_summary.contract_a_total_value_thb.toLocaleString("th-TH")} ฿</div>
                </div>
              )}
              {report.financial_summary.contract_b_total_value_thb != null && (
                <div className="px-3 py-3 text-center">
                  <div className="text-xs text-[#718096] mb-1">มูลค่าสัญญา B</div>
                  <div className="font-bold text-[#1a365d] text-sm">{report.financial_summary.contract_b_total_value_thb.toLocaleString("th-TH")} ฿</div>
                </div>
              )}
              {report.financial_summary.value_increase_thb != null && (
                <div className="px-3 py-3 text-center">
                  <div className="text-xs text-[#718096] mb-1">เพิ่มขึ้น (฿)</div>
                  <div className="font-bold text-red-600 text-sm">+{report.financial_summary.value_increase_thb.toLocaleString("th-TH")} ฿</div>
                </div>
              )}
              {report.financial_summary.value_increase_percent != null && (
                <div className="px-3 py-3 text-center">
                  <div className="text-xs text-[#718096] mb-1">เพิ่มขึ้น (%)</div>
                  <div className="font-bold text-red-600 text-sm">+{report.financial_summary.value_increase_percent}%</div>
                </div>
              )}
            </div>
            {report.financial_summary.financial_risk_assessment && (
              <div className="px-3 py-3 text-xs text-[#2d3748] border-t border-[#e2e8f0] bg-[#fffaf0]">
                <span className="font-semibold text-[#c05621]">ประเมินความเสี่ยงทางการเงิน: </span>
                {report.financial_summary.financial_risk_assessment}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Risk Matrix */}
      {report.risk_matrix && report.risk_matrix.length > 0 && (
        <div>
          <h3 className="text-[15px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">Risk Matrix</h3>
          <div className="overflow-x-auto rounded-lg shadow-sm">
            <table className="min-w-full text-[13px] border-collapse">
              <thead>
                <tr className="bg-[#1a365d] text-white">
                  <th className="px-3 py-2.5 text-left font-semibold">ด้าน</th>
                  <th className="px-3 py-2.5 text-center font-semibold w-24">สถานะ</th>
                  <th className="px-3 py-2.5 text-center font-semibold w-28">ระดับความเสี่ยง</th>
                  <th className="px-3 py-2.5 text-left font-semibold">สรุป</th>
                </tr>
              </thead>
              <tbody>
                {report.risk_matrix.map((row, idx) => {
                  const st = (row.status || "").toUpperCase()
                  const stColor = st === "PASS" ? "bg-green-50 text-green-700" : st === "FAIL" ? "bg-red-50 text-red-700" : "bg-yellow-50 text-yellow-700"
                  const rl = (row.risk_level || "").toUpperCase()
                  const rlColor = rl === "CRITICAL" ? "text-red-700 font-bold" : rl === "HIGH" ? "text-red-600 font-bold" : rl === "MEDIUM" ? "text-yellow-600 font-semibold" : "text-slate-500"
                  return (
                    <tr key={idx} className={`border-b border-[#e2e8f0] ${idx % 2 === 0 ? "bg-white" : "bg-[#f7fafc]"} hover:bg-[#ebf8ff] transition-colors`}>
                      <td className="px-3 py-2 font-semibold text-[#1a365d] align-top">{row.area || "—"}</td>
                      <td className="px-3 py-2 text-center align-top">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${stColor}`}>{st || "—"}</span>
                      </td>
                      <td className={`px-3 py-2 text-center text-xs align-top ${rlColor}`}>{row.risk_level || "—"}</td>
                      <td className="px-3 py-2 text-xs text-[#2d3748] align-top">{row.summary || "—"}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Business Impact */}
      {report.business_impact && (
        <div className="bg-[#fffaf0] border border-[#feebc8] rounded-lg p-4">
          <h3 className="text-[14px] font-bold text-[#c05621] mb-2">ผลกระทบทางธุรกิจโดยรวม</h3>
          <p className="text-[14px] text-[#2d3748] leading-relaxed">{report.business_impact}</p>
        </div>
      )}

      {/* Generic fields fallback — render remaining truly unknown keys */}
      {(() => {
        const knownKeys = new Set(["report_title","analysis_date","documents_analyzed","executive_summary","key_differences","financial_comparison","sla_comparison","risks_and_recommendations","comparison_summary","overall_recommendation","validation_items","negotiation_priorities","business_impact","overall_status","financial_summary","risk_matrix"])
        const extras = Object.entries(report).filter(([k]) => !knownKeys.has(k) && report[k] != null)
        if (extras.length === 0) return null
        return (
          <div>
            <h3 className="text-[15px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">ข้อมูลเพิ่มเติม</h3>
            <div className="space-y-2">
              {extras.map(([key, val]) => (
                <div key={key} className="bg-[#f7fafc] border border-[#e2e8f0] rounded-lg p-3 text-sm">
                  <span className="font-semibold text-[#1a365d] capitalize">{key.replace(/_/g, " ")}: </span>
                  <span className="text-[#2d3748]">{typeof val === "object" ? JSON.stringify(val, null, 2) : String(val)}</span>
                </div>
              ))}
            </div>
          </div>
        )
      })()}

      {/* Raw JSON toggle */}
      <div className="pt-3 border-t border-[#e2e8f0]">
        <button
          className="text-xs text-[#718096] hover:text-[#2b6cb0] transition-colors"
          onClick={() => setShowRaw(!showRaw)}
        >
          {showRaw ? "ซ่อน" : "แสดง"} raw JSON
        </button>
        {showRaw && (
          <pre className="mt-2 text-xs bg-[#f7fafc] border border-[#e2e8f0] rounded-lg p-3 overflow-x-auto max-h-60 overflow-y-auto font-mono text-[#2d3748]">
            {JSON.stringify(report, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

// ── TOR Verification Report renderer ──
function TorVerificationReportView({ report }: { report: TorVerificationReport }) {
  const [showRaw, setShowRaw] = useState(false)
  const s = report.verification_summary

  const verdictColor = (verdict: string) => {
    const v = (verdict || "").toUpperCase()
    if (v === "PASS") return "bg-[#f0fff4] text-[#276749] border-[#c6f6d5]"
    if (v === "FAIL") return "bg-[#fff5f5] text-[#c53030] border-[#fed7d7]"
    return "bg-[#fffaf0] text-[#c05621] border-[#feebc8]"
  }

  // Collect all unique keys across requirements (excluding 'id')
  const reqKeys = Array.from(
    new Set(report.requirements.flatMap(r => Object.keys(r).filter(k => k !== "id")))
  )

  return (
    <div className="space-y-5">
      {/* Summary header */}
      <div className="bg-[#ebf8ff] border-l-4 border-[#2b6cb0] rounded-[10px] p-5 shadow-[0_2px_10px_rgba(0,0,0,0.05)]">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div>
            {s.spec_document && <div className="text-xs text-[#718096]">Spec: <span className="font-semibold text-[#2d3748]">{s.spec_document}</span></div>}
            {s.datasheet_document && <div className="text-xs text-[#718096]">Datasheet: <span className="font-semibold text-[#2d3748]">{s.datasheet_document}</span></div>}
          </div>
          {s.overall_verdict && (
            <span className={`text-sm font-bold px-3 py-1 rounded-full border ${verdictColor(s.overall_verdict)}`}>
              {s.overall_verdict}
            </span>
          )}
        </div>

        {/* Stat boxes */}
        <div className="flex gap-3 flex-wrap">
          {s.total_requirements != null && (
            <div className="flex-1 min-w-[80px] rounded-[8px] bg-white border border-[#e2e8f0] py-3 text-center shadow-sm">
              <div className="text-2xl font-[800] text-[#1a365d]">{s.total_requirements}</div>
              <div className="text-[11px] text-[#718096] mt-0.5">Total</div>
            </div>
          )}
          {s.pass_count != null && (
            <div className="flex-1 min-w-[80px] rounded-[8px] bg-[#f0fff4] border border-[#c6f6d5] py-3 text-center shadow-sm">
              <div className="text-2xl font-[800] text-[#276749]">{s.pass_count}</div>
              <div className="text-[11px] text-[#718096] mt-0.5">PASS</div>
            </div>
          )}
          {s.partial_count != null && (
            <div className="flex-1 min-w-[80px] rounded-[8px] bg-[#fffaf0] border border-[#feebc8] py-3 text-center shadow-sm">
              <div className="text-2xl font-[800] text-[#c05621]">{s.partial_count}</div>
              <div className="text-[11px] text-[#718096] mt-0.5">PARTIAL</div>
            </div>
          )}
          {s.fail_count != null && (
            <div className="flex-1 min-w-[80px] rounded-[8px] bg-[#fff5f5] border border-[#fed7d7] py-3 text-center shadow-sm">
              <div className="text-2xl font-[800] text-[#c53030]">{s.fail_count}</div>
              <div className="text-[11px] text-[#718096] mt-0.5">FAIL</div>
            </div>
          )}
          {s.coverage_percent != null && (
            <div className="flex-1 min-w-[80px] rounded-[8px] bg-white border border-[#e2e8f0] py-3 text-center shadow-sm">
              <div className="text-2xl font-[800] text-[#2b6cb0]">{s.coverage_percent}%</div>
              <div className="text-[11px] text-[#718096] mt-0.5">Coverage</div>
            </div>
          )}
        </div>

        {s.notes && (
          <p className="text-[13px] text-[#2d3748] mt-3 leading-relaxed italic">{s.notes}</p>
        )}
      </div>

      {/* Requirements table */}
      {report.requirements.length > 0 && (
        <div>
          <h3 className="text-[15px] font-bold text-[#2b6cb0] border-l-4 border-[#2b6cb0] pl-3 mb-3">รายการ Requirements</h3>
          <div className="overflow-x-auto rounded-[10px] shadow-[0_2px_10px_rgba(0,0,0,0.05)]">
            <table className="min-w-full text-[12px] border-collapse">
              <thead>
                <tr className="bg-[#1a365d] text-white">
                  <th className="px-3 py-2.5 text-left font-semibold w-10">#</th>
                  {reqKeys.map(k => (
                    <th key={k} className="px-3 py-2.5 text-left font-semibold capitalize">{k.replace(/_/g, " ")}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {report.requirements.map((req, idx) => {
                  const statusVal = (req.status || req.verdict || req.result || "").toUpperCase()
                  const rowBg = idx % 2 === 0 ? "bg-white" : "bg-[#f7fafc]"
                  return (
                    <tr key={idx} className={`border-b border-[#e2e8f0] ${rowBg} hover:bg-[#ebf8ff] transition-colors`}>
                      <td className="px-3 py-[9px] text-[#718096] font-mono text-xs align-top">{req.id ?? idx + 1}</td>
                      {reqKeys.map(k => {
                        const val = req[k]
                        const isStatusCol = k === "status" || k === "verdict" || k === "result"
                        if (isStatusCol && val) {
                          const v = String(val).toUpperCase()
                          const sc = v === "PASS" ? "bg-[#f0fff4] text-[#276749]"
                            : v === "FAIL" ? "bg-[#fff5f5] text-[#c53030]"
                            : v === "PARTIAL" ? "bg-[#fffaf0] text-[#c05621]"
                            : "bg-[#f7fafc] text-[#718096]"
                          return (
                            <td key={k} className="px-3 py-[9px] text-center align-top">
                              <span className={`inline-block text-xs font-bold px-2 py-0.5 rounded-full ${sc}`}>{v}</span>
                            </td>
                          )
                        }
                        return (
                          <td key={k} className="px-3 py-[9px] text-[#2d3748] align-top">
                            {val == null ? "—" : typeof val === "object" ? JSON.stringify(val) : String(val)}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Raw JSON toggle */}
      <div className="pt-3 border-t border-[#e2e8f0]">
        <button
          className="text-xs text-[#718096] hover:text-[#2b6cb0] transition-colors"
          onClick={() => setShowRaw(!showRaw)}
        >
          {showRaw ? "ซ่อน" : "แสดง"} raw JSON
        </button>
        {showRaw && (
          <pre className="mt-2 text-xs bg-[#f7fafc] border border-[#e2e8f0] rounded-lg p-3 overflow-x-auto max-h-60 overflow-y-auto font-mono text-[#2d3748]">
            {JSON.stringify(report, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

// ── Main component ──

interface LlmResultRendererProps {
  content: string
}

export default function LlmResultRenderer({ content }: LlmResultRendererProps) {
  const [showRaw, setShowRaw] = useState(false)

  // 1. Try JSON validation report
  const report = tryParseJson(content)
  if (report) {
    return (
      <div className="space-y-2">
        <StatBoxes summary={report.validation_summary} />

        <ValidationTable rules={report.validation_results} />

        <BusinessImpact report={report} />

        {report.documents_reviewed && report.documents_reviewed.length > 0 && (
          <DocumentsReviewed docs={report.documents_reviewed} />
        )}

        {/* Toggle raw JSON */}
        <div className="pt-3 border-t border-[#e2e8f0]">
          <button
            className="text-xs text-[#718096] hover:text-[#2b6cb0] transition-colors"
            onClick={() => setShowRaw(!showRaw)}
          >
            {showRaw ? "Hide" : "Show"} raw JSON
          </button>
          {showRaw && (
            <pre className="mt-2 text-xs bg-[#f7fafc] border border-[#e2e8f0] rounded-[8px] p-3 overflow-x-auto max-h-60 overflow-y-auto font-mono text-[#2d3748]">
              {JSON.stringify(report, null, 2)}
            </pre>
          )}
        </div>
      </div>
    )
  }

  // 2. Try TOR Verification Report
  const torReport = tryParseTorVerification(content)
  if (torReport) {
    return <TorVerificationReportView report={torReport} />
  }

  // 3. Try Contract Comparison Report
  const contractReport = tryParseContractComparison(content)
  if (contractReport) {
    return <ContractComparisonReportView report={contractReport} />
  }

  // 4. Try HTML
  if (isHtml(content)) {
    return (
      <div
        className="prose prose-sm max-w-none text-slate-700"
        dangerouslySetInnerHTML={{ __html: content }}
      />
    )
  }

  // 5. Try Markdown
  if (isMarkdown(content)) {
    return <MarkdownView text={content} />
  }

  // 6. Try any valid JSON (generic renderer)
  const anyJson = tryParseRaw(content)
  if (anyJson !== null) {
    return (
      <div className="space-y-3">
        <GenericJsonView data={anyJson} />
        <div className="pt-3 border-t border-[#e2e8f0]">
          <button
            className="text-xs text-[#718096] hover:text-[#2b6cb0] transition-colors"
            onClick={() => setShowRaw(!showRaw)}
          >
            {showRaw ? "ซ่อน" : "แสดง"} raw JSON
          </button>
          {showRaw && (
            <pre className="mt-2 text-xs bg-[#f7fafc] border border-[#e2e8f0] rounded-lg p-3 overflow-x-auto max-h-60 overflow-y-auto font-mono text-[#2d3748]">
              {JSON.stringify(anyJson, null, 2)}
            </pre>
          )}
        </div>
      </div>
    )
  }

  // 7. Fallback: plain text
  return <div className="whitespace-pre-wrap text-slate-700 leading-relaxed">{content}</div>
}
