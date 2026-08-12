"""Trade-derived document PDFs — shared context builder.

Every customer/vendor-facing document for a trade (Order Confirmation,
Delivery Note, Packing Slip, Vendor PO, Payment Receipt) is generated
on-demand from the live Trade data. No persistence — every doc is a
computed view, which means existing trades automatically inherit access
to every document type with no backfill needed.

Reference numbers use only the NUMERIC part of the trade ref, so external docs
carry a clean "OC-0001 / DN-0001 / PO-0001" number — never our internal "TRD-".
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Optional

from models import Party, Trade, TradeLine, TradePayment


def _split_pcts(trade: Trade, side: str):
    """Normalised (adv, dely, cred, days, cred2, days2) so percentages always
    total 100. cred2/days2 are 0 on the vendor side (no second tranche there)."""
    if side == "customer":
        adv, dely, cred, days = (trade.cust_advance_pct, trade.cust_delivery_pct,
                                 trade.cust_credit_pct, trade.customer_terms_days)
        cred2, days2 = trade.cust_credit2_pct, trade.customer_terms2_days
    else:
        adv, dely, cred, days = (trade.vend_advance_pct, trade.vend_delivery_pct,
                                 trade.vend_credit_pct, trade.vendor_terms_days)
        cred2, days2 = Decimal(0), 0
    adv, dely, cred, cred2 = (Decimal(adv or 0), Decimal(dely or 0),
                              Decimal(cred or 0), Decimal(cred2 or 0))
    tot = adv + dely + cred + cred2
    if tot <= 0:
        adv, dely, cred, cred2, tot = Decimal(0), Decimal(0), Decimal(100), Decimal(0), Decimal(100)
    return (adv / tot * 100, dely / tot * 100, cred / tot * 100, int(days or 0),
            cred2 / tot * 100, int(days2 or 0))


def _terms_label(trade: Trade, side: str) -> str:
    """Readable split terms for docs, e.g. '30% advance · 50% on delivery ·
    20% in 25 days'. Normalised to 100%. On the customer side, a non-zero
    cust_credit2_pct appends a second '% in N days' segment."""
    adv, dely, cred, days, cred2, days2 = _split_pcts(trade, side)
    parts = []
    if adv > 0:
        parts.append(f"{float(adv):g}% advance")
    if dely > 0:
        parts.append(f"{float(dely):g}% on delivery")
    if cred > 0:
        parts.append(f"{float(cred):g}% " + (f"in {days} days" if days else "on delivery"))
    if cred2 > 0:
        parts.append(f"{float(cred2):g}% " + (f"in {days2} days" if days2 else "on delivery"))
    return " · ".join(parts) if parts else f"Net {days} days"


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
    # External documents carry a clean "PO-0019" / "DN-0019" style number built
    # from the NUMERIC part of the internal trade ref only — never our internal
    # "TRD-" scheme (customers/vendors shouldn't see it).
    ref_num = (trade.reference or "").split("-")[-1] or (trade.reference or "")
    base = f"{prefix}-{ref_num}"
    return f"{base}-{suffix}" if suffix else base


def _due_dates_for(ctx) -> list:
    """[(pct, due_date), ...] for each customer credit tranche billed on this
    invoice's delivery event — due_date = event date + customer_terms_days.

    A non-zero cust_credit2_pct splits the credit portion into two tranches,
    each with its own day-count (customer_terms_days / customer_terms2_days);
    otherwise a single (100, due_date) entry, matching the old behaviour.
    Falls back to the trade-level `customer_due_date` if no event_date is set
    (e.g. a full-trade-level use of the helper).
    """
    from datetime import timedelta
    t = ctx.trade
    if not ctx.event_date:
        return [(Decimal(100), getattr(t, "customer_due_date", None))]
    pct1 = Decimal(t.cust_credit_pct or 0)
    pct2 = Decimal(t.cust_credit2_pct or 0)
    if pct2 > 0 and (pct1 + pct2) > 0:
        return [
            (pct1, ctx.event_date + timedelta(days=int(t.customer_terms_days or 0))),
            (pct2, ctx.event_date + timedelta(days=int(t.customer_terms2_days or 0))),
        ]
    return [(Decimal(100), ctx.event_date + timedelta(days=int(t.customer_terms_days or 0)))]


def _due_phrase_for(ctx, fmt: str = "%b %d, %Y", with_by: bool = True, bold: bool = False) -> str:
    """Human-readable due-date phrase, e.g. 'by Sep 06, 2026', or
    '50% by Sep 06, 2026 · 50% by Sep 16, 2026' when split into two tranches."""
    dues = [d for d in _due_dates_for(ctx) if d[1]]
    if not dues:
        return ""
    wrap = (lambda s: f"<b>{s}</b>") if bold else (lambda s: s)
    prefix = "by " if with_by else ""
    if len(dues) == 1:
        return f"{prefix}{wrap(dues[0][1].strftime(fmt))}"
    return " · ".join(f"{float(p):g}% {prefix}{wrap(d.strftime(fmt))}" for p, d in dues)


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
        # One priced table with a Packed checkbox column — a separate
        # no-price "Packing Checklist" used to just repeat the same
        # description/qty a second time with nothing new to add.
        sections.append(SectionTitle("Items Delivered"))
        sections.append(_lines_table(_with_kind(ctx, "delivery_pack_items")))
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
            suffix=f"Payment terms: {_terms_label(ctx.trade, 'vendor')}",
        ))
    elif kind == "order_confirm":
        sections.append(CalloutCard(
            label="Total",
            value=_pkr(ctx.trade.total_sale),
            suffix=f"Payment terms: {_terms_label(ctx.trade, 'customer')}",
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
        suffix_parts = []
        if ctx.event_label:
            suffix_parts.append(f"For delivery on {ctx.event_label}")
        _phrase = _due_phrase_for(ctx)
        if _phrase:
            suffix_parts.append(f"Due {_phrase}")
        if ctx.trade.customer_terms_days:
            suffix_parts.append(_terms_label(ctx.trade, 'customer'))
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
        ]
    kpis = [
        KpiSpec("Items", str(len(t.lines))),
    ]
    if kind == "vendor_po":
        kpis.append(KpiSpec("Order Value", _pkr(t.total_cost)))
        kpis.append(KpiSpec("Pay Terms",   _terms_label(t, 'vendor')))
    elif kind == "order_confirm":
        kpis.append(KpiSpec("Total",     _pkr(t.total_sale)))
        kpis.append(KpiSpec("Pay Terms", _terms_label(t, 'customer')))
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
        _phrase = _due_phrase_for(ctx, with_by=False)
        kpis.append(KpiSpec(
            "Due Date",
            _phrase if _phrase else "—",
            sub=_terms_label(t, 'customer'),
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
        elif ctx.kind == "delivery_pack_items":
            line_amt = (qty * Decimal(ln.unit_price)).quantize(Decimal("0.01"))
            rows.append([name_html, qty_text, _pkr(ln.unit_price), _pkr(line_amt), "☐"])
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
    if ctx.kind == "delivery_pack_items":
        return TableSpec(
            headers=["Description", "Qty", "Rate", "Amount", "Packed"],
            rows=rows,
            col_widths=[250, 55, 75, 85, 55],
            num_cols={1, 2, 3},
            totals_row=["", "", "Total", _pkr(subtotal), ""],
        )
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
                f"Payment terms: <b>{_terms_label(ctx.trade, 'customer')}</b>."
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
        _phrase = _due_phrase_for(ctx, fmt="%B %d, %Y", bold=True)
        due_phrase = _phrase if _phrase else f"within <b>{ctx.trade.customer_terms_days} days</b> of this invoice"
        return [
            SectionTitle("Payment Instructions"),
            ParagraphBlock(
                f"Kindly remit the amount due {due_phrase}. "
                f"Please reference invoice <b>{_ref_for(kind, ctx.trade)}</b>"
                f"{suffix} on your payment so we can apply it correctly."
            ),
        ]
    return []
