"""Production orders as PDF (ReportLab) and Word (python-docx). One order per batch; several orders make one file,
each starting on a new page with its own page numbering ("Page 1 of 2")."""
from __future__ import annotations

import base64
import io

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, Image, KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

INK = colors.HexColor("#1d1628")
LINE = colors.HexColor("#8a8496")
SOFT = colors.HexColor("#efedf3")
STATUS_MARK = {"draft": "DRAFT", "cancelled": "CANCELLED"}
WEIGHTS = {"ser": 0.5, "name": 3.2, "code": 1.6, "qty_required": 1.1, "qty_issued": 1.1, "uom": 0.7, "lot": 1.2,
           "qc": 1.1, "assay": 1.0, "remarks": 1.6, "dispensed_by": 1.3, "checked_by": 1.3}


def _logo_bytes(logo: str | None) -> bytes | None:
    if not logo or "," not in logo:
        return None
    try:
        return base64.b64decode(logo.split(",", 1)[1])
    except Exception:
        return None


def _esc(s) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sign_text(sig: dict | None) -> str:
    if not sig:
        return ""
    return f"{sig['user_name']}\n{sig['signed_at']}\nSigned electronically"


# ------------------------------------------------------------------ PDF
class _Start(Flowable):
    """Marks the start of an order so the page footer knows which order and page it is on."""
    def __init__(self, index: int):
        super().__init__()
        self.index = index
        self.width = self.height = 0

    def draw(self):
        doc = self.canv._doctemplate
        doc.current = self.index
        doc.first_page[self.index] = self.canv.getPageNumber()


class _Doc(BaseDocTemplate):
    def __init__(self, buf, orders, counts, **kw):
        super().__init__(buf, **kw)
        self.orders, self.counts, self.current, self.first_page = orders, counts, 0, {}


def _styles():
    base = ParagraphStyle("b", fontName="Helvetica", fontSize=9, leading=11.5, textColor=INK)
    return {
        "base": base,
        "bold": ParagraphStyle("bo", parent=base, fontName="Helvetica-Bold"),
        "title": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21, alignment=TA_CENTER),
        "num": ParagraphStyle("n", parent=base, fontName="Helvetica-Bold", fontSize=10, alignment=TA_RIGHT),
        "head": ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", fontSize=8.5, alignment=TA_CENTER),
        "cell": ParagraphStyle("c", parent=base, fontSize=8.5, leading=10.5),
        "cellc": ParagraphStyle("cc", parent=base, fontSize=8.5, leading=10.5, alignment=TA_CENTER),
        "small": ParagraphStyle("s", parent=base, fontSize=7.5, leading=9, textColor=colors.HexColor("#5c546c")),
    }


