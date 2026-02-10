from sqlalchemy.orm import Session
from app.models.template import SchemaTemplate
import uuid


def init_system_templates(db: Session) -> None:
    """
    Initialize system templates if they don't exist.
    Called on application startup.
    """

    # Check if system templates already exist
    existing = db.query(SchemaTemplate).filter(
        SchemaTemplate.is_system_template == True
    ).first()

    if existing:
        print("System templates already exist")
        return

    # Template 1: Standard Invoice
    invoice_template = SchemaTemplate(
        id=uuid.uuid4(),
        name="Standard Invoice",
        description="Template for processing standard business invoices with common fields",
        document_type="invoice",
        category="financial",
        is_system_template=True,
        thumbnail_url=None,
        usage_count=0,
        created_by=None,
        is_active=True,
        fields=[
            {
                "name": "invoice_number",
                "type": "text",
                "description": "The unique invoice identifier or number",
                "required": True,
                "validation_rules": {},
                "help_text": "Unique identifier for this invoice",
                "example": "INV-2024-001",
                "order": 1
            },
            {
                "name": "invoice_date",
                "type": "date",
                "description": "The date when the invoice was issued (format: YYYY-MM-DD)",
                "required": True,
                "validation_rules": {"format": "YYYY-MM-DD"},
                "help_text": "Date the invoice was created",
                "example": "2024-12-03",
                "order": 2
            },
            {
                "name": "due_date",
                "type": "date",
                "description": "The payment due date (format: YYYY-MM-DD)",
                "required": False,
                "validation_rules": {"format": "YYYY-MM-DD"},
                "help_text": "When payment is due",
                "example": "2024-12-17",
                "order": 3
            },
            {
                "name": "vendor_name",
                "type": "text",
                "description": "The name of the vendor or supplier",
                "required": True,
                "validation_rules": {},
                "help_text": "Company or person issuing the invoice",
                "example": "ABC Corporation",
                "order": 4
            },
            {
                "name": "vendor_address",
                "type": "text",
                "description": "The vendor's business address",
                "required": False,
                "validation_rules": {},
                "help_text": "Full address of the vendor",
                "example": "123 Main St, Bangkok, Thailand",
                "order": 5
            },
            {
                "name": "total_amount",
                "type": "currency",
                "description": "The total amount including all taxes and fees",
                "required": True,
                "validation_rules": {"min": 0},
                "help_text": "Final total to be paid",
                "example": "1,234.56",
                "order": 6
            },
            {
                "name": "tax_amount",
                "type": "currency",
                "description": "The VAT or tax amount",
                "required": False,
                "validation_rules": {"min": 0},
                "help_text": "Tax or VAT charged",
                "example": "123.45",
                "order": 7
            },
            {
                "name": "subtotal",
                "type": "currency",
                "description": "The subtotal before taxes",
                "required": False,
                "validation_rules": {"min": 0},
                "help_text": "Amount before tax",
                "example": "1,111.11",
                "order": 8
            },
            {
                "name": "payment_terms",
                "type": "text",
                "description": "Payment terms or conditions",
                "required": False,
                "validation_rules": {},
                "help_text": "Payment conditions (e.g., Net 30)",
                "example": "Net 30 days",
                "order": 9
            }
        ]
    )

    # Template 2: Receipt
    receipt_template = SchemaTemplate(
        id=uuid.uuid4(),
        name="Receipt",
        description="Template for processing receipts and payment confirmations",
        document_type="receipt",
        category="financial",
        is_system_template=True,
        thumbnail_url=None,
        usage_count=0,
        created_by=None,
        is_active=True,
        fields=[
            {
                "name": "receipt_number",
                "type": "text",
                "description": "The unique receipt identifier or number",
                "required": True,
                "validation_rules": {},
                "help_text": "Unique receipt ID",
                "example": "REC-2024-001",
                "order": 1
            },
            {
                "name": "date",
                "type": "date",
                "description": "The date of purchase or transaction (format: YYYY-MM-DD)",
                "required": True,
                "validation_rules": {"format": "YYYY-MM-DD"},
                "help_text": "Transaction date",
                "example": "2024-12-03",
                "order": 2
            },
            {
                "name": "merchant_name",
                "type": "text",
                "description": "The name of the store or merchant",
                "required": True,
                "validation_rules": {},
                "help_text": "Store or business name",
                "example": "ABC Store",
                "order": 3
            },
            {
                "name": "merchant_address",
                "type": "text",
                "description": "The merchant's business address",
                "required": False,
                "validation_rules": {},
                "help_text": "Store location",
                "example": "456 Shopping St, Bangkok",
                "order": 4
            },
            {
                "name": "total_amount",
                "type": "currency",
                "description": "The total amount paid",
                "required": True,
                "validation_rules": {"min": 0},
                "help_text": "Total paid",
                "example": "567.89",
                "order": 5
            },
            {
                "name": "payment_method",
                "type": "text",
                "description": "The method of payment used (cash, credit card, etc.)",
                "required": False,
                "validation_rules": {},
                "help_text": "How payment was made",
                "example": "Credit Card",
                "order": 6
            },
            {
                "name": "tax_amount",
                "type": "currency",
                "description": "The VAT or tax amount if applicable",
                "required": False,
                "validation_rules": {"min": 0},
                "help_text": "Tax included in total",
                "example": "56.78",
                "order": 7
            }
        ]
    )

    # Template 3: Purchase Order
    po_template = SchemaTemplate(
        id=uuid.uuid4(),
        name="Purchase Order",
        description="Template for processing purchase orders from procurement",
        document_type="po",
        category="procurement",
        is_system_template=True,
        thumbnail_url=None,
        usage_count=0,
        created_by=None,
        is_active=True,
        fields=[
            {
                "name": "po_number",
                "type": "text",
                "description": "The unique purchase order number",
                "required": True,
                "validation_rules": {},
                "help_text": "Unique PO identifier",
                "example": "PO-2024-001",
                "order": 1
            },
            {
                "name": "po_date",
                "type": "date",
                "description": "The date the purchase order was created (format: YYYY-MM-DD)",
                "required": True,
                "validation_rules": {"format": "YYYY-MM-DD"},
                "help_text": "PO creation date",
                "example": "2024-12-03",
                "order": 2
            },
            {
                "name": "vendor_name",
                "type": "text",
                "description": "The name of the supplier or vendor",
                "required": True,
                "validation_rules": {},
                "help_text": "Supplier name",
                "example": "XYZ Supplies Inc",
                "order": 3
            },
            {
                "name": "delivery_address",
                "type": "text",
                "description": "The address where goods should be delivered",
                "required": False,
                "validation_rules": {},
                "help_text": "Delivery location",
                "example": "789 Warehouse Rd, Bangkok",
                "order": 4
            },
            {
                "name": "total_amount",
                "type": "currency",
                "description": "The total order amount",
                "required": True,
                "validation_rules": {"min": 0},
                "help_text": "Total PO value",
                "example": "10,000.00",
                "order": 5
            },
            {
                "name": "requested_by",
                "type": "text",
                "description": "The name of the person requesting the purchase",
                "required": False,
                "validation_rules": {},
                "help_text": "Requester name",
                "example": "John Doe",
                "order": 6
            },
            {
                "name": "approved_by",
                "type": "text",
                "description": "The name of the person who approved the purchase",
                "required": False,
                "validation_rules": {},
                "help_text": "Approver name",
                "example": "Jane Smith",
                "order": 7
            },
            {
                "name": "delivery_date",
                "type": "date",
                "description": "The requested or expected delivery date (format: YYYY-MM-DD)",
                "required": False,
                "validation_rules": {"format": "YYYY-MM-DD"},
                "help_text": "When delivery is expected",
                "example": "2024-12-10",
                "order": 8
            },
            {
                "name": "notes",
                "type": "text",
                "description": "Any additional notes or special instructions",
                "required": False,
                "validation_rules": {},
                "help_text": "Special instructions",
                "example": "Fragile items - handle with care",
                "order": 9
            }
        ]
    )

    # Template 4: Contract
    contract_template = SchemaTemplate(
        id=uuid.uuid4(),
        name="Contract",
        description="Template for processing business contracts and agreements",
        document_type="contract",
        category="legal",
        is_system_template=True,
        thumbnail_url=None,
        usage_count=0,
        created_by=None,
        is_active=True,
        fields=[
            {
                "name": "contract_number",
                "type": "text",
                "description": "The unique contract identifier or reference number",
                "required": True,
                "validation_rules": {},
                "help_text": "Unique contract ID",
                "example": "CONT-2024-001",
                "order": 1
            },
            {
                "name": "contract_date",
                "type": "date",
                "description": "The date when the contract was signed (format: YYYY-MM-DD)",
                "required": True,
                "validation_rules": {"format": "YYYY-MM-DD"},
                "help_text": "Signing date",
                "example": "2024-12-03",
                "order": 2
            },
            {
                "name": "party_a",
                "type": "text",
                "description": "The name of the first party",
                "required": True,
                "validation_rules": {},
                "help_text": "First contracting party",
                "example": "ABC Corporation",
                "order": 3
            },
            {
                "name": "party_b",
                "type": "text",
                "description": "The name of the second party",
                "required": True,
                "validation_rules": {},
                "help_text": "Second contracting party",
                "example": "XYZ Company Ltd",
                "order": 4
            },
            {
                "name": "start_date",
                "type": "date",
                "description": "The contract start date (format: YYYY-MM-DD)",
                "required": False,
                "validation_rules": {"format": "YYYY-MM-DD"},
                "help_text": "When contract begins",
                "example": "2024-12-01",
                "order": 5
            },
            {
                "name": "end_date",
                "type": "date",
                "description": "The contract end or expiration date (format: YYYY-MM-DD)",
                "required": False,
                "validation_rules": {"format": "YYYY-MM-DD"},
                "help_text": "When contract expires",
                "example": "2025-11-30",
                "order": 6
            },
            {
                "name": "contract_value",
                "type": "currency",
                "description": "The total value of the contract",
                "required": False,
                "validation_rules": {"min": 0},
                "help_text": "Contract monetary value",
                "example": "50,000.00",
                "order": 7
            },
            {
                "name": "terms",
                "type": "text",
                "description": "Key terms and conditions of the contract",
                "required": False,
                "validation_rules": {},
                "help_text": "Main contract terms",
                "example": "Monthly payments, 30-day notice period",
                "order": 8
            },
            {
                "name": "renewal_clause",
                "type": "text",
                "description": "Information about contract renewal terms",
                "required": False,
                "validation_rules": {},
                "help_text": "Renewal conditions",
                "example": "Auto-renew annually unless terminated",
                "order": 9
            }
        ]
    )

    # Add all templates to database
    db.add(invoice_template)
    db.add(receipt_template)
    db.add(po_template)
    db.add(contract_template)

    db.commit()
    print("System templates created successfully")


if __name__ == "__main__":
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        init_system_templates(db)
    finally:
        db.close()
