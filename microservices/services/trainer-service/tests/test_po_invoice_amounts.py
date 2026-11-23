import asyncio

from app.routes.purchase_orders import InvoiceGenerateRequest, generate_invoice_from_po
from app.routes.invoices import LabInvoiceRequest, generate_lab_invoice
from shared.document_amounts import offline_expense_items


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


def test_saved_invoice_recomputes_stale_amount_and_inherits_zero_tax():
    db = {'purchase_orders': _Collection({'po_id': 'PO-2', 'gst_rate': 0,
          'items': [{'description': 'Training', 'quantity': 3, 'rate': 100, 'amount': 9000}]}),
          'invoices': _Collection(), 'requirements': _Collection()}
    result = asyncio.run(generate_invoice_from_po('PO-2', InvoiceGenerateRequest(), db))
    saved = db['invoices'].inserted[0]
    assert result['invoice']['commercials']['grand_total'] == 300
    assert saved['items'][0]['amount'] == 300
    assert saved['gst_rate'] == 0


def test_po_persists_calculated_total_not_submitted_total():
    from app.routes.purchase_orders import generate_purchase_order, POGenerateRequest
    db = {'requirements': _Collection({'requirement_id': 'REQ-1'}),
          'trainers': _Collection({'trainer_id': 'T-1', 'name': 'Trainer'}),
          'purchase_orders': _Collection()}
    payload = POGenerateRequest(requirement_id='REQ-1', trainer_id='T-1', gst_rate=0,
        total_amount=9000, items=[{'description': 'Training', 'quantity': 2, 'rate': 100, 'amount': 9000}])
    result = asyncio.run(generate_purchase_order(payload, db))
    assert result['purchase_order']['total_amount'] == 200
    assert db['purchase_orders'].inserted[0]['items'][0]['amount'] == 200


def test_offline_invoice_items_include_only_clahan_arranged_costs():
    items = offline_expense_items({
        'offline_logistics': {
            'owners': {'travel': 'clahan', 'accommodation': 'client', 'food': 'needs_review'},
            'actual_expenses': {'travel': 8000, 'accommodation': 6000, 'food': 900},
        },
    })
    assert items == [{
        'description': 'Offline travel expense', 'quantity': 1,
        'rate': 8000.0, 'amount': 8000.0,
    }]


class _Invoices(_Collection):
    async def insert_one(self, document):
        self.document = document


def test_lab_invoice_is_a_separate_client_invoice():
    invoices = _Invoices()
    db = {
        'lab_cost_requests': _Collection({
            'requirement_id': 'LAB-1', 'client_name': 'Acme',
            'client_email': 'client@example.com', 'technology_needed': 'DevOps',
        }),
        'requirements': _Collection(),
        'invoices': invoices,
    }
    result = asyncio.run(generate_lab_invoice(
        'LAB-1', LabInvoiceRequest(lab_amount=7000, gst_rate=18), db,
    ))
    invoice = result['invoice']
    assert invoice['invoice_kind'] == 'lab'
    assert invoice['lab_requirement_id'] == 'LAB-1'
    assert invoice['total_amount'] == 7000
    assert invoice['balance_due'] == 8260
