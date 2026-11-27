"""PDF report generation. Pure rendering: dictionaries in, PDF bytes out (ReportLab only)."""
import io
import re
from datetime import datetime
from statistics import mean, median, pstdev
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

INK = colors.HexColor("#16222E")
MUTED = colors.HexColor("#5A6775")
BRAND = colors.HexColor("#0B6B73")
BRAND_TINT = colors.HexColor("#E3F1F2")
LINE = colors.HexColor("#D8DEE4")
ZEBRA = colors.HexColor("#F6F8FA")
OK = colors.HexColor("#1F7A4D")
WARN = colors.HexColor("#8A5A00")
WARN_TINT = colors.HexColor("#FFF3D4")
BAD = colors.HexColor("#B3361B")
PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def safe(text) -> str:
    """Escape Paragraph markup and replace characters unsupported by built-in PDF fonts."""
    value = "" if text is None else str(text)
    return escape(value.encode("cp1252", "replace").decode("cp1252"))


def num(x) -> str:
    try:
        value = round(float(x) + 0.0, 2)
    except (TypeError, ValueError):
        return "-"
    return f"{value:g}"


def pct(score, maximum) -> str:
    try:
        return f"{round(100 * float(score) / float(maximum))}%" if float(maximum) > 0 else "-"
    except (TypeError, ValueError):
        return "-"


def fmt_dt(value) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "").replace(" ", "T"))
        return dt.strftime("%d %b %Y, %H:%M") + " UTC"
    except ValueError:
        return str(value)


def outcome(row: dict) -> str:
    """Plain-language result of one question; never reveals the answer key."""
    if not row.get("is_graded"):
        return "Awaiting grading"
    awarded = float(row.get("marks_awarded") or 0)
    marks = float(row["marks"])
    written = row["question_type"] == "written"
    if awarded >= marks - 1e-9:
        return "Full marks" if written else "Correct"
    if awarded > 0:
        return "Partial marks" if written else "Partly correct"
    if not row.get("is_answered"):
        return "Not answered"
    return "No marks" if written else "Incorrect"


def _styles():
    base = dict(fontName="Helvetica", textColor=INK, leading=13, fontSize=9.5)
    return {
        "body": ParagraphStyle("body", **base),
        "small": ParagraphStyle("small", **{**base, "fontSize": 8.5, "textColor": MUTED, "leading": 11}),
        "h1": ParagraphStyle("h1", **{**base, "fontName": "Helvetica-Bold", "fontSize": 20, "leading": 24}),
        "kicker": ParagraphStyle("kicker", **{**base, "fontName": "Helvetica-Bold", "fontSize": 9, "textColor": BRAND, "leading": 12}),
        "h2": ParagraphStyle("h2", **{**base, "fontName": "Helvetica-Bold", "fontSize": 12, "leading": 15, "spaceBefore": 14, "spaceAfter": 6}),
        "th": ParagraphStyle("th", **{**base, "fontName": "Helvetica-Bold", "fontSize": 8.5, "textColor": MUTED}),
        "td": ParagraphStyle("td", **{**base, "fontSize": 9, "leading": 11.5}),
        "tdr": ParagraphStyle("tdr", **{**base, "fontSize": 9, "leading": 11.5, "alignment": 2}),
        "big": ParagraphStyle("big", **{**base, "fontName": "Helvetica-Bold", "fontSize": 28, "leading": 32}),
        "bigsub": ParagraphStyle("bigsub", **{**base, "fontSize": 9, "textColor": MUTED, "leading": 12}),
        "warn": ParagraphStyle("warn", **{**base, "textColor": colors.HexColor("#5E3E00")}),
        "mono": ParagraphStyle("mono", **{**base, "fontName": "Courier-Bold", "fontSize": 12, "leading": 15}),
    }


