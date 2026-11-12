"""Temporary CI check for the new TOC workbook sheets. Removed after review."""
import io, json, pathlib
import openpyxl
from app.toc_reference_excel import render_reference_toc
from shared.toc_layouts import REFERENCE_LAYOUTS

FIXTURE = json.loads((pathlib.Path(__file__).parent / "_tmp_combined_toc.json").read_text())


def test_print_new_layout_summary():
    for layout in REFERENCE_LAYOUTS:
        wb = openpyxl.load_workbook(io.BytesIO(render_reference_toc({**FIXTURE, "excel_layout": layout})))
        plan = wb.worksheets[1]
        headers = [c.value for c in plan[1]]
        print(f"\n[{layout}] sheets={wb.sheetnames}")
        print(f"  schedule headers={headers}")
        assert headers[-3:] == ["Week", "Technology", "Level"]
        assert {"Weekly Plan", "Technology Plan", "Certification Roadmap"} <= set(wb.sheetnames)
        tech_col = len(headers) - 1
        rows = [(plan.cell(r, 1).value, plan.cell(r, 4).value, plan.cell(r, tech_col).value, plan.cell(r, tech_col).fill.fgColor.rgb,
                 plan.cell(r, 1).border.top.style) for r in range(2, plan.max_row + 1) if plan.cell(r, 1).value]
        for row in rows[:16]:
            print("  ", row)
        assert len(rows) == 15
        assert rows[0][2] == "Python" and rows[-1][2] == "All technologies"
        assert rows[5][4] == "medium"  # day 6 starts week 2
        ov = wb["Program Overview"]
        print("  overview:", [(ov.cell(r, 1).value, str(ov.cell(r, 2).value)[:70]) for r in range(2, ov.max_row + 1)])
        assert str(ov["B6"].value).startswith("=SUM(")
        tp = wb["Technology Plan"]
        print("  tech plan:", [[tp.cell(r, c).value for c in (1, 2, 3, 4, 5)] for r in range(2, tp.max_row + 1)])
        wp = wb["Weekly Plan"]
        print("  weekly:", [[wp.cell(r, c).value for c in (1, 2, 3)] for r in range(2, wp.max_row + 1)])
