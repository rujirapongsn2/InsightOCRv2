# Demo Use Case: IT Service Contract Renewal Comparison
## InsightDOC — AI-Powered Contract Intelligence

> **Scenario:** Siam Nexus Co., Ltd. is evaluating whether to renew its 3-year IT Managed Services contract with DataSphere Systems Co., Ltd. The Legal and Procurement teams need to compare the expiring contract (Contract A) against the new renewal proposal (Contract B) across key commercial, SLA, and legal dimensions — before signing.

---

## 📁 Test Files

| File | Description |
|------|-------------|
| `Contract_A_Expiring.pdf` | SNX-IT-2022-0047 — Current 3-year IT Managed Services contract, expires 28 Feb 2025 |
| `Contract_B_Renewal_Proposal.pdf` | SNX-IT-2025-0012-R — New 3-year renewal proposal, effective 1 Mar 2025 |

---

## 1. JSON Schema

> **หมายเหตุ:** ใช้ Schema ไฟล์เดียวกันสำหรับทั้งสองสัญญา เนื่องจากโครงสร้างหลักเหมือนกัน
> ฟิลด์ที่มีเฉพาะสัญญา B (เช่น `replaces_contract`, `liability_terms`, `change_vs_contract_a`) ถูกทำเป็น **optional**
> เมื่อ extract จากสัญญา A ฟิลด์เหล่านี้จะมีค่าเป็น `null` หรือไม่ปรากฏ ซึ่ง AI จะนำมาเปรียบเทียบได้ทันที

