"""Read client purchase order PDFs into reviewable, traceable fields."""
import base64
import io
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple


MAX_PO_PDF_BYTES = 12 * 1024 * 1024
MAX_PO_PDF_PAGES = 15


def _pdf_text(raw: bytes) -> Tuple[str, int, bool]:
    import fitz

    document = fitz.open(stream=raw, filetype="pdf")
    try:
        pages = list(document)[:MAX_PO_PDF_PAGES]
        text = "\n".join(page.get_text("text") or "" for page in pages).strip()
        used_ocr = False
        if len(re.sub(r"\s", "", text)) < 40:
            import pytesseract
            from PIL import Image

            scanned_pages = []
            for page in pages:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False)
                image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                scanned_pages.append(pytesseract.image_to_string(image) or "")
            text = "\n".join(scanned_pages).strip()
            used_ocr = True
        return text, len(document), used_ocr
    finally:
        document.close()


def _label_value(text: str, labels: Iterable[str], *, max_chars: int = 120) -> str:
    label = "|".join(labels)
    match = re.search(
        rf"(?im)^\s*(?:{label})\s*(?:number|no\.?|#|date)?\s*[:#\-]?\s*([^\r\n]{{1,{max_chars}}})",
        text,
    )
    if not match:
        return ""
    value = match.group(1).strip(" \t:#-|")
    value = re.split(r"\s{3,}", value)[0].strip()
    return value if value.lower() not in {"n/a", "na", "not applicable", "-"} else ""


def _first(patterns: Iterable[str], text: str, flags: int = re.IGNORECASE) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return (match.group(1) if match.lastindex else match.group(0)).strip(" \t:#-")
    return ""


def _extract_fields(text: str) -> Dict[str, Any]:
    normalized = re.sub(r"[\u00a0\t]+", " ", text)
    po_number = _first([
        r"\b(?:purchase\s*order|P\.?\s*O\.?)\s*(?:number|no\.?|#)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/_\-]{2,})",
        r"\bPO\s*[:#\-]\s*([A-Z0-9][A-Z0-9/_\-]{2,})",
    ], normalized)
    po_date = _first([
        r"\b(?:purchase\s*order\s*)?date\s*[:#\-]?\s*((?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})|(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2})|(?:\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}))",
    ], normalized)
    amount_match = re.search(
        r"(?im)^\s*(?:grand\s+total|total\s+(?:po\s+)?amount|total\s+value|order\s+value|po\s+value|net\s+payable|total)\s*[:\-]?\s*(?:INR|Rs\.?|₹)?\s*([0-9][0-9,]*(?:\.\d{1,2})?)",
        normalized,
    )
    amount = 0.0
    if amount_match:
        try:
            amount = float(amount_match.group(1).replace(",", ""))
        except ValueError:
            amount = 0.0
    gstin = _first([r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z])\b"], normalized)
    gst_rate = 0.0
    gst_match = re.search(r"(?i)\bGST(?:\s+rate)?\s*(?:@|:)?\s*(\d{1,2}(?:\.\d+)?)\s*%", normalized)
    if gst_match:
        gst_rate = float(gst_match.group(1))
    else:
        component_rates = [float(value) for value in re.findall(r"(?i)\b(?:CGST|SGST|IGST)\s*(?:@|:)?\s*(\d{1,2}(?:\.\d+)?)\s*%", normalized)]
        if component_rates:
            gst_rate = round(sum(component_rates) if len(component_rates) > 1 and not re.search(r"(?i)\bIGST\b", normalized) else max(component_rates), 2)
    payment_terms = _label_value(normalized, (r"payment\s+terms?", r"terms\s+of\s+payment", r"payment\s+due"), max_chars=180)
    client_name = _label_value(normalized, (r"buyer", r"bill\s+to", r"customer", r"client", r"invoice\s+to"), max_chars=140)
    vendor_name = _label_value(normalized, (r"supplier", r"vendor", r"seller", r"service\s+provider"), max_chars=140)
    billing_address = _label_value(normalized, (r"billing\s+address", r"bill\s+to\s+address", r"registered\s+address"), max_chars=220)
    training_dates = _label_value(normalized, (r"training\s+dates?", r"service\s+period", r"delivery\s+period", r"period\s+of\s+service"), max_chars=140)
    due_date = _label_value(normalized, (r"due\s+date", r"payment\s+due\s+date"), max_chars=80)
    description = _label_value(normalized, (r"description", r"scope\s+of\s+work", r"service\s+description", r"particulars"), max_chars=220)
    title = bool(re.search(r"\b(purchase\s+order|\bp\.?\s*o\.?\b|work\s+order)\b", normalized, re.I))
    fields = {
        "po_number": po_number,
        "po_date": po_date,
        "total_amount": amount or None,
        "gst_rate": gst_rate or None,
        "gstin": gstin,
        "payment_terms": payment_terms,
        "client_name": client_name,
        "vendor_name": vendor_name,
        "billing_address": billing_address,
        "training_dates": training_dates,
        "due_date": due_date,
        "description": description,
    }
    present = sum(value not in (None, "", 0) for value in fields.values())
    fields["document_detected"] = title
    fields["confidence"] = round(present / len(fields), 2)
    fields["review_required"] = True
    fields["missing_fields"] = [key for key, value in fields.items() if key in {
        "po_number", "po_date", "total_amount", "client_name", "vendor_name"
    } and value in (None, "", 0)]
    return _mark_auto_process_eligibility(normalized, fields)


