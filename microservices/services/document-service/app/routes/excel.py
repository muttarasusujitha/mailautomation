"""Excel export — trainers, requirements, email logs."""
import io
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Response
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from shared.database.service import get_db

router = APIRouter()
logger = logging.getLogger(__name__)
TOC_GREEN_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "assets" / "ToC_Template_8_Columns_Green_Header.xlsx"
TOC_ORANGE_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "assets" / "ToC_Template_8_Columns_Orange_Header.xlsx"
LAB_COST_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "assets" / "Lab_Cost_Estimator_No_Internal_Pricing.xlsx"


def _to_excel(rows: List[Dict[str, Any]], sheet_name: str = "Sheet1") -> bytes:
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
        if not rows:
            output = io.BytesIO()
            wb.save(output)
            return output.getvalue()

        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            ws.append([str(row.get(h, "")) if row.get(h) is not None else "" for h in headers])

        # Style header row
        from openpyxl.styles import Font, PatternFill
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()
    except ImportError:
        raise Exception("openpyxl not installed. Add it to requirements.")


def _toc_to_eight_column_template(toc: Dict[str, Any], template_path: Path) -> bytes:
    """Fill a user-approved eight-column ToC workbook without changing its layout."""
    import openpyxl
    from copy import copy
    from openpyxl.styles import Alignment, Font, PatternFill

    if not template_path.exists():
        raise FileNotFoundError(f"ToC template is missing: {template_path}")
    workbook = openpyxl.load_workbook(template_path)
    sheet = workbook["ToC Template"] if "ToC Template" in workbook.sheetnames else workbook.active
    # Both supplied templates contain an Excel table style.  Google Drive
    # renders that table style as blue/teal over the cell fills, even when the
    # cells are orange.  Remove it so the approved explicit colours win.
    sheet.tables.clear()
    days = list(toc.get("days") or [])
    is_ai_template = template_path == TOC_GREEN_TEMPLATE_PATH
    # Use opaque ARGB colours.  Six-digit values are written as transparent
    # colours by openpyxl and Google Drive then falls back to blue/teal.
    header_fill = PatternFill("solid", fgColor="FF629A1C" if is_ai_template else "FFFFA500")
    alternate_row_fill = PatternFill("solid", fgColor="FFE2F0D9" if is_ai_template else "FFFCE4D6")
    plain_row_fill = PatternFill("solid", fgColor="FFFFFFFF")

    # Keep every generated ToC consistently readable in Calibri, regardless
    # of the font embedded in a user-supplied template.
    for cell in sheet[1]:
        cell.font = Font(name="Calibri", size=11, bold=True, color=cell.font.color.rgb if cell.font.color and cell.font.color.type == "rgb" else "000000")
        cell.fill = header_fill

    def as_text(value: Any) -> str:
        if isinstance(value, (list, tuple, set)):
            return "\n".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    def as_date(value: Any):
        if isinstance(value, datetime):
            return value
        raw = str(value or "").strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return None

    for index, day in enumerate(days, 1):
        row = index + 1
        # The supplied template contains 20 ready-formatted rows. Preserve its
        # green header and duplicate the final body-row style for longer ToCs.
        if row > sheet.max_row:
            source_row = sheet.max_row
            for column in range(1, 9):
                source = sheet.cell(source_row, column)
                target = sheet.cell(row, column)
                target._style = copy(source._style)
                target.number_format = source.number_format
                target.alignment = copy(source.alignment)
            sheet.row_dimensions[row].height = sheet.row_dimensions[source_row].height

        date_value = as_date(day.get("date") or day.get("_resolved_date"))
        weekday = day.get("weekday") or day.get("day_name") or (date_value.strftime("%A") if date_value else "To be confirmed")
        # ``focus_area`` is the validated day-level curriculum title.  Category
        # is only a broad reporting label (for example, "Final Capstone
        # Project") and must not replace the specific corporate module name.
        main_topic = day.get("focus_area") or day.get("module") or day.get("category") or day.get("title") or "Training"
        row_values = [
            day.get("day") or day.get("sr_no") or index,
            date_value or "To be confirmed",
            weekday,
            day.get("timing") or toc.get("timing") or toc.get("session_timing") or "To be confirmed",
            main_topic,
            as_text(day.get("subtopics")) or as_text((day.get("morning_session") or {}).get("topics")) or main_topic,
            as_text(day.get("lab") or day.get("lab_task")) or f"Implement and validate {main_topic}; capture evidence and troubleshoot one realistic failure scenario.",
            as_text(day.get("learning_objectives")) or f"Apply {main_topic} through guided practice.",
        ]
        for column, value in enumerate(row_values, 1):
            cell = sheet.cell(row, column, value)
            cell.font = Font(name="Calibri", size=11)
            cell.fill = alternate_row_fill if index % 2 else plain_row_fill
            cell.alignment = Alignment(horizontal="center" if column <= 4 else "left", vertical="top", wrap_text=True)
        sheet.cell(row, 2).number_format = "dd-mmm-yyyy"
        sheet.row_dimensions[row].height = max(sheet.row_dimensions[row].height or 15, 72)

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:H{max(sheet.max_row, len(days) + 1)}"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _toc_to_excel(toc: Dict[str, Any]) -> bytes:
    """Export AI and manual ToCs in their respective user-approved templates."""
    if str(toc.get("generation_mode") or "").strip().lower() == "ai":
        return _toc_to_eight_column_template(toc, TOC_GREEN_TEMPLATE_PATH)
    # Manual / dataset content intentionally uses the separate orange
    # eight-column template. It never uses the LLM-specific green sheet.
    return _toc_to_eight_column_template(toc, TOC_ORANGE_TEMPLATE_PATH)
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    orange_fill = PatternFill(start_color="FFED7D31", end_color="FFED7D31", fill_type="solid")
    # Legacy renderer safety: blue/teal is permanently retired.  If an old
    # caller ever reaches this renderer, it still uses the approved orange
    # palette rather than recreating the obsolete blue workbook.
    toc_blue_fill = PatternFill(start_color="FFFFA500", end_color="FFFFA500", fill_type="solid")
    cyan_fill = PatternFill(start_color="FFFCE4D6", end_color="FFFCE4D6", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFFFF", end_color="FFFFFFFF", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="000000"),
        right=Side(style="thin", color="000000"),
        top=Side(style="thin", color="000000"),
        bottom=Side(style="thin", color="000000"),
    )
    title_font = Font(name="Arial", bold=True, color="FFFFFF")
    schedule_header_font = Font(name="Arial", bold=True, color="FFFFFF")
    toc_header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    tracker_header_font = Font(name="Arial", bold=True, size=9)
    body_font = Font(name="Arial")

    def style_header(ws, row: int, columns: int, fill: PatternFill, font: Font):
        for cell in ws[row][:columns]:
            cell.font = font
            cell.fill = fill
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center", vertical="bottom", wrap_text=True)

    def topic_text(items: Any) -> str:
        lines = []
        for item in items or []:
            if isinstance(item, dict):
                text = item.get("topic") or item.get("title") or item.get("name") or ""
            else:
                text = str(item or "")
            if text:
                lines.append(str(text))
        return "\n".join(lines)

    def finish(ws, widths: List[float], center_columns: int, body_borders: bool = True, white_background: bool = True):
        for index, width in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(index)].width = width
        for row in ws.iter_rows():
            for cell in row:
                cell.font = cell.font.copy(name=cell.font.name or "Arial") if cell.font else body_font
                if white_background and cell.fill.fill_type is None:
                    cell.fill = white_fill
                if body_borders:
                    cell.border = thin_border
                horizontal = "center" if cell.column <= center_columns else None
                cell.alignment = Alignment(horizontal=horizontal, vertical="bottom", wrap_text=cell.column > center_columns)

    def parse_start_date(value: Any):
        raw = str(value or "")
        match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", raw)
        if match:
            return datetime.strptime(match.group(0), "%Y-%m-%d")
        # Handles requirement date ranges such as "November 1, 2026 to
        # November 15, 2026" so Day and Date are never blank in the ToC.
        match = re.search(r"\b[A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}\b", raw)
        if match:
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    return datetime.strptime(match.group(0), fmt)
                except ValueError:
                    continue
        match = re.search(r"\b\d{1,2}[-/ ][A-Za-z]{3,9}[-/ ]\d{2,4}\b", raw)
        if match:
            for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %B %Y", "%d/%b/%Y"):
                try:
                    return datetime.strptime(match.group(0), fmt)
                except ValueError:
                    continue
        match = re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", raw)
        if match:
            for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
                try:
                    return datetime.strptime(match.group(0), fmt)
                except ValueError:
                    continue
        return None

    start_date = parse_start_date(toc.get("training_dates") or toc.get("preferred_dates") or toc.get("timeline_start"))
    # A delivery-ready TOC must never render a blank schedule.  Generated TOCs
    # use this full-day window unless the client supplied a different timing.
    default_timing = toc.get("timing") or toc.get("session_timing") or "9:00 AM - 5:00 PM"

    def parse_time(value: str):
        value = str(value or "").strip().upper().replace(".", "")
        for fmt in ("%I:%M %p", "%I %p", "%H:%M", "%H"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def infer_hours(timing: Any) -> Any:
        raw = str(timing or "")
        if not raw:
            return ""
        parts = re.split(r"\s*(?:-|–|—|to)\s*", raw, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) != 2:
            return ""
        start = parse_time(parts[0])
        end = parse_time(parts[1])
        if not start or not end:
            return ""
        if end <= start:
            end += timedelta(days=1)
        hours = (end - start).total_seconds() / 3600
        if hours > 5:
            hours -= 1
        return int(hours) if hours.is_integer() else round(hours, 2)

    def generated_date(index: int):
        if not start_date:
            return ""
        current = start_date
        delivered = 0
        while delivered < index:
            if current.weekday() < 6:
                delivered += 1
                if delivered == index:
                    return current
            current += timedelta(days=1)
        return ""

    def day_label(day: Dict[str, Any]) -> str:
        value = day.get("weekday") or day.get("day_name") or ""
        if value:
            return str(value)
        date_value = day.get("date") or day.get("_resolved_date")
        if isinstance(date_value, str):
            parsed = parse_start_date(date_value)
            if parsed:
                date_value = parsed
        if hasattr(date_value, "strftime"):
            return date_value.strftime("%A")
        return ""

    def module_name(day: Dict[str, Any]) -> str:
        return day.get("category") or day.get("module") or day.get("focus_area") or day.get("title") or day.get("topic") or ""

    def topic_name(day: Dict[str, Any]) -> str:
        morning = topic_text((day.get("morning_session") or {}).get("topics"))
        afternoon = topic_text((day.get("afternoon_session") or {}).get("topics"))
        combined = "\n".join(part for part in (morning, afternoon) if part)
        return combined or day.get("focus_area") or day.get("title") or day.get("topic") or ""

    def display_date(day: Dict[str, Any]) -> Any:
        return day.get("date") or day.get("_resolved_date") or "To be confirmed"

    days = toc.get("days") or []
    for index, day in enumerate(days, 1):
        if not day.get("date"):
            resolved = generated_date(index)
            if resolved:
                day["_resolved_date"] = resolved

    overview = wb.active
    overview.title = "Training Schedule"
    # Client-facing agenda summary.  Keep this compact and readable; the
    # detailed sheet below contains the actual date, weekday, and hourly plan.
    programme_name = toc.get("domain") or toc.get("title") or "Training"
    duration_label = toc.get("duration_days") or len(days)
    overview.merge_cells("A1:D1")
    overview["A1"] = f"{str(programme_name).upper()} CORPORATE TRAINING - {duration_label}-DAY COURSE AGENDA"
    overview["A1"].font = Font(name="Arial", bold=True, color="000000", size=14)
    overview["A1"].fill = PatternFill(start_color="FFFCE4D6", end_color="FFFCE4D6", fill_type="solid")
    overview["A1"].alignment = Alignment(horizontal="center", vertical="center")
    for column in range(1, 5):
        overview.cell(1, column).border = thin_border
    overview.row_dimensions[1].height = 28
    metadata = [
        ("Technology", programme_name),
        ("Training Duration", f"{duration_label} Days"),
        ("Mode", toc.get("mode") or "Online"),
        ("Audience", toc.get("audience_level") or toc.get("level") or "Corporate Professionals"),
    ]
    commercial = toc.get("commercial") or toc.get("commercials") or toc.get("total_training_fee")
    if commercial not in (None, "", []):
        metadata.append(("Commercial", commercial))
    for row, (label, value) in enumerate(metadata, 3):
        overview.cell(row, 1, label)
        overview.cell(row, 2, value)
        overview.cell(row, 1).font = Font(name="Arial", bold=True)
        for column in range(1, 5):
            overview.cell(row, column).border = thin_border
            overview.cell(row, column).alignment = Alignment(vertical="center", wrap_text=True)
    header_row = len(metadata) + 5
    overview.cell(header_row, 1, "Day")
    overview.cell(header_row, 2, "Module / Topic")
    overview.cell(header_row, 3, "Topics Covered")
    overview.cell(header_row, 4, "Practical / Hands-on")
    style_header(overview, header_row, 4, toc_blue_fill, toc_header_font)
    for index, day in enumerate(days, 1):
        overview.append([
            day.get("sr_no") or day.get("day") or index,
            module_name(day),
            topic_name(day),
            day.get("lab") or day.get("lab_task") or f"Implement and validate {topic_name(day)}; capture evidence and troubleshoot one realistic failure scenario.",
        ])
    finish(overview, [9, 35, 90, 54], 1)
    for row in range(header_row + 1, overview.max_row + 1):
        overview.row_dimensions[row].height = 48

    domain_name = re.sub(r"[\\\\/*?:\[\]]", "", str(toc.get("domain") or toc.get("title") or "Training")).strip()
    detail = wb.create_sheet(f"{domain_name[:20] or 'Training'} Daily TOC")
    detail.append(["S#", "Day", "Date", "Session", "Time", "Topic / Concept", "Method"])
    style_header(detail, 1, 7, toc_blue_fill, toc_header_font)
    for index, day in enumerate(days, 1):
        for session_key, session_label in (("morning_session", "Morning"), ("afternoon_session", "Afternoon")):
            session = day.get(session_key) or {}
            session_title = session.get("title") or f"{module_name(day) or 'Training'} - {session_label}"
            topics = session.get("topics") or [{
                "time": session.get("time") or default_timing,
                "topic": day.get("focus_area") or day.get("title") or "Training concepts and guided practice",
                "type": "guided learning",
            }]
            for item in topics:
                if isinstance(item, dict):
                    time_slot = item.get("time") or session.get("time") or default_timing
                    concept = item.get("topic") or item.get("title") or session_title
                    method = item.get("type") or "guided learning"
                else:
                    time_slot, concept, method = session.get("time") or default_timing, str(item or session_title), "guided learning"
                detail.append([
                    day.get("toc_no") or day.get("day") or index,
                    f"Day {day.get('day') or index}",
                    display_date(day),
                    session_label,
                    time_slot,
                    concept,
                    method.title(),
                ])
    finish(detail, [8, 10, 18, 14, 20, 62, 18], 5)
    for row in range(2, detail.max_row + 1):
        detail.cell(row, 3).number_format = "d-mmm-yy"

    hands_on = wb.create_sheet("Daily Handson Tracker")
    hands_on.append(["Sr", "Day", "Date", "Module", "Daily HandsOn"])
    style_header(hands_on, 1, 5, cyan_fill, tracker_header_font)
    for index, day in enumerate(days, 1):
        hands_on.append([
            day.get("sr_no") or day.get("day") or index,
            day_label(day),
            display_date(day),
            module_name(day),
            day.get("lab") or day.get("lab_task") or f"Implement and validate {topic_name(day)}; capture evidence and troubleshoot one realistic failure scenario.",
        ])
    finish(hands_on, [13, 13, 13, 39.75, 102.25], 3, body_borders=False, white_background=False)
    for row in range(2, hands_on.max_row + 1):
        hands_on.cell(row, 3).number_format = "d-mmm-yy"

    return_bytes = io.BytesIO()
    wb.save(return_bytes)
    return return_bytes.getvalue()


LAB_COST_RATE_CARD = [
    {
        "key": "compute_light",
        "category": "Compute - Light (2 vCPU / 4GB)",
        "use_case": "General labs: Python, Linux, Git, scripting",
        "unit": "per_hour",
        "providers": {
            "aws": ("EC2 t3.medium", 0.0416),
            "azure": ("VM B2s", 0.0416),
            "gcp": ("Compute Engine e2-medium", 0.0335),
        },
    },
    {
        "key": "compute_heavy",
        "category": "Compute - Heavy (4 vCPU / 16GB)",
        "use_case": "Docker, Kubernetes, Jenkins, CI/CD, capstones",
        "unit": "per_hour",
        "providers": {
            "aws": ("EC2 t3.xlarge", 0.167),
            "azure": ("VM D4s v5", 0.192),
            "gcp": ("Compute Engine e2-standard-4", 0.134),
        },
    },
    {
        "key": "managed_kubernetes",
        "category": "Managed Kubernetes",
        "use_case": "Managed cluster control plane",
        "unit": "per_hour_per_cluster",
        "providers": {
            "aws": ("EKS control plane", 0.1),
            "azure": ("AKS Standard/SLA control plane", 0.1),
            "gcp": ("GKE control plane", 0.1),
        },
    },
    {
        "key": "block_storage",
        "category": "Block Storage",
        "use_case": "SSD disk attached to a virtual machine",
        "unit": "per_gb_month",
        "providers": {
            "aws": ("EBS gp3", 0.08),
            "azure": ("Premium SSD v2", 0.113),
            "gcp": ("Persistent Disk SSD", 0.17),
        },
    },
    {
        "key": "object_storage",
        "category": "Object Storage",
        "use_case": "Hot or standard object storage",
        "unit": "per_gb_month",
        "providers": {
            "aws": ("S3 Standard", 0.023),
            "azure": ("Blob Storage Hot LRS", 0.018),
            "gcp": ("Cloud Storage Standard", 0.02),
        },
    },
    {
        "key": "load_balancer",
        "category": "Load Balancer",
        "use_case": "HTTP(S) or TCP load balancing",
        "unit": "per_hour_plus_data",
        "providers": {
            "aws": ("Application Load Balancer", 0.025),
            "azure": ("Standard Load Balancer", 0.025),
            "gcp": ("Cloud Load Balancing", 0.025),
        },
    },
    {
        "key": "nat_gateway",
        "category": "NAT Gateway",
        "use_case": "Outbound internet for private subnets",
        "unit": "per_hour_plus_data",
        "providers": {
            "aws": ("NAT Gateway", 0.045),
            "azure": ("NAT Gateway", 0.045),
            "gcp": ("Cloud NAT", 0.044),
        },
    },
    {
        "key": "data_egress",
        "category": "Data Egress",
        "use_case": "Outbound internet data transfer",
        "unit": "per_gb",
        "providers": {
            "aws": ("Data Transfer Out", 0.09),
            "azure": ("Bandwidth Outbound", 0.087),
            "gcp": ("Internet Egress", 0.12),
        },
    },
    {
        "key": "build_runner",
        "category": "CI/CD Build Runner",
        "use_case": "Managed build-minute billing",
        "unit": "per_build_minute",
        "providers": {
            "aws": ("CodeBuild general1.small", 0.005),
            "azure": ("Azure Pipelines hosted agent", 0.008),
            "gcp": ("Cloud Build e2-medium", 0.003),
        },
    },
    {
        "key": "container_registry",
        "category": "Container Registry",
        "use_case": "Private container image storage",
        "unit": "per_gb_month",
        "providers": {
            "aws": ("ECR", 0.1),
            "azure": ("ACR Basic equivalent storage", 0.05),
            "gcp": ("Artifact Registry", 0.1),
        },
    },
    {
        "key": "relational_db",
        "category": "Managed Relational Database",
        "use_case": "Small development or test database",
        "unit": "per_hour",
        "providers": {
            "aws": ("RDS db.t3.medium", 0.068),
            "azure": ("Azure SQL DB General Purpose 2 vCore", 0.2),
            "gcp": ("Cloud SQL db-custom-2-4096", 0.1),
        },
    },
    {
        "key": "monitoring",
        "category": "Monitoring / Logs",
        "use_case": "Log ingestion beyond the free tier",
        "unit": "per_gb_ingested",
        "providers": {
            "aws": ("CloudWatch Logs", 0.5),
            "azure": ("Azure Monitor Log Analytics", 2.3),
            "gcp": ("Cloud Logging", 0.5),
        },
    },
]

FREE_TOOL_KEYWORDS = (
    "docker", "self-managed kubernetes", "git", "github", "jenkins",
    "sonarqube", "maven", "ansible", "terraform", "helm", "linux",
)
THIRD_PARTY_KEYWORDS = (
    "jira", "datadog", "claude", "factory.ai", "factory ai", "harness",
    "openai", "langchain", "langgraph", "langfuse", "anthropic",
)
HEAVY_WORKLOAD_KEYWORDS = (
    "docker", "kubernetes", "jenkins", "ci/cd", "ci-cd", "pipeline",
    "helm", "capstone", "microservice", "container", "cluster",
)


def _lab_cost_template_to_excel(toc: Dict[str, Any], assumptions: Optional[Dict[str, Any]] = None) -> bytes:
    """Populate the approved five-sheet Lab Cost template without changing its design."""
    import openpyxl
    from copy import copy

    if not LAB_COST_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Lab Cost template is missing: {LAB_COST_TEMPLATE_PATH}")

    values = assumptions or {}
    provider = str(values.get("cloud_provider") or values.get("provider") or "aws").strip().lower()
    if provider not in {"aws", "azure", "gcp"}:
        provider = "aws"
    provider_label = {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}[provider]
    region = str(values.get("cloud_region") or values.get("region") or "").strip().lower()
    region_label = {
        "aws": "Mumbai",
        "azure": "Central India",
        "gcp": "GCP Mumbai",
    }[provider]
    if region:
        region_label = {
            "india-mumbai": {"aws": "Mumbai", "azure": "Central India", "gcp": "GCP Mumbai"},
            "ap-south-1": {"aws": "Mumbai", "azure": "Central India", "gcp": "GCP Mumbai"},
            "central-india": {"aws": "Mumbai", "azure": "Central India", "gcp": "GCP Mumbai"},
            "mumbai": {"aws": "Mumbai", "azure": "Central India", "gcp": "GCP Mumbai"},
            "gcp mumbai": {"aws": "Mumbai", "azure": "Central India", "gcp": "GCP Mumbai"},
        }.get(region, {}).get(provider, region_label)

    def as_number(key: str, default: float, minimum: float = 0) -> float:
        try:
            return max(minimum, float(values.get(key) if values.get(key) is not None else default))
        except (TypeError, ValueError):
            return max(minimum, default)

    def as_positive_int(key: str, default: int = 1) -> int:
        return max(1, int(round(as_number(key, default, 1))))

    def day_text(day: Dict[str, Any]) -> str:
        parts: List[Any] = [
            day.get("category"), day.get("module"), day.get("focus_area"), day.get("title"),
            day.get("topic"), day.get("tools"), day.get("lab"), day.get("lab_task"), day.get("subtopics"),
        ]
        for session_name in ("morning_session", "afternoon_session"):
            session = day.get(session_name) or {}
            parts.extend([session.get("title"), session.get("time")])
            parts.extend(
                item.get("topic") if isinstance(item, dict) else item
                for item in (session.get("topics") or [])
            )
        return " ".join(str(part) for part in parts if part).lower()

    def day_title(day: Dict[str, Any], index: int) -> str:
        return str(
            day.get("focus_area") or day.get("title") or day.get("topic") or
            day.get("category") or day.get("module") or f"Training Day {index}"
        ).strip()

    days = [item for item in (toc.get("days") or []) if isinstance(item, dict)]
    if not days:
        days = [{"title": str(toc.get("title") or toc.get("domain") or "Training")}]
    duration_days = sum(
        max(1, int(float(day.get("duration_days") or day.get("days") or 1)))
        for day in days
    )
    title = str(toc.get("title") or toc.get("domain") or toc.get("technology") or "Training").strip()

    workbook = openpyxl.load_workbook(LAB_COST_TEMPLATE_PATH)
    assumptions_ws = workbook["Assumptions"]
    assumptions_ws["B4"] = title
    assumptions_ws["B5"] = provider_label
    assumptions_ws["B6"] = region_label
    assumptions_ws["B7"] = as_number("hours_per_day", 3, 0.5)
    assumptions_ws["B8"] = duration_days
    assumptions_ws["B9"] = as_positive_int("participant_count", 1)
    assumptions_ws["B10"] = as_number("storage_gb", 10, 0)
    assumptions_ws["B11"] = as_number("egress_gb", 1, 0)
    assumptions_ws["B12"] = as_number("build_minutes", 60, 0)
    assumptions_ws["B13"] = as_number("monitoring_gb", 1, 0)
    assumptions_ws["B14"] = as_positive_int("k8s_worker_nodes", 1)
    assumptions_ws["B15"] = as_number("fx_rate", 84, 0.01)
    assumptions_ws["B16"] = as_number("contingency_percent", 10, 0) / 100
    assumptions_ws["B17"] = as_number("tax_percent", 0, 0) / 100
    package = str(values.get("lab_package") or "standard").strip().lower()
    assumptions_ws["B18"] = package.title() if package in {"basic", "standard", "advanced"} else "Standard"
    assumptions_ws["B19"] = as_positive_int("quote_validity_days", 7)

    # The supplied template owns the entire visual structure.  Replace only
    # its example mapping rows with one accurately mapped row per ToC day.
    mapping_ws = workbook["TOC Mapping"]
    body_styles = [copy(mapping_ws.cell(4, column)._style) for column in range(1, 9)]
    body_alignments = [copy(mapping_ws.cell(4, column).alignment) for column in range(1, 9)]
    body_row_height = mapping_ws.row_dimensions[4].height
    note_title_style = copy(mapping_ws["A10"]._style)
    note_title_alignment = copy(mapping_ws["A10"].alignment)
    note_body_style = copy(mapping_ws["A11"]._style)
    note_body_alignment = copy(mapping_ws["A11"].alignment)
    note_text = str(mapping_ws["A11"].value or "")
    for merged_range in ("A10:H10", "A11:H12"):
        if merged_range in {str(item) for item in mapping_ws.merged_cells.ranges}:
            mapping_ws.unmerge_cells(merged_range)
    mapping_ws.delete_rows(4, mapping_ws.max_row - 3)

    for index, day in enumerate(days, 1):
        row = index + 3
        text = day_text(day)
        k8s_needed = any(token in text for token in ("kubernetes", " k8s", "eks", "aks", "gke", "helm"))
        database_needed = any(token in text for token in ("database", " rds", "azure sql", "cloud sql", "postgres", "mysql", "mongodb"))
        storage_needed = any(token in text for token in ("s3", "blob storage", "object storage", "bucket"))
        heavy_vm = any(token in text for token in ("docker", "terraform", "ansible", "jenkins", "ci/cd", "pipeline", "agentic ai", "llm"))
        vm_needed = not k8s_needed or heavy_vm
        row_values = [
            index,
            day_title(day, index),
            "=Assumptions!$B$9" if vm_needed else 0,
            "Heavy" if heavy_vm else ("Light" if vm_needed else "None"),
            "=Assumptions!$B$9" if k8s_needed else 0,
            "=Assumptions!$B$9*Assumptions!$B$14" if k8s_needed else 0,
            "=Assumptions!$B$9" if database_needed else 0,
            "=Assumptions!$B$9" if storage_needed else 0,
        ]
        for column, value in enumerate(row_values, 1):
            cell = mapping_ws.cell(row, column, value)
            cell._style = copy(body_styles[column - 1])
            cell.alignment = copy(body_alignments[column - 1])
        mapping_ws.row_dimensions[row].height = body_row_height

    mapping_end_row = len(days) + 3
    mapping_table = mapping_ws.tables.get("TOCMappingTable")
    if mapping_table:
        mapping_table.ref = f"A3:H{mapping_end_row}"
    note_title_row = mapping_end_row + 2
    note_body_row = note_title_row + 1
    mapping_ws.merge_cells(start_row=note_title_row, start_column=1, end_row=note_title_row, end_column=8)
    mapping_ws.cell(note_title_row, 1, "Mapping note")
    mapping_ws.cell(note_title_row, 1)._style = note_title_style
    mapping_ws.cell(note_title_row, 1).alignment = note_title_alignment
    mapping_ws.merge_cells(start_row=note_body_row, start_column=1, end_row=note_body_row + 1, end_column=8)
    mapping_ws.cell(note_body_row, 1, note_text)
    mapping_ws.cell(note_body_row, 1)._style = note_body_style
    mapping_ws.cell(note_body_row, 1).alignment = note_body_alignment

    # Retain the approved billing-unit formulas.  Only the quantities are
    # linked to the generated mapping, so one participant receives one lab
    # environment/cluster when that technology requires it.
    breakdown_ws = workbook["Resource Cost Breakdown"]
    breakdown_ws["B4"] = f"=MAX('TOC Mapping'!$C$4:$C${mapping_end_row})"
    breakdown_ws["B5"] = f"=MAX('TOC Mapping'!$E$4:$E${mapping_end_row})"
    breakdown_ws["B6"] = f"=MAX('TOC Mapping'!$F$4:$F${mapping_end_row})"
    breakdown_ws["B11"] = f"=MAX('TOC Mapping'!$G$4:$G${mapping_end_row})"
    breakdown_ws["B8"] = f"=IF(MAX('TOC Mapping'!$H$4:$H${mapping_end_row})>0,Assumptions!$B$10,0)"

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _retired_lab_cost_to_excel(toc: Dict[str, Any], assumptions: Optional[Dict[str, Any]] = None) -> bytes:
    """Retired custom Lab Cost layout. The export route uses the approved template above."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    values = assumptions or {}
    provider = str(values.get("cloud_provider") or values.get("provider") or "aws").lower()
    if provider not in {"aws", "azure", "gcp"}:
        provider = "aws"
    hours_per_day = max(0.5, float(values.get("hours_per_day") or 8))
    participant_count = max(1, int(values.get("participant_count") or 1))
    fx_rate = max(0.01, float(values.get("fx_rate") or 83))
    contingency_value = values.get("contingency_percent")
    contingency_percent = max(0, min(100, float(10 if contingency_value is None else contingency_value))) / 100
    tax_percent = max(0, min(100, float(values.get("tax_percent") or 0))) / 100
    lab_package = str(values.get("lab_package") or "standard").strip().lower()
    if lab_package not in {"basic", "standard", "advanced"}:
        lab_package = "standard"
    package_multiplier = {"basic": 0.80, "standard": 1.00, "advanced": 1.30}[lab_package]
    lab_support_per_participant = max(0, float(values.get("lab_support_per_participant") or 0))
    quote_validity_days = max(1, int(values.get("quote_validity_days") or 7))
    include_internal_pricing = bool(values.get("include_internal_pricing"))
    clahan_margin_percent = max(0, min(100, float(values.get("clahan_margin_percent") or 0))) / 100
    region = str(values.get("cloud_region") or "india-mumbai").strip().lower()
    region_labels = {
        "india-mumbai": {"aws": "ap-south-1 (Mumbai)", "azure": "Central India", "gcp": "asia-south1 (Mumbai)"},
        "ap-south-1": {"aws": "ap-south-1 (Mumbai)", "azure": "Central India", "gcp": "asia-south1 (Mumbai)"},
        "central-india": {"aws": "ap-south-1 (Mumbai)", "azure": "Central India", "gcp": "asia-south1 (Mumbai)"},
    }
    region_name = region_labels.get(region, region_labels["india-mumbai"])[provider]
    storage_gb = max(0, float(values.get("storage_gb") or 10))
    egress_gb = max(0, float(values.get("egress_gb") or 1))
    build_minutes = max(0, float(values.get("build_minutes") or 60))
    monitoring_gb = max(0, float(values.get("monitoring_gb") or 1))
    k8s_worker_nodes = max(0, int(values.get("k8s_worker_nodes") or 1))
    provider_label = {"aws": "AWS", "azure": "Azure", "gcp": "GCP"}[provider]
    provider_compute_label = {"aws": "AWS EC2", "azure": "Azure VM", "gcp": "GCP Compute Engine"}[provider]

    wb = openpyxl.Workbook()
    assumptions_ws = wb.active
    assumptions_ws.title = "Assumptions"
    cost_ws = wb.create_sheet("Lab Cost")
    summary_ws = wb.create_sheet("Lab Cost Estimate", 0)
    requirements_ws = wb.create_sheet("Lab Requirements", 1)

    # Always use opaque ARGB values.  Six-digit values are saved by openpyxl
    # with a transparent alpha channel and Google Drive can then display its
    # default blue/teal theme.  Lab Cost follows the current orange template
    # family, the same way manual ToC workbooks do.
    primary_orange = "FFC65911"
    header_orange = "FFED7D31"
    input_yellow = "FFFFF2CC"
    free_green = "FFE2F0D9"
    light_orange = "FFFCE4D6"
    light_gray = "FFF2F2F2"
    white = "FFFFFFFF"
    total_orange = "FFF4B183"
    text_gray = "FF595959"
    total_text = "FF7F2704"
    thin_gray = Side(style="thin", color="FFB7C9D6")
    border = Border(bottom=thin_gray)
    input_fill = PatternFill("solid", fgColor=input_yellow)
    header_fill = PatternFill("solid", fgColor=header_orange)
    section_fill = PatternFill("solid", fgColor=primary_orange)
    free_fill = PatternFill("solid", fgColor=free_green)

    assumptions_ws.sheet_view.showGridLines = False
    assumptions_ws.merge_cells("A1:F1")
    assumptions_ws["A1"] = f"Lab Cost Generator - Assumptions & {provider_label} Rate Card ({region_name})"
    assumptions_ws["A1"].font = Font(name="Calibri", size=16, bold=True, color=white)
    assumptions_ws["A1"].fill = section_fill
    assumptions_ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    assumptions_ws.row_dimensions[1].height = 26
    assumptions_ws.merge_cells("A3:F3")
    assumptions_ws["A3"] = "Global Inputs (edit yellow cells)"
    assumptions_ws["A3"].font = Font(bold=True, color=white)
    assumptions_ws["A3"].fill = header_fill
    input_rows = [
        ("Hours per Training Day", hours_per_day, "hours"),
        ("Number of Participants", participant_count, "learners"),
        ("USD to INR Conversion Rate", fx_rate, "INR per USD 1"),
        ("Cloud Provider", provider_label, f"AWS / Azure / GCP; region: {region_name}"),
        ("Contingency", contingency_percent, "Buffer for regional pricing, taxes, and incidental usage"),
        ("Tax / GST", tax_percent, "Applied after contingency"),
        ("Lab Package", lab_package.title(), "Basic / Standard / Advanced"),
        ("Package Multiplier", package_multiplier, "Basic 80%, Standard 100%, Advanced 130%"),
        ("Lab Support per Participant", lab_support_per_participant, "INR; optional support, provisioning, and teardown"),
        ("Quote Validity", quote_validity_days, "days from issue date"),
        ("Clahan Margin", clahan_margin_percent, "Internal-only; never shown in a normal client workbook"),
    ]
    for row, (label, value, note) in enumerate(input_rows, 4):
        assumptions_ws.cell(row, 1, label)
        assumptions_ws.cell(row, 2, value)
        assumptions_ws.cell(row, 2).fill = input_fill
        assumptions_ws.cell(row, 3, note)
    assumptions_ws["B4"].number_format = "0.00"
    assumptions_ws["B5"].number_format = "0"
    assumptions_ws["B6"].number_format = "0.00"
    assumptions_ws["B8"].number_format = "0%"
    assumptions_ws["B9"].number_format = "0%"
    assumptions_ws["B11"].number_format = "0%"
    assumptions_ws["B12"].number_format = 'INR #,##0.00'
    assumptions_ws["B14"].number_format = "0%"
    assumptions_ws.row_dimensions[14].hidden = not include_internal_pricing

    usage_title_row = 16
    assumptions_ws.merge_cells(start_row=usage_title_row, start_column=1, end_row=usage_title_row, end_column=6)
    assumptions_ws.cell(usage_title_row, 1, "Usage Inputs (edit yellow cells; used according to each resource billing unit)")
    assumptions_ws.cell(usage_title_row, 1).font = Font(bold=True, color=white)
    assumptions_ws.cell(usage_title_row, 1).fill = section_fill
    usage_rows = [
        ("Persistent / Object Storage", storage_gb, "GB; charged per GB-month"),
        ("Expected Data Egress", egress_gb, "GB; charged per GB"),
        ("CI/CD Build Minutes", build_minutes, "build minutes; charged per build minute"),
        ("Monitoring Log Ingest", monitoring_gb, "GB; charged per GB ingested"),
        ("Kubernetes Worker Nodes", k8s_worker_nodes, "nodes; added to managed control-plane cost"),
    ]
    for row, (label, value, note) in enumerate(usage_rows, usage_title_row + 1):
        assumptions_ws.cell(row, 1, label)
        assumptions_ws.cell(row, 2, value)
        assumptions_ws.cell(row, 2).fill = input_fill
        assumptions_ws.cell(row, 3, note)
    assumptions_ws["B17"].number_format = "0.00"
    assumptions_ws["B18"].number_format = "0.00"
    assumptions_ws["B19"].number_format = "0.00"
    assumptions_ws["B20"].number_format = "0.00"
    assumptions_ws["B21"].number_format = "0"

    rate_title_row = 23
    assumptions_ws.merge_cells(start_row=rate_title_row, start_column=1, end_row=rate_title_row, end_column=6)
    assumptions_ws.cell(rate_title_row, 1, f"{provider_label} Rate Card (India/Mumbai estimate for {region_name}; verify current regional rates before final budget)")
    assumptions_ws.cell(rate_title_row, 1).font = Font(bold=True, color=white)
    assumptions_ws.cell(rate_title_row, 1).fill = section_fill
    rate_headers = ["Key", "Tool / Cloud Resource", "Billing Unit", "Rate (USD)", "Use Case", "Source / Note"]
    assumptions_ws.append(rate_headers)
    for cell in assumptions_ws[rate_title_row + 1]:
        cell.fill = header_fill
        cell.font = Font(bold=True, color=white)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    rate_rows: Dict[str, int] = {}
    for item in LAB_COST_RATE_CARD:
        service, rate = item["providers"][provider]
        row = assumptions_ws.max_row + 1
        rate_rows[item["key"]] = row
        assumptions_ws.append([
            item["key"], service, item["unit"], rate, item["use_case"],
            "User-provided Multi-Cloud Tool Cost Dataset (Aug 2026 approximate rate)",
        ])
        assumptions_ws.cell(row, 4).number_format = '$0.0000'
    free_start = assumptions_ws.max_row + 2
    assumptions_ws.merge_cells(start_row=free_start, start_column=1, end_row=free_start, end_column=6)
    assumptions_ws.cell(free_start, 1, "Free / Third-Party Tool Rules")
    assumptions_ws.cell(free_start, 1).font = Font(bold=True, color=white)
    assumptions_ws.cell(free_start, 1).fill = section_fill
    assumptions_ws.append(["Tool Group", "Billing Type", "Rate (USD)", "Notes", "", ""])
    free_groups = [
        ("Docker / Kubernetes self-managed / Git / Jenkins / SonarQube / Maven / Ansible / Terraform / Helm", "free", 0, "Open-source; underlying cloud compute may still be billed"),
        ("Jira / Datadog / Claude / Factory.AI / Harness.io / OpenAI / LangChain / LangGraph / Langfuse", "third_party", 0, "Not cloud-provider billed; vendor charges are tracked separately"),
    ]
    for group in free_groups:
        assumptions_ws.append([*group, "", ""])
        for cell in assumptions_ws[assumptions_ws.max_row]:
            cell.fill = free_fill

    for column, width in enumerate([25, 34, 24, 15, 48, 48], 1):
        assumptions_ws.column_dimensions[get_column_letter(column)].width = width
    assumptions_ws.freeze_panes = "A25"
    for row in assumptions_ws.iter_rows(min_row=3, max_row=assumptions_ws.max_row, min_col=1, max_col=6):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = border

    def flatten_text(day: Dict[str, Any]) -> str:
        parts = [day.get("category"), day.get("module"), day.get("focus_area"), day.get("title"), day.get("topic"), day.get("tools"), day.get("lab"), day.get("lab_task")]
        for session_name in ("morning_session", "afternoon_session"):
            session = day.get(session_name) or {}
            parts.extend([session.get("title"), session.get("time")])
            for topic in session.get("topics") or []:
                parts.append(topic.get("topic") if isinstance(topic, dict) else topic)
        return " ".join(str(part) for part in parts if part).lower()

    def select_resource(day: Dict[str, Any]):
        text = flatten_text(day)
        cloud_terms = ("aws", "azure", "gcp", "cloud", "ec2", "virtual machine", "vm", "eks", "aks", "gke", "rds", "cloud sql", "blob storage", "s3")
        if "python" in text and not any(term in text for term in cloud_terms):
            return "Local Python environment", "free", None
        managed_rules = [
            (("eks", "aks", "gke", "managed kubernetes"), "managed_kubernetes"),
            (("rds", "azure sql", "cloud sql", "managed database", "relational database"), "relational_db"),
            (("load balancer", "alb"), "load_balancer"),
            (("nat gateway", "cloud nat"), "nat_gateway"),
            (("ebs", "block storage", "persistent disk", "attached disk"), "block_storage"),
            (("s3", "blob storage", "cloud storage", "object storage", "bucket"), "object_storage"),
            (("egress", "data transfer out", "bandwidth outbound", "internet transfer"), "data_egress"),
            (("codebuild", "build runner", "build minutes", "cloud build", "pipeline build"), "build_runner"),
            (("cloudwatch", "log analytics", "cloud logging", "monitoring logs", "log ingest"), "monitoring"),
            (("ecr", "container registry", "artifact registry", "container image"), "container_registry"),
        ]
        for keywords, key in managed_rules:
            if any(keyword in text for keyword in keywords):
                item = next(entry for entry in LAB_COST_RATE_CARD if entry["key"] == key)
                return item["providers"][provider][0], key, rate_rows[key]
        if any(keyword in text for keyword in HEAVY_WORKLOAD_KEYWORDS):
            item = next(entry for entry in LAB_COST_RATE_CARD if entry["key"] == "compute_heavy")
            return item["providers"][provider][0], "compute_heavy", rate_rows["compute_heavy"]
        if any(keyword in text for keyword in THIRD_PARTY_KEYWORDS):
            matched = next((keyword for keyword in THIRD_PARTY_KEYWORDS if keyword in text), "third-party tool")
            return matched.title(), "third_party", None
        if any(keyword in text for keyword in FREE_TOOL_KEYWORDS) and not any(token in text for token in ("lab", "hands-on", "practice", "deploy", "project")):
            matched = next((keyword for keyword in FREE_TOOL_KEYWORDS if keyword in text), "open-source tool")
            return matched.title(), "free", None
        item = next(entry for entry in LAB_COST_RATE_CARD if entry["key"] == "compute_light")
        return item["providers"][provider][0], "compute_light", rate_rows["compute_light"]

    cost_ws.sheet_view.showGridLines = False
    cost_ws.merge_cells("A1:M1")
    title = toc.get("title") or toc.get("domain") or "Training"
    cost_ws["A1"] = f"{provider_label} Lab Cost by TOC Line Item - {title}"
    cost_ws["A1"].font = Font(name="Calibri", size=16, bold=True, color=white)
    cost_ws["A1"].fill = section_fill
    cost_ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    cost_ws.row_dimensions[1].height = 28
    cost_ws.merge_cells("A2:M2")
    cost_ws["A2"] = "Parent TOC rows carry costs. Indented session topics show tool usage only and are already covered by the parent day."
    cost_ws["A2"].fill = PatternFill("solid", fgColor=light_orange)
    cost_ws["A2"].font = Font(italic=True, color=primary_orange)
    headers = [
        "S#", "Category", "Topic (as per TOC)", "Day(s)", "Tool / Cloud Resource Required",
        "Billing Type", "Rate (USD)", "Rate (INR)", "Cost/Unit (INR)",
        "Billable Quantity", "No. of Participants", "Cost/Participant (INR)", "TOTAL Cost (INR)",
    ]
    cost_ws.append([])
    cost_ws.append(headers)
    for cell in cost_ws[4]:
        cell.fill = header_fill
        cell.font = Font(bold=True, color=white)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cost_ws.row_dimensions[4].height = 44

    cost_parent_rows = []
    current_day = 1
    for index, day in enumerate(toc.get("days") or [], 1):
        raw_days = day.get("duration_days") or day.get("days") or 1
        try:
            day_count = max(1, int(float(raw_days)))
        except (TypeError, ValueError):
            day_count = 1
        day_end = current_day + day_count - 1
        day_label = f"Day {current_day}" if day_count == 1 else f"Day {current_day}-{day_end}"
        category = day.get("category") or day.get("module") or day.get("focus_area") or "Training"
        topic = day.get("focus_area") or day.get("title") or day.get("topic") or f"Training Day {index}"
        resource, billing_key, rate_row = select_resource(day)
        row = cost_ws.max_row + 1
        cost_parent_rows.append(row)
        is_free = billing_key in {"free", "third_party"}
        billing = "Free / 3rd-party (not cloud-provider billed)" if is_free else f"{provider_compute_label if billing_key.startswith('compute_') else provider_label + ' managed resource'} ({billing_key} billing)"
        rate_formula = "=0" if is_free else f"='Assumptions'!$D${rate_row}"
        # J is the billable quantity; each cloud service keeps its own unit.
        usage_formula = {
            "compute_light": f"={day_count}*'Assumptions'!$B$4",
            "compute_heavy": f"={day_count}*'Assumptions'!$B$4",
            "managed_kubernetes": f"={day_count}*'Assumptions'!$B$4",
            "relational_db": f"={day_count}*'Assumptions'!$B$4",
            "load_balancer": f"={day_count}*'Assumptions'!$B$4",
            "nat_gateway": f"={day_count}*'Assumptions'!$B$4",
            "block_storage": f"='Assumptions'!$B$17*{day_count}/30",
            "object_storage": f"='Assumptions'!$B$17*{day_count}/30",
            "container_registry": f"='Assumptions'!$B$17*{day_count}/30",
            "data_egress": "='Assumptions'!$B$18",
            "build_runner": "='Assumptions'!$B$19",
            "monitoring": "='Assumptions'!$B$20",
        }.get(billing_key, f"={day_count}*'Assumptions'!$B$4")
        if is_free:
            cost_formula = f"=0"
        elif billing_key == "managed_kubernetes":
            worker_rate_row = rate_rows["compute_heavy"]
            cost_formula = f"=(G{row}*J{row}+'Assumptions'!$B$21*'Assumptions'!$D${worker_rate_row}*J{row})*'Assumptions'!$B$6*'Assumptions'!$B$11"
        else:
            cost_formula = f"=G{row}*J{row}*'Assumptions'!$B$6*'Assumptions'!$B$11"
        cost_ws.append([index, category, topic, day_label, resource, billing, rate_formula, f"=G{row}*'Assumptions'!$B$6", f"=L{row}/K{row}", usage_formula, "='Assumptions'!$B$5", cost_formula, f"=L{row}*K{row}"])
        if is_free:
            for cell in cost_ws[row]:
                cell.fill = free_fill

        subtopics = []
        for session_name in ("morning_session", "afternoon_session"):
            session = day.get(session_name) or {}
            for item in session.get("topics") or []:
                text = item.get("topic") if isinstance(item, dict) else str(item)
                if text and text.strip().lower() != str(topic).strip().lower():
                    subtopics.append(text)
        seen = set()
        for subtopic in subtopics:
            normalized = str(subtopic).strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            sub_day = {"focus_area": subtopic}
            sub_resource, sub_key, sub_rate_row = select_resource(sub_day)
            sub_row = cost_ws.max_row + 1
            sub_free = sub_key in {"free", "third_party"}
            sub_billing = "Free / 3rd-party (not cloud-provider billed)" if sub_free else billing
            sub_rate_formula = "=0" if sub_free else f"='Assumptions'!$D${sub_rate_row}"
            cost_ws.append(["", "", f"    > {subtopic}", "-", sub_resource, sub_billing, sub_rate_formula, f"=G{sub_row}*'Assumptions'!$B$6", "-", "-", "-", "-", "-"])
            for cell in cost_ws[sub_row]:
                cell.fill = free_fill if sub_free else PatternFill("solid", fgColor=light_gray)
                cell.font = Font(italic=True, color=text_gray)
        current_day = day_end + 1

    total_row = cost_ws.max_row + 1
    total_hours_formula = "=SUM(" + ",".join(f"J{row}" for row in cost_parent_rows) + ")" if cost_parent_rows else "=0"
    total_cost_formula = "=SUM(" + ",".join(f"M{row}" for row in cost_parent_rows) + ")" if cost_parent_rows else "=0"
    cost_ws.append(["", "", "TOTAL (all day-bearing TOC rows)", "", "", "", "", "", "", total_hours_formula, "", "", total_cost_formula])
    for cell in cost_ws[total_row]:
        cell.fill = PatternFill("solid", fgColor=total_orange)
        cell.font = Font(bold=True, color=total_text)
    note_row = cost_ws.max_row + 2
    cost_ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=13)
    cost_ws.cell(note_row, 1, "Green rows are free/open-source or third-party tools from the cloud-provider perspective. Rates are approximate; verify region, taxes, quotas, storage, egress, and vendor subscriptions before final budgeting.")
    cost_ws.cell(note_row, 1).font = Font(italic=True, color=text_gray)
    cost_ws.cell(note_row, 1).alignment = Alignment(wrap_text=True, vertical="top")
    cost_ws.row_dimensions[note_row].height = 34

    widths = [7, 28, 50, 13, 34, 38, 14, 14, 18, 16, 16, 20, 20]
    for column, width in enumerate(widths, 1):
        cost_ws.column_dimensions[get_column_letter(column)].width = width
    cost_ws.freeze_panes = "A5"
    cost_ws.auto_filter.ref = f"A4:M{max(4, total_row - 1)}"
    for row in cost_ws.iter_rows(min_row=4, max_row=total_row, min_col=1, max_col=13):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True, horizontal="right" if cell.column >= 7 else "left")
            cell.border = border
    for column in (7, 8):
        for row in range(5, total_row + 1):
            cost_ws.cell(row, column).number_format = '$0.0000' if column == 7 else 'INR #,##0.00'
    for column in (9, 12, 13):
        for row in range(5, total_row + 1):
            cost_ws.cell(row, column).number_format = 'INR #,##0.00'
    for row in range(5, total_row + 1):
        cost_ws.cell(row, 10).number_format = '0.00'
        cost_ws.cell(row, 11).number_format = '0'

    # The only client-facing worksheet: concise quote information without
    # implementation rate-card or spreadsheet-generator language.
    summary_ws.sheet_view.showGridLines = False
    summary_ws.merge_cells("A1:D1")
    summary_ws["A1"] = f"Lab Cost Estimate — {title}"
    summary_ws["A1"].font = Font(name="Calibri", size=16, bold=True, color=white)
    summary_ws["A1"].fill = section_fill
    summary_ws.row_dimensions[1].height = 30
    summary_ws.merge_cells("A2:D2")
    summary_ws["A2"] = "Prepared for review. Final pricing is confirmed after cloud region, access window, participant count, and taxes are approved."
    summary_ws["A2"].fill = PatternFill("solid", fgColor=light_orange)
    summary_ws["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    summary_ws.row_dimensions[2].height = 34
    summary_ws.append([])
    summary_ws.append(["Item", "Amount / Detail", "Notes", ""])
    for cell in summary_ws[4]:
        cell.fill = header_fill
        cell.font = Font(bold=True, color=white)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    summary_rows = [
        ("Cloud environment", f"='Assumptions'!B7", "Provider selected for the lab", ""),
        ("Participants", "='Assumptions'!B5", "Individual lab environments", ""),
        ("Lab access", "='Assumptions'!B4", "Hours per training day", "hours/day"),
        ("Infrastructure", f"='Lab Cost'!M{total_row}", "Cloud resources required for the TOC", ""),
        ("Lab support", "='Assumptions'!B5*'Assumptions'!B12", "Provisioning, access support, and teardown", ""),
        ("Estimated lab cost", "=SUM(B8:B9)*(1+'Assumptions'!B8)*(1+'Assumptions'!B9)", "Includes approved contingency and taxes", ""),
        ("Quote validity", "='Assumptions'!B13", "Days from issue date", "days"),
    ]
    for row in summary_rows:
        summary_ws.append(row)
    for row in range(5, summary_ws.max_row + 1):
        for cell in summary_ws[row]:
            cell.border = border
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    for cell_ref in ("B8", "B9", "B10"):
        summary_ws[cell_ref].number_format = 'INR #,##0.00'
    summary_ws["B6"].number_format = '0'
    summary_ws["B7"].number_format = '0.00'
    for column, width in enumerate([26, 24, 48, 16], 1):
        summary_ws.column_dimensions[get_column_letter(column)].width = width
    summary_ws.freeze_panes = "A5"

    requirements_ws.sheet_view.showGridLines = False
    requirements_ws.merge_cells("A1:D1")
    requirements_ws["A1"] = f"Lab Requirements and Setup Checklist - {title}"
    requirements_ws["A1"].font = Font(name="Calibri", size=16, bold=True, color=white)
    requirements_ws["A1"].fill = section_fill
    requirements_ws.row_dimensions[1].height = 28
    requirements_ws.merge_cells("A2:D2")
    requirements_ws["A2"] = "This checklist is for participant readiness. Cloud access, credits, and any paid third-party subscriptions must be approved before provisioning."
    requirements_ws["A2"].fill = PatternFill("solid", fgColor=light_orange)
    requirements_ws["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    requirements_ws.row_dimensions[2].height = 34
    requirements_ws.append([])
    requirements_ws.append(["Area", "Requirement", "Owner", "Status / Notes"])
    for cell in requirements_ws[4]:
        cell.fill = header_fill
        cell.font = Font(bold=True, color=white)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    requirement_rows = [
        ("Cloud account", f"Active {provider_label} account or Clahan-managed sandbox with billing access", "Client / Clahan", "Required before Day 1"),
        ("Cloud credits", "Approved training budget and spend limit for each participant", "Client", "Set budget alerts and quotas"),
        ("Access", "Participant login, MFA, IAM role / least-privilege permissions", "Client / Participant", "No shared credentials"),
        ("Workstation", "Laptop with 8 GB RAM minimum, stable internet, browser access", "Participant", "Admin rights may be needed for installs"),
        ("Local tools", "VS Code, Git, Python 3, Docker Desktop or approved alternative", "Participant", "Install before training"),
        ("Lab package", f"{lab_package.title()} package; multiplier {package_multiplier:.0%}", "Clahan", "Package affects resource sizing and estimate"),
        ("Usage limits", f"{hours_per_day:g} lab hours/day; resources stopped outside the lab window", "Clahan / Participant", "Storage and egress are monitored"),
        ("Support", "Provisioning, access support, and teardown as quoted", "Clahan", "Confirm the final scope before preparing a quote"),
        ("Third-party tools", "Confirm licences for any paid tools named in the TOC", "Client", "Not included in cloud estimate unless separately quoted"),
        ("Cleanup", "Delete resources, repositories, credentials, and data after training", "Clahan / Participant", "Avoid post-training cloud charges"),
    ]
    for item in requirement_rows:
        requirements_ws.append(item)
    for row in requirements_ws.iter_rows(min_row=4, max_row=requirements_ws.max_row, min_col=1, max_col=4):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for column, width in enumerate([22, 64, 26, 42], 1):
        requirements_ws.column_dimensions[get_column_letter(column)].width = width
    requirements_ws.freeze_panes = "A5"

    if include_internal_pricing:
        internal_ws = wb.create_sheet("Internal Pricing")
        internal_ws.sheet_view.showGridLines = False
        internal_ws.merge_cells("A1:D1")
        internal_ws["A1"] = f"Clahan Internal Pricing - {title}"
        internal_ws["A1"].font = Font(name="Calibri", size=16, bold=True, color=white)
        internal_ws["A1"].fill = section_fill
        internal_ws.append([])
        internal_ws.append(["Metric", "Value", "Use", "Do not send to client unless approved"])
        for cell in internal_ws[3]:
            cell.fill = header_fill
            cell.font = Font(bold=True, color=white)
        internal_rows = [
            ("Client estimate before margin", "='Lab Cost Estimate'!B10", "Client-facing total", "Use Lab Cost Estimate for normal client export"),
            ("Clahan margin", "='Assumptions'!B14", "Internal commercial margin", "Internal only"),
            ("Internal quoted amount", "=B4*(1+B5)", "Estimate plus margin", "Internal only"),
            ("Internal quoted amount per participant", "=IF('Assumptions'!B5=0,0,B6/'Assumptions'!B5)", "Per participant amount", "Internal only"),
        ]
        for item in internal_rows:
            internal_ws.append(item)
        internal_ws["B5"].number_format = "0%"
        for cell_ref in ("B4", "B6", "B7"):
            internal_ws[cell_ref].number_format = 'INR #,##0.00'
        for row in internal_ws.iter_rows(min_row=3, max_row=internal_ws.max_row, min_col=1, max_col=4):
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for column, width in enumerate([36, 24, 36, 46], 1):
            internal_ws.column_dimensions[get_column_letter(column)].width = width

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _lab_cost_to_excel(toc: Dict[str, Any], assumptions: Optional[Dict[str, Any]] = None) -> bytes:
    """Export Lab Cost using the client-approved five-sheet workbook template."""
    return _lab_cost_template_to_excel(toc, assumptions)


@router.post("/toc")
async def export_toc_workbook(payload: Dict[str, Any] = Body(...)):
    toc = payload.get("toc") if isinstance(payload.get("toc"), dict) else payload
    workbook = _toc_to_excel(toc)
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=training_toc.xlsx"},
    )


@router.post("/toc/lab-cost")
async def export_toc_lab_cost_workbook(payload: Dict[str, Any] = Body(...)):
    toc = payload.get("toc") if isinstance(payload.get("toc"), dict) else payload
    assumptions = payload.get("assumptions") if isinstance(payload.get("assumptions"), dict) else {}
    workbook = _lab_cost_to_excel(toc, assumptions)
    provider = str(assumptions.get("cloud_provider") or "aws").lower()
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={provider}_lab_cost.xlsx"},
    )


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a MongoDB document for Excel export."""
    from datetime import datetime
    result = {}
    for k, v in doc.items():
        if k in ("_id", "resume", "combined_text", "raw_text"):
            continue
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, (list, dict)):
            result[k] = str(v)
        else:
            result[k] = v
    return result


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return ""


