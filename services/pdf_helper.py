"""Posthog-themed PDF report builder.

Build a ReportSpec, call render_report_pdf(buf, spec). Done.

Sections you can stack inside spec.sections:
    SectionTitle("Bill To")        →  bold sub-heading
    ParagraphBlock("<b>…</b>")     →  paragraph with reportlab mini-HTML
    TableSpec(headers, rows, …)    →  zebra-striped table w/ optional totals row
    CalloutCard(label, value, …)   →  big right-aligned number, orange left rail
    PageBreak()                    →  force a page break
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Set, Union, IO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Table, TableStyle,
    Paragraph, Spacer, PageBreak, Image,
)
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER


# Posthog palette
BG_PAGE      = colors.HexColor('#fdfdf8')
BG_SURFACE   = colors.HexColor('#ffffff')
BG_SURFACE_2 = colors.HexColor('#eeefe9')
BG_SURFACE_3 = colors.HexColor('#e5e7e0')
BORDER       = colors.HexColor('#bfc1b7')
BORDER_SOFT  = colors.HexColor('#dadbd0')
TEXT         = colors.HexColor('#4d4f46')
TEXT_STRONG  = colors.HexColor('#23251d')
TEXT_MUTED   = colors.HexColor('#65675e')
ACCENT       = colors.HexColor('#F54E00')
POS          = colors.HexColor('#2e7d32')
NEG          = colors.HexColor('#c0392b')


@dataclass
class KpiSpec:
    label: str
    value: str
    sub: str = ''
    negative: bool = False


@dataclass
class TableSpec:
    headers: List[str]
    rows: List[List[str]]
    col_widths: Optional[List[float]] = None
    totals_row: Optional[List[str]] = None
    num_cols: Set[int] = field(default_factory=set)            # right-align money cols
    sign_color_cols: Set[int] = field(default_factory=set)     # +/- → green/red


@dataclass
class SectionTitle:
    text: str
    bold: bool = True
    keep_with_next: bool = False   # don't orphan this heading from the block below it


@dataclass
class ParagraphBlock:
    html: str


@dataclass
class CalloutCard:
    label: str
    value: str
    suffix: str = ''
    negative: bool = False


@dataclass
class ImageBlock:
    """Embed a raster image (PNG / JPG / GIF) at a sensibly capped size.

    `path` may be a filesystem path OR a browser-loadable URL like
    `/static/uploads/foo.png` — leading slashes are stripped automatically.
    The image preserves its aspect ratio inside the (max_width, max_height) box.
    """
    path: str
    caption: str = ''
    max_width: float = 480        # points — narrower than full content area
    max_height: float = 420       # points — cap so doc doesn't balloon


@dataclass
class ReportSpec:
    title: str
    subtitle_parts: List[str] = field(default_factory=list)
    kpis: List[KpiSpec] = field(default_factory=list)
    sections: List[Union[TableSpec, SectionTitle, ParagraphBlock,
                         CalloutCard, ImageBlock, PageBreak]] = field(default_factory=list)
    footer_subtitle: Optional[str] = None
    generated_label: str = 'Generated'
    brand: str = 'WEALTH TRACKER'


def render_report_pdf(buffer: IO[bytes], spec: ReportSpec) -> None:
    page_w, page_h = A4
    L, R, T, B = 14 * mm, 14 * mm, 22 * mm, 18 * mm

    def page_chrome(canvas, doc):
        canvas.saveState()
        # Warm parchment canvas
        canvas.setFillColor(BG_PAGE)
        canvas.rect(0, 0, page_w, page_h, fill=1, stroke=0)
        # Orange accent stripe (4pt) at the very top
        canvas.setFillColor(ACCENT)
        canvas.rect(0, page_h - 4, page_w, 4, fill=1, stroke=0)
        # Sage-cream header band
        canvas.setFillColor(BG_SURFACE_2)
        canvas.rect(0, page_h - T + 2, page_w, T - 6, fill=1, stroke=0)
        # Wordmark + title.  The brand width varies (AITEX is 5 chars, IBRAHIM
        # TRADERS is 15), so measure it and offset the title with a fixed gap —
        # otherwise long brands collide with the title text.
        canvas.setFillColor(TEXT_STRONG)
        canvas.setFont('Helvetica-Bold', 11)
        canvas.drawString(L, page_h - 14, spec.brand)
        brand_w = canvas.stringWidth(spec.brand, 'Helvetica-Bold', 11)
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont('Helvetica', 8.5)
        # Vertical separator + 10pt gap on each side of it.
        sep_x = L + brand_w + 10
        canvas.setStrokeColor(BORDER_SOFT)
        canvas.setLineWidth(0.5)
        canvas.line(sep_x, page_h - 20, sep_x, page_h - 9)
        canvas.drawString(sep_x + 10, page_h - 14, spec.title)
        # Generated timestamp (right)
        stamp = f"{spec.generated_label} {datetime.now().strftime('%b %d, %Y · %H:%M')}"
        canvas.drawRightString(page_w - R, page_h - 14, stamp)
        # Footer rule
        canvas.setStrokeColor(BORDER_SOFT)
        canvas.setLineWidth(0.5)
        canvas.line(L, B - 4, page_w - R, B - 4)
        # Footer text
        canvas.setFillColor(TEXT_MUTED)
        canvas.setFont('Helvetica', 8.5)
        canvas.drawRightString(page_w - R, B - 12, f"Page {doc.page}")
        if spec.footer_subtitle:
            canvas.drawString(L, B - 12, spec.footer_subtitle)
        canvas.restoreState()

    doc = BaseDocTemplate(
        buffer, pagesize=A4,
        leftMargin=L, rightMargin=R, topMargin=T, bottomMargin=B,
        title=spec.title, author=spec.brand,
    )
    frame = Frame(L, B, page_w - L - R, page_h - T - B,
                  id='content', showBoundary=0)
    doc.addPageTemplates([
        PageTemplate(id='main', frames=[frame], onPage=page_chrome),
    ])
    doc.build(_build_story(spec, content_w=page_w - L - R))


def _build_story(spec: ReportSpec, *, content_w):
    title_style = ParagraphStyle(
        'Title', fontName='Helvetica-Bold', fontSize=22, leading=26,
        textColor=TEXT_STRONG, spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        'Subtitle', fontName='Helvetica', fontSize=10, leading=14,
        textColor=TEXT_MUTED, spaceAfter=10,
    )
    section_style = ParagraphStyle(
        'Section', fontName='Helvetica-Bold', fontSize=11, leading=13,
        textColor=TEXT_STRONG, spaceBefore=10, spaceAfter=6,
    )
    section_style_keep = ParagraphStyle(
        'SectionKeep', parent=section_style, keepWithNext=1,
    )
    body_style = ParagraphStyle(
        'Body', fontName='Helvetica', fontSize=9.5, leading=13,
        textColor=TEXT, spaceAfter=8,
    )

    story = [Paragraph(spec.title, title_style)]
    if spec.subtitle_parts:
        story.append(Paragraph(
            ' &nbsp;·&nbsp; '.join(spec.subtitle_parts), subtitle_style,
        ))
    if spec.kpis:
        story.append(_kpi_strip(spec.kpis, content_w))
        story.append(Spacer(1, 10))

    for entry in spec.sections:
        if isinstance(entry, SectionTitle):
            story.append(Paragraph(
                f"<b>{entry.text}</b>" if entry.bold else entry.text,
                section_style_keep if entry.keep_with_next else section_style,
            ))
        elif isinstance(entry, ParagraphBlock):
            story.append(Paragraph(entry.html, body_style))
        elif isinstance(entry, TableSpec):
            story.append(_data_table(entry, content_w))
            story.append(Spacer(1, 8))
        elif isinstance(entry, CalloutCard):
            story.append(_callout_card(entry, content_w))
            story.append(Spacer(1, 6))
        elif isinstance(entry, ImageBlock):
            img_flowable = _image_block(entry, content_w)
            if img_flowable is not None:
                story.append(img_flowable)
                story.append(Spacer(1, 8))
        elif isinstance(entry, PageBreak):
            story.append(entry)
    return story


def _image_block(blk: 'ImageBlock', content_w):
    """Build a centred Image flowable preserving aspect ratio, with caption."""
    import os
    path = blk.path or ''
    if path.startswith('/'):
        path = path.lstrip('/')                          # /static/... → static/...
    if not os.path.isfile(path):
        # Fall back to a placeholder paragraph if the file is missing.
        return Paragraph(
            f"<font color='#c0392b'>[Image not found: {path}]</font>",
            ParagraphStyle('img-missing', fontName='Helvetica', fontSize=9.5,
                           textColor=NEG, leading=13)
        )
    try:
        reader = ImageReader(path)
        iw, ih = reader.getSize()
    except Exception:
        return Paragraph(
            f"<font color='#c0392b'>[Image unreadable: {path}]</font>",
            ParagraphStyle('img-err', fontName='Helvetica', fontSize=9.5,
                           textColor=NEG, leading=13)
        )

    # Scale to fit (max_width × max_height) while preserving aspect ratio.
    max_w = min(blk.max_width, content_w)
    max_h = blk.max_height
    scale = min(max_w / iw, max_h / ih, 1.0)
    draw_w, draw_h = iw * scale, ih * scale

    img = Image(path, width=draw_w, height=draw_h)
    # Centre via a 1-cell table so the image isn't left-justified.
    cell_style = TableStyle([
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
        ('TOPPADDING',    (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
    ])
    if blk.caption:
        cap_style = ParagraphStyle(
            'img-cap', fontName='Helvetica', fontSize=9, leading=12,
            textColor=TEXT_MUTED, alignment=TA_CENTER,
        )
        t = Table([[img], [Paragraph(blk.caption, cap_style)]], colWidths=[content_w])
    else:
        t = Table([[img]], colWidths=[content_w])
    t.setStyle(cell_style)
    return t


def _kpi_strip(kpis, content_w):
    label_s = ParagraphStyle('kl', fontName='Helvetica-Bold', fontSize=7.5,
        leading=10, textColor=TEXT_MUTED, spaceAfter=2)
    val_s = ParagraphStyle('kv', fontName='Helvetica-Bold', fontSize=14,
        leading=16, textColor=TEXT_STRONG)
    val_neg = ParagraphStyle('kvn', parent=val_s, textColor=NEG)
    sub_s = ParagraphStyle('ks', fontName='Helvetica', fontSize=8,
        leading=10, textColor=TEXT_MUTED, spaceBefore=2)

    def cell(k):
        return [
            Paragraph(k.label.upper(), label_s),
            Paragraph(k.value, val_neg if k.negative else val_s),
            Paragraph(k.sub, sub_s) if k.sub else Spacer(1, 0),
        ]
    cells = [cell(k) for k in kpis]
    n = len(cells)
    if n == 0:
        return Spacer(1, 0)
    col_w = (content_w - (n - 1) * 3) / n
    t = Table([cells], colWidths=[col_w] * n, rowHeights=[58])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), BG_SURFACE),
        *[('BOX', (i, 0), (i, 0), 0.5, BORDER) for i in range(n)],
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('TOPPADDING',    (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    return t


def _data_table(spec, content_w):
    header_s   = ParagraphStyle('th', fontName='Helvetica-Bold', fontSize=8,
        leading=10, textColor=TEXT_MUTED)
    header_s_r = ParagraphStyle('thr', parent=header_s, alignment=TA_RIGHT)
    cell_s     = ParagraphStyle('td', fontName='Helvetica', fontSize=8.5,
        leading=11, textColor=TEXT, wordWrap='LTR')
    cell_s_r   = ParagraphStyle('tdr', parent=cell_s, alignment=TA_RIGHT)
    tot_s      = ParagraphStyle('tot', parent=cell_s, fontName='Helvetica-Bold',
        textColor=TEXT_STRONG)
    tot_s_r    = ParagraphStyle('totr', parent=tot_s, alignment=TA_RIGHT)

    def hdr(text, i):
        return Paragraph(f"<b>{text}</b>",
                         header_s_r if i in spec.num_cols else header_s)
    def body(text, i):
        if i in spec.sign_color_cols and isinstance(text, str):
            color_hex = '#c0392b' if text.startswith('-') else (
                        '#2e7d32' if text.startswith('+') else '#4d4f46')
            return Paragraph(
                f"<font color='{color_hex}'>{text}</font>",
                cell_s_r if i in spec.num_cols else cell_s,
            )
        return Paragraph(str(text) if text is not None else '',
                         cell_s_r if i in spec.num_cols else cell_s)
    def tot(text, i):
        return Paragraph(f"<b>{text}</b>",
                         tot_s_r if i in spec.num_cols else tot_s)

    data = [[hdr(h, i) for i, h in enumerate(spec.headers)]]
    data.extend([[body(c, i) for i, c in enumerate(row)] for row in spec.rows])
    if spec.totals_row:
        data.append([tot(c, i) for i, c in enumerate(spec.totals_row)])

    col_widths = spec.col_widths or [content_w / len(spec.headers)] * len(spec.headers)
    body_last = len(data) - (2 if spec.totals_row else 1)

    style = [
        ('BACKGROUND',    (0, 0), (-1, 0), BG_SURFACE_2),
        ('LINEBELOW',     (0, 0), (-1, 0), 0.5, BORDER),
        ('BACKGROUND',    (0, 1), (-1, body_last), BG_SURFACE),
        ('LEFTPADDING',   (0, 0), (-1, -1), 7),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 7),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('BOX',           (0, 0), (-1, -1), 0.5, BORDER),
        ('LINEBELOW',     (0, 1), (-1, body_last), 0.25, BORDER_SOFT),
    ]
    # Zebra rows
    for r in range(2, body_last + 1, 2):
        style.append(('BACKGROUND', (0, r), (-1, r),
                      colors.HexColor('#f7f7f1')))
    if spec.totals_row:
        style.extend([
            ('BACKGROUND',    (0, -1), (-1, -1), BG_SURFACE_2),
            ('LINEABOVE',     (0, -1), (-1, -1), 0.75, BORDER),
            ('TOPPADDING',    (0, -1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
        ])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style))
    return t


def _callout_card(c, content_w):
    label_s = ParagraphStyle('cl-l', fontName='Helvetica-Bold', fontSize=8,
        leading=10, textColor=TEXT_MUTED)
    val_s = ParagraphStyle('cl-v', fontName='Helvetica-Bold', fontSize=18,
        leading=20,
        textColor=NEG if c.negative else TEXT_STRONG,
        alignment=TA_RIGHT)
    value_html = c.value + (f"  <font size='10'>{c.suffix}</font>" if c.suffix else '')
    t = Table([[
        Paragraph(c.label.upper(), label_s),
        Paragraph(value_html, val_s),
    ]], colWidths=[content_w * 0.5, content_w * 0.5])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), BG_SURFACE),
        ('LINEBEFORE',    (0, 0), (0, 0),  3, ACCENT),
        ('BOX',           (0, 0), (-1, -1), 0.5, BORDER),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
        ('TOPPADDING',    (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t
