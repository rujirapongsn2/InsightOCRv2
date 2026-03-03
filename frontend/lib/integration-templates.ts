export type TemplateCategory = "finance" | "legal" | "supply-chain" | "hr-admin" | "healthcare" | "quality-ops"

export interface LLMIntegrationTemplate {
    id: string
    category: TemplateCategory
    icon: string
    name: string
    description: string
    tags: string[]
    config: {
        model: string
        reasoningEffort: "low" | "medium" | "high"
        instructions: string
        userPrompt: string
        outputFormatPrompt: string
    }
}

export const TEMPLATE_CATEGORIES: Record<TemplateCategory, { label: string; labelTh: string; badgeClass: string; iconBgClass: string; iconColorClass: string }> = {
    finance:         { label: "Finance & Accounting", labelTh: "การเงิน / บัญชี",       badgeClass: "bg-blue-100 text-blue-700",    iconBgClass: "bg-gradient-to-br from-blue-500 to-blue-700",     iconColorClass: "text-white" },
    legal:           { label: "Legal & Compliance",   labelTh: "กฎหมาย / การปฏิบัติ",  badgeClass: "bg-purple-100 text-purple-700", iconBgClass: "bg-gradient-to-br from-violet-500 to-purple-700", iconColorClass: "text-white" },
    "supply-chain":  { label: "Supply Chain",         labelTh: "ซัพพลายเชน",           badgeClass: "bg-amber-100 text-amber-700",  iconBgClass: "bg-gradient-to-br from-amber-400 to-orange-500",  iconColorClass: "text-white" },
    "hr-admin":      { label: "HR & Administration",  labelTh: "HR / งานธุรการ",       badgeClass: "bg-green-100 text-green-700",  iconBgClass: "bg-gradient-to-br from-green-500 to-emerald-600", iconColorClass: "text-white" },
    healthcare:      { label: "Healthcare",           labelTh: "สาธารณสุข",            badgeClass: "bg-rose-100 text-rose-700",    iconBgClass: "bg-gradient-to-br from-rose-500 to-pink-600",     iconColorClass: "text-white" },
    "quality-ops":   { label: "Quality & Operations", labelTh: "คุณภาพ / ปฏิบัติการ",  badgeClass: "bg-slate-100 text-slate-600",  iconBgClass: "bg-gradient-to-br from-indigo-500 to-purple-700", iconColorClass: "text-white" },
}

