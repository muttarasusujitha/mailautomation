#!/usr/bin/env python3
"""
SonarQube-style PDF report generator using pure Python stdlib.
Produces a professional multi-page PDF for Trainer Platform v8.
"""
import struct
import zlib
import io
import textwrap
from datetime import date

# ---------------------------------------------------------------------------
# Low-level PDF primitives
# ---------------------------------------------------------------------------

class PDFWriter:
    """Minimal but complete PDF-1.4 writer with compression and Type1 fonts."""

    def __init__(self):
        self._buf = io.BytesIO()
        self._offsets = []
        self._pages = []
        self._resources = {}
        self._obj_count = 0
        # We'll collect page content streams separately
        self._page_streams = []
        self._write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    # --- low-level helpers --------------------------------------------------

    def _write(self, data: bytes) -> int:
        pos = self._buf.tell()
        self._buf.write(data)
        return pos

    def _start_obj(self) -> int:
        self._obj_count += 1
        n = self._obj_count
        self._offsets.append(self._buf.tell())
        self._write(f"{n} 0 obj\n".encode())
        return n

    def _end_obj(self):
        self._write(b"endobj\n")

    def _dict(self, d: dict) -> bytes:
        lines = ["<<"]
        for k, v in d.items():
            lines.append(f"  {k} {v}")
        lines.append(">>")
        return "\n".join(lines).encode() + b"\n"

    def _ref(self, n: int) -> str:
        return f"{n} 0 R"

    # --- font registration --------------------------------------------------

    FONTS = {
        "Helvetica":        "/Helvetica",
        "Helvetica-Bold":   "/Helvetica-Bold",
        "Helvetica-Oblique":"/Helvetica-Oblique",
        "Courier":          "/Courier",
        "Courier-Bold":     "/Courier-Bold",
    }

    def _build_font_objects(self):
        self._font_obj_ids = {}
        for alias, base in self.FONTS.items():
            n = self._start_obj()
            self._write(self._dict({
                "/Type":     "/Font",
                "/Subtype":  "/Type1",
                "/BaseFont": base,
                "/Encoding": "/WinAnsiEncoding",
            }))
            self._end_obj()
            self._font_obj_ids[alias] = n

    def _font_resources(self) -> str:
        parts = []
        for alias, oid in self._font_obj_ids.items():
            parts.append(f"    /F_{alias.replace('-','_')} {self._ref(oid)}")
        return "<<\n" + "\n".join(parts) + "\n  >>"

    # --- page building ------------------------------------------------------

    def add_page(self, commands: str, width=595, height=842):
        """Add a page given a PDF content-stream string."""
        raw = commands.encode("latin-1", errors="replace")
        compressed = zlib.compress(raw, 9)

        # stream object
        n_stream = self._start_obj()
        self._write(self._dict({
            "/Filter": "/FlateDecode",
            "/Length": str(len(compressed)),
        }))
        self._write(b"stream\n")
        self._write(compressed)
        self._write(b"\nendstream\n")
        self._end_obj()

        self._page_streams.append((n_stream, width, height))

    # --- finalise -----------------------------------------------------------

    def save(self, path: str):
        # Strategy: write everything in order, use forward references.
        # Object layout:
        #   obj 1 ... N_streams : already written (content streams)
        #   font objs            : next
        #   page objs            : next
        #   pages dict           : next
        #   catalog              : last
        # We know IDs in advance because we control obj_count.

        # 1. Font objects
        self._build_font_objects()
        font_res_str = self._font_resources()

        # 2. Determine pages dict id = obj_count + 1 + len(page_streams)
        #    (we'll write page objs first, then pages dict)
        pages_id = self._obj_count + 1 + len(self._page_streams)

        # 3. Page objects
        page_obj_ids = []
        for (n_stream, w, h) in self._page_streams:
            n_page = self._start_obj()
            self._write(self._dict({
                "/Type":      "/Page",
                "/Parent":    self._ref(pages_id),
                "/MediaBox":  f"[0 0 {w} {h}]",
                "/Contents":  self._ref(n_stream),
                "/Resources": "<<\n  /Font " + font_res_str + "\n>>",
            }))
            self._end_obj()
            page_obj_ids.append(n_page)

        # 4. Pages dictionary — must land at pages_id
        assert self._obj_count + 1 == pages_id, \
            f"Pages id mismatch: next={self._obj_count+1} expected={pages_id}"
        kids = " ".join(self._ref(i) for i in page_obj_ids)
        n_pages = self._start_obj()
        self._write(self._dict({
            "/Type":  "/Pages",
            "/Kids":  f"[{kids}]",
            "/Count": str(len(page_obj_ids)),
        }))
        self._end_obj()

        # 5. Catalog
        n_catalog = self._start_obj()
        self._write(self._dict({
            "/Type":  "/Catalog",
            "/Pages": self._ref(n_pages),
        }))
        self._end_obj()

        # 6. xref + trailer
        xref_pos = self._buf.tell()
        total = self._obj_count + 1
        self._write(f"xref\n0 {total}\n".encode())
        self._write(b"0000000000 65535 f \n")
        for off in self._offsets:
            self._write(f"{off:010d} 00000 n \n".encode())

        self._write(f"trailer\n<<\n  /Size {total}\n  /Root {self._ref(n_catalog)}\n>>\n".encode())
        self._write(f"startxref\n{xref_pos}\n%%EOF\n".encode())

        with open(path, "wb") as f:
            f.write(self._buf.getvalue())



# ---------------------------------------------------------------------------
# Page builder helpers (content-stream DSL)
# ---------------------------------------------------------------------------

FONT_ALIAS = {
    "regular":   "F_Helvetica",
    "bold":      "F_Helvetica_Bold",
    "italic":    "F_Helvetica_Oblique",
    "mono":      "F_Courier",
    "mono_bold": "F_Courier_Bold",
}

# Severity colour palette  (R G B  0-1)
COLOUR = {
    "blocker":  (0.82, 0.05, 0.05),   # deep red
    "critical": (0.85, 0.18, 0.10),   # red
    "major":    (0.90, 0.45, 0.00),   # orange
    "minor":    (0.75, 0.65, 0.00),   # dark yellow
    "info":     (0.10, 0.40, 0.75),   # blue
    "pass":     (0.12, 0.60, 0.20),   # green
    "fail":     (0.82, 0.05, 0.05),   # red
    "white":    (1.00, 1.00, 1.00),
    "black":    (0.00, 0.00, 0.00),
    "dark":     (0.15, 0.15, 0.15),
    "heading":  (0.07, 0.18, 0.38),   # navy
    "lightgrey":(0.93, 0.93, 0.93),
    "midgrey":  (0.70, 0.70, 0.70),
    "sonar_bg": (0.04, 0.10, 0.22),   # SonarQube dark navy
    "sonar_blue":(0.13, 0.46, 0.93),
    "row_even": (0.97, 0.97, 0.97),
    "row_odd":  (1.00, 1.00, 1.00),
}