def _shortlist_rows(shortlists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for shortlist in shortlists:
        trainers = shortlist.get("top_trainers") or []
        base = {
            "shortlist_id": shortlist.get("shortlist_id", ""),
            "requirement_id": shortlist.get("requirement_id", ""),
            "client_name": shortlist.get("client_name", ""),
            "client_email": _first_value(shortlist.get("client_email"), shortlist.get("client_contact_email")),
            "technology": _first_value(shortlist.get("technology"), shortlist.get("technology_needed"), shortlist.get("domain")),
            "training_dates": shortlist.get("training_dates", ""),
            "timeline_start": shortlist.get("timeline_start", ""),
            "timeline_end": shortlist.get("timeline_end", ""),
            "top_count": shortlist.get("top_count", len(trainers)),
            "shortlist_status": shortlist.get("status", ""),
            "shortlist_created_at": shortlist.get("created_at", ""),
            "shortlist_updated_at": shortlist.get("updated_at", ""),
        }

        if not trainers:
            rows.append(_clean(base))
            continue

        for trainer in trainers:
            row = {
                **base,
                "rank": trainer.get("rank", ""),
                "trainer_id": trainer.get("trainer_id", ""),
                "trainer_name": _first_value(trainer.get("trainer_name"), trainer.get("name")),
                "trainer_email": _first_value(trainer.get("trainer_email"), trainer.get("email")),
                "trainer_phone": _first_value(trainer.get("trainer_phone"), trainer.get("phone")),
                "linkedin": trainer.get("linkedin", ""),
                "location": trainer.get("location", ""),
                "skills": trainer.get("skills", ""),
                "technology_category": trainer.get("technology_category", ""),
                "experience_years": trainer.get("experience_years", ""),
                "score": trainer.get("score", ""),
                "match_score": trainer.get("match_score", ""),
                "pipeline_status": trainer.get("pipeline_status", ""),
                "slot_status": trainer.get("slot_status", ""),
                "toc_status": trainer.get("toc_status", ""),
                "commercial_amount": _first_value(
                    trainer.get("commercial_amount"),
                    trainer.get("trainer_commercial"),
                    trainer.get("day_rate"),
                ),
                "last_mail_type": trainer.get("last_mail_type", ""),
                "last_mailed_at": trainer.get("last_mailed_at", ""),
                "last_mail_error": trainer.get("last_mail_error", ""),
                "interview_date": trainer.get("interview_date", ""),
                "interview_link": _first_value(trainer.get("interview_link"), trainer.get("meet_link")),
                "updated_at": trainer.get("updated_at", ""),
            }
            rows.append(_clean(row))
    return rows


@router.get("/trainers")
async def export_trainers(
    limit: int = 500,
    category: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if category:
        query["technology_category"] = {"$regex": category, "$options": "i"}
    cursor = db.trainers.find(query, {"_id": 0, "resume": 0, "combined_text": 0}).limit(limit)
    rows = [_clean(d) async for d in cursor]
    try:
        xlsx = _to_excel(rows, "Trainers")
        return Response(
            content=xlsx,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=trainers.xlsx"},
        )
    except Exception as exc:
        return {"error": str(exc), "rows": rows}


@router.get("/requirements")
async def export_requirements(
    limit: int = 500,
    status: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    cursor = db.requirements.find(query, {"_id": 0}).limit(limit)
    rows = [_clean(d) async for d in cursor]
    try:
        xlsx = _to_excel(rows, "Requirements")
        return Response(
            content=xlsx,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=requirements.xlsx"},
        )
    except Exception as exc:
        return {"error": str(exc), "rows": rows}


@router.get("/shortlists")
async def export_shortlists(
    limit: int = 500,
    requirement_id: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    query: Dict[str, Any] = {}
    if requirement_id:
        query["requirement_id"] = requirement_id
    cursor = db.shortlists.find(query, {"_id": 0}).limit(limit).sort("updated_at", -1)
    rows = _shortlist_rows([d async for d in cursor])
    try:
        xlsx = _to_excel(rows, "Shortlists")
        filename = f"shortlist_{requirement_id}.xlsx" if requirement_id else "shortlists.xlsx"
        return Response(
            content=xlsx,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as exc:
        return {"error": str(exc), "rows": rows}


@router.get("/email-logs")
async def export_email_logs(
    limit: int = 500,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    cursor = db.email_logs.find({}, {"_id": 0}).limit(limit).sort("created_at", -1)
    rows = [_clean(d) async for d in cursor]
    try:
        xlsx = _to_excel(rows, "EmailLogs")
        return Response(
            content=xlsx,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=email_logs.xlsx"},
        )
    except Exception as exc:
        return {"error": str(exc), "rows": rows}


class ExcelImportRow(BaseModel):
    rows: List[Dict[str, Any]]
    collection: str


@router.post("/import")
async def import_excel_rows(
    payload: ExcelImportRow,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Bulk-insert rows from an Excel import into a named collection."""
    allowed = {"trainers", "requirements", "customers"}
    if payload.collection not in allowed:
        from fastapi import HTTPException
        raise HTTPException(400, f"Collection must be one of: {', '.join(allowed)}")
    if not payload.rows:
        return {"inserted": 0}
    from datetime import datetime
    now = datetime.utcnow()
    docs = [{**row, "created_at": now, "updated_at": now, "source": "excel_import"} for row in payload.rows]
    result = await db[payload.collection].insert_many(docs)
    return {"inserted": len(result.inserted_ids), "collection": payload.collection}
