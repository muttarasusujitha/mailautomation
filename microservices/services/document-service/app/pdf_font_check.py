"""Fail the image build when the ToC course-outline fonts would not be used.

The course-outline PDF (trainer-service ``app/toc_pdf_template.py``) sets headings
in Poppins and body text in Calibri, or its metric-compatible Carlito. When a
font is missing, WeasyPrint substitutes another one without an error. This check
renders a sample with the same font stacks and reads the fonts embedded in the PDF.

    python -m app.pdf_font_check
"""

import re
import subprocess
import sys

SAMPLE = """<html><body>
<p style="font: 400 26pt Poppins, 'Segoe UI', Arial, sans-serif">Course Outline</p>
<p style="font: 500 14pt Poppins, 'Segoe UI', Arial, sans-serif">Course Outline</p>
<p style="font: 700 13pt Poppins, 'Segoe UI', Arial, sans-serif">Day 1</p>
<p style="font-family: Calibri, Carlito, 'Segoe UI', Arial, sans-serif">Participants verify each check.</p>
<p style="font-family: Calibri, Carlito, 'Segoe UI', Arial, sans-serif; font-weight: 700">Lab Deliverable</p>
</body></html>"""
REQUIRED_FACES = {("Poppins", "Regular"), ("Poppins", "Medium"), ("Poppins", "Bold"),
                  ("Carlito", "Regular"), ("Carlito", "Bold")}
TEMPLATE_FAMILIES = ("Poppins", "Carlito")


def embedded_font_names(pdf: bytes) -> list:
    """Font names in an uncompressed PDF, without the subset prefix ("ABCDEF+")."""
    names = set()
    for raw in re.findall(rb"/BaseFont\s*/([^\s/<>\[\]()]+)", pdf):
        name = re.sub(r"#([0-9A-Fa-f]{2})", lambda match: chr(int(match.group(1), 16)), raw.decode("latin-1"))
        names.add(name.split("+", 1)[-1])
    return sorted(names)


def installed_faces() -> set:
    output = subprocess.run(["fc-list", "--format", "%{family[0]}|%{style[0]}\n"],
                            capture_output=True, text=True, check=True).stdout
    return {tuple(line.split("|", 1)) for line in output.splitlines() if "|" in line}


def problems() -> list:
    found = []
    missing = sorted(REQUIRED_FACES - installed_faces())
    if missing:
        found.append("fonts not installed: " + ", ".join(f"{family} {style}" for family, style in missing))
    from weasyprint import HTML  # raises here if WeasyPrint's native libraries are missing

    names = embedded_font_names(HTML(string=SAMPLE).write_pdf(uncompressed_pdf=True))
    substituted = [name for name in names if not name.startswith(TEMPLATE_FAMILIES)]
    if substituted or not names:
        found.append("WeasyPrint used other fonts: " + (", ".join(substituted) or "none embedded"))
    return found


def main() -> int:
    found = problems()
    for problem in found:
        print("PDF font check failed:", problem, file=sys.stderr)
    if not found:
        print("PDF font check passed: Poppins and Carlito are embedded")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