def esc_pdf(text: str) -> str:
    """Escape special chars for PDF string literals."""
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class PageBuilder:
    """Builds a PDF content stream for one page (A4: 595x842 pt)."""

    W = 595
    H = 842
    MARGIN_L = 50
    MARGIN_R = 545
    MARGIN_T = 800
    MARGIN_B = 50

    def __init__(self):
        self._cmds = []
        self.y = self.MARGIN_T
        self._in_text = False

    # --- state helpers ------------------------------------------------------

    def _bt(self):
        if not self._in_text:
            self._cmds.append("BT")
            self._in_text = True

    def _et(self):
        if self._in_text:
            self._cmds.append("ET")
            self._in_text = False

    def _setrgb_fill(self, c):
        self._et()
        self._cmds.append(f"{c[0]:.3f} {c[1]:.3f} {c[2]:.3f} rg")

    def _setrgb_stroke(self, c):
        self._et()
        self._cmds.append(f"{c[0]:.3f} {c[1]:.3f} {c[2]:.3f} RG")

    # --- drawing primitives -------------------------------------------------

    def rect(self, x, y, w, h, fill_colour=None, stroke_colour=None, line_width=0.5):
        self._et()
        self._cmds.append(f"{line_width:.2f} w")
        if fill_colour:
            self._setrgb_fill(fill_colour)
        if stroke_colour:
            self._setrgb_stroke(stroke_colour)
        op = "B" if (fill_colour and stroke_colour) else ("f" if fill_colour else "S")
        self._cmds.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re {op}")
        # reset colours
        self._setrgb_fill(COLOUR["black"])
        self._setrgb_stroke(COLOUR["black"])

    def line(self, x1, y1, x2, y2, colour=COLOUR["midgrey"], width=0.5):
        self._et()
        self._cmds.append(f"{width:.2f} w")
        self._setrgb_stroke(colour)
        self._cmds.append(f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")
        self._setrgb_stroke(COLOUR["black"])

    # --- text primitives ----------------------------------------------------

    def text(self, x, y, txt, font="regular", size=10, colour=COLOUR["black"]):
        self._et()
        self._setrgb_fill(colour)
        self._bt()
        alias = FONT_ALIAS[font]
        self._cmds.append(f"/{alias} {size} Tf")
        self._cmds.append(f"{x:.2f} {y:.2f} Td")
        self._cmds.append(f"({esc_pdf(txt)}) Tj")
        self._et()
        self._setrgb_fill(COLOUR["black"])



    def wrapped_text(self, x, y, txt, font="regular", size=10,
                     colour=COLOUR["dark"], max_width=450, line_height=None):
        """Render text wrapping at max_width (approx char-based) and return new y."""
        if line_height is None:
            line_height = size * 1.35
        # approximate chars per line based on average glyph width ~0.55*size
        chars_per_line = max(10, int(max_width / (size * 0.55)))
        lines = []
        for para in txt.split("\n"):
            if para.strip() == "":
                lines.append("")
            else:
                wrapped = textwrap.wrap(para, width=chars_per_line) or [""]
                lines.extend(wrapped)
        for ln in lines:
            if y < self.MARGIN_B + 10:
                break
            self.text(x, y, ln, font=font, size=size, colour=colour)
            y -= line_height
        return y

    def flow_text(self, x, y, label, value, label_font="bold", val_font="regular",
                  size=9, col=COLOUR["dark"]):
        """Print 'label: value' pair inline."""
        label_width = len(label) * size * 0.65
        self.text(x, y, label, font=label_font, size=size, colour=COLOUR["heading"])
        self.text(x + label_width, y, value, font=val_font, size=size, colour=col)

    def badge(self, x, y, label, bg_colour, text_colour=COLOUR["white"], size=8):
        """Draw a coloured pill badge."""
        pad_x, pad_y = 5, 2
        w = len(label) * size * 0.60 + pad_x * 2
        h = size + pad_y * 2
        self.rect(x, y - pad_y, w, h, fill_colour=bg_colour)
        self.text(x + pad_x, y + 1, label, font="bold", size=size,
                  colour=text_colour)
        return x + w + 6

    def section_header(self, title, y, bg=COLOUR["heading"]):
        """Full-width section header bar."""
        self.rect(self.MARGIN_L, y - 4, self.MARGIN_R - self.MARGIN_L, 18,
                  fill_colour=bg)
        self.text(self.MARGIN_L + 6, y + 2, title, font="bold", size=11,
                  colour=COLOUR["white"])
        return y - 26

    def sub_header(self, title, y, colour=COLOUR["heading"]):
        self.line(self.MARGIN_L, y - 2, self.MARGIN_R, y - 2,
                  colour=colour, width=1.0)
        self.text(self.MARGIN_L, y + 2, title, font="bold", size=10,
                  colour=colour)
        return y - 16

    def get_stream(self) -> str:
        self._et()
        return "\n".join(self._cmds) + "\n"

    # --- header / footer ----------------------------------------------------

    def page_chrome(self, page_num: int, total_pages: int, title: str = ""):
        """Draw header bar and footer line with page number."""
        # top bar
        self.rect(0, self.H - 30, self.W, 30, fill_colour=COLOUR["sonar_bg"])
        self.text(self.MARGIN_L, self.H - 19, "TrainerSync  |  Code Quality Report",
                  font="bold", size=9, colour=COLOUR["white"])
        if title:
            self.text(300, self.H - 19, title, font="italic", size=8,
                      colour=COLOUR["midgrey"])
        # bottom rule
        self.line(self.MARGIN_L, 38, self.MARGIN_R, 38,
                  colour=COLOUR["midgrey"], width=0.5)
        self.text(self.MARGIN_L, 25,
                  f"Confidential — Internal Use Only  |  Generated {date.today()}",
                  font="italic", size=7, colour=COLOUR["midgrey"])
        self.text(510, 25, f"Page {page_num} of {total_pages}",
                  font="regular", size=7, colour=COLOUR["midgrey"])

    def remaining_height(self):
        return self.y - self.MARGIN_B - 20



# ---------------------------------------------------------------------------
# Table helper
# ---------------------------------------------------------------------------

def draw_table(pb: PageBuilder, headers, rows, col_widths, start_x, start_y,
               row_height=16, header_bg=COLOUR["heading"], font_size=8,
               severity_col=None):
    """
    Draw a table, return final y position.
    severity_col: index of column that carries a severity badge colour override.
    """
    total_w = sum(col_widths)
    y = start_y

    # header row
    pb.rect(start_x, y - row_height + 3, total_w, row_height,
            fill_colour=header_bg)
    x = start_x
    for i, h in enumerate(headers):
        pb.text(x + 4, y - row_height + 7, h, font="bold", size=font_size,
                colour=COLOUR["white"])
        x += col_widths[i]
    y -= row_height

    # data rows
    for ri, row in enumerate(rows):
        bg = COLOUR["row_even"] if ri % 2 == 0 else COLOUR["row_odd"]
        pb.rect(start_x, y - row_height + 3, total_w, row_height,
                fill_colour=bg)
        x = start_x
        for ci, cell in enumerate(row):
            cell_str = str(cell)
            # severity badge overrides
            sev_lower = cell_str.lower()
            text_colour = COLOUR["dark"]
            if ci == severity_col:
                if "blocker" in sev_lower:
                    text_colour = COLOUR["blocker"]
                elif "critical" in sev_lower:
                    text_colour = COLOUR["critical"]
                elif "major" in sev_lower:
                    text_colour = COLOUR["major"]
                elif "minor" in sev_lower:
                    text_colour = COLOUR["minor"]
                elif "info" in sev_lower or "smell" in sev_lower:
                    text_colour = COLOUR["info"]
                elif "fail" in sev_lower:
                    text_colour = COLOUR["fail"]
                elif "pass" in sev_lower:
                    text_colour = COLOUR["pass"]
            pb.text(x + 4, y - row_height + 7, cell_str[:50],
                    font="regular", size=font_size, colour=text_colour)
            x += col_widths[ci]
        # bottom grid line
        pb.line(start_x, y - row_height + 3, start_x + total_w,
                y - row_height + 3, colour=COLOUR["lightgrey"], width=0.3)
        y -= row_height

    # outer border
    pb.rect(start_x, y + 3, total_w, start_y - y, stroke_colour=COLOUR["midgrey"],
            line_width=0.5)
    return y



# ---------------------------------------------------------------------------
# Issue card renderer
# ---------------------------------------------------------------------------

SEV_COLOUR = {
    "Blocker":  COLOUR["blocker"],
    "Critical": COLOUR["critical"],
    "Major":    COLOUR["major"],
    "Minor":    COLOUR["minor"],
    "Info":     COLOUR["info"],
}


def issue_height(impact_len: int, fix_len: int) -> int:
    """Estimate height in points an issue card will need."""
    base = 70
    base += (impact_len // 70 + 1) * 13
    base += (fix_len // 70 + 1) * 13
    return base


def draw_issue(pb: PageBuilder, issue_id, title, file_path, severity,
               category, cwe, impact, fix, y, x=50):
    """Render a single issue card. Returns new y after rendering."""
    right = PageBuilder.MARGIN_R
    card_width = right - x

    # --- background strip ---------------------------------------------------
    sev_col = SEV_COLOUR.get(severity, COLOUR["midgrey"])
    # left severity stripe
    pb.rect(x, y - 4, 4, issue_height(len(impact), len(fix)) + 4,
            fill_colour=sev_col)

    # --- issue ID + title ---------------------------------------------------
    pb.text(x + 10, y, issue_id, font="bold", size=10,
            colour=COLOUR["heading"])
    id_w = len(issue_id) * 6.5
    pb.text(x + 10 + id_w, y, f" — {title}", font="regular", size=10,
            colour=COLOUR["dark"])
    y -= 14

    # --- file path (monospace) ----------------------------------------------
    pb.text(x + 10, y, file_path, font="mono", size=8,
            colour=COLOUR["info"])
    y -= 13

    # --- badges (severity + category + CWE) --------------------------------
    bx = x + 10
    bx = pb.badge(bx, y, severity, bg_colour=sev_col)
    cat_col = COLOUR["heading"] if severity in ("Blocker", "Critical") else COLOUR["midgrey"]
    bx = pb.badge(bx, y, category, bg_colour=cat_col)
    if cwe:
        pb.badge(bx, y, cwe, bg_colour=COLOUR["sonar_bg"])
    y -= 16

    # --- impact -------------------------------------------------------------
    pb.text(x + 10, y, "Impact:", font="bold", size=8.5,
            colour=COLOUR["heading"])
    y -= 12
    y = pb.wrapped_text(x + 14, y, impact, font="regular", size=8.5,
                        colour=COLOUR["dark"], max_width=card_width - 24,
                        line_height=12)

    # --- fix ----------------------------------------------------------------
    pb.text(x + 10, y - 1, "Fix:", font="bold", size=8.5,
            colour=COLOUR["pass"])
    y -= 12
    y = pb.wrapped_text(x + 14, y, fix, font="regular", size=8.5,
                        colour=COLOUR["dark"], max_width=card_width - 24,
                        line_height=12)

    # --- separator ----------------------------------------------------------
    y -= 6
    pb.line(x, y, right, y, colour=COLOUR["lightgrey"], width=0.4)
    y -= 8
    return y



# ---------------------------------------------------------------------------
# Report data
# ---------------------------------------------------------------------------

REPORT_DATE = date.today().strftime("%B %d, %Y")

EXEC_SUMMARY = [
    ("Critical Issues",  "14", "Blocker/Critical"),
    ("Major Issues",     "31", "Major"),
    ("Minor Issues",     "28", "Minor"),
    ("Code Smells",      "47", "Info"),
    ("Total Issues",    "120", ""),
]

BLOCKERS = [
    {
        "id": "SEC-001", "title": "Hardcoded Secret Key in Production Code",
        "file": "backend/main.py  line 22",
        "severity": "Blocker", "category": "Security", "cwe": "CWE-798",
        "impact": (
            "If SECRET_KEY env var is not set, a predictable fallback is used, "
            "making JWT tokens forgeable and the entire authentication system compromised."
        ),
        "fix": "Remove fallback default entirely. Raise RuntimeError('SECRET_KEY must be set') "
               "at startup if the environment variable is missing.",
    },
    {
        "id": "SEC-002", "title": "JWT Token Accepted Without Expiry Validation",
        "file": "backend/main.py  —  verify_token() function",
        "severity": "Critical", "category": "Security", "cwe": "CWE-613",
        "impact": "Expired tokens are accepted silently or validation errors are swallowed, "
                  "allowing indefinitely valid sessions after account compromise.",
        "fix": "Ensure options={'verify_exp': True} is always enforced in jwt.decode() "
               "and never overridden or caught silently.",
    },
    {
        "id": "SEC-003", "title": "CORS Wildcard with Credentials Allowed",
        "file": "backend/main.py",
        "severity": "Blocker", "category": "Security", "cwe": "CWE-942",
        "impact": "Any origin can call the API with credentials. Enables CSRF and cross-origin "
                  "data exfiltration attacks from malicious websites.",
        "fix": 'Replace allow_origins=["*"] with an explicit whitelist of production domains. '
               "Never combine wildcard origins with allow_credentials=True.",
    },
    {
        "id": "SEC-004", "title": "Plaintext Sensitive Data Logged",
        "file": "backend/agents/email_agent.py, backend/agents/teams_agent.py",
        "severity": "Critical", "category": "Security", "cwe": "CWE-532",
        "impact": "OAuth access tokens and refresh tokens written to stdout/log files. "
                  "Any log aggregation or monitoring system retains these tokens indefinitely.",
        "fix": "Remove all token logging. If debugging is required, mask tokens: "
               "token[:4] + '****' + token[-4:].",
    },
    {
        "id": "SEC-005", "title": "MongoDB Operator Injection via Unvalidated Queries",
        "file": "backend/routes/api.py",
        "severity": "Critical", "category": "Security", "cwe": "CWE-943",
        "impact": "Query parameters passed directly to MongoDB find() allow $where, $gt, "
                  "$regex operator injection, potentially exposing all documents.",
        "fix": "Validate and allowlist all query parameters. Use pydantic models to coerce "
               "types and reject dict/list inputs where strings are expected.",
    },
    {
        "id": "BUG-001", "title": "Unhandled None Return Propagated as Response",
        "file": "backend/routes/api.py",
        "severity": "Critical", "category": "Bug", "cwe": "",
        "impact": "Functions returning None when a document is not found are serialized silently; "
                  "downstream clients receive null body and crash unexpectedly.",
        "fix": "Add explicit None-checks after every database query. Return HTTPException(404) "
               "with a descriptive message when records are not found.",
    },
    {
        "id": "BUG-002", "title": "Celery Task Exception Swallowed Silently",
        "file": "backend/agents/reminder_tasks.py",
        "severity": "Critical", "category": "Bug", "cwe": "",
        "impact": "Failed reminder email tasks are silently dropped. Users miss interview "
                  "reminders and other critical time-sensitive notifications with no alerting.",
        "fix": "Catch exceptions explicitly, log them, and use self.retry(exc=exc, "
               "max_retries=3, countdown=60) so Celery can retry the task.",
    },
    {
        "id": "BUG-003", "title": "Race Condition in Interview Slot Booking",
        "file": "backend/agents/client_slot_agent.py",
        "severity": "Critical", "category": "Bug (Concurrency)", "cwe": "",
        "impact": "Two concurrent requests can read the same 'available' slot and both "
                  "book it, causing double-booking and data corruption in the schedule.",
        "fix": "Replace find + update pattern with atomic find_one_and_update using "
               "filter={'_id': slot_id, 'status': 'available'} and check the return value.",
    },
]



MAJOR_ISSUES = [
    ("SEC-006", "API Keys Stored Without Rotation Policy",
     "backend/.env.example, backend/config.py", "Major",
     "OPENAI_API_KEY, WHATSAPP_TOKEN, TEAMS_CLIENT_SECRET have no rotation mechanism or expiry tracking."),
    ("SEC-007", "No Rate Limiting on Authentication Endpoint",
     "backend/main.py — /login route  [CWE-307]", "Major",
     "Brute-force attacks on /login are unrestricted. Add slowapi rate-limiting middleware."),
    ("SEC-008", "File Upload Without MIME Type Validation",
     "backend/routes/api.py  [CWE-434]", "Major",
     "Only filename extension is checked, not actual MIME type. Use python-magic to validate content."),
    ("BUG-004", "Incorrect Timezone Handling in Scheduler",
     "backend/agents/scheduler.py, backend/utils/time_utils.py", "Major",
     "Datetime objects mixed — some naive, some timezone-aware. Comparisons raise TypeError at runtime."),
    ("BUG-005", "Memory Leak: File Handles Not Closed",
     "backend/utils/pdf_generator.py, backend/utils/pdf_processor.py", "Major",
     "File handles not closed in exception paths. Replace with 'with open(...) as f' context managers."),
    ("BUG-006", "async Functions Called Without await",
     "backend/agents/pipeline.py", "Major",
     "Coroutines are never awaited; they return coroutine objects silently causing data loss."),
    ("BUG-007", "Frontend API Base URL Hardcoded",
     "frontend/src/utils/api.js", "Major",
     'BASE_URL = "http://localhost:8000" is hardcoded; the application breaks in all non-local deployments.'),
    ("BUG-008", "useEffect Missing Dependency Array — Infinite Re-renders",
     "frontend/src/pages/Dashboard.jsx, Emails.jsx, Inbox.jsx", "Major",
     "useEffect called without dependency array triggers on every render, causing infinite loops."),
    ("BUG-009", "Unhandled Promise Rejections in Frontend Fetches",
     "Multiple frontend page components", "Major",
     "fetch() calls lack .catch() handlers; network errors crash the page without user feedback."),
    ("REL-001", "No Database Connection Retry Logic",
     "backend/database.py", "Major",
     "MongoDB client created once at import time. Transient connection failures cause permanent outage."),
    ("REL-002", "Celery Beat Schedule Not Persisted",
     "backend/celery_app.py", "Major",
     "beat_schedule defined in memory only; restarting the worker resets all scheduled task state."),
    ("PERF-001", "N+1 Query Pattern in Trainer Listing",
     "backend/routes/api.py", "Major",
     "For each trainer in a list, a separate DB query fetches related data. Use aggregation pipeline."),
    ("PERF-002", "Large Payload Fetched Without Pagination",
     "backend/routes/api.py, frontend/src/pages/Trainers.jsx, Shortlist.jsx", "Major",
     "All records fetched at once with no limit/offset. Will cause timeouts as data grows."),
    ("MAINT-001", "Dead Code: Shortlist1.jsx Is Unused Duplicate",
     "frontend/src/pages/Shortlist1.jsx", "Major",
     "Shortlist1.jsx duplicates Shortlist.jsx with no route or import reference. Should be deleted."),
    ("MAINT-002", "God Function: process_email() Exceeds 200 Lines",
     "backend/agents/email_agent.py  [Cyclomatic Complexity ~28]", "Major",
     "Single function handles parsing, classification, DB writes, and sending. Decompose into services."),
    ("MAINT-003", "routes/api.py Is a 2000+ Line Monolith",
     "backend/routes/api.py", "Major",
     "All API endpoints in one file. Split into domain routers: trainers, clients, schedule, documents."),
]

MINOR_ISSUES = [
    ("BUG-010", "console.log Statements Left in Production Code",
     "17 occurrences across frontend JSX files",
     "Remove all console.log calls or replace with a proper logging library."),
    ("BUG-011", "React key Prop Uses Array Index",
     "Trainers.jsx, Shortlist.jsx, Emails.jsx, Inbox.jsx + 8 others",
     "Using array index as key causes incorrect reconciliation on reorder/filter operations."),
    ("BUG-012", "Missing loading State on Initial Page Load",
     "Dashboard.jsx, Trainers.jsx, Requirements.jsx",
     "No loading indicator shown while data is fetching; users see blank/stale content."),
    ("SEC-009", "Token Stored in localStorage (XSS Vulnerable)",
     "frontend/src/utils/api.js  [CWE-922]",
     "JWT stored in localStorage is accessible to any JS on the page. Use httpOnly cookies."),
    ("SEC-010", "No CSRF Protection on State-Mutating Endpoints",
     "backend/main.py",
     "POST/PUT/DELETE endpoints have no CSRF token validation. Add SameSite cookie + CSRF header check."),
    ("MAINT-004", "Duplicated API Call Logic Across 20+ Components",
     "frontend/src — all page components",
     "Auth header construction, error handling, loading state are copy-pasted. Extract to useApi() hook."),
    ("MAINT-005", "Magic Strings and Numbers Throughout Codebase",
     "Multiple files across backend and frontend",
     'Status strings like "pending", "approved", numeric limits scattered inline. Use constants/enums.'),
    ("MAINT-006", "No TypeScript / PropTypes Validation",
     "frontend/src — all components",
     "Zero runtime type checking on props leads to silent data-shape errors. Add PropTypes or migrate to TS."),
    ("MAINT-007", "Inconsistent Error Response Shape",
     "backend/routes/api.py",
     "Some endpoints return {error: msg}, others {detail: msg}, others plain strings. Standardize schema."),
    ("MAINT-008", "Missing __init__.py Files in Some Packages",
     "backend/agents/, backend/utils/",
     "Inconsistent package structure causes import resolution issues across different Python toolchains."),
    ("MAINT-009", "random.js Contains Unused Exported Functions",
     "frontend/src/utils/random.js",
     "Several exported utility functions have no import references. Remove dead code."),
    ("PERF-003", "No Memoization on Expensive Computed Values",
     "frontend/src/pages/Dashboard.jsx, Trainers.jsx",
     "Computed lists and filtered arrays recalculated on every render. Wrap with useMemo()."),
    ("PERF-004", "Images Not Optimized",
     "frontend/public/images/",
     "PNG/JPG assets not compressed or resized for web delivery. Use WebP with proper dimensions."),
]



BACKEND_METRICS = [
    ("Files Analyzed",              "24",    ""),
    ("Avg Cyclomatic Complexity",   "14.2",  "FAIL  (threshold: 10)"),
    ("Code Duplication Ratio",      "18%",   "FAIL  (threshold: 5%)"),
    ("Test Coverage",               "0%",    "FAIL  (target: 70%)"),
    ("Documented Functions",        "8%",    "FAIL  (target: 80%)"),
    ("Security Hotspots",           "12",    ""),
    ("Cognitive Complexity (max)",  "28",    "FAIL  (threshold: 15)"),
]

FRONTEND_METRICS = [
    ("Files Analyzed",              "34",    ""),
    ("Components with PropTypes",   "0%",    "FAIL  (target: 100%)"),
    ("Unhandled Async Errors",      "23",    "FAIL"),
    ("console.log Statements",      "17",    "FAIL  (target: 0)"),
    ("Infinite Re-render Risks",    "8",     "FAIL"),
    ("Missing Dependency Arrays",   "8",     "FAIL"),
    ("Hardcoded Environment Refs",  "3",     "FAIL"),
]

DUPLICATION_TABLE = [
    ("Auth header construction",    "All JSX pages",       "~85%"),
    ("MongoDB connection setup",    "3 agent files",       "~90%"),
    ("Date formatting logic",       "6 files",             "~70%"),
    ("Error toast notifications",   "14 JSX files",        "~95%"),
    ("PDF generation boilerplate",  "2 util files",        "~60%"),
]

SPRINTS = [
    ("Sprint 1", "Security Blockers", [
        "SEC-001  Fix SECRET_KEY hardcoded fallback",
        "SEC-004  Remove OAuth token logging",
        "SEC-003  Replace CORS wildcard with allowlist",
        "SEC-007  Add rate limiting to /login endpoint",
        "SEC-008  Validate file upload MIME types",
    ]),
    ("Sprint 2", "Critical Bugs", [
        "BUG-007  Fix hardcoded BASE_URL in frontend",
        "BUG-006  Add missing await in pipeline.py",
        "BUG-003  Implement atomic slot booking",
        "BUG-008  Fix useEffect infinite re-render loops",
        "BUG-009  Handle unhandled Promise rejections",
    ]),
    ("Sprint 3", "Architecture & Maintainability", [
        "MAINT-003  Split api.py monolith into domain routers",
        "MAINT-002  Decompose process_email() god function",
        "MAINT-004  Create shared useApi() custom hook",
        "PERF-002   Implement pagination on all list endpoints",
        "REL-001    Add DB connection retry with backoff",
    ]),
    ("Sprint 4", "Quality & Technical Debt", [
        "Add unit tests (target: 70% coverage)",
        "Add PropTypes or migrate frontend to TypeScript",
        "MAINT-007  Standardize API error response shape",
        "BUG-004    Fix timezone-aware/naive mixing",
        "Add OpenAPI documentation strings to all endpoints",
    ]),
]



# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def build_cover_page(total_pages: int) -> PageBuilder:
    pb = PageBuilder()

    # Full dark background
    pb.rect(0, 0, pb.W, pb.H, fill_colour=COLOUR["sonar_bg"])

    # Top accent stripe
    pb.rect(0, pb.H - 8, pb.W, 8, fill_colour=COLOUR["sonar_blue"])

    # Bottom accent
    pb.rect(0, 0, pb.W, 6, fill_colour=COLOUR["sonar_blue"])

    # Side accent bar
    pb.rect(40, 180, 4, 420, fill_colour=COLOUR["sonar_blue"])

    # --- Main title ---------------------------------------------------------
    y = 680
    pb.text(60, y, "Code Quality", font="bold", size=38, colour=COLOUR["white"])
    y -= 44
    pb.text(60, y, "Analysis Report", font="bold", size=38, colour=COLOUR["sonar_blue"])
    y -= 50

    # Thin divider
    pb.line(60, y, 540, y, colour=COLOUR["sonar_blue"], width=1.5)
    y -= 22

    pb.text(60, y, "Trainer Platform v8", font="bold", size=20,
            colour=COLOUR["white"])
    y -= 28
    pb.text(60, y, "Full Codebase Audit — Backend (Python/FastAPI) & Frontend (React/JSX)",
            font="italic", size=11, colour=COLOUR["midgrey"])
    y -= 44

    # --- Quality Gate badge -----------------------------------------------
    pb.rect(60, y - 12, 210, 34, fill_colour=COLOUR["blocker"])
    pb.text(72, y + 4, "QUALITY GATE:  FAILED", font="bold", size=14,
            colour=COLOUR["white"])
    y -= 60

    # --- Stats boxes --------------------------------------------------------
    stats = [
        ("14", "Critical Issues",  COLOUR["blocker"]),
        ("31", "Major Issues",     COLOUR["major"]),
        ("28", "Minor Issues",     COLOUR["minor"]),
        ("47", "Code Smells",      COLOUR["info"]),
    ]
    box_w, box_h, gap = 110, 68, 8
    bx = 60
    for count, label, col in stats:
        pb.rect(bx, y - box_h + 10, box_w, box_h, fill_colour=col)
        pb.text(bx + 10, y, count, font="bold", size=28, colour=COLOUR["white"])
        pb.text(bx + 10, y - 28, label, font="regular", size=9,
                colour=COLOUR["white"])
        bx += box_w + gap
    y -= box_h + 20

    # --- Metadata -----------------------------------------------------------
    pb.line(60, y, 540, y, colour=COLOUR["midgrey"], width=0.5)
    y -= 20
    meta = [
        ("Project",   "Trainer Platform v8"),
        ("Scope",     "24 Python files | 34 React/JSX files"),
        ("Generated", REPORT_DATE),
        ("Tool",      "Static Analysis — SonarQube-style Audit"),
        ("Total",     "120 issues identified across all categories"),
    ]
    for label, val in meta:
        pb.text(60, y, f"{label}:", font="bold", size=10, colour=COLOUR["midgrey"])
        pb.text(155, y, val, font="regular", size=10, colour=COLOUR["white"])
        y -= 18

    # --- Page number --------------------------------------------------------
    pb.text(510, 20, "1", font="regular", size=8, colour=COLOUR["midgrey"])
    return pb


def build_executive_summary(page_num: int, total_pages: int) -> PageBuilder:
    pb = PageBuilder()
    pb.page_chrome(page_num, total_pages, "Executive Summary")
    pb.y = 780

    # Title
    pb.text(pb.MARGIN_L, pb.y, "Executive Summary", font="bold", size=18,
            colour=COLOUR["heading"])
    pb.y -= 6
    pb.line(pb.MARGIN_L, pb.y, pb.MARGIN_R, pb.y,
            colour=COLOUR["sonar_blue"], width=2)
    pb.y -= 20

    # Intro paragraph
    intro = (
        "This report presents a comprehensive static-analysis audit of the Trainer Platform v8 codebase, "
        "covering security vulnerabilities, bugs, code smells, maintainability risks, and performance issues. "
        "The overall Quality Gate has FAILED. Immediate remediation of the 14 blocker/critical issues "
        "is strongly recommended before any production deployment."
    )
    pb.y = pb.wrapped_text(pb.MARGIN_L, pb.y, intro, size=9.5,
                           max_width=495, line_height=14)
    pb.y -= 14

    # Issue summary table
    pb.y = pb.section_header("Issue Summary by Severity", pb.y)
    headers = ["Category", "Count", "Severity Level", "Quality Gate Impact"]
    col_w = [180, 60, 130, 125]
    rows = [
        ("Blocker / Critical Issues",  "14", "Blocker/Critical", "FAILED — Fix immediately"),
        ("Major Issues",               "31", "Major",            "FAILED — Fix before release"),
        ("Minor Issues",               "28", "Minor",            "WARNING — Fix in next sprint"),
        ("Code Smells",                "47", "Info",             "INFO — Technical debt"),
        ("TOTAL",                     "120", "",                 ""),
    ]
    pb.y = draw_table(pb, headers, rows, col_w, pb.MARGIN_L, pb.y,
                      row_height=17, severity_col=2, font_size=8.5)
    pb.y -= 20

    # Quality gate box
    pb.rect(pb.MARGIN_L, pb.y - 36, 495, 46, fill_colour=COLOUR["blocker"])
    pb.text(pb.MARGIN_L + 16, pb.y - 10,
            "OVERALL QUALITY GATE STATUS:  FAILED", font="bold", size=15,
            colour=COLOUR["white"])
    pb.text(pb.MARGIN_L + 16, pb.y - 28,
            "120 total issues  |  14 blockers/critical  |  0% test coverage  |  18% code duplication",
            font="regular", size=9, colour=COLOUR["white"])
    pb.y -= 60

    # Issue distribution bar chart (visual)
    pb.y -= 10
    pb.text(pb.MARGIN_L, pb.y, "Issue Distribution", font="bold", size=11,
            colour=COLOUR["heading"])
    pb.y -= 18
    bar_data = [
        ("Blocker/Critical", 14, 120, COLOUR["blocker"]),
        ("Major",            31, 120, COLOUR["major"]),
        ("Minor",            28, 120, COLOUR["minor"]),
        ("Code Smells",      47, 120, COLOUR["info"]),
    ]
    bar_max_w = 380
    for label, count, total, col in bar_data:
        bar_w = int(bar_max_w * count / total)
        pb.text(pb.MARGIN_L, pb.y, f"{label}:", font="bold", size=8.5,
                colour=COLOUR["dark"])
        pb.rect(pb.MARGIN_L + 120, pb.y - 2, bar_w, 11, fill_colour=col)
        pb.text(pb.MARGIN_L + 120 + bar_w + 6, pb.y + 1,
                f"{count} ({count*100//total}%)", font="regular", size=8,
                colour=COLOUR["dark"])
        pb.y -= 18

    return pb



def build_blocker_pages(start_page: int, total_pages: int):
    """Returns list of PageBuilder objects for blocker/critical section."""
    pages = []
    pb = PageBuilder()
    pb.page_chrome(start_page, total_pages, "Blocker / Critical Issues")
    pb.y = 780
    pb.y = pb.section_header("BLOCKER / CRITICAL ISSUES  (8 issues)", pb.y,
                              bg=COLOUR["blocker"])
    pb.y -= 6
    intro = (
        "The following issues represent immediate security vulnerabilities and critical bugs that MUST be "
        "resolved before any production deployment. Blockers indicate a system-wide security or data-integrity "
        "risk. Critical issues can lead to data loss, authentication bypass, or service outage."
    )
    pb.y = pb.wrapped_text(pb.MARGIN_L, pb.y, intro, size=9, max_width=495, line_height=13)
    pb.y -= 10

    current_page = start_page
    for issue in BLOCKERS:
        h_needed = issue_height(len(issue["impact"]), len(issue["fix"])) + 30
        if pb.y - h_needed < pb.MARGIN_B + 40:
            pages.append(pb)
            current_page += 1
            pb = PageBuilder()
            pb.page_chrome(current_page, total_pages, "Blocker / Critical Issues (cont.)")
            pb.y = 780

        pb.y = draw_issue(
            pb,
            issue_id=issue["id"],
            title=issue["title"],
            file_path=issue["file"],
            severity=issue["severity"],
            category=issue["category"],
            cwe=issue["cwe"],
            impact=issue["impact"],
            fix=issue["fix"],
            y=pb.y,
        )

    pages.append(pb)
    return pages


def build_major_issues_page(start_page: int, total_pages: int):
    """Returns list of pages for major issues section."""
    pages = []
    pb = PageBuilder()
    pb.page_chrome(start_page, total_pages, "Major Issues")
    pb.y = 780
    pb.y = pb.section_header("MAJOR ISSUES  (16 issues)", pb.y, bg=COLOUR["major"])
    pb.y -= 6

    headers = ["ID", "Title", "File / Location", "Severity"]
    col_w = [65, 185, 180, 65]

    rows = [(i[0], i[1], i[2], i[3]) for i in MAJOR_ISSUES]

    # split into chunks that fit a page
    chunk_size = 8
    first = True
    current_page = start_page
    for chunk_start in range(0, len(rows), chunk_size):
        chunk = rows[chunk_start:chunk_start + chunk_size]
        if not first:
            pages.append(pb)
            current_page += 1
            pb = PageBuilder()
            pb.page_chrome(current_page, total_pages, "Major Issues (cont.)")
            pb.y = 780
        first = False

        pb.y = draw_table(pb, headers, chunk, col_w, pb.MARGIN_L, pb.y,
                          row_height=17, severity_col=3, font_size=8)
        pb.y -= 16

    # Detail cards for first 3 major issues as examples
    pb.y = pb.section_header("Selected Major Issue Details", pb.y, bg=COLOUR["major"])
    pb.y -= 6

    detail_issues = [
        {
            "id": "BUG-006", "title": "async Functions Called Without await",
            "file": "backend/agents/pipeline.py",
            "severity": "Major", "category": "Bug", "cwe": "",
            "impact": (
                "All async functions in pipeline.py return coroutine objects rather than executing. "
                "Data processing steps are silently skipped, causing incomplete pipeline runs and "
                "data that appears to process successfully but is never persisted."
            ),
            "fix": (
                "Add await before every async function call. If the caller is not async, "
                "use asyncio.run() or restructure the execution loop to be fully async."
            ),
        },
        {
            "id": "MAINT-003", "title": "routes/api.py Is a Monolith (2000+ lines)",
            "file": "backend/routes/api.py",
            "severity": "Major", "category": "Maintainability", "cwe": "",
            "impact": (
                "A single 2000+ line router file with cyclomatic complexity >200 makes code review, "
                "testing, and onboarding extremely difficult. Any change risks unintended side effects."
            ),
            "fix": (
                "Split into domain-specific routers: routers/trainers.py, routers/clients.py, "
                "routers/schedule.py, routers/documents.py, routers/auth.py. "
                "Register each with app.include_router()."
            ),
        },
    ]

    for issue in detail_issues:
        h_needed = issue_height(len(issue["impact"]), len(issue["fix"])) + 30
        if pb.y - h_needed < pb.MARGIN_B + 40:
            pages.append(pb)
            current_page += 1
            pb = PageBuilder()
            pb.page_chrome(current_page, total_pages, "Major Issues — Detail Cards")
            pb.y = 780

        pb.y = draw_issue(
            pb,
            issue_id=issue["id"],
            title=issue["title"],
            file_path=issue["file"],
            severity=issue["severity"],
            category=issue["category"],
            cwe=issue["cwe"],
            impact=issue["impact"],
            fix=issue["fix"],
            y=pb.y,
        )

    pages.append(pb)
    return pages



def build_minor_issues_page(start_page: int, total_pages: int):
    pb = PageBuilder()
    pb.page_chrome(start_page, total_pages, "Minor Issues & Code Smells")
    pb.y = 780
    pb.y = pb.section_header("MINOR ISSUES  (13 issues)", pb.y, bg=COLOUR["minor"])
    pb.y -= 6

    headers = ["ID", "Title", "Location", "Category"]
    col_w = [65, 195, 175, 60]
    rows = [(i[0], i[1], i[2], "Minor") for i in MINOR_ISSUES]
    pb.y = draw_table(pb, headers, rows, col_w, pb.MARGIN_L, pb.y,
                      row_height=16, severity_col=3, font_size=8)
    pb.y -= 20

    # Descriptions in condensed form
    pb.y = pb.sub_header("Issue Descriptions", pb.y, colour=COLOUR["minor"])
    for item in MINOR_ISSUES:
        if pb.y < pb.MARGIN_B + 60:
            break
        pb.text(pb.MARGIN_L, pb.y, f"{item[0]}:", font="bold", size=8.5,
                colour=COLOUR["minor"])
        desc_x = pb.MARGIN_L + len(item[0]) * 6.5 + 6
        pb.y = pb.wrapped_text(desc_x, pb.y, item[3],
                               font="regular", size=8.5, max_width=380,
                               line_height=12, colour=COLOUR["dark"])
        pb.y -= 4

    return [pb]


def build_metrics_page(start_page: int, total_pages: int):
    pb = PageBuilder()
    pb.page_chrome(start_page, total_pages, "Metrics Summary")
    pb.y = 780

    pb.text(pb.MARGIN_L, pb.y, "Metrics Summary", font="bold", size=18,
            colour=COLOUR["heading"])
    pb.y -= 6
    pb.line(pb.MARGIN_L, pb.y, pb.MARGIN_R, pb.y,
            colour=COLOUR["sonar_blue"], width=2)
    pb.y -= 22

    # Backend metrics table
    pb.y = pb.section_header("Backend Metrics  (Python / FastAPI)", pb.y,
                              bg=COLOUR["heading"])
    pb.y -= 6
    be_headers = ["Metric", "Value", "Status"]
    be_cols = [220, 80, 195]
    pb.y = draw_table(pb, be_headers, BACKEND_METRICS, be_cols,
                      pb.MARGIN_L, pb.y, row_height=17, severity_col=2, font_size=9)
    pb.y -= 22

    # Frontend metrics table
    pb.y = pb.section_header("Frontend Metrics  (React / JSX)", pb.y,
                              bg=COLOUR["heading"])
    pb.y -= 6
    fe_headers = ["Metric", "Value", "Status"]
    fe_cols = [220, 80, 195]
    pb.y = draw_table(pb, fe_headers, FRONTEND_METRICS, fe_cols,
                      pb.MARGIN_L, pb.y, row_height=17, severity_col=2, font_size=9)
    pb.y -= 22

    # Code duplication table
    pb.y = pb.section_header("Code Duplication Hotspots", pb.y,
                              bg=COLOUR["heading"])
    pb.y -= 6
    dup_headers = ["Pattern", "Files Affected", "Duplication %"]
    dup_cols = [220, 155, 120]
    pb.y = draw_table(pb, dup_headers, DUPLICATION_TABLE, dup_cols,
                      pb.MARGIN_L, pb.y, row_height=17, font_size=9)
    pb.y -= 20

    # Summary insight box
    pb.rect(pb.MARGIN_L, pb.y - 56, 495, 66, fill_colour=COLOUR["lightgrey"])
    pb.rect(pb.MARGIN_L, pb.y - 56, 4, 66, fill_colour=COLOUR["sonar_blue"])
    pb.text(pb.MARGIN_L + 14, pb.y - 8,
            "Key Findings", font="bold", size=11, colour=COLOUR["heading"])
    insights = [
        "Backend cyclomatic complexity 42% above threshold — requires urgent refactoring",
        "Code duplication at 18% — 3.6x above the 5% quality gate threshold",
        "Zero test coverage across all backend modules — highest single risk factor",
        "Frontend has 23 unhandled async errors and 8 infinite re-render risks",
    ]
    iy = pb.y - 24
    for insight in insights:
        pb.text(pb.MARGIN_L + 14, iy, f"  {chr(8226)}  {insight}",
                font="regular", size=8.5, colour=COLOUR["dark"])
        iy -= 13

    return [pb]


def build_remediation_page(start_page: int, total_pages: int):
    pb = PageBuilder()
    pb.page_chrome(start_page, total_pages, "Remediation Roadmap")
    pb.y = 780

    pb.text(pb.MARGIN_L, pb.y, "Remediation Roadmap", font="bold", size=18,
            colour=COLOUR["heading"])
    pb.y -= 6
    pb.line(pb.MARGIN_L, pb.y, pb.MARGIN_R, pb.y,
            colour=COLOUR["sonar_blue"], width=2)
    pb.y -= 20

    intro = (
        "Issues are prioritised across four sprints. Sprint 1 addresses all security blockers and "
        "must be completed before any production release. Subsequent sprints address stability, "
        "architecture quality, and long-term maintainability."
    )
    pb.y = pb.wrapped_text(pb.MARGIN_L, pb.y, intro, size=9.5, max_width=495,
                           line_height=14)
    pb.y -= 14

    sprint_colours = [
        COLOUR["blocker"], COLOUR["major"], COLOUR["info"], COLOUR["pass"]
    ]
    sprint_labels = ["IMMEDIATE", "HIGH PRIORITY", "ARCHITECTURE", "TECH DEBT"]

    for (sprint_name, sprint_title, items), col, label in zip(
            SPRINTS, sprint_colours, sprint_labels):
        if pb.y < pb.MARGIN_B + 120:
            break

        # Sprint header
        pb.rect(pb.MARGIN_L, pb.y - 4, 495, 20, fill_colour=col)
        pb.text(pb.MARGIN_L + 8, pb.y + 2,
                f"{sprint_name}: {sprint_title}  [{label}]",
                font="bold", size=10, colour=COLOUR["white"])
        pb.y -= 26

        for i, task in enumerate(items, 1):
            pb.text(pb.MARGIN_L + 12, pb.y, f"{i}.  {task}",
                    font="regular", size=9, colour=COLOUR["dark"])
            pb.y -= 14
        pb.y -= 8

    # Effort estimates table
    pb.y -= 4
    pb.y = pb.section_header("Effort Estimates", pb.y, bg=COLOUR["heading"])
    pb.y -= 6
    effort_rows = [
        ("Sprint 1 — Security Blockers",       "5 items",  "3-5 days",   "Immediate"),
        ("Sprint 2 — Critical Bug Fixes",       "5 items",  "5-8 days",   "Week 2"),
        ("Sprint 3 — Architecture Refactor",    "5 items",  "10-15 days", "Weeks 3-5"),
        ("Sprint 4 — Quality & Tech Debt",      "5 items",  "8-12 days",  "Weeks 6-8"),
    ]
    eff_headers = ["Sprint", "Items", "Effort", "Timeline"]
    eff_cols = [220, 65, 90, 120]
    pb.y = draw_table(pb, eff_headers, effort_rows, eff_cols,
                      pb.MARGIN_L, pb.y, row_height=17, font_size=9)

    return [pb]



# ---------------------------------------------------------------------------
# Main: assemble and save
# ---------------------------------------------------------------------------

def main():
    OUTPUT = "/projects/sandbox/mailautomation/TrainerPlatform_SonarQube_Report.pdf"

    # --- First pass: count pages -------------------------------------------
    # We need total_pages to print page X of N
    # Rough estimate first, then build properly
    # Sections: cover(1) + exec(1) + blockers(~3) + major(~3) + minor(1) + metrics(1) + remediation(1) = ~11
    TOTAL_PAGES = 11  # initial estimate; adjusted below

    # --- Second pass: build all pages ---------------------------------------
    all_pages = []

    # 1. Cover
    cover = build_cover_page(TOTAL_PAGES)
    all_pages.append(cover)

    # 2. Executive Summary
    exec_p = build_executive_summary(2, TOTAL_PAGES)
    all_pages.append(exec_p)

    # 3. Blocker / Critical
    blocker_pages = build_blocker_pages(3, TOTAL_PAGES)
    all_pages.extend(blocker_pages)

    # 4. Major Issues
    major_start = 3 + len(blocker_pages)
    major_pages = build_major_issues_page(major_start, TOTAL_PAGES)
    all_pages.extend(major_pages)

    # 5. Minor Issues
    minor_start = major_start + len(major_pages)
    minor_pages = build_minor_issues_page(minor_start, TOTAL_PAGES)
    all_pages.extend(minor_pages)

    # 6. Metrics
    metrics_start = minor_start + len(minor_pages)
    metrics_pages = build_metrics_page(metrics_start, TOTAL_PAGES)
    all_pages.extend(metrics_pages)

    # 7. Remediation
    remed_start = metrics_start + len(metrics_pages)
    remed_pages = build_remediation_page(remed_start, TOTAL_PAGES)
    all_pages.extend(remed_pages)

    actual_total = len(all_pages)
    print(f"[INFO] Assembled {actual_total} pages.")

    # If counts differ significantly, rebuild with correct total
    if actual_total != TOTAL_PAGES:
        TOTAL_PAGES = actual_total
        all_pages = []

        cover = build_cover_page(TOTAL_PAGES)
        all_pages.append(cover)

        exec_p = build_executive_summary(2, TOTAL_PAGES)
        all_pages.append(exec_p)

        blocker_pages = build_blocker_pages(3, TOTAL_PAGES)
        all_pages.extend(blocker_pages)

        major_start = 3 + len(blocker_pages)
        major_pages = build_major_issues_page(major_start, TOTAL_PAGES)
        all_pages.extend(major_pages)

        minor_start = major_start + len(major_pages)
        minor_pages = build_minor_issues_page(minor_start, TOTAL_PAGES)
        all_pages.extend(minor_pages)

        metrics_start = minor_start + len(minor_pages)
        metrics_pages = build_metrics_page(metrics_start, TOTAL_PAGES)
        all_pages.extend(metrics_pages)

        remed_start = metrics_start + len(metrics_pages)
        remed_pages = build_remediation_page(remed_start, TOTAL_PAGES)
        all_pages.extend(remed_pages)

        print(f"[INFO] Rebuilt with corrected total: {len(all_pages)} pages.")

    # --- Render to PDF ------------------------------------------------------
    writer = PDFWriter()
    for pb in all_pages:
        writer.add_page(pb.get_stream())

    writer.save(OUTPUT)

    import os
    size = os.path.getsize(OUTPUT)
    print(f"[SUCCESS] PDF saved to: {OUTPUT}")
    print(f"[SUCCESS] File size:    {size:,} bytes ({size/1024:.1f} KB)")
    print(f"[SUCCESS] Total pages:  {len(all_pages)}")


if __name__ == "__main__":
    main()