### Schema ใช้ร่วมกัน — `schema_it_service_contract.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "IT Service Contract — Unified Schema (ใช้ได้กับทั้งสัญญาเดิมและสัญญาต่ออายุ)",
  "description": "Schema สำหรับ extract ข้อมูลจากสัญญา IT Managed Services ทุกฉบับ ทั้งฉบับปัจจุบันและข้อเสนอต่ออายุ",
  "type": "object",
  "properties": {

    "contract_reference": {
      "type": "string",
      "description": "เลขที่อ้างอิงสัญญา เช่น SNX-IT-2022-0047"
    },
    "replaces_contract": {
      "type": ["string", "null"],
      "description": "เลขที่สัญญาฉบับเดิมที่ถูกแทนที่ (มีเฉพาะสัญญาต่ออายุ — null สำหรับสัญญาแรก)"
    },
    "contract_status": {
      "type": "string",
      "enum": ["ACTIVE", "EXPIRED", "TERMINATED", "DRAFT", "UNDER_REVIEW", "APPROVED", "SIGNED", "REJECTED"],
      "description": "สถานะปัจจุบันของสัญญา"
    },

    "parties": {
      "type": "object",
      "properties": {
        "service_provider": {
          "type": "object",
          "properties": {
            "company_name": { "type": "string" },
            "registration_no": { "type": "string" },
            "contact_person": { "type": "string" },
            "email": { "type": "string" },
            "tel": { "type": "string" }
          },
          "required": ["company_name", "registration_no"]
        },
        "client": {
          "type": "object",
          "properties": {
            "company_name": { "type": "string" },
            "registration_no": { "type": "string" },
            "contact_person": { "type": "string" },
            "email": { "type": "string" },
            "tel": { "type": "string" }
          },
          "required": ["company_name", "registration_no"]
        }
      },
      "required": ["service_provider", "client"]
    },

    "contract_period": {
      "type": "object",
      "description": "ระยะเวลาสัญญา — ใช้ effective_date/expiry_date สำหรับสัญญาที่ลงนามแล้ว หรือ proposed_* สำหรับฉบับร่าง",
      "properties": {
        "effective_date": { "type": ["string", "null"], "format": "date" },
        "expiry_date": { "type": ["string", "null"], "format": "date" },
        "proposed_effective_date": { "type": ["string", "null"], "format": "date" },
        "proposed_expiry_date": { "type": ["string", "null"], "format": "date" },
        "duration_months": { "type": "integer" }
      }
    },

    "financial_terms": {
      "type": "object",
      "description": "เงื่อนไขทางการเงิน — monthly_fee_thb ใช้สำหรับสัญญาที่ราคาคงที่ตลอด, monthly_fee_year1/2/3 ใช้สำหรับสัญญาที่ราคาขยับรายปี",
      "properties": {
        "monthly_fee_thb": {
          "type": ["number", "null"],
          "description": "ค่าบริการรายเดือนคงที่ (สำหรับสัญญาที่ราคาไม่เปลี่ยนแปลงตลอดอายุ)"
        },
        "monthly_fee_year1_thb": { "type": ["number", "null"], "description": "ค่าบริการรายเดือน ปีที่ 1" },
        "monthly_fee_year2_thb": { "type": ["number", "null"], "description": "ค่าบริการรายเดือน ปีที่ 2" },
        "monthly_fee_year3_thb": { "type": ["number", "null"], "description": "ค่าบริการรายเดือน ปีที่ 3" },
        "total_contract_value_thb": { "type": "number", "description": "มูลค่าสัญญารวมตลอดอายุ (บาท)" },
        "one_time_setup_fee_thb": { "type": ["number", "null"], "description": "ค่าธรรมเนียมแรกเข้าหรือ setup fee (ถ้ามี)" },
        "payment_terms_days": { "type": "integer", "description": "ระยะเวลาชำระเงิน (วัน) นับจากวันที่ออกใบแจ้งหนี้" },
        "late_payment_penalty_percent": { "type": "number", "description": "อัตราดอกเบี้ยปรับชำระล่าช้า (% ต่อเดือน)" },
        "price_escalation_clause": { "type": ["string", "null"], "description": "เงื่อนไขการปรับราคา (รูปแบบข้อความ)" },
        "price_escalation_year2_percent": { "type": ["number", "null"], "description": "อัตราปรับราคาปีที่ 2 (%)" },
        "price_escalation_year3_percent": { "type": ["number", "null"], "description": "อัตราปรับราคาปีที่ 3 (%)" },
        "vat_included": { "type": "boolean", "description": "ราคารวม VAT แล้วหรือไม่" }
      },
      "required": ["total_contract_value_thb", "payment_terms_days", "late_payment_penalty_percent"]
    },

    "scope_of_services": {
      "type": "array",
      "description": "รายการบริการที่ครอบคลุมในสัญญา",
      "items": {
        "type": "object",
        "properties": {
          "service_name": { "type": "string", "description": "ชื่อบริการ" },
          "coverage_hours": { "type": "string", "description": "ชั่วโมงให้บริการ เช่น 24/7 หรือ Mon-Fri 08:00-18:00" },
          "sla_p1_response": { "type": "string", "description": "เวลาตอบสนอง Priority 1" },
          "sla_p2_response": { "type": "string", "description": "เวลาตอบสนอง Priority 2" },
          "change_vs_previous": {
            "type": ["string", "null"],
            "enum": ["NEW", "ENHANCED", "UPGRADED", "UNCHANGED", "REMOVED", null],
            "description": "การเปลี่ยนแปลงเทียบกับสัญญาฉบับก่อนหน้า (null หากเป็นสัญญาแรก)"
          }
        },
        "required": ["service_name"]
      }
    },

    "sla_targets": {
      "type": "object",
      "description": "เป้าหมาย SLA หลักของสัญญา",
      "properties": {
        "network_uptime_percent": { "type": "number" },
        "helpdesk_p1_response_minutes": { "type": "integer" },
        "security_p1_response_minutes": { "type": "integer" },
        "cloud_availability_percent": { "type": ["number", "null"], "description": "SLA สำหรับ Cloud (null หากไม่มีบริการ Cloud)" },
        "monthly_report_delivery_day": { "type": "integer", "description": "วันที่ส่งรายงานประจำเดือน (วันที่ของเดือน)" },
        "penalty_cap_percent_of_monthly_fee": { "type": "number", "description": "เพดานสูงสุดของบทลงโทษ (% ของค่าบริการรายเดือน)" }
      }
    },

    "termination_conditions": {
      "type": "object",
      "description": "เงื่อนไขการยกเลิกและต่ออายุสัญญา",
      "properties": {
        "notice_period_days": { "type": "integer", "description": "ระยะเวลาแจ้งล่วงหน้าก่อนยกเลิก (วัน)" },
        "cure_period_days": { "type": "integer", "description": "ระยะเวลาแก้ไขข้อผิดพลาดก่อนยกเลิก (วัน)" },
        "auto_renewal": { "type": "boolean", "description": "มีการต่ออายุอัตโนมัติหรือไม่" },
        "auto_renewal_opt_out_days": { "type": ["integer", "null"], "description": "ต้องแจ้งล่วงหน้ากี่วันเพื่อยกเลิก auto-renewal (null หากไม่มี auto-renewal)" },
        "post_expiry_extension": { "type": "string", "description": "เงื่อนไขการต่ออายุชั่วคราวหลังหมดสัญญา" },
        "data_return_days": { "type": "integer", "description": "กำหนดคืนข้อมูลหลังสิ้นสุดสัญญา (วัน)" },
        "ip_ownership": { "type": "string", "description": "ผู้ถือกรรมสิทธิ์ใน IP/script ที่พัฒนาระหว่างสัญญา" },
        "non_compete_clause": { "type": "boolean", "description": "มี Non-Compete Clause หรือไม่" },
        "non_compete_duration_months": { "type": ["integer", "null"], "description": "ระยะเวลา Non-Compete หลังสิ้นสุดสัญญา (เดือน) — null หากไม่มี" }
      },
      "required": ["notice_period_days", "auto_renewal", "data_return_days"]
    },

    "liability_terms": {
      "type": "object",
      "description": "เงื่อนไขความรับผิดและการชดเชย (อาจไม่มีในสัญญาฉบับเก่า)",
      "properties": {
        "liability_cap_months_of_fee": { "type": "integer", "description": "เพดานความรับผิดสูงสุด (จำนวนเดือนของค่าบริการ)" },
        "consequential_damages_excluded": { "type": "boolean" },
        "cyber_insurance_required": { "type": "boolean", "description": "กำหนดให้ต้องมีประกันภัยไซเบอร์หรือไม่" },
        "cyber_insurance_coverage_thb": { "type": ["number", "null"], "description": "วงเงินประกันภัยไซเบอร์ขั้นต่ำ (บาท)" }
      }
    },

    "compliance_requirements": {
      "type": "array",
      "items": { "type": "string" },
      "description": "รายการมาตรฐานและกฎระเบียบที่ผู้ให้บริการต้องปฏิบัติตาม"
    },
    "audit_frequency": {
      "type": ["string", "null"],
      "enum": ["Monthly", "Quarterly", "Semi-Annual", "Annual", null],
      "description": "ความถี่ในการตรวจสอบ (null หากไม่ระบุในสัญญา)"
    },
    "nda_post_contract_years": {
      "type": ["integer", "null"],
      "description": "ระยะเวลา NDA หลังสิ้นสุดสัญญา (ปี)"
    },
    "governing_law": { "type": "string" },
    "dispute_resolution": { "type": "string" }
  },
  "required": [
    "contract_reference",
    "contract_status",
    "parties",
    "contract_period",
    "financial_terms",
    "scope_of_services",
    "sla_targets",
    "termination_conditions",
    "governing_law"
  ]
}
```

> **วิธีใช้งาน:** อัปโหลด Schema นี้ใน InsightDOC ครั้งเดียว แล้วเลือกใช้กับทั้ง Contract A และ Contract B
> AI จะ extract ออกมาในรูปแบบเดียวกัน ทำให้การเปรียบเทียบใน LLM Agent ทำได้ทันทีโดยไม่ต้องแปลงรูปแบบ

---

## 2. LLM Integration Configuration

### 2.1 System Prompt (Instructions Field)

```
คุณคือผู้เชี่ยวชาญด้านการวิเคราะห์สัญญาเชิงกฎหมายและเชิงพาณิชย์ โดยเฉพาะสัญญาบริการด้าน IT ภายใต้กฎหมายไทย
บทบาทของคุณคือการเปรียบเทียบสัญญา IT Managed Services สองฉบับอย่างครอบคลุมและละเอียดถี่ถ้วน:
- สัญญา A: สัญญาฉบับปัจจุบันที่กำลังหมดอายุ (เลขที่อ้างอิง: SNX-IT-2022-0047)
- สัญญา B: ข้อเสนอต่ออายุสัญญาฉบับใหม่ (เลขที่อ้างอิง: SNX-IT-2025-0012-R)