export const LLM_TEMPLATES: LLMIntegrationTemplate[] = [
    // ─── Finance & Accounting ───────────────────────────────────────────────
    {
        id: "tpl-fin-001",
        category: "finance",
        icon: "FileCheck2",
        name: "ตรวจสอบใบแจ้งหนี้ข้ามเอกสาร",
        description: "เปรียบเทียบใบแจ้งหนี้กับใบสั่งซื้อ (PO) และใบรับสินค้า (GRN) ตรวจสอบความถูกต้องของ VAT และยอดรวม",
        tags: ["Invoice", "PO", "GRN", "VAT"],
        config: {
            model: "gpt-4o",
            reasoningEffort: "medium",
            instructions: `คุณคือผู้เชี่ยวชาญด้านการตรวจสอบเอกสารทางการเงิน มีหน้าที่เปรียบเทียบใบแจ้งหนี้ (Invoice) กับใบสั่งซื้อ (PO) และใบรับสินค้า (GRN)

กฎการตรวจสอบ:
1. ยอดรวมใน Invoice ต้องตรงกับ PO (อนุญาตส่วนต่าง ±1%)
2. รายการสินค้าและปริมาณต้องตรงกับ GRN
3. ภาษีมูลค่าเพิ่ม (VAT) ต้องคำนวณถูกต้อง (7% ของยอดก่อนภาษี)
4. ชื่อผู้ขาย เลขผู้เสียภาษี และที่อยู่ต้องครบถ้วน
5. วันที่ใบแจ้งหนี้ต้องไม่เกิน 30 วันหลังจากวันส่งสินค้า

ให้ระบุความคลาดเคลื่อนทุกรายการพร้อมคำแนะนำการแก้ไข`,
            userPrompt: `กรุณาตรวจสอบเอกสารต่อไปนี้และเปรียบเทียบข้อมูลระหว่างเอกสาร ระบุ:
1. ความคลาดเคลื่อนที่พบ (ถ้ามี)
2. การคำนวณ VAT ถูกต้องหรือไม่
3. สถานะการอนุมัติ (ผ่าน / ไม่ผ่าน / ต้องการข้อมูลเพิ่มเติม)`,
            outputFormatPrompt: `{
  "status": "approved|rejected|needs_review",
  "invoice_number": "string",
  "po_number": "string",
  "grn_number": "string",
  "discrepancies": [
    {
      "field": "string",
      "invoice_value": "string",
      "expected_value": "string",
      "severity": "critical|warning|info"
    }
  ],
  "vat_check": {
    "is_correct": true,
    "calculated_vat": 0.00,
    "declared_vat": 0.00
  },
  "summary": "string",
  "recommendation": "string"
}`,
        },
    },
    {
        id: "tpl-fin-002",
        category: "finance",
        icon: "Receipt",
        name: "สกัดข้อมูลใบเสร็จและค่าใช้จ่าย",
        description: "สกัดข้อมูลจากใบเสร็จรับเงินและจัดหมวดหมู่ค่าใช้จ่ายสำหรับระบบบัญชี",
        tags: ["Receipt", "Expense", "Accounting", "Category"],
        config: {
            model: "gpt-4o-mini",
            reasoningEffort: "low",
            instructions: `คุณคือผู้ช่วยสกัดข้อมูลใบเสร็จรับเงิน มีหน้าที่อ่านและจัดโครงสร้างข้อมูลจากใบเสร็จ

หมวดหมู่ค่าใช้จ่าย:
- TRAVEL: ค่าเดินทาง น้ำมัน ที่พัก
- MEALS: ค่าอาหาร เครื่องดื่ม จัดเลี้ยง
- SUPPLIES: วัสดุสำนักงาน อุปกรณ์
- UTILITIES: ค่าสาธารณูปโภค อินเทอร์เน็ต โทรศัพท์
- SERVICES: ค่าบริการวิชาชีพ ที่ปรึกษา
- OTHER: อื่น ๆ

ดึงข้อมูลให้ครบถ้วนและแม่นยำที่สุด`,
            userPrompt: `สกัดข้อมูลจากใบเสร็จ`,
            outputFormatPrompt: `{
  "receipt_date": "YYYY-MM-DD",
  "vendor_name": "string",
  "vendor_tax_id": "string",
  "items": [
    {
      "description": "string",
      "quantity": 0,
      "unit_price": 0.00,
      "amount": 0.00
    }
  ],
  "subtotal": 0.00,
  "vat_amount": 0.00,
  "total_amount": 0.00,
  "currency": "THB",
  "expense_category": "TRAVEL|MEALS|SUPPLIES|UTILITIES|SERVICES|OTHER",
  "payment_method": "cash|card|transfer|unknown",
  "notes": "string"
}`,
        },
    },
    {
        id: "tpl-fin-003",
        category: "finance",
        icon: "Landmark",
        name: "กระทบยอดรายการธนาคาร",
        description: "เปรียบเทียบรายการในสมุดบัญชีกับ Statement ธนาคาร ระบุรายการที่ยังไม่กระทบยอด",
        tags: ["Bank", "Reconciliation", "Statement"],
        config: {
            model: "gpt-4o",
            reasoningEffort: "medium",
            instructions: `คุณคือผู้เชี่ยวชาญด้านการกระทบยอดบัญชีธนาคาร (Bank Reconciliation)

หน้าที่หลัก:
1. เปรียบเทียบรายการใน Bank Statement กับรายการในสมุดรายวัน
2. ระบุรายการที่ตรงกัน รายการที่ยังค้างอยู่ และรายการที่ผิดปกติ
3. คำนวณยอดคงเหลือที่ถูกต้องตามหลักการบัญชี
4. แจ้งเตือนรายการที่อาจเป็นการทุจริตหรือข้อผิดพลาด

ให้ผลลัพธ์เป็นรายงานที่ชัดเจนพร้อมยอดกระทบยอด`,
            userPrompt: `กรุณากระทบยอดรายการต่อไปนี้ ระบุ:
1. รายการที่กระทบยอดได้
2. รายการที่ยังค้างอยู่ (Outstanding)
3. ความแตกต่างของยอดคงเหลือ`,
            outputFormatPrompt: `{
  "statement_date": "YYYY-MM-DD",
  "bank_closing_balance": 0.00,
  "book_closing_balance": 0.00,
  "matched_transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": "string",
      "amount": 0.00,
      "type": "debit|credit"
    }
  ],
  "outstanding_deposits": [],
  "outstanding_checks": [],
  "bank_errors": [],
  "book_errors": [],
  "adjusted_bank_balance": 0.00,
  "adjusted_book_balance": 0.00,
  "is_reconciled": true,
  "difference": 0.00,
  "notes": "string"
}`,
        },
    },

    // ─── Legal & Compliance ─────────────────────────────────────────────────
    {
        id: "tpl-legal-001",
        category: "legal",
        icon: "Scale",
        name: "เปรียบเทียบสัญญา",
        description: "เปรียบเทียบสัญญาสองฉบับ ระบุความแตกต่าง ข้อที่เพิ่ม/ลด และประเมินความเสี่ยงทางกฎหมาย",
        tags: ["Contract", "Comparison", "Risk", "Legal"],
        config: {
            model: "gpt-4o",
            reasoningEffort: "high",
            instructions: `คุณคือที่ปรึกษากฎหมายผู้เชี่ยวชาญด้านการวิเคราะห์สัญญา มีหน้าที่เปรียบเทียบสัญญาสองฉบับอย่างละเอียด

ขอบเขตการวิเคราะห์:
1. ข้อกำหนดและเงื่อนไขหลัก (Terms & Conditions)
2. ข้อยกเว้นความรับผิด (Liability Exclusions)
3. ข้อบทลงโทษและค่าปรับ (Penalties)
4. ระยะเวลาสัญญาและเงื่อนไขการต่ออายุ
5. เงื่อนไขการบอกเลิกสัญญา (Termination Clauses)
6. ข้อกฎหมายที่บังคับใช้ (Governing Law)
7. การระงับข้อพิพาท (Dispute Resolution)

ให้ประเมินระดับความเสี่ยง: ต่ำ / กลาง / สูง / วิกฤต
และให้คำแนะนำสำหรับการเจรจาต่อรอง`,
            userPrompt: `กรุณาเปรียบเทียบสัญญาที่แนบมาทั้งหมด วิเคราะห์และระบุ:
1. ข้อที่แตกต่างกันระหว่างฉบับที่ 1 และฉบับที่ 2
2. ข้อที่เพิ่มขึ้นหรือลดลง
3. ข้อที่มีความเสี่ยงสูง
4. คำแนะนำสำหรับการเจรจา`,
            outputFormatPrompt: `{
  "contract_a_title": "string",
  "contract_b_title": "string",
  "overall_risk_level": "low|medium|high|critical",
  "differences": [
    {
      "clause": "string",
      "contract_a": "string",
      "contract_b": "string",
      "risk_level": "low|medium|high|critical",
      "impact": "string",
      "recommendation": "string"
    }
  ],
  "added_clauses": ["string"],
  "removed_clauses": ["string"],
  "key_risks": [
    {
      "risk": "string",
      "severity": "low|medium|high|critical",
      "mitigation": "string"
    }
  ],
  "negotiation_points": ["string"],
  "summary": "string",
  "recommendation": "accept|reject|negotiate"
}`,
        },
    },
    {
        id: "tpl-legal-002",
        category: "legal",
        icon: "ShieldCheck",
        name: "ตรวจสอบการปฏิบัติตามกฎระเบียบ",
        description: "ตรวจสอบเอกสารตาม PDPA และกฎระเบียบที่เกี่ยวข้อง ระบุส่วนที่ไม่สอดคล้องและแนวทางแก้ไข",
        tags: ["PDPA", "Compliance", "Regulation", "Privacy"],
        config: {
            model: "gpt-4o",
            reasoningEffort: "high",
            instructions: `คุณคือผู้เชี่ยวชาญด้าน Compliance และกฎหมายคุ้มครองข้อมูลส่วนบุคคล (PDPA)

กรอบการตรวจสอบ:
1. พระราชบัญญัติคุ้มครองข้อมูลส่วนบุคคล พ.ศ. 2562 (PDPA)
2. ข้อมูลส่วนบุคคลอ่อนไหว (Sensitive Data) ได้แก่ สุขภาพ การเงิน ชีวภาพ
3. ความยินยอม (Consent) และวัตถุประสงค์การประมวลผล
4. สิทธิของเจ้าของข้อมูล
5. มาตรการรักษาความปลอดภัยของข้อมูล
6. การโอนข้อมูลข้ามแดน

ระบุข้อที่ไม่สอดคล้องพร้อมบทลงโทษที่อาจเกิดขึ้นและแนวทางแก้ไข`,
            userPrompt: `ตรวจสอบเอกสารต่อไปนี้เพื่อความสอดคล้องกับ PDPA และกฎระเบียบ`,
            outputFormatPrompt: `{
  "document_type": "string",
  "compliance_score": 0,
  "overall_status": "compliant|non_compliant|partially_compliant",
  "violations": [
    {
      "regulation": "string",
      "section": "string",
      "description": "string",
      "severity": "low|medium|high|critical",
      "penalty_risk": "string",
      "remediation": "string"
    }
  ],
  "compliant_items": ["string"],
  "sensitive_data_found": ["string"],
  "recommendations": ["string"],
  "priority_actions": ["string"],
  "summary": "string"
}`,
        },
    },
    {
        id: "tpl-legal-003",
        category: "legal",
        icon: "Lock",
        name: "สกัดข้อกำหนดสำคัญจาก NDA",
        description: "สกัดข้อกำหนดสำคัญจากสัญญาไม่เปิดเผยข้อมูล (NDA) พร้อมประเมินความเสี่ยง",
        tags: ["NDA", "Confidentiality", "Key Terms", "Risk"],
        config: {
            model: "gpt-4o",
            reasoningEffort: "medium",
            instructions: `คุณคือผู้เชี่ยวชาญด้านการวิเคราะห์สัญญาไม่เปิดเผยข้อมูล (Non-Disclosure Agreement)

ข้อกำหนดที่ต้องสกัด:
1. คู่สัญญา (Parties) - ผู้เปิดเผยและผู้รับข้อมูล
2. นิยามข้อมูลลับ (Definition of Confidential Information)
3. ข้อยกเว้น (Exclusions)
4. ระยะเวลาการรักษาความลับ (Duration)
5. การใช้ข้อมูล (Permitted Use)
6. ข้อห้าม (Restrictions)
7. บทลงโทษการละเมิด (Breach Consequences)
8. เขตอำนาจศาล (Jurisdiction)

ประเมินความเสี่ยงและจุดที่ควรเจรจาต่อรอง`,
            userPrompt: `สกัดและวิเคราะห์ข้อกำหนดจาก NDA ต่อไปนี้`,
            outputFormatPrompt: `{
  "parties": {
    "disclosing_party": "string",
    "receiving_party": "string"
  },
  "effective_date": "YYYY-MM-DD",
  "duration_years": 0,
  "confidential_info_definition": "string",
  "permitted_use": "string",
  "exclusions": ["string"],
  "key_restrictions": ["string"],
  "breach_consequences": "string",
  "jurisdiction": "string",
  "risk_assessment": {
    "overall_risk": "low|medium|high",
    "risky_clauses": [
      {
        "clause": "string",
        "risk": "string",
        "negotiation_suggestion": "string"
      }
    ]
  },
  "missing_clauses": ["string"],
  "summary": "string"
}`,
        },
    },

    // ─── Supply Chain & Logistics ───────────────────────────────────────────
    {
        id: "tpl-sc-001",
        category: "supply-chain",
        icon: "PackageCheck",
        name: "ตรวจสอบเอกสารข้ามฉบับ (ค้าส่งอาหาร)",
        description: "ตรวจสอบความสอดคล้องระหว่างใบสั่งซื้อ ใบส่งสินค้า และใบกำกับภาษีในธุรกิจค้าส่งอาหาร",
        tags: ["PO", "Delivery", "Tax Invoice", "Food"],
        config: {
            model: "gpt-4o",
            reasoningEffort: "medium",
            instructions: `คุณคือผู้เชี่ยวชาญด้านการตรวจสอบเอกสารในห่วงโซ่อุปทานธุรกิจค้าส่งอาหาร

เอกสารที่ตรวจสอบ:
1. ใบสั่งซื้อ (Purchase Order / PO)
2. ใบส่งสินค้า / ใบเบิกสินค้า (Delivery Note)
3. ใบกำกับภาษี (Tax Invoice)

กฎการตรวจสอบ:
- ชื่อสินค้า รหัสสินค้า และปริมาณต้องตรงกันทุกเอกสาร
- ราคาต่อหน่วยต้องตรงกับ PO (ยกเว้นมีการแก้ไขที่ได้รับอนุมัติ)
- วันหมดอายุของสินค้าอาหารต้องระบุในใบส่งสินค้า
- เลขที่ Lot / Batch ต้องสอดคล้องกัน
- เงื่อนไขการชำระเงินต้องตรงกับสัญญา

ระบุความคลาดเคลื่อนทุกรายการพร้อมระดับความรุนแรง`,
            userPrompt: `ตรวจสอบเอกสารต่อไปนี้ ระบุความคลาดเคลื่อนและประเมินว่าสามารถยืนยันการรับสินค้าและชำระเงินได้หรือไม่`,
            outputFormatPrompt: `{
  "verification_status": "approved|rejected|pending",
  "po_number": "string",
  "delivery_note_number": "string",
  "tax_invoice_number": "string",
  "items": [
    {
      "product_code": "string",
      "product_name": "string",
      "po_qty": 0,
      "delivered_qty": 0,
      "invoiced_qty": 0,
      "unit_price": 0.00,
      "expiry_date": "YYYY-MM-DD",
      "lot_number": "string",
      "status": "matched|discrepancy"
    }
  ],
  "discrepancies": [
    {
      "type": "string",
      "description": "string",
      "severity": "critical|warning|info"
    }
  ],
  "payment_eligible": true,
  "total_amount": 0.00,
  "summary": "string"
}`,
        },
    },
    {
        id: "tpl-sc-002",
        category: "supply-chain",
        icon: "Ship",
        name: "สกัดข้อมูลเอกสารขนส่ง",
        description: "สกัดข้อมูลจาก B/L, Packing List และ Commercial Invoice สำหรับการนำเข้า-ส่งออก",
        tags: ["B/L", "Packing List", "Commercial Invoice", "Import/Export"],
        config: {
            model: "gpt-4o-mini",
            reasoningEffort: "low",
            instructions: `คุณคือผู้เชี่ยวชาญด้านเอกสารการค้าระหว่างประเทศ

เอกสารที่จัดการ:
1. Bill of Lading (B/L) - ใบตราส่งสินค้า
2. Packing List - รายการบรรจุภัณฑ์
3. Commercial Invoice - ใบกำกับสินค้าพาณิชย์

ข้อมูลที่ต้องสกัด:
- ผู้ส่งสินค้า (Shipper) และผู้รับสินค้า (Consignee)
- รายการสินค้า ปริมาณ น้ำหนัก และมูลค่า
- เงื่อนไขการส่งมอบ Incoterms (EXW, FOB, CIF ฯลฯ)
- ท่าเรือต้นทางและปลายทาง
- หมายเลขตู้คอนเทนเนอร์และซีล
- วันที่คาดการณ์การส่งมอบ`,
            userPrompt: `สกัดข้อมูลจากเอกสารขนส่งต่อไปนี้`,
            outputFormatPrompt: `{
  "document_type": "BL|packing_list|commercial_invoice|combined",
  "bl_number": "string",
  "shipper": "string",
  "consignee": "string",
  "notify_party": "string",
  "vessel_name": "string",
  "voyage_number": "string",
  "port_of_loading": "string",
  "port_of_discharge": "string",
  "incoterms": "string",
  "container_numbers": ["string"],
  "seal_numbers": ["string"],
  "cargo_description": "string",
  "packages": [
    {
      "marks": "string",
      "description": "string",
      "quantity": 0,
      "gross_weight_kg": 0.00,
      "net_weight_kg": 0.00,
      "cbm": 0.00,
      "unit_price": 0.00,
      "total_value": 0.00,
      "currency": "string"
    }
  ],
  "total_gross_weight": 0.00,
  "total_value": 0.00,
  "etd": "YYYY-MM-DD",
  "eta": "YYYY-MM-DD",
  "payment_terms": "string"
}`,
        },
    },
    {
        id: "tpl-sc-003",
        category: "supply-chain",
        icon: "BarChart2",
        name: "รายงานความคลาดเคลื่อนสต็อคสินค้า",
        description: "วิเคราะห์ความแตกต่างระหว่างสต็อคทางบัญชีและสต็อคจริงจากรายงานการนับสินค้า",
        tags: ["Inventory", "Stock", "Discrepancy", "Count"],
        config: {
            model: "gpt-4o-mini",
            reasoningEffort: "medium",
            instructions: `คุณคือผู้เชี่ยวชาญด้านการวิเคราะห์สต็อคสินค้าและคลังสินค้า

หน้าที่หลัก:
1. เปรียบเทียบยอดสต็อคในระบบกับผลการนับจริง
2. คำนวณมูลค่าความคลาดเคลื่อน
3. จำแนกประเภทความคลาดเคลื่อน (บวก/ลบ)
4. ระบุสินค้าที่มีความเสี่ยงสูง (มูลค่าสูง/ความคลาดเคลื่อนมาก)
5. แนะนำการปรับปรุงกระบวนการควบคุมสต็อค

เกณฑ์ความคลาดเคลื่อนที่ยอมรับได้: ±2% ของมูลค่าสต็อครวม`,
            userPrompt: `วิเคราะห์รายงานสต็อคต่อไปนี้`,
            outputFormatPrompt: `{
  "count_date": "YYYY-MM-DD",
  "location": "string",
  "total_sku_counted": 0,
  "items": [
    {
      "sku": "string",
      "product_name": "string",
      "system_qty": 0,
      "physical_qty": 0,
      "variance_qty": 0,
      "unit_cost": 0.00,
      "variance_value": 0.00,
      "variance_pct": 0.00,
      "status": "matched|short|over"
    }
  ],
  "total_variance_value": 0.00,
  "total_variance_pct": 0.00,
  "high_risk_items": ["string"],
  "within_tolerance": true,
  "root_cause_analysis": "string",
  "recommendations": ["string"],
  "adjustment_required": true
}`,
        },
    },

    // ─── HR & Administration ────────────────────────────────────────────────
    {
        id: "tpl-hr-001",
        category: "hr-admin",
        icon: "Briefcase",
        name: "วิเคราะห์สัญญาจ้างงาน",
        description: "วิเคราะห์สัญญาจ้างงานตามกฎหมายแรงงานไทย ระบุข้อที่ไม่ถูกต้องและความเสี่ยง",
        tags: ["Employment", "Contract", "Labor Law", "Thailand"],
        config: {
            model: "gpt-4o",
            reasoningEffort: "medium",
            instructions: `คุณคือผู้เชี่ยวชาญด้านกฎหมายแรงงานไทยและสัญญาจ้างงาน

กฎหมายที่เกี่ยวข้อง:
1. พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541 (แก้ไขเพิ่มเติม)
2. ประกาศอัตราค่าจ้างขั้นต่ำ
3. กฎหมายประกันสังคม
4. กฎหมายกองทุนเงินทดแทน

ตรวจสอบ:
- ค่าจ้างและสวัสดิการตามกฎหมาย
- วันหยุดและการลาตามสิทธิ์
- เงื่อนไขการเลิกจ้างและค่าชดเชย
- ข้อห้ามทำงานกับคู่แข่ง (Non-compete)
- ความลับทางการค้า
- ข้อสัญญาที่อาจเป็นโมฆะตามกฎหมาย`,
            userPrompt: `วิเคราะห์สัญญาจ้างงานต่อไปนี้ ระบุข้อที่ไม่ถูกต้องตามกฎหมายและข้อที่เป็นประโยชน์/โทษต่อลูกจ้าง`,
            outputFormatPrompt: `{
  "employee_name": "string",
  "employer_name": "string",
  "position": "string",
  "employment_type": "permanent|contract|part-time|probation",
  "start_date": "YYYY-MM-DD",
  "salary": 0.00,
  "legal_compliance": {
    "minimum_wage_compliant": true,
    "leave_benefits_compliant": true,
    "severance_clause_present": true,
    "social_security_mentioned": true
  },
  "issues": [
    {
      "clause": "string",
      "issue": "string",
      "severity": "low|medium|high|illegal",
      "legal_reference": "string",
      "recommendation": "string"
    }
  ],
  "employee_friendly_clauses": ["string"],
  "employer_protective_clauses": ["string"],
  "non_compete": {
    "present": true,
    "duration_months": 0,
    "geographic_scope": "string",
    "is_enforceable": true
  },
  "overall_assessment": "string",
  "recommendation": "string"
}`,
        },
    },
    {
        id: "tpl-hr-002",
        category: "hr-admin",
        icon: "ClipboardList",
        name: "สรุปรายงานการประชุม",
        description: "สกัดมติที่ประชุม รายการงานที่ต้องทำ และผู้รับผิดชอบจากรายงานการประชุม",
        tags: ["Meeting", "Minutes", "Action Items", "Summary"],
        config: {
            model: "gpt-4o-mini",
            reasoningEffort: "low",
            instructions: `คุณคือผู้ช่วยสรุปการประชุมที่มีประสิทธิภาพ

สิ่งที่ต้องสกัด:
1. วัน เวลา สถานที่ และผู้เข้าร่วมประชุม
2. วาระการประชุมและสรุปการอภิปราย
3. มติที่ประชุม (ผ่าน/ไม่ผ่าน)
4. รายการงานที่ต้องดำเนินการ (Action Items)
5. ผู้รับผิดชอบและกำหนดเสร็จ
6. วันนัดประชุมครั้งต่อไป

ให้สรุปกระชับ ชัดเจน และเป็นระเบียบ`,
            userPrompt: `สรุปรายงานการประชุมต่อไปนี้`,
            outputFormatPrompt: `{
  "meeting_date": "YYYY-MM-DD",
  "meeting_time": "HH:MM",
  "location": "string",
  "chairperson": "string",
  "attendees": ["string"],
  "absent": ["string"],
  "agenda_items": [
    {
      "item_number": 0,
      "topic": "string",
      "discussion_summary": "string",
      "resolution": "string",
      "resolution_status": "approved|rejected|deferred|noted"
    }
  ],
  "action_items": [
    {
      "task": "string",
      "assignee": "string",
      "due_date": "YYYY-MM-DD",
      "priority": "high|medium|low"
    }
  ],
  "next_meeting_date": "YYYY-MM-DD",
  "executive_summary": "string"
}`,
        },
    },
    {
        id: "tpl-hr-003",
        category: "hr-admin",
        icon: "CalendarCheck",
        name: "ตรวจสอบใบลาและการอนุมัติ",
        description: "ตรวจสอบความถูกต้องของใบลา ตรวจสอบสิทธิ์วันลาคงเหลือ และสถานะการอนุมัติ",
        tags: ["Leave", "Approval", "HR", "Attendance"],
        config: {
            model: "gpt-4o-mini",
            reasoningEffort: "low",
            instructions: `คุณคือระบบตรวจสอบใบลาพนักงาน

ประเภทการลาตามกฎหมายแรงงานไทย:
- ลาพักร้อน: ≥6 วัน/ปี (หลังทำงาน 1 ปี)
- ลาป่วย: ≤30 วัน/ปี (โดยได้รับค่าจ้าง)
- ลากิจส่วนตัว: ตามนโยบายบริษัท (โดยปกติ 3-5 วัน)
- ลาคลอด: 98 วัน (45 วันได้รับค่าจ้าง)
- ลาทหาร: ตามระยะเวลาจริง

การตรวจสอบ:
1. ประเภทการลาถูกต้องและมีสิทธิ์หรือไม่
2. วันลาไม่ทับซ้อนกับวันหยุดนักขัตฤกษ์
3. มีเอกสารประกอบครบถ้วน (ใบรับรองแพทย์สำหรับลาป่วย >3 วัน)
4. ผ่านขั้นตอนการอนุมัติตามลำดับ`,
            userPrompt: `ตรวจสอบใบลาต่อไปนี้`,
            outputFormatPrompt: `{
  "employee_name": "string",
  "employee_id": "string",
  "leave_type": "annual|sick|personal|maternity|military|other",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "total_days": 0,
  "reason": "string",
  "documents_required": true,
  "documents_provided": true,
  "remaining_leave_balance": 0,
  "eligibility_check": {
    "is_eligible": true,
    "reason": "string"
  },
  "approval_chain": [
    {
      "approver": "string",
      "status": "approved|pending|rejected",
      "date": "YYYY-MM-DD"
    }
  ],
  "overall_status": "approved|rejected|pending",
  "notes": "string"
}`,
        },
    },

    // ─── Healthcare ─────────────────────────────────────────────────────────
    {
        id: "tpl-health-001",
        category: "healthcare",
        icon: "HeartPulse",
        name: "ตรวจสอบใบแจ้งหนี้ค่ารักษาพยาบาล",
        description: "ตรวจสอบความถูกต้องของใบแจ้งหนี้ค่ารักษาพยาบาล และตรวจสอบสิทธิ์การเบิกจ่าย",
        tags: ["Medical", "Invoice", "Insurance", "Reimbursement"],
        config: {
            model: "gpt-4o",
            reasoningEffort: "medium",
            instructions: `คุณคือผู้เชี่ยวชาญด้านการตรวจสอบค่ารักษาพยาบาลและการเบิกจ่ายสวัสดิการ

สิทธิ์การรักษาพยาบาลที่พบบ่อย:
1. ประกันสังคม - โรงพยาบาลตามสิทธิ์ ค่ารักษาฟรี
2. สวัสดิการข้าราชการ - เบิกได้ตามระเบียบกรมบัญชีกลาง
3. ประกันสุขภาพกลุ่ม - วงเงินและเงื่อนไขตามกรมธรรม์
4. จ่ายเองและเบิกคืน - ต้องมีใบเสร็จต้นฉบับ

การตรวจสอบ:
- รหัสโรค (ICD-10) สอดคล้องกับการรักษา
- ค่ารักษาไม่เกินวงเงินสิทธิ์
- ใบเสร็จต้นฉบับจากสถานพยาบาลที่รับรอง
- ยาและการรักษาอยู่ในบัญชียาและรายการที่เบิกได้`,
            userPrompt: `ตรวจสอบใบแจ้งหนี้ค่ารักษาพยาบาลต่อไปนี้ ระบุรายการที่เบิกได้ รายการที่เบิกไม่ได้ และยอดรวมที่อนุมัติ`,
            outputFormatPrompt: `{
  "patient_name": "string",
  "hospital_name": "string",
  "visit_date": "YYYY-MM-DD",
  "diagnosis": "string",
  "icd10_codes": ["string"],
  "items": [
    {
      "description": "string",
      "amount": 0.00,
      "reimbursable": true,
      "rejection_reason": "string"
    }
  ],
  "total_amount": 0.00,
  "approved_amount": 0.00,
  "rejected_amount": 0.00,
  "insurance_type": "social_security|civil_servant|group|self_pay",
  "claim_status": "approved|rejected|partial",
  "rejection_reasons": ["string"],
  "required_documents": ["string"],
  "notes": "string"
}`,
        },
    },
    {
        id: "tpl-health-002",
        category: "healthcare",
        icon: "FlaskConical",
        name: "สกัดและสรุปผลตรวจทางห้องปฏิบัติการ",
        description: "สกัดผลการตรวจเลือดและผลแล็บ ระบุค่าที่ผิดปกติ และสรุปสำหรับแพทย์",
        tags: ["Lab Results", "Blood Test", "Abnormal", "Healthcare"],
        config: {
            model: "gpt-4o-mini",
            reasoningEffort: "low",
            instructions: `คุณคือผู้ช่วยสกัดและวิเคราะห์ผลการตรวจทางห้องปฏิบัติการ

หมวดหมู่ผลตรวจที่พบบ่อย:
- CBC (Complete Blood Count): ความสมบูรณ์ของเม็ดเลือด
- Chemistry Panel: การทำงานของตับ ไต น้ำตาล ไขมัน
- Urinalysis: การตรวจปัสสาวะ
- Thyroid Function: การทำงานของต่อมไทรอยด์
- Tumor Markers: มะเร็ง

สำหรับแต่ละรายการ:
1. ระบุค่าที่ตรวจได้ ค่าอ้างอิงปกติ และหน่วย
2. ระบุสถานะ: ปกติ / สูงกว่าปกติ / ต่ำกว่าปกติ / วิกฤต
3. สรุปค่าที่ผิดปกติสำหรับแพทย์

หมายเหตุ: ให้ข้อมูลเชิงข้อเท็จจริงเท่านั้น ไม่วินิจฉัยโรค`,
            userPrompt: `สกัดและสรุปผลการตรวจต่อไปนี้`,
            outputFormatPrompt: `{
  "patient_id": "string",
  "test_date": "YYYY-MM-DD",
  "lab_name": "string",
  "ordered_by": "string",
  "results": [
    {
      "test_name": "string",
      "value": "string",
      "unit": "string",
      "reference_range": "string",
      "status": "normal|high|low|critical",
      "flag": "H|L|HH|LL|N"
    }
  ],
  "abnormal_results": [
    {
      "test_name": "string",
      "value": "string",
      "reference_range": "string",
      "status": "high|low|critical",
      "clinical_significance": "string"
    }
  ],
  "critical_values": ["string"],
  "summary_for_physician": "string",
  "follow_up_recommended": true
}`,
        },
    },

    // ─── Quality & Operations ────────────────────────────────────────────────
    {
        id: "tpl-qa-001",
        category: "quality-ops",
        icon: "ClipboardCheck",
        name: "วิเคราะห์รายงานการตรวจสอบคุณภาพ",
        description: "วิเคราะห์รายงาน QC ตรวจสอบข้อบกพร่อง จัดประเภทตาม AQL และสรุปผลการยอมรับ/ปฏิเสธ",
        tags: ["QC", "Defect", "AQL", "Inspection"],
        config: {
            model: "gpt-4o",
            reasoningEffort: "medium",
            instructions: `คุณคือผู้เชี่ยวชาญด้านการควบคุมคุณภาพและมาตรฐาน ISO

มาตรฐานการตรวจสอบ:
- AQL (Acceptable Quality Limit) ตามมาตรฐาน MIL-STD-1916 / ISO 2859
- ระดับความรุนแรงของข้อบกพร่อง: Critical / Major / Minor
- AQL ปกติ: Critical = 0, Major = 1.0, Minor = 2.5

การวิเคราะห์:
1. จำนวนตัวอย่างและข้อบกพร่องที่พบ
2. เปรียบเทียบกับเกณฑ์ AQL
3. จำแนกประเภทข้อบกพร่อง
4. สรุปผล Accept / Reject / Re-inspect
5. แนะนำการแก้ไขและป้องกัน`,
            userPrompt: `วิเคราะห์รายงาน QC ต่อไปนี้`,
            outputFormatPrompt: `{
  "inspection_date": "YYYY-MM-DD",
  "product": "string",
  "lot_number": "string",
  "lot_size": 0,
  "sample_size": 0,
  "inspection_level": "I|II|III|S1|S2|S3|S4",
  "defects_found": [
    {
      "defect_type": "string",
      "classification": "critical|major|minor",
      "count": 0,
      "description": "string",
      "location": "string"
    }
  ],
  "aql_results": {
    "critical_defects": 0,
    "critical_aql": 0,
    "critical_result": "pass|fail",
    "major_defects": 0,
    "major_aql": 1.0,
    "major_result": "pass|fail",
    "minor_defects": 0,
    "minor_aql": 2.5,
    "minor_result": "pass|fail"
  },
  "overall_result": "accept|reject|re-inspect",
  "defect_rate_pct": 0.00,
  "corrective_actions": ["string"],
  "root_cause": "string",
  "inspector": "string"
}`,
        },
    },
    {
        id: "tpl-qa-002",
        category: "quality-ops",
        icon: "TrendingUp",
        name: "วิเคราะห์ประสิทธิภาพ SLA / KPI",
        description: "วิเคราะห์รายงานประสิทธิภาพ SLA/KPI ระบุตัวชี้วัดที่ต่ำกว่าเป้าหมายและแนวทางปรับปรุง",
        tags: ["SLA", "KPI", "Performance", "Report"],
        config: {
            model: "gpt-4o-mini",
            reasoningEffort: "medium",
            instructions: `คุณคือผู้วิเคราะห์ประสิทธิภาพองค์กรด้าน SLA และ KPI

หน้าที่หลัก:
1. สกัดตัวชี้วัดทั้งหมดจากรายงาน
2. เปรียบเทียบกับเป้าหมายที่กำหนด
3. คำนวณเปอร์เซ็นต์การบรรลุเป้าหมาย
4. ระบุ KPI ที่ต่ำกว่าเป้าหมาย (Under-performing)
5. วิเคราะห์แนวโน้ม (ดีขึ้น/แย่ลง/คงที่)
6. แนะนำแนวทางการปรับปรุง

ระดับประสิทธิภาพ:
- Excellent: ≥110% ของเป้า
- On Track: 90-109%
- Warning: 70-89%
- Critical: <70%`,
            userPrompt: `วิเคราะห์รายงาน SLA/KPI ต่อไปนี้`,
            outputFormatPrompt: `{
  "report_period": "string",
  "department": "string",
  "kpis": [
    {
      "name": "string",
      "target": "string",
      "actual": "string",
      "achievement_pct": 0.00,
      "trend": "improving|stable|declining",
      "status": "excellent|on_track|warning|critical"
    }
  ],
  "sla_items": [
    {
      "service": "string",
      "sla_target": "string",
      "actual_performance": "string",
      "breaches": 0,
      "status": "met|breached"
    }
  ],
  "overall_score": 0.00,
  "underperforming_kpis": ["string"],
  "top_performers": ["string"],
  "recommendations": [
    {
      "kpi": "string",
      "action": "string",
      "priority": "high|medium|low",
      "owner": "string"
    }
  ],
  "executive_summary": "string"
}`,
        },
    },
    {
        id: "tpl-qa-003",
        category: "quality-ops",
        icon: "AlertOctagon",
        name: "วิเคราะห์รายงานเหตุการณ์ไม่พึงประสงค์",
        description: "วิเคราะห์รายงานเหตุการณ์ด้วย 5 Why และ CAPA เพื่อหาสาเหตุรากเหง้าและแผนป้องกัน",
        tags: ["Incident", "Root Cause", "5 Why", "CAPA"],
        config: {
            model: "gpt-4o",
            reasoningEffort: "high",
            instructions: `คุณคือผู้เชี่ยวชาญด้าน Root Cause Analysis และ Corrective & Preventive Action (CAPA)

เครื่องมือที่ใช้:
1. 5 Why Analysis - ถามทำไม 5 ครั้งเพื่อหาสาเหตุที่แท้จริง
2. Fishbone Diagram (Ishikawa) - วิเคราะห์ใน 6 มิติ: Man, Machine, Method, Material, Measurement, Environment
3. CAPA Framework:
   - Containment Action: การควบคุมทันที
   - Corrective Action: การแก้ไขสาเหตุ
   - Preventive Action: การป้องกันไม่ให้เกิดซ้ำ

ประเมินความรุนแรงตาม Risk Matrix:
- Severity: 1-5 (ผลกระทบ)
- Likelihood: 1-5 (โอกาสเกิดซ้ำ)
- Risk Score = Severity × Likelihood`,
            userPrompt: `วิเคราะห์รายงานเหตุการณ์ต่อไปนี้โดยใช้ 5 Why และ CAPA`,
            outputFormatPrompt: `{
  "incident_id": "string",
  "incident_date": "YYYY-MM-DD",
  "reported_by": "string",
  "incident_description": "string",
  "immediate_impact": "string",
  "severity": 0,
  "likelihood": 0,
  "risk_score": 0,
  "risk_level": "low|medium|high|critical",
  "five_why": [
    { "why_number": 1, "question": "string", "answer": "string" },
    { "why_number": 2, "question": "string", "answer": "string" },
    { "why_number": 3, "question": "string", "answer": "string" },
    { "why_number": 4, "question": "string", "answer": "string" },
    { "why_number": 5, "question": "string", "answer": "string" }
  ],
  "root_cause": "string",
  "fishbone_analysis": {
    "man": "string",
    "machine": "string",
    "method": "string",
    "material": "string",
    "measurement": "string",
    "environment": "string"
  },
  "capa": {
    "containment_actions": [
      { "action": "string", "owner": "string", "due_date": "YYYY-MM-DD", "status": "open|in_progress|closed" }
    ],
    "corrective_actions": [
      { "action": "string", "owner": "string", "due_date": "YYYY-MM-DD", "status": "open|in_progress|closed" }
    ],
    "preventive_actions": [
      { "action": "string", "owner": "string", "due_date": "YYYY-MM-DD", "status": "open|in_progress|closed" }
    ]
  },
  "lessons_learned": "string",
  "follow_up_date": "YYYY-MM-DD"
}`,
        },
    },
]
