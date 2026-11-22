"""Excel export — trainers, requirements, email logs."""
import io
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Response
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


def _topic_outline_to_excel(toc: Dict[str, Any]) -> bytes:
    """Export proposal scope without adding dates, timings, or duration."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Topic Outline"
    title = str(toc.get("title") or toc.get("domain") or "Training Topic Outline")
    sheet.merge_cells("A1:B1")
    sheet["A1"] = title
    sheet["A1"].font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor="FFFFA500")
    sheet["A1"].alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 28
    sheet.merge_cells("A3:B3")
    sheet["A3"] = "Proposal scope only. Duration, dates, and session timings are to be confirmed."
    sheet["A3"].font = Font(name="Calibri", size=10, italic=True, color="595959")
    sheet["A3"].alignment = Alignment(wrap_text=True, vertical="center")
    sheet.row_dimensions[3].height = 30
    for column, label in enumerate(("S.No.", "Training Topic"), 1):
        cell = sheet.cell(5, column, label)
        cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="FFFFA500")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    topics = toc.get("topics") or [
        day.get("focus_area") or day.get("title")
        for day in toc.get("days") or []
        if isinstance(day, dict)
    ]
    for index, topic in enumerate((item for item in topics if str(item or "").strip()), 1):
        sheet.cell(index + 5, 1, index).alignment = Alignment(horizontal="center", vertical="top")
        cell = sheet.cell(index + 5, 2, str(topic).strip())
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.row_dimensions[index + 5].height = 30
    sheet.column_dimensions["A"].width = 10
    sheet.column_dimensions["B"].width = 100
    sheet.freeze_panes = "A6"
    sheet.auto_filter.ref = f"A5:B{max(5, 5 + len(topics))}"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


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

    # Preserve the approved 8-column ToC template, including
    # day, date, weekday, timing, topic, subtopics, lab, and outcomes.
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:H{max(sheet.max_row, len(days) + 1)}"
    sheet.print_area = sheet.auto_filter.ref
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _toc_to_course_workbook(toc: Dict[str, Any]) -> bytes:
    """Ten-sheet course workbook built from the validated curriculum.

    Sheets: Contents, Course Overview, Course Outline, Module Outcomes, Topic
    Breakdown, Labs & Deliverables, Day-wise Schedule (multi-day only),
    Assessment (with lab rubrics, pass rule and knowledge checks), Lab
    Environment and Trainer & Support.

    ``Module No.`` is the shared key across sheets. Course Outline totals its
    hours with a SUM formula and Course Overview reads that total. A module
    with an authored ``outline.design`` block fills every column; other
    modules use the standard 7-hour split and leave unknown cells blank rather
    than invent content. Client text is written as data, never as a formula.
    """
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    PURPLE, DEEP, INK, BAND, MUTED = "FF5B21B6", "FF2E1065", "FF1F2937", "FFF3EEFF", "FF6B7280"
    edge = Side(style="thin", color="E5E0F2")
    border = Border(left=edge, right=edge, top=edge, bottom=edge)
    TBC = "To be confirmed"
    # The agreed split of a 7-hour module day (minutes), scaled to the module length.
    STANDARD_SPLIT = (("Concepts", 90, "discussion"), ("Demonstrations", 60, "demo"), ("Main lab", 150, "lab"),
                      ("Troubleshooting a seeded failure", 60, "lab"), ("Knowledge check and recap", 60, "discussion"))
    CAPSTONE_SPLIT = (("Capstone build", 270, "lab"), ("Presentation and defence", 90, "discussion"),
                      ("Review and feedback", 60, "discussion"))
    ASSESSMENT_RE = re.compile(r"knowledge check|quiz|recap|presentation|defen[cs]e|review and feedback", re.I)

    def text(value: Any) -> str:
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(i).strip().rstrip(".") for i in value if str(i).strip())
        if isinstance(value, dict):
            return text(value.get("topic") or value.get("title") or value.get("name") or value.get("text"))
        return str(value or "").strip()

    def lines(value: Any) -> List[str]:
        if isinstance(value, (list, tuple, set)):
            items = [text(i) for i in value]
        else:
            items = re.split(r"[\n;]+", str(value or ""))
        return [i.strip().rstrip(".") for i in items if i and i.strip()]

    def scaled(parts, total):
        base = sum(minutes for _, minutes, _ in parts)
        values = [round(minutes * total / base) for _, minutes, _ in parts]
        values[-1] += total - sum(values)
        return values

    def hhmm(minutes_from_midnight: int) -> str:
        return f"{(minutes_from_midnight // 60) % 24:02d}:{minutes_from_midnight % 60:02d}"

    def numbered(value: str, module_no: int) -> str:
        # Authored designs say "Lab check" or "Lab:"; number them for this module's position.
        return re.sub(r"\bLab(?=\s+checks?\b|:)", f"Lab {module_no}", value)

    # Modules without a design are filled from their own course-dataset checks and objectives,
    # by rules only: nothing is invented, so a cell stays blank when the dataset has no source.
    STOP = {"with", "from", "that", "this", "your", "into", "after", "before", "using", "when", "each",
            "their", "them", "then", "they", "what", "which", "while", "about", "every", "without", "between",
            "shown", "show", "make", "made", "only", "same", "other", "than", "more", "most", "used", "uses"}
    FAILURE_RE = re.compile(r"#[A-Z0-9/]+!?|\b(?:errors?|fails?|failed|failure|denied|rejected|refused|blocked|"
                            r"exceptions?|rolls?\s+back|rolled\s+back|warnings?|violations?|alerts?\s+fires?|crash(?:es)?)\b",
                            re.I)

    def check_parts(item: Any):
        """(what to do, expected result, evidence) from a dataset check in any stored shape."""
        if isinstance(item, dict):
            return (text(item.get("input_or_condition") or item.get("check")), text(item.get("expected_result")),
                    text(item.get("evidence")))
        if isinstance(item, (list, tuple)):
            values = [text(value) for value in item] + ["", "", ""]
            return values[0], values[1], values[2]
        return text(item), "", ""

    def stems(value: str) -> set:
        return {word[:5] for word in re.findall(r"[a-z0-9]+", value.lower()) if len(word) > 3 and word not in STOP}

    # Objectives that start with one of these verbs read as a question ("How would you restore ...?").
    VERBS = set("""analyse analyze apply assess automate back build calculate choose clean collect compare
        configure connect create debug decide define deploy describe design detect diagnose distinguish document
        enable estimate evaluate explain export filter find fix format handle identify implement import improve
        install integrate interpret investigate load maintain manage map measure migrate model monitor navigate
        optimise optimize organise organize perform plan prepare present prevent prioritise prioritize protect
        query read recover reduce refactor report resolve restore review run save scale schedule secure select
        set share solve store structure summarise summarize test track transform troubleshoot tune update
        upgrade use validate verify visualise visualize write""".split())

    def matched_check(objective: str, checks: List[tuple], module_no: int) -> str:
        """The module's lab check that tests this objective, or '' when that is not clear.

        A link needs two shared words and one clear best check; a single shared word linked
        unrelated pairs ("Monitor identity activity" to "Collect") across the dataset.
        """
        wanted = stems(objective)
        scored = sorted(((len(wanted & stems(f"{c} {e}")), -index) for index, (c, e, _) in enumerate(checks)),
                        reverse=True)
        if not scored or scored[0][0] < 2 or (len(scored) > 1 and scored[1][0] == scored[0][0]):
            return ""
        return f"Lab {module_no} check: {checks[-scored[0][1]][0]}"

    def derived_rubric(checks: List[tuple]) -> List[List[str]]:
        rows = []
        for condition, expected, evidence in checks:
            if not (condition and expected):
                continue
            proof = f", evidence: {evidence}" if evidence else ""
            rows.append([condition, f"{expected}; done without help{proof}", f"{expected}; done with a hint",
                         "Attempted; the result is incomplete", "Not attempted or not working"])
        return rows[:5]

    def derived_quiz(checks: List[tuple], objectives: List[str], subtopics: List[str]) -> List[str]:
        questions = [f"{condition.rstrip('.')}: what result should you see, and how do you show it?"
                     for condition, expected, _ in checks if condition and expected]
        for objective in objectives:
            verb, _, rest = objective.rstrip(".").partition(" ")
            if verb.lower() in VERBS and rest:
                questions.append(f"How would you {verb.lower()} {rest}?")
        for subtopic in subtopics:
            if len(questions) >= 5 or len(questions) < 2:
                break  # sub-topic questions only top up a module that has its own specific questions
            questions.append(f"Explain, with an example from this module's lab: {subtopic.rstrip('.')}.")
        return list(dict.fromkeys(questions))[:6]

    days = list(toc.get("days") or [])
    try:
        hours_per_day = int(toc.get("hours_per_day") or 7)
    except (TypeError, ValueError):
        hours_per_day = 7
    course_name = text(toc.get("title") or toc.get("domain") or "Training Programme")
    level = text(toc.get("level")).replace("_", " ").title()
    mode = text(toc.get("mode")) or "Online"

    # One module model, reused by every sheet (Module No. is the shared key).
    modules = []
    for i, day in enumerate(days, 1):
        outline = day.get("outline") if isinstance(day.get("outline"), dict) else {}
        lab = outline.get("lab") if isinstance(outline.get("lab"), dict) else {}
        # A hand-authored outline design wins over a model-drafted day design.
        design = next((value for value in (outline.get("design"), day.get("design")) if isinstance(value, dict) and value), {})
        topic = text(day.get("focus_area") or day.get("module") or day.get("title") or day.get("topic")) or f"Module {i}"
        subs = lines(day.get("subtopics"))
        if not subs:
            for module in day.get("modules") or []:
                subs += lines(module.get("subtopics"))
        lab_text = text(day.get("lab") or day.get("lab_task"))
        lab_title = text(lab.get("title"))
        if not lab_title:
            head = lab_text.split(":", 1)[0].strip() if ":" in lab_text else ""
            lab_title = head if head and len(head) <= 60 else f"{topic} Lab"
        tasks = lines(lab.get("tasks")) or lines(lab_text.split(":", 1)[1] if ":" in lab_text else lab_text)
        seeded = design.get("seeded_failure") if isinstance(design.get("seeded_failure"), dict) else {}
        checks = day.get("acceptance_checks") or lab.get("verify") or day.get("checks") or []
        if not isinstance(checks, list):
            checks = []
        dataset_checks = [parts for parts in (check_parts(item) for item in checks) if parts[0]]
        success = ""
        if dataset_checks:
            success = dataset_checks[0][1] or dataset_checks[0][0]
        if not success:
            success = text(day.get("assessment")).split("\n")[0]
        try:
            minutes = int(day.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        minutes = minutes or hours_per_day * 60
        is_capstone = "capstone" in topic.lower()

        rows = []
        if isinstance(design.get("topics"), list) and design["topics"]:
            authored = [item for item in design["topics"] if isinstance(item, dict) and int(item.get("minutes") or 0) > 0]
            # Keep Topic Breakdown in step with Course Outline if this ToC changed the module length.
            authored_minutes = scaled([(None, int(item["minutes"]), None) for item in authored], minutes) if authored else []
            for item, item_minutes in zip(authored, authored_minutes):
                rows.append({"topic": numbered(text(item.get("topic")), i), "subs": lines(item.get("subtopics")),
                             "minutes": item_minutes, "mode": text(item.get("mode")) or "discussion",
                             "failure": text(item.get("failure_scenario")), "practice": text(item.get("best_practice"))})
        else:
            parts = CAPSTONE_SPLIT if is_capstone else STANDARD_SPLIT
            half = (len(subs) + 1) // 2
            for (name, _, part_mode), part_minutes in zip(parts, scaled(parts, minutes)):
                if name == "Concepts":
                    part_subs = subs[:half]
                elif name == "Demonstrations":
                    part_subs = subs[half:]
                elif name in ("Main lab", "Capstone build"):
                    name, part_subs = f"Lab {i}: {lab_title}", tasks
                else:
                    part_subs = []
                failure = ""
                if name == "Troubleshooting a seeded failure":
                    # A dataset check whose expected result is an error is the module's planned failure.
                    failure = next((f"{c}: {e}" for c, e, _ in dataset_checks if e and FAILURE_RE.search(e)), "")
                rows.append({"topic": name, "subs": part_subs, "minutes": part_minutes, "mode": part_mode,
                             "failure": failure, "practice": ""})

        outcomes = []
        for item in design.get("outcomes") or []:
            if isinstance(item, dict) and text(item.get("outcome")):
                outcomes.append((text(item.get("outcome")), numbered(text(item.get("assessed_by")), i) or f"Lab {i} checks"))
        if not outcomes:
            outcomes = [(obj, matched_check(obj, dataset_checks, i) or f"Lab {i} checks")
                        for obj in lines(day.get("learning_objectives") or day.get("objectives"))[:5]]
        if not outcomes:
            outcomes = [(f"Complete Lab {i}: {lab_title}", f"Lab {i} rubric")]

        modules.append({
            "no": i, "name": topic, "day": day.get("day") or i, "minutes": minutes,
            "hrs": round(minutes / 60, 1) if minutes % 60 else minutes // 60, "subs": subs,
            "lab_title": lab_title, "tasks": tasks, "seeded": seeded,
            "scenario": text(lab.get("scenario") or day.get("scenario")),
            "deliverable": text(lab.get("deliverables") or day.get("deliverable")),
            "success": success, "objectives": lines(day.get("learning_objectives") or day.get("objectives")),
            "is_capstone": is_capstone, "rows": rows, "outcomes": outcomes,
            "quiz": lines(design.get("quiz")) or ([] if is_capstone else derived_quiz(
                dataset_checks, lines(day.get("learning_objectives") or day.get("objectives")), subs)),
            "rubric": [r for r in design.get("lab_rubric") or [] if isinstance(r, (list, tuple)) and len(r) == 5]
            or derived_rubric(dataset_checks),
            "environment": [e for e in design.get("lab_environment") or [] if isinstance(e, dict) and text(e.get("tool"))],
            "tools": lines(day.get("tools")),
        })

    num_days = len({m["day"] for m in modules})
    multi_day = num_days > 1

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    def new_sheet(name: str):
        sheet = wb.create_sheet(name)
        sheet.sheet_view.showGridLines = False
        return sheet

    def put(sheet, r, c, value, *, bold=False, size=10, color=INK, fill=None,
            wrap=True, align="left", valign="top", data=True, bordered=True, italic=False):
        cell = sheet.cell(r, c, value)
        if data and isinstance(value, str):
            cell.data_type = "s"  # client text is data, never a formula
        cell.font = Font(name="Calibri", size=size, bold=bold, italic=italic, color=color)
        if fill:
            cell.fill = PatternFill("solid", fgColor=fill)
        cell.alignment = Alignment(horizontal=align, vertical=valign, wrap_text=wrap)
        if bordered:
            cell.border = border
        return cell

    def formula(sheet, r, c, expr, *, bold=False, align="center", color=INK):
        cell = sheet.cell(r, c, expr)  # kept as a formula on purpose
        cell.font = Font(name="Calibri", size=10, bold=bold, color=color)
        cell.alignment = Alignment(horizontal=align, vertical="center")
        cell.border = border
        return cell

    def table_header(sheet, r, headers):
        for c, head in enumerate(headers, 1):
            put(sheet, r, c, head, bold=True, size=11, color="FFFFFFFF", fill=PURPLE, align="center", valign="center")

    def section(sheet, r, label, ncols):
        sheet.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        put(sheet, r, 1, label, bold=True, size=12, color=DEEP, valign="center", bordered=False)

    def title_block(sheet, ncols, subtitle):
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
        put(sheet, 1, 1, course_name, bold=True, size=16, color=PURPLE, align="left", valign="center", bordered=False)
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncols)
        put(sheet, 2, 1, subtitle, bold=True, size=11, color=DEEP, align="left", valign="center", bordered=False)

    def zebra(sheet, r, ncols, index):
        fill = PatternFill("solid", fgColor=BAND if index % 2 else "FFFFFFFF")
        for c in range(1, ncols + 1):
            sheet.cell(r, c).fill = fill

    def widths(sheet, values):
        for c, w in enumerate(values, 1):
            sheet.column_dimensions[get_column_letter(c)].width = w

    order = ["Contents", "Course Overview", "Course Outline", "Module Outcomes", "Topic Breakdown",
             "Labs & Deliverables"]
    if multi_day:
        order.append("Day-wise Schedule")
    order += ["Assessment", "Lab Environment", "Trainer & Support"]

    # 1. Contents
    contents = new_sheet("Contents")
    title_block(contents, 2, "Contents")
    table_header(contents, 4, ["#", "Sheet"])
    for i, name in enumerate(order, 1):
        put(contents, 4 + i, 1, i, align="center")
        link = formula(contents, 4 + i, 2, f"=HYPERLINK(\"#'{name}'!A1\",\"{name}\")", align="left", color=PURPLE)
        link.font = Font(name="Calibri", size=11, color=PURPLE, underline="single")
    widths(contents, [6, 42])

    # 3. Course Outline (built before Overview so its total cell is known)
    outline_ws = new_sheet("Course Outline")
    title_block(outline_ws, 7, "Course Outline")
    oh = 4
    table_header(outline_ws, oh, ["Module No.", "Module Name", "Day", "Duration (hrs)",
                                  "Topics Covered", "Lab Reference", "Participant Output"])
    for i, m in enumerate(modules, 1):
        r = oh + i
        put(outline_ws, r, 1, m["no"], align="center")
        put(outline_ws, r, 2, m["name"])
        put(outline_ws, r, 3, m["day"], align="center")
        put(outline_ws, r, 4, m["hrs"], align="center", data=False)
        put(outline_ws, r, 5, "\n".join(m["subs"]) or m["name"])
        put(outline_ws, r, 6, f"Lab {m['no']}", align="center")
        put(outline_ws, r, 7, m["deliverable"] or "Working result and notes")
        zebra(outline_ws, r, 7, i)
    total_row = oh + len(modules) + 1
    put(outline_ws, total_row, 3, "Total", bold=True, align="right")
    if modules:
        formula(outline_ws, total_row, 4, f"=SUM(D{oh + 1}:D{oh + len(modules)})", bold=True)
    widths(outline_ws, [11, 30, 6, 13, 60, 13, 40])
    outline_ws.freeze_panes = outline_ws.cell(oh + 1, 1)
    total_ref = f"'Course Outline'!D{total_row}"

    # 2. Course Overview
    overview = new_sheet("Course Overview")
    title_block(overview, 2, "Course Overview")
    certifications = "\n".join(lines(toc.get("certification_roadmap") or toc.get("certifications")))
    facts = [
        ("Course Name", course_name),
        ("Duration (hours)", f"={total_ref}"),
        ("Number of Days", num_days),
        ("Level", level or TBC),
        ("Audience", text(toc.get("audience_level")) or ((level + " engineers") if level else "Professional engineers")),
        ("Prerequisites", "\n".join(lines(toc.get("prerequisites"))) or TBC),
        ("Delivery Mode", mode),
        ("Tools Required", "\n".join(lines(toc.get("tools_software") or toc.get("tools"))) or TBC),
        ("Certificate", text(toc.get("certificate")) or "Certificate of completion"),
        ("Target Certifications", certifications or TBC),
    ]
    r = 4
    for label, value in facts:
        put(overview, r, 1, label, bold=True, fill=BAND, valign="center")
        if isinstance(value, str) and value.startswith("="):
            formula(overview, r, 2, value, align="left")  # reads the total from Course Outline
        else:
            put(overview, r, 2, value, valign="center")
        r += 1
    r += 1
    section(overview, r, "Learning Objectives", 2)
    r += 1
    objectives = lines(toc.get("learning_outcomes") or toc.get("learning_objectives"))
    if not objectives:
        for m in modules:
            for obj in m["objectives"]:
                if obj not in objectives:
                    objectives.append(obj)
    for i, obj in enumerate(objectives[:15], 1):  # 12-15 "can do" statements, not 58
        put(overview, r, 1, i, align="center")
        put(overview, r, 2, obj)
        r += 1
    widths(overview, [24, 82])

    # 4. Module Outcomes
    outcomes_ws = new_sheet("Module Outcomes")
    title_block(outcomes_ws, 3, "Module Outcomes")
    table_header(outcomes_ws, 4, ["Module No.", "Outcome", "Assessed By"])
    r = 4
    for m in modules:
        for outcome, assessed_by in m["outcomes"]:
            r += 1
            put(outcomes_ws, r, 1, m["no"], align="center")
            put(outcomes_ws, r, 2, outcome)
            put(outcomes_ws, r, 3, assessed_by)
            zebra(outcomes_ws, r, 3, m["no"])
    widths(outcomes_ws, [11, 80, 40])
    outcomes_ws.freeze_panes = outcomes_ws.cell(5, 1)

    # 5. Topic Breakdown
    topics_ws = new_sheet("Topic Breakdown")
    title_block(topics_ws, 7, "Topic Breakdown")
    th = 4
    table_header(topics_ws, th, ["Module No.", "Topic", "Sub-topics", "Minutes", "Mode",
                                 "Failure Scenario", "Best Practice"])
    r = th
    for m in modules:
        for row in m["rows"]:
            r += 1
            put(topics_ws, r, 1, m["no"], align="center")
            put(topics_ws, r, 2, row["topic"])
            put(topics_ws, r, 3, "\n".join(row["subs"]))
            put(topics_ws, r, 4, row["minutes"], align="center", data=False)
            put(topics_ws, r, 5, row["mode"], align="center")
            put(topics_ws, r, 6, row["failure"])
            put(topics_ws, r, 7, row["practice"])
            zebra(topics_ws, r, 7, m["no"])
    if r > th:
        put(topics_ws, r + 1, 3, "Total minutes", bold=True, align="right")
        formula(topics_ws, r + 1, 4, f"=SUM(D{th + 1}:D{r})", bold=True)
    widths(topics_ws, [11, 32, 48, 9, 11, 42, 42])
    topics_ws.freeze_panes = topics_ws.cell(th + 1, 1)

    # 6. Labs & Deliverables
    labs_ws = new_sheet("Labs & Deliverables")
    title_block(labs_ws, 7, "Labs & Deliverables")
    lh = 4
    table_header(labs_ws, lh, ["Lab No.", "Lab Name", "Module No.", "Scenario",
                               "Tasks Participants Do", "Deliverable", "Success Measure"])
    for i, m in enumerate(modules, 1):
        r = lh + i
        task_lines = list(m["tasks"])
        if text(m["seeded"].get("symptom")):
            # Participants see the symptom; the cause and fix stay with the trainer.
            task_lines.append("Troubleshoot the seeded failure: " + text(m["seeded"].get("symptom")))
        put(labs_ws, r, 1, f"Lab {m['no']}", align="center")
        put(labs_ws, r, 2, m["lab_title"])
        put(labs_ws, r, 3, m["no"], align="center")
        put(labs_ws, r, 4, m["scenario"] or "Applied to a realistic training scenario.")
        put(labs_ws, r, 5, "\n".join(task_lines) if task_lines else "Guided, hands-on practice.")
        put(labs_ws, r, 6, m["deliverable"] or "Working result and notes")
        put(labs_ws, r, 7, m["success"] or "Trainer confirms the output meets the brief")
        zebra(labs_ws, r, 7, i)
    widths(labs_ws, [9, 28, 11, 42, 56, 36, 40])
    labs_ws.freeze_panes = labs_ws.cell(lh + 1, 1)

    # 7. Day-wise Schedule (multi-day only): Theory / Lab / Assessment blocks from the topic minutes.
    if multi_day:
        sched = new_sheet("Day-wise Schedule")
        title_block(sched, 6, "Day-wise Schedule")
        sh = 4
        table_header(sched, sh, ["Day", "Start", "End", "Module No.", "Module Name", "Session Type"])
        r = sh
        lunch = 60 if hours_per_day >= 6 else 0
        # Lab time on the schedule is the lab-access time the Lab Cost Estimate prices, so the two always agree.
        from shared.lab_cost_inputs import course_workbook_lab_hours
        priced_lab_minutes = round(course_workbook_lab_hours(hours_per_day) * 60)
        for m in modules:
            blocks = []
            for row in m["rows"]:
                kind = "Assessment" if ASSESSMENT_RE.search(row["topic"]) else ("Lab" if row["mode"] == "lab" else "Theory")
                if blocks and blocks[-1][0] == kind:
                    blocks[-1][1] += row["minutes"]
                else:
                    blocks.append([kind, row["minutes"]])
            lab_minutes = sum(b[1] for b in blocks if b[0] == "Lab")
            if lab_minutes and not m["is_capstone"] and m["minutes"] == hours_per_day * 60 and lab_minutes != priced_lab_minutes:
                # Move the difference to theory so the day length stays the same.
                for block in blocks:
                    if block[0] == "Lab":
                        block[1] = round(block[1] * priced_lab_minutes / lab_minutes)
                theory = next((b for b in blocks if b[0] == "Theory"), None)
                if theory:
                    theory[1] += m["minutes"] - sum(b[1] for b in blocks)
            clock, taught, lunch_taken = 9 * 60, 0, not lunch
            for kind, block_minutes in blocks:
                if not lunch_taken and taught >= 120:  # lunch after the morning theory block
                    clock += lunch
                    lunch_taken = True
                r += 1
                put(sched, r, 1, m["day"], align="center")
                put(sched, r, 2, hhmm(clock), align="center", data=False)
                put(sched, r, 3, hhmm(clock + block_minutes), align="center", data=False)
                put(sched, r, 4, m["no"], align="center")
                put(sched, r, 5, m["name"])
                put(sched, r, 6, kind, align="center")
                zebra(sched, r, 6, m["no"])
                clock += block_minutes
                taught += block_minutes
        widths(sched, [6, 9, 9, 11, 34, 16])
        sched.freeze_panes = sched.cell(sh + 1, 1)

    # 8. Assessment: weighted items, pass rule, lab rubrics and knowledge checks.
    assess = new_sheet("Assessment")
    title_block(assess, 5, "Assessment")
    ah = 4
    table_header(assess, ah, ["Assessment Item", "Weight %", "Pass Mark", "Modules Covered", "Evidence"])
    capstone = next((m for m in modules if m["is_capstone"]), None)
    non_capstone = [m for m in modules if not m["is_capstone"]]
    span = f"1-{len(modules)}" if modules else "-"
    items = []
    if non_capstone:
        lab_span = f"1-{non_capstone[-1]['no']}"
        if capstone:
            items.append(("Lab deliverables (rubric)", 50, "50%", lab_span, "Completed lab deliverables scored against the lab rubric"))
            items.append(("Knowledge checks", 10, "60%", lab_span, "End-of-module quiz results"))
        else:
            items.append(("Lab deliverables (rubric)", 60, "50%", lab_span, "Completed lab deliverables scored against the lab rubric"))
            items.append(("Knowledge checks", 10, "60%", lab_span, "End-of-module quiz results"))
    if capstone:
        items.append(("Capstone project", 30, "60%", str(capstone["no"]), "Capstone build, presentation and defence"))
        items.append(("Final review", 10, "50%", span, "Capstone review and Q&A"))
    else:
        items.append(("Final assessment", 30 if non_capstone else 100, "60%", span, "End-of-course assessment results"))
    for i, (item, weight, pass_mark, mods, evidence) in enumerate(items, 1):
        r = ah + i
        put(assess, r, 1, item)
        put(assess, r, 2, weight, align="center", data=False)
        put(assess, r, 3, pass_mark, align="center")
        put(assess, r, 4, mods, align="center")
        put(assess, r, 5, evidence)
        zebra(assess, r, 5, i)
    r = ah + len(items) + 1
    put(assess, r, 1, "Total", bold=True, align="right")
    formula(assess, r, 2, f"=SUM(B{ah + 1}:B{ah + len(items)})", bold=True)

    r += 2
    assess.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
    rule = "Pass rule: an overall weighted score of 60% or more and no lab scored 1 (Not met)"
    put(assess, r, 1, rule + (", and the capstone passed." if capstone else "."), bold=True, bordered=False)

    rubric_headers = ["Criterion", "4 - Exceeds", "3 - Meets", "2 - Partly meets", "1 - Not met"]
    for m in modules:
        if not m["rubric"]:
            continue
        r += 2
        section(assess, r, f"Lab {m['no']} Rubric: {m['lab_title']}", 5)
        r += 1
        table_header(assess, r, rubric_headers)
        for index, criterion in enumerate(m["rubric"], 1):
            r += 1
            for c, value in enumerate(criterion, 1):
                put(assess, r, c, text(value), bold=c == 1)
            zebra(assess, r, 5, index)
    standard_rubric = [
        ("Working result", "All tasks complete and verified against the success measure", "Core tasks complete and verified",
         "Some tasks complete", "Lab not completed"),
        ("Troubleshooting", "Seeded failure diagnosed and fixed without help, with evidence", "Fixed with a hint",
         "Symptom found but not fixed", "Not attempted"),
        ("Evidence", "Deliverable complete and clearly documented", "Deliverable complete",
         "Deliverable partly complete", "No deliverable"),
        ("Best practice", "Applies the module's best practices and explains why", "Applies most best practices",
         "Applies some best practices", "Best practices not applied"),
    ]
    r += 2
    authored = any(m["rubric"] for m in modules)
    section(assess, r, "Standard Lab Rubric (all other labs)" if authored else "Lab Rubric (every lab)", 5)
    r += 1
    table_header(assess, r, rubric_headers)
    for index, criterion in enumerate(standard_rubric, 1):
        r += 1
        for c, value in enumerate(criterion, 1):
            put(assess, r, c, value, bold=c == 1)
        zebra(assess, r, 5, index)

    quiz_rows = [(m["no"], q) for m in modules for q in m["quiz"]]
    if quiz_rows:
        r += 2
        section(assess, r, "Knowledge Check Questions", 5)
        r += 1
        table_header(assess, r, ["Module No.", "Question"])
        assess.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
        for index, (module_no, question) in enumerate(quiz_rows, 1):
            r += 1
            put(assess, r, 1, module_no, align="center")
            assess.merge_cells(start_row=r, start_column=2, end_row=r, end_column=5)
            put(assess, r, 2, question)
            zebra(assess, r, 2, index)  # style only real cells, not the merged range
    widths(assess, [30, 30, 30, 30, 52])

    # 9. Lab Environment: authored rows first, then any other course tools.
    env_ws = new_sheet("Lab Environment")
    title_block(env_ws, 5, "Lab Environment")
    table_header(env_ws, 4, ["Tool", "Version", "Account or Access", "Setup Owner", "Cost per Participant"])
    seen, env_rows = set(), []
    for m in modules:
        for item in m["environment"]:
            key = re.sub(r"[^a-z0-9]+", " ", text(item.get("tool")).lower()).strip()
            if key and key not in seen:
                seen.add(key)
                env_rows.append([text(item.get("tool")), text(item.get("version")) or TBC, text(item.get("access")) or TBC,
                                 text(item.get("setup_owner")) or TBC, text(item.get("cost")) or TBC])
    other_tools = lines(toc.get("tools_software") or toc.get("tools")) + [t for m in modules for t in m["tools"]]
    for tool in other_tools:
        for part in re.split(r"\s+\+\s+", tool):
            key = re.sub(r"[^a-z0-9]+", " ", part.lower()).strip()
            if not key or re.fullmatch(r"all .*tools?", key):
                continue  # dataset filler such as "All DevOps Tools" is not a tool
            if any(existing.startswith(key + " ") for existing in seen):
                continue  # "Docker" is already covered by the authored "Docker Engine" row
            if key not in seen:
                seen.add(key)
                env_rows.append([part.strip(), TBC, TBC, TBC, TBC])
    for index, values in enumerate(env_rows, 1):
        for c, value in enumerate(values, 1):
            put(env_ws, 4 + index, c, value, color=MUTED if value == TBC else INK, italic=value == TBC)
        zebra(env_ws, 4 + index, 5, index)
    widths(env_ws, [28, 24, 40, 30, 40])
    env_ws.freeze_panes = env_ws.cell(5, 1)

    # 10. Trainer & Support
    support = new_sheet("Trainer & Support")
    title_block(support, 3, "Trainer & Support")
    table_header(support, 4, ["Trainer Profile", "Batch Size", "Post-training Support"])
    try:
        participants = int(toc.get("participant_count") or 0)
    except (TypeError, ValueError):
        participants = 0
    put(support, 5, 1, text(toc.get("trainer_profile_summary")) or "Shared separately in the trainer profile")
    put(support, 5, 2, f"{participants} participants" if participants > 0 else TBC, align="center")
    put(support, 5, 3, text(toc.get("post_training_support")) or "To be confirmed with the client")
    widths(support, [48, 18, 48])

    wb._sheets = [wb[name] for name in order]  # exact sheet order
    wb.active = 0
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _toc_to_excel(toc: Dict[str, Any]) -> bytes:
    """Export AI and manual ToCs in their respective user-approved templates."""
    if toc.get("topic_only"):
        return _topic_outline_to_excel(toc)
    if toc.get("excel_layout") in ("course_workbook", "daily_plan"):
        return _toc_to_course_workbook(toc)
    from shared.toc_layouts import REFERENCE_LAYOUTS
    if toc.get("excel_layout") in REFERENCE_LAYOUTS:
        from app.toc_reference_excel import render_reference_toc
        return render_reference_toc(toc)
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
    """Populate lab-cost calculations and the concise day-wise client view."""
    import openpyxl
    from copy import copy

    if not LAB_COST_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Lab Cost template is missing: {LAB_COST_TEMPLATE_PATH}")

    from shared.lab_cost_inputs import validate_lab_cost_inputs, lab_resources
    try:
        values = validate_lab_cost_inputs(assumptions)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
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
        from shared.lab_curriculum import cloud_lab_text
        return cloud_lab_text(day)

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
    if not 1 <= duration_days <= 30:
        raise ValueError("Lab cost estimates support training durations from 1 to 30 days")
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
    assumptions_ws["B11"] = as_number("egress_gb", 0, 0)
    assumptions_ws["B12"] = as_number("build_minutes", 0, 0)
    assumptions_ws["B13"] = as_number("monitoring_gb", 0, 0)
    assumptions_ws["B14"] = as_positive_int("k8s_worker_nodes", 1)
    assumptions_ws["B15"] = as_number("fx_rate", 84, 0.01)
    assumptions_ws["B16"] = as_number("contingency_percent", 10, 0) / 100
    # India is the default billing context for the approved regional rate
    # card. A caller may still supply a validated exemption/different rate.
    assumptions_ws["B17"] = as_number("tax_percent", 0, 0) / 100
    package = str(values.get("lab_package") or "standard").strip().lower()
    assumptions_ws["B18"] = package.title() if package in {"basic", "standard", "advanced"} else "Standard"
    assumptions_ws["B19"] = as_positive_int("quote_validity_days", 7)
    # Lab workbooks are client quotations. Apply Clahan's standard service
    # uplift to the final client amount; raw provider cost remains part of
    # the calculation/audit trail, not the amount offered to the client.
    client_lab_markup_percent = values["clahan_margin_percent"]
    if client_lab_markup_percent > 100:
        raise ValueError("client_lab_markup_percent cannot exceed 100")
    # Keep the markup factor out of visible client cells and the formula bar.
    # The client sees only the resulting estimate on the Client Estimate sheet.
    internal_calc_ws = workbook.create_sheet("Internal Calculation")
    internal_calc_ws["A1"] = "Client adjustment factor"
    internal_calc_ws["B1"] = client_lab_markup_percent / 100
    internal_calc_ws["B1"].number_format = "0%"
    internal_calc_ws.sheet_state = "veryHidden"

    # The supplied template owns the entire visual structure.  Replace only
    # its example mapping rows with one accurately mapped row per ToC day.
    mapping_ws = workbook["TOC Mapping"]
    body_styles = [copy(mapping_ws.cell(4, min(column, 8))._style) for column in range(1, 12)]
    body_alignments = [copy(mapping_ws.cell(4, min(column, 8)).alignment) for column in range(1, 12)]
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
    mapping_ws.cell(3, 9, "Active days")
    mapping_ws.cell(3, 9)._style = copy(mapping_ws.cell(3, 8)._style)
    mapping_ws.cell(3, 9).alignment = copy(mapping_ws.cell(3, 8).alignment)
    mapping_ws.column_dimensions["I"].width = 13
    mapping_ws.cell(3, 10, "Storage PUT requests / day")
    mapping_ws.cell(3, 11, "Storage GET requests / day")
    for column in (10, 11):
        mapping_ws.cell(3, column)._style = copy(mapping_ws.cell(3, 8)._style)
        mapping_ws.cell(3, column).alignment = copy(mapping_ws.cell(3, 8).alignment)
    mapping_ws.column_dimensions["J"].width = 24
    mapping_ws.column_dimensions["K"].width = 24

    # `lab_day_mapping` is the auditable hand-off from a trainer/client lab
    # template. It may be keyed by 1-based day number or provided as a list.
    # When supplied, exact template counts always override keyword inference.
    supplied_mapping = values.get("lab_day_mapping") or {}

    def template_mapping(day_number: int) -> Dict[str, Any]:
        if isinstance(supplied_mapping, list):
            item = supplied_mapping[day_number - 1] if day_number <= len(supplied_mapping) else {}
        elif isinstance(supplied_mapping, dict):
            item = supplied_mapping.get(day_number) or supplied_mapping.get(str(day_number)) or {}
        else:
            item = {}
        return item if isinstance(item, dict) else {}

    def mapped_quantity(mapping: Dict[str, Any], key: str, fallback: Any) -> Any:
        value = mapping.get(key, fallback)
        if isinstance(value, str) and value.startswith("="):
            return value
        try:
            return max(0, float(value) if key == "object_storage_gb" else int(value))
        except (TypeError, ValueError):
            return fallback

    for index, day in enumerate(days, 1):
        row = index + 3
        text = day_text(day)
        resources = lab_resources(text)
        template = template_mapping(index)
        k8s_needed = resources["k8s"]
        database_needed = resources["database"]
        storage_needed = resources["storage"]
        heavy_vm = resources["heavy"]
        vm_needed = resources["vm"]
        row_values = [
            index,
            day_title(day, index),
            mapped_quantity(template, "vm_qty", "=Assumptions!$B$9" if vm_needed else 0),
            str(template.get("vm_profile") or ("Heavy" if heavy_vm else ("Light" if vm_needed else "None"))).title(),
            mapped_quantity(template, "k8s_control_plane", 1 if k8s_needed else 0),
            # A managed cluster has a fixed worker count. Never multiply it
            # by participants unless the supplied lab template explicitly does.
            mapped_quantity(template, "k8s_worker_nodes", "=Assumptions!$B$14" if k8s_needed else 0),
            # One managed database is billed per provisioned instance, not per learner.
            mapped_quantity(template, "managed_db", 1 if database_needed else 0),
            mapped_quantity(template, "object_storage_gb", "=Assumptions!$B$10" if storage_needed else 0),
            mapped_quantity(template, "active_days", max(1, int(float(day.get("duration_days") or day.get("days") or 1)))),
            mapped_quantity(template, "storage_put_requests", int(values.get("participant_count", 1) * values.get("storage_put_requests_per_participant_day", 1)) if storage_needed else 0),
            mapped_quantity(template, "storage_get_requests", int(values.get("participant_count", 1) * values.get("storage_get_requests_per_participant_day", 10)) if storage_needed else 0),
        ]
        for column, value in enumerate(row_values, 1):
            cell = mapping_ws.cell(row, column, value)
            cell._style = copy(body_styles[column - 1])
            cell.alignment = copy(body_alignments[column - 1])
        mapping_ws.row_dimensions[row].height = body_row_height

    mapping_end_row = len(days) + 3
    mapping_table = mapping_ws.tables.get("TOCMappingTable")
    if mapping_table:
        mapping_table.ref = f"A3:K{mapping_end_row}"
    note_title_row = mapping_end_row + 2
    note_body_row = note_title_row + 1
    mapping_ws.merge_cells(start_row=note_title_row, start_column=1, end_row=note_title_row, end_column=11)
    mapping_ws.cell(note_title_row, 1, "Mapping note")
    mapping_ws.cell(note_title_row, 1)._style = note_title_style
    mapping_ws.cell(note_title_row, 1).alignment = note_title_alignment
    mapping_ws.merge_cells(start_row=note_body_row, start_column=1, end_row=note_body_row + 1, end_column=11)
    mapping_ws.cell(note_body_row, 1, note_text + " VM Light and Heavy rows are billed separately. Storage defaults to 1 PUT and 10 GET requests per participant per storage-active day; change the mapping counts to match the lab. Blob transactions and S3 API requests are billed separately from stored GB.")
    mapping_ws.cell(note_body_row, 1)._style = note_body_style
    mapping_ws.cell(note_body_row, 1).alignment = note_body_alignment

    # Add selected-provider VM profile rows to the rate card. Consumers can
    # supply current, SKU-specific values through vm_profile_rates; otherwise
    # the workbook deliberately labels its template-rate fallback for review.
    rate_ws = workbook["Rate Card"]
    rate_end_row = rate_ws.max_row
    # A quote may provide current, SKU-specific prices for the selected
    # provider/region. Keep the amount, source URL, and verification date in
    # the visible rate card rather than burying them in the export request.
    rate_card_overrides = values.get("rate_card_overrides") or {}
    if isinstance(rate_card_overrides, dict):
        for row in range(4, rate_end_row + 1):
            if rate_ws.cell(row, 1).value != provider_label or rate_ws.cell(row, 2).value != region_label:
                # Other-provider template examples are not verified prices.
                rate_ws.cell(row, 5).value = None
                rate_ws.cell(row, 6).value = None
                rate_ws.cell(row, 8, 'Not priced for this quote')
                continue
            resource = str(rate_ws.cell(row, 3).value or "")
            override = rate_card_overrides.get(resource) or rate_card_overrides.get(resource.lower())
            if not isinstance(override, dict):
                continue
            if override.get("rate") is not None:
                rate_ws.cell(row, 5, max(0, float(override["rate"])))
            if override.get("unit"):
                rate_ws.cell(row, 4, str(override["unit"]))
            if override.get("source"):
                rate_ws.cell(row, 7, str(override["source"]))
            rate_ws.cell(row, 8, str(override.get("verified_date") or values.get("rate_card_verified_date") or datetime.now().date().isoformat()))
            rate_ws.cell(row, 7).comment = openpyxl.comments.Comment(
                str(override.get("note") or "Current rate supplied for this estimate"), "Codex"
            )
        configured_selections = values.get("pricing_selections") or {}
        dynamic_resources = ["Managed database storage", "Object storage PUT requests", "Object storage GET requests"]
        dynamic_resources.extend(name for name in configured_selections
                                 if name not in {"VM", "VM Light", "VM Heavy", "Kubernetes control plane",
                                                 "Kubernetes worker", "Disk", "Storage", "Egress",
                                                 "Object storage PUT requests", "Object storage GET requests",
                                                 "Build runner", "Managed database", "Managed database storage",
                                                 "Monitoring"})
        for resource in dict.fromkeys(dynamic_resources):
            override = rate_card_overrides.get(resource) or {}
            if not isinstance(override, dict) or not override.get("source") or override.get("sku") == "NOT_BILLED":
                continue
            rate_end_row += 1
            for column in range(1, 9):
                rate_ws.cell(rate_end_row, column)._style = copy(rate_ws.cell(4, column)._style)
                rate_ws.cell(rate_end_row, column).alignment = copy(rate_ws.cell(4, column).alignment)
            rate_ws.cell(rate_end_row, 1, provider_label)
            rate_ws.cell(rate_end_row, 2, region_label)
            rate_ws.cell(rate_end_row, 3, resource)
            unit = str(override.get("unit") or "")
            rate_ws.cell(rate_end_row, 4, {"Requests": "per request", "GB-Mo": "GB-month", "1 GB/Month": "GB-month", "1/Day": "per database-day", "Hrs": "per hour", "Hours": "per hour"}.get(unit, unit))
            rate_ws.cell(rate_end_row, 5, max(0, float(override.get("rate", 0))))
            rate_ws.cell(rate_end_row, 6, f"=E{rate_end_row}*'Assumptions'!$B$15")
            rate_ws.cell(rate_end_row, 7, str(override.get("source")))
            rate_ws.cell(rate_end_row, 8, str(override.get("verified_date") or values.get("rate_card_verified_date") or datetime.now().date().isoformat()))
            rate_ws.cell(rate_end_row, 7).comment = openpyxl.comments.Comment(str(override.get("note") or "Live provider rate"), "Codex")
    selected_vm_row = next(
        (row for row in range(4, rate_end_row + 1)
         if rate_ws.cell(row, 1).value == provider_label and rate_ws.cell(row, 2).value == region_label
         and rate_ws.cell(row, 3).value == "VM"),
        None,
    )
    if selected_vm_row is None:
        raise HTTPException(422, "A base VM rate is required for the selected provider/region")
    profile_rates = values.get("vm_profile_rates") or {}
    profile_sources = values.get("vm_profile_sources") or {}
    verified_date = str(values.get("rate_card_verified_date") or datetime.now().date().isoformat())
    base_rate = float(rate_ws.cell(selected_vm_row, 5).value or 0)
    base_source = str(rate_ws.cell(selected_vm_row, 7).value or "")
    profile_rate_rows: Dict[str, int] = {}
    for profile in ("Light", "Heavy"):
        profile_value = profile_rates.get(profile, profile_rates.get(profile.lower())) if isinstance(profile_rates, dict) else None
        source_value = profile_sources.get(profile, profile_sources.get(profile.lower())) if isinstance(profile_sources, dict) else None
        rate = base_rate if profile_value is None else float(profile_value)
        source = str(source_value or base_source)
        status = "live SKU rate supplied" if profile_value is not None and source_value else "template fallback — replace with current SKU rate before approval"
        rate_end_row += 1
        for column in range(1, 9):
            rate_ws.cell(rate_end_row, column)._style = copy(rate_ws.cell(selected_vm_row, column)._style)
            rate_ws.cell(rate_end_row, column).alignment = copy(rate_ws.cell(selected_vm_row, column).alignment)
        rate_ws.cell(rate_end_row, 1, provider_label)
        rate_ws.cell(rate_end_row, 2, region_label)
        rate_ws.cell(rate_end_row, 3, f"VM {profile}")
        rate_ws.cell(rate_end_row, 4, "per hour")
        rate_ws.cell(rate_end_row, 5, rate)
        rate_ws.cell(rate_end_row, 6, f"=E{rate_end_row}*'Assumptions'!$B$15")
        rate_ws.cell(rate_end_row, 7, source)
        rate_ws.cell(rate_end_row, 8, verified_date)
        rate_ws.cell(rate_end_row, 7).comment = openpyxl.comments.Comment(status, "Codex")
        profile_rate_rows[profile] = rate_end_row
    for row in range(4, rate_end_row + 1):
        resource = rate_ws.cell(row, 3).value
        if resource not in {"VM Light", "VM Heavy"} and rate_ws.cell(row, 1).value == provider_label and rate_ws.cell(row, 2).value == region_label:
            rate_ws.cell(row, 6, f"=E{row}*'Assumptions'!$B$15")

    for ws in workbook.worksheets:
        for cells in ws.iter_rows():
            for cell in cells:
                if isinstance(cell.value, str) and cell.value.startswith("=") and "'Rate Card'!" in cell.value:
                    cell.value = cell.value.replace("$30", f"${rate_end_row}")

    # Billing is driven by resource-days in the mapping. This avoids the old
    # peak-quantity approximation and makes every ToC line auditable.
    breakdown_ws = workbook["Resource Cost Breakdown"]
    mapping_ranges = {
        "vm": f"'TOC Mapping'!$C$4:$C${mapping_end_row}",
        "profile": f"'TOC Mapping'!$D$4:$D${mapping_end_row}",
        "control": f"'TOC Mapping'!$E$4:$E${mapping_end_row}",
        "worker": f"'TOC Mapping'!$F$4:$F${mapping_end_row}",
        "database": f"'TOC Mapping'!$G$4:$G${mapping_end_row}",
        "storage": f"'TOC Mapping'!$H$4:$H${mapping_end_row}",
        "days": f"'TOC Mapping'!$I$4:$I${mapping_end_row}",
        "put": f"'TOC Mapping'!$J$4:$J${mapping_end_row}",
        "get": f"'TOC Mapping'!$K$4:$K${mapping_end_row}",
    }
    for cost_row, key in ((5, "control"), (6, "worker"), (11, "database")):
        breakdown_ws[f"B{cost_row}"] = f"=SUMPRODUCT({mapping_ranges[key]},{mapping_ranges['days']})"
        daily_database = cost_row == 11 and str((rate_card_overrides.get("Managed database") or {}).get("unit")) == "1/Day"
        breakdown_ws[f"F{cost_row}"] = 1 if daily_database else "='Assumptions'!$B$7"
        breakdown_ws[f"H{cost_row}"] = f"=B{cost_row}*D{cost_row}*F{cost_row}"
        breakdown_ws[f"G{cost_row}"] = "Resource-days × Rate × Hours/day"
    breakdown_ws["A4"] = "VM (profiled)"
    breakdown_ws["B4"] = f"=SUMPRODUCT({mapping_ranges['vm']},{mapping_ranges['days']})"
    breakdown_ws["F4"] = "='Assumptions'!$B$7"
    breakdown_ws["G4"] = "Light/Heavy VM-days × respective rate × Hours/day"
    breakdown_ws["H4"] = (
        f"=(SUMPRODUCT({mapping_ranges['vm']},{mapping_ranges['days']},--({mapping_ranges['profile']}=\"Light\"))*"
        f"'Rate Card'!$F${profile_rate_rows['Light']}+SUMPRODUCT({mapping_ranges['vm']},{mapping_ranges['days']},--({mapping_ranges['profile']}=\"Heavy\"))*"
        f"'Rate Card'!$F${profile_rate_rows['Heavy']})*'Assumptions'!$B$7"
    )
    # Disk is driven by nodes and an explicit GB-per-node assumption, never
    # by participant count. A per-day template mapping can override the node
    # quantities above before this formula is evaluated.
    assumptions_ws["A20"] = "Disk GB per VM / worker node"
    assumptions_ws["B20"] = as_number("disk_gb_per_node", 20, 0)
    assumptions_ws["C20"] = "GB"
    assumptions_ws["D20"] = "Explicit sizing assumption; replace with lab-template node sizing when supplied"
    for column in range(1, 5):
        assumptions_ws.cell(20, column)._style = copy(assumptions_ws.cell(19, column)._style)
    # This is billed at a monthly rate, so display the GB-month equivalent
    # instead of a GB-node-days intermediate in the client workbook.
    breakdown_ws["B7"] = f"=SUMPRODUCT(({mapping_ranges['vm']}+{mapping_ranges['worker']}),{mapping_ranges['days']})*'Assumptions'!$B$20/30"
    breakdown_ws["F7"] = 1
    breakdown_ws["G7"] = "GB-node-days × monthly rate / 30"
    breakdown_ws["H7"] = "=B7*D7"
    breakdown_ws["B8"] = f"=SUMPRODUCT({mapping_ranges['storage']},{mapping_ranges['days']})"
    breakdown_ws["F8"] = 1
    breakdown_ws["G8"] = "GB-days × monthly rate / 30"
    breakdown_ws["H8"] = "=B8*D8/30"

    assumptions_ws["A42"] = "Managed database storage (GB)"
    assumptions_ws["B42"] = as_number("database_storage_gb", 20, 0)
    assumptions_ws["C42"] = "GB per database"
    assumptions_ws["D42"] = "RDS gp3 default 20 GB; Azure SQL S0 includes up to 250 GB and has no separate storage line"
    for column in range(1, 5):
        assumptions_ws.cell(42, column)._style = copy(assumptions_ws.cell(19, column)._style)
    breakdown_ws.insert_rows(14, amount=2)
    for row in (13, 14, 15):
        for column in range(1, 11):
            breakdown_ws.cell(row, column)._style = copy(breakdown_ws.cell(12, column)._style)
    breakdown_ws["A13"] = "Managed database storage"
    breakdown_ws["B13"] = f"='Assumptions'!$B$42*SUMPRODUCT({mapping_ranges['database']},{mapping_ranges['days']})/30"
    breakdown_ws["D13"] = f"=SUMIFS('Rate Card'!$F$4:$F${rate_end_row},'Rate Card'!$A$4:$A${rate_end_row},I13,'Rate Card'!$B$4:$B${rate_end_row},J13,'Rate Card'!$C$4:$C${rate_end_row},A13)"
    breakdown_ws["F13"] = 1
    breakdown_ws["G13"] = "GB database-days × monthly rate / 30; included in Azure SQL S0"
    breakdown_ws["H13"] = "=B13*D13"
    for row, label, key, title in ((14, "Object storage PUT requests", "put", "PUT"), (15, "Object storage GET requests", "get", "GET")):
        breakdown_ws[f"A{row}"] = label
        breakdown_ws[f"B{row}"] = f"=SUMPRODUCT({mapping_ranges[key]},{mapping_ranges['days']})"
        breakdown_ws[f"D{row}"] = f"=SUMIFS('Rate Card'!$F$4:$F${rate_end_row},'Rate Card'!$A$4:$A${rate_end_row},I{row},'Rate Card'!$B$4:$B${rate_end_row},J{row},'Rate Card'!$C$4:$C${rate_end_row},A{row})"
        breakdown_ws[f"F{row}"] = 1
        breakdown_ws[f"G{row}"] = f"{title} requests × per-request rate"
        breakdown_ws[f"H{row}"] = f"=B{row}*D{row}"
    additional_names = [name for name in (values.get("pricing_selections") or {})
                        if name not in {"VM", "VM Light", "VM Heavy", "Kubernetes control plane",
                                        "Kubernetes worker", "Disk", "Storage", "Egress",
                                        "Object storage PUT requests", "Object storage GET requests",
                                        "Build runner", "Managed database", "Managed database storage",
                                        "Monitoring"}]
    if additional_names:
        breakdown_ws.insert_rows(16, amount=len(additional_names))
    for index, resource in enumerate(additional_names):
        row = 16 + index
        for column in range(1, 11):
            breakdown_ws.cell(row, column)._style = copy(breakdown_ws.cell(15, column)._style)
        quantity = (values.get("additional_resource_usage") or {}).get(resource, 0)
        breakdown_ws[f"A{row}"] = resource
        breakdown_ws[f"B{row}"] = quantity
        breakdown_ws[f"D{row}"] = f"=SUMIFS('Rate Card'!$F$4:$F${rate_end_row},'Rate Card'!$A$4:$A${rate_end_row},I{row},'Rate Card'!$B$4:$B${rate_end_row},J{row},'Rate Card'!$C$4:$C${rate_end_row},A{row})"
        breakdown_ws[f"F{row}"] = 1
        breakdown_ws[f"G{row}"] = "Explicit billed usage × live catalog rate"
        breakdown_ws[f"H{row}"] = f"=B{row}*D{row}"
    total_row = 16 + len(additional_names)
    breakdown_ws[f"A{total_row}"] = "Total Infrastructure Cost"
    breakdown_ws[f"H{total_row}"] = f"=SUM(H4:H{total_row - 1})"
    workbook["Client Estimate"]["B8"] = f"='Resource Cost Breakdown'!H{total_row}"

    support = as_number("lab_support_per_participant_day", values.get("lab_support_per_participant") or 0, 0)
    assumptions_ws["A21"] = "Applied support rate (INR / participant-day)"
    assumptions_ws["B21"] = "=IF(B23=\"Basic\",B24,IF(B23=\"Standard\",B25,B26))"
    assumptions_ws["C21"] = "INR / participant-day"
    assumptions_ws["D21"] = "Formula selects the applied support tier; total scales with participants and training days"
    for column in range(1, 5):
        assumptions_ws.cell(21, column)._style = copy(assumptions_ws.cell(19, column)._style)
    assumptions_ws["A22"] = "Advanced support threshold"
    assumptions_ws["B22"] = as_positive_int("advanced_support_threshold_participant_days", 400)
    assumptions_ws["C22"] = "participant-days"
    assumptions_ws["D22"] = "At or above this engagement size, Standard is automatically quoted as Advanced support"
    assumptions_ws["A23"] = "Applied support tier"
    assumptions_ws["B23"] = "=IF(AND(B18=\"Standard\",B9*B8>=B22),\"Advanced\",B18)"
    assumptions_ws["C23"] = "tier"
    assumptions_ws["D23"] = "Uses participant count × training days"
    assumptions_ws["A24"] = "Basic support rate"
    assumptions_ws["B24"] = as_number("basic_support_per_participant_day", 0, 0)
    assumptions_ws["C24"] = "INR / participant-day"
    assumptions_ws["D24"] = "Editable commercial rate"
    assumptions_ws["A25"] = "Standard support rate"
    assumptions_ws["B25"] = support
    assumptions_ws["C25"] = "INR / participant-day"
    assumptions_ws["D25"] = "Editable commercial rate"
    assumptions_ws["A26"] = "Advanced support rate"
    assumptions_ws["B26"] = as_number("advanced_support_per_participant_day", support, 0)
    assumptions_ws["C26"] = "INR / participant-day"
    assumptions_ws["D26"] = "Editable commercial rate"
    profile_is_live = bool(isinstance(profile_rates, dict) and profile_rates.get("Light", profile_rates.get("light")) is not None and profile_rates.get("Heavy", profile_rates.get("heavy")) is not None and isinstance(profile_sources, dict))
    assumptions_ws["A27"] = "VM profile pricing status"
    assumptions_ws["B27"] = "Live profile rates supplied" if profile_is_live else "Template fallback — approval blocked"
    assumptions_ws["C27"] = verified_date
    assumptions_ws["D27"] = "Enter vm_profile_rates and vm_profile_sources with current provider URLs before final client approval"
    for row in range(22, 28):
        for column in range(1, 5):
            assumptions_ws.cell(row, column)._style = copy(assumptions_ws.cell(19, column)._style)
    # Quote provenance belongs in the workbook as well as the service audit
    # record. This makes a downloaded file independently reviewable months
    # later, even after a provider updates its public price list.
    provenance_rows = [
        ("Rate snapshot ID", values.get("rate_snapshot_id") or "Not recorded", "audit ID", "Use this ID to retrieve the rate snapshot and calculation record"),
        ("Pricing status", values.get("pricing_status") or "template_fallback_review_required", "status", "Live SKU rates and official source URLs are required before final client approval"),
        ("FX attribution", values.get("fx_rate_attribution") or "Not supplied", "URL", "Exchange-rate data provider"),
        ("USD/INR source", values.get("fx_rate_source") or "Not supplied", "URL", "Published exchange-rate source"),
        ("USD/INR observation date", values.get("fx_rate_date") or "Not supplied", "date", "Provider observation date"),
        ("USD/INR checked at", values.get("fx_rate_fetched_at") or "Not supplied", "timestamp", "Lookup for this quote"),
        ("Rate source", values.get("rate_snapshot_source") or "Not supplied", "URL", "Official provider pricing page or approved pricing-export URL"),
        ("Rates checked at (UTC)", values.get("rate_checked_at") or "Not recorded", "timestamp", "Rate snapshot timestamp"),
        ("Quote valid until (UTC)", values.get("quote_valid_until") or "Not recorded", "timestamp", "Recalculate from current rates after this time"),
        ("Price-change review threshold", as_number("price_change_review_threshold_percent", 5, 0), "%", "Escalate for review when refreshed pricing changes beyond this threshold"),
        ("Lab architecture", values.get('architecture_note') or 'Caller-supplied per-day resource mapping', 'assumption', 'Quantities are total resources; learner VMs scale with participants, shared services do not'),
        ("FX status", 'Published rate fetched for quote' if values.get('fx_rate_source') else 'Unverified', 'status', 'Latest published observation; see FX date and source'),
        ("Support pricing status", 'Configured' if any(values.get(k) is not None for k in ('lab_support_per_participant_day', 'lab_support_per_participant')) else 'Unconfigured / zero charge', 'status', 'No support price is invented. Confirm the applied tier rate before client approval'),
        ("Quote approval status", 'Draft — commercial review required', 'status', 'Provider verification covers selected resource rates only; confirm architecture, access hours, support, FX, taxes and exclusions'),
    ]
    for row, values_row in enumerate(provenance_rows, start=28):
        for column, value in enumerate(values_row, start=1):
            assumptions_ws.cell(row, column, value)
            assumptions_ws.cell(row, column)._style = copy(assumptions_ws.cell(19, column)._style)
    workbook["Client Estimate"]["B9"] = "='Assumptions'!B21*'Assumptions'!B9*'Assumptions'!B8"
    workbook["Client Estimate"]["B11"] = "=SUM(B8:B10)*(1+'Internal Calculation'!$B$1)*'Assumptions'!B17"
    # The uplift is already reflected in the tax base above. Add the tax once
    # instead of applying the uplift a second time to the full taxed total.
    # The internal commercial composition is never displayed in the client workbook.
    workbook["Client Estimate"]["A12"] = "Final estimated cost"
    workbook["Client Estimate"]["B12"] = "=SUM(B8:B10)*(1+'Internal Calculation'!$B$1)+B11"
    workbook["Client Estimate"]["B13"] = "=B12/Assumptions!B9"
    workbook["Client Estimate"]["A17"] = (
        "Infrastructure is calculated from per-day resource counts, active days, VM profile rates, and storage/node sizing. "
        "Tax uses the supplied percentage; 0% means no tax has been included. VM profile rate rows marked as template fallback must be replaced with a current provider SKU rate and URL before client approval."
    )
    request_summary = values.get("request_summary")
    if isinstance(request_summary, dict) and request_summary:
        from openpyxl.styles import Alignment, Font, PatternFill

        summary_ws = workbook.create_sheet("Request Summary")
        summary_ws.sheet_view.showGridLines = False
        summary_ws.merge_cells("A1:B1")
        summary_ws["A1"] = "Client Lab Request Summary"
        summary_ws["A1"].font = Font(bold=True, size=16, color="FFFFFFFF")
        summary_ws["A1"].fill = PatternFill("solid", fgColor="FF1F4E78")
        summary_ws["A1"].alignment = Alignment(vertical="center")
        summary_ws.row_dimensions[1].height = 28
        summary_rows = [
            ("Request ID", request_summary.get("request_id")),
            ("Client", request_summary.get("client_name")),
            ("Training", request_summary.get("technology")),
            ("Scope", request_summary.get("scope")),
            ("Training days", request_summary.get("duration_days")),
            ("Training dates", request_summary.get("training_dates")),
            ("Participants", request_summary.get("participant_count")),
            ("Lab access hours per day", request_summary.get("hours_per_day")),
            ("Cloud provider", request_summary.get("cloud_provider")),
            ("Cloud region", request_summary.get("cloud_region")),
            ("Delivery mode", request_summary.get("mode")),
            ("Estimate status", "Draft estimate — review assumptions and rates before approval"),
        ]
        for row, (label, value) in enumerate(summary_rows, start=3):
            summary_ws.cell(row, 1, label)
            summary_ws.cell(row, 2, str(value) if value not in (None, "") else "Not provided")
            summary_ws.cell(row, 1).font = Font(bold=True, color="FF344054")
            summary_ws.cell(row, 1).fill = PatternFill("solid", fgColor="FFF2F4F7")
            summary_ws.cell(row, 1).alignment = Alignment(vertical="top", wrap_text=True)
            summary_ws.cell(row, 2).alignment = Alignment(vertical="top", wrap_text=True)
        summary_ws.column_dimensions["A"].width = 30
        summary_ws.column_dimensions["B"].width = 82
        summary_ws.freeze_panes = "A3"
        estimate_ws = workbook["Client Estimate"]
        if "A2:D2" not in {str(item) for item in estimate_ws.merged_cells.ranges}:
            estimate_ws.merge_cells("A2:D2")
        request_link = estimate_ws["A2"]
        request_link.value = "View request summary and estimate assumptions"
        request_link.hyperlink = "#'Request Summary'!A1"
        request_link.style = "Hyperlink"
        request_link.alignment = Alignment(horizontal="right", vertical="center")

    if values.get('price_changes'):
        audit_ws = workbook.create_sheet('Live Price Check')
        audit_ws.append(['Resource', 'SKU', 'Billing dimension', 'Unit', 'USD rate',
                         'Region', 'Source', 'Checked at', 'Previous USD rate',
                         'Change %', 'Review required'])
        for change in values['price_changes']:
            rate = values['rate_card_overrides'][change['resource']]
            audit_ws.append([change['resource'], rate['sku'], rate['dimension'],
                rate['unit'], rate['rate'], region_label, rate['source'],
                values['rate_checked_at'], change['previous'], change['change_percent'],
                'Yes' if change['review_required'] else 'No'])
        audit_ws.freeze_panes = 'A2'
        audit_ws.auto_filter.ref = audit_ws.dimensions
        for col in 'ABCDEFGHIJK':
            audit_ws.column_dimensions[col].width = 26
        audit_ws.column_dimensions['G'].width = 65
        workbook['Client Estimate']['A17'] = (
            'Fresh public retail rates checked: ' + values['rate_checked_at']
            + '. Valid until: ' + values['quote_valid_until']
            + '. Price-change review: ' + ('required' if any(c['review_required'] for c in values['price_changes']) else 'not triggered')
            + '. See Live Price Check. Account discounts and future usage may differ.'
        )
    ai_cost = values.get('ai_cost')
    if ai_cost:
        ai_ws = workbook.create_sheet('AI Cost Evidence')
        ai_ws.append(['Field', 'Value'])
        usage = ai_cost.get('usage', {})
        rows = [
            ('Status', ai_cost.get('status')), ('Provider', usage.get('provider')),
            ('Model', usage.get('model')), ('Input tokens', usage.get('input_tokens')),
            ('Output tokens', usage.get('output_tokens')), ('GPU hours', usage.get('gpu_hours')),
            ('Input USD / 1M tokens', ai_cost.get('input_per_million')),
            ('Output USD / 1M tokens', ai_cost.get('output_per_million')),
            ('GPU USD / hour', ai_cost.get('gpu_per_hour')),
            ('Total AI cost (USD)', ai_cost.get('total_usd')),
            ('Evidence source', ai_cost.get('source_url')),
            ('Evidence title', ai_cost.get('source_title')),
            ('Effective date', ai_cost.get('effective_date')),
            ('Retrieved at (UTC)', ai_cost.get('retrieved_at')),
            ('Evidence excerpt', ai_cost.get('evidence_excerpt') or ai_cost.get('message')),
        ]
        for row in rows:
            ai_ws.append(row)
        ai_ws.freeze_panes = 'A2'
        ai_ws.column_dimensions['A'].width = 28
        ai_ws.column_dimensions['B'].width = 95
        ai_ws['A1'].font = ai_ws['B1'].font = openpyxl.styles.Font(bold=True)
    # openpyxl writes formulas but does not calculate them.  Ask Excel and
    # compatible spreadsheet clients to rebuild the client-facing totals
    # before showing cached values from the template.
    from openpyxl.workbook.properties import CalcProperties

    workbook.calculation = workbook.calculation or CalcProperties()
    workbook.calculation.calcMode = "auto"
    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    from app.lab_plan import add_lab_plan
    add_lab_plan(workbook, days, values, profile_rate_rows)
    if any(day.get('modules') for day in days):
        from shared.lab_curriculum import local_unit
        module_sheet = workbook.create_sheet('Module Lab Inputs')
        module_sheet.append(['Day', 'Module', 'Teaching minutes', 'Practical activity', 'Execution context', 'Lab access hours/day'])
        for index, day in enumerate(days, 1):
            for module in day.get('modules') or []:
                module_sheet.append([day.get('day') or index, module.get('title') or module.get('topic'),
                    module.get('minutes'), module.get('lab') or module.get('lab_task'),
                    'Local' if day.get('lab_setup') == 'local' or local_unit(module) else 'Cloud/shared: see TOC Mapping',
                    "='Assumptions'!$B$7"])
        for row in module_sheet:
            for cell in row:
                if cell.column != 6 and isinstance(cell.value, str):
                    cell.data_type = 's'
                cell.alignment = openpyxl.styles.Alignment(wrap_text=True, vertical='top')
        for col, width in zip('ABCDEF', (10, 38, 18, 85, 35, 25)):
            module_sheet.column_dimensions[col].width = width
        module_sheet.freeze_panes = 'A2'
        module_sheet.auto_filter.ref = module_sheet.dimensions
    # Deliver one beginner-friendly sheet. Calculation tabs remain available
    # internally for audit and recalculation, without overwhelming clients.
    client_sheet_index = workbook.sheetnames.index("Lab Plan")
    workbook.active = client_sheet_index
    from openpyxl.workbook.views import BookView
    if not workbook.views:
        workbook.views.append(BookView(activeTab=client_sheet_index))
    else:
        workbook.views[0].activeTab = client_sheet_index
    # Some approved templates retain a stale selected tab. Clear every sheet
    # view first so Excel, Google Drive, and LibreOffice open the quote.
    for sheet_index, sheet in enumerate(workbook.worksheets):
        sheet.sheet_view.tabSelected = sheet_index == client_sheet_index
        if sheet_index != client_sheet_index and sheet.sheet_state != "veryHidden":
            sheet.sheet_state = 'hidden'
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
    """Export a day-wise lab plan backed by the existing cost workbook."""
    return _lab_cost_template_to_excel(toc, assumptions)


@router.post("/toc")
async def export_toc_workbook(payload: Dict[str, Any] = Body(...)):
    toc = payload.get("toc") if isinstance(payload.get("toc"), dict) else payload
    from shared.toc_quality import toc_delivery_error
    error = toc_delivery_error(toc)
    draft = payload.get("draft") is True
    if error and not (draft and toc.get("days")):
        raise HTTPException(422, error)
    if draft:
        # Draft exports are visible review artefacts, never delivery approval.
        toc = {**toc, "draft_export": True}
        if toc.get("excel_layout") in (None, "legacy", "auto"):
            toc["excel_layout"] = "execution_plan"
    workbook = _toc_to_excel(toc)
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=" + ("DRAFT_training_toc.xlsx" if draft else "training_toc.xlsx")},
    )


@router.post("/toc/lab-cost/combine")
async def combine_cloud_lab_costs(payload: Dict[str, Any] = Body(...)):
    import base64
    from app.lab_sheet import combine_lab_estimates
    try:
        inputs = payload.get('estimates') or []
        content = combine_lab_estimates([
            (item['provider'], base64.b64decode(item['content_base64'], validate=True))
            for item in inputs
        ])
        from app.lab_recalculation import recalculate_lab_workbook
        from starlette.concurrency import run_in_threadpool
        content = await run_in_threadpool(recalculate_lab_workbook, content)
    except Exception as exc:
        logger.exception('Could not consolidate cloud estimates')
        raise HTTPException(422, 'Could not combine complete cloud estimates') from exc
    return Response(content=content,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=lab_cost_estimate.xlsx'})


@router.post("/toc/lab-cost")
async def export_toc_lab_cost_workbook(payload: Dict[str, Any] = Body(...), db=Depends(get_db)):
    toc = payload.get("toc") if isinstance(payload.get("toc"), dict) else payload
    from shared.toc_quality import toc_delivery_error
    error = toc_delivery_error(toc)
    # A generated agenda may be shared as a proposed scope during the
    # automated trainer/client handoff. Its later delivery review must not
    # prevent preparing the corresponding draft lab workbook.
    if error and payload.get("draft") is not True:
        raise HTTPException(422, error)
    # The lab-cost template has 30 day rows. Refuse longer programmes before
    # refreshing live prices or planning lab resources.
    assumptions = dict(payload.get("assumptions") or {})
    from shared.lab_cost_inputs import lab_quote_scope
    count = assumptions.get("participant_count", toc.get("participant_count"))
    if count in (None, ""):
        assumptions["sample_quote"] = True
    try:
        toc, assumptions["participant_count"], assumptions["hours_per_day"] = lab_quote_scope(
            toc, count, assumptions.get("hours_per_day"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if assumptions.get("sample_quote") and assumptions.get("lab_day_mapping"):
        rows = assumptions["lab_day_mapping"]
        first = rows[0] if isinstance(rows, list) else rows.get("1", rows.get(1))
        assumptions["lab_day_mapping"] = [{**first, "active_days": 1}] if first else None
    lab_days = 0
    for day in toc.get("days") or []:
        if isinstance(day, dict):
            try:
                lab_days += max(1, int(float(day.get("duration_days") or day.get("days") or 1)))
            except (TypeError, ValueError):
                lab_days += 1
    if lab_days > 30:
        raise HTTPException(422, f"Lab cost estimates support training durations from 1 to 30 days; this ToC has {lab_days} days")
    from shared.lab_cost_inputs import validate_lab_cost_inputs, validate_lab_pricing_coverage
    from shared.live_lab_pricing import refresh_rates, refresh_exchange_rate, automatic_pricing_selections
    from starlette.concurrency import run_in_threadpool
    import hashlib
    import json
    ai_usage = assumptions.get('ai_usage')
    try:
        assumptions = dict(assumptions)
        for key in ('rate_snapshot_id', 'rate_snapshot_source', 'rate_checked_at', 'quote_valid_until'):
            assumptions.pop(key, None)
        for key, default in (("cloud_provider", "aws"), ("hours_per_day", 3), ("participant_count", 1)):
            if assumptions.get(key) in (None, ""):
                source_key = 'lab_access_hours_per_day' if key == 'hours_per_day' else key
                assumptions[key] = toc.get(source_key) if toc.get(source_key) not in (None, '') else default
        if assumptions.get("cloud_region") in (None, ""):
            assumptions["cloud_region"] = {"aws": "ap-south-1", "azure": "centralindia", "gcp": "asia-south1"}.get(assumptions["cloud_provider"], "")
        # Caller-supplied FX, including old saved values, is never production evidence.
        for key in ("fx_rate", "fx_rate_source", "fx_rate_date", "fx_rate_fetched_at"):
            assumptions.pop(key, None)
        assumptions = validate_lab_cost_inputs(assumptions, require_fx=False)
        assumptions["allow_incomplete_draft"] = payload.get("draft") is True
        # Match the trainer-service rule: a fully local course cannot inherit
        # default cloud egress, build-runner, or monitoring charges.
        from shared.lab_planning import local_only_delivery
        toc, is_local_only = local_only_delivery(toc, assumptions)
        if is_local_only:
            for key in ('storage_gb', 'egress_gb', 'build_minutes', 'monitoring_gb', 'k8s_worker_nodes'):
                assumptions[key] = 0
        if not assumptions.get('lab_day_mapping'):
            from shared.lab_planning import default_cloud_mapping
            assumptions['lab_day_mapping'] = default_cloud_mapping(toc, assumptions)
            assumptions['architecture_note'] = (
                'Proposed cloud lab: one learner VM per participant on practical days; '
                'generic Kubernetes runs locally on heavy learner VMs. Explicit managed '
                'clusters, database and object storage are shared. No resources have been provisioned. '
                'Compute hours use the supplied lab-access assumption; disk/storage retention '
                'uses active days and requires deletion after each mapped lab period.'
            )
        else:
            from shared.lab_planning import default_cloud_mapping
            planned = default_cloud_mapping(toc, assumptions)
            provided = assumptions['lab_day_mapping']
            if isinstance(provided, dict):
                provided_rows = [provided.get(str(i)) or provided.get(i) or {}
                                 for i in range(1, len(planned) + 1)]
            else:
                provided_rows = list(provided)
            if len(provided_rows) == len(planned):
                for day_index, (actual, inferred) in enumerate(zip(provided_rows, planned), 1):
                    inferred_allocated = any(float(inferred.get(key) or 0) > 0 for key in (
                        'vm_qty', 'k8s_control_plane', 'k8s_worker_nodes', 'managed_db', 'object_storage_gb'))
                    if inferred_allocated:
                        # Preserve any quantities the requester supplied, but
                        # never allow a short hand-written map to hide named
                        # services implied by the exercise's tools/subtopics.
                        for key in ('vm_qty', 'k8s_control_plane', 'k8s_worker_nodes', 'managed_db',
                                    'object_storage_gb', 'storage_put_requests', 'storage_get_requests'):
                            actual[key] = max(float(actual.get(key) or 0), float(inferred.get(key) or 0))
                        if actual.get('vm_qty', 0) > 0 and actual.get('vm_profile') == 'None':
                            actual['vm_profile'] = inferred.get('vm_profile') or 'Light'
        from shared.lab_planning import validate_mapping
        mapping = assumptions['lab_day_mapping']
        if isinstance(mapping, dict):
            mapping = [mapping.get(str(i)) or mapping.get(i) for i in range(1, len(toc.get('days') or []) + 1)]
        assumptions['lab_day_mapping'] = validate_mapping(mapping, len(toc.get('days') or []))
        # Selections may be maintained centrally; never substitute stored rates.
        config = await db['lab_pricing_catalogs'].find_one({
                'provider': assumptions['cloud_provider'], 'region': assumptions['cloud_region'],
        }, {'_id': 0})
        automatic = automatic_pricing_selections(toc, assumptions)
        selections = dict(automatic)
        selections.update((config or {}).get('selections') or {})
        selections.update(assumptions.get('pricing_selections') or {})
        # Keep the legacy VM rate row because the workbook still validates and
        # exposes it; also use it as the Light profile default when absent.
        base_vm = selections.get('VM')
        if base_vm:
            selections.setdefault('VM Light', base_vm)
        assumptions['pricing_selections'] = selections
        validate_lab_pricing_coverage(toc, assumptions)
        assumptions['toc'] = toc
        service_architecture = assumptions.get('service_architecture') or {}
        architecture_lines = [
            f"Day {item['day']} ({item['topic']}): Tools: {', '.join(item.get('tools') or []) or 'not specified'}; "
            f"Hands-on: {item.get('experiment') or 'not specified'}; Infrastructure: {item['plan']}"
            for item in service_architecture.get('days', [])
        ]
        if architecture_lines:
            assumptions['architecture_note'] = (
                f"Proposed {assumptions['cloud_provider'].upper()} training architecture; "
                "resources are shared per course unless stated otherwise. No resources "
                "have been provisioned.\n" + "\n".join(architecture_lines)
            )
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    selection_key = hashlib.sha256(json.dumps({
        'provider': assumptions['cloud_provider'], 'region': assumptions['cloud_region'],
        'selections': assumptions['pricing_selections'],
    }, sort_keys=True).encode()).hexdigest()
    previous = await db['lab_cost_rate_snapshots'].find_one(
        {'selection_key': selection_key}, sort=[('rate_checked_at', -1)])
    try:
        # Both observations are refreshed for this quote and saved in its snapshot.
        assumptions = await run_in_threadpool(refresh_exchange_rate, assumptions)
        assumptions = validate_lab_cost_inputs(assumptions)
        assumptions = await run_in_threadpool(refresh_rates, assumptions)
    except ValueError as exc:
        # Invalid SKU, billing units, or architecture cannot use old rates.
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        logger.exception('Fresh provider price refresh failed; client workbook is blocked')
        raise HTTPException(
            503,
            'Fresh cloud or USD/INR pricing is temporarily unavailable; client workbook generation is blocked',
        ) from exc
    if ai_usage:
        from shared.ai_pricing import resolve_ai_cost
        usage = ai_usage if isinstance(ai_usage, dict) else {}
        evidence = await db['ai_pricing_evidence'].find(
            {'provider': str(usage.get('provider') or '').lower()}, {'_id': 0}).to_list(100)
        assumptions['ai_cost'] = resolve_ai_cost(usage, evidence)
    changes = []
    threshold = assumptions.get('price_change_review_threshold_percent', 5)
    for name, rate in assumptions['rate_card_overrides'].items():
        old = (previous or {}).get('rates', {}).get(name, {}).get('rate')
        delta = None if old in (None, 0) else (rate['rate'] / old - 1) * 100
        review = (old == 0 and rate['rate'] != 0) or (delta is not None and abs(delta) > threshold)
        changes.append({'resource': name, 'previous': old, 'current': rate['rate'],
                        'change_percent': delta, 'review_required': review})
    assumptions['price_changes'] = changes
    workbook = _lab_cost_to_excel(toc, assumptions)
    from app.lab_recalculation import final_estimated_cost, recalculate_lab_workbook
    workbook = await run_in_threadpool(recalculate_lab_workbook, workbook)
    final_inr = final_estimated_cost(workbook)
    await db['lab_cost_rate_snapshots'].insert_one({
        'quote_id': assumptions['rate_snapshot_id'], 'selection_key': selection_key,
        'rate_checked_at': assumptions['rate_checked_at'],
        'quote_valid_until': assumptions['quote_valid_until'],
        'provider': assumptions['cloud_provider'], 'region': assumptions['cloud_region'],
        'rates': assumptions['rate_card_overrides'], 'changes': changes,
        'assumptions': assumptions, 'toc': toc,
        'workbook_sha256': hashlib.sha256(workbook).hexdigest(),
    })
    provider = str(assumptions.get("cloud_provider") or "aws").lower()
    headers = {
        "Content-Disposition": f"attachment; filename={provider}_lab_cost.xlsx",
        "X-Lab-Cost-Quote-ID": assumptions["rate_snapshot_id"],
        "X-Lab-Cost-Quote-Valid-Until": assumptions["quote_valid_until"],
        "X-Lab-Cost-Pricing-Status": assumptions["pricing_status"],
        "X-Lab-Cost-Review-Required": "true" if any(change["review_required"] for change in changes) else "false",
        "X-Lab-Cost-Review-Reason": "; ".join(
            f"{change['resource']}: {change['change_percent']:.1f}%"
            for change in changes if change["review_required"] and change.get("change_percent") is not None
        ),
    }
    if final_inr is not None:
        headers["X-Lab-Cost-Final-INR"] = f"{final_inr:.2f}"
    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
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