คุณต้องวิเคราะห์เอกสารทั้งสองอย่างแม่นยำ ระบุความแตกต่างที่มีนัยสำคัญทุกประเด็น ประเมินความเสี่ยงทางพาณิชย์
และส่งมอบรายงานการตรวจสอบที่พร้อมนำเสนอต่อผู้บริหาร ในรูปแบบ JSON ตามที่กำหนด

**ข้อกำหนดสำคัญ — ภาษาในการรายงาน:**
- **ต้องเขียนข้อความทั้งหมดในฟิลด์ที่เป็น string เป็นภาษาไทยเท่านั้น** ได้แก่ finding, recommendation, executive_summary,
  financial_risk_assessment, business_impact, summary, negotiation_priorities ทุกฟิลด์
- ชื่อ topic, label, clause ให้ใช้ภาษาไทย
- ค่าที่เป็น enum เช่น PASS/WARNING/FAIL, CRITICAL/HIGH/MEDIUM/LOW, APPROVE/REJECT ให้คงเป็นภาษาอังกฤษ
- ตัวเลข วันที่ และค่าตัวเลขทางการเงิน ให้คงรูปแบบเดิม

หลักการวิเคราะห์:
1. อ้างอิงข้อมูลจากเอกสารจริง — ระบุมาตราหรือตัวเลขที่เกี่ยวข้องเสมอ
2. ระบุทุก clause ที่เพิ่มความเสี่ยงให้ลูกค้า หรือลดความคุ้มครองเมื่อเทียบกับสัญญาเดิม
3. คำนวณผลกระทบทางการเงินเป็นตัวเลข (หน่วย: บาท) ทุกครั้งที่ทำได้
4. กำหนดระดับความเสี่ยง: CRITICAL, HIGH, MEDIUM, LOW
5. ระบุ "คำแนะนำการดำเนินการ" ที่ชัดเจนสำหรับทีมกฎหมายและจัดซื้อของลูกค้า
```

### 2.2 User Prompt

```
กรุณาดำเนินการวิเคราะห์และเปรียบเทียบสัญญาอย่างครอบคลุม ระหว่างสัญญา A (สัญญาฉบับปัจจุบันที่กำลังหมดอายุ)
และสัญญา B (ข้อเสนอต่ออายุสัญญา) โดยเอกสารทั้งสองฉบับได้แนบมาให้ตรวจสอบแล้ว