def _order_story(o: dict, idx: int, st: dict, width: float) -> list:
    c, t = o["content"], o["content"]["template"]
    story: list = [_Start(idx)]
    logo = _logo_bytes(t.get("logo"))
    logo_cell = ""
    if logo:
        img = ImageReader(io.BytesIO(logo))
        iw, ih = img.getSize()
        h = 16 * mm
        w = min(55 * mm, iw * h / ih)
        logo_cell = Image(io.BytesIO(logo), width=w, height=w * ih / iw)
    top = Table([[logo_cell, Paragraph(_esc(t["title"]), st["title"]),
                  Paragraph(f"Order Number: {_esc(c['number'])}", st["num"])]],
                colWidths=[width * 0.28, width * 0.44, width * 0.28])
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [top, Spacer(1, 4)]

    fields = [f for f in t["header_fields"]]
    ncol = max(1, int(t.get("header_columns") or 3))
    rows = []
    for i in range(0, len(fields), ncol):
        chunk = fields[i:i + ncol]
        rows.append([Paragraph(f"<b>{_esc(f['label'])}:</b> {_esc(c['values'].get(f['key'], ''))}", st["cell"]) for f in chunk]
                    + [""] * (ncol - len(chunk)))
    if rows:
        ht = Table(rows, colWidths=[width / ncol] * ncol)
        ht.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story += [ht, Spacer(1, 8)]

    cols = t["columns"]
    weights = WEIGHTS
    total = sum(weights.get(x["key"], 1) for x in cols)
    widths = [width * weights.get(x["key"], 1) / total for x in cols]
    data = [[Paragraph(_esc(x["label"]), st["head"]) for x in cols]]
    centered = {"ser", "qty_required", "qty_issued", "uom"}
    for ln in c["lines"]:
        data.append([Paragraph(_esc(ln.get(x["key"], "")), st["cellc"] if x["key"] in centered else st["cell"]) for x in cols])
    if len(data) == 1:
        data.append([Paragraph("No materials of the listed types in this batch's bill of materials.", st["small"])]
                    + [""] * (len(cols) - 1))
    mt = Table(data, colWidths=widths, repeatRows=1)
    style = [("GRID", (0, 0), (-1, -1), 0.6, LINE), ("BACKGROUND", (0, 0), (-1, 0), SOFT),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    for j, x in enumerate(cols):
        if x["key"] in ("ser", "qty_required", "qty_issued", "uom"):
            style.append(("ALIGN", (j, 1), (j, -1), "CENTER"))
    mt.setStyle(TableStyle(style))
    story += [mt, Spacer(1, 10)]

    if t.get("remarks_label") or t.get("remarks_lines"):
        rem = [Paragraph(f"<b>{_esc(t.get('remarks_label') or '')}</b>", st["base"])]
        for _ in range(int(t.get("remarks_lines") or 0)):
            rem.append(Spacer(1, 9))
            rem.append(_Rule(width))
        story += [KeepTogether(rem), Spacer(1, 12)]

    sigs = t["signatures"]
    if sigs:
        signed = {s["level"]: s for s in o.get("signatures", [])}
        head = [Paragraph(f"<b>{_esc(s['title'])}:</b>", st["cell"]) for s in sigs]
        body = [Paragraph(_esc(_sign_text(signed.get(i))).replace("\n", "<br/>"), st["small"]) for i in range(len(sigs))]
        sg = Table([head, body], colWidths=[width / len(sigs)] * len(sigs), rowHeights=[None, 16 * mm])
        sg.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, LINE), ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
                                ("VALIGN", (0, 1), (-1, 1), "TOP"), ("BACKGROUND", (0, 0), (-1, 0), SOFT)]))
        story += [KeepTogether([sg])]
    return story


class _Rule(Flowable):
    def __init__(self, width):
        super().__init__()
        self.width, self.height = width, 1

    def draw(self):
        self.canv.setStrokeColor(LINE)
        self.canv.setDash(1, 2)
        self.canv.line(0, 0, self.width, 0)


def _footer(canv, doc):
    o = doc.orders[doc.current]
    t = o["content"]["template"]
    w, h = doc.pagesize
    canv.saveState()
    canv.setFont("Helvetica", 8)
    canv.setFillColor(INK)
    if t.get("format_number"):
        canv.drawString(doc.leftMargin, 10 * mm, f"Format Number: {t['format_number']}")
    page = canv.getPageNumber() - doc.first_page.get(doc.current, canv.getPageNumber()) + 1
    canv.drawRightString(w - doc.rightMargin, 10 * mm, f"Page {page} of {doc.counts[doc.current]}")
    if t.get("footer_note"):
        canv.drawCentredString(w / 2, 10 * mm, t["footer_note"][:140])
    if o.get("revision"):
        canv.setFont("Helvetica", 7.5)
        canv.drawString(doc.leftMargin, 6 * mm, f"Revision {o['revision']}")
    mark = STATUS_MARK.get(o.get("status"))
    if mark:
        canv.setFont("Helvetica-Bold", 90)
        canv.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.12))
        canv.translate(w / 2, h / 2)
        canv.rotate(28)
        canv.drawCentredString(0, -30, mark)
    canv.restoreState()