def _mark_auto_process_eligibility(text: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Permit auto-invoicing only from a complete, final INR PO with a clear tax basis."""
    normalized = str(text or "")
    blockers = []
    lowered = normalized.lower()
    draft_markers = (
        "draft", "for review", "for authorization", "indicative", "unverified",
        "subject to approval", "subject to confirmation", "not approved", "not authorized",
    )
    draft_reasons = [marker for marker in draft_markers if marker in lowered]
    placeholder_fields = [
        key for key in ("po_number", "client_name", "vendor_name")
        if re.search(r"(?i)\b(?:TBD|TBC|XXXX|PLACEHOLDER|INSERT)\b", str(fields.get(key) or ""))
        or str(fields.get(key) or "").strip().lower() in {"tbd", "tbc", "xxxx", "placeholder", "insert"}
    ]
    currency_inr = bool(re.search(r"(?i)\bINR\b|\bRs\.?\s*\d|\u20b9", normalized))
    foreign_currency = bool(re.search(r"(?i)\b(?:USD|US\s*\$|EUR|GBP|AED|SGD|AUD)\b", normalized))
    tax_exempt = bool(re.search(r"(?i)\b(?:GST\s*(?:not applicable|exempt)|no GST|without GST|GST\s*@?\s*0\s*%)\b", normalized))
    tax_exclusive = bool(re.search(r"(?i)\b(?:exclusive of (?:all )?(?:tax|GST)|excluding (?:all )?(?:tax|GST)|GST extra|plus GST|taxes extra)\b", normalized))
    gst_rate = float(fields.get("gst_rate") or 0)

    def amount_for(pattern: str) -> Optional[float]:
        match = re.search(
            rf"(?im)^\s*(?:{pattern})\b\s*[:\-]?\s*(?:INR|Rs\.?|\u20b9)?\s*([0-9][0-9,]*(?:\.\d{{1,2}})?)",
            normalized,
        )
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None

    subtotal = amount_for(r"subtotal(?:\s+amount)?|taxable\s+(?:value|amount)|net\s+amount\s+before\s+tax|amount\s+before\s+tax")
    face_total = amount_for(r"grand\s+total|net\s+payable|total\s+(?:po\s+)?amount|total\s+value|order\s+value|po\s+value|total")
    amount_basis = "unknown"
    if subtotal and subtotal > 0:
        fields["total_amount"] = subtotal
        amount_basis = "pre_tax"
    elif face_total and face_total > 0 and gst_rate > 0 and (
        re.search(r"(?i)\bgrand\s+total\b|\bnet\s+payable\b|inclusive of (?:all )?(?:tax|GST)|including (?:all )?(?:tax|GST)", normalized)
    ):
        fields["total_amount"] = round(face_total / (1 + gst_rate / 100), 2)
        amount_basis = "grand_total_includes_tax"
    elif fields.get("total_amount") and fields["total_amount"] > 0 and (tax_exclusive or tax_exempt):
        amount_basis = "pre_tax"
    fields["po_face_total"] = face_total or subtotal or fields.get("total_amount")
    fields["amount_basis"] = amount_basis
    fields["currency"] = "INR" if currency_inr and not foreign_currency else ""
    fields["draft_document"] = bool(draft_reasons)
    fields["draft_reasons"] = draft_reasons
    fields["placeholder_fields"] = placeholder_fields

    if draft_reasons:
        blockers.append("PO is marked draft, indicative, or unapproved")
    if placeholder_fields:
        blockers.append("PO contains placeholder values: " + ", ".join(placeholder_fields))
    if not currency_inr or foreign_currency:
        blockers.append("PO currency is missing or is not INR")
    if amount_basis == "unknown":
        blockers.append("PO amount or tax basis is ambiguous")
    if subtotal and face_total and gst_rate > 0 and abs(round(subtotal * (1 + gst_rate / 100), 2) - face_total) > 1:
        blockers.append("PO subtotal, GST rate, and grand total do not reconcile")
    if gst_rate <= 0 and not tax_exempt:
        blockers.append("PO does not state a GST rate or tax exemption")
    vendor_name = str(fields.get("vendor_name") or "").strip()
    if not vendor_name or "clahan" not in vendor_name.lower():
        blockers.append("PO supplier is missing or does not identify Clahan")
    required = ("po_number", "po_date", "total_amount", "client_name", "vendor_name")
    fields["missing_fields"] = [key for key in required if fields.get(key) in (None, "", 0)]
    blockers.extend(f"Missing required PO field: {key.replace('_', ' ')}" for key in fields["missing_fields"])

    fields["auto_processing_blockers"] = list(dict.fromkeys(blockers))
    fields["auto_processing_eligible"] = bool(fields.get("document_detected") and not fields["auto_processing_blockers"])
    fields["review_required"] = not fields["auto_processing_eligible"]
    return fields


def extract_purchase_order_attachments(attachments: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Extract likely PO PDFs. All extracted values remain untrusted until reviewed."""
    results = []
    for attachment in attachments or []:
        if not isinstance(attachment, dict):
            continue
        filename = str(attachment.get("filename") or "")
        if not filename.lower().endswith(".pdf"):
            continue
        encoded = attachment.get("content_base64") or ""
        if not encoded:
            results.append({"filename": filename, "status": "unavailable", "error": "PDF bytes were not captured"})
            continue
        try:
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) > MAX_PO_PDF_BYTES:
                raise ValueError("PDF exceeds the 12 MB processing limit")
            if not raw.startswith(b"%PDF"):
                raise ValueError("Attachment is not a valid PDF")
            text, page_count, used_ocr = _pdf_text(raw)
            fields = _extract_fields(text)
            status = "parsed" if fields["document_detected"] and not fields["missing_fields"] else "partial" if text else "unreadable"
            results.append({
                "filename": filename,
                "status": status,
                "page_count": page_count,
                "ocr_used": used_ocr,
                "fields": fields,
                "text_preview": text[:12000],
            })
        except Exception as exc:
            results.append({"filename": filename, "status": "error", "error": str(exc)[:300]})
    po_docs = [item for item in results if item.get("fields", {}).get("document_detected") or re.search(r"\b(po|purchase|work.?order)\b", item.get("filename", ""), re.I)]
    return {
        "status": "parsed" if any(item.get("status") == "parsed" for item in po_docs) else "partial" if po_docs else "no_po_pdf",
        "documents": po_docs,
        "fields": next((item["fields"] for item in po_docs if item.get("fields")), {}),
        "review_required": not any(item.get("fields", {}).get("auto_processing_eligible") for item in po_docs),
    }
