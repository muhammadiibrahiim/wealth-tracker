"""Trade-derived document PDFs — shared context builder.

Every customer/vendor-facing document for a trade (Order Confirmation,
Delivery Note, Packing Slip, Vendor PO, Payment Receipt) is generated
on-demand from the live Trade data. No persistence — every doc is a
computed view, which means existing trades automatically inherit access
to every document type with no backfill needed.

Reference numbers derive from the trade ref:  e.g. OC-TRD-0001, DN-TRD-0001.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Optional

from models import Party, Trade, TradeLine, TradePayment
from services.pdf_helper import (
    render_report_pdf, ReportSpec, KpiSpec, TableSpec,
    SectionTitle, ParagraphBlock, CalloutCard,
)


COMPANY = {
    "name":    "Ibrahim Traders",
    "brand":   "IBRAHIM TRADERS",
    "address": None,
    "phone":   None,
    "email":   None,
}


# kind             (ref prefix, title,                          footer subtitle,                           generated label)
KINDS = {
    "vendor_po":        ("PO",  "Purchase Order",                 "Ibrahim Traders · purchase order",         "Issued"),
    "order_confirm":    ("OC",  "Order Confirmation",             "Ibrahim Traders · order confirmation",     "Issued"),
    "delivery_note":    ("DN",  "Delivery Note",                  "Ibrahim Traders · delivery note",          "Delivered"),
    "packing_slip":     ("PS",  "Packing Slip",                   "Ibrahim Traders · packing slip",           "Packed"),
    "delivery_pack":    ("DNP", "Delivery Note & Packing Slip",   "Ibrahim Traders · delivery + packing",     "Delivered"),
    "delivery_invoice": ("INV", "Invoice",                        "Ibrahim Traders · invoice",                "Issued"),
    "payment_receipt":  ("REC", "Payment Receipt",                "Ibrahim Traders · payment receipt",        "Issued"),
}

# Default tolerance phrasing for Order Confirmations — the trade's quoted qty
# may shift by ±10-15% based on what the vendor actually packs.
ORDER_QTY_TOLERANCE_NOTE = (
    "Quantities shown are <b>as ordered</b>. Actual delivered quantities may vary "
    "by <b>±10–15%</b> based on vendor packing — final invoice will be raised against "
    "the delivered quantity."
)


def _pkr(v) -> str:
    try:
        return f"Rs. {Decimal(str(v)):,.2f}"
    except Exception:
        return f"Rs. {v}"


def _qty_str(line: TradeLine) -> str:
    return f"{float(line.quantity):g} {line.unit}"


def _bill_to_html(party: Party) -> str:
    lines = [f"<b>{party.name}</b>"]
    if party.address: lines.append(party.address)
    if party.phone:   lines.append(f"Phone: {party.phone}")
    if party.email:   lines.append(f"Email: {party.email}")
    return "<br/>".join(lines)


def _ref_for(kind: str, trade: Trade, suffix: str = "") -> str:
    prefix, *_ = KINDS[kind]
    base = f"{prefix}-{trade.reference}"
    return f"{base}-{suffix}" if suffix else base


def _due_date_for(ctx) -> Optional[date]:
    """Per-receipt invoice due date = delivery event date + customer_terms_days.

    Falls back to the trade-level `customer_due_date` if no event_date is set
    (e.g. a full-trade-level use of the helper). Returns None when neither side
    has enough info to compute one.
    """
    if ctx.event_date and ctx.trade.customer_terms_days is not None:
        from datetime import timedelta
        return ctx.event_date + timedelta(days=int(ctx.trade.customer_terms_days))
    return getattr(ctx.trade, "customer_due_date", None)


@dataclass
class DocContext:
    """Knobs each caller (route handler) can pass to vary the doc."""
    kind: str
    trade: Trade
    vendor: Party
    purchaser: Party
    payment: Optional[TradePayment] = None
    extra_sections: Optional[list] = None
    header_kpis: Optional[list] = None
    # For per-receipt-event docs (DN+PS per partial delivery): override the qty
    # used per trade line. Map line_id → Decimal qty. Lines not in the map are
    # omitted from the table.
    line_qty_override: Optional[dict] = None
    # Optional label that appears below the title for per-receipt docs ("for
    # delivery on YYYY-MM-DD") — used by per-receipt-event routes.
    event_label: Optional[str] = None
    # Optional actual date the event happened on (used to compute the per-receipt
    # invoice's payment-due date = event_date + customer_terms_days).
    event_date: Optional[date] = None


def build_doc_pdf(ctx: DocContext) -> bytes:
    kind = ctx.kind
    if kind not in KINDS:
        raise ValueError(f"Unknown doc kind: {kind}")
    _prefix, title, footer_subtitle, generated_label = KINDS[kind]
    ref = _ref_for(
        kind, ctx.trade,
        str(ctx.payment.id) if (kind == "payment_receipt" and ctx.payment) else "",
    )

    if kind == "vendor_po":
        to_party, to_label = ctx.vendor, "PO Issued To"
    elif kind == "payment_receipt":
        to_party, to_label = ctx.purchaser, "Received From"
    else:
        to_party, to_label = ctx.purchaser, "Recipient"

    kpis = ctx.header_kpis or _default_kpis(ctx)

    sections: list = [
        SectionTitle(to_label),
        ParagraphBlock(_bill_to_html(to_party)),
    ]
    if ctx.event_label:
        sections.append(ParagraphBlock(f"<font color='#65675e'><b>For delivery on:</b> {ctx.event_label}</font>"))

    if kind == "delivery_pack":
        # Two compact tables back-to-back: priced delivery + warehouse packing.
        sections.append(SectionTitle("Items Delivered"))
        sections.append(_lines_table(_with_kind(ctx, "delivery_note")))
        sections.append(SectionTitle("Packing Checklist"))
        sections.append(_lines_table(_with_kind(ctx, "packing_slip")))
    elif kind != "payment_receipt":
        sections.append(SectionTitle("Items"))
        sections.append(_lines_table(ctx))

    if kind == "payment_receipt" and ctx.payment:
        sections.append(SectionTitle("Payment Details"))
        sections.append(ParagraphBlock(_payment_paragraph(ctx)))
        sections.append(CalloutCard(
            label="Amount Received",
            value=_pkr(ctx.payment.amount),
            suffix=f"Method: {ctx.payment.method or 'cash'}",
        ))
    elif kind == "vendor_po":
        sections.append(CalloutCard(
            label="Total Order Value",
            value=_pkr(ctx.trade.total_cost),
            suffix=f"Payment terms: {ctx.trade.vendor_terms_days} days",
        ))
    elif kind == "order_confirm":
        sections.append(CalloutCard(
            label="Total",
            value=_pkr(ctx.trade.total_sale),
            suffix=f"Payment terms: {ctx.trade.customer_terms_days} days",
        ))
    elif kind == "delivery_note":
        sections.append(CalloutCard(
            label="Total Value",
            value=_pkr(ctx.trade.total_sale),
            suffix=(f"Delivered on {ctx.trade.delivered_at.strftime('%b %d, %Y')}"
                    if ctx.trade.delivered_at else "Delivery in progress"),
        ))
    elif kind == "delivery_pack":
        sections.append(CalloutCard(
            label="Total Value",
            value=_pkr(_subtotal_for(ctx)),
            suffix=(ctx.event_label or
                    (f"Delivered on {ctx.trade.delivered_at.strftime('%b %d, %Y')}"
                     if ctx.trade.delivered_at else "Delivery in progress")),
        ))
    elif kind == "delivery_invoice":
        _due = _due_date_for(ctx)
        suffix_parts = []
        if ctx.event_label:
            suffix_parts.append(f"For delivery on {ctx.event_label}")
        if _due:
            suffix_parts.append(f"Due by {_due.strftime('%b %d, %Y')}")
        if ctx.trade.customer_terms_days:
            suffix_parts.append(f"{ctx.trade.customer_terms_days}-day terms")
        sections.append(CalloutCard(
            label="Amount Due",
            value=_pkr(_subtotal_for(ctx)),
            suffix=" · ".join(suffix_parts),
            negative=True,
        ))
    # packing_slip intentionally has no money callout.

    if ctx.extra_sections:
        sections.extend(ctx.extra_sections)

    sections += _closing_for(kind, ctx)

    buf = BytesIO()
    render_report_pdf(buf, ReportSpec(
        title=title,
        subtitle_parts=[
            f"{title} {ref}",
            f"Issued {date.today().strftime('%B %d, %Y')}",
            f"Trade {ctx.trade.reference}",
        ],
        kpis=kpis,
        sections=sections,
        footer_subtitle=footer_subtitle,
        generated_label=generated_label,
        brand=COMPANY["brand"],
    ))
    return buf.getvalue()


def _default_kpis(ctx: DocContext) -> list:
    kind = ctx.kind
    t = ctx.trade
    if kind == "payment_receipt" and ctx.payment:
        return [
            KpiSpec("Amount", _pkr(ctx.payment.amount)),
            KpiSpec("Method", (ctx.payment.method or "cash").title()),
            KpiSpec("Date",   ctx.payment.paid_on.strftime("%b %d, %Y")),
            KpiSpec("Trade",  t.reference),
        ]
    kpis = [
        KpiSpec("Trade", t.reference),
        KpiSpec("Items", str(len(t.lines))),
    ]
    if kind == "vendor_po":
        kpis.append(KpiSpec("Order Value", _pkr(t.total_cost)))
        kpis.append(KpiSpec("Pay Terms",   f"{t.vendor_terms_days} days"))
    elif kind == "order_confirm":
        kpis.append(KpiSpec("Total",     _pkr(t.total_sale)))
        kpis.append(KpiSpec("Pay Terms", f"{t.customer_terms_days} days"))
    elif kind == "delivery_note":
        kpis.append(KpiSpec("Total",     _pkr(t.total_sale)))
        kpis.append(KpiSpec("Delivered",
            t.delivered_at.strftime("%b %d, %Y") if t.delivered_at else "Pending"))
    elif kind == "packing_slip":
        kpis.append(KpiSpec("Total Qty",
            f"{float(sum(Decimal(l.quantity) for l in t.lines)):g}"))
        kpis.append(KpiSpec("Packed On", date.today().strftime("%b %d, %Y")))
    elif kind == "delivery_pack":
        # When line_qty_override is set (per-receipt event), totals reflect the event;
        # otherwise reflect the trade's full delivered qty.
        kpis.append(KpiSpec("Total", _pkr(_subtotal_for(ctx))))
        kpis.append(KpiSpec("Delivered",
            ctx.event_label or
            (t.delivered_at.strftime("%b %d, %Y") if t.delivered_at else "Pending")))
    elif kind == "delivery_invoice":
        kpis.append(KpiSpec("Amount", _pkr(_subtotal_for(ctx))))
        kpis.append(KpiSpec("Delivered",
            ctx.event_label or
            (t.delivered_at.strftime("%b %d, %Y") if t.delivered_at else "Pending")))
        _due = _due_date_for(ctx)
        kpis.append(KpiSpec(
            "Due Date",
            _due.strftime("%b %d, %Y") if _due else "—",
            sub=(f"{t.customer_terms_days}-day terms" if t.customer_terms_days else ""),
        ))
    return kpis


def _with_kind(ctx: DocContext, new_kind: str) -> DocContext:
    """Return a shallow copy of `ctx` with `kind` swapped — used by delivery_pack."""
    from dataclasses import replace
    return replace(ctx, kind=new_kind)


def _qty_for(ctx: DocContext, line) -> Decimal:
    """Resolve the quantity to display on this line for this doc kind.

    - Order Confirmation → `ordered_quantity` (what the customer signed off on).
    - Per-receipt-event docs (line_qty_override present) → the overridden qty.
    - Everything else → `quantity` (the final delivered qty).
    """
    if ctx.line_qty_override is not None:
        return Decimal(ctx.line_qty_override.get(line.id, 0))
    if ctx.kind == "order_confirm":
        return Decimal(line.ordered_quantity)
    return Decimal(line.quantity)


def _qty_str(line: "TradeLine", qty: Optional[Decimal] = None) -> str:
    use = qty if qty is not None else Decimal(line.quantity)
    return f"{float(use):g} {line.unit}"


def _subtotal_for(ctx: DocContext) -> Decimal:
    """Sum of line value at the appropriate rate, respecting qty overrides."""
    rate_attr = "unit_cost" if ctx.kind == "vendor_po" else "unit_price"
    total = Decimal("0")
    for ln in ctx.trade.lines:
        q = _qty_for(ctx, ln)
        if q == 0:
            continue
        total += q * Decimal(getattr(ln, rate_attr))
    return total.quantize(Decimal("0.01"))


def _lines_table(ctx: DocContext) -> TableSpec:
    rows = []
    for ln in ctx.trade.lines:
        qty = _qty_for(ctx, ln)
        if qty == 0:
            continue
        bullets = [f"{s.label}: {s.value}" for s in (ln.specs or [])]
        if ln.line_notes:
            bullets.append(ln.line_notes)
        name_html = f"<b>{ln.item_name}</b>"
        if bullets:
            name_html += "<br/>" + "<br/>".join(
                f"<font color='#65675e' size='8'>• {b}</font>" for b in bullets
            )
        qty_text = _qty_str(ln, qty)
        if ctx.kind == "packing_slip":
            rows.append([name_html, qty_text, "☐"])
        elif ctx.kind == "vendor_po":
            line_amt = (qty * Decimal(ln.unit_cost)).quantize(Decimal("0.01"))
            rows.append([name_html, qty_text, _pkr(ln.unit_cost), _pkr(line_amt)])
        else:
            line_amt = (qty * Decimal(ln.unit_price)).quantize(Decimal("0.01"))
            rows.append([name_html, qty_text, _pkr(ln.unit_price), _pkr(line_amt)])

    if ctx.kind == "packing_slip":
        return TableSpec(
            headers=["Description", "Qty", "Packed"],
            rows=rows, col_widths=[360, 120, 70],
            num_cols={1, 2},
        )
    subtotal = _subtotal_for(ctx)
    return TableSpec(
        headers=["Description", "Qty", "Rate", "Amount"],
        rows=rows,
        col_widths=[300, 60, 90, 100],
        num_cols={1, 2, 3},
        totals_row=["", "", "Total", _pkr(subtotal)],
    )


def _payment_paragraph(ctx: DocContext) -> str:
    p = ctx.payment
    cash_name = (p.cash_account.name if p.cash_account else (p.gl_account.name if p.gl_account else "cash account"))
    return (
        f"Received from <b>{ctx.purchaser.name}</b> on "
        f"<b>{p.paid_on.strftime('%B %d, %Y')}</b> the sum of "
        f"<b>{_pkr(p.amount)}</b> via <b>{(p.method or 'cash')}</b> "
        f"into <b>{cash_name}</b>"
        + (f", reference <b>{p.reference}</b>" if p.reference else "")
        + f". Applied against trade <b>{ctx.trade.reference}</b>."
    )


def _closing_for(kind: str, ctx: DocContext) -> list:
    if kind == "vendor_po":
        return [
            SectionTitle("Delivery Instructions"),
            ParagraphBlock(
                "Please confirm receipt of this purchase order and advise expected "
                f"dispatch date. Reference <b>{_ref_for(kind, ctx.trade)}</b> on all "
                "shipping documents and invoices."
            ),
        ]
    if kind == "order_confirm":
        return [
            SectionTitle("Order Confirmation"),
            ParagraphBlock(
                f"This confirms the order placed by <b>{ctx.purchaser.name}</b> "
                f"under reference <b>{_ref_for(kind, ctx.trade)}</b>. "
                f"Goods will be delivered as specified above. "
                f"Payment terms: <b>{ctx.trade.customer_terms_days} days</b> from invoice."
            ),
            SectionTitle("Quantity Tolerance"),
            ParagraphBlock(ORDER_QTY_TOLERANCE_NOTE),
        ]
    if kind == "delivery_note":
        return [
            SectionTitle("Receipt of Goods"),
            ParagraphBlock(
                "Please inspect the goods on receipt and acknowledge below. "
                "Any shortage or damage must be reported within 48 hours."
            ),
            ParagraphBlock("<br/><br/><br/>Signature: ___________________________  &nbsp;&nbsp; Date: _______________"),
        ]
    if kind == "delivery_pack":
        return [
            SectionTitle("Receipt & Verification"),
            ParagraphBlock(
                "Warehouse: tick each line in the <b>Packed</b> column above before sealing "
                "the shipment. Customer: inspect goods on receipt and sign below. "
                "Any shortage or damage must be reported within 48 hours."
            ),
            ParagraphBlock("<br/><br/>Packed by: ____________________________  &nbsp;&nbsp; Date: _______________"),
            ParagraphBlock("<br/>Received by: __________________________  &nbsp;&nbsp; Date: _______________"),
        ]
    if kind == "packing_slip":
        return [
            SectionTitle("Carrier / Notes"),
            ParagraphBlock(
                "Confirm all items packed match the quantities above before sealing the shipment."
            ),
        ]
    if kind == "payment_receipt":
        return [
            SectionTitle("Thank You"),
            ParagraphBlock(
                "This receipt acknowledges payment received against the trade above. "
                "Retain for your records."
            ),
        ]
    if kind == "delivery_invoice":
        suffix = f" on {ctx.event_label}" if ctx.event_label else ""
        _due = _due_date_for(ctx)
        due_phrase = (f"by <b>{_due.strftime('%B %d, %Y')}</b>"
                      if _due else
                      f"within <b>{ctx.trade.customer_terms_days} days</b> of this invoice")
        return [
            SectionTitle("Payment Instructions"),
            ParagraphBlock(
                f"Kindly remit the amount due {due_phrase}. "
                f"Please reference invoice <b>{_ref_for(kind, ctx.trade)}</b>"
                f"{suffix} on your payment so we can apply it correctly."
            ),
        ]
    return []