def _pdf_once(orders: list[dict], counts: list[int]) -> tuple[bytes, list[int]]:
    buf = io.BytesIO()
    size = landscape(A4) if orders[0]["content"]["template"].get("orientation", "landscape") == "landscape" else A4
    doc = _Doc(buf, orders, counts, pagesize=size, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
               bottomMargin=18 * mm, title="Production orders", author="Complanning")
    templates = []
    for i, o in enumerate(orders):
        sz = landscape(A4) if o["content"]["template"].get("orientation", "landscape") == "landscape" else A4
        fr = Frame(14 * mm, 18 * mm, sz[0] - 28 * mm, sz[1] - 30 * mm, id=f"f{i}", leftPadding=0, rightPadding=0,
                   topPadding=0, bottomPadding=0)
        templates.append(PageTemplate(id=f"o{i}", frames=[fr], onPageEnd=_footer, pagesize=sz))
    doc.addPageTemplates(templates)
    st = _styles()
    story: list = []
    from reportlab.platypus.doctemplate import NextPageTemplate
    for i, o in enumerate(orders):
        sz = templates[i].pagesize
        if i:
            story += [NextPageTemplate(f"o{i}"), PageBreak()]
        story += _order_story(o, i, st, sz[0] - 28 * mm)
    doc.build(story)
    # Pages per order, from where each order started.
    starts = [doc.first_page[i] for i in range(len(orders))]
    total = doc.page
    per = [(starts[i + 1] if i + 1 < len(starts) else total + 1) - starts[i] for i in range(len(starts))]
    return buf.getvalue(), per


def render_pdf(orders: list[dict]) -> bytes:
    _, per = _pdf_once(orders, [1] * len(orders))
    data, _ = _pdf_once(orders, per)
    return data


# ------------------------------------------------------------------ Word
def _cell_text(cell, text, bold=False, size=9, align=None):
    cell.text = ""
    p = cell.paragraphs[0]
    for i, part in enumerate(str(text or "").split("\n")):
        if i:
            p.add_run().add_break()
        r = p.add_run(part)
        r.bold = bold
        r.font.size = Pt(size)
    if align:
        p.alignment = align


def _shade(cell, hex_fill="EFEDF3"):
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc.append(shd)


