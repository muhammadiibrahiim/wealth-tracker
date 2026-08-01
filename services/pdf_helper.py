"""Themeable PDF report builder.

Build a ReportSpec, call render_report_pdf(buf, spec[, theme='classic']). Done.

Sections you can stack inside spec.sections:
    SectionTitle("Bill To")        →  bold sub-heading
    ParagraphBlock("<b>…</b>")     →  paragraph with reportlab mini-HTML
    TableSpec(headers, rows, …)    →  zebra-striped table w/ optional totals row
    CalloutCard(label, value, …)   →  big right-aligned number, orange left rail
    PageBreak()                    →  force a page break

Themes: every visual constant (background, accent, header style) lives in a
Theme, looked up from THEMES by name. 'classic' is the original look — every
existing call site that doesn't pass `theme=` keeps rendering exactly as
before. New themes can be added to THEMES without touching a single call
site; flipping DEFAULT_THEME re-skins every report/invoice in the app at once.

Layouts: `theme` controls colour; `layout` controls the actual document
skeleton (header structure, where KPIs sit, how the total is presented).
'report' is the original skeleton (boxed KPI row, centred callout box) — the
default, untouched at every existing call site. 'invoice' / 'sidebar' / 'memo'
are structurally different documents, not recolours of the same one.
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
    Paragraph, Spacer, PageBreak, Image, HRFlowable,
)
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

# Universal — green/red mean the same thing regardless of theme.
POS = colors.HexColor('#2e7d32')
NEG = colors.HexColor('#c0392b')


@dataclass
class Theme:
    key: str
    label: str
    bg_page: colors.Color
    bg_surface: colors.Color
    bg_surface_2: colors.Color
    border: colors.Color
    border_soft: colors.Color
    text: colors.Color
    text_strong: colors.Color
    text_muted: colors.Color
    accent: colors.Color
    accent_text: colors.Color         # text/rule colour used ON the accent (header band mode)
    zebra: colors.Color
    header_mode: str = 'classic'      # 'classic' (stripe+soft band) | 'plain' (hairline) | 'band' (solid colour block)
    header_divider: Optional[colors.Color] = None   # separator in the header row; None → border_soft


def _c(hexstr: str) -> colors.Color:
    return colors.HexColor(hexstr)


THEMES = {
    # Original look — preserved so any report can always be regenerated
    # exactly as it always has been. Never remove entries from this dict.
    'classic': Theme(
        key='classic', label='Classic (parchment & orange)',
        bg_page=_c('#fdfdf8'), bg_surface=_c('#ffffff'), bg_surface_2=_c('#eeefe9'),
        border=_c('#bfc1b7'), border_soft=_c('#dadbd0'),
        text=_c('#4d4f46'), text_strong=_c('#23251d'), text_muted=_c('#65675e'),
        accent=_c('#F54E00'), accent_text=_c('#ffffff'),
        zebra=_c('#f7f7f1'), header_mode='classic',
    ),
    # Candidate 1 — clean, white, indigo accent (matches the app's own UI).
    'white-indigo': Theme(
        key='white-indigo', label='Clean Indigo',
        bg_page=_c('#ffffff'), bg_surface=_c('#ffffff'), bg_surface_2=_c('#eef2ff'),
        border=_c('#e2e4ea'), border_soft=_c('#e5e7eb'),
        text=_c('#374151'), text_strong=_c('#111827'), text_muted=_c('#6b7280'),
        accent=_c('#4f46e5'), accent_text=_c('#ffffff'),
        zebra=_c('#fafafa'), header_mode='plain',
    ),
    # Candidate 2 — austere black-and-white ledger/statement feel.
    'white-mono': Theme(
        key='white-mono', label='Monochrome Ledger',
        bg_page=_c('#ffffff'), bg_surface=_c('#ffffff'), bg_surface_2=_c('#f3f4f6'),
        border=_c('#d1d5db'), border_soft=_c('#e5e7eb'),
        text=_c('#1f2937'), text_strong=_c('#000000'), text_muted=_c('#6b7280'),
        accent=_c('#111827'), accent_text=_c('#ffffff'),
        zebra=_c('#f9fafb'), header_mode='plain',
    ),
    # Candidate 3 — bold solid header band, white body (letterhead feel).
    'white-band': Theme(
        key='white-band', label='Bold Band',
        bg_page=_c('#ffffff'), bg_surface=_c('#ffffff'), bg_surface_2=_c('#f8fafc'),
        border=_c('#e2e8f0'), border_soft=_c('#eef1f5'),
        text=_c('#334155'), text_strong=_c('#0f172a'), text_muted=_c('#64748b'),
        accent=_c('#1e293b'), accent_text=_c('#ffffff'),
        zebra=_c('#f8fafc'), header_mode='band', header_divider=_c('#475569'),
    ),
}
DEFAULT_THEME = 'classic'

# Document skeletons — structurally different, not just recoloured.
LAYOUTS = {
    'report':  'Classic Report (current)',
    'invoice': 'Invoice-Style Letterhead',
    'sidebar': 'Sidebar Statement',
    'memo':    'Minimal Memo',
}
DEFAULT_LAYOUT = 'report'


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


# Per-layout story composition — how KPIs and the closing total are rendered,
# and whether the title is drawn as chrome (repeats per page) instead of flow.
_LAYOUT_STORY_CFG = {
    'report':  dict(skip_title=False, skip_kpis=False, kpi_style='boxed',  callout_style='boxed', section_underline=False),
    'invoice': dict(skip_title=True,  skip_kpis=False, kpi_style='inline', callout_style='right',  section_underline=False),
    'sidebar': dict(skip_title=False, skip_kpis=True,  kpi_style='boxed',  callout_style='boxed',  section_underline=False),
    'memo':    dict(skip_title=False, skip_kpis=False, kpi_style='text',   callout_style='text',   section_underline=True),
}


def render_report_pdf(
    buffer: IO[bytes], spec: ReportSpec,
    theme: Union[str, Theme] = DEFAULT_THEME, layout: str = DEFAULT_LAYOUT,
) -> None:
    th = theme if isinstance(theme, Theme) else THEMES.get(theme, THEMES[DEFAULT_THEME])
    lay = layout if layout in LAYOUTS else DEFAULT_LAYOUT
    page_w, page_h = A4
    L = R = 14 * mm
    B = 18 * mm
    if lay == 'invoice':
        T = 34 * mm                    # taller header — brand line + big title line
    elif lay == 'memo':
        L = R = 18 * mm                # airier margins for a letter/memo feel
        T = 22 * mm
    elif lay == 'sidebar':
        T = 20 * mm
    else:
        T = 22 * mm

    SIDEBAR_W = 52 * mm
    SIDEBAR_GUTTER = 10 * mm
    main_L = (L + SIDEBAR_W + SIDEBAR_GUTTER) if lay == 'sidebar' else L
    content_w = page_w - main_L - R

    def page_chrome(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(th.bg_page)
        canvas.rect(0, 0, page_w, page_h, fill=1, stroke=0)

        if lay == 'sidebar':
            # Persistent left data rail — brand + every KPI, redrawn each page,
            # so the reader never scrolls away from the headline numbers.
            canvas.setFillColor(th.bg_surface_2)
            canvas.rect(0, 0, SIDEBAR_W, page_h, fill=1, stroke=0)
            canvas.setFillColor(th.accent)
            canvas.rect(0, page_h - 3, page_w, 3, fill=1, stroke=0)
            sx = 10 * mm
            sy = page_h - 22
            canvas.setFillColor(th.text_strong)
            canvas.setFont('Helvetica-Bold', 11)
            canvas.drawString(sx, sy, spec.brand)
            sy -= 16
            canvas.setStrokeColor(th.border_soft)
            canvas.setLineWidth(0.5)
            canvas.line(sx, sy, SIDEBAR_W - 10 * mm, sy)
            sy -= 20
            for k in spec.kpis:
                canvas.setFillColor(th.text_muted)
                canvas.setFont('Helvetica-Bold', 7)
                canvas.drawString(sx, sy, k.label.upper())
                sy -= 13
                canvas.setFillColor(NEG if k.negative else th.text_strong)
                canvas.setFont('Helvetica-Bold', 13)
                canvas.drawString(sx, sy, k.value)
                sy -= 12
                if k.sub:
                    canvas.setFillColor(th.text_muted)
                    canvas.setFont('Helvetica', 7)
                    canvas.drawString(sx, sy, k.sub[:34])
                    sy -= 10
                sy -= 12
            canvas.setFillColor(th.text_muted)
            canvas.setFont('Helvetica', 8)
            stamp = f"{spec.generated_label} {datetime.now().strftime('%b %d, %Y · %H:%M')}"
            canvas.drawRightString(page_w - R, page_h - 16, stamp)
            canvas.setStrokeColor(th.border_soft)
            canvas.setLineWidth(0.5)
            canvas.line(main_L, page_h - T + 4, page_w - R, page_h - T + 4)

        elif lay == 'invoice':
            # Big dominant title on its own line — a letterhead, not a report banner.
            canvas.setFillColor(th.accent)
            canvas.rect(0, page_h - 2, page_w, 2, fill=1, stroke=0)
            canvas.setFillColor(th.text_muted)
            canvas.setFont('Helvetica-Bold', 9)
            canvas.drawString(L, page_h - 14, spec.brand)
            stamp = f"{spec.generated_label} {datetime.now().strftime('%b %d, %Y · %H:%M')}"
            canvas.drawRightString(page_w - R, page_h - 14, stamp)
            canvas.setFillColor(th.text_strong)
            canvas.setFont('Helvetica-Bold', 20)
            canvas.drawString(L, page_h - 34, spec.title)
            canvas.setStrokeColor(th.border_soft)
            canvas.setLineWidth(0.75)
            canvas.line(L, page_h - T + 6, page_w - R, page_h - T + 6)

        else:  # 'report' (classic/plain/band per theme) and 'memo' (always plain)
            if lay == 'report' and th.header_mode == 'classic':
                canvas.setFillColor(th.accent)
                canvas.rect(0, page_h - 4, page_w, 4, fill=1, stroke=0)
                canvas.setFillColor(th.bg_surface_2)
                canvas.rect(0, page_h - T + 2, page_w, T - 6, fill=1, stroke=0)
            elif lay == 'report' and th.header_mode == 'band':
                canvas.setFillColor(th.accent)
                canvas.rect(0, page_h - T, page_w, T, fill=1, stroke=0)
            else:
                canvas.setFillColor(th.accent)
                canvas.rect(0, page_h - 2, page_w, 2, fill=1, stroke=0)

            band = lay == 'report' and th.header_mode == 'band'
            brand_color = th.accent_text if band else th.text_strong
            title_color = stamp_color = th.accent_text if band else th.text_muted
            divider = th.accent_text if band else (th.header_divider or th.border_soft)

            canvas.setFillColor(brand_color)
            canvas.setFont('Helvetica-Bold', 11)
            canvas.drawString(L, page_h - 14, spec.brand)
            brand_w = canvas.stringWidth(spec.brand, 'Helvetica-Bold', 11)
            canvas.setFillColor(title_color)
            canvas.setFont('Helvetica', 8.5)
            sep_x = L + brand_w + 10
            canvas.setStrokeColor(divider)
            canvas.setLineWidth(0.5)
            canvas.line(sep_x, page_h - 20, sep_x, page_h - 9)
            canvas.drawString(sep_x + 10, page_h - 14, spec.title)
            stamp = f"{spec.generated_label} {datetime.now().strftime('%b %d, %Y · %H:%M')}"
            canvas.setFillColor(stamp_color)
            canvas.drawRightString(page_w - R, page_h - 14, stamp)

            if lay == 'memo' or (lay == 'report' and th.header_mode == 'plain'):
                canvas.setStrokeColor(th.border_soft)
                canvas.setLineWidth(0.5)
                canvas.line(L, page_h - T + 2, page_w - R, page_h - T + 2)

        # Footer rule (full page width — including under the sidebar, if any)
        foot_x0 = 0 if lay == 'sidebar' else L
        canvas.setStrokeColor(th.border_soft)
        canvas.setLineWidth(0.5)
        canvas.line(foot_x0, B - 4, page_w - R, B - 4)
        canvas.setFillColor(th.text_muted)
        canvas.setFont('Helvetica', 8.5)
        canvas.drawRightString(page_w - R, B - 12, f"Page {doc.page}")
        if spec.footer_subtitle:
            canvas.drawString(main_L, B - 12, spec.footer_subtitle)
        canvas.restoreState()

    doc = BaseDocTemplate(
        buffer, pagesize=A4,
        leftMargin=main_L, rightMargin=R, topMargin=T, bottomMargin=B,
        title=spec.title, author=spec.brand,
    )
    frame = Frame(main_L, B, content_w, page_h - T - B,
                  id='content', showBoundary=0)
    doc.addPageTemplates([
        PageTemplate(id='main', frames=[frame], onPage=page_chrome),
    ])
    cfg = _LAYOUT_STORY_CFG[lay]
    doc.build(_build_story(spec, content_w=content_w, theme=th, **cfg))


def _build_story(
    spec: ReportSpec, *, content_w, theme: Theme,
    skip_title: bool = False, skip_kpis: bool = False,
    kpi_style: str = 'boxed', callout_style: str = 'boxed',
    section_underline: bool = False,
):
    th = theme
    title_style = ParagraphStyle(
        'Title', fontName='Helvetica-Bold', fontSize=22, leading=26,
        textColor=th.text_strong, spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        'Subtitle', fontName='Helvetica', fontSize=10, leading=14,
        textColor=th.text_muted, spaceAfter=10,
    )
    section_style = ParagraphStyle(
        'Section', fontName='Helvetica-Bold', fontSize=11, leading=13,
        textColor=th.text_strong, spaceBefore=10, spaceAfter=6,
    )
    section_style_keep = ParagraphStyle(
        'SectionKeep', parent=section_style, keepWithNext=1,
    )
    body_style = ParagraphStyle(
        'Body', fontName='Helvetica', fontSize=9.5, leading=13,
        textColor=th.text, spaceAfter=8,
    )

    story = []
    if not skip_title:
        story.append(Paragraph(spec.title, title_style))
    if spec.subtitle_parts:
        story.append(Paragraph(
            ' &nbsp;·&nbsp; '.join(spec.subtitle_parts), subtitle_style,
        ))
    if spec.kpis and not skip_kpis:
        if kpi_style == 'inline':
            story.append(_kpi_strip_inline(spec.kpis, content_w, th))
        elif kpi_style == 'text':
            story.append(_kpi_text(spec.kpis, th))
        else:
            story.append(_kpi_strip(spec.kpis, content_w, th))
        story.append(Spacer(1, 10))

    for entry in spec.sections:
        if isinstance(entry, SectionTitle):
            story.append(Paragraph(
                f"<b>{entry.text}</b>" if entry.bold else entry.text,
                section_style_keep if entry.keep_with_next else section_style,
            ))
            if section_underline:
                story.append(HRFlowable(width='100%', thickness=0.5,
                                        color=th.border_soft, spaceBefore=0, spaceAfter=6))
        elif isinstance(entry, ParagraphBlock):
            story.append(Paragraph(entry.html, body_style))
        elif isinstance(entry, TableSpec):
            story.append(_data_table(entry, content_w, th))
            story.append(Spacer(1, 8))
        elif isinstance(entry, CalloutCard):
            if callout_style == 'right':
                story.append(_callout_right(entry, content_w, th))
            elif callout_style == 'text':
                story.append(_callout_text(entry, th))
            else:
                story.append(_callout_card(entry, content_w, th))
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
            textColor=colors.HexColor('#65675e'), alignment=TA_CENTER,
        )
        t = Table([[img], [Paragraph(blk.caption, cap_style)]], colWidths=[content_w])
    else:
        t = Table([[img]], colWidths=[content_w])
    t.setStyle(cell_style)
    return t


def _kpi_strip(kpis, content_w, theme: Theme):
    th = theme
    label_s = ParagraphStyle('kl', fontName='Helvetica-Bold', fontSize=7.5,
        leading=10, textColor=th.text_muted, spaceAfter=2)
    val_s = ParagraphStyle('kv', fontName='Helvetica-Bold', fontSize=14,
        leading=16, textColor=th.text_strong)
    val_neg = ParagraphStyle('kvn', parent=val_s, textColor=NEG)
    sub_s = ParagraphStyle('ks', fontName='Helvetica', fontSize=8,
        leading=10, textColor=th.text_muted, spaceBefore=2)

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
        ('BACKGROUND', (0, 0), (-1, -1), th.bg_surface),
        *[('BOX', (i, 0), (i, 0), 0.5, th.border) for i in range(n)],
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('TOPPADDING',    (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
    ]))
    return t


def _kpi_strip_inline(kpis, content_w, theme: Theme):
    """Slim single-row 'invoice meta' strip — label above value, no boxes,
    just a rule underneath the whole row."""
    th = theme
    label_s = ParagraphStyle('kil', fontName='Helvetica-Bold', fontSize=7.5,
        leading=9, textColor=th.text_muted)
    val_s = ParagraphStyle('kiv', fontName='Helvetica-Bold', fontSize=12.5,
        leading=15, textColor=th.text_strong, spaceBefore=1)
    val_neg = ParagraphStyle('kivn', parent=val_s, textColor=NEG)

    def cell(k):
        return [Paragraph(k.label.upper(), label_s), Paragraph(k.value, val_neg if k.negative else val_s)]
    cells = [cell(k) for k in kpis]
    n = len(cells)
    if n == 0:
        return Spacer(1, 0)
    col_w = content_w / n
    t = Table([cells], colWidths=[col_w] * n)
    t.setStyle(TableStyle([
        ('LINEBELOW',     (0, 0), (-1, -1), 0.75, th.accent),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 12),
        ('TOPPADDING',    (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN',        (0, 0), (-1, -1), 'BOTTOM'),
    ]))
    return t


def _kpi_text(kpis, theme: Theme):
    """Most minimal form — one inline sentence, no table/box at all."""
    style = ParagraphStyle('kt', fontName='Helvetica', fontSize=10, leading=15,
        textColor=theme.text, spaceAfter=10)
    parts = []
    for k in kpis:
        if k.negative:
            parts.append(f"<b>{k.label}:</b> <font color='#c0392b'>{k.value}</font>")
        else:
            parts.append(f"<b>{k.label}:</b> {k.value}")
    return Paragraph(' &nbsp;&nbsp;·&nbsp;&nbsp; '.join(parts), style)


def _callout_right(c, content_w, theme: Theme):
    """Invoice-style total — right-aligned, big, a rule above instead of a box."""
    th = theme
    label_s = ParagraphStyle('cr-l', fontName='Helvetica-Bold', fontSize=8,
        leading=10, textColor=th.text_muted, alignment=TA_RIGHT, spaceAfter=3)
    val_s = ParagraphStyle('cr-v', fontName='Helvetica-Bold', fontSize=20, leading=22,
        textColor=NEG if c.negative else th.text_strong, alignment=TA_RIGHT)
    value_html = c.value + (f"  <font size='11'>{c.suffix}</font>" if c.suffix else '')
    t = Table([
        [Paragraph(c.label.upper(), label_s)],
        [Paragraph(value_html, val_s)],
    ], colWidths=[content_w])
    t.setStyle(TableStyle([
        ('LINEABOVE',     (0, 0), (-1, 0), 1, th.accent),
        ('TOPPADDING',    (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 0),
    ]))
    return t


def _callout_text(c, theme: Theme):
    """Memo-style total — a single bold right-aligned line, nothing else."""
    th = theme
    style = ParagraphStyle('ctx', fontName='Helvetica-Bold', fontSize=13, leading=17,
        textColor=NEG if c.negative else th.text_strong, alignment=TA_RIGHT, spaceBefore=6)
    value_html = f"{c.label.upper()} — {c.value}" + (f" <font size='10'>{c.suffix}</font>" if c.suffix else '')
    return Paragraph(value_html, style)


def _data_table(spec, content_w, theme: Theme):
    th = theme
    header_s   = ParagraphStyle('th', fontName='Helvetica-Bold', fontSize=8,
        leading=10, textColor=th.text_muted)
    header_s_r = ParagraphStyle('thr', parent=header_s, alignment=TA_RIGHT)
    cell_s     = ParagraphStyle('td', fontName='Helvetica', fontSize=8.5,
        leading=11, textColor=th.text, wordWrap='LTR')
    cell_s_r   = ParagraphStyle('tdr', parent=cell_s, alignment=TA_RIGHT)
    tot_s      = ParagraphStyle('tot', parent=cell_s, fontName='Helvetica-Bold',
        textColor=th.text_strong)
    tot_s_r    = ParagraphStyle('totr', parent=tot_s, alignment=TA_RIGHT)

    def hdr(text, i):
        return Paragraph(f"<b>{text}</b>",
                         header_s_r if i in spec.num_cols else header_s)
    def body(text, i):
        if i in spec.sign_color_cols and isinstance(text, str):
            color_hex = '#c0392b' if text.startswith('-') else (
                        '#2e7d32' if text.startswith('+') else None)
            if color_hex:
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
    # Callers pass fixed point widths sized for the default (widest) content
    # column; a narrower layout (e.g. 'sidebar') must scale them down to fit
    # rather than let the table overflow the frame and clip.
    total_w = sum(col_widths)
    if total_w > content_w:
        scale = content_w / total_w
        col_widths = [w * scale for w in col_widths]
    body_last = len(data) - (2 if spec.totals_row else 1)

    style = [
        ('BACKGROUND',    (0, 0), (-1, 0), th.bg_surface_2),
        ('LINEBELOW',     (0, 0), (-1, 0), 0.5, th.border),
        ('BACKGROUND',    (0, 1), (-1, body_last), th.bg_surface),
        ('LEFTPADDING',   (0, 0), (-1, -1), 7),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 7),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('BOX',           (0, 0), (-1, -1), 0.5, th.border),
        ('LINEBELOW',     (0, 1), (-1, body_last), 0.25, th.border_soft),
    ]
    # Zebra rows
    for r in range(2, body_last + 1, 2):
        style.append(('BACKGROUND', (0, r), (-1, r), th.zebra))
    if spec.totals_row:
        style.extend([
            ('BACKGROUND',    (0, -1), (-1, -1), th.bg_surface_2),
            ('LINEABOVE',     (0, -1), (-1, -1), 0.75, th.border),
            ('TOPPADDING',    (0, -1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
        ])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style))
    return t


def _callout_card(c, content_w, theme: Theme):
    th = theme
    label_s = ParagraphStyle('cl-l', fontName='Helvetica-Bold', fontSize=8,
        leading=10, textColor=th.text_muted)
    val_s = ParagraphStyle('cl-v', fontName='Helvetica-Bold', fontSize=18,
        leading=20,
        textColor=NEG if c.negative else th.text_strong,
        alignment=TA_RIGHT)
    value_html = c.value + (f"  <font size='10'>{c.suffix}</font>" if c.suffix else '')
    t = Table([[
        Paragraph(c.label.upper(), label_s),
        Paragraph(value_html, val_s),
    ]], colWidths=[content_w * 0.5, content_w * 0.5])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), th.bg_surface),
        ('LINEBEFORE',    (0, 0), (0, 0),  3, th.accent),
        ('BOX',           (0, 0), (-1, -1), 0.5, th.border),
        ('LEFTPADDING',   (0, 0), (-1, -1), 14),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 14),
        ('TOPPADDING',    (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t