class _NumberedCanvas(rl_canvas.Canvas):
    """Adds page numbering, header and footer to every page."""
    doc_label = "Report"
    footer_left = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total):
        self.saveState()
        y = PAGE_H - 11 * mm
        self.setStrokeColor(BRAND)
        self.setLineWidth(2.2)
        self.circle(MARGIN + 3.2 * mm, y, 3.2 * mm, stroke=1, fill=0)
        self.setFillColor(BRAND)
        self.circle(MARGIN + 3.2 * mm, y, 1.3 * mm, stroke=0, fill=1)
        self.setFillColor(INK)
        self.setFont("Helvetica-Bold", 10.5)
        self.drawString(MARGIN + 9 * mm, y - 1.3 * mm, "ExamDesk")
        self.setFillColor(MUTED)
        self.setFont("Helvetica", 8.5)
        self.drawRightString(PAGE_W - MARGIN, y - 1.2 * mm, self.doc_label)
        self.setStrokeColor(LINE)
        self.setLineWidth(0.6)
        self.line(MARGIN, y - 5 * mm, PAGE_W - MARGIN, y - 5 * mm)
        self.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(MUTED)
        self.drawString(MARGIN, 8.5 * mm, self.footer_left)
        self.drawRightString(PAGE_W - MARGIN, 8.5 * mm, f"Page {self._pageNumber} of {total}")
        self.restoreState()


def _canvas_factory(label: str, footer: str):
    class NumberedCanvas(_NumberedCanvas):
        doc_label = label
        footer_left = footer
    return NumberedCanvas


def _table(rows, widths, header=True, align_right=(), zebra=True, repeat=1):
    table = Table(rows, colWidths=widths, repeatRows=repeat if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), BRAND_TINT),
                  ("LINEBELOW", (0, 0), (-1, 0), 0.8, BRAND)]
    if zebra:
        style += [("BACKGROUND", (0, i), (-1, i), ZEBRA)
                  for i in range(2 if header else 1, len(rows), 2)]
    table.setStyle(TableStyle(style))
    return table


def _kv(rows, styles, widths=(38 * mm, None)):
    second_width = CONTENT_W - widths[0]
    table = Table(
        [[Paragraph(safe(key), styles["small"]), Paragraph(safe(value), styles["td"])]
         for key, value in rows],
        colWidths=[widths[0], second_width],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _qr(url: str, size=32 * mm) -> Drawing:
    widget = QrCodeWidget(url)
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    drawing.add(widget)
    return drawing


def _box(text, styles, style="warn"):
    table = Table([[Paragraph(text, styles["warn"])]], colWidths=[CONTENT_W])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WARN_TINT),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#EBCB83")),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def topic_rows(questions: list) -> list:
    """Marks by topic from the candidate's own paper."""
    groups = {}
    for question in questions:
        group = groups.setdefault(question.get("category") or "General", {"n": 0, "got": 0.0, "max": 0.0})
        group["n"] += 1
        group["max"] += float(question["marks"])
        if question.get("is_graded"):
            group["got"] += float(question.get("marks_awarded") or 0)
    return [
        {"topic": name, "questions": values["n"], "got": max(0.0, values["got"]), "max": values["max"]}
        for name, values in sorted(groups.items())
    ]