**กรุณาเขียนผลการวิเคราะห์ทั้งหมดเป็นภาษาไทย** เพื่อให้ผู้บริหารและทีมที่รับผิดชอบสามารถนำไปใช้งานได้ทันที

วิเคราะห์และเปรียบเทียบในประเด็นหลักดังต่อไปนี้:

**1. การวิเคราะห์ด้านการเงิน (FINANCIAL):**
- เปรียบเทียบมูลค่าสัญญารวม ค่าบริการรายเดือน และอัตราการปรับราคาของทั้งสองสัญญา
- คำนวณเปอร์เซ็นต์การเพิ่มขึ้นของค่าบริการจากสัญญา A ไปยังสัญญา B
- ระบุค่าธรรมเนียมใหม่ ค่าใช้จ่ายแบบ one-time หรือการเปลี่ยนแปลงเงื่อนไขการชำระเงิน
- ประเมินว่าราคาที่เพิ่มขึ้นนั้นสมเหตุสมผลกับขอบเขตบริการที่ขยายเพิ่มหรือไม่

**2. มาตรฐาน SLA และการประเมินผลงาน (SLA & PERFORMANCE):**
- เปรียบเทียบเป้าหมาย SLA ทั้งหมด (uptime, response time, การส่งรายงาน)
- ระบุ SLA ที่เข้มงวดขึ้นหรือผ่อนคลายลง และผลกระทบต่อบทลงโทษ
- เปรียบเทียบโครงสร้างบทลงโทษและเพดานสูงสุดของบทลงโทษ
- ระบุ SLA ที่ขาดหายไปหรือหมวดบริการใหม่ที่เพิ่มเข้ามา

