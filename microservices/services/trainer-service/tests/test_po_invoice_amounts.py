import asyncio

from app.routes.purchase_orders import InvoiceGenerateRequest, generate_invoice_from_po


class _Collection:
    def __init__(self, document=None):
        self.document = document
        self.inserted = []

    async def find_one(self, *args, **kwargs):
        return self.document

    async def insert_one(self, document):
        self.inserted.append(document)

    async def update_one(self, *args, **kwargs):
        return None


def test_invoice_uses_day_rate_and_duration_when_the_total_is_blank():
    db = {
        "purchase_orders": _Collection({
            "po_id": "PO-1",
            "requirement_id": "REQ-1",
            "duration": "2.5",
            "day_rate": 10000,
            "training_domain": "Python",
            "items": [],
            "total_amount": 0,
            "company_name": "BEULIX SOLUTIONS PRIVATE LIMITED",
            "company_pan": "TESTP1234Z",
            "company_gst": "29TESTP1234Z1Z5",
            "bank_account_no": "000111222333",
            "bank_ifsc": "TEST0001234",
            "company_address": "Hyderabad",
        }),
        "invoices": _Collection(),
        "requirements": _Collection(),
    }

    result = asyncio.run(generate_invoice_from_po("PO-1", InvoiceGenerateRequest(gst_rate=18), db))
    invoice = result["invoice"]

    assert invoice["total_amount"] == 25000
    assert invoice["items"][0]["quantity"] == 2.5
    assert invoice["items"][0]["amount"] == 25000
    assert invoice["commercials"]["gst_amount"] == 4500
    assert invoice["commercials"]["grand_total"] == 29500
    assert invoice["balance_due"] == 29500
    assert invoice["company_pan"] == "TESTP1234Z"
    assert invoice["company_gst"] == "29TESTP1234Z1Z5"
    assert invoice["bank_account_no"] == "000111222333"
    assert invoice["bank_ifsc"] == "TEST0001234"
    assert invoice["company_name_full"] == "BEULIX SOLUTIONS PRIVATE LIMITED"
