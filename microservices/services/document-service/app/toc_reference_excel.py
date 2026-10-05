"""Reference-inspired client TOCs rendered from one validated curriculum."""
import io
import math
import textwrap

from shared.toc_layouts import REFERENCE_LAYOUTS


NAVY = "FF10243E"
INK = "FF1C2834"
GOLD = "FFC4A46A"
PAPER = "FFFBF9F6"
SAND = "FFF4F1EB"
WHITE = "FFFFFFFF"
LINE = "FFE6E1D8"
LABEL = "FFF3EDE3"

TAB_COLORS = {
    "Program Overview": "10243E",
    "Day-wise Plan": "C4A46A",
    "Day-wise Training Plan": "1F4E79",
    "Skills Matrix": "3E6B4F",
    "Detailed Syllabus": "6E4B3A",
    "Module Outcomes": "24506E",
    "Assessment": "8A6A3B",
    "Training Delivery": "3D4F66",
    "Acceptance Checks": "5C4A3A",
    "Client Objectives": "1E3A4C",
    "Scenarios": "4A5568",
    "Readiness & Risks": "7A3E3E",
}


def render_reference_toc(toc):
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.page import PageMargins

    layout = toc["excel_layout"]
    if layout not in REFERENCE_LAYOUTS:
        raise ValueError("Unknown TOC layout")
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    programme_title = str(toc.get("title") or toc.get("domain") or "Training Programme")
    if toc.get("draft_export"):
        programme_title = "DRAFT  ·  " + programme_title

    def text(value):
        if isinstance(value, list):
            return "\n".join(text(item) for item in value)
        if isinstance(value, dict):
            return text(value.get("topic") or value.get("title") or "")
        return str(value or "")

    def sheet(name, headers, rows, widths):
        ws = workbook.create_sheet(name)
        ws.sheet_properties.tabColor = TAB_COLORS.get(name, "10243E")
        ws.append(headers)
        for row in rows:
            # Excel caps row height at 409 points. Spread long prose across
            # continuation rows instead of hiding the end of a detailed lab.
            chunks = []
            for index, value in enumerate(row):
                if not isinstance(value, str):
                    chunks.append([value])
                    continue
                wrapped = [line for paragraph in value.split("\n")
                           for line in (textwrap.wrap(paragraph, max(8, int(widths[index]) - 3)) or [""])]
                chunks.append(["\n".join(wrapped[start:start+22]) for start in range(0, len(wrapped), 22)] or [""]
                              if len(wrapped) > 22 else [value])
            for index in range(max(len(parts) for parts in chunks)):
                ws.append([parts[index] if index < len(parts) else None for parts in chunks])
        for column, width in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(column)].width = width
        hairline = Side(style="thin", color=LINE)
        gold_rule = Side(style="medium", color=GOLD)
        header_border = Border(left=hairline, right=hairline, top=hairline, bottom=gold_rule)
        body_border = Border(left=hairline, right=hairline, top=hairline, bottom=hairline)
        centered_headers = {"Day", "Hours", "Step", "Minutes"}
        centered_columns = {index for index, header in enumerate(headers, 1) if header in centered_headers}
        overview = name == "Program Overview"
        band = 0
        for row in ws:
            lines = 1
            starts_record = row[0].value not in (None, "")
            if row[0].row > 1 and starts_record:
                band += 1
            stripe = SAND if band % 2 else PAPER
            for cell in row:
                # Client text is data, including strings beginning with '='.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                if cell.row == 1:
                    cell.font = Font(name="Calibri", size=10, bold=True, color=WHITE)
                    cell.fill = PatternFill("solid", fgColor=NAVY)
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                    cell.border = header_border
                elif overview and cell.column == 1:
                    cell.font = Font(name="Calibri", size=11, bold=True, color=NAVY)
                    cell.fill = PatternFill("solid", fgColor=LABEL)
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1)
                    cell.border = body_border
                else:
                    cell.font = Font(name="Calibri", size=11, color=INK, bold=cell.column in centered_columns and cell.value not in (None, ""))
                    cell.fill = PatternFill("solid", fgColor=WHITE if overview else stripe)
                    horizontal = "center" if cell.column in centered_columns else "left"
                    cell.alignment = Alignment(horizontal=horizontal, vertical="top", wrap_text=True, indent=0 if horizontal == "center" else 1)
                    cell.border = body_border
                width = max(8, int(widths[cell.column - 1]) - 3)
                lines = max(lines, sum(max(1, len(textwrap.wrap(part, width)))
                                       for part in str(cell.value or "").split("\n")))
            ws.row_dimensions[row[0].row].height = min(409, 34 if row[0].row == 1 else max(36, 16 * lines + 14))
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        ws.print_title_rows = "1:1"
        ws.print_area = ws.dimensions
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A3
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.page_setup.horizontalCentered = True
        ws.page_margins = PageMargins(left=0.45, right=0.45, top=0.7, bottom=0.55, header=0.28, footer=0.28)
        ws.oddHeader.left.text = programme_title[:90]
        ws.oddHeader.left.font = "Calibri"
        ws.oddHeader.left.size = 10
        ws.oddFooter.left.text = "Client curriculum"
        ws.oddFooter.left.font = "Calibri"
        ws.oddFooter.left.size = 9
        ws.oddFooter.right.text = "Page &P of &N"
        ws.oddFooter.right.font = "Calibri"
        ws.oddFooter.right.size = 9
        ws.sheet_view.showGridLines = False
        ws.sheet_view.zoomScale = 110
        return ws

    original_days = toc.get("days") or []
    days = []
    for day in original_days:
        if day.get("modules"):
            for module in day["modules"]:
                days.append({**module, "day": day.get("day"), "date": day.get("date"),
                    "timing": module.get("timing") or day.get("timing"), "focus_area": module.get("title") or module.get("topic"),
                    "hours_per_day": None})
        else:
            days.append(day)
    def hours(day):
        minutes = day.get("minutes")
        try:
            value = float(minutes) / 60 if minutes is not None else day.get("hours_per_day", toc.get("hours_per_day"))
            value = float(value)
            return value if math.isfinite(value) and value > 0 else None
        except (TypeError, ValueError):
            return None

    durations = [hours(day) for day in days]
    brief = toc.get("requirement_brief") or {}
    overview = sheet("Program Overview", ["Programme", "Details"], [
        ["Title", ("DRAFT - FOR REVIEW: " if toc.get("draft_export") else "") + str(toc.get("title") or toc.get("domain") or "Training Programme")],
        ["Overview", text(toc.get("overview"))],
        ["Audience", brief.get("audience") or toc.get("audience_level") or toc.get("level") or "To be confirmed"],
        ["Training days", len(original_days)],
        ["Planned training hours", sum(durations) if all(v is not None for v in durations) else "To be confirmed"],
        ["Delivery mode", toc.get("mode") or "To be confirmed"],
        ["Prerequisites", text(toc.get("prerequisites")) or "To be confirmed"],
        ["Learning outcomes", text(toc.get("learning_outcomes"))],
    ], [28, 105])

    plan_rows, outcomes, assessments, delivery_rows = [], [], [], []
    for index, day in enumerate(days, 1):
        title = day.get("focus_area") or day.get("module") or day.get("title") or f"Module {index}"
        topics = text(day.get("subtopics") or (day.get("morning_session") or {}).get("topics"))
        lab = text(day.get("lab") or day.get("lab_task"))
        objectives = text(day.get("learning_objectives"))
        assessment = text(day.get("assessment")) or "To be confirmed"
        deliverable = text(day.get("deliverable") or day.get("lab_deliverable")) or "To be confirmed"
        duration = durations[index - 1]
        row = [day.get("day") or index, day.get("date") or "To be confirmed",
               day.get("timing") or toc.get("timing") or "To be confirmed", title,
               duration, topics, lab, objectives, deliverable, assessment, text(day.get("tools"))]
        plan_rows.append(row)
        outcomes.append([row[0], title, objectives])
        assessments.append([row[0], title, assessment, deliverable])
        steps = day.get("delivery_steps") or []
        if steps:
            for sequence, step in enumerate(steps, 1):
                delivery_rows.append([row[0], title, sequence, text(step.get("method")),
                    step.get("minutes"), text(step.get("activity")), text(step.get("evidence"))])
        else:
            delivery_rows.append([row[0], title, None, "To be confirmed", None,
                "Teaching sequence and activity timings require trainer confirmation.", "To be confirmed"])

    if layout == "execution_plan":
        schedule = sheet("Day-wise Plan", ["Day", "Date", "Session timing", "Module", "Hours", "Topics",
            "Hands-on lab", "Learning outcomes", "Deliverable", "Success measure"],
            [row[:10] for row in plan_rows], [8, 17, 24, 36, 10, 48, 50, 48, 36, 40])
    elif layout == "technical_plan":
        schedule = sheet("Day-wise Training Plan", ["Day", "Date", "Session timing", "Module", "Hours", "Technical coverage", "Practical lab", "Learning outcomes", "Tools"],
            [row[:8] + [row[10]] for row in plan_rows], [8, 17, 24, 36, 10, 58, 52, 48, 26])
    elif layout == "skills_matrix":
        schedule = sheet("Skills Matrix", ["Day", "Date", "Session timing", "Module", "Hours", "Focus areas", "Practical application", "Participant outcomes", "Participant output"],
            [row[:9] for row in plan_rows], [8, 17, 24, 38, 10, 55, 50, 48, 38])
    else:
        schedule = sheet("Detailed Syllabus", ["Day", "Date", "Session timing", "Module", "Hours", "Detailed topics", "Lab", "Learning objectives", "Lab deliverable", "Assessment", "Tools"],
            plan_rows, [8, 17, 24, 38, 10, 58, 52, 48, 36, 40, 26])
    for row in range(2, schedule.max_row + 1):
        schedule.cell(row, 5).number_format = "0.##"
    if days and all(value is not None for value in durations):
        overview.cell(6, 2, f"=SUM('{schedule.title}'!E2:E{schedule.max_row})")
        overview.cell(6, 2).number_format = "0.##"
    sheet("Module Outcomes", ["Day", "Module", "Learning outcomes"], outcomes, [8, 42, 100])
    sheet("Assessment", ["Day", "Module", "Assessment / success measure", "Deliverable"], assessments, [8, 40, 85, 65])
    sheet("Training Delivery", ["Day", "Module", "Step", "Teaching method", "Minutes", "Trainer / participant activity", "Evidence of completion"],
          delivery_rows, [8, 38, 8, 25, 12, 75, 65])
    check_rows = []
    for row, day in zip(plan_rows, days):
        for check in day.get("acceptance_checks") or []:
            if isinstance(check, dict):
                check_rows.append([row[0], row[3], text(check.get("input_or_condition")),
                    text(check.get("expected_result")), text(check.get("evidence"))])
            elif isinstance(check, str) and check.strip():
                check_rows.append([row[0], row[3], check, "See acceptance statement", "Trainer to confirm evidence"])
    if check_rows:
        sheet("Acceptance Checks", ["Day", "Module", "Input / condition", "Expected result", "Evidence"],
              check_rows, [8, 38, 65, 65, 55])
    outcome_rows = []
    for outcome in toc.get("outcome_coverage") or []:
        for module in outcome.get("modules") or []:
            outcome_rows.append([text(outcome.get("client_outcome")), module.get("day"),
                                 text(module.get("module")), text(module.get("deliverable"))])
    if outcome_rows:
        sheet("Client Objectives", ["Client outcome", "Day", "Module", "Participant deliverable"],
              outcome_rows, [65, 8, 45, 65])
    scenario_rows = []
    for row, day in zip(plan_rows, days):
        if day.get("scenarios"):
            for scenario in day["scenarios"]:
                scenario_rows.append([row[0], row[3], text(scenario.get("situation")),
                    text(scenario.get("activity")), text(scenario.get("outcome")), text(scenario.get("evidence"))])
        elif day.get("scenario"):
            scenario_rows.append([row[0], row[3], text(day["scenario"]), row[6], row[7], row[9]])
    if scenario_rows:
        sheet("Scenarios", ["Day", "Module", "Scenario", "Participant activity", "Expected outcome", "Evidence"],
              scenario_rows, [8, 38, 60, 60, 55, 45])
    readiness = []
    if toc.get("draft_export"):
        quality = toc.get("quality") or {}
        readiness.append(["Draft status", "For review only; this export does not approve client delivery."])
        readiness.extend(["Validation issue", text(v)] for v in quality.get("validation_errors") or [])
        readiness.extend(["Review item", text(v)] for v in quality.get("review_warnings") or [])
        for day in days:
            if day.get("proposed_fields"):
                readiness.append(["Proposed module content", text(day.get("title") or day.get("focus_area")) + ": " + ", ".join(day["proposed_fields"])])
    for item in toc.get("prerequisites") or []:
        readiness.append(["Prerequisite", text(item)])
    for item in toc.get("assumptions") or []:
        readiness.append(["Assumption to confirm", text(item)])
    for item in toc.get("clarification_questions") or []:
        readiness.append(["Clarification", text(item)])
    for item in brief.get("constraints") or []:
        readiness.append(["Client constraint", text(item)])
    for day in days:
        title = day.get("title") or day.get("focus_area") or "Module"
        for item in day.get("preparation_requirements") or []:
            readiness.append(["Trainer preparation: " + str(title), text(item)])
        for item in day.get("prerequisites") or []:
            readiness.append(["Module prerequisite: " + str(title), text(item)])
    if readiness:
        sheet("Readiness & Risks", ["Category", "Requirement / action"], readiness, [30, 110])
    workbook.properties.title = programme_title[:120]
    workbook.properties.subject = "Training curriculum"
    workbook.properties.category = layout.replace("_", " ").title()
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