**3. ขอบเขตการให้บริการ (SCOPE OF SERVICES):**
- ระบุบริการจากสัญญา A ที่ยังคงอยู่ในสัญญา B
- ระบุบริการใหม่ที่เพิ่มเข้ามาในสัญญา B
- ระบุบริการที่ได้รับการยกระดับหรือเปลี่ยนแปลงขอบเขต
- ระบุบริการที่ถูกลดระดับหรือตัดออก (ถ้ามี)

**4. ความเสี่ยงด้านการยกเลิกและต่ออายุสัญญา (TERMINATION & RENEWAL RISK):**
- เปรียบเทียบระยะเวลาแจ้งล่วงหน้าในการยกเลิกและระยะเวลาแก้ไขข้อผิดพลาด
- **ประเด็นวิกฤต:** ระบุและวิเคราะห์ผลกระทบของ Auto-Renewal Clause ในสัญญา B ซึ่งไม่มีในสัญญา A
- เปรียบเทียบเงื่อนไขการต่ออายุชั่วคราวหลังหมดสัญญา
- วิเคราะห์ Non-Compete Clause ใหม่และผลกระทบต่อธุรกิจ

**5. ความรับผิดและการคุ้มครองทางกฎหมาย (LIABILITY & LEGAL PROTECTION):**
- เปรียบเทียบเพดานความรับผิด (จำนวนเดือนของค่าบริการ)
- ระบุการเปลี่ยนแปลงในเงื่อนไขการชดเชย (indemnification)
- ระบุข้อกำหนดประกันภัยไซเบอร์ใหม่และผลกระทบ
- ประเมินการเปลี่ยนแปลงระยะเวลา NDA

**6. การปฏิบัติตามมาตรฐานและการกำกับดูแล (COMPLIANCE & GOVERNANCE):**
- เปรียบเทียบมาตรฐานที่กำหนด (เวอร์ชัน ISO, ความถี่ในการตรวจสอบ)
- ระบุมาตรฐานที่ได้รับการอัปเกรด เช่น ISO 27001:2013 → ISO 27001:2022
- เปรียบเทียบความถี่การ audit และกรอบเวลาการรายงาน

