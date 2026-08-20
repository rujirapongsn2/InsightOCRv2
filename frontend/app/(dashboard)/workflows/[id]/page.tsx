"use client"

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { useParams, useSearchParams } from "next/navigation"
import Link from "next/link"
import {
    ReactFlow,
    ReactFlowProvider,
    Background,
    Controls,
    MiniMap,
    addEdge,
    useNodesState,
    useEdgesState,
    useReactFlow,
    Handle,
    Position,
    MarkerType,
    type Node,
    type Edge,
    type Connection,
    type NodeProps,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import {
    ArrowLeft, Save, Play, Loader2, CalendarClock, Trash2, X,
    Zap, FileText, Sparkles, GitBranch, Shuffle, Code2, Globe, FileOutput, Briefcase,
    CheckCircle2, XCircle, CircleDashed, CircleDot, SkipForward, Activity, ChevronDown, ChevronRight,
    Download, Plus, FlaskConical, Cloud, CloudUpload, CloudDownload, Webhook, Copy, RotateCw, ShieldOff, Maximize2, Upload,
} from "lucide-react"
import {
    Workflow, WorkflowRun, NodeTypeDef, JobSummary,
    getWorkflow, updateWorkflow, runWorkflow, getRun, getWorkflowRuns, getNodeTypes, getJobs, getSchemas, testNode,
    downloadRunOutput, downloadRunArtifact, rotateWorkflowWebhookSecret, disableWorkflowWebhookSecret,
    suggestVariables, type VariableCandidate, type VariableSuggestion, type SchemaSummary,
    getWorkflowAgentSkills, type WorkflowAgentSkill,
} from "@/lib/workflows-api"
import { Integration, getActiveIntegrations } from "@/lib/integrations-api"
import { listAIProviders, type AIProviderSetting } from "@/lib/ai-settings-api"

// ── AI variable finder context (provides workflowId + token to the picker) ──
const AiFinderContext = createContext<{ workflowId: string; token: string | null; defaultIntegrationId?: string | null } | null>(null)

// ── Node visuals ─────────────────────────────────────────────────────
const CATEGORY_STYLE: Record<string, { icon: any; color: string; bg: string }> = {
    trigger:   { icon: Zap,        color: "#D97706", bg: "#FEF3C7" },
    data:      { icon: FileText,   color: "#2786C2", bg: "#EBF4FB" },
    ai:        { icon: Sparkles,   color: "#7C3AED", bg: "#F3E8FF" },
    logic:     { icon: GitBranch,  color: "#0D9488", bg: "#CCFBF1" },
    developer: { icon: Code2,      color: "#334155", bg: "#E2E8F0" },
    action:    { icon: Globe,      color: "#DC2626", bg: "#FEE2E2" },
    storage:   { icon: Cloud,      color: "#0EA5E9", bg: "#E0F2FE" },
}

const TYPE_ICON: Record<string, any> = {
    trigger_manual: Zap,
    trigger_schedule: CalendarClock,
    trigger_webhook: Webhook,
    job_source: Briefcase,
    document_source: FileText,
    llm: Sparkles,
    condition: GitBranch,
    transform: Shuffle,
    python_code: Code2,
    http_request: Globe,
    api: Globe,
    write_output: FileOutput,
    publish_artifact: Upload,
    webhook_response: Webhook,
    gdrive_upload: CloudUpload,
    gdrive_import: CloudDownload,
    onedrive_upload: CloudUpload,
    onedrive_import: CloudDownload,
}

const STATUS_BORDER: Record<string, string> = {
    running: "#84CC16",
    succeeded: "#10B981",
    failed: "#EF4444",
    skipped: "#CBD5E1",
}

type WfNodeData = {
    nodeType: string
    label: string
    config: Record<string, any>
    category: string
    runStatus?: string
}

function WfNode({ data, selected }: NodeProps) {
    const d = data as WfNodeData
    const style = CATEGORY_STYLE[d.category] || CATEGORY_STYLE.action
    const Icon = TYPE_ICON[d.nodeType] || style.icon
    const isTrigger = d.category === "trigger"
    const isCondition = d.nodeType === "condition"
    const borderColor = d.runStatus ? STATUS_BORDER[d.runStatus] : selected ? "#2786C2" : "#E2E8F0"
    const isRunning = d.runStatus === "running"

    return (
        <div
            className="rounded-xl bg-white shadow-sm px-3 py-2.5 min-w-[180px] max-w-[220px]"
            style={{
                border: isRunning ? "3px solid #84CC16" : `2px solid ${borderColor}`,
                animation: isRunning ? "wf-node-run-flash 0.9s ease-in-out infinite" : undefined,
            }}
        >
            {!isTrigger && <Handle type="target" position={Position.Left} className="!w-2.5 !h-2.5 !bg-[#94A3B8]" />}
            <div className="flex items-center gap-2">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg" style={{ background: style.bg }}>
                    <Icon className="h-4 w-4" style={{ color: style.color }} />
                </span>
                <div className="min-w-0">
                    <div className="text-xs font-semibold text-[#0D1B2A] truncate">{d.label}</div>
                    <div className="text-[10px] text-[#94A3B8]">{d.nodeType}</div>
                </div>
            </div>
            {isCondition ? (
                <>
                    <Handle id="true" type="source" position={Position.Right} style={{ top: "35%" }} className="!w-2.5 !h-2.5 !bg-emerald-500" />
                    <Handle id="false" type="source" position={Position.Right} style={{ top: "75%" }} className="!w-2.5 !h-2.5 !bg-red-400" />
                    <div className="absolute right-1.5 text-[9px] text-emerald-600 font-semibold" style={{ top: "calc(35% - 7px)" }}>T</div>
                    <div className="absolute right-1.5 text-[9px] text-red-500 font-semibold" style={{ top: "calc(75% - 7px)" }}>F</div>
                </>
            ) : (
                <Handle type="source" position={Position.Right} className="!w-2.5 !h-2.5 !bg-[#2786C2]" />
            )}
        </div>
    )
}

const nodeTypes = { wf: WfNode }

const TRIGGER_TYPE_LABEL: Record<string, string> = {
    manual: "manual",
    schedule: "schedule",
    webhook: "webhook",
    node_test: "ทดสอบโหนด",
}

type NodeHelpContent = {
    purpose: string
    steps: string[]
    example: string
    caution?: string
}

const NODE_HELP_CONTENT: Record<string, NodeHelpContent> = {
    trigger_manual: {
        purpose: "ใช้เริ่ม workflow ด้วยตนเองจากปุ่ม Run ด้านบน เหมาะกับงานที่ต้องการตรวจผลก่อนรันทุกครั้ง",
        steps: [
            "วาง node นี้ไว้ต้นทาง แล้วเชื่อมต่อไปยัง node ที่ต้องการทำงานต่อ",
            "กด Run และใส่ Trigger input เป็น JSON เฉพาะเมื่อ node ถัดไปต้องรับข้อมูลจากภายนอก",
        ],
        example: "ตัวอย่าง: Manual Trigger → Jobs เพื่อดึงเอกสารจาก Job ที่เลือก",
    },
    trigger_schedule: {
        purpose: "ใช้เริ่ม workflow อัตโนมัติตามวันและเวลาที่กำหนด โดยไม่ต้องเปิดหน้าเว็บค้างไว้",
        steps: [
            "เปิดใช้งาน Schedule แล้วเลือกความถี่และเวลาให้ตรงกับรอบงาน",
            "กด Save หลังตั้งค่า ระบบจึงบันทึกตารางและเริ่มรันตามรอบที่เลือก",
        ],
        example: "ตัวอย่าง: ตั้งเป็นทุกวัน 09:00 เพื่อประมวลผลข้อมูลประจำวัน",
        caution: "หนึ่ง workflow ใช้ Schedule Trigger ได้เพียงหนึ่ง node",
    },
    trigger_webhook: {
        purpose: "ใช้รับคำสั่งหรือข้อมูลจากระบบภายนอก แล้วเริ่ม workflow ทันทีเมื่อมี HTTP request เข้ามา",
        steps: [
            "กด Generate เพื่อสร้าง Webhook URL และคัดลอกไปตั้งค่าที่ระบบต้นทาง",
            "อ้างข้อมูลที่ส่งเข้ามาด้วย {{trigger.body.<field>}} ใน node ถัดไป",
        ],
        example: "ตัวอย่าง: ส่ง POST พร้อม { \"job_id\": \"...\" } จากระบบต้นทาง",
        caution: "เก็บ Webhook URL เป็นความลับ และ Regenerate ทันทีเมื่อสงสัยว่าลิงก์รั่ว",
    },
    job_source: {
        purpose: "ใช้ดึงข้อมูลเอกสารจาก Job หนึ่งชุด เพื่อส่งให้ LLM, Mapping หรือ API ใน workflow เดียวกัน",
        steps: [
            "เลือก Job ที่ต้องการเป็นแหล่งข้อมูล",
            "เลือก reviewed สำหรับข้อมูลที่ผู้ใช้ตรวจแล้ว; เลือก extracted เมื่อต้องการผลสกัดล่าสุด; เลือก ocr_text เมื่อต้องการข้อความเอกสารดิบ",
            "กำหนดสถานะ, เฉพาะงานที่ประมวลผลเสร็จ และจำนวนสูงสุด เพื่อลดข้อมูลที่ไม่จำเป็น",
        ],
        example: "ตัวอย่าง: เลือก Job และใช้ reviewed เพื่อส่งเฉพาะข้อมูลที่ตรวจแล้ว",
    },
    document_source: {
        purpose: "ใช้ส่งรายการเอกสารพร้อมข้อความ OCR และข้อมูลสกัดไปยัง node ถัดไป โดยเลือกได้จาก Job เดียว",
        steps: [
            "เลือก Job ที่ต้องการอ่านเอกสาร",
            "ใช้ตัวกรองสถานะและจำนวนสูงสุดเพื่อเลือกเฉพาะเอกสารที่พร้อมใช้งาน",
            "เปิดรวมข้อความ OCR เมื่อต้องส่งเนื้อหาเอกสารให้ LLM วิเคราะห์",
        ],
        example: "ตัวอย่าง: กรองเฉพาะเอกสารที่สถานะ Reviewed ก่อนวิเคราะห์",
    },
    llm: {
        purpose: "ใช้ให้ AI วิเคราะห์ สรุป จัดหมวดหมู่ หรือสร้างข้อความจากข้อมูลของ node ก่อนหน้า",
        steps: [
            "เลือก AI Provider เฉพาะกรณีที่ต้องใช้ model อื่น; เว้นว่างเพื่อใช้ Agent Provider กลางของระบบ",
            "ใส่ System prompt เพื่อกำหนดบทบาทและรูปแบบคำตอบ แล้วใส่คำสั่งจริงใน Prompt",
            "แทรกตัวแปรจาก node ก่อนหน้าใน Prompt แทนการคัดลอกข้อมูลเอง",
            "เปิด JSON output เฉพาะเมื่อ Prompt สั่งให้ตอบ JSON ที่ถูกต้องและ node ถัดไปต้องอ้างฟิลด์ภายใน",
        ],
        example: "ตัวอย่าง: ใช้ {{job.documents}} ใน prompt เพื่อสรุปประเด็นสำคัญ",
        caution: "ระบุรูปแบบผลลัพธ์ให้ชัดเจน เช่น หัวข้อ ตาราง หรือ JSON เพื่อให้ node ถัดไปใช้งานต่อได้แน่นอน",
    },
    condition: {
        purpose: "ใช้ตัดสินใจและส่งงานต่อคนละเส้นทางตามผล True หรือ False",
        steps: [
            "ใส่ค่าที่ต้องการตรวจใน ค่าที่ตรวจ โดยแทรกตัวแปรจาก node ก่อนหน้า",
            "เลือกเงื่อนไขให้ตรงชนิดข้อมูล เช่น greater_than สำหรับตัวเลข หรือ contains สำหรับข้อความ",
            "ใส่ค่าที่ใช้เทียบ ยกเว้นเงื่อนไข is_empty และ is_not_empty",
        ],
        example: "ตัวอย่าง: ถ้า {{job.total}} > 100000 ให้ส่งไปตรวจสอบเพิ่มเติม",
    },
    transform: {
        purpose: "ใช้จัดรูปแบบข้อมูลใหม่และเปลี่ยนชื่อฟิลด์ก่อนส่งต่อให้ API, ไฟล์ หรือ node อื่น",
        steps: [
            "เพิ่ม mapping หนึ่งแถวต่อหนึ่งฟิลด์ผลลัพธ์",
            "ตั้งชื่อฟิลด์ใหม่ทางซ้าย และแทรกค่าจาก node ก่อนหน้าทางขวา",
            "ใช้ข้อความคงที่ร่วมกับตัวแปรได้ เช่น INV-{{job.invoice_number}}",
        ],
        example: "ตัวอย่าง: map {{job.invoice_number}} ไปเป็น invoiceNo",
    },
    python_code: {
        purpose: "ใช้คำนวณหรือแปลงข้อมูลที่ทำด้วย Mapping ปกติไม่ได้ โดยรันใน sandbox",
        steps: [
            "ใส่ข้อมูลจาก node ก่อนหน้าใน Input ซึ่งจะถูกส่งให้โค้ดในตัวแปร inputs",
            "เขียนโค้ดและกำหนดตัวแปร result เพื่อส่งผลให้ node ถัดไป",
            "กำหนด Timeout ให้พอกับงาน แต่ไม่สูงเกินความจำเป็น",
        ],
        example: "ตัวอย่าง: รวมยอด line items แล้วคืนค่าเป็น { \"total\": 1250 }",
        caution: "โค้ดทำงานใน sandbox; อย่าใส่ secret หรือพึ่งพาไฟล์/เครือข่ายภายนอกโดยไม่จำเป็น",
    },
    http_request: {
        purpose: "ใช้ส่งข้อมูลไปยัง REST API หรือ Webhook ภายนอก และรับผลตอบกลับเข้าสู่ workflow",
        steps: [
            "เลือก Method ให้ตรงกับ API และใส่ URL แบบ HTTPS ที่เชื่อถือได้",
            "ใส่ Headers เป็น JSON ที่ถูกต้อง เช่น Content-Type และ Authorization ตามเอกสาร API",
            "แทรกข้อมูลจาก node ก่อนหน้าใน Body แล้วทดสอบ node ก่อนใช้กับข้อมูลจริง",
        ],
        example: "ตัวอย่าง: POST {{job.reviewed}} ไปยังระบบบัญชีหลังตรวจเอกสาร",
        caution: "ตรวจปลายทางและข้อมูลใน Body ทุกครั้ง เพราะ node นี้สามารถส่งข้อมูลออกนอกระบบได้",
    },
    api: {
        purpose: "ใช้ส่งข้อมูลจาก node ก่อนหน้าไปยัง Custom API ที่ตั้งค่าไว้ในเมนู Integration โดยไม่ต้องใส่ endpoint หรือ credentials ซ้ำใน workflow",
        steps: [
            "สร้างและทดสอบ Custom API ในเมนู Integration ก่อน แล้วเลือกการเชื่อมต่อนั้นในฟอร์มนี้",
            "ใส่ Request body โดยใช้ปุ่มแทรกข้อมูลเพื่อเลือกผลจาก node ก่อนหน้า หรือเว้นว่างเพื่อใช้ Payload Template ของ Custom API",
            "ตั้ง Timeout และทดสอบ node เพื่อดู HTTP status กับ response ก่อนเปิดใช้ workflow จริง",
        ],
        example: "ตัวอย่าง: Transform / Mapping → API เพื่อส่งข้อมูล invoice ที่จัดรูปแบบแล้วไปยังระบบบัญชี",
        caution: "ข้อมูลใน Request body จะถูกส่งออกนอก InsightDOC ตาม endpoint ของ Custom API ที่เลือก",
    },
    write_output: {
        purpose: "ใช้สร้างไฟล์ผลลัพธ์จากข้อมูลใน workflow เพื่อดาวน์โหลดหรืออัปโหลดต่อไปยัง storage",
        steps: [
            "ตั้งชื่อไฟล์และเลือกรูปแบบให้เหมาะกับข้อมูล",
            "ใส่เนื้อหาจาก node ก่อนหน้า; xlsx และ docx เหมาะกับรายการ object ที่ต้องการแสดงเป็นตาราง",
            "นำ output ของ node นี้ไปเชื่อมกับ Google Drive หรือ OneDrive upload ได้",
        ],
        example: "ตัวอย่าง: เขียนสรุปเป็น report.md จากผลของ node LLM",
    },
    publish_artifact: {
        purpose: "ใช้เผยแพร่ไฟล์ที่ Agent สร้างให้เป็นผลลัพธ์ของ Workflow run เพื่อดาวน์โหลดและตรวจสอบย้อนหลังได้",
        steps: [
            "เชื่อมจาก Agent แล้วเลือก {{agent.artifacts.0.path}} เป็นไฟล์จาก Agent",
            "เว้น Job context เพื่อใช้ Job เดียวจากโหนดก่อนหน้า หรือเลือก Job เมื่อ workflow มีหลายแหล่งข้อมูล",
            "ตั้งชื่อใหม่เฉพาะเมื่ออยากให้ชื่อไฟล์ที่ดาวน์โหลดต่างจากไฟล์ต้นทาง",
        ],
        example: "ตัวอย่าง: Agent สร้าง outputs/report-contract.docx → Publish Artifact → ดาวน์โหลดจาก Activity",
        caution: "หากเผยแพร่ไม่สำเร็จ Workflow จะล้มเหลว เพื่อไม่ให้รายงานที่ขาดหายถูกมองว่าสมบูรณ์",
    },
    webhook_response: {
        purpose: "ใช้กำหนดข้อมูลที่ระบบภายนอกจะอ่านได้เมื่อเรียก Workflow ผ่าน Webhook",
        steps: [
            "เปิด ใช้เป็น result ของ webhook แล้วกำหนด HTTP status ที่ต้องการ",
            "ใส่ Result body โดยแทรกผลจาก node ก่อนหน้า",
            "กำหนดเงื่อนไขเฉพาะเมื่อ response นี้ควรใช้เฉพาะบางเส้นทาง",
        ],
        example: "ตัวอย่าง: คืน { \"status\": \"ok\", \"result\": {{llm}} }",
    },
    gdrive_upload: {
        purpose: "ใช้บันทึกไฟล์ผลลัพธ์ของ workflow ลง Google Drive",
        steps: [
            "เลือกบัญชี Google Drive ที่ตั้งค่าไว้ใน Integration",
            "ใส่ Folder ID ปลายทางและตรวจว่า service account มีสิทธิ์เข้าถึงโฟลเดอร์นั้น",
            "กำหนดชื่อ, MIME type และเนื้อหาจาก node ก่อนหน้า",
        ],
        example: "ตัวอย่าง: บันทึก report.pdf ลงโฟลเดอร์รายงานประจำเดือน",
    },
    gdrive_import: {
        purpose: "ใช้ดึงไฟล์จาก Google Drive เข้า Job แล้วให้ระบบประมวลผลเอกสารต่อ",
        steps: [
            "เลือกบัญชี Google Drive และใส่ Folder ID ต้นทางที่แชร์ให้ service account อ่านได้",
            "เลือก Job ปลายทาง และเลือก Schema เมื่อต้องการบังคับรูปแบบการสกัดข้อมูล",
            "ใส่ตัวกรองชื่อไฟล์ เช่น .pdf และจำกัดจำนวนไฟล์ต่อรอบเพื่อควบคุมปริมาณงาน",
        ],
        example: "ตัวอย่าง: เลือกโฟลเดอร์ใบแจ้งหนี้และนำเข้าเฉพาะไฟล์ .pdf",
    },
    onedrive_upload: {
        purpose: "ใช้บันทึกไฟล์ผลลัพธ์ของ workflow ลง OneDrive หรือ SharePoint",
        steps: [
            "เลือกบัญชี OneDrive ที่ตั้งค่าไว้ใน Integration",
            "ใส่ Folder item ID หรือเว้นว่างเพื่อบันทึกที่ root ของ drive",
            "กำหนดชื่อ, MIME type และเนื้อหาจาก node ก่อนหน้า",
        ],
        example: "ตัวอย่าง: เก็บไฟล์ผลตรวจไว้ในโฟลเดอร์ทีมที่กำหนด",
    },
    onedrive_import: {
        purpose: "ใช้ดึงไฟล์จาก OneDrive หรือ SharePoint เข้า Job แล้วประมวลผลเอกสารต่อ",
        steps: [
            "เลือกบัญชี OneDrive และ Folder item ID; เว้นว่างเพื่ออ่านจาก root",
            "เลือก Job ปลายทางและ Schema เมื่อต้องการบังคับรูปแบบการสกัดข้อมูล",
            "กรองชื่อไฟล์และกำหนดจำนวนสูงสุดให้เหมาะกับรอบงาน",
        ],
        example: "ตัวอย่าง: นำเข้าไฟล์จากโฟลเดอร์รับเอกสารของทีมอัตโนมัติ",
    },
}

const FIELD_HELP: Record<string, string> = {
    "job_source.job_id": "เลือก Job ที่จะอ่านข้อมูลเอกสารที่ประมวลผลแล้ว",
    "document_source.job_id": "เลือก Job ที่เป็นแหล่งเอกสารสำหรับส่งต่อไปยัง node ถัดไป",
    "gdrive_import.job_id": "เลือก Job ปลายทางสำหรับเก็บไฟล์ที่นำเข้าจาก Google Drive",
    "onedrive_import.job_id": "เลือก Job ปลายทางสำหรับเก็บไฟล์ที่นำเข้าจาก OneDrive",
    auto_review: "เมื่อเปิดใช้งาน: หลัง OCR และสกัดข้อมูลเสร็จ เอกสารจะถูก Review ยืนยันข้อมูลอัตโนมัติ (สถานะเป็น reviewed)",
    wait_for_completion: "เปิดใช้งาน (ค่าเริ่มต้น): โหนดจะรอให้ OCR & Extraction ทุกเอกสารเสร็จสมบูรณ์ก่อนส่งผลลัพธ์ไปยังโหนดถัดไป; หากปิด: นำเข้าไฟล์แล้วส่งต่อทันที",
    data_source: "reviewed เหมาะกับข้อมูลที่ตรวจแล้ว, extracted คือผลสกัดล่าสุด, ocr_text คือข้อความเอกสารดิบ",
    status: "เลือก reviewed หรือ extraction_completed เพื่อกรองเพิ่ม; เว้นว่างเมื่อไม่ต้องการจำกัดสถานะ",
    only_completed: "เปิดไว้เพื่อไม่ให้ส่งเอกสารที่ยังประมวลผลไม่เสร็จเข้า workflow",
    limit: "กำหนดจำนวนสูงสุดต่อรอบเพื่อควบคุมเวลาและปริมาณข้อมูล",
    include_ocr_text: "เปิดเมื่อต้องส่งข้อความเต็มของเอกสารให้ node ถัดไป เช่น LLM",
    ai_provider_id: "เว้นว่างเพื่อใช้ Agent Provider กลาง หรือเลือก model เฉพาะสำหรับ node นี้",
    system_prompt: "กำหนดบทบาท, ภาษา และกติกาคงที่ของ AI เช่น ห้ามเดาข้อมูลที่ไม่มีในเอกสาร",
    prompt: "คำสั่งงานหลักของ AI; ใช้ปุ่มแทรกข้อมูลเพื่อเลือกตัวแปรจาก node ก่อนหน้า",
    json_output: "เปิดเมื่อ Prompt ระบุให้ตอบ JSON ที่ถูกต้องและต้องใช้ฟิลด์ผลลัพธ์ต่อ",
    left: "ค่าหรือตัวแปรที่ต้องการตรวจ เช่น {{jobs_1.count}}",
    operator: "เลือกวิธีเปรียบเทียบให้ตรงกับข้อความหรือตัวเลข",
    right: "ค่าที่นำมาเทียบ; เว้นว่างได้เมื่อใช้ is_empty หรือ is_not_empty",
    mappings: "เพิ่มหนึ่งแถวต่อหนึ่งฟิลด์ผลลัพธ์: ชื่อฟิลด์ใหม่ = ค่าหรือตัวแปรจาก node ก่อนหน้า",
    code: "เขียนโค้ดโดยอ่านข้อมูลจาก inputs และกำหนด result เป็นผลลัพธ์สุดท้าย",
    input: "ข้อมูลที่ส่งให้โค้ด Python ในตัวแปร inputs; ใช้ตัวแปรจาก node ก่อนหน้าได้",
    timeout: "เวลาสูงสุดของโค้ด; งานทั่วไปใช้ค่าเริ่มต้นก่อนแล้วค่อยเพิ่มเมื่อจำเป็น",
    method: "เลือก HTTP method ตามเอกสารของ API ปลายทาง",
    url: "URL ของ API ปลายทาง ควรเป็น HTTPS และตรวจสอบโดเมนก่อนบันทึก",
    headers: "ใส่ JSON ที่ถูกต้อง เช่น { \"Content-Type\": \"application/json\" }",
    body: "ข้อมูลที่จะส่งไปยัง API หรือใช้เป็นผลลัพธ์; แทรกตัวแปรจาก node ก่อนหน้าได้",
    "api.integration_id": "เลือก Custom API ที่ตั้งค่า endpoint, method และ headers ไว้ในเมนู Integration",
    "api.body": "ใช้ปุ่มแทรกข้อมูลเพื่อส่งผลของ node ก่อนหน้า; เว้นว่างเพื่อใช้ Payload Template ที่บันทึกไว้",
    timeout_seconds: "เวลาสูงสุดที่รอ API ตอบกลับ; กำหนดได้ตั้งแต่ 1 ถึง 120 วินาที",
    filename: "ชื่อไฟล์รวมถึงนามสกุล เพื่อให้ผู้รับรู้ประเภทไฟล์ได้ชัดเจน",
    format: "เลือกรูปแบบไฟล์ให้เหมาะกับข้อมูล: json สำหรับระบบ, csv/xlsx สำหรับตาราง, docx สำหรับเอกสาร",
    content: "เนื้อหาที่จะบันทึกหรืออัปโหลด; ใช้ปุ่มแทรกข้อมูลเพื่อเลือกผลจาก node ก่อนหน้า",
    visible: "เปิดเมื่อต้องการให้ node นี้เป็นผลลัพธ์ที่ผู้เรียก Webhook อ่านได้",
    status_code: "HTTP status ที่จะตอบกลับ เช่น 200 เมื่อสำเร็จ หรือ 400 เมื่อข้อมูลไม่ครบ",
    condition_left: "ค่าที่ใช้ตรวจว่า response นี้ควรถูกส่งหรือไม่",
    condition_operator: "วิธีเปรียบเทียบสำหรับการเลือก response",
    condition_right: "ค่าที่ใช้เทียบกับเงื่อนไข response",
    integration_id: "เลือกบัญชีที่สร้างไว้ในเมนู Integration; ต้องเป็นชนิดเดียวกับ node ที่ใช้",
    folder_id: "ระบุโฟลเดอร์ต้นทางหรือปลายทางตามระบบ storage ที่เลือก และตรวจสิทธิ์ของบัญชี",
    schema_id: "เลือก Auto เพื่อใช้ตาม Job/สกัดอัตโนมัติ หรือเลือก Schema เฉพาะสำหรับเอกสารที่นำเข้า",
    name_filter: "ใส่คำหรือนามสกุลไฟล์ เช่น .pdf; เว้นว่างเมื่อต้องการรับทุกไฟล์",
    mime_type: "ระบุ MIME type ให้ตรงกับไฟล์ เช่น application/json หรือ text/csv",
}

function getFieldHelp(nodeType: string, field: NodeTypeDef["config_fields"][number]): string {
    return FIELD_HELP[`${nodeType}.${field.name}`]
        || FIELD_HELP[field.name]
        || field.hint
        || (field.required ? "ต้องระบุก่อนบันทึกและรัน workflow" : "ตั้งค่าได้ตามความต้องการของ workflow")
}

const WEEKDAY_OPTIONS = [
    { value: "1", label: "จันทร์" },
    { value: "2", label: "อังคาร" },
    { value: "3", label: "พุธ" },
    { value: "4", label: "พฤหัสบดี" },
    { value: "5", label: "ศุกร์" },
    { value: "6", label: "เสาร์" },
    { value: "0", label: "อาทิตย์" },
]

const SCHEDULE_PRESETS = [
    { value: "every_5_minutes", label: "ทุก 5 นาที" },
    { value: "every_15_minutes", label: "ทุก 15 นาที" },
    { value: "every_30_minutes", label: "ทุก 30 นาที" },
    { value: "hourly", label: "ทุกชั่วโมง" },
    { value: "daily", label: "ทุกวัน" },
    { value: "weekdays", label: "ทุกวันทำงาน (จันทร์-ศุกร์)" },
    { value: "weekly", label: "ทุกสัปดาห์" },
    { value: "monthly", label: "ทุกเดือน" },
    { value: "custom", label: "กำหนดเองขั้นสูง" },
]

const defaultScheduleConfig = () => ({
    schedule_enabled: false,
    schedule_preset: "daily",
    schedule_time: "09:00",
    schedule_weekday: "1",
    schedule_day: 1,
    custom_cron: "",
})

const parseTime = (value: any) => {
    const match = String(value || "09:00").match(/^([01]?\d|2[0-3]):([0-5]\d)$/)
    return match ? { hour: Number(match[1]), minute: Number(match[2]) } : { hour: 9, minute: 0 }
}

const buildCronFromScheduleConfig = (config: Record<string, any>): string => {
    const preset = config.schedule_preset || "daily"
    const { hour, minute } = parseTime(config.schedule_time)
    if (preset === "every_5_minutes") return "*/5 * * * *"
    if (preset === "every_15_minutes") return "*/15 * * * *"
    if (preset === "every_30_minutes") return "*/30 * * * *"
    if (preset === "hourly") return `${minute} * * * *`
    if (preset === "weekdays") return `${minute} ${hour} * * 1-5`
    if (preset === "weekly") return `${minute} ${hour} * * ${config.schedule_weekday || "1"}`
    if (preset === "monthly") {
        const day = Math.min(31, Math.max(1, Number(config.schedule_day || 1)))
        return `${minute} ${hour} ${day} * *`
    }
    if (preset === "custom") return String(config.custom_cron || "").trim()
    return `${minute} ${hour} * * *`
}

const parseCronToScheduleConfig = (cron: string | null | undefined, enabled: boolean) => {
    const base = defaultScheduleConfig()
    if (!cron) return { ...base, schedule_enabled: enabled }
    const parts = cron.trim().split(/\s+/)
    if (cron === "*/5 * * * *") return { ...base, schedule_enabled: enabled, schedule_preset: "every_5_minutes", custom_cron: cron }
    if (cron === "*/15 * * * *") return { ...base, schedule_enabled: enabled, schedule_preset: "every_15_minutes", custom_cron: cron }
    if (cron === "*/30 * * * *") return { ...base, schedule_enabled: enabled, schedule_preset: "every_30_minutes", custom_cron: cron }
    if (parts.length !== 5) return { ...base, schedule_enabled: enabled, schedule_preset: "custom", custom_cron: cron }
    const [minute, hour, day, month, weekday] = parts
    if (hour === "*" && day === "*" && month === "*" && weekday === "*") {
        return { ...base, schedule_enabled: enabled, schedule_preset: "hourly", schedule_time: `09:${String(minute).padStart(2, "0")}`, custom_cron: cron }
    }
    if (day === "*" && month === "*" && weekday === "1-5") {
        return { ...base, schedule_enabled: enabled, schedule_preset: "weekdays", schedule_time: `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`, custom_cron: cron }
    }
    if (day === "*" && month === "*" && /^[0-6]$/.test(weekday)) {
        return { ...base, schedule_enabled: enabled, schedule_preset: "weekly", schedule_weekday: weekday, schedule_time: `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`, custom_cron: cron }
    }
    if (/^\d+$/.test(day) && month === "*" && weekday === "*") {
        return { ...base, schedule_enabled: enabled, schedule_preset: "monthly", schedule_day: Number(day), schedule_time: `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`, custom_cron: cron }
    }
    if (day === "*" && month === "*" && weekday === "*") {
        return { ...base, schedule_enabled: enabled, schedule_preset: "daily", schedule_time: `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`, custom_cron: cron }
    }
    return { ...base, schedule_enabled: enabled, schedule_preset: "custom", custom_cron: cron }
}

const summarizeSchedule = (config?: Record<string, any>) => {
    if (!config?.schedule_enabled) return "Schedule off"
    const preset = config.schedule_preset || "daily"
    const label = SCHEDULE_PRESETS.find((p) => p.value === preset)?.label || "กำหนดเวลา"
    if (["daily", "weekdays", "weekly", "monthly"].includes(preset)) return `${label} ${config.schedule_time || "09:00"}`
    if (preset === "custom") return config.custom_cron || "Custom cron"
    return label
}

// ── Helpers: backend definition ⇄ React Flow ─────────────────────────
const categoryOf = (defs: NodeTypeDef[], type: string) =>
    defs.find((d) => d.type === type)?.category || "action"

const toFlowNodes = (wf: Workflow, defs: NodeTypeDef[]): Node[] =>
    (wf.definition?.nodes || []).map((n) => ({
        id: n.id,
        type: "wf",
        position: n.position || { x: 0, y: 0 },
        data: {
            nodeType: n.type,
            label: n.data?.label || n.type,
            config: n.type === "trigger_schedule"
                ? { ...parseCronToScheduleConfig(wf.schedule_cron, wf.schedule_enabled), ...(n.data?.config || {}) }
                : n.data?.config || {},
            category: categoryOf(defs, n.type),
        },
    }))

const toFlowEdges = (wf: Workflow): Edge[] =>
    (wf.definition?.edges || []).map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle || undefined,
        targetHandle: e.targetHandle || undefined,
        label: e.sourceHandle === "true" ? "True" : e.sourceHandle === "false" ? "False" : undefined,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { strokeWidth: 1.5 },
    }))