def _field(par, instr: str, size=8):
    r = par.add_run()
    r.font.size = Pt(size)
    for kind, text in (("begin", None), (None, instr), ("separate", None), (None, "1"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
            r._r.append(el)
        elif text == "1":
            t = OxmlElement("w:t")
            t.text = "1"
            r._r.append(t)
        else:
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = f" {text} "
            r._r.append(it)


def render_docx(orders: list[dict]) -> bytes:
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(9)
    for i, o in enumerate(orders):
        c, t = o["content"], o["content"]["template"]
        sec = doc.sections[0] if i == 0 else doc.add_section()
        land = t.get("orientation", "landscape") == "landscape"
        sec.orientation = WD_ORIENT.LANDSCAPE if land else WD_ORIENT.PORTRAIT
        sec.page_width, sec.page_height = (Cm(29.7), Cm(21.0)) if land else (Cm(21.0), Cm(29.7))
        for m in ("left_margin", "right_margin"):
            setattr(sec, m, Cm(1.4))
        sec.top_margin, sec.bottom_margin, sec.header_distance, sec.footer_distance = Cm(1.0), Cm(1.4), Cm(0.6), Cm(0.6)
        width = sec.page_width - sec.left_margin - sec.right_margin
        # Page numbers restart with each order.
        pg = OxmlElement("w:pgNumType")
        pg.set(qn("w:start"), "1")
        sec._sectPr.append(pg)

        # Header: logo, title, order number (own header per order).
        hdr = sec.header
        hdr.is_linked_to_previous = False
        for p in list(hdr.paragraphs):
            p.text = ""
        ht = hdr.add_table(1, 3, width)
        ht.alignment = WD_TABLE_ALIGNMENT.CENTER
        logo = _logo_bytes(t.get("logo"))
        if logo:
            ht.cell(0, 0).paragraphs[0].add_run().add_picture(io.BytesIO(logo), height=Cm(1.6))
        _cell_text(ht.cell(0, 1), t["title"], bold=True, size=16, align=WD_ALIGN_PARAGRAPH.CENTER)
        _cell_text(ht.cell(0, 2), f"Order Number: {c['number']}", bold=True, size=10, align=WD_ALIGN_PARAGRAPH.RIGHT)

        ftr = sec.footer
        ftr.is_linked_to_previous = False
        ftr.paragraphs[0].text = ""
        ft = ftr.add_table(1, 2, width)
        left = ft.cell(0, 0).paragraphs[0]
        r = left.add_run(f"Format Number: {t['format_number']}" if t.get("format_number") else "")
        r.font.size = Pt(8)
        if t.get("footer_note"):
            r2 = left.add_run(f"    {t['footer_note']}")
            r2.font.size = Pt(8)
        fp = ft.cell(0, 1).paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        x = fp.add_run("Page ")
        x.font.size = Pt(8)
        _field(fp, "PAGE")
        y = fp.add_run(" of ")
        y.font.size = Pt(8)
        _field(fp, "SECTIONPAGES")
        if o.get("revision"):
            rv = ftr.add_paragraph(f"Revision {o['revision']}")
            rv.runs[0].font.size = Pt(7)

        body_start = doc.add_paragraph() if i else (doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph())
        mark = STATUS_MARK.get(o.get("status"))
        if mark:
            rr = body_start.add_run(mark)
            rr.bold = True
            rr.font.size = Pt(12)
            rr.font.color.rgb = RGBColor(0xB4, 0x23, 0x18)

        fields = t["header_fields"]
        ncol = max(1, int(t.get("header_columns") or 3))
        if fields:
            rows = (len(fields) + ncol - 1) // ncol
            tb = doc.add_table(rows, ncol)
            tb.style = "Table Grid"
            for k, f in enumerate(fields):
                cell = tb.cell(k // ncol, k % ncol)
                cell.text = ""
                p = cell.paragraphs[0]
                a = p.add_run(f"{f['label']}: ")
                a.bold = True
                a.font.size = Pt(9)
                b = p.add_run(str(c["values"].get(f["key"], "")))
                b.font.size = Pt(9)
            doc.add_paragraph()

        cols = t["columns"]
        mt = doc.add_table(1 + max(1, len(c["lines"])), len(cols))
        mt.style = "Table Grid"
        for j, col in enumerate(cols):
            _cell_text(mt.cell(0, j), col["label"], bold=True, size=8.5, align=WD_ALIGN_PARAGRAPH.CENTER)
            _shade(mt.cell(0, j))
        for k, ln in enumerate(c["lines"], start=1):
            for j, col in enumerate(cols):
                center = col["key"] in ("ser", "qty_required", "qty_issued", "uom")
                _cell_text(mt.cell(k, j), ln.get(col["key"], ""), size=8.5, align=WD_ALIGN_PARAGRAPH.CENTER if center else None)
        if not c["lines"]:
            _cell_text(mt.cell(1, 0), "No materials of the listed types in this batch's bill of materials.", size=8)
        total = sum(WEIGHTS.get(col["key"], 1) for col in cols)
        mt.autofit = False
        grid = mt._tbl.tblGrid.findall(qn("w:gridCol"))
        for j, col in enumerate(cols):
            w = int(width * WEIGHTS.get(col["key"], 1) / total)
            if j < len(grid):
                grid[j].set(qn("w:w"), str(int(w / 635)))
            for row in mt.rows:
                row.cells[j].width = w
        # Mark the header row to repeat on each page.
        trpr = mt.rows[0]._tr.get_or_add_trPr()
        th = OxmlElement("w:tblHeader")
        th.set(qn("w:val"), "true")
        trpr.append(th)

        if t.get("remarks_label") or t.get("remarks_lines"):
            p = doc.add_paragraph()
            rr = p.add_run(t.get("remarks_label") or "")
            rr.bold = True
            for _ in range(int(t.get("remarks_lines") or 0)):
                doc.add_paragraph("…" * 120).runs[0].font.size = Pt(7)

        sigs = t["signatures"]
        if sigs:
            doc.add_paragraph()
            signed = {s["level"]: s for s in o.get("signatures", [])}
            sg = doc.add_table(2, len(sigs))
            sg.style = "Table Grid"
            for j, s in enumerate(sigs):
                _cell_text(sg.cell(0, j), f"{s['title']}:", bold=True, size=9)
                _shade(sg.cell(0, j))
                _cell_text(sg.cell(1, j), _sign_text(signed.get(j)), size=8)
            sg.rows[1].height = Cm(1.6)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