def build_candidate_pdf(d: dict) -> bytes:
    """Build one candidate's result PDF; answer keys and other candidates are never included."""
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=24 * mm, bottomMargin=20 * mm,
        title=f"Result report - {d['exam_title']}", author="ExamDesk",
        subject="Examination result report",
    )
    out = [
        Paragraph("RESULT REPORT" + ("" if d["official"] else "  -  PROVISIONAL"), styles["kicker"]),
        Spacer(1, 3), Paragraph(safe(d["exam_title"]), styles["h1"]), Spacer(1, 8),
    ]
    out.append(_kv([
        ("Candidate", d["candidate"]), ("Roll number", d.get("roll_no") or "-"),
        ("Examiner", d["examiner"]), ("Exam duration", f"{d['duration_minutes']} minutes"),
        ("Submitted", fmt_dt(d["submitted_at"]) +
         (" (closed automatically when time ran out)" if d["status"] == "expired" else "")),
    ], styles))
    out.append(Spacer(1, 10))

    cohort = d.get("cohort")
    stand = ""
    if d["official"] and cohort and cohort.get("rank"):
        stand = f"Rank {cohort['rank']} of {cohort['n']} graded candidates<br/>Group average {cohort['mean_pct']}%"
    score = Table([[
        Paragraph(f"{num(d['total_score'])} <font size=14 color='#5A6775'>/ {num(d['max_score'])}</font>", styles["big"]),
        Paragraph(f"{pct(d['total_score'], d['max_score'])}<br/><font size=9 color='#5A6775'>of the marks</font>",
                  ParagraphStyle("score_pct", parent=styles["big"], fontSize=22, leading=26)),
        Paragraph(stand or "&nbsp;", styles["bigsub"]),
    ]], colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.24, CONTENT_W * 0.34])
    score.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_TINT), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 11),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    out.append(score)
    if not d["official"]:
        out += [
            Spacer(1, 8),
            _box("<b>Provisional report.</b> " +
                 safe(d.get("provisional_reason") or "This is not an official published result.") +
                 " It has no verification code and must not be used as proof of a result.", styles),
        ]

    topics = topic_rows(d["questions"])
    if topics:
        out.append(Paragraph("Performance by topic", styles["h2"]))
        rows = [[Paragraph(h, styles["th"]) for h in ("Topic", "Questions", "Marks", "Out of", "Score")]]
        for topic in topics:
            rows.append([
                Paragraph(safe(topic["topic"]), styles["td"]), Paragraph(str(topic["questions"]), styles["td"]),
                Paragraph(num(topic["got"]), styles["td"]), Paragraph(num(topic["max"]), styles["td"]),
                Paragraph(pct(topic["got"], topic["max"]), styles["td"]),
            ])
        out.append(_table(rows, [CONTENT_W * 0.40, CONTENT_W * 0.15, CONTENT_W * 0.15,
                                 CONTENT_W * 0.15, CONTENT_W * 0.15]))

    out.append(Paragraph("Question by question", styles["h2"]))
    type_name = {"mcq": "Single answer", "multi": "Multiple select", "written": "Written"}
    rows = [[Paragraph(h, styles["th"]) for h in ("No.", "Type", "Topic", "Marks", "Result")]]
    for question in d["questions"]:
        got = num(question["marks_awarded"]) if question.get("is_graded") else "-"
        rows.append([
            Paragraph(str(question["position"]), styles["td"]),
            Paragraph(type_name.get(question["question_type"], question["question_type"]), styles["td"]),
            Paragraph(safe(question.get("category") or "General"), styles["td"]),
            Paragraph(f"{got} / {num(question['marks'])}", styles["td"]),
            Paragraph(outcome(question), styles["td"]),
        ])
    out.append(_table(rows, [CONTENT_W * 0.08, CONTENT_W * 0.20, CONTENT_W * 0.30,
                             CONTENT_W * 0.16, CONTENT_W * 0.26]))

    comments = [q for q in d["questions"] if (q.get("grader_comment") or "").strip()]
    if comments:
        out.append(Paragraph("Examiner comments", styles["h2"]))
        for question in comments:
            out.append(Paragraph(f"<b>Question {question['position']}:</b> {safe(question['grader_comment'])[:600]}",
                                 styles["body"]))
            out.append(Spacer(1, 3))

    out.append(Spacer(1, 12))
    verification = d.get("verify")
    if verification:
        info = [
            Paragraph("Verify this report", styles["h2"]),
            Paragraph("Scan the code, or open the address below and enter the report ID. The page confirms that this report was issued by "
                      "ExamDesk and that the result has not changed since. It shows only the exam name, the score and the candidate's initials.",
                      styles["body"]),
            Spacer(1, 5),
            Paragraph(f"Report ID: <font face='Courier-Bold'>{safe(verification['code'])}</font>", styles["body"]),
            Paragraph(safe(verification["url"]), styles["small"]),
        ]
        block = Table([[_qr(verification["url"]), info]], colWidths=[36 * mm, CONTENT_W - 36 * mm])
        block.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.7, LINE),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        out.append(KeepTogether([block]))
    else:
        out.append(Paragraph("Verification codes are issued only for official results: published by the examiner and fully graded.",
                             styles["small"]))
    out.append(Spacer(1, 8))
    out.append(Paragraph("This report lists marks only. It does not include answer keys, other candidates' results or monitoring data.",
                         styles["small"]))
    footer = f"Generated {fmt_dt(d['generated_at'])}" + (
        f"  |  Report ID {verification['code']}" if verification else "  |  Provisional"
    )
    doc.build(out, canvasmaker=_canvas_factory("Result report", footer))
    return buffer.getvalue()


def score_stats(percents: list) -> dict:
    if not percents:
        return {}
    return {
        "n": len(percents), "mean": round(mean(percents), 1), "median": round(median(percents), 1),
        "std": round(pstdev(percents), 1) if len(percents) > 1 else 0.0,
        "min": round(min(percents), 1), "max": round(max(percents), 1),
    }