const toDefinition = (nodes: Node[], edges: Edge[]) => ({
    nodes: nodes.map((n) => ({
        id: n.id,
        type: (n.data as WfNodeData).nodeType,
        position: { x: n.position.x, y: n.position.y },
        data: { label: (n.data as WfNodeData).label, config: (n.data as WfNodeData).config },
    })),
    edges: edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle || null,
        targetHandle: e.targetHandle || null,
    })),
})

// ── Run activity helpers ─────────────────────────────────────────────
const RUN_STATUS_ICON: Record<string, any> = {
    pending: CircleDashed,
    running: CircleDot,
    succeeded: CheckCircle2,
    failed: XCircle,
    skipped: SkipForward,
}
const RUN_STATUS_COLOR: Record<string, string> = {
    pending: "text-gray-400",
    running: "text-[#2786C2]",
    succeeded: "text-emerald-500",
    failed: "text-red-500",
    skipped: "text-gray-400",
}

/** Collapsible JSON tree — แทน raw &lt;pre&gt; เล็กๆ */
function JsonTree({ data, depth = 0 }: { data: any; depth?: number }) {
    const [collapsed, setCollapsed] = useState(depth > 0)
    if (data === null || data === undefined) return <span className="text-slate-400 text-[10px]">{String(data)}</span>
    if (typeof data === "boolean") return <span className="text-purple-500 text-[10px]">{String(data)}</span>
    if (typeof data === "number") return <span className="text-blue-500 text-[10px]">{data}</span>
    if (typeof data === "string") {
        const display = data.length > 120 ? data.slice(0, 120) + "…" : data
        return <span className="text-emerald-600 text-[10px]">"{display}"</span>
    }
    const isArr = Array.isArray(data)
    const entries: [string | number, any][] = isArr
        ? (data as any[]).map((v, i) => [i, v])
        : Object.entries(data)
    const count = entries.length
    const [o, c] = isArr ? ["[", "]"] : ["{", "}"]
    if (count === 0) return <span className="text-slate-500 text-[10px]">{o}{c}</span>
    const visible = entries.slice(0, 60)
    return (
        <span>
            <button type="button" onClick={() => setCollapsed(!collapsed)}
                className="text-[10px] text-slate-500 hover:text-[#2786C2] select-none">
                {collapsed ? "▸" : "▾"} {o}{collapsed ? <span className="text-[#94A3B8]"> …{count} </span> : null}
            </button>
            {!collapsed && (
                <div className="pl-3 border-l border-slate-200 ml-0.5">
                    {visible.map(([k, v]) => (
                        <div key={String(k)} className="flex items-start gap-0.5 py-0.5">
                            <span className="text-[10px] text-slate-600 shrink-0 mr-0.5">{isArr ? `[${k}]` : `"${k}"`}:</span>
                            <JsonTree data={v} depth={depth + 1} />
                        </div>
                    ))}
                    {entries.length > 60 && <div className="text-[10px] text-slate-400">…{entries.length - 60} รายการเพิ่มเติม</div>}
                </div>
            )}
            {!collapsed && <span className="text-slate-500 text-[10px]">{c}</span>}
        </span>
    )
}

