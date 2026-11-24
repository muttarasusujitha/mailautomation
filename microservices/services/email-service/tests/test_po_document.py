from app.agents.po_document import _extract_fields


def _po(text=""):
    return _extract_fields(f"""PURCHASE ORDER
PO Number: PO-2026-041
Date: 12-01-2026
Buyer: Acme Learning Pvt Ltd
Supplier: Clahan Technologies Private Limited
Subtotal: INR 100,000
GST Rate: 18%
Grand Total: INR 118,000
{text}
""")


def test_complete_final_inr_po_is_eligible_and_uses_pre_tax_amount():
    fields = _po()
    assert fields["auto_processing_eligible"] is True
    assert fields["review_required"] is False
    assert fields["total_amount"] == 100000
    assert fields["po_face_total"] == 118000
    assert fields["amount_basis"] == "pre_tax"


def test_draft_or_placeholder_po_stays_in_review():
    fields = _extract_fields("""DRAFT PURCHASE ORDER - FOR REVIEW\nPO Number: XXXX\nDate: 12-01-2026\nBuyer: Acme Learning Pvt Ltd\nSupplier: Clahan Technologies Private Limited\nSubtotal: INR 100,000\nGST Rate: 18%\nGrand Total: INR 118,000\n""")
    assert fields["auto_processing_eligible"] is False
    assert fields["draft_document"] is True
    assert fields["placeholder_fields"] == ["po_number"]


def test_ambiguous_tax_basis_stays_in_review():
    fields = _extract_fields("""PURCHASE ORDER
PO Number: PO-2026-042
Date: 12-01-2026
Buyer: Acme Learning Pvt Ltd
Supplier: Clahan Technologies Private Limited
Total Amount: INR 118,000
""")
    assert fields["auto_processing_eligible"] is False
    assert fields["amount_basis"] == "unknown"
    assert any("tax basis" in blocker for blocker in fields["auto_processing_blockers"])


def test_foreign_currency_po_stays_in_review():
    fields = _extract_fields("""PURCHASE ORDER
PO Number: PO-2026-043
Date: 12-01-2026
Buyer: Acme Learning Pvt Ltd
Supplier: Clahan Technologies Private Limited
Subtotal: USD 1,000
GST Rate: 18%
Grand Total: USD 1,180
""")
    assert fields["auto_processing_eligible"] is False
    assert fields["currency"] == ""