def histogram(percents: list, bins: int = 10) -> list:
    counts = [0] * bins
    for value in percents:
        counts[min(bins - 1, max(0, int(value // (100 / bins))))] += 1
    return counts


def build_exam_pdf(d: dict) -> bytes:
    """Build examiner's exam summary PDF."""
    styles = _styles()
    exam, counts_data = d["exam"], d["counts"]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=24 * mm, bottomMargin=20 * mm,
        title=f"Exam summary - {exam['title']}", author="ExamDesk",
        subject="Examination summary report",
    )
    out = [
        Paragraph("EXAMINATION SUMMARY  -  CONFIDENTIAL, FOR EXAMINERS", styles["kicker"]),
        Spacer(1, 3), Paragraph(safe(exam["title"]), styles["h1"]), Spacer(1, 8),
    ]
    paper = (
        f"Each candidate answers {exam['paper_size']} questions drawn from a pool of {exam['pool_size']}, "
        f"balanced to {num(exam['total_marks'])} marks"
        if exam.get("paper_size")
        else f"All candidates answer the same {exam['pool_size']} questions ({num(exam['total_marks'])} marks)"
    )
    out.append(_kv([
        ("Examiner", exam["examiner"]),
        ("Available", f"{fmt_dt(exam['start_time'])}  to  {fmt_dt(exam['end_time'])}"),
        ("Time allowed", f"{exam['duration_minutes']} minutes per candidate"),
        ("Paper", paper),
        ("Status", exam["status"].capitalize() +
         ("; results published" if exam.get("results_published") else "; results not published")),
    ], styles))

    out.append(Paragraph("Participation", styles["h2"]))
    cells = [
        ("Enrolled", counts_data["enrolled"]), ("Submitted", counts_data["submitted"]),
        ("Time expired", counts_data["expired"]), ("In progress", counts_data["in_progress"]),
        ("Not started", counts_data["not_started"]), ("Graded", counts_data["graded"]),
    ]
    tiles = Table([
        [Paragraph(f"<font size=17><b>{value}</b></font>", styles["body"]) for _, value in cells],
        [Paragraph(label, styles["small"]) for label, _ in cells],
    ], colWidths=[CONTENT_W / len(cells)] * len(cells))
    tiles.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_TINT),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.white),
    ]))
    out.append(tiles)

    graded = [r for r in d["rows"] if r.get("grading_status") == "graded" and r.get("percent") is not None]
    percentages = [r["percent"] for r in graded]
    out.append(Paragraph("Score distribution", styles["h2"]))
    if percentages:
        stats = score_stats(percentages)
        out.append(_table([
            [Paragraph(h, styles["th"]) for h in ("Graded", "Average", "Median", "Std. deviation", "Lowest", "Highest")],
            [Paragraph(str(v), styles["td"]) for v in (
                stats["n"], f"{stats['mean']}%", f"{stats['median']}%", f"{stats['std']} pts",
                f"{stats['min']}%", f"{stats['max']}%",
            )],
        ], [CONTENT_W / 6] * 6, zebra=False))
        out.append(Spacer(1, 6))
        bin_counts = histogram(percentages)
        drawing = Drawing(CONTENT_W, 120)
        chart = VerticalBarChart()
        chart.x, chart.y, chart.width, chart.height = 28, 22, CONTENT_W - 40, 86
        chart.data = [bin_counts]
        chart.categoryAxis.categoryNames = [f"{i * 10}-{i * 10 + 10}" for i in range(10)]
        chart.categoryAxis.labels.fontSize = 7
        chart.categoryAxis.labels.fontName = "Helvetica"
        chart.valueAxis.valueMin = 0
        chart.valueAxis.valueMax = max(max(bin_counts), 1) + (1 if max(bin_counts) < 5 else 0)
        chart.valueAxis.valueStep = max(1, round(chart.valueAxis.valueMax / 5))
        chart.valueAxis.labels.fontSize = 7
        chart.bars[0].fillColor = BRAND
        chart.bars[0].strokeColor = None
        chart.barWidth = 10
        chart.valueAxis.gridStrokeColor = LINE
        chart.valueAxis.visibleGrid = True
        drawing.add(chart)
        out.append(drawing)
        out.append(Paragraph(
            f"Candidates per score band (percent of marks). Based on {len(percentages)} fully graded attempt"
            f"{'s' if len(percentages) != 1 else ''}"
            + (f"; {counts_data['ungraded']} not yet graded "
               f"{'is' if counts_data['ungraded'] == 1 else 'are'} left out."
               if counts_data.get("ungraded") else "."),
            styles["small"],
        ))
    else:
        out.append(Paragraph("No fully graded attempts yet, so there are no score statistics to show.", styles["body"]))

    if d.get("topics"):
        out.append(Paragraph("Performance by topic", styles["h2"]))
        rows = [[Paragraph(h, styles["th"]) for h in ("Topic", "Questions", "Average score")]]
        for topic in d["topics"]:
            rows.append([
                Paragraph(safe(topic["topic"]), styles["td"]),
                Paragraph(str(topic["questions"]), styles["td"]),
                Paragraph(f"{topic['avg_pct']}%", styles["td"]),
            ])
        out.append(_table(rows, [CONTENT_W * 0.55, CONTENT_W * 0.2, CONTENT_W * 0.25]))

    highlights = d.get("highlights")
    if highlights and (highlights["hardest"] or highlights["most_skipped"] or highlights["needs_review"]):
        out.append(Paragraph("Question highlights", styles["h2"]))
        blocks = [
            ("Hardest in practice", [
                f"{safe(item['label'])} ({round(item['correct_rate'] * 100)}% correct)"
                for item in highlights["hardest"]
            ]),
            ("Most skipped", [
                f"{safe(item['label'])} ({round(item['skip_rate'] * 100)}% skipped)"
                for item in highlights["most_skipped"]
            ]),
            ("Worth a second look (key or wording)", [
                safe(item["label"]) for item in highlights["needs_review"]
            ]),
        ]
        for heading, items in blocks:
            if items:
                out.append(Paragraph(f"<b>{heading}</b>", styles["body"]))
                out += [Paragraph("-  " + item, styles["td"]) for item in items]
                out.append(Spacer(1, 4))
        out.append(Paragraph("These are statistical indicators from the attempts so far, not verdicts.", styles["small"]))

    out.append(Paragraph("Candidate results", styles["h2"]))
    status_name = {"submitted": "Submitted", "expired": "Time expired", "in_progress": "In progress"}
    rows = [[Paragraph(h, styles["th"]) for h in ("Candidate", "Roll no.", "Status", "Score", "%", "Grading")]]
    for row in d["rows"]:
        rows.append([
            Paragraph(safe(row["full_name"]), styles["td"]),
            Paragraph(safe(row.get("roll_no") or "-"), styles["td"]),
            Paragraph(status_name.get(row["status"], row["status"]), styles["td"]),
            Paragraph(f"{num(row['total_score'])} / {num(row['max_score'])}"
                      if row["status"] != "in_progress" else "-", styles["td"]),
            Paragraph(f"{round(row['percent'])}%"
                      if row.get("percent") is not None and row["status"] != "in_progress" else "-", styles["td"]),
            Paragraph({"graded": "Complete", "partial": "Partly graded", "pending": "Pending"}
                      .get(row["grading_status"], row["grading_status"]), styles["td"]),
        ])
    if len(rows) == 1:
        out.append(Paragraph("No candidate has attempted this exam yet.", styles["body"]))
    else:
        out.append(_table(rows, [CONTENT_W * 0.30, CONTENT_W * 0.16, CONTENT_W * 0.16,
                                 CONTENT_W * 0.14, CONTENT_W * 0.08, CONTENT_W * 0.16]))
    out += [
        Spacer(1, 10),
        Paragraph("Practice or preview attempts are not included. Monitoring indicators are not part of this report: "
                  "they are signals for human review and are never treated as results.", styles["small"]),
    ]
    doc.build(out, canvasmaker=_canvas_factory(
        "Examination summary", f"Generated {fmt_dt(d['generated_at'])}  |  Confidential"
    ))
    return buffer.getvalue()


CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def normalize_code(raw: str) -> str:
    """'exd 7k3q-m9wa 4htr' -> 'EXD-7K3Q-M9WA-4HTR'; empty if it cannot be a code."""
    value = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()
    if value.startswith("EXD"):
        value = value[3:]
    if not re.fullmatch(r"[A-Z0-9]{12}", value):
        return ""
    return "EXD-" + "-".join(value[i:i + 4] for i in range(0, 12, 4))
