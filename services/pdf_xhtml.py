"""HTML/CSS → PDF via xhtml2pdf.

For report designs ported from real HTML/CSS templates (table-based markup,
inline CSS — xhtml2pdf's renderer doesn't handle modern flex/grid), rather
than built with the reportlab flowable API in pdf_helper.py. Render a Jinja2
template to an HTML string, then call html_to_pdf(buffer, html).
"""
from __future__ import annotations
from typing import IO

from xhtml2pdf import pisa


def html_to_pdf(buffer: IO[bytes], html: str) -> None:
    result = pisa.CreatePDF(src=html, dest=buffer)
    if result.err:
        raise RuntimeError(f"xhtml2pdf failed with {result.err} error(s)")
