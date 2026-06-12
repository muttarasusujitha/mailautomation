from datetime import datetime
from utils.time_utils import utc_now
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import re
from typing import Any, Dict


GST_RATE = Decimal("0.18")
CURRENCY_QUANT = Decimal("0.01")
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"

DEFAULT_COMPANY = {
    "name": "Clahan Technologies",
    "tagline": "Corporate Training and Technology Consulting",
    "address": "Company Address, India",
    "email": "accounts@clahantech.com",
    "phone": "+91 XXXXXXXXXX",
    "gstin": "GSTIN: To be updated",
    "logo_text": "CLAHAN",
}

DEFAULT_PAYMENT_TERMS = (
    "Payment will be processed within 30 days from successful completion of "
    "training and receipt of a valid invoice."
)

DEFAULT_TERMS = [
    "The trainer will deliver the agreed training content professionally and on schedule.",
    "The trainer will share the final table of contents, lab setup notes, and prerequisite list before training.",
    "Training material, examples, and exercises must not infringe third-party intellectual property rights.",
    "The trainer will maintain confidentiality of client information, participant data, and project details.",
    "Invoices must reference the PO number and include applicable tax registration details.",
]

DEFAULT_CANCELLATION_POLICY = [
    "Schedule changes requested more than 7 calendar days before training will be handled without cancellation charges.",
    "Cancellation within 3 to 7 calendar days may be billed up to 50 percent of the professional fee.",
    "Cancellation within 72 hours or trainer no-show may lead to cancellation of the PO and recovery of client penalties, if any.",
]


def _as_decimal(value: Any, default: Any = "0") -> Decimal:
    if value in (None, ""):
        value = default
    try:
        return Decimal(str(value).replace(",", "")).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal(str(default)).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)


def _as_duration_days(value: Any, fallback_hours: Any = None) -> Decimal:
    if value not in (None, ""):
        days = _as_decimal(value, "1")
    elif fallback_hours not in (None, ""):
        days = (_as_decimal(fallback_hours, "8") / Decimal("8")).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    else:
        days = Decimal("1.00")
    return max(days, Decimal("0.25"))


def _clean_filename(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "purchase_order")).strip("_")
    return cleaned[:90] or "purchase_order"


def _display_decimal(value: Decimal) -> str:
    return f"{value.normalize():f}".rstrip("0").rstrip(".") if value % 1 else str(int(value))


def format_money(value: Any) -> str:
    amount = _as_decimal(value)
    return f"INR {amount:,.2f}"


def build_purchase_order_doc(
    trainer: Dict[str, Any],
    requirement: Dict[str, Any],
    payload: Dict[str, Any],
    po_number: str,
) -> Dict[str, Any]:
    now = utc_now()
    duration_days = _as_duration_days(
        payload.get("duration_days") or requirement.get("duration_days"),
        requirement.get("duration_hours"),
    )
    day_rate = _as_decimal(
        payload.get("day_rate")
        or trainer.get("day_rate")
        or requirement.get("budget_per_day")
        or 0
    )
    total_amount = _as_decimal(payload.get("total_amount") or 0)
    if total_amount <= 0:
        total_amount = (day_rate * duration_days).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    if total_amount <= 0 and requirement.get("budget_total"):
        total_amount = _as_decimal(requirement.get("budget_total"))

    gst_amount = (total_amount * GST_RATE).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    grand_total = (total_amount + gst_amount).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)

    duration_label = payload.get("duration") or payload.get("duration_label")
    if not duration_label:
        if requirement.get("duration_days") or payload.get("duration_days"):
            duration_label = f"{_display_decimal(duration_days)} day(s)"
        elif requirement.get("duration_hours"):
            duration_label = f"{requirement.get('duration_hours')} hour(s)"
        else:
            duration_label = f"{_display_decimal(duration_days)} day(s)"

    training_dates = (
        payload.get("training_dates")
        or requirement.get("training_dates")
        or requirement.get("timeline_start")
        or "To be confirmed"
    )
    client_name = (
        payload.get("client_name")
        or requirement.get("client_company")
        or requirement.get("client_name")
        or "Client"
    )
    client_email = payload.get("client_email") or requirement.get("client_email") or ""

    return {
        "po_number": po_number,
        "issue_date": now,
        "issue_date_display": now.strftime("%d %b %Y"),
        "status": "generated",
        "company": {**DEFAULT_COMPANY, **(payload.get("company") or {})},
        "trainer": {
            "trainer_id": trainer.get("trainer_id"),
            "name": payload.get("trainer_name") or trainer.get("name") or "Trainer",
            "email": payload.get("trainer_email") or trainer.get("email") or "",
            "phone": payload.get("trainer_phone") or trainer.get("phone") or "",
            "location": trainer.get("location") or "",
        },
        "requirement": {
            "requirement_id": requirement.get("requirement_id"),
            "technology": payload.get("technology") or requirement.get("technology_needed") or "Training",
            "client_name": client_name,
            "client_email": client_email,
            "mode": payload.get("mode") or requirement.get("mode") or "Online",
            "training_dates": training_dates,
            "duration": duration_label,
            "duration_days": float(duration_days),
        },
        "commercials": {
            "currency": payload.get("currency") or requirement.get("budget_currency") or "INR",
            "day_rate": float(day_rate),
            "total_amount": float(total_amount),
            "gst_rate": 18,
            "gst_amount": float(gst_amount),
            "grand_total": float(grand_total),
        },
        "payment_terms": payload.get("payment_terms") or DEFAULT_PAYMENT_TERMS,
        "terms_and_conditions": payload.get("terms_and_conditions") or DEFAULT_TERMS,
        "cancellation_policy": payload.get("cancellation_policy") or DEFAULT_CANCELLATION_POLICY,
        "prepared_by": payload.get("prepared_by") or "TrainerSync Team",
        "created_at": now,
    }


def render_purchase_order_html(po_doc: Dict[str, Any]) -> str:
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except Exception as exc:
        raise RuntimeError("Jinja2 is required for purchase order rendering. Install backend requirements.") from exc

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["money"] = format_money
    template = env.get_template("purchase_order.html")
    return template.render(po=po_doc)


def purchase_order_pdf_bytes(po_doc: Dict[str, Any], html: str = "") -> bytes:
    try:
        from weasyprint import HTML
    except Exception as exc:
        raise RuntimeError(
            "WeasyPrint is required for purchase order PDF generation. "
            "Install backend requirements and the GTK/Pango runtime libraries required by WeasyPrint on Windows."
        ) from exc

    rendered = html or render_purchase_order_html(po_doc)
    return HTML(string=rendered, base_url=str(TEMPLATE_DIR)).write_pdf()


def purchase_order_filename(po_doc: Dict[str, Any]) -> str:
    trainer = (po_doc.get("trainer") or {}).get("name") or "trainer"
    return f"{_clean_filename(po_doc.get('po_number'))}_{_clean_filename(trainer)}.pdf"


def public_purchase_order(po_doc: Dict[str, Any]) -> Dict[str, Any]:
    public = {k: v for k, v in po_doc.items() if k not in {"_id", "html", "pdf_base64"}}
    for key in ("issue_date", "created_at", "pdf_generated_at", "sent_at", "acknowledged_at"):
        if isinstance(public.get(key), datetime):
            public[key] = public[key].isoformat()
    return public