function NodeRunRow({ nr, runId }: { nr: WorkflowRun["node_runs"][0]; runId: string }) {
    const [open, setOpen] = useState(false)
    const [downloading, setDownloading] = useState(false)
    const [downloadingArtifactIndex, setDownloadingArtifactIndex] = useState<number | null>(null)
    const [downloadError, setDownloadError] = useState<string | null>(null)
    const [expandOutput, setExpandOutput] = useState(false)
    const Icon = RUN_STATUS_ICON[nr.status] || CircleDashed
    const outputFile = nr.node_type === "write_output" && nr.output?.filename ? nr.output.filename : null
    const artifacts = Array.isArray(nr.output?.artifacts)
        ? nr.output.artifacts.filter((artifact: unknown) => artifact && typeof artifact === "object")
        : nr.output?.artifact && typeof nr.output.artifact === "object"
            ? [nr.output.artifact]
            : []

    const handleDownload = async () => {
        if (!outputFile) return
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        if (!token) { setDownloadError("กรุณาเข้าสู่ระบบใหม่"); return }
        try {
            setDownloading(true)
            setDownloadError(null)
            await downloadRunOutput(token, runId, outputFile)
        } catch (e: any) {
            setDownloadError(e.message || "ดาวน์โหลดไม่สำเร็จ")
        } finally {
            setDownloading(false)
        }
    }

    const handleArtifactDownload = async (artifactIndex: number, artifact: any) => {
        const filename = String(artifact?.filename || artifact?.path || "download")
            .replace(/\\/g, "/")
            .split("/")
            .pop() || "download"
        const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
        if (!token) { setDownloadError("กรุณาเข้าสู่ระบบใหม่"); return }
        try {
            setDownloadingArtifactIndex(artifactIndex)
            setDownloadError(null)
            await downloadRunArtifact(token, runId, nr.id, artifactIndex, filename)
        } catch (e: any) {
            setDownloadError(e.message || "ดาวน์โหลดไม่สำเร็จ")
        } finally {
            setDownloadingArtifactIndex(null)
        }
    }

    return (
        <>
            {/* ── Expand output modal ── */}
            {expandOutput && nr.output != null && (
                <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4" onClick={() => setExpandOutput(false)}>
                    <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl flex flex-col max-h-[80vh]" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-between px-4 py-3 border-b">
                            <span className="text-sm font-semibold text-[#0D1B2A]">Output — {nr.node_label || nr.node_id}</span>
                            <button onClick={() => setExpandOutput(false)} className="text-slate-400 hover:text-slate-600"><X className="h-4 w-4" /></button>
                        </div>
                        <div className="overflow-auto flex-1 p-4">
                            <pre className="text-xs text-[#334155] whitespace-pre-wrap font-mono leading-relaxed">
                                {JSON.stringify(nr.output, null, 2)}
                            </pre>
                        </div>
                    </div>
                </div>
            )}
            <div className="border border-[#E2E8F0] rounded-lg">
                <button className="w-full flex items-center gap-2 px-3 py-2 text-left" onClick={() => setOpen(!open)}>
                    {open ? <ChevronDown className="h-3.5 w-3.5 text-[#94A3B8]" /> : <ChevronRight className="h-3.5 w-3.5 text-[#94A3B8]" />}
                    <Icon className={`h-4 w-4 ${RUN_STATUS_COLOR[nr.status]} ${nr.status === "running" ? "animate-pulse" : ""}`} />
                    <span className="text-xs font-medium text-[#0D1B2A] flex-1 truncate">{nr.node_label || nr.node_id}</span>
                    <span className="text-[10px] text-[#94A3B8]">{nr.status}</span>
                </button>
                {open && (
                    <div className="px-3 pb-3 space-y-2">
                        {nr.logs && (
                            <pre className="text-[10px] bg-[#0D1B2A] text-emerald-200 rounded-lg p-2 overflow-auto max-h-32 whitespace-pre-wrap">{nr.logs}</pre>
                        )}
                        {nr.error && <pre className="text-[10px] bg-red-50 text-red-600 rounded-lg p-2 overflow-auto max-h-32 whitespace-pre-wrap">{nr.error}</pre>}
                        {nr.output != null && (
                            <div className="rounded-lg bg-[#F8F9FA] border border-[#E2E8F0] p-2">
                                <div className="flex items-center justify-between mb-1">
                                    <span className="text-[9px] uppercase tracking-wide text-[#94A3B8] font-semibold">Output</span>
                                    <button
                                        type="button"
                                        onClick={() => setExpandOutput(true)}
                                        title="เปิดแบบเต็มจอ"
                                        className="text-[#94A3B8] hover:text-[#2786C2] p-0.5 rounded"
                                    >
                                        <Maximize2 className="h-3 w-3" />
                                    </button>
                                </div>
                                <div className="text-[10px] font-mono overflow-auto max-h-48">
                                    <JsonTree data={nr.output} depth={0} />
                                </div>
                            </div>
                        )}
                        {outputFile && (
                            <div>
                                <button
                                    onClick={handleDownload}
                                    disabled={downloading}
                                    className="inline-flex items-center gap-1 text-xs text-[#2786C2] hover:underline disabled:opacity-50"
                                >
                                    {downloading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                                    ดาวน์โหลด {outputFile}
                                </button>
                                {downloadError && <p className="text-[10px] text-red-600 mt-1">{downloadError}</p>}
                            </div>
                        )}
                        {artifacts.length > 0 && (
                            <div className="space-y-1.5">
                                <span className="text-[9px] uppercase tracking-wide text-[#94A3B8] font-semibold">Files</span>
                                {artifacts.map((artifact: any, artifactIndex: number) => {
                                    const filename = String(artifact?.filename || artifact?.path || "download")
                                        .replace(/\\/g, "/")
                                        .split("/")
                                        .pop() || "download"
                                    const isDownloading = downloadingArtifactIndex === artifactIndex
                                    return (
                                        <button
                                            key={`${artifactIndex}-${filename}`}
                                            type="button"
                                            onClick={() => handleArtifactDownload(artifactIndex, artifact)}
                                            disabled={isDownloading}
                                            title={`ดาวน์โหลด ${filename}`}
                                            className="flex w-full items-center gap-2 rounded-md border border-[#E2E8F0] bg-white px-2 py-1.5 text-left text-xs text-[#2786C2] hover:bg-[#F8F9FA] disabled:opacity-50"
                                        >
                                            {isDownloading ? <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" /> : <Download className="h-3.5 w-3.5 shrink-0" />}
                                            <span className="min-w-0 flex-1 truncate">{filename}</span>
                                            {artifact?.type && <span className="shrink-0 text-[9px] uppercase text-[#94A3B8]">{artifact.type}</span>}
                                        </button>
                                    )
                                })}
                                {downloadError && <p className="text-[10px] text-red-600">{downloadError}</p>}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </>
    )
}

// ── Variable picker (แทรกข้อมูลจากโหนดก่อนหน้า) ──────────────────────
type UpstreamField = { name: string; label: string }
type UpstreamNode = { id: string; label: string; type: string; fields: UpstreamField[]; output?: any }

/** traverse dot-path ใน object (เลียนแบบ backend _lookup_path) */
function lookupPath(obj: any, path: string): any {
    if (obj == null) return undefined
    const parts = path.split(".")
    let cur: any = obj
    for (const part of parts) {
        if (cur == null) return undefined
        if (Array.isArray(cur)) { const idx = parseInt(part, 10); cur = isNaN(idx) ? undefined : cur[idx] }
        else if (typeof cur === "object") { cur = cur[part] }
        else return undefined
    }
    return cur
}

function formatPreview(val: any): string {
    if (val === undefined || val === null) return "(ไม่มีข้อมูลจาก run ล่าสุด)"
    if (typeof val === "string") return val.length > 120 ? `"${val.slice(0, 120)}…"` : `"${val}"`
    if (typeof val === "number" || typeof val === "boolean") return String(val)
    const str = JSON.stringify(val)
    return str.length > 140 ? str.slice(0, 140) + "…" : str
}

/** หา id ของโหนดต้นทางทั้งหมด (ancestors) ของ targetId ด้วย reverse-BFS บน edges */
function getAncestors(targetId: string, edges: Edge[]): string[] {
    const parents: Record<string, string[]> = {}
    edges.forEach((e) => { (parents[e.target] ||= []).push(e.source) })
    const seen = new Set<string>()
    const queue = [...(parents[targetId] || [])]
    while (queue.length) {
        const id = queue.shift()!
        if (seen.has(id)) continue
        seen.add(id)
        queue.push(...(parents[id] || []))
    }
    return [...seen]
}

/** เติมรายชื่อฟิลด์จาก output จริงของการรันล่าสุด (top-level + 2 ระดับลึก) */
function deriveFields(staticFields: UpstreamField[], sample: any): UpstreamField[] {
    const out: UpstreamField[] = [...staticFields]
    const has = (n: string) => out.some((f) => f.name === n)
    const add = (name: string, label: string) => { if (!has(name)) out.push({ name, label }) }
    if (sample && typeof sample === "object" && !Array.isArray(sample)) {
        for (const [k, v] of Object.entries(sample)) {
            add(k, k)
            if (Array.isArray(v) && v[0] && typeof v[0] === "object") {
                for (const [sk, sv] of Object.entries(v[0])) {
                    add(`${k}.0.${sk}`, `${k}[0].${sk}`)
                    // deep expand: ถ้า sv เป็น object ให้เจาะลงอีก 1 ระดับ (เช่น documents.0.data.total_amount)
                    if (sv && typeof sv === "object" && !Array.isArray(sv)) {
                        for (const ssk of Object.keys(sv as object)) {
                            add(`${k}.0.${sk}.${ssk}`, `${k}[0].${sk}.${ssk}`)
                        }
                    }
                }
            } else if (v && typeof v === "object" && !Array.isArray(v)) {
                for (const sk of Object.keys(v as object)) add(`${k}.${sk}`, `${k}.${sk}`)
            }
        }
    }
    return out
}

/** แบน output ของทุกโหนดต้นทางเป็น catalog ตัวแปร (token + label + ตัวอย่าง)
 *  สำหรับส่งให้ AI จัดอันดับ — เจาะลึกกว่า deriveFields เพื่อให้ครอบคลุมทุก field */
function buildAiCandidates(upstream: UpstreamNode[]): VariableCandidate[] {
    const out: VariableCandidate[] = []
    const MAX = 200

    for (const n of upstream) {
        const labelByName = new Map(n.fields.map((f) => [f.name, f.label]))
        // ทั้งโหนด
        out.push({ token: `{{${n.id}}}`, label: `ทั้งโหนด: ${n.label}`, sample: formatPreview(n.output), type: "object" })

        const walk = (obj: any, prefix: string, depth: number) => {
            if (out.length >= MAX || depth > 6) return
            const entries: [string, any][] = Array.isArray(obj)
                ? obj.slice(0, 10).map((v, i) => [String(i), v])
                : Object.entries(obj as object)
            for (const [k, v] of entries) {
                if (out.length >= MAX) return
                const path = prefix ? `${prefix}.${k}` : k
                const ptype = Array.isArray(v) ? "array" : v === null ? "null" : typeof v
                out.push({
                    token: `{{${n.id}.${path}}}`,
                    label: labelByName.get(path) || path.replace(/\.(\d+)\./g, "[$1].").replace(/\.(\d+)$/, "[$1]"),
                    sample: formatPreview(v),
                    type: ptype,
                })
                if (v && typeof v === "object") walk(v, path, depth + 1)
            }
        }

        if (n.output && typeof n.output === "object") {
            walk(n.output, "", 0)
        } else {
            // ยังไม่เคยรัน — ใช้ field schema ที่ทราบล่วงหน้าแทน (ไม่มีตัวอย่าง)
            for (const f of n.fields) {
                if (out.length >= MAX) break
                out.push({ token: `{{${n.id}.${f.name}}}`, label: f.label, sample: "", type: "" })
            }
        }
    }
    return out.slice(0, MAX)
}

const CONFIDENCE_META: Record<string, { stars: string; label: string; cls: string }> = {
    high:   { stars: "★★★", label: "มั่นใจสูง",   cls: "text-emerald-600" },
    medium: { stars: "★★",  label: "พอจะตรง",    cls: "text-amber-600" },
    low:    { stars: "★",   label: "อาจไม่ตรง",  cls: "text-[#94A3B8]" },
}

/** ค้นหาแบบ client-side (fallback เมื่อ LLM ใช้ไม่ได้) — จับ substring ไทย/อังกฤษ บน label/token */
function fuzzyMatch(query: string, candidates: VariableCandidate[]): VariableSuggestion[] {
    const q = query.trim().toLowerCase()
    if (!q) return []
    const terms = q.split(/\s+/).filter(Boolean)
    const scored = candidates.map((c) => {
        const hay = `${c.label || ""} ${c.token} ${c.sample || ""}`.toLowerCase()
        let score = 0
        for (const t of terms) if (hay.includes(t)) score += 1
        return { c, score }
    }).filter((x) => x.score > 0)
    scored.sort((a, b) => b.score - a.score)
    return scored.slice(0, 5).map((x) => ({
        token: x.c.token,
        reason: "ค้นหาแบบข้อความ (AI ไม่พร้อมใช้งานชั่วคราว)",
        confidence: x.score >= terms.length ? "medium" : "low",
    }))
}

/** hovered item rect — ใช้คำนวณตำแหน่ง portal */
type HoveredVar = { nodeId: string; path: string; rect: DOMRect }

function InsertVariableButton({ upstream, onInsert }: { upstream: UpstreamNode[]; onInsert: (token: string) => void }) {
    const [mode, setMode] = useState<null | "manual" | "ai">(null)
    const [expanded, setExpanded] = useState<string | null>(upstream[0]?.id ?? null)
    const [hovered, setHovered] = useState<HoveredVar | null>(null)
    const ref = useRef<HTMLDivElement>(null)
    const aiCtx = useContext(AiFinderContext)

    // ── AI state ──
    const [aiQuery, setAiQuery] = useState("")
    const [aiLoading, setAiLoading] = useState(false)
    const [aiError, setAiError] = useState<string | null>(null)
    const [aiResults, setAiResults] = useState<VariableSuggestion[] | null>(null)
    const aiInputRef = useRef<HTMLInputElement>(null)

    const candidates = useMemo(() => buildAiCandidates(upstream), [upstream])
    const sampleByToken = useMemo(() => new Map(candidates.map((c) => [c.token, c])), [candidates])

    useEffect(() => {
        const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as HTMLElement)) { setMode(null); setHovered(null) } }
        document.addEventListener("mousedown", h)
        return () => document.removeEventListener("mousedown", h)
    }, [])

    useEffect(() => { if (mode === "ai") setTimeout(() => aiInputRef.current?.focus(), 0) }, [mode])

    const hoveredNode = hovered ? upstream.find((n) => n.id === hovered.nodeId) : null
    const hoveredValue = hoveredNode?.output != null
        ? (hovered!.path === "" ? hoveredNode.output : lookupPath(hoveredNode.output, hovered!.path))
        : undefined

    const onEnter = (e: React.MouseEvent<HTMLButtonElement>, nodeId: string, path: string) => {
        setHovered({ nodeId, path, rect: e.currentTarget.getBoundingClientRect() })
    }

    const runAiSearch = async () => {
        const q = aiQuery.trim()
        if (!q || aiLoading) return
        setAiLoading(true); setAiError(null); setAiResults(null)
        try {
            if (!aiCtx?.token || !aiCtx?.workflowId) throw new Error("no-auth")
            const { suggestions } = await suggestVariables(aiCtx.token, aiCtx.workflowId, q, candidates, aiCtx.defaultIntegrationId)
            setAiResults(suggestions)
            if (suggestions.length === 0) {
                const fb = fuzzyMatch(q, candidates)
                if (fb.length) setAiResults(fb)
            }
        } catch (err: any) {
            // LLM ใช้ไม่ได้ → fallback เป็น fuzzy search ฝั่ง client
            const fb = fuzzyMatch(q, candidates)
            if (fb.length) { setAiResults(fb); setAiError("AI ไม่พร้อมใช้งาน — แสดงผลการค้นหาแบบข้อความแทน") }
            else setAiError(err?.message === "no-auth" ? "กรุณาเข้าสู่ระบบใหม่" : (err?.message || "ค้นหาไม่สำเร็จ"))
        } finally {
            setAiLoading(false)
        }
    }

    /** preview: fixed บน document.body — ไม่ถูก overflow clip จาก parent ใดๆ */
    const previewPortal = hovered && typeof document !== "undefined" ? createPortal(
        <div
            style={{
                position: "fixed",
                top: Math.max(8, hovered.rect.top),
                right: window.innerWidth - hovered.rect.left + 8,
                zIndex: 99999,
                width: "224px",
                maxHeight: "320px",
                pointerEvents: "none",
            }}
            className="bg-[#0D1B2A] border border-[#2786C2]/40 rounded-xl shadow-2xl p-2.5 flex flex-col gap-1 overflow-hidden"
        >
            <p className="text-[9px] text-[#94A3B8] uppercase tracking-wide font-semibold shrink-0">ค่าจาก run ล่าสุด</p>
            <code className="text-[10px] text-[#2786C2] font-mono break-all leading-relaxed shrink-0">
                {`{{${hovered.nodeId}${hovered.path ? "." + hovered.path : ""}}}`}
            </code>
            <div className="mt-1 text-[10px] font-mono text-emerald-300 whitespace-pre-wrap break-all leading-relaxed overflow-y-auto">
                {hoveredNode?.output == null
                    ? <span className="text-[#778DA9]">(ยังไม่มีข้อมูล — รัน workflow ก่อนเพื่อดูค่าจริง)</span>
                    : formatPreview(hoveredValue)
                }
            </div>
        </div>,
        document.body
    ) : null

    return (
        <div className="relative" ref={ref}>
            <div className="flex items-center gap-3">
                <button
                    type="button"
                    onClick={() => setMode(mode === "manual" ? null : "manual")}
                    className="flex items-center gap-1 text-[10px] text-[#2786C2] hover:text-[#1F6FA3] font-medium"
                >
                    <Plus className="h-3 w-3" /> แทรกข้อมูลจากโหนดก่อนหน้า
                </button>
                <button
                    type="button"
                    onClick={() => setMode(mode === "ai" ? null : "ai")}
                    className="flex items-center gap-1 text-[10px] font-medium bg-gradient-to-r from-[#7C3AED] to-[#2786C2] bg-clip-text text-transparent hover:opacity-80"
                >
                    <Sparkles className="h-3 w-3 text-[#7C3AED]" /> ค้นหาด้วย AI
                </button>
            </div>

            {/* ── Manual tree ── */}
            {mode === "manual" && (
                <div className="absolute z-30 mt-1">
                    <div className="w-64 max-h-80 overflow-y-auto bg-white border border-[#E2E8F0] rounded-xl shadow-lg p-1.5">
                        {upstream.length === 0 ? (
                            <p className="text-[10px] text-[#94A3B8] px-2 py-2">ยังไม่มีโหนดก่อนหน้า — ลากเส้นเชื่อมจากโหนดอื่นมายังโหนดนี้ก่อน</p>
                        ) : upstream.map((n) => (
                            <div key={n.id}>
                                <button
                                    type="button"
                                    onClick={() => setExpanded(expanded === n.id ? null : n.id)}
                                    className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-lg hover:bg-[#F8F9FA] text-left"
                                >
                                    {expanded === n.id ? <ChevronDown className="h-3 w-3 text-[#94A3B8]" /> : <ChevronRight className="h-3 w-3 text-[#94A3B8]" />}
                                    <span className="text-[11px] font-medium text-[#0D1B2A] flex-1 truncate">{n.label}</span>
                                    <span className="text-[9px] text-[#94A3B8]">{n.id}</span>
                                </button>
                                {expanded === n.id && (
                                    <div className="pl-5 pb-1">
                                        <button
                                            type="button"
                                            onClick={() => { onInsert(`{{${n.id}}}`); setMode(null) }}
                                            onMouseEnter={(e) => onEnter(e, n.id, "")}
                                            onMouseLeave={() => setHovered(null)}
                                            className="block w-full text-left px-2 py-1 rounded text-[10px] text-[#778DA9] hover:bg-[#EBF4FB] hover:text-[#2786C2] italic"
                                        >
                                            ทั้งโหนด ({"{{"}{n.id}{"}}"})
                                        </button>
                                        {n.fields.map((f) => (
                                            <button
                                                key={f.name}
                                                type="button"
                                                onClick={() => { onInsert(`{{${n.id}.${f.name}}}`); setMode(null) }}
                                                onMouseEnter={(e) => onEnter(e, n.id, f.name)}
                                                onMouseLeave={() => setHovered(null)}
                                                className="block w-full text-left px-2 py-1 rounded text-[10px] text-[#0D1B2A] hover:bg-[#EBF4FB] hover:text-[#2786C2]"
                                            >
                                                {f.label} <span className="text-[#94A3B8]">· {f.name}</span>
                                            </button>
                                        ))}
                                        {n.fields.length === 0 && (
                                            <p className="px-2 py-1 text-[9px] text-[#94A3B8]">ไม่มีฟิลด์ที่ทราบล่วงหน้า — ลองรันโหนดนี้ก่อนเพื่อดูฟิลด์จริง</p>
                                        )}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* ── AI search ── */}
            {mode === "ai" && (
                <div className="absolute z-30 mt-1">
                    <div className="w-80 max-h-96 overflow-y-auto bg-white border border-[#7C3AED]/30 rounded-xl shadow-xl p-2.5">
                        <p className="text-[10px] text-[#64748B] mb-1.5 flex items-center gap-1">
                            <Sparkles className="h-3 w-3 text-[#7C3AED]" /> พิมพ์ข้อมูลที่ต้องการเป็นภาษาธรรมชาติ
                        </p>
                        <div className="flex gap-1.5">
                            <input
                                ref={aiInputRef}
                                value={aiQuery}
                                onChange={(e) => setAiQuery(e.target.value)}
                                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); runAiSearch() } }}
                                placeholder="เช่น เลขที่ใบแจ้งหนี้, ยอดรวมทั้งหมด"
                                className="flex-1 border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#7C3AED]/30"
                            />
                            <button
                                type="button"
                                onClick={runAiSearch}
                                disabled={aiLoading || !aiQuery.trim()}
                                className="px-3 rounded-lg text-xs bg-[#7C3AED] text-white hover:bg-[#6D28D9] disabled:opacity-40 flex items-center"
                            >
                                {aiLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "ค้นหา"}
                            </button>
                        </div>

                        {candidates.length === 0 && (
                            <p className="text-[10px] text-amber-600 mt-2">ยังไม่มีโหนดก่อนหน้า — เชื่อมโหนดและรัน workflow ก่อนเพื่อให้ AI รู้จักตัวแปร</p>
                        )}
                        {aiError && <p className="text-[10px] text-amber-600 mt-2">{aiError}</p>}

                        {aiResults && (
                            <div className="mt-2 space-y-1.5">
                                {aiResults.length === 0 ? (
                                    <p className="text-[10px] text-[#94A3B8]">ไม่พบตัวแปรที่ตรง — ลองอธิบายใหม่ หรือใช้เมนูแทรกแบบเลือกเอง</p>
                                ) : aiResults.map((s) => {
                                    const cand = sampleByToken.get(s.token)
                                    const meta = CONFIDENCE_META[s.confidence] || CONFIDENCE_META.medium
                                    return (
                                        <div key={s.token} className="border border-[#E2E8F0] rounded-lg p-2 hover:border-[#7C3AED]/40">
                                            <div className="flex items-center gap-1.5 mb-0.5">
                                                <span className="text-[11px] font-medium text-[#0D1B2A] flex-1 truncate">{cand?.label || s.token}</span>
                                                <span className={`text-[9px] font-semibold ${meta.cls}`} title={meta.label}>{meta.stars}</span>
                                            </div>
                                            <code className="block text-[9px] text-[#2786C2] font-mono break-all">{s.token}</code>
                                            {cand?.sample && (
                                                <p className="text-[9px] text-emerald-600 font-mono mt-0.5 break-all line-clamp-2">ตัวอย่าง: {cand.sample}</p>
                                            )}
                                            {s.reason && <p className="text-[9px] text-[#94A3B8] mt-0.5">↳ {s.reason}</p>}
                                            <button
                                                type="button"
                                                onClick={() => { onInsert(s.token); setMode(null) }}
                                                className="mt-1.5 w-full text-[10px] py-1 rounded-lg bg-[#EBF4FB] text-[#2786C2] hover:bg-[#7C3AED] hover:text-white font-medium transition-colors"
                                            >
                                                แทรกตัวแปรนี้
                                            </button>
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </div>
                </div>
            )}
            {previewPortal}
        </div>
    )
}

// ── Config panel field renderer ──────────────────────────────────────
function ConfigField({
    field, value, onChange, jobs, schemas, upstream, integrations, aiProviders, agentSkills,
    agentSkillsLoading, agentSkillsError, onRetryAgentSkills,
}: { field: NodeTypeDef["config_fields"][0]; value: any; onChange: (v: any) => void; jobs: JobSummary[]; schemas: SchemaSummary[]; upstream: UpstreamNode[]; integrations: Integration[]; aiProviders: AIProviderSetting[]; agentSkills: WorkflowAgentSkill[]; agentSkillsLoading: boolean; agentSkillsError: string | null; onRetryAgentSkills: () => void }) {
    const base = "w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30"
    const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null)
    const supportsTemplate = ["text", "textarea", "code"].includes(field.type)

    if (field.type === "segmented") {
        return (
            <div className="grid grid-cols-2 gap-1 rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] p-1" role="radiogroup" aria-label={field.label}>
                {(field.options || []).map((option) => {
                    const active = (value ?? field.default) === option
                    return (
                        <button
                            key={option}
                            type="button"
                            role="radio"
                            aria-checked={active}
                            onClick={() => onChange(option)}
                            className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${active ? "bg-white text-[#2786C2] shadow-sm" : "text-[#64748B] hover:text-[#0D1B2A]"}`}
                        >
                            {field.option_labels?.[option] || option}
                        </button>
                    )
                })}
            </div>
        )
    }

    if (field.type === "skill_multi_select") {
        const selected = new Set(Array.isArray(value) ? value : [])
        if (agentSkillsLoading) {
            return <p className="rounded-lg border border-[#E2E8F0] px-3 py-2 text-[10px] text-[#64748B]">กำลังโหลด Skills...</p>
        }
        if (agentSkillsError) {
            return (
                <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[10px] text-red-600">
                    <p>โหลด Skills ไม่สำเร็จ</p>
                    <button type="button" onClick={onRetryAgentSkills} className="mt-1 font-semibold underline">ลองใหม่</button>
                </div>
            )
        }
        return (
            <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-[#E2E8F0] bg-white p-1.5">
                {agentSkills.map((skill) => (
                    <label key={skill.id} className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-2 hover:bg-[#F8FAFC]">
                        <input
                            type="checkbox"
                            className="mt-0.5"
                            checked={selected.has(skill.id)}
                            onChange={(event) => {
                                const next = new Set(selected)
                                if (event.target.checked) next.add(skill.id)
                                else next.delete(skill.id)
                                onChange(Array.from(next))
                            }}
                        />
                        <span className="min-w-0">
                            <span className="block text-xs font-semibold text-[#0D1B2A]">{skill.name}</span>
                            <span className="mt-0.5 block text-[10px] leading-snug text-[#64748B] line-clamp-2">{skill.description}</span>
                        </span>
                    </label>
                ))}
                {agentSkills.length === 0 && <p className="px-2 py-3 text-[10px] text-amber-600">ยังไม่มี Skill ที่ใช้งานได้</p>}
            </div>
        )
    }

    /** แทรก token ที่ตำแหน่ง caret ของช่องนี้ */
    const insertToken = (token: string) => {
        const el = inputRef.current
        const cur = typeof value === "string" ? value : ""
        if (el && typeof el.selectionStart === "number") {
            const start = el.selectionStart, end = el.selectionEnd ?? start
            onChange(cur.slice(0, start) + token + cur.slice(end))
            requestAnimationFrame(() => {
                el.focus()
                const pos = start + token.length
                el.setSelectionRange(pos, pos)
            })
        } else {
            onChange(cur + token)
        }
    }
    if (field.type === "ai_provider_select") {
        const activeProviders = aiProviders.filter((p) => p.is_active)
        const known = activeProviders.some((p) => p.id === value)
        return (
            <div>
                <select className={base} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
                    <option value="">ใช้ Agent Provider กลางของระบบ</option>
                    {activeProviders.map((p) => {
                        const badges = [p.is_agent_provider ? "Agent" : null, p.is_default ? "Default" : null, p.provider_type].filter(Boolean).join(" · ")
                        return (
                            <option key={p.id} value={p.id}>
                                {p.display_name || p.name}{badges ? ` · ${badges}` : ""}
                            </option>
                        )
                    })}
                    {value && !known && <option value={value}>{`${value} (ไม่พบในรายการ)`}</option>}
                </select>
                {activeProviders.length === 0 && (
                    <p className="text-[10px] text-amber-600 mt-1">
                        ยังไม่มี AI provider — ไปตั้งค่าที่ <a href="/settings" className="underline">Setting AI</a> ก่อน
                    </p>
                )}
            </div>
        )
    }
    if (field.type === "integration_select") {
        const allMatches = integrations.filter((i) => !field.provider || i.type === field.provider)
        const matches = allMatches.filter((i) => i.status === "active")
        const selected = allMatches.find((i) => i.id === value)
        const known = matches.some((i) => i.id === value)
        return (
            <div>
                <select className={base} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
                    <option value="">— เลือกบัญชี —</option>
                    {matches.map((i) => (
                        <option key={i.id} value={i.id}>{i.name}{i.status === "paused" ? " (paused)" : ""}</option>
                    ))}
                    {selected && selected.status !== "active" && (
                        <option value={selected.id}>{`${selected.name} (paused — ใช้งานไม่ได้)`}</option>
                    )}
                    {value && !known && !selected && <option value={value}>{`${value} (ไม่พบในรายการ)`}</option>}
                </select>
                {matches.length === 0 && (
                    <p className="text-[10px] text-amber-600 mt-1">
                        ยังไม่มีบัญชีชนิดนี้ที่พร้อมใช้งาน — ไปตรวจสอบที่ <a href="/integrations" className="underline">เมนู Integration</a>
                    </p>
                )}
                {selected && selected.status !== "active" && (
                    <p className="text-[10px] text-amber-600 mt-1">บัญชีนี้ถูกพักไว้ ต้องเปิดใช้งานก่อนจึงจะรัน workflow ได้</p>
                )}
            </div>
        )
    }
    if (field.type === "job_select") {
        const known = jobs.some((j) => j.id === value)
        return (
            <select className={base} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
                <option value="">— เลือก Job —</option>
                {jobs.map((j) => (
                    <option key={j.id} value={j.id}>{(j.name || "(ไม่มีชื่อ)") + ` · ${j.status}`}</option>
                ))}
                {value && !known && <option value={value}>{`${value} (ไม่พบในรายการ)`}</option>}
            </select>
        )
    }
    if (field.type === "schema_select") {
        const normalizedValue = (!value || value === "auto") ? "" : value
        const known = !normalizedValue || schemas.some((s) => s.id === normalizedValue)
        return (
            <select
                className={base}
                value={normalizedValue}
                onChange={(e) => onChange(e.target.value ? e.target.value : null)}
            >
                <option value="">Auto (default)</option>
                {schemas.map((s) => (
                    <option key={s.id} value={s.id}>
                        {s.name}{s.document_type ? ` · ${s.document_type}` : ""}
                    </option>
                ))}
                {normalizedValue && !known && <option value={normalizedValue}>{`${normalizedValue} (ไม่พบในรายการ)`}</option>}
            </select>
        )
    }
    if (field.type === "boolean") {
        return (
            <label className="flex items-center gap-2 text-xs text-[#0D1B2A]">
                <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
                {field.label}
            </label>
        )
    }
    if (field.type === "select") {
        return (
            <select className={base} value={value ?? field.default ?? ""} onChange={(e) => onChange(e.target.value)}>
                {(field.options || []).map((o) => <option key={o} value={o}>{field.option_labels?.[o] || o || "(any)"}</option>)}
            </select>
        )
    }
    if (field.type === "textarea" || field.type === "code") {
        return (
            <div>
                {supportsTemplate && field.type !== "code" && (
                    <div className="mb-1"><InsertVariableButton upstream={upstream} onInsert={insertToken} /></div>
                )}
                <textarea
                    ref={(el) => { inputRef.current = el }}
                    className={`${base} ${field.type === "code" ? "font-mono" : ""}`}
                    rows={field.type === "code" ? 8 : 4}
                    value={value ?? ""}
                    placeholder={field.placeholder ?? (field.type === "code" ? "# set `result` variable\nresult = inputs" : undefined)}
                    onChange={(e) => onChange(e.target.value)}
                />
            </div>
        )
    }
    if (field.type === "mappings") {
        return <MappingsField value={value} onChange={onChange} base={base} upstream={upstream} />
    }
    return (
        <div>
            {supportsTemplate && (
                <div className="mb-1"><InsertVariableButton upstream={upstream} onInsert={insertToken} /></div>
            )}
            <input
                ref={(el) => { inputRef.current = el }}
                type={field.type === "number" ? "number" : "text"}
                className={base}
                placeholder={field.placeholder}
                value={value ?? field.default ?? ""}
                onChange={(e) => onChange(field.type === "number" ? Number(e.target.value) : e.target.value)}
            />
        </div>
    )
}

/** mappings field — แต่ละแถวมีช่อง target + value(template) + ปุ่มแทรกข้อมูล */
function MappingsField({
    value, onChange, base, upstream,
}: { value: any; onChange: (v: any) => void; base: string; upstream: UpstreamNode[] }) {
    const rows: { target: string; value: string }[] = Array.isArray(value) ? value : []
    const valueRefs = useRef<(HTMLInputElement | null)[]>([])
    const update = (i: number, key: "target" | "value", v: string) => {
        onChange(rows.map((r, idx) => (idx === i ? { ...r, [key]: v } : r)))
    }
    const insertAt = (i: number, token: string) => {
        const el = valueRefs.current[i]
        const cur = rows[i]?.value || ""
        if (el && typeof el.selectionStart === "number") {
            const start = el.selectionStart, end = el.selectionEnd ?? start
            update(i, "value", cur.slice(0, start) + token + cur.slice(end))
            requestAnimationFrame(() => { el.focus(); const p = start + token.length; el.setSelectionRange(p, p) })
        } else {
            update(i, "value", cur + token)
        }
    }
    return (
        <div className="space-y-2">
            {rows.map((r, i) => (
                <div key={i} className="border border-[#E2E8F0] rounded-lg p-1.5 space-y-1">
                    <div className="flex gap-1.5 items-center">
                        <input className={`${base} flex-[2]`} placeholder="ชื่อฟิลด์ใหม่" value={r.target || ""} onChange={(e) => update(i, "target", e.target.value)} />
                        <span className="text-[#94A3B8] text-xs">=</span>
                        <button onClick={() => onChange(rows.filter((_, idx) => idx !== i))} className="text-red-400 hover:text-red-600" title="ลบ">
                            <X className="h-3.5 w-3.5" />
                        </button>
                    </div>
                    <InsertVariableButton upstream={upstream} onInsert={(t) => insertAt(i, t)} />
                    <input
                        ref={(el) => { valueRefs.current[i] = el }}
                        className={base}
                        placeholder="ค่า เช่น {{jobs_1.count}} หรือข้อความคงที่"
                        value={r.value || ""}
                        onChange={(e) => update(i, "value", e.target.value)}
                    />
                </div>
            ))}
            <button onClick={() => onChange([...rows, { target: "", value: "" }])} className="text-xs text-[#2786C2] hover:underline">
                + เพิ่ม mapping
            </button>
        </div>
    )
}

function ScheduleTriggerSettings({
    config,
    onChange,
}: {
    config: Record<string, any>
    onChange: (patch: Record<string, any>) => void
}) {
    const cfg = { ...defaultScheduleConfig(), ...(config || {}) }
    const preset = cfg.schedule_preset || "daily"
    const minute = parseTime(cfg.schedule_time).minute
    const cronPreview = buildCronFromScheduleConfig(cfg)
    const base = "w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30"

    return (
        <div className="mb-4 rounded-lg border border-[#E2E8F0] bg-[#F8F9FA] p-3 space-y-3">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <p className="text-xs font-semibold text-[#0D1B2A] flex items-center gap-1.5">
                        <CalendarClock className="h-3.5 w-3.5 text-[#D97706]" /> ตั้งเวลารันอัตโนมัติ
                    </p>
                    <p className="text-[10px] text-[#778DA9] mt-0.5 leading-snug">
                        เมื่อเปิดใช้งาน workflow นี้จะรันเองตามเวลาที่เลือก โดยไม่ต้องเปิดหน้าเว็บค้างไว้
                    </p>
                </div>
                <label className="flex items-center gap-1.5 text-xs text-[#0D1B2A] shrink-0">
                    <input
                        type="checkbox"
                        checked={!!cfg.schedule_enabled}
                        onChange={(e) => onChange({ schedule_enabled: e.target.checked })}
                    />
                    เปิด
                </label>
            </div>

            <div>
                <label className="block text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold mb-1">
                    ความถี่
                </label>
                <select
                    className={base}
                    value={preset}
                    onChange={(e) => onChange({
                        schedule_preset: e.target.value,
                        custom_cron: e.target.value === "custom" ? cfg.custom_cron || cronPreview : cfg.custom_cron,
                    })}
                >
                    {SCHEDULE_PRESETS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                </select>
            </div>

            {["daily", "weekdays", "weekly", "monthly"].includes(preset) && (
                <div>
                    <label className="block text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold mb-1">
                        เวลา
                    </label>
                    <input
                        type="time"
                        className={base}
                        value={cfg.schedule_time || "09:00"}
                        onChange={(e) => onChange({ schedule_time: e.target.value })}
                    />
                </div>
            )}

            {preset === "hourly" && (
                <div>
                    <label className="block text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold mb-1">
                        รันที่นาทีที่
                    </label>
                    <input
                        type="number"
                        min={0}
                        max={59}
                        className={base}
                        value={minute}
                        onChange={(e) => {
                            const nextMinute = Math.min(59, Math.max(0, Number(e.target.value || 0)))
                            onChange({ schedule_time: `00:${String(nextMinute).padStart(2, "0")}` })
                        }}
                    />
                </div>
            )}

            {preset === "weekly" && (
                <div>
                    <label className="block text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold mb-1">
                        วันในสัปดาห์
                    </label>
                    <select
                        className={base}
                        value={cfg.schedule_weekday || "1"}
                        onChange={(e) => onChange({ schedule_weekday: e.target.value })}
                    >
                        {WEEKDAY_OPTIONS.map((day) => <option key={day.value} value={day.value}>{day.label}</option>)}
                    </select>
                </div>
            )}

            {preset === "monthly" && (
                <div>
                    <label className="block text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold mb-1">
                        วันที่ของเดือน
                    </label>
                    <input
                        type="number"
                        min={1}
                        max={31}
                        className={base}
                        value={cfg.schedule_day || 1}
                        onChange={(e) => onChange({ schedule_day: Math.min(31, Math.max(1, Number(e.target.value || 1))) })}
                    />
                </div>
            )}

            {preset === "custom" && (
                <div>
                    <label className="block text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold mb-1">
                        Cron ขั้นสูง
                    </label>
                    <input
                        className={`${base} font-mono`}
                        value={cfg.custom_cron || ""}
                        placeholder="*/15 * * * *"
                        onChange={(e) => onChange({ custom_cron: e.target.value })}
                    />
                </div>
            )}

            <div className="rounded-md bg-white border border-[#E2E8F0] px-2.5 py-2">
                <p className="text-[10px] text-[#94A3B8]">สรุปการตั้งค่า</p>
                <p className="text-[11px] text-[#0D1B2A]">{summarizeSchedule(cfg)}</p>
                {preset === "custom" && (
                    <code className="block mt-1 text-[10px] text-[#94A3B8]">{cronPreview || "ยังไม่ได้ตั้งค่า"}</code>
                )}
            </div>
        </div>
    )
}

// ── Main builder ─────────────────────────────────────────────────────
function Builder() {
    const params = useParams()
    const searchParams = useSearchParams()
    const workflowId = params.id as string
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null
    const { screenToFlowPosition } = useReactFlow()

    const [workflow, setWorkflow] = useState<Workflow | null>(null)
    const [nodeDefs, setNodeDefs] = useState<NodeTypeDef[]>([])
    const [jobs, setJobs] = useState<JobSummary[]>([])
    const [schemas, setSchemas] = useState<SchemaSummary[]>([])
    const [integrations, setIntegrations] = useState<Integration[]>([])
    const [aiProviders, setAiProviders] = useState<AIProviderSetting[]>([])
    const [agentSkills, setAgentSkills] = useState<WorkflowAgentSkill[]>([])
    const [agentSkillsLoading, setAgentSkillsLoading] = useState(false)
    const [agentSkillsError, setAgentSkillsError] = useState<string | null>(null)
    const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
    const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [saving, setSaving] = useState(false)
    const [dirty, setDirty] = useState(false)
    const [notice, setNotice] = useState<string | null>(null)

    // runs / activity
    const [activeRun, setActiveRun] = useState<WorkflowRun | null>(null)
    const [runPanelOpen, setRunPanelOpen] = useState(false)
    const [runHistory, setRunHistory] = useState<WorkflowRun[]>([])
    const [showRunModal, setShowRunModal] = useState(false)
    const [runInput, setRunInput] = useState("")
    const [starting, setStarting] = useState(false)
    const [testing, setTesting] = useState(false)
    const [helpOpen, setHelpOpen] = useState(false)
    const [webhookUrl, setWebhookUrl] = useState<string | null>(null)
    const [webhookBusy, setWebhookBusy] = useState(false)
    // output จริงของแต่ละโหนดจากการรันเต็มล่าสุด — ใช้เติมฟิลด์ใน variable picker
    const [nodeOutputs, setNodeOutputs] = useState<Record<string, any>>({})
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

    const loadAgentSkills = useCallback(async () => {
        if (!token) return
        setAgentSkillsLoading(true)
        setAgentSkillsError(null)
        try {
            setAgentSkills(await getWorkflowAgentSkills(token))
        } catch (error: any) {
            setAgentSkills([])
            setAgentSkillsError(error?.message || "Unable to load Skills")
        } finally {
            setAgentSkillsLoading(false)
        }
    }, [token])

    // ── Load workflow + node catalog ──
    useEffect(() => {
        if (!token) return
        Promise.all([getWorkflow(token, workflowId), getNodeTypes(token)])
            .then(([wf, nt]) => {
                setWorkflow(wf)
                setNodeDefs(nt.node_types)
                setNodes(toFlowNodes(wf, nt.node_types))
                setEdges(toFlowEdges(wf))
                const runId = searchParams.get("run")
                if (runId) watchRun(runId)
            })
            .catch((e) => setNotice(e.message))
        getJobs(token).then(setJobs).catch(() => { /* picker falls back to manual id */ })
        getSchemas(token).then(setSchemas).catch(() => { /* select shows the fallback option */ })
        getActiveIntegrations(token).then(setIntegrations).catch(() => { /* select shows empty hint */ })
        listAIProviders(token).then(setAiProviders).catch(() => { /* select shows empty hint */ })
        loadAgentSkills()
        loadLatestOutputs()
        return () => { if (pollRef.current) clearInterval(pollRef.current) }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token, workflowId, loadAgentSkills])

    // ── Run polling ──
    const applyRunToCanvas = useCallback((run: WorkflowRun | null) => {
        setNodes((nds) => nds.map((n) => {
            const nr = run?.node_runs?.find((r) => r.node_id === n.id)
            return { ...n, data: { ...n.data, runStatus: nr?.status } }
        }))
    }, [setNodes])

    // เก็บ output จริงของแต่ละโหนดไว้เติม variable picker (เฉพาะ run เต็ม ไม่ใช่ node_test)
    const captureOutputs = useCallback((run: WorkflowRun) => {
        if (run.trigger_type === "node_test") return
        setNodeOutputs((prev) => {
            const next = { ...prev }
            for (const nr of run.node_runs || []) {
                if (nr.output != null) next[nr.node_id] = nr.output
            }
            return next
        })
    }, [])

    // โหลด output จากการรันเต็มล่าสุดตอนเปิดหน้า (ให้ picker มีฟิลด์จริงทันที)
    const loadLatestOutputs = useCallback(async () => {
        if (!token) return
        try {
            const { runs } = await getWorkflowRuns(token, workflowId, 10)
            const latest = runs.find((r) => r.trigger_type !== "node_test")
            if (latest) captureOutputs(await getRun(token, latest.id))
        } catch { /* ignore */ }
    }, [token, workflowId, captureOutputs])

    const watchRun = useCallback((runId: string) => {
        if (!token) return
        setRunPanelOpen(true)
        if (pollRef.current) clearInterval(pollRef.current)
        const tick = async () => {
            try {
                const run = await getRun(token, runId)
                setActiveRun(run)
                applyRunToCanvas(run)
                captureOutputs(run)
                if (["succeeded", "failed", "cancelled"].includes(run.status) && pollRef.current) {
                    clearInterval(pollRef.current)
                    pollRef.current = null
                }
            } catch { /* transient poll errors are fine */ }
        }
        tick()
        pollRef.current = setInterval(tick, 1500)
    }, [token, applyRunToCanvas])

    // ── DnD from palette ──
    const onDragStart = (e: React.DragEvent, type: string) => {
        e.dataTransfer.setData("application/wf-node", type)
        e.dataTransfer.effectAllowed = "move"
    }

    const onDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault()
        const type = e.dataTransfer.getData("application/wf-node")
        const def = nodeDefs.find((d) => d.type === type)
        if (!def) return
        if (type === "trigger_schedule" && nodes.some((n) => (n.data as WfNodeData).nodeType === "trigger_schedule")) {
            const existing = nodes.find((n) => (n.data as WfNodeData).nodeType === "trigger_schedule")
            if (existing) setSelectedId(existing.id)
            setNotice("หนึ่ง workflow ตั้ง Schedule Trigger ได้เพียง 1 โหนด")
            return
        }
        const position = screenToFlowPosition({ x: e.clientX, y: e.clientY })
        const config: Record<string, any> = {}
        def.config_fields.forEach((f) => { if (f.default !== undefined) config[f.name] = f.default })
        if (type === "trigger_schedule") Object.assign(config, defaultScheduleConfig())
        const id = `${type}_${Date.now().toString(36)}`
        setNodes((nds) => [...nds, {
            id, type: "wf", position,
            data: { nodeType: type, label: def.label, config, category: def.category },
        }])
        setSelectedId(id)
        setDirty(true)
    }, [nodeDefs, screenToFlowPosition, setNodes])

    const onConnect = useCallback((conn: Connection) => {
        setEdges((eds) => addEdge({
            ...conn,
            label: conn.sourceHandle === "true" ? "True" : conn.sourceHandle === "false" ? "False" : undefined,
            markerEnd: { type: MarkerType.ArrowClosed },
            style: { strokeWidth: 1.5 },
        }, eds))
        setDirty(true)
    }, [setEdges])

    const scheduleNode = nodes.find((n) => (n.data as WfNodeData).nodeType === "trigger_schedule") || null
    const scheduleConfig = scheduleNode ? ((scheduleNode.data as WfNodeData).config || {}) : null
    const scheduleCron = scheduleConfig ? buildCronFromScheduleConfig(scheduleConfig) : ""
    const scheduleIsEnabled = !!scheduleNode && !!scheduleConfig?.schedule_enabled && !!scheduleCron.trim()

    // ── Save ──
    const handleSave = async (): Promise<boolean> => {
        if (!token || !workflow) return false
        if (scheduleConfig?.schedule_enabled && !scheduleCron.trim()) {
            setNotice("กรุณาตั้งค่า Schedule ให้ครบ หรือปิดใช้งาน schedule ก่อน Save")
            return false
        }
        try {
            setSaving(true)
            const updated = await updateWorkflow(token, workflowId, {
                name: workflow.name,
                description: workflow.description,
                definition: toDefinition(nodes, edges),
                schedule_cron: scheduleIsEnabled ? scheduleCron : null,
                schedule_enabled: scheduleIsEnabled,
            })
            setWorkflow(updated)
            setDirty(false)
            setNotice(null)
            return true
        } catch (e: any) {
            setNotice(`Save failed: ${e.message}`)
            return false
        } finally {
            setSaving(false)
        }
    }

    // ── Run ──
    const handleRun = async () => {
        if (!token) return
        let input: Record<string, any> = {}
        if (runInput.trim()) {
            try { input = JSON.parse(runInput) } catch { setNotice("Trigger input ต้องเป็น JSON ที่ถูกต้อง"); return }
        }
        try {
            setStarting(true)
            if (dirty && !(await handleSave())) return
            const run = await runWorkflow(token, workflowId, input)
            setShowRunModal(false)
            watchRun(run.id)
        } catch (e: any) {
            setNotice(`Run failed: ${e.message}`)
        } finally {
            setStarting(false)
        }
    }

    const loadHistory = async () => {
        if (!token) return
        try {
            const data = await getWorkflowRuns(token, workflowId)
            setRunHistory(data.runs as unknown as WorkflowRun[])
        } catch { /* ignore */ }
    }

    // ── Selection / deletion ──
    const selectedNode = nodes.find((n) => n.id === selectedId) || null
    const selectedDef = selectedNode ? nodeDefs.find((d) => d.type === (selectedNode.data as WfNodeData).nodeType) : null
    const selectedNodeType = selectedNode ? (selectedNode.data as WfNodeData).nodeType : null
    const selectedConfig = selectedNode ? (selectedNode.data as WfNodeData).config || {} : {}
    const visibleConfigFields = selectedDef?.config_fields.filter((field) => {
        if (!field.visible_when) return true
        const actual = selectedConfig[field.visible_when.field] ?? (
            field.visible_when.field === "mode" ? "llm" : undefined
        )
        return actual === field.visible_when.equals
    }) || []
    const primaryConfigFields = visibleConfigFields.filter((field) => !field.advanced)
    const advancedConfigFields = visibleConfigFields.filter((field) => field.advanced)
    const selectedHelp = selectedNodeType
        ? NODE_HELP_CONTENT[selectedNodeType] || {
            purpose: selectedDef?.description || "ตั้งค่าข้อมูลของ node นี้แล้วส่งต่อให้ node ถัดไป",
            steps: ["กรอกฟิลด์ที่มีเครื่องหมาย * ให้ครบ", "เชื่อมต่อ node กับขั้นตอนถัดไป แล้วทดสอบก่อนใช้งานจริง"],
            example: "ตัวอย่าง: ตั้งค่าฟิลด์ที่จำเป็น แล้วเชื่อมต่อกับ node ถัดไปบน canvas",
        }
        : null

    useEffect(() => {
        setHelpOpen(false)
    }, [selectedId])

    const updateSelectedConfig = (name: string, value: any) => {
        setNodes((nds) => nds.map((n) => n.id === selectedId
            ? { ...n, data: { ...n.data, config: { ...(n.data as WfNodeData).config, [name]: value } } }
            : n))
        setDirty(true)
    }

    const updateSelectedConfigPatch = (patch: Record<string, any>) => {
        setNodes((nds) => nds.map((n) => n.id === selectedId
            ? { ...n, data: { ...n.data, config: { ...(n.data as WfNodeData).config, ...patch } } }
            : n))
        setDirty(true)
    }

    const updateSelectedLabel = (label: string) => {
        setNodes((nds) => nds.map((n) => n.id === selectedId ? { ...n, data: { ...n.data, label } } : n))
        setDirty(true)
    }

    const deleteSelected = () => {
        if (!selectedId) return
        setNodes((nds) => nds.filter((n) => n.id !== selectedId))
        setEdges((eds) => eds.filter((e) => e.source !== selectedId && e.target !== selectedId))
        setSelectedId(null)
        setDirty(true)
    }

    // รายชื่อโหนดต้นทาง + ฟิลด์ ที่ใช้ใน variable picker ของโหนดที่เลือก
    const upstreamVars: UpstreamNode[] = useMemo(() => {
        if (!selectedId) return []
        const ancestorIds = getAncestors(selectedId, edges)
        return ancestorIds.map((id) => {
            const node = nodes.find((n) => n.id === id)
            const nodeType = node ? (node.data as WfNodeData).nodeType : "unknown"
            const def = nodeDefs.find((d) => d.type === nodeType)
            let staticFields: UpstreamField[] = (def?.output_fields || []).map((f) => ({ name: f.name, label: f.label }))
            // transform: ฟิลด์มาจาก target ที่ผู้ใช้กำหนดเอง
            if (nodeType === "transform") {
                const maps = (node?.data as WfNodeData)?.config?.mappings || []
                staticFields = maps.filter((m: any) => m?.target).map((m: any) => ({ name: m.target, label: m.target }))
            }
            const fields = deriveFields(staticFields, nodeOutputs[id])
            return {
                id,
                label: node ? (node.data as WfNodeData).label : id,
                type: nodeType,
                fields,
                output: nodeOutputs[id],
            }
        })
    }, [selectedId, edges, nodes, nodeDefs, nodeOutputs])

    // ── ทดสอบโหนดเดียว ──
    const handleTestNode = async () => {
        if (!token || !selectedId) return
        try {
            setTesting(true)
            if (dirty) await handleSave()
            const run = await testNode(token, workflowId, selectedId)
            watchRun(run.id)
        } catch (e: any) {
            setNotice(`ทดสอบโหนดล้มเหลว: ${e.message}`)
        } finally {
            setTesting(false)
        }
    }

    const handleRotateWebhookSecret = async () => {
        if (!token || !workflow) return
        try {
            setWebhookBusy(true)
            if (dirty && !(await handleSave())) return
            const data = await rotateWorkflowWebhookSecret(token, workflowId)
            setWebhookUrl(data.webhook_url)
            setWorkflow((prev) => prev ? {
                ...prev,
                webhook_enabled: true,
                webhook_secret_created_at: data.secret_created_at,
            } : prev)
            try { await navigator.clipboard.writeText(data.webhook_url) } catch { /* copy is best-effort */ }
            setNotice("สร้าง Webhook URL แล้ว และคัดลอกไปยัง clipboard แล้ว")
        } catch (e: any) {
            setNotice(`สร้าง Webhook URL ไม่สำเร็จ: ${e.message}`)
        } finally {
            setWebhookBusy(false)
        }
    }

    const handleDisableWebhookSecret = async () => {
        if (!token || !workflow) return
        if (!confirm("ปิด Webhook URL นี้? External apps ที่ใช้อยู่จะเรียก workflow ไม่ได้จนกว่าจะ generate ใหม่")) return
        try {
            setWebhookBusy(true)
            await disableWorkflowWebhookSecret(token, workflowId)
            setWebhookUrl(null)
            setWorkflow((prev) => prev ? {
                ...prev,
                webhook_enabled: false,
                webhook_secret_created_at: null,
            } : prev)
            setNotice("ปิด Webhook URL แล้ว")
        } catch (e: any) {
            setNotice(`ปิด Webhook URL ไม่สำเร็จ: ${e.message}`)
        } finally {
            setWebhookBusy(false)
        }
    }

    const grouped = useMemo(() => {
        const groups: Record<string, NodeTypeDef[]> = {}
        nodeDefs.forEach((d) => { (groups[d.category] ||= []).push(d) })
        return groups
    }, [nodeDefs])

    if (!workflow) {
        return (
            <div className="flex items-center justify-center h-full text-[#778DA9]">
                <Loader2 className="h-6 w-6 animate-spin mr-2" /> Loading workflow…
            </div>
        )
    }

    return (
        <AiFinderContext.Provider value={{ workflowId, token, defaultIntegrationId: null }}>
        <div className="flex flex-col h-full">
            {/* ── Top bar ── */}
            <div className="flex items-center gap-3 px-4 py-2.5 bg-white border-b border-[#E2E8F0]">
                <Link href="/workflows" className="p-1.5 rounded-lg hover:bg-[#F8F9FA] text-[#778DA9]">
                    <ArrowLeft className="h-4 w-4" />
                </Link>
                <input
                    className="font-semibold text-[#0D1B2A] text-sm bg-transparent focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30 rounded px-2 py-1 min-w-0 flex-1 max-w-xs"
                    value={workflow.name}
                    onChange={(e) => { setWorkflow({ ...workflow, name: e.target.value }); setDirty(true) }}
                />
                {dirty && <span className="text-[10px] text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">unsaved</span>}

                <div className="flex-1" />

                <button
                    onClick={() => {
                        if (scheduleNode) setSelectedId(scheduleNode.id)
                    }}
                    disabled={!scheduleNode}
                    title={scheduleNode ? "เลือก Schedule Trigger เพื่อตั้งเวลา" : "ลาก Schedule Trigger ลง canvas ก่อนจึงจะตั้งเวลาได้"}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                        scheduleNode
                            ? scheduleIsEnabled
                                ? "border-[#2786C2] text-[#2786C2] bg-[#EBF4FB] hover:bg-[#DCECF8]"
                                : "border-[#E2E8F0] text-[#778DA9] hover:bg-[#F8F9FA]"
                            : "border-[#E2E8F0] text-[#CBD5E1] cursor-not-allowed"
                    }`}
                >
                    <CalendarClock className="h-3.5 w-3.5" />
                    {scheduleNode ? summarizeSchedule(scheduleConfig || undefined) : "Schedule: เพิ่ม node ก่อน"}
                </button>

                <button
                    onClick={() => { setRunPanelOpen(!runPanelOpen); if (!runPanelOpen) loadHistory() }}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border border-[#E2E8F0] text-[#778DA9] hover:bg-[#F8F9FA]"
                >
                    <Activity className="h-3.5 w-3.5" /> Activity
                </button>

                <button
                    onClick={handleSave}
                    disabled={saving}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border border-[#2786C2] text-[#2786C2] hover:bg-[#EBF4FB] disabled:opacity-50"
                >
                    {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} Save
                </button>
                <button
                    onClick={() => setShowRunModal(true)}
                    className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs bg-[#2786C2] text-white hover:bg-[#1F6FA3]"
                >
                    <Play className="h-3.5 w-3.5" /> Run
                </button>
            </div>

            {notice && (
                <div className="px-4 py-2 bg-amber-50 text-amber-700 text-xs flex justify-between">
                    {notice}
                    <button onClick={() => setNotice(null)} className="font-bold ml-4">×</button>
                </div>
            )}

            <div className="flex flex-1 min-h-0">
                {/* ── Palette ── */}
                <aside className="w-56 bg-white border-r border-[#E2E8F0] overflow-y-auto p-3 space-y-4">
                    <p className="text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold">ลาก node ไปวางบน canvas</p>
                    {Object.entries(grouped).map(([cat, defs]) => {
                        const style = CATEGORY_STYLE[cat] || CATEGORY_STYLE.action
                        return (
                            <div key={cat}>
                                <p className="text-[10px] uppercase tracking-wide font-semibold mb-1.5" style={{ color: style.color }}>{cat}</p>
                                <div className="space-y-1.5">
                                    {defs.map((d) => {
                                        const Icon = TYPE_ICON[d.type] || style.icon
                                        return (
                                            <div
                                                key={d.type}
                                                draggable
                                                onDragStart={(e) => onDragStart(e, d.type)}
                                                title={d.description}
                                                className="flex items-center gap-2 px-2.5 py-2 rounded-lg border border-[#E2E8F0] bg-white cursor-grab hover:border-[#2786C2] hover:shadow-sm transition-all"
                                            >
                                                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md" style={{ background: style.bg }}>
                                                    <Icon className="h-3.5 w-3.5" style={{ color: style.color }} />
                                                </span>
                                                <span className="text-xs text-[#0D1B2A]">{d.label}</span>
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        )
                    })}
                </aside>

                {/* ── Canvas ── */}
                <div className="flex-1 relative" onDrop={onDrop} onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move" }}>
                    <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        nodeTypes={nodeTypes}
                        onNodesChange={(c) => { onNodesChange(c); if (c.some((ch) => ch.type !== "select" && ch.type !== "dimensions")) setDirty(true) }}
                        onEdgesChange={(c) => { onEdgesChange(c); if (c.some((ch) => ch.type === "remove")) setDirty(true) }}
                        onConnect={onConnect}
                        onNodeClick={(_, n) => setSelectedId(n.id)}
                        onPaneClick={() => setSelectedId(null)}
                        fitView
                        proOptions={{ hideAttribution: true }}
                        deleteKeyCode={["Backspace", "Delete"]}
                    >
                        <Background gap={18} color="#E2E8F0" />
                        <Controls position="bottom-left" />
                        <MiniMap pannable zoomable className="!bg-[#F8F9FA]" />
                    </ReactFlow>

                    {/* ── Activity panel ── */}
                    {runPanelOpen && (
                        <div className="absolute top-3 right-3 z-20 w-96 max-h-[calc(100%-24px)] bg-white border border-[#E2E8F0] rounded-xl shadow-lg flex flex-col">
                            <div className="flex items-center justify-between px-3 py-2.5 border-b border-[#E2E8F0]">
                                <span className="text-xs font-semibold text-[#0D1B2A] flex items-center gap-1.5">
                                    <Activity className="h-3.5 w-3.5 text-[#2786C2]" /> Run Activity
                                </span>
                                <button onClick={() => { setRunPanelOpen(false); setActiveRun(null); applyRunToCanvas(null) }} className="text-[#94A3B8] hover:text-[#0D1B2A]">
                                    <X className="h-4 w-4" />
                                </button>
                            </div>
                            <div className="overflow-y-auto p-3 space-y-2">
                                {activeRun ? (
                                    <>
                                        <div className="flex items-center gap-2 text-xs">
                                            <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                                                activeRun.status === "succeeded" ? "bg-emerald-50 text-emerald-600"
                                                : activeRun.status === "failed" ? "bg-red-50 text-red-600"
                                                : "bg-[#EBF4FB] text-[#2786C2]"
                                            }`}>
                                                {activeRun.status}
                                            </span>
                                            <span className="text-[#94A3B8] text-[10px]">{TRIGGER_TYPE_LABEL[activeRun.trigger_type] || activeRun.trigger_type}</span>
                                            {["queued", "running"].includes(activeRun.status) && <Loader2 className="h-3 w-3 animate-spin text-[#2786C2]" />}
                                            <button className="ml-auto text-[10px] text-[#2786C2] hover:underline" onClick={() => { setActiveRun(null); loadHistory() }}>
                                                ← history
                                            </button>
                                        </div>
                                        {activeRun.error && <p className="text-[10px] text-red-600 bg-red-50 rounded-lg p-2">{activeRun.error}</p>}
                                        {(activeRun.node_runs || []).map((nr) => <NodeRunRow key={nr.id} nr={nr} runId={activeRun.id} />)}
                                    </>
                                ) : (
                                    <>
                                        <p className="text-[10px] text-[#94A3B8]">ประวัติการรันล่าสุด</p>
                                        {runHistory.length === 0 && <p className="text-xs text-[#778DA9]">ยังไม่มีการรัน</p>}
                                        {runHistory.map((r) => (
                                            <button
                                                key={r.id}
                                                onClick={() => watchRun(r.id)}
                                                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg border border-[#E2E8F0] hover:border-[#2786C2] text-left"
                                            >
                                                {r.status === "succeeded" ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                                                    : r.status === "failed" ? <XCircle className="h-3.5 w-3.5 text-red-500" />
                                                    : <Loader2 className="h-3.5 w-3.5 text-[#2786C2] animate-spin" />}
                                                <span className="text-[11px] text-[#0D1B2A] flex-1">
                                                    {r.created_at ? new Date(r.created_at).toLocaleString() : r.id.slice(0, 8)}
                                                </span>
                                                <span className="text-[10px] text-[#94A3B8]">{TRIGGER_TYPE_LABEL[r.trigger_type] || r.trigger_type}</span>
                                            </button>
                                        ))}
                                    </>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                {/* ── Config panel ── */}
                {selectedNode && selectedDef && (
                    <aside className="w-80 bg-white border-l border-[#E2E8F0] overflow-y-auto p-4">
                        <div className="flex items-center justify-between mb-1">
                            <span className="text-xs font-semibold text-[#0D1B2A]">{selectedDef.label}</span>
                            <button onClick={deleteSelected} title="ลบ node" className="p-1.5 rounded-lg text-red-500 hover:bg-red-50">
                                <Trash2 className="h-3.5 w-3.5" />
                            </button>
                        </div>
                        <p className="text-[10px] text-[#94A3B8] mb-3">{selectedDef.description}</p>

                        {selectedNodeType === "trigger_schedule" && (
                            <ScheduleTriggerSettings
                                config={(selectedNode.data as WfNodeData).config}
                                onChange={updateSelectedConfigPatch}
                            />
                        )}

                        {selectedNodeType === "trigger_webhook" && (
                            <div className="mb-4 rounded-lg border border-[#E2E8F0] bg-[#F8F9FA] p-3">
                                <div className="flex items-center justify-between gap-2 mb-2">
                                    <span className="text-xs font-semibold text-[#0D1B2A] flex items-center gap-1.5">
                                        <Webhook className="h-3.5 w-3.5 text-[#2786C2]" /> Webhook URL
                                    </span>
                                    <span className={`px-2 py-0.5 rounded-full text-[10px] ${
                                        workflow.webhook_enabled ? "bg-emerald-50 text-emerald-600" : "bg-gray-100 text-gray-500"
                                    }`}>
                                        {workflow.webhook_enabled ? "enabled" : "disabled"}
                                    </span>
                                </div>
                                {workflow.webhook_enabled && !webhookUrl && (
                                    <p className="text-[10px] text-[#778DA9] leading-snug mb-2">
                                        Webhook เปิดอยู่แล้ว แต่ URL แบบเต็มจะแสดงเฉพาะตอน generate/regenerate เพื่อความปลอดภัย
                                    </p>
                                )}
                                {webhookUrl && (
                                    <div className="mb-2 rounded-md bg-white border border-[#E2E8F0] p-2">
                                        <p className="text-[10px] text-[#94A3B8] mb-1">คัดลอก URL นี้ไปใช้กับ web app หรือ LINE webhook</p>
                                        <code className="block text-[10px] text-[#0D1B2A] break-all">{webhookUrl}</code>
                                        <button
                                            onClick={async () => {
                                                try {
                                                    await navigator.clipboard.writeText(webhookUrl)
                                                    setNotice("คัดลอก Webhook URL แล้ว")
                                                } catch {
                                                    setNotice("คัดลอกไม่สำเร็จ กรุณาคัดลอกจากกล่อง URL")
                                                }
                                            }}
                                            className="mt-2 inline-flex items-center gap-1 text-[10px] text-[#2786C2] hover:underline"
                                        >
                                            <Copy className="h-3 w-3" /> Copy URL
                                        </button>
                                    </div>
                                )}
                                <div className="flex gap-2">
                                    <button
                                        onClick={handleRotateWebhookSecret}
                                        disabled={webhookBusy}
                                        className="flex-1 inline-flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-lg text-xs border border-[#2786C2] text-[#2786C2] hover:bg-[#EBF4FB] disabled:opacity-50"
                                    >
                                        {webhookBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCw className="h-3.5 w-3.5" />}
                                        {workflow.webhook_enabled ? "Regenerate" : "Generate"}
                                    </button>
                                    {workflow.webhook_enabled && (
                                        <button
                                            onClick={handleDisableWebhookSecret}
                                            disabled={webhookBusy}
                                            title="Disable webhook"
                                            className="inline-flex items-center justify-center px-2 py-1.5 rounded-lg text-xs border border-red-200 text-red-500 hover:bg-red-50 disabled:opacity-50"
                                        >
                                            <ShieldOff className="h-3.5 w-3.5" />
                                        </button>
                                    )}
                                </div>
                            </div>
                        )}

                        {selectedNodeType && !selectedNodeType.startsWith("trigger") && (
                            <button
                                onClick={handleTestNode}
                                disabled={testing}
                                className="w-full flex items-center justify-center gap-1.5 mb-4 px-3 py-1.5 rounded-lg text-xs border border-emerald-500 text-emerald-600 hover:bg-emerald-50 disabled:opacity-50"
                            >
                                {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5" />}
                                ทดสอบโหนดนี้
                            </button>
                        )}

                        <label className="block text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold mb-1">ชื่อโหนด</label>
                        <input
                            className="w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-xs mb-4 focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30"
                            value={(selectedNode.data as WfNodeData).label}
                            onChange={(e) => updateSelectedLabel(e.target.value)}
                        />

                        {selectedNodeType !== "trigger_schedule" && (
                        <div className="space-y-3">
                            {primaryConfigFields.map((f) => (
                                <div key={f.name}>
                                    {f.type !== "boolean" && (
                                        <label className="block text-[10px] uppercase tracking-wide text-[#94A3B8] font-semibold mb-1">
                                            {f.label}{f.required || (f.name === "skill_ids" && selectedConfig.mode === "agent") ? " *" : ""}
                                        </label>
                                    )}
                                    <ConfigField
                                        field={f}
                                        value={(selectedNode.data as WfNodeData).config?.[f.name]}
                                        onChange={(v) => updateSelectedConfig(f.name, v)}
                                        jobs={jobs}
                                        schemas={schemas}
                                        upstream={upstreamVars}
                                        integrations={integrations}
                                        aiProviders={aiProviders}
                                        agentSkills={agentSkills}
                                        agentSkillsLoading={agentSkillsLoading}
                                        agentSkillsError={agentSkillsError}
                                        onRetryAgentSkills={loadAgentSkills}
                                    />
                                    {f.hint && <p className="text-[10px] text-[#94A3B8] mt-1 leading-snug">{f.hint}</p>}
                                </div>
                            ))}
                            {advancedConfigFields.length > 0 && (
                                <details className="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC]">
                                    <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-[#475569]">Advanced</summary>
                                    <div className="space-y-3 border-t border-[#E2E8F0] p-3">
                                        {advancedConfigFields.map((f) => (
                                            <div key={f.name}>
                                                <label className="mb-1 block text-[10px] font-semibold uppercase text-[#94A3B8]">{f.label}</label>
                                                <ConfigField
                                                    field={f}
                                                    value={selectedConfig[f.name]}
                                                    onChange={(v) => updateSelectedConfig(f.name, v)}
                                                    jobs={jobs}
                                                    schemas={schemas}
                                                    upstream={upstreamVars}
                                                    integrations={integrations}
                                                    aiProviders={aiProviders}
                                                    agentSkills={agentSkills}
                                                    agentSkillsLoading={agentSkillsLoading}
                                                    agentSkillsError={agentSkillsError}
                                                    onRetryAgentSkills={loadAgentSkills}
                                                />
                                                {f.hint && <p className="mt-1 text-[10px] leading-snug text-[#94A3B8]">{f.hint}</p>}
                                            </div>
                                        ))}
                                    </div>
                                </details>
                            )}
                        </div>
                        )}

                        {selectedHelp && (
                            <div className="mt-5 rounded-lg border border-[#E2E8F0] bg-[#F8F9FA] text-[10px] text-[#778DA9]">
                                <button
                                    type="button"
                                    onClick={() => setHelpOpen((open) => !open)}
                                    aria-expanded={helpOpen}
                                    className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left hover:bg-white rounded-lg"
                                >
                                    <span className="font-semibold text-[#0D1B2A]">วิธีใช้งาน node นี้</span>
                                    {helpOpen
                                        ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-[#778DA9]" />
                                        : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[#778DA9]" />}
                                </button>
                                {helpOpen && (
                                    <div className="space-y-3 border-t border-[#E2E8F0] px-3 py-3 leading-relaxed">
                                        <section>
                                            <p className="font-semibold text-[#0D1B2A]">ใช้เมื่อไร</p>
                                            <p className="mt-0.5">{selectedHelp.purpose}</p>
                                        </section>

                                        {visibleConfigFields.length > 0 && selectedNodeType && (
                                            <section>
                                                <p className="font-semibold text-[#0D1B2A]">ตั้งค่าฟอร์ม</p>
                                                <ol className="mt-1 space-y-1 list-decimal list-outside pl-4">
                                                    {visibleConfigFields.map((field) => (
                                                        <li key={field.name}>
                                                            <span className="font-medium text-[#0D1B2A]">{field.label}{field.required ? " *" : ""}</span>
                                                            {": "}{getFieldHelp(selectedNodeType, field)}
                                                        </li>
                                                    ))}
                                                </ol>
                                            </section>
                                        )}

                                        {selectedNodeType === "trigger_schedule" && (
                                            <section>
                                                <p className="font-semibold text-[#0D1B2A]">ตั้งค่าฟอร์ม</p>
                                                <ol className="mt-1 space-y-1 list-decimal list-outside pl-4">
                                                    <li><span className="font-medium text-[#0D1B2A]">เปิด:</span> ต้องเปิดก่อนระบบจะรันตามตาราง</li>
                                                    <li><span className="font-medium text-[#0D1B2A]">ความถี่:</span> เลือกรอบที่เหมาะกับงาน เช่น ทุกวันหรือทุกวันทำงาน</li>
                                                    <li><span className="font-medium text-[#0D1B2A]">เวลา:</span> ระบุเวลาตามเขตเวลาของระบบ</li>
                                                    <li><span className="font-medium text-[#0D1B2A]">วัน/วันที่:</span> ตั้งค่าเพิ่มเติมเมื่อเลือกแบบรายสัปดาห์หรือรายเดือน</li>
                                                    <li><span className="font-medium text-[#0D1B2A]">Cron ขั้นสูง:</span> ใช้เฉพาะเมื่อต้องการตารางที่ preset ไม่รองรับ</li>
                                                </ol>
                                            </section>
                                        )}

                                        <section>
                                            <p className="font-semibold text-[#0D1B2A]">ลำดับการใช้งาน</p>
                                            <ol className="mt-1 space-y-1 list-decimal list-outside pl-4">
                                                {selectedHelp.steps.map((step) => <li key={step}>{step}</li>)}
                                            </ol>
                                        </section>

                                        <section>
                                            <p className="font-semibold text-[#0D1B2A]">ตัวอย่าง</p>
                                            <p className="mt-0.5 text-[#2786C2]">{selectedHelp.example}</p>
                                        </section>

                                        {selectedHelp.caution && (
                                            <p className="rounded-md bg-amber-50 px-2 py-1.5 text-amber-700">ข้อควรระวัง: {selectedHelp.caution}</p>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}
                    </aside>
                )}
            </div>

            {/* ── Run modal ── */}
            {showRunModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowRunModal(false)}>
                    <div className="bg-white rounded-xl p-5 w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
                        <h3 className="text-sm font-semibold text-[#0D1B2A] mb-3">Run Workflow</h3>
                        <label className="block text-xs text-[#778DA9] mb-1">Trigger input (JSON, optional) — เข้าถึงด้วย {"{{trigger.field}}"}</label>
                        <textarea
                            rows={4}
                            className="w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-xs font-mono mb-4 focus:outline-none focus:ring-2 focus:ring-[#2786C2]/30"
                            placeholder='{ "customer": "ACME" }'
                            value={runInput}
                            onChange={(e) => setRunInput(e.target.value)}
                        />
                        <div className="flex justify-end gap-2">
                            <button onClick={() => setShowRunModal(false)} className="px-3 py-1.5 rounded-lg text-xs text-[#778DA9] hover:bg-gray-50">ยกเลิก</button>
                            <button
                                onClick={handleRun}
                                disabled={starting}
                                className="px-4 py-1.5 rounded-lg bg-[#2786C2] text-white text-xs hover:bg-[#1F6FA3] disabled:opacity-50 flex items-center gap-1.5"
                            >
                                {starting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                                {dirty ? "Save & Run" : "Run"}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
        </AiFinderContext.Provider>
    )
}

export default function WorkflowBuilderPage() {
    return (
        <ReactFlowProvider>
            <Builder />
        </ReactFlowProvider>
    )
}