**7. การประเมินความเสี่ยงโดยรวม (OVERALL RISK ASSESSMENT):**
จัดทำ risk matrix สรุปพร้อมสถานะ PASS/WARNING/FAIL สำหรับแต่ละด้าน
ระบุคำแนะนำโดยรวม (APPROVE / APPROVE_WITH_CONDITIONS / REJECT)
และรายการประเด็นการเจรจาต่อรองที่จัดลำดับความสำคัญแล้ว ซึ่งลูกค้าควรดำเนินการก่อนลงนาม
```

### 2.3 Output Format Prompt

```json
{
  "report_title": "string — ชื่อรายงาน เช่น 'รายงานวิเคราะห์เปรียบเทียบสัญญาต่ออายุบริการ IT — Siam Nexus'",
  "analysis_date": "string — วันที่วิเคราะห์ในรูปแบบ ISO date",
  "documents_analyzed": [
    {
      "label": "string — ชื่อเอกสาร เช่น 'สัญญา A (ฉบับปัจจุบัน — กำลังหมดอายุ)'",
      "reference": "string — เลขที่อ้างอิงสัญญา",
      "status": "string — สถานะเอกสาร เช่น 'ACTIVE — ใกล้หมดอายุ'"
    }
  ],
  "executive_summary": "string — สรุปภาพรวมสำหรับผู้บริหาร 3-4 ประโยค พร้อมคำแนะนำโดยรวม (ภาษาไทย)",
  "overall_recommendation": "APPROVE | APPROVE_WITH_CONDITIONS | REJECT",
  "overall_status": "PASS | WARNING | FAIL",
  "validation_items": [
    {
      "item_id": "string — รหัสประเด็น เช่น 'FIN-001'",
      "category": "FINANCIAL | SLA | SCOPE | TERMINATION | LIABILITY | COMPLIANCE",
      "topic": "string — ชื่อประเด็นสั้นๆ เป็นภาษาไทย เช่น 'มูลค่าสัญญารวม'",
      "contract_a_value": "string — ค่า/ข้อกำหนดจากสัญญา A (ภาษาไทย)",
      "contract_b_value": "string — ค่า/ข้อกำหนดจากสัญญา B (ภาษาไทย)",
      "change": "INCREASE | DECREASE | NEW | REMOVED | UNCHANGED | TIGHTENED | RELAXED",
      "risk_level": "CRITICAL | HIGH | MEDIUM | LOW",
      "status": "PASS | WARNING | FAIL",
      "finding": "string — รายละเอียดผลการตรวจสอบ พร้อมอ้างอิงตัวเลขหรือมาตรา (ภาษาไทย)",
      "recommendation": "string — คำแนะนำเฉพาะเจาะจงสำหรับทีมกฎหมาย/จัดซื้อ (ภาษาไทย)"
    }
  ],
  "financial_summary": {
    "contract_a_total_value_thb": "number — มูลค่าสัญญา A รวม (บาท)",
    "contract_b_total_value_thb": "number — มูลค่าสัญญา B รวม (บาท)",
    "value_increase_thb": "number — ส่วนต่างมูลค่า (บาท)",
    "value_increase_percent": "number — เปอร์เซ็นต์เพิ่มขึ้น",
    "contract_b_monthly_fee_year1": "number — ค่าบริการรายเดือนปีที่ 1 ของสัญญา B (บาท)",
    "fee_increase_from_a_percent": "number — เปอร์เซ็นต์ค่าบริการรายเดือนที่เพิ่มขึ้นจากสัญญา A",
    "one_time_costs_thb": "number — ค่าใช้จ่ายแบบ one-time (บาท)",
    "financial_risk_assessment": "string — การประเมินความเสี่ยงทางการเงินโดยรวม (ภาษาไทย)"
  },
  "risk_matrix": [
    {
      "area": "string — ชื่อด้านที่ประเมิน เช่น 'การเงิน', 'SLA', 'เงื่อนไขการยกเลิก'",
      "status": "PASS | WARNING | FAIL",
      "risk_level": "CRITICAL | HIGH | MEDIUM | LOW",
      "summary": "string — สรุปสั้นๆ ของผลการประเมินด้านนี้ (ภาษาไทย)"
    }
  ],
  "negotiation_priorities": [
    {
      "priority": "integer — ลำดับความสำคัญ โดย 1 = สำคัญที่สุด",
      "clause": "string — ชื่อข้อกำหนดที่ควรเจรจา (ภาษาไทย)",
      "current_proposal": "string — เนื้อหาปัจจุบันในสัญญา B (ภาษาไทย)",
      "recommended_position": "string — ท่าทีที่แนะนำสำหรับการเจรจา (ภาษาไทย)",
      "business_impact": "string — ผลกระทบทางธุรกิจถ้าไม่เจรจา (ภาษาไทย)"
    }
  ],
  "business_impact": "string — ย่อหน้าสรุปผลกระทบทางธุรกิจและการเงินโดยรวม หากลงนามสัญญา B ตามที่เสนอมา (ภาษาไทย)"
}
```

---

## 3. Demo Script — Presentation Guide

### 🎯 Use Case Title
**"InsightDOC: From 200 Pages of Legal Text to Executive Decision in 60 Seconds"**
*IT Service Contract Renewal Intelligence — Live Demo*

---

### Act 1 — The Problem (2 minutes)

> **[Show slide or blank screen — speak naturally]**

"ลองนึกภาพนี้ครับ — ทีม Procurement ของบริษัทกำลังเข้าสู่ช่วงต่ออายุสัญญา IT ที่มีมูลค่ากว่า 9 ล้านบาท
คุณมีสัญญาฉบับเก่า 30 หน้า และข้อเสนอฉบับใหม่อีก 35 หน้า
ทนายความบอกว่าใช้เวลาอย่างน้อย 2 วันในการเปรียบเทียบ
CFO ต้องการคำตอบภายในวันนี้
และทีม Legal กำลังโฟกัสอยู่กับ deal ใหญ่อีกชิ้น

**นี่คือปัญหาจริงที่ทุกองค์กรเจอ** — contract review ใช้เวลานาน มีความเสี่ยงในการมองข้ามรายละเอียดสำคัญ
และมักจะตกอยู่ในมือคนเพียงไม่กี่คน

**วันนี้ผมจะแสดงให้เห็นว่า InsightDOC แก้ปัญหานี้ได้อย่างไร — ในเวลาไม่ถึง 60 วินาที**"

---

### Act 2 — Setup & Context (1 minute)

> **[Open InsightDOC — navigate to Jobs]**

"สถานการณ์ที่เราจะ demo วันนี้คือ บริษัท Siam Nexus Co., Ltd.
กำลังพิจารณาต่ออายุสัญญา IT Managed Services กับ DataSphere Systems
เรามีเอกสาร 2 ฉบับ:

- **Contract A** — สัญญาฉบับเดิมที่กำลังหมดอายุ มูลค่า 6.72 ล้านบาท
- **Contract B** — ข้อเสนอต่ออายุฉบับใหม่ มูลค่า 9.09 ล้านบาท

คำถามของทีม Procurement คือ: *ราคาที่เพิ่มขึ้น 32% นั้นสมเหตุสมผลไหม? มีความเสี่ยงอะไรซ่อนอยู่บ้าง?*

ปกติ ต้องใช้ทนายความ 2 วัน ตอนนี้เราจะทำใน 60 วินาที"

---

### Act 3 — Live Demo (5–7 minutes)

> **[Step 1: Create new job]**

"เริ่มต้นด้วยการสร้าง Job ใหม่ — ผมตั้งชื่อว่า 'IT Contract Renewal Review — Siam Nexus 2025'
แล้ว upload ทั้งสองไฟล์พร้อมกัน — Contract A และ Contract B"

> **[Upload both PDFs]**

"InsightDOC รับไฟล์ PDF ต้นฉบับ ไม่จำเป็นต้องแปลงไฟล์ก่อน
ระบบจะทำ OCR และ extract ข้อมูลโดยอัตโนมัติ"

> **[Show extraction running → completed]**

"ภายใน 15–20 วินาที ข้อมูลถูก extract ออกมาครบทั้ง 2 ฉบับ
ตอนนี้เราได้ข้อมูลที่ structured แล้ว พร้อมส่งให้ AI วิเคราะห์"

> **[Navigate to Integrations — select LLM Agent: Contract Comparison Analyzer]**

"ขั้นตอนต่อไป เราส่งข้อมูลทั้งสองไปให้ AI Agent ที่เราตั้งค่าไว้สำหรับ contract comparison
Agent นี้มี prompt ที่ออกแบบมาโดยเฉพาะ ให้วิเคราะห์ใน 6 มิติหลัก:
การเงิน, SLA, ขอบเขตบริการ, เงื่อนไขยกเลิก, ความรับผิด, และ compliance"

> **[Click 'Send to Agent' — show streaming response]**

"นี่คือจุดที่ InsightDOC โดดเด่น — AI ไม่ได้แค่ summarize
แต่ทำการ **cross-document analysis** เปรียบเทียบ clause-by-clause พร้อม risk assessment"

> **[Wait for completion — show result modal]**

"เสร็จแล้ว — ขอให้ดูผลลัพธ์ที่ได้..."

> **[Highlight key findings in the result]**

**ชี้ประเด็นสำคัญ 5 ข้อ:**

"ประเด็นแรก — **ค่าบริการเพิ่มขึ้น 32%** จาก 6.72 ล้านเป็น 9.09 ล้านบาท
แต่มี new services เพิ่มมา 2 รายการ คือ Cloud Management และ IT Asset Management
AI บอกว่าระดับความเสี่ยง MEDIUM — ราคาขึ้นพอสมเหตุสมผล แต่ควร negotiate

ประเด็นที่สอง — **Auto-Renewal Clause** — นี่คือ CRITICAL RISK
Contract B มี auto-renewal อัตโนมัติ 12 เดือน ถ้าไม่แจ้งยกเลิกล่วงหน้า 120 วัน
Contract A ไม่มี clause นี้เลย ถ้าไม่รู้ อาจถูกผูกสัญญาโดยไม่ตั้งใจ

ประเด็นที่สาม — **Liability Cap ลดลง** จาก 6 เดือน เหลือ 3 เดือน
นั่นหมายความว่าถ้าเกิดความเสียหายร้ายแรง Client ได้รับการชดเชยน้อยลงครึ่งหนึ่ง — HIGH RISK

ประเด็นที่สี่ — **SLA ดีขึ้น** Network uptime จาก 99.5% เป็น 99.9%
Security response จาก 15 นาที เป็น 10 นาที — นี่คือ PASS

ประเด็นที่ห้า — **Non-Compete Clause ใหม่** — Service Provider
ห้ามให้บริการคู่แข่งโดยตรงเป็นเวลา 12 เดือนหลังสัญญาสิ้นสุด"

---

### Act 4 — Export & Action (1 minute)

> **[Click Export Docs or Export PDF]**

"ผลการวิเคราะห์นี้ export ได้ทันที เป็น Word หรือ PDF
พร้อมส่งให้ Legal Team, CFO, หรือ Board ได้เลย
ไม่ต้องพิมพ์ใหม่ ไม่ต้องสรุปเอง"

> **[Show the exported document briefly]**

"สิ่งที่ใช้เวลา 2 วันของทนายความ — InsightDOC ทำได้ใน 60 วินาที
และ output มีโครงสร้างที่ชัดเจน พร้อม negotiation priorities ที่ prioritize แล้ว"

---

### Act 5 — Closing (1 minute)

"สรุปคุณค่าของ InsightDOC ใน Use Case นี้:

✅ **Speed** — จาก 2 วัน เหลือ 60 วินาที
✅ **Accuracy** — ไม่มี human error ในการเปรียบเทียบ clause-by-clause
✅ **Risk Detection** — ค้นพบ CRITICAL risk (auto-renewal) ที่มักถูกมองข้าม
✅ **Actionable Output** — negotiation priorities พร้อมใช้
✅ **Cost Saving** — ลดค่าทนายความในขั้นตอน initial review

InsightDOC ไม่ได้แทนที่ทนายความ — แต่ช่วยให้ทนายความ
**โฟกัสเวลาและความเชี่ยวชาญไปกับสิ่งที่สำคัญที่สุด**
แทนที่จะเสียเวลากับการอ่านเปรียบเทียบเบื้องต้น

**ถ้าองค์กรของคุณมีสัญญา 50 ฉบับต่อปี
InsightDOC ช่วยประหยัดเวลาได้กว่า 100 วันทำงาน"**

> **[Q&A]**

---

### 💡 Suggested Follow-Up Questions to Anticipate

| Question | Suggested Answer |
|----------|-----------------|
| ระบบรองรับสัญญาภาษาไทยได้ไหม? | ใช่ครับ รองรับทั้งภาษาไทยและอังกฤษ และ mixed-language documents |
| ถ้า PDF เป็นสแกนจากกระดาษจริงได้ไหม? | ได้ครับ มี OCR engine รองรับสแกน รวมถึงเอกสารคุณภาพต่ำ |
| ข้อมูลสัญญาปลอดภัยไหม? | ระบบ deploy on-premise ได้ ข้อมูลไม่ออกนอกองค์กร |
| customize prompt ให้เหมาะกับ use case เฉพาะได้ไหม? | ได้ครับ LLM Integration ออกแบบมาให้ปรับ prompt ได้อย่างอิสระ |
| เชื่อมกับระบบ contract management อื่นได้ไหม? | มี API และ Workflow Integration สำหรับเชื่อมกับระบบภายนอก |

---

*Demo prepared for InsightDOC — AI Document Intelligence Platform*
*Use Case: Legal & Procurement — IT Contract Renewal Comparison*
