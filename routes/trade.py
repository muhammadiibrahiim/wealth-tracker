"""
Routes for the Trade module.
"""
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from config import DEFAULT_USER_ID, CURRENCY_SYMBOL
from database import get_session
from models import Party, PaymentDirection, QuotationStatus, TradeStatus
from services.trade import (
    CashAccountService,
    ItemService,
    MasterReceiptService,
    PartyService,
    PaymentService,
    QuotationService,
    TradeReportService,
    TradeService,
)
from services import account_setup


router = APIRouter(prefix="/trade", tags=["trade"])
templates = Jinja2Templates(directory="templates")


# ───────── helpers ──────────────────────────────────────────────


def _ctx(request: Request, **extra) -> dict:
    base = {"request": request, "currency": CURRENCY_SYMBOL}
    base.update(extra)
    return base


def _parse_decimal(s: Optional[str], default: str = "0") -> Decimal:
    if s is None or str(s).strip() == "":
        return Decimal(default)
    try:
        return Decimal(str(s).strip())
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _close_modal() -> Response:
    """Tell HTMX to close the modal and reload the page."""
    return Response(status_code=204, headers={"HX-Refresh": "true"})


# ───────── dashboard ────────────────────────────────────────────


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request, month: str = Query(None),
                    session: Session = Depends(get_session)):
    import calendar
    user_id = DEFAULT_USER_ID
    today = date.today()
    # Resolve the selected month (YYYY-MM) → its first day, last day, and the
    # as-of date (today for the current month, month-end for a past month).
    sel_start = today.replace(day=1)
    if month:
        try:
            y, m = month.split("-")
            sel_start = date(int(y), int(m), 1)
        except (ValueError, TypeError):
            sel_start = today.replace(day=1)
    if sel_start > today:                      # no future months
        sel_start = today.replace(day=1)
    month_end = date(sel_start.year, sel_start.month,
                     calendar.monthrange(sel_start.year, sel_start.month)[1])
    as_of = min(today, month_end)

    kpis = TradeReportService.dashboard_kpis(session, user_id, as_of=as_of)
    recent = TradeService.list(session, user_id)[:8]
    parties = PartyService.list(session, user_id)
    party_map = {p.id: p for p in parties}
    items = ItemService.list(session, user_id, active_only=True)
    accounts = CashAccountService.list(session, user_id, active_only=True)
    from services.analytics import working_capital_metrics, capital_utilization, time_based_performance
    wc = working_capital_metrics(session, user_id, as_of=as_of)
    cap = capital_utilization(session, user_id, as_of=as_of,
                              ni_from=sel_start, ni_to=as_of)
    perf = time_based_performance(session, user_id, as_of=as_of)
    from services import partners as PS
    owner_roe = PS.owner_returns(session, user_id, sel_start, as_of) if PS._owner_partner(session, user_id) or PS._non_owner_partners(session, user_id) else []
    return templates.TemplateResponse(
        "trade_dashboard.html",
        _ctx(
            request,
            kpis=kpis,
            recent=recent,
            party_map=party_map,
            party_count=sum(1 for p in parties if p.is_active),
            item_count=len(items),
            account_count=len(accounts),
            today=date.today(),
            wc=wc,
            cap=cap,
            perf=perf,
            owner_roe=owner_roe,
            selected_month=sel_start.strftime("%Y-%m"),
            month_label=sel_start.strftime("%B %Y"),
            month_short=sel_start.strftime("%b %Y"),
            is_current_month=(sel_start == today.replace(day=1)),
        ),
    )


# ───────── trades list & detail ─────────────────────────────────


@router.get("/trades", response_class=HTMLResponse)
async def trades_list(
    request: Request,
    status: Optional[str] = Query(None),
    party_id: Optional[int] = Query(None),
    tab: Optional[str] = Query("all"),
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    status_enum = None
    if status:
        try:
            status_enum = TradeStatus(status)
        except ValueError:
            status_enum = None
    trades = TradeService.list(session, user_id, status=status_enum, party_id=party_id)
    # All / Pending tabs. "Pending" = the cycle isn't done yet (still to deliver
    # and/or still to collect) — i.e. anything not Completed/Cancelled/Closed.
    _DONE = {TradeStatus.COMPLETED, TradeStatus.CANCELLED, TradeStatus.CLOSED}
    all_count = len(trades)
    pending_trades = [t for t in trades if t.status not in _DONE]
    pending_count = len(pending_trades)
    tab = (tab or "all").lower()
    if tab == "pending":
        trades = pending_trades
    parties = PartyService.list(session, user_id)
    party_map = {p.id: p for p in parties}
    # Net profit (after bilty + trade costs) and ROI per trade — same basis as
    # the trade-detail card so the numbers match.
    trade_metrics = {}
    for t in trades:
        tc = TradeService.trade_costs_total(session, user_id, t)
        net = (Decimal(t.total_sale) - Decimal(t.total_cost) - tc)
        invested = Decimal(t.total_cost) + tc
        roi = (net / invested * 100) if invested > 0 else None
        trade_metrics[t.id] = {
            "net_profit": net.quantize(Decimal("0.01")),
            "roi": (roi.quantize(Decimal("0.01")) if roi is not None else None),
        }
    return templates.TemplateResponse(
        "trade_list.html",
        _ctx(
            request,
            trades=trades,
            parties=parties,
            party_map=party_map,
            trade_metrics=trade_metrics,
            current_status=status,
            current_party=party_id,
            current_tab=tab,
            all_count=all_count,
            pending_count=pending_count,
            statuses=[s.value for s in TradeStatus],
            today=date.today(),
        ),
    )


@router.get("/trades/new", response_class=HTMLResponse)
async def trade_new_modal(request: Request, session: Session = Depends(get_session),
                          from_: str = Query("", alias="from")):
    user_id = DEFAULT_USER_ID
    # Previously-used spec values per label (lower-cased key) → autocomplete.
    from models import TradeLineSpec as _TLS
    spec_rows = session.exec(select(_TLS.label, _TLS.value)).all()
    spec_values: dict[str, list[str]] = {}
    for lab, val in spec_rows:
        lab = (lab or "").strip().lower()
        val = (val or "").strip()
        if not lab or not val:
            continue
        bucket = spec_values.setdefault(lab, [])
        if val not in bucket:
            bucket.append(val)
    for k in spec_values:
        spec_values[k].sort()

    # Optional pre-fill from the Projection planner: one line per included order,
    # with buy/sale rates, qty, and the vendor payment split carried over. Vendor
    # and customer are left blank for the user to pick.
    prefill = None
    if from_ == "projection":
        from models import ProjectionLine
        plines = session.exec(
            select(ProjectionLine).where(
                ProjectionLine.user_id == user_id, ProjectionLine.include == True  # noqa: E712
            ).order_by(ProjectionLine.sort_order, ProjectionLine.id)
        ).all()
        # vendor payment split — averaged across lines (they're usually uniform)
        def _avg(attr):
            vals = [float(getattr(p, attr) or 0) for p in plines]
            return round(sum(vals) / len(vals)) if vals else 0
        prefill = {
            "lines": [{
                "name": p.item_name, "qty": float(p.quantity),
                "buy": float(p.purchase_rate), "sale": float(p.sale_rate),
                "dye": float(p.dye_block_cost), "bilty": float(p.bilty),
            } for p in plines],
            "vend_advance": _avg("pct_advance"),
            "vend_delivery": _avg("pct_on_delivery"),
            "vend_credit": _avg("pct_credit"),
            "vendor_terms": int(round(sum(int(p.credit_days or 0) for p in plines) / len(plines))) if plines else 30,
            "collect_days": int(round(sum(int(p.collection_lag_days or 0) for p in plines) / len(plines))) if plines else 30,
        }

    return templates.TemplateResponse(
        "trade_new_modal.html",
        _ctx(
            request,
            vendors=PartyService.list_vendors(session, user_id),
            customers=PartyService.list_customers(session, user_id),
            items=ItemService.list(session, user_id, active_only=True),
            spec_values=spec_values,
            prefill=prefill,
            today=date.today(),
        ),
    )


@router.post("/trades")
async def trade_create(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    form = await request.form()

    vendor_id = int(form.get("vendor_id") or 0)
    purchaser_id = int(form.get("purchaser_id") or 0)
    customer_terms = int(_parse_decimal(form.get("customer_terms_days"), "30"))
    vendor_terms = int(_parse_decimal(form.get("vendor_terms_days"), "7"))
    split = dict(
        cust_advance_pct=_parse_decimal(form.get("cust_advance_pct"), "0"),
        cust_delivery_pct=_parse_decimal(form.get("cust_delivery_pct"), "0"),
        cust_credit_pct=_parse_decimal(form.get("cust_credit_pct"), "100"),
        vend_advance_pct=_parse_decimal(form.get("vend_advance_pct"), "0"),
        vend_delivery_pct=_parse_decimal(form.get("vend_delivery_pct"), "0"),
        vend_credit_pct=_parse_decimal(form.get("vend_credit_pct"), "100"),
    )

    # Inline party creation: if a vendor/customer name was typed that doesn't
    # exist yet, the New-Party step collected its details — create the party
    # now (with its ledger account) and use its id for the trade.
    vendor_new = (form.get("vendor_new_name") or "").strip()
    customer_new = (form.get("customer_new_name") or "").strip()
    if not vendor_id and vendor_new:
        vp = PartyService.create(
            session, user_id, name=vendor_new, is_vendor=True, is_customer=False,
            contact_person=(form.get("vendor_new_contact") or "").strip() or None,
            phone=(form.get("vendor_new_phone") or "").strip() or None,
            city=(form.get("vendor_new_city") or "").strip() or None,
            default_vendor_terms_days=vendor_terms, default_customer_terms_days=30,
        )
        account_setup.sync_party_account(session, user_id, vp)
        vendor_id = vp.id
    if not purchaser_id and customer_new:
        cp = PartyService.create(
            session, user_id, name=customer_new, is_customer=True, is_vendor=False,
            contact_person=(form.get("customer_new_contact") or "").strip() or None,
            phone=(form.get("customer_new_phone") or "").strip() or None,
            city=(form.get("customer_new_city") or "").strip() or None,
            default_customer_terms_days=customer_terms, default_vendor_terms_days=7,
        )
        account_setup.sync_party_account(session, user_id, cp)
        purchaser_id = cp.id

    if not vendor_id or not purchaser_id:
        raise HTTPException(400, "Vendor and purchaser are required")
    if vendor_id == purchaser_id:
        raise HTTPException(400, "Vendor and purchaser must be different parties")
    trade_date = _parse_date(form.get("trade_date")) or date.today()
    notes = (form.get("notes") or "").strip() or None

    # Reconstruct lines from posted indices.
    line_indices = sorted({int(k.split("_")[1]) for k in form.keys() if k.startswith("line_") and "_item_name" in k})
    # existing catalog items, keyed by name — a typed-in name not in the catalog
    # gets auto-created (and reused thereafter).
    catalog_by_name = {(i.name or "").strip().lower(): i.id
                       for i in ItemService.list(session, user_id)}
    lines: list[dict] = []
    for idx in line_indices:
        name = (form.get(f"line_{idx}_item_name") or "").strip()
        if not name:
            continue
        item_id_raw = form.get(f"line_{idx}_item_id")
        item_id = int(item_id_raw) if item_id_raw else None
        spec_labels = form.getlist(f"line_{idx}_spec_label")
        spec_values = form.getlist(f"line_{idx}_spec_value")
        specs = []
        for lab, val in zip(spec_labels, spec_values):
            if lab.strip() or val.strip():
                specs.append({"label": lab, "value": val})
        # No catalog item picked → match by name, else create a new catalog item
        # (with its spec labels as the template) so it's reusable next time.
        if item_id is None:
            key = name.lower()
            if key in catalog_by_name:
                item_id = catalog_by_name[key]
            else:
                new_item = ItemService.create(
                    session, user_id,
                    spec_labels=[l for l in spec_labels if l.strip()] or None,
                    name=name,
                    unit=(form.get(f"line_{idx}_unit") or "pcs").strip(),
                    default_price=_parse_decimal(form.get(f"line_{idx}_unit_price"), "0"),
                )
                catalog_by_name[key] = new_item.id
                item_id = new_item.id
        lines.append(
            {
                "item_id": item_id,
                "item_name": name,
                "quantity": _parse_decimal(form.get(f"line_{idx}_quantity"), "1"),
                "unit": (form.get(f"line_{idx}_unit") or "pcs").strip(),
                "unit_cost": _parse_decimal(form.get(f"line_{idx}_unit_cost"), "0"),
                "unit_price": _parse_decimal(form.get(f"line_{idx}_unit_price"), "0"),
                "line_notes": (form.get(f"line_{idx}_notes") or "").strip() or None,
                "specs": specs,
            }
        )
    if not lines:
        raise HTTPException(400, "At least one line item is required")

    trade = TradeService.create(
        session,
        user_id,
        vendor_id=vendor_id,
        purchaser_id=purchaser_id,
        customer_terms_days=customer_terms,
        vendor_terms_days=vendor_terms,
        trade_date=trade_date,
        notes=notes,
        lines=lines,
        **split,
    )
    # If this trade was created from the Projection planner, those planned orders
    # are now real — remove them so they stop counting as "projected investment".
    if form.get("from_projection"):
        from models import ProjectionLine
        for pl in session.exec(select(ProjectionLine).where(
                ProjectionLine.user_id == user_id, ProjectionLine.include == True)).all():  # noqa: E712
            session.delete(pl)
        session.commit()
    return Response(status_code=204, headers={"HX-Redirect": f"/trade/trades/{trade.id}"})


@router.get("/trades/{trade_id}", response_class=HTMLResponse)
async def trade_detail(request: Request, trade_id: int, session: Session = Depends(get_session)):
    from models import Account, JournalEntry, JournalEntryType
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    vendor = PartyService.get(session, user_id, trade.vendor_id)
    purchaser = PartyService.get(session, user_id, trade.purchaser_id)

    # Trade costs posted via Record Cost. Self-paid costs now route through the
    # P&L A/C (EXPENSE, Dr 3903 / Cr payee) + a close-to-Capital; customer-paid
    # ones stay as a JOURNAL that reduces the customer's receivable. Both share
    # the "{ref} cost:" prefix; the "{ref} cost close:" JVs are excluded by it.
    cost_prefix = f"{trade.reference} cost:"
    cost_entries = session.exec(
        select(JournalEntry).where(
            JournalEntry.user_id == user_id,
            JournalEntry.trade_id == trade.id,
            JournalEntry.entry_type.in_([JournalEntryType.JOURNAL, JournalEntryType.EXPENSE]),
            JournalEntry.description.like(f"{cost_prefix}%"),
            JournalEntry.is_reversed == False,  # noqa: E712
        ).order_by(JournalEntry.entry_date, JournalEntry.id)
    ).all()
    capital_acct = session.exec(
        select(Account).where(Account.user_id == user_id, Account.name == "Capital A/C")
    ).first()
    pl_acct = session.exec(
        select(Account).where(Account.user_id == user_id, Account.code == "3903")
    ).first()
    _skip_ids = {a.id for a in (capital_acct, pl_acct) if a}
    purchaser_acct = account_setup.sync_party_account(session, user_id, purchaser) if purchaser else None
    purchaser_acct_id = purchaser_acct.id if purchaser_acct else None

    costs = []
    total_cost_absorbed = Decimal("0")
    customer_paid_costs = Decimal("0")
    for e in cost_entries:
        # payee = the credited counterparty line (not the Capital or P&L legs)
        payee_line = next(
            (ln for ln in e.lines if ln.account_id not in _skip_ids and Decimal(ln.credit or 0) > 0),
            None,
        )
        if not payee_line:
            continue
        payee_acct = session.get(Account, payee_line.account_id)
        amount = Decimal(payee_line.credit or 0)
        total_cost_absorbed += amount
        by_customer = (
            purchaser_acct_id is not None
            and payee_line.account_id == purchaser_acct_id
            and (e.description or "").endswith("[paid-by-customer]")
        )
        if by_customer:
            customer_paid_costs += amount
        # Strip the description prefix and trailing tag for display.
        clean_desc = e.description
        if clean_desc.startswith(cost_prefix):
            clean_desc = clean_desc[len(cost_prefix):].strip()
        if clean_desc.endswith("[paid-by-customer]"):
            clean_desc = clean_desc.removesuffix("[paid-by-customer]").strip()
        costs.append({
            "entry_id": e.id,
            "reference": e.reference,
            "entry_date": e.entry_date,
            "description": clean_desc,
            "payee": payee_acct.name if payee_acct else "—",
            "payee_code": payee_acct.code if payee_acct else "",
            "amount": amount,
            "by_customer": by_customer,
        })

    # Bilty entries paid by customer also reduce their receivable. They use a
    # different description shape ({ref} <desc> [bilty-for:{date}] [paid-by-customer])
    # than the "Record Cost" flow, so add their amounts in here.
    if purchaser_acct_id is not None:
        bilty_by_cust = session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.entry_type == JournalEntryType.EXPENSE,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalEntry.description.like("%[paid-by-customer]"),
            )
        ).all()
        for e in bilty_by_cust:
            for ln in e.lines:
                if ln.account_id == purchaser_acct_id and Decimal(ln.credit or 0) > 0:
                    customer_paid_costs += Decimal(ln.credit)

    # Use the shared helper so the button, the status badge and this number
    # always agree — it nets cash received, customer-paid costs AND write-offs.
    customer_outstanding = TradeService.customer_outstanding(session, trade)

    from models import TradeAttachment, TradeAttachmentKind
    attachments = list(session.exec(
        select(TradeAttachment).where(
            TradeAttachment.user_id == user_id,
            TradeAttachment.trade_id == trade.id,
        ).order_by(TradeAttachment.uploaded_at)
    ).all())
    # Split by kind so the trade detail can render dedicated sections.
    def _kind_of(a):
        return a.kind.value if hasattr(a.kind, "value") else a.kind
    customer_pos = [a for a in attachments if _kind_of(a) == "customer_po"]
    designs      = [a for a in attachments if _kind_of(a) == "design"]
    other_atts   = [a for a in attachments
                    if _kind_of(a) not in ("customer_po", "design")]

    inbound_payments = sorted(
        [p for p in trade.payments
         if (p.direction.value if hasattr(p.direction, "value") else p.direction) == "inbound"],
        key=lambda p: (p.paid_on, p.id or 0),
    )

    # Unique receipt dates → one combined DN+PS row per delivery event.
    receipt_dates = sorted({
        r.received_on for ln in trade.lines for r in (ln.receipts or [])
    })

    # Bilty (transport expense) per delivery date — used by both the Receipts
    # table (inline amount + Add/Edit button) and the Documents section.
    from models import TradeBilty, TradeTerminal
    bilties_by_date: dict = {}
    for d in receipt_dates:
        entry = _find_bilty(session, user_id, trade.id, d)
        if entry:
            amt = next((Decimal(ln.debit) for ln in entry.lines if Decimal(ln.debit) > 0), Decimal("0"))
            by_cust = (entry.description or "").endswith("[paid-by-customer]")
            meta = session.exec(
                select(TradeBilty).where(
                    TradeBilty.trade_id == trade.id,
                    TradeBilty.journal_entry_id == entry.id,
                )
            ).first()
            terminal_name = None
            if meta and meta.terminal_id:
                term = session.get(TradeTerminal, meta.terminal_id)
                if term:
                    terminal_name = term.name
            bilties_by_date[d] = {
                "entry": entry,
                "amount": amt,
                "by_customer": by_cust,
                "weight_kgs": (meta.weight_kgs if meta else None),
                "terminal": terminal_name,
            }

    # Net profit = line-item margin minus the direct costs of executing the
    # trade: bilty (delivery freight) and Record Cost entries.
    bilty_total = sum((b["amount"] for b in bilties_by_date.values()), Decimal("0"))
    trade_costs_total = (total_cost_absorbed + bilty_total).quantize(Decimal("0.01"))
    net_profit = (
        Decimal(trade.total_sale) - Decimal(trade.total_cost) - trade_costs_total
    ).quantize(Decimal("0.01"))

    return templates.TemplateResponse(
        "trade_detail.html",
        _ctx(
            request,
            trade=trade,
            vendor=vendor,
            purchaser=purchaser,
            cust_terms_label=TradeService.terms_label(trade, "customer"),
            vend_terms_label=TradeService.terms_label(trade, "vendor"),
            today=date.today(),
            customer_outstanding=customer_outstanding,
            trade_costs_total=trade_costs_total,
            net_profit=net_profit,
            vendor_outstanding=(Decimal(trade.total_cost) - Decimal(trade.paid_to_vendor)).quantize(Decimal("0.01")),
            costs=costs,
            total_cost_absorbed=total_cost_absorbed.quantize(Decimal("0.01")),
            customer_paid_costs=customer_paid_costs.quantize(Decimal("0.01")),
            attachments=attachments,
            customer_pos=customer_pos,
            designs=designs,
            other_atts=other_atts,
            inbound_payments=inbound_payments,
            receipt_dates=receipt_dates,
            bilties_by_date=bilties_by_date,
        ),
    )


@router.post("/trades/{trade_id}/deliver")
async def trade_mark_delivered(
    trade_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    form = await request.form()
    delivered_on = _parse_date(form.get("delivered_on"))

    # Collect per-line final quantities: form fields named `final_qty_<line_id>`.
    final_qtys: dict[int, Decimal] = {}
    for key, value in form.items():
        if key.startswith("final_qty_"):
            try:
                line_id = int(key.removeprefix("final_qty_"))
            except ValueError:
                continue
            final_qtys[line_id] = _parse_decimal(value, "0")

    TradeService.mark_delivered(
        session,
        user_id,
        trade_id,
        delivered_on=delivered_on,
        final_quantities=final_qtys or None,
    )
    return _close_modal()


@router.get("/trades/{trade_id}/deliver", response_class=HTMLResponse)
async def trade_deliver_modal(request: Request, trade_id: int, session: Session = Depends(get_session)):
    from services.trade import ReceiptService
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    # For each line, the suggested final qty = sum of receipts (or current qty if none).
    line_defaults = {}
    for ln in trade.lines:
        recv = ReceiptService.line_received_total(session, ln.id)
        line_defaults[ln.id] = recv if recv > 0 else Decimal(ln.quantity)
    return templates.TemplateResponse(
        "trade_deliver_modal.html",
        _ctx(request, trade=trade, today=date.today(), line_defaults=line_defaults),
    )


@router.get("/trades/{trade_id}/edit", response_class=HTMLResponse)
async def trade_edit_modal(trade_id: int, request: Request,
                           session: Session = Depends(get_session)):
    trade = TradeService.get(session, DEFAULT_USER_ID, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    return templates.TemplateResponse(
        "trade_edit_modal.html", _ctx(request, trade=trade),
    )


@router.post("/trades/{trade_id}/edit")
async def trade_edit_save(trade_id: int, request: Request,
                          session: Session = Depends(get_session)):
    """Edit trade header: dates, terms days and the payment splits. These don't
    touch the ledger (they affect due dates, forecast and docs only)."""
    trade = TradeService.get(session, DEFAULT_USER_ID, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    form = await request.form()
    td = _parse_date(form.get("trade_date"))
    if td:
        trade.trade_date = td
    trade.customer_terms_days = int(_parse_decimal(form.get("customer_terms_days"), str(trade.customer_terms_days)))
    trade.vendor_terms_days = int(_parse_decimal(form.get("vendor_terms_days"), str(trade.vendor_terms_days)))
    for f in ("cust_advance_pct", "cust_delivery_pct", "cust_credit_pct",
              "vend_advance_pct", "vend_delivery_pct", "vend_credit_pct"):
        setattr(trade, f, _parse_decimal(form.get(f), str(getattr(trade, f))))
    # refresh due dates from the (possibly new) terms if delivered
    if trade.delivered_at:
        trade.customer_due_date = trade.delivered_at + timedelta(days=trade.customer_terms_days)
        trade.vendor_due_date = trade.trade_date + timedelta(days=trade.vendor_terms_days)
    trade.updated_at = datetime.utcnow()
    session.add(trade)
    session.commit()
    return _close_modal()


@router.post("/trades/{trade_id}/cancel")
async def trade_cancel(
    trade_id: int,
    reason: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    TradeService.cancel(session, DEFAULT_USER_ID, trade_id, reason)
    return _close_modal()


@router.post("/trades/{trade_id}/close")
async def trade_close(trade_id: int, session: Session = Depends(get_session)):
    TradeService.close(session, DEFAULT_USER_ID, trade_id)
    return _close_modal()


@router.post("/trades/{trade_id}/delete")
async def trade_delete(trade_id: int, session: Session = Depends(get_session)):
    TradeService.delete(session, DEFAULT_USER_ID, trade_id)
    # After delete the trade page no longer exists — redirect to the list.
    return Response(status_code=204, headers={"HX-Redirect": "/trade/trades"})


# ───────── purchases (cost recorded per batch/rate) ─────


@router.get("/trades/{trade_id}/purchase/new", response_class=HTMLResponse)
async def trade_purchase_modal(request: Request, trade_id: int, session: Session = Depends(get_session)):
    from services.trade import PurchaseService, ReceiptService
    trade = TradeService.get(session, DEFAULT_USER_ID, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    line_info = []
    for ln in trade.lines:
        purchased = PurchaseService.line_purchased_qty(session, ln.id)
        line_info.append({
            "line": ln,
            "purchased_qty": purchased,
            "remaining": (Decimal(ln.quantity) - purchased).quantize(Decimal("0.001")),
            "purchases": PurchaseService.list_for_line(session, ln.id),
        })
    return templates.TemplateResponse(
        "trade_purchase_modal.html",
        _ctx(request, trade=trade, line_info=line_info, today=date.today()),
    )


@router.post("/trades/{trade_id}/purchase")
async def trade_purchase_post(trade_id: int, request: Request, session: Session = Depends(get_session)):
    """Record purchases (qty + rate + optional invoice) per line, then re-post cost."""
    from services.trade import PurchaseService
    import os, uuid
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    form = await request.form()
    purchased_on = _parse_date(form.get("purchased_on")) or date.today()
    notes = (form.get("notes") or "").strip() or None
    upload_dir = "static/uploads/invoices"
    os.makedirs(upload_dir, exist_ok=True)
    recorded = 0
    for ln in trade.lines:
        qty_raw = form.get(f"line_{ln.id}_qty")
        rate_raw = form.get(f"line_{ln.id}_rate")
        if not qty_raw or not rate_raw:
            continue
        try:
            qty = Decimal(str(qty_raw)); rate = Decimal(str(rate_raw))
        except Exception:
            continue
        if qty <= 0:
            continue
        invoice_path = None
        f = form.get(f"line_{ln.id}_invoice")
        if f and hasattr(f, "filename") and f.filename:
            ext = os.path.splitext(f.filename)[1].lower() or ".bin"
            safe = f"{uuid.uuid4().hex}{ext}"
            full = os.path.join(upload_dir, safe)
            with open(full, "wb") as out:
                while True:
                    chunk = await f.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            invoice_path = f"/{full}"
        PurchaseService.record(session, user_id, trade_id, ln.id, qty, rate,
                               purchased_on=purchased_on, vendor_invoice_path=invoice_path,
                               notes=notes)
        recorded += 1
    if not recorded:
        raise HTTPException(400, "No purchases entered")
    return _close_modal()


@router.post("/purchases/{purchase_id}/delete")
async def purchase_delete(purchase_id: int, session: Session = Depends(get_session)):
    from services.trade import PurchaseService
    PurchaseService.delete(session, DEFAULT_USER_ID, purchase_id)
    return _close_modal()


# ───────── partial receipts (vendor delivery + invoice upload) ─────


@router.get("/trades/{trade_id}/receive", response_class=HTMLResponse)
async def trade_receive_modal(request: Request, trade_id: int, session: Session = Depends(get_session)):
    from services.trade import ReceiptService
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    line_info = []
    for ln in trade.lines:
        received = ReceiptService.line_received_total(session, ln.id)
        line_info.append({
            "line": ln,
            "received_total": received,
            "remaining": (Decimal(ln.ordered_quantity or ln.quantity) - received).quantize(Decimal("0.001")),
            "receipts": ReceiptService.list_for_line(session, ln.id),
        })
    return templates.TemplateResponse(
        "trade_receive_modal.html",
        _ctx(request, trade=trade, line_info=line_info, today=date.today()),
    )


@router.post("/trades/{trade_id}/receive")
async def trade_receive_post(trade_id: int, request: Request, session: Session = Depends(get_session)):
    """Multipart endpoint: each line carries qty + optional invoice file."""
    from services.trade import ReceiptService
    import os
    import uuid

    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")

    form = await request.form()
    received_on = _parse_date(form.get("received_on")) or date.today()
    notes = (form.get("notes") or "").strip() or None

    upload_dir = "static/uploads/invoices"
    os.makedirs(upload_dir, exist_ok=True)

    per_line: dict[int, Decimal] = {}
    invoice_paths: dict[int, Optional[str]] = {}

    for ln in trade.lines:
        key = f"line_{ln.id}_qty"
        qty_raw = form.get(key)
        if not qty_raw:
            continue
        try:
            qty = Decimal(str(qty_raw))
        except Exception:
            continue
        if qty <= 0:
            continue
        per_line[ln.id] = qty

        # Optional file upload for this line.
        file_field = form.get(f"line_{ln.id}_invoice")
        if file_field and hasattr(file_field, "filename") and file_field.filename:
            ext = os.path.splitext(file_field.filename)[1].lower() or ".bin"
            safe_name = f"{uuid.uuid4().hex}{ext}"
            full_path = os.path.join(upload_dir, safe_name)
            with open(full_path, "wb") as out:
                while True:
                    chunk = await file_field.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            # Store browser-loadable URL path.
            invoice_paths[ln.id] = f"/{full_path}"

    if not per_line:
        raise HTTPException(400, "No quantities entered")

    ReceiptService.record(
        session, user_id, trade_id,
        per_line=per_line,
        received_on=received_on,
        invoice_paths=invoice_paths,
        notes=notes,
    )
    return _close_modal()


@router.post("/receipts/{receipt_id}/delete")
async def receipt_delete(receipt_id: int, session: Session = Depends(get_session)):
    from services.trade import ReceiptService
    ReceiptService.delete(session, DEFAULT_USER_ID, receipt_id)
    return _close_modal()


@router.get("/goods-received", response_class=HTMLResponse)
async def goods_received(request: Request, session: Session = Depends(get_session)):
    """Log of every goods-receipt, grouped into deliveries (one vendor, one date)
    — the combined view of what came in on each Master Receive / partial delivery."""
    from models import (TradeLineReceipt, TradeLine, Trade, TradeBilty,
                        TradePurchase, TradeTerminal, JournalEntry, Party)
    user_id = DEFAULT_USER_ID
    vname = {p.id: p.name for p in session.exec(select(Party).where(Party.user_id == user_id)).all()}
    rows = session.exec(
        select(TradeLineReceipt, TradeLine, Trade)
        .join(TradeLine, TradeLineReceipt.line_id == TradeLine.id)
        .join(Trade, TradeLine.trade_id == Trade.id)
        .where(Trade.user_id == user_id)
        .order_by(TradeLineReceipt.received_on.desc(), Trade.id)
    ).all()

    groups: dict = {}
    for r, line, trade in rows:
        key = (r.received_on, trade.vendor_id)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"date": r.received_on, "vendor": vname.get(trade.vendor_id, "?"),
                               "vendor_id": trade.vendor_id, "lines": [], "trade_ids": set(),
                               "notes": [], "invoice": None, "total_qty": Decimal("0")}
        batches = session.exec(select(TradePurchase).where(
            TradePurchase.line_id == line.id,
            TradePurchase.purchased_on == r.received_on)).all()
        g["lines"].append({
            "trade_id": trade.id, "trade_ref": trade.reference, "customer": vname.get(trade.purchaser_id, "?"),
            "item": line.item_name, "unit": line.unit, "qty": Decimal(r.received_qty),
            "batches": [{"qty": Decimal(b.quantity), "rate": Decimal(b.unit_cost)} for b in batches],
            "receipt_id": r.id,
        })
        g["trade_ids"].add(trade.id)
        g["total_qty"] += Decimal(r.received_qty)
        if r.notes and r.notes not in g["notes"]:
            g["notes"].append(r.notes)
        if r.vendor_invoice_path and not g["invoice"]:
            g["invoice"] = r.vendor_invoice_path

    # attach bilty (summed across the group's trades for that date)
    deliveries = []
    for key, g in groups.items():
        d = g["date"]
        bilty_total = Decimal("0"); kg = Decimal("0"); terms = []; paid_cust = False
        for tid in g["trade_ids"]:
            for b in session.exec(select(TradeBilty).where(
                    TradeBilty.trade_id == tid, TradeBilty.delivery_date == d)).all():
                je = session.get(JournalEntry, b.journal_entry_id)
                if je and not je.is_reversed:
                    bilty_total += sum((Decimal(l.debit) for l in je.lines), Decimal("0"))
                if b.weight_kgs:
                    kg += Decimal(b.weight_kgs)
                if b.paid_by_customer:
                    paid_cust = True
                if b.terminal_id:
                    t = session.get(TradeTerminal, b.terminal_id)
                    if t and t.name not in terms:
                        terms.append(t.name)
        g["bilty_total"] = bilty_total.quantize(Decimal("0.01"))
        g["bilty_kg"] = kg
        g["terminals"] = terms
        g["paid_by_customer"] = paid_cust
        g["trade_count"] = len(g["trade_ids"])
        deliveries.append(g)
    deliveries.sort(key=lambda x: x["date"], reverse=True)
    return templates.TemplateResponse(
        "trade_goods_received.html", _ctx(request, deliveries=deliveries),
    )


@router.get("/trades/receive/new", response_class=HTMLResponse)
async def master_receive_modal(request: Request, session: Session = Depends(get_session)):
    """Master Receive Voucher — one vendor delivery across many trades/items."""
    from models import Account, AccountSubClass, TradeTerminal, TradeStatus
    from services.trade import ReceiptService
    user_id = DEFAULT_USER_ID
    open_trades = [t for t in TradeService.list(session, user_id)
                   if t.status in (TradeStatus.OPEN, TradeStatus.DELIVERED, TradeStatus.PARTIALLY_PAID)]
    trades_data = []
    for t in open_trades:
        vendor = PartyService.get(session, user_id, t.vendor_id)
        customer = PartyService.get(session, user_id, t.purchaser_id)
        lines = []
        pending = False
        for ln in t.lines:
            recv = ReceiptService.line_received_total(session, ln.id)
            remaining = float(ln.quantity) - float(recv)
            if remaining > 0.0005:
                pending = True
            # short spec summary for the picker (e.g. size / brand)
            spec = " · ".join(f"{s.label}: {s.value}" for s in (ln.specs or []) if s.value)[:60]
            lines.append({"id": ln.id, "name": ln.item_name, "unit": ln.unit,
                          "ordered": float(ln.quantity), "received": float(recv),
                          "remaining": remaining, "rate": float(ln.unit_cost), "spec": spec})
        trades_data.append({"id": t.id, "ref": t.reference,
                            "vendor": vendor.name if vendor else "?",
                            "customer": customer.name if customer else "?",
                            "date": t.trade_date.isoformat() if t.trade_date else "",
                            "delivered": t.delivered_at is not None,
                            "pending": pending, "lines": lines})
    sub = session.exec(select(AccountSubClass).where(
        AccountSubClass.user_id == user_id, AccountSubClass.code == "1100")).first()
    cash = list(session.exec(select(Account).where(
        Account.subclass_id == sub.id, Account.is_active == True)).all()) if sub else []  # noqa: E712
    ceo = next((a for a in session.exec(select(Account).where(Account.user_id == user_id)).all()
                if (a.name or "").strip().lower() in ("ibrahim (ceo)", "ceo", "funding")), None)
    if ceo and ceo.id not in {a.id for a in cash}:
        cash.append(ceo)
    terminals = list(session.exec(select(TradeTerminal).where(
        TradeTerminal.user_id == user_id).order_by(TradeTerminal.name)).all())
    return templates.TemplateResponse(
        "trade_master_receive_modal.html",
        _ctx(request, trades_data=trades_data, cash_accounts=cash, terminals=terminals,
             today=date.today(), default_cash_id=(ceo.id if ceo else (cash[0].id if cash else None))),
    )


@router.post("/trades/receive")
async def master_receive_post(request: Request, session: Session = Depends(get_session)):
    from services.trade import MasterReceiveService
    import os, uuid
    user_id = DEFAULT_USER_ID
    form = await request.form()
    received_on = _parse_date(form.get("received_on")) or date.today()
    bilty_total = _parse_decimal(form.get("bilty_total"), "0")
    bilty_by_customer = bool(form.get("bilty_by_customer"))
    terminal = (form.get("terminal") or "").strip()
    notes = (form.get("notes") or "").strip() or None
    paid_from_raw = form.get("paid_from_id")
    paid_from_id = int(paid_from_raw) if (paid_from_raw and str(paid_from_raw).isdigit()) else None

    # one shared vendor-invoice image for the whole delivery
    invoice_path = None
    f = form.get("invoice")
    if f is not None and hasattr(f, "filename") and f.filename:
        upload_dir = "static/uploads/invoices"
        os.makedirs(upload_dir, exist_ok=True)
        ext = os.path.splitext(f.filename)[1].lower() or ".bin"
        full_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}{ext}")
        with open(full_path, "wb") as out:
            while True:
                chunk = await f.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        invoice_path = f"/{full_path}"

    idxs = sorted({int(k.split("_")[1]) for k in form.keys()
                   if k.startswith("row_") and k.endswith("_trade_id")})
    rows = []
    for i in idxs:
        tid = form.get(f"row_{i}_trade_id")
        lid = form.get(f"row_{i}_line_id")
        qty = form.get(f"row_{i}_qty")
        if not (tid and lid and qty):
            continue
        try:
            if Decimal(str(qty)) <= 0:
                continue
        except Exception:
            continue
        rows.append({"trade_id": int(tid), "line_id": int(lid), "qty": qty,
                     "rate": form.get(f"row_{i}_rate") or "0", "kg": form.get(f"row_{i}_kg") or "0"})
    if not rows:
        raise HTTPException(400, "Add at least one received line (trade, item, qty)")
    MasterReceiveService.record(
        session, user_id, received_on, rows, bilty_total=bilty_total,
        terminal_name=terminal, paid_from_id=paid_from_id, notes=notes,
        invoice_path=invoice_path, bilty_by_customer=bilty_by_customer)
    return _close_modal()


# ───────── trade-attributed cost (DR Capital A/C / CR payee) ────────


@router.get("/trades/{trade_id}/cost/new", response_class=HTMLResponse)
async def trade_cost_modal(request: Request, trade_id: int, session: Session = Depends(get_session)):
    from models import Account, AccountClass
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    # All active accounts (with class name for the dropdown grouping).
    accounts = list(session.exec(
        select(Account).where(Account.user_id == user_id, Account.is_active == True)  # noqa: E712
        .order_by(Account.code)
    ).all())
    capital_acct = session.exec(
        select(Account).where(Account.user_id == user_id, Account.name == "Capital A/C")
    ).first()
    purchaser = PartyService.get(session, user_id, trade.purchaser_id)
    purchaser_acct = account_setup.sync_party_account(session, user_id, purchaser) if purchaser else None
    return templates.TemplateResponse(
        "trade_cost_modal.html",
        _ctx(request, trade=trade, accounts=accounts,
             capital_acct=capital_acct,
             purchaser=purchaser, purchaser_acct=purchaser_acct,
             today=date.today()),
    )


@router.post("/trades/{trade_id}/cost")
async def trade_cost_post(
    trade_id: int,
    description: str = Form(...),
    amount: str = Form(...),
    payee_account_id: Optional[int] = Form(None),
    paid_by_customer: Optional[str] = Form(None),
    cost_date: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    from models import Account
    from services.posting import PostingEngine, PostingError
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    amt = _parse_decimal(amount, "0")
    if amt <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    capital = session.exec(
        select(Account).where(Account.user_id == user_id, Account.name == "Capital A/C")
    ).first()
    if not capital:
        raise HTTPException(400, "Capital A/C not found — create it in Chart of A/Cs first")

    customer_paid = bool(paid_by_customer)
    if customer_paid:
        purchaser = PartyService.get(session, user_id, trade.purchaser_id)
        if not purchaser:
            raise HTTPException(400, "Purchaser not found on this trade")
        payee = account_setup.sync_party_account(session, user_id, purchaser)
        if not payee:
            raise HTTPException(400, "Could not resolve purchaser receivable account")
    else:
        if not payee_account_id:
            raise HTTPException(400, "Payee account is required")
        payee = session.get(Account, payee_account_id)
        if not payee or payee.user_id != user_id:
            raise HTTPException(400, "Invalid payee account")

    desc = (description or "").strip() or "Trade cost"
    tag = " [paid-by-customer]" if customer_paid else ""
    entry_date = _parse_date(cost_date) or date.today()
    try:
        from models import JournalEntryType as _JET
        if customer_paid:
            # Customer bore this cost — it reduces their receivable (unchanged
            # behaviour; not our P&L expense since we didn't incur it).
            PostingEngine.post(
                session, user_id, entry_date=entry_date, entry_type=_JET.JOURNAL,
                description=f"{trade.reference} cost: {desc}{tag}",
                lines=[
                    {"account_id": capital.id, "debit": amt, "credit": 0,
                     "description": f"Cost absorbed by capital ({desc})"},
                    {"account_id": payee.id, "debit": 0, "credit": amt,
                     "description": desc + " (paid by customer)",
                     "party_id": trade.purchaser_id},
                ],
                trade_id=trade.id,
            )
        else:
            # OUR cost — route it through the trade's P&L (3903) so it lands in
            # THIS trade's profit AND net income, then close to Capital (mirrors
            # how bilty is handled). No longer silently absorbed into Capital.
            pl = session.exec(select(Account).where(
                Account.user_id == user_id, Account.code == "3903")).first()
            if not pl:
                raise HTTPException(400, "Profit/Loss A/C (3903) not found")
            PostingEngine.post(
                session, user_id, entry_date=entry_date, entry_type=_JET.EXPENSE,
                description=f"{trade.reference} cost: {desc}",
                lines=[
                    {"account_id": pl.id, "debit": amt, "credit": 0,
                     "description": f"Trade cost — {desc} ({trade.reference})",
                     "trade_line_id": None},
                    {"account_id": payee.id, "debit": 0, "credit": amt,
                     "description": desc, "party_id": None},
                ],
                trade_id=trade.id,
            )
            PostingEngine.post(
                session, user_id, entry_date=entry_date, entry_type=_JET.JOURNAL,
                description=f"{trade.reference} cost close: {desc}",
                lines=[
                    {"account_id": capital.id, "debit": amt, "credit": 0,
                     "description": f"Close trade cost to Capital — {desc} ({trade.reference})"},
                    {"account_id": pl.id, "debit": 0, "credit": amt,
                     "description": f"Close trade cost — {desc} ({trade.reference})"},
                ],
                trade_id=trade.id,
            )
    except PostingError as e:
        raise HTTPException(400, str(e))
    return _close_modal()


@router.get("/trades/{trade_id}/invoice.pdf")
async def trade_invoice_pdf(trade_id: int, session: Session = Depends(get_session)):
    """Customer-facing invoice PDF (pure reportlab via services.pdf_helper)."""
    from io import BytesIO
    from models import Account, JournalEntry, JournalEntryType
    from services.pdf_helper import (
        render_report_pdf, ReportSpec, KpiSpec, TableSpec,
        SectionTitle, ParagraphBlock, CalloutCard,
    )

    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    purchaser = PartyService.get(session, user_id, trade.purchaser_id)
    if not purchaser:
        raise HTTPException(400, "Purchaser not found")

    # ── Aggregate cash payments + customer-paid costs ────────────
    cash_payments = sorted(
        [p for p in trade.payments
         if (p.direction.value if hasattr(p.direction, "value") else p.direction) == "inbound"],
        key=lambda p: (p.paid_on, p.id or 0),
    )
    cash_paid_total = sum((Decimal(p.amount) for p in cash_payments), Decimal("0"))

    purchaser_acct = account_setup.sync_party_account(session, user_id, purchaser)
    purchaser_acct_id = purchaser_acct.id if purchaser_acct else None
    cost_prefix = f"{trade.reference} cost:"
    cost_entries = session.exec(
        select(JournalEntry).where(
            JournalEntry.user_id == user_id,
            JournalEntry.trade_id == trade.id,
            JournalEntry.entry_type == JournalEntryType.JOURNAL,
            JournalEntry.description.like(f"{cost_prefix}%"),
            JournalEntry.is_reversed == False,  # noqa: E712
        ).order_by(JournalEntry.entry_date, JournalEntry.id)
    ).all()
    customer_paid_costs = []
    for e in cost_entries:
        if not (e.description or "").endswith("[paid-by-customer]"):
            continue
        payee_line = next((ln for ln in e.lines if ln.account_id == purchaser_acct_id), None)
        if not payee_line or not purchaser_acct_id:
            continue
        desc = e.description[len(cost_prefix):].strip()
        if desc.endswith("[paid-by-customer]"):
            desc = desc.removesuffix("[paid-by-customer]").strip()
        customer_paid_costs.append({
            "entry_date": e.entry_date,
            "description": desc,
            "amount": Decimal(payee_line.credit or 0),
        })
    # Customer-paid bilties use a different shape than the "Record Cost" flow:
    # EXPENSE entries tagged "{ref} <desc> [bilty-for:{date}] [paid-by-customer]".
    bilty_entries = session.exec(
        select(JournalEntry).where(
            JournalEntry.user_id == user_id,
            JournalEntry.trade_id == trade.id,
            JournalEntry.entry_type == JournalEntryType.EXPENSE,
            JournalEntry.description.like("%[bilty-for:%"),
            JournalEntry.description.like("%[paid-by-customer]"),
            JournalEntry.is_reversed == False,  # noqa: E712
        ).order_by(JournalEntry.entry_date, JournalEntry.id)
    ).all()
    for e in bilty_entries:
        payee_line = next((ln for ln in e.lines if ln.account_id == purchaser_acct_id), None)
        if not payee_line or not purchaser_acct_id:
            continue
        desc = e.description or ""
        if desc.startswith(trade.reference):
            desc = desc[len(trade.reference):].strip()
        desc = re.sub(r"\s*\[bilty-for:[0-9-]+\]", "", desc).removesuffix("[paid-by-customer]").strip()
        customer_paid_costs.append({
            "entry_date": e.entry_date,
            "description": desc or "Bilty",
            "amount": Decimal(payee_line.credit or 0),
        })
    customer_paid_costs.sort(key=lambda c: c["entry_date"])
    customer_paid_costs_total = sum(
        (Decimal(c["amount"]) for c in customer_paid_costs), Decimal("0")
    )

    subtotal    = Decimal(trade.total_sale)
    amount_paid = (cash_paid_total + customer_paid_costs_total).quantize(Decimal("0.01"))
    balance_due = (subtotal - amount_paid).quantize(Decimal("0.01"))

    if balance_due <= 0:
        status = "Paid"
    elif amount_paid > 0:
        status = "Partial"
    elif trade.customer_due_date and trade.customer_due_date < date.today():
        status = "Overdue"
    else:
        status = "Unpaid"

    def pkr(v):
        try:
            return f"Rs. {Decimal(str(v)):,.2f}"
        except Exception:
            return f"Rs. {v}"

    # ── KPI strip ────────────────────────────────────────────────
    kpis = [
        KpiSpec("Total",       pkr(subtotal)),
        KpiSpec("Balance Due", pkr(balance_due), negative=balance_due > 0),
        KpiSpec("Status",      status, negative=status in ("Unpaid", "Overdue", "Partial")),
        KpiSpec(
            "Due Date",
            trade.customer_due_date.strftime("%b %d, %Y") if trade.customer_due_date else "—",
            sub=f"{trade.customer_terms_days} day terms" if trade.customer_terms_days else "",
        ),
    ]

    # ── Charges table (one row per item; specs bullet under name) ──
    charge_rows = []
    for ln in trade.lines:
        bullets = [f"{s.label}: {s.value}" for s in (ln.specs or [])]
        if ln.line_notes:
            bullets.append(ln.line_notes)
        name_html = f"<b>{ln.item_name}</b>"
        if bullets:
            name_html += "<br/>" + "<br/>".join(
                f"<font color='#65675e' size='8'>• {b}</font>" for b in bullets
            )
        line_amount = (Decimal(ln.quantity) * Decimal(ln.unit_price)).quantize(Decimal("0.01"))
        charge_rows.append([
            name_html,
            f"{ln.quantity:g} {ln.unit}",
            pkr(ln.unit_price),
            pkr(line_amount),
        ])
    charges = TableSpec(
        headers=["Description", "Qty", "Rate", "Amount"],
        rows=charge_rows,
        col_widths=[300, 60, 90, 100],
        num_cols={1, 2, 3},
        totals_row=["", "", "Subtotal", pkr(subtotal)],
    )

    # ── Bill-To block ────────────────────────────────────────────
    bill_to_lines = [f"<b>{purchaser.name}</b>"]
    if purchaser.address: bill_to_lines.append(purchaser.address)
    if purchaser.phone:   bill_to_lines.append(f"Phone: {purchaser.phone}")
    if purchaser.email:   bill_to_lines.append(f"Email: {purchaser.email}")
    bill_to_html = "<br/>".join(bill_to_lines)

    sections = [
        SectionTitle("Bill To"),
        ParagraphBlock(bill_to_html),
        SectionTitle("Charges"),
        charges,
    ]

    # ── Payments & Adjustments table (only if any) ───────────────
    if cash_payments or customer_paid_costs:
        pay_rows = []
        for p in cash_payments:
            method = f" · {p.method}" if p.method else ""
            acct = p.cash_account.name if p.cash_account else "—"
            pay_rows.append([
                p.paid_on.strftime("%b %d, %Y"),
                "Cash payment",
                f"{acct}{method}",
                f"- {pkr(p.amount)}",
            ])
        for c in customer_paid_costs:
            pay_rows.append([
                c["entry_date"].strftime("%b %d, %Y"),
                "Paid on our behalf",
                c["description"],
                f"- {pkr(c['amount'])}",
            ])
        sections += [
            SectionTitle("Payments & Adjustments"),
            TableSpec(
                headers=["Date", "Type", "Details", "Amount"],
                rows=pay_rows,
                col_widths=[80, 120, 250, 100],
                num_cols={3},
                sign_color_cols={3},
                totals_row=["", "", "Total received", f"- {pkr(amount_paid)}"],
            ),
        ]

    # ── Amount Due callout ───────────────────────────────────────
    if balance_due <= 0:
        callout_suffix = "Fully settled — thank you"
    elif status == "Overdue":
        callout_suffix = "Past due — kindly remit at the earliest"
    elif trade.customer_due_date:
        callout_suffix = f"Due by {trade.customer_due_date.strftime('%b %d, %Y')}"
    else:
        callout_suffix = "Top up to settle"

    sections.append(CalloutCard(
        label="Amount Paid" if balance_due <= 0 else "Amount Due",
        value=pkr(balance_due if balance_due > 0 else amount_paid),
        suffix=callout_suffix,
        negative=balance_due > 0,
    ))

    # ── Payment Details footer paragraph ─────────────────────────
    sections.append(SectionTitle("Payment Details"))
    sections.append(ParagraphBlock(
        f"Kindly remit the balance due by the date shown above. "
        f"Please reference invoice <b>{trade.reference}</b> on your payment so we can apply it correctly."
    ))
    if customer_paid_costs_total > 0:
        sections.append(ParagraphBlock(
            f"<font color='#65675e'>Includes {pkr(customer_paid_costs_total)} in costs you paid on our behalf, "
            f"deducted from this invoice.</font>"
        ))

    buf = BytesIO()
    render_report_pdf(buf, ReportSpec(
        title="Invoice",
        subtitle_parts=[
            f"Invoice {trade.reference}",
            f"Issued {trade.trade_date.strftime('%B %d, %Y')}" if trade.trade_date else "",
            f"Billed to {purchaser.name}",
        ],
        kpis=kpis,
        sections=sections,
        footer_subtitle="Ibrahim Traders · billing",
        generated_label="Issued",
        brand="IBRAHIM TRADERS",
    ))
    pdf_bytes = buf.getvalue()
    filename = f"Invoice-{trade.reference}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/trades/{trade_id}/costs/{entry_id}/delete")
async def trade_cost_delete(trade_id: int, entry_id: int, session: Session = Depends(get_session)):
    """Reverse a previously-posted trade cost journal entry (and, for a self-paid
    cost routed through the P&L, its matching close-to-Capital entry)."""
    from models import JournalEntry
    from services.posting import PostingEngine, PostingError
    user_id = DEFAULT_USER_ID
    entry = session.get(JournalEntry, entry_id)
    if not entry or entry.user_id != user_id or entry.trade_id != trade_id:
        raise HTTPException(404, "Cost entry not found")
    try:
        PostingEngine.reverse(session, user_id, entry_id, reason="Trade cost deleted")
        # Self-paid costs post a paired "... cost close: ..." JV — reverse it too
        # so the P&L clearing account and Capital stay balanced.
        desc = entry.description or ""
        close_desc = desc.replace(" cost: ", " cost close: ", 1)
        if close_desc != desc:
            close = session.exec(
                select(JournalEntry).where(
                    JournalEntry.user_id == user_id,
                    JournalEntry.trade_id == trade_id,
                    JournalEntry.description == close_desc,
                    JournalEntry.is_reversed == False,  # noqa: E712
                )
            ).first()
            if close:
                PostingEngine.reverse(session, user_id, close.id, reason="Trade cost deleted")
    except PostingError as e:
        raise HTTPException(400, str(e))
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.post("/trades/{trade_id}/lines/{line_id}/delete")
async def trade_line_delete(trade_id: int, line_id: int, session: Session = Depends(get_session)):
    TradeService.delete_line(session, DEFAULT_USER_ID, trade_id, line_id)
    return _close_modal()


@router.get("/trades/{trade_id}/lines/new", response_class=HTMLResponse)
async def trade_line_add_modal(trade_id: int, request: Request,
                               session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    # Previously-used spec values per label → autocomplete (same as create modal).
    from models import TradeLineSpec as _TLS
    spec_values: dict[str, list[str]] = {}
    for lab, val in session.exec(select(_TLS.label, _TLS.value)).all():
        lab, val = (lab or "").strip().lower(), (val or "").strip()
        if lab and val and val not in spec_values.setdefault(lab, []):
            spec_values[lab].append(val)
    for k in spec_values:
        spec_values[k].sort()
    return templates.TemplateResponse(
        "trade_line_add_modal.html",
        _ctx(request, trade=trade,
             items=ItemService.list(session, user_id, active_only=True),
             spec_values=spec_values),
    )


@router.post("/trades/{trade_id}/lines")
async def trade_line_add(trade_id: int, request: Request,
                         session: Session = Depends(get_session)):
    form = await request.form()
    name = (form.get("item_name") or "").strip()
    if not name:
        raise HTTPException(400, "Item name is required")
    specs = []
    for lab, val in zip(form.getlist("spec_label"), form.getlist("spec_value")):
        lab, val = (lab or "").strip(), (val or "").strip()
        if lab or val:
            specs.append({"label": lab or "Spec", "value": val})
    raw_item_id = form.get("item_id")
    ln = {
        "item_id": int(raw_item_id) if (raw_item_id and str(raw_item_id).strip().isdigit()) else None,
        "item_name": name,
        "quantity": form.get("quantity") or "1",
        "unit": (form.get("unit") or "pcs").strip() or "pcs",
        "unit_cost": form.get("unit_cost") or "0",
        "unit_price": form.get("unit_price") or "0",
        "line_notes": (form.get("line_notes") or "").strip() or None,
        "specs": specs,
    }
    trade = TradeService.add_line(session, DEFAULT_USER_ID, trade_id, ln)
    if trade is None:
        raise HTTPException(400, "Could not add line — trade not found or cancelled")
    # re-post the ledger so cost/sale reflect the new line (like the edit path)
    TradeService._repost_cost(session, TradeService.get(session, DEFAULT_USER_ID, trade_id))
    return _close_modal()


@router.get("/trades/{trade_id}/lines/{line_id}/edit", response_class=HTMLResponse)
async def trade_line_edit_modal(trade_id: int, line_id: int, request: Request,
                                session: Session = Depends(get_session)):
    from models import TradeLine
    line = session.get(TradeLine, line_id)
    if not line or line.trade_id != trade_id:
        raise HTTPException(404, "Line not found")
    trade = TradeService.get(session, DEFAULT_USER_ID, trade_id)
    return templates.TemplateResponse(
        "trade_line_edit_modal.html", _ctx(request, trade=trade, line=line),
    )


@router.post("/trades/{trade_id}/lines/{line_id}")
async def trade_line_update(trade_id: int, line_id: int, request: Request,
                            session: Session = Depends(get_session)):
    from models import TradeLine, TradeLineSpec
    line = session.get(TradeLine, line_id)
    if not line or line.trade_id != trade_id:
        raise HTTPException(404, "Line not found")
    trade = TradeService.get(session, DEFAULT_USER_ID, trade_id)
    form = await request.form()
    name = (form.get("item_name") or "").strip()
    if name:
        line.item_name = name
    new_qty = _parse_decimal(form.get("quantity"), str(line.quantity))
    # editing an open line is a correction — keep ordered == final unless goods
    # have already been received against it
    had_receipts = bool(line.receipts)
    line.quantity = new_qty
    if not had_receipts:
        line.ordered_quantity = new_qty
    line.unit = (form.get("unit") or line.unit).strip() or "pcs"
    line.unit_cost = _parse_decimal(form.get("unit_cost"), str(line.unit_cost))
    line.unit_price = _parse_decimal(form.get("unit_price"), str(line.unit_price))
    line.line_notes = (form.get("line_notes") or "").strip() or None
    # replace specs with submitted label/value pairs
    for sp in list(line.specs):
        session.delete(sp)
    session.flush()
    labels = form.getlist("spec_label")
    values = form.getlist("spec_value")
    for i, (lab, val) in enumerate(zip(labels, values)):
        lab, val = (lab or "").strip(), (val or "").strip()
        if lab or val:
            session.add(TradeLineSpec(line_id=line.id, label=lab, value=val, sort_order=i))
    session.add(line)
    session.commit()
    # recompute totals + re-post the ledger so COGS/sale reflect the edit
    TradeService._repost_cost(session, trade)
    return _close_modal()


# ───────── payments ─────────────────────────────────────────────


@router.get("/trades/{trade_id}/payments/new", response_class=HTMLResponse)
async def payment_new_modal(
    request: Request,
    trade_id: int,
    direction: str = Query("inbound"),
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    accounts = [a for a in CashAccountService.list(session, user_id, active_only=True) if a.kind != "capital"]
    # Every other ledger account is also selectable — a payment can land on any
    # account (CEO's ledger, a party ledger, etc.), grouped for the dropdown.
    cash_linked_ids = {a.account_id for a in accounts if a.account_id}
    # Exclude the trade's own counterparty account so the user can't pick
    # (e.g.) Fleure as the "paid into" destination for a Fleure receipt —
    # a same-account DR/CR entry that nets to zero and hides the money.
    excluded_ids = set(cash_linked_ids)
    if direction == "outbound":
        counterparty = PartyService.get(session, user_id, trade.vendor_id) if trade.vendor_id else None
    else:
        counterparty = PartyService.get(session, user_id, trade.purchaser_id) if trade.purchaser_id else None
    if counterparty and counterparty.account_id:
        excluded_ids.add(counterparty.account_id)
    gl_groups = []
    for cls_block in account_setup.list_accounts_grouped(session, user_id):
        for sub_block in cls_block["subclasses"]:
            sub = sub_block["subclass"]
            accts = [a for a in sub_block["accounts"] if a.is_active and a.id not in excluded_ids]
            if accts:
                gl_groups.append({"label": f"{sub.code} · {sub.name}", "accounts": accts})
        loose = [a for a in cls_block["accounts_without_subclass"] if a.is_active and a.id not in excluded_ids]
        if loose:
            gl_groups.append({"label": cls_block["class"].name, "accounts": loose})
    dirn = PaymentDirection.OUTBOUND if direction == "outbound" else PaymentDirection.INBOUND
    if dirn == PaymentDirection.INBOUND:
        default_amount = (Decimal(trade.total_sale) - Decimal(trade.paid_by_customer)).quantize(Decimal("0.01"))
    else:
        default_amount = (Decimal(trade.total_cost) - Decimal(trade.paid_to_vendor)).quantize(Decimal("0.01"))
    return templates.TemplateResponse(
        "trade_payment_modal.html",
        _ctx(
            request,
            trade=trade,
            accounts=accounts,
            gl_groups=gl_groups,
            direction=dirn.value,
            default_amount=default_amount if default_amount > 0 else Decimal("0.00"),
            today=date.today(),
        ),
    )


@router.post("/trades/{trade_id}/payments")
async def payment_create(
    trade_id: int,
    direction: str = Form(...),
    account_ref: str = Form(...),
    amount: str = Form(...),
    paid_on: Optional[str] = Form(None),
    method: Optional[str] = Form(None),
    reference: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    proof: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    amt = _parse_decimal(amount, "0")
    if amt <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    # Optional proof-of-payment image (pasted screenshot / uploaded receipt).
    proof_path = None
    if proof is not None and getattr(proof, "filename", None):
        import os, uuid
        upload_dir = "static/uploads/payments"
        os.makedirs(upload_dir, exist_ok=True)
        ext = os.path.splitext(proof.filename)[1].lower() or ".png"
        full_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}{ext}")
        with open(full_path, "wb") as out:
            while True:
                chunk = await proof.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        proof_path = f"/{full_path}"
    # account_ref is "cash:<id>" (managed cash/bank account) or "gl:<id>" (any ledger account)
    try:
        kind, raw_id = account_ref.split(":", 1)
        ref_id = int(raw_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid account selection")
    if kind not in ("cash", "gl"):
        raise HTTPException(400, "Invalid account selection")
    dirn = PaymentDirection.OUTBOUND if direction == "outbound" else PaymentDirection.INBOUND
    try:
        p = PaymentService.record(
            session,
            user_id,
            trade_id=trade_id,
            cash_account_id=ref_id if kind == "cash" else None,
            gl_account_id=ref_id if kind == "gl" else None,
            direction=dirn,
            amount=amt,
            paid_on=_parse_date(paid_on),
            method=(method or "").strip() or None,
            reference=(reference or "").strip() or None,
            notes=(notes or "").strip() or None,
            proof_path=proof_path,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if p is None:
        raise HTTPException(400, "Account not found")
    return _close_modal()


@router.post("/payments/{payment_id}/delete")
async def payment_delete(payment_id: int, session: Session = Depends(get_session)):
    PaymentService.delete(session, DEFAULT_USER_ID, payment_id)
    return _close_modal()


def _gl_groups_for_receipt(session, user_id):
    """Cash/bank + every GL account (grouped) a customer receipt can land in."""
    from services import account_setup
    accounts = [a for a in CashAccountService.list(session, user_id, active_only=True) if a.kind != "capital"]
    cash_linked_ids = {a.account_id for a in accounts if a.account_id}
    gl_groups = []
    for cls_block in account_setup.list_accounts_grouped(session, user_id):
        for sub_block in cls_block["subclasses"]:
            sub = sub_block["subclass"]
            accts = [a for a in sub_block["accounts"] if a.is_active and a.id not in cash_linked_ids]
            if accts:
                gl_groups.append({"label": f"{sub.code} · {sub.name}", "accounts": accts})
        loose = [a for a in cls_block["accounts_without_subclass"] if a.is_active and a.id not in cash_linked_ids]
        if loose:
            gl_groups.append({"label": cls_block["class"].name, "accounts": loose})
    return accounts, gl_groups


@router.get("/payments/receive/new", response_class=HTMLResponse)
async def master_receive_payment_modal(request: Request, session: Session = Depends(get_session)):
    """Master Payment Receive — one customer receipt, auto-applied oldest-due-first
    across that customer's outstanding trades."""
    user_id = DEFAULT_USER_ID
    customers = PartyService.list_customers(session, user_id)
    accounts, gl_groups = _gl_groups_for_receipt(session, user_id)
    return templates.TemplateResponse(
        "trade_master_payment_modal.html",
        _ctx(request, customers=customers, accounts=accounts, gl_groups=gl_groups, today=date.today()),
    )


@router.get("/payments/receive/preview", response_class=HTMLResponse)
async def master_receive_payment_preview(
    request: Request, customer_id: Optional[int] = Query(None),
    amount: Optional[str] = Query(None), session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    prev = None
    if customer_id:
        prev = MasterReceiptService.preview(session, user_id, customer_id, _parse_decimal(amount, "0"))
    return templates.TemplateResponse(
        "trade_master_payment_preview.html", _ctx(request, prev=prev),
    )


@router.post("/payments/receive")
async def master_receive_payment_post(
    request: Request,
    customer_id: int = Form(...),
    amount: str = Form(...),
    account_ref: str = Form(...),
    received_on: Optional[str] = Form(None),
    method: Optional[str] = Form(None),
    reference: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    proof: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    amt = _parse_decimal(amount, "0")
    if amt <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    try:
        kind, raw_id = account_ref.split(":", 1)
        ref_id = int(raw_id)
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid account selection")
    if kind not in ("cash", "gl"):
        raise HTTPException(400, "Invalid account selection")
    proof_path = None
    if proof is not None and getattr(proof, "filename", None):
        import os, uuid
        upload_dir = "static/uploads/payments"
        os.makedirs(upload_dir, exist_ok=True)
        ext = os.path.splitext(proof.filename)[1].lower() or ".png"
        full_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}{ext}")
        with open(full_path, "wb") as out:
            while True:
                chunk = await proof.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        proof_path = f"/{full_path}"
    try:
        res = MasterReceiptService.record(
            session, user_id, customer_id=customer_id, amount=amt,
            received_on=_parse_date(received_on),
            cash_account_id=ref_id if kind == "cash" else None,
            gl_account_id=ref_id if kind == "gl" else None,
            method=(method or "").strip() or None,
            reference=(reference or "").strip() or None,
            notes=(notes or "").strip() or None,
            proof_path=proof_path,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "Could not apply the payment"))
    return _close_modal()


@router.post("/trades/{trade_id}/writeoff-residual")
async def trade_writeoff_residual(trade_id: int, session: Session = Depends(get_session)):
    """Write off a tiny remaining customer balance (< Rs 100) to expense and mark
    the trade fully settled. Posts DR Other Expenses / CR customer A/R so the
    receivable clears and the small under-collection lands in the P&L."""
    user_id = DEFAULT_USER_ID
    ok, msg = TradeService.writeoff_residual(session, user_id, trade_id, threshold=Decimal("100"))
    if not ok:
        raise HTTPException(400, msg)
    return Response(status_code=204, headers={"HX-Redirect": f"/trade/trades/{trade_id}"})


# ───────── parties ──────────────────────────────────────────────


@router.get("/parties", response_class=HTMLResponse)
async def parties_list(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    parties = PartyService.list(session, user_id)
    return templates.TemplateResponse("trade_parties.html", _ctx(request, parties=parties))


# ── Partners (equity) ────────────────────────────────────────────────────
@router.get("/partners", response_class=HTMLResponse)
async def partners_page(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    from services import partners as PS
    from models import Account
    # Auto-run any due monthly allocations (idempotent — catches up missed months).
    PS.run_due_allocations(session, user_id)
    cap = PS.cap_table(session, user_id)
    history = PS.allocation_history(session, user_id)
    # "Received into" — where an optional opening contribution's cash landed.
    # Offer the user's real accounts, grouped, cash/bank first. Exclude reversal/
    # P&L-clearing and the partner capital accounts themselves.
    from models import AccountSubClass
    partner_acct_ids = {p["account_id"] for p in cap["partners"] if p.get("account_id")}
    owner_p = PS._owner_partner(session, user_id)
    if owner_p and owner_p.account_id:
        partner_acct_ids.add(owner_p.account_id)
    sub_by_id = {s.id: s.code for s in session.exec(select(AccountSubClass).where(AccountSubClass.user_id == user_id)).all()}
    vendor_acct_ids = {v.account_id for v in PartyService.list_vendors(session, user_id) if v.account_id}
    cash_bank, funding, vendors = [], [], []
    for a in session.exec(select(Account).where(Account.user_id == user_id, Account.is_active == True)).all():  # noqa: E712
        if a.id in partner_acct_ids:
            continue
        sub_code = sub_by_id.get(a.subclass_id, "")
        if sub_code == "1100":                              # cash / bank (assets)
            cash_bank.append({"account_id": a.id, "label": a.name})
        elif a.code == "2103":                              # owner funding conduit
            funding.append({"account_id": a.id, "label": "Owner funding (CEO)"})
        elif a.id in vendor_acct_ids and a.code not in ("2102", "2103"):   # an actual vendor's ledger
            vendors.append({"account_id": a.id, "label": a.name})
    groups = [g for g in (("Cash & Bank", cash_bank),
                          ("Owner funding", funding),
                          ("Pay a vendor directly", vendors)) if g[1]]
    return templates.TemplateResponse(
        "trade_partners.html",
        _ctx(request, cap=cap, history=history, funding_groups=groups, today=date.today()),
    )


@router.post("/partners")
async def partner_add(
    request: Request,
    name: str = Form(...),
    pct: str = Form(...),
    joined_on: Optional[str] = Form(None),
    contribution: Optional[str] = Form(None),
    contribution_account_id: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    from services import partners as PS
    try:
        pctd = Decimal(str(pct))
    except Exception:
        pctd = Decimal("0")
    contrib = Decimal(str(contribution)) if (contribution and str(contribution).strip()) else Decimal("0")
    caid = int(contribution_account_id) if (contribution_account_id and str(contribution_account_id).strip().isdigit()) else None
    if name and name.strip():
        PS.add_partner(session, DEFAULT_USER_ID, name.strip(), pctd,
                       joined_on=_parse_date(joined_on),
                       contribution=contrib, contribution_account_id=caid,
                       notes=(notes.strip() if notes else None))
    return RedirectResponse("/trade/partners", status_code=303)


@router.post("/partners/{partner_id}")
async def partner_update(
    partner_id: int,
    pct: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    is_active: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    from services import partners as PS
    kwargs = {}
    if pct is not None and str(pct).strip():
        try:
            kwargs["pct"] = Decimal(str(pct))
        except Exception:
            pass
    if name is not None and str(name).strip():
        kwargs["name"] = name.strip()
    if is_active is not None:
        kwargs["is_active"] = str(is_active).lower() in ("1", "true", "on", "yes")
    PS.update_partner(session, DEFAULT_USER_ID, partner_id, **kwargs)
    return RedirectResponse("/trade/partners", status_code=303)


@router.post("/partners/allocate")
async def partners_allocate(session: Session = Depends(get_session)):
    from services import partners as PS
    PS.run_due_allocations(session, DEFAULT_USER_ID)
    return RedirectResponse("/trade/partners", status_code=303)


@router.post("/partners/setup-owner")
async def partners_setup_owner(
    name: str = Form(...),
    session: Session = Depends(get_session),
):
    """Create the owner's own capital account and move all current retained
    capital into it, so the pool starts empty for the partnership era."""
    from services import partners as PS
    if name and name.strip():
        PS.setup_owner_capital(session, DEFAULT_USER_ID, name.strip())
    return RedirectResponse("/trade/partners", status_code=303)


@router.get("/parties/new", response_class=HTMLResponse)
async def party_new_modal(request: Request):
    from services.pk_cities import PK_CITIES
    return templates.TemplateResponse(
        "trade_party_modal.html",
        _ctx(request, party=None, action="/trade/parties", cities=PK_CITIES),
    )


@router.get("/parties/{party_id}/edit", response_class=HTMLResponse)
async def party_edit_modal(request: Request, party_id: int, session: Session = Depends(get_session)):
    from services.pk_cities import PK_CITIES
    party = PartyService.get(session, DEFAULT_USER_ID, party_id)
    if not party:
        raise HTTPException(404, "Party not found")
    return templates.TemplateResponse(
        "trade_party_modal.html",
        _ctx(request, party=party, action=f"/trade/parties/{party_id}", cities=PK_CITIES),
    )


def _party_form_payload(form_values: dict) -> dict:
    """Shared mapper for party create/update form bodies."""
    is_vendor = bool(form_values.get("is_vendor"))
    is_customer = bool(form_values.get("is_customer")) or not is_vendor
    return {
        "name": (form_values["name"] or "").strip(),
        "is_vendor": is_vendor,
        "is_customer": is_customer,
        "contact_person": (form_values.get("contact_person") or "").strip() or None,
        "phone": (form_values.get("phone") or "").strip() or None,
        "email": (form_values.get("email") or "").strip() or None,
        "address": (form_values.get("address") or "").strip() or None,
        "city": (form_values.get("city") or "").strip() or None,
        "tax_id": (form_values.get("tax_id") or "").strip() or None,
        "default_customer_terms_days": int(form_values.get("default_customer_terms_days") or 30),
        "default_vendor_terms_days": int(form_values.get("default_vendor_terms_days") or 7),
        "max_payment_delay_days": max(0, int(form_values.get("max_payment_delay_days") or 1)),
        "opening_balance": _parse_decimal(form_values.get("opening_balance"), "0"),
        "opening_balance_date": _parse_date(form_values.get("opening_balance_date")),
        "notes": (form_values.get("notes") or "").strip() or None,
    }


@router.post("/parties")
async def party_create(request: Request, session: Session = Depends(get_session)):
    form = dict(await request.form())
    p = PartyService.create(session, DEFAULT_USER_ID, **_party_form_payload(form))
    account_setup.sync_party_account(session, DEFAULT_USER_ID, p)
    return _close_modal()


@router.post("/parties/{party_id}")
async def party_update(party_id: int, request: Request, session: Session = Depends(get_session)):
    form = dict(await request.form())
    p = PartyService.update(session, DEFAULT_USER_ID, party_id, **_party_form_payload(form))
    if p:
        account_setup.sync_party_account(session, DEFAULT_USER_ID, p)
    return _close_modal()


@router.post("/parties/{party_id}/delete")
async def party_delete(party_id: int, session: Session = Depends(get_session)):
    PartyService.delete(session, DEFAULT_USER_ID, party_id)
    return _close_modal()


# ───────── cash accounts ────────────────────────────────────────


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_list(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    accounts = CashAccountService.list(session, user_id)
    rows = []
    for a in accounts:
        rows.append({"account": a, "balance": CashAccountService.balance(session, user_id, a.id)})

    # Group by kind: cash/bank/mobile_wallet/other go under "cash", capital under "capital".
    cash_rows = [r for r in rows if r["account"].kind != "capital"]
    capital_rows = [r for r in rows if r["account"].kind == "capital"]
    return templates.TemplateResponse(
        "trade_accounts.html",
        _ctx(request, cash_rows=cash_rows, capital_rows=capital_rows),
    )


@router.get("/accounts/new", response_class=HTMLResponse)
async def account_new_modal(request: Request):
    return templates.TemplateResponse(
        "trade_account_modal.html", _ctx(request, account=None, action="/trade/accounts")
    )


@router.get("/accounts/{account_id}/edit", response_class=HTMLResponse)
async def account_edit_modal(request: Request, account_id: int, session: Session = Depends(get_session)):
    a = CashAccountService.get(session, DEFAULT_USER_ID, account_id)
    if not a:
        raise HTTPException(404, "Account not found")
    return templates.TemplateResponse(
        "trade_account_modal.html",
        _ctx(request, account=a, action=f"/trade/accounts/{account_id}"),
    )


@router.post("/accounts")
async def account_create(
    name: str = Form(...),
    kind: str = Form("bank"),
    bank_name: Optional[str] = Form(None),
    account_number: Optional[str] = Form(None),
    opening_balance: str = Form("0"),
    notes: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    a = CashAccountService.create(
        session,
        DEFAULT_USER_ID,
        name=name.strip(),
        kind=kind,
        bank_name=(bank_name or "").strip() or None,
        account_number=(account_number or "").strip() or None,
        opening_balance=_parse_decimal(opening_balance, "0"),
        notes=(notes or "").strip() or None,
    )
    account_setup.sync_cash_account(session, DEFAULT_USER_ID, a)
    return _close_modal()


@router.post("/accounts/{account_id}")
async def account_update(
    account_id: int,
    name: str = Form(...),
    kind: str = Form("bank"),
    bank_name: Optional[str] = Form(None),
    account_number: Optional[str] = Form(None),
    opening_balance: str = Form("0"),
    notes: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    a = CashAccountService.update(
        session,
        DEFAULT_USER_ID,
        account_id,
        name=name.strip(),
        kind=kind,
        bank_name=(bank_name or "").strip() or None,
        account_number=(account_number or "").strip() or None,
        opening_balance=_parse_decimal(opening_balance, "0"),
        notes=(notes or "").strip() or None,
    )
    if a:
        account_setup.sync_cash_account(session, DEFAULT_USER_ID, a)
    return _close_modal()


@router.post("/accounts/{account_id}/delete")
async def account_delete(account_id: int, session: Session = Depends(get_session)):
    CashAccountService.delete(session, DEFAULT_USER_ID, account_id)
    return _close_modal()


# ───────── items ────────────────────────────────────────────────


@router.get("/items", response_class=HTMLResponse)
async def items_list(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    items = ItemService.list(session, user_id)
    return templates.TemplateResponse("trade_items.html", _ctx(request, items=items))


@router.get("/items/new", response_class=HTMLResponse)
async def item_new_modal(request: Request):
    return templates.TemplateResponse(
        "trade_item_modal.html", _ctx(request, item=None, action="/trade/items")
    )


@router.get("/items/{item_id}/edit", response_class=HTMLResponse)
async def item_edit_modal(request: Request, item_id: int, session: Session = Depends(get_session)):
    i = ItemService.get(session, DEFAULT_USER_ID, item_id)
    if not i:
        raise HTTPException(404, "Item not found")
    return templates.TemplateResponse(
        "trade_item_modal.html",
        _ctx(request, item=i, action=f"/trade/items/{item_id}"),
    )


@router.post("/items")
async def item_create(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    spec_labels = [v for v in form.getlist("spec_label") if v.strip()]
    ItemService.create(
        session,
        DEFAULT_USER_ID,
        name=(form.get("name") or "").strip(),
        sku=(form.get("sku") or "").strip() or None,
        unit=(form.get("unit") or "pcs").strip(),
        default_cost=_parse_decimal(form.get("default_cost"), "0"),
        default_price=_parse_decimal(form.get("default_price"), "0"),
        notes=(form.get("notes") or "").strip() or None,
        spec_labels=spec_labels,
    )
    return _close_modal()


@router.post("/items/{item_id}")
async def item_update(item_id: int, request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    spec_labels = [v for v in form.getlist("spec_label") if v.strip()]
    ItemService.update(
        session,
        DEFAULT_USER_ID,
        item_id,
        spec_labels=spec_labels,
        name=(form.get("name") or "").strip(),
        sku=(form.get("sku") or "").strip() or None,
        unit=(form.get("unit") or "pcs").strip(),
        default_cost=_parse_decimal(form.get("default_cost"), "0"),
        default_price=_parse_decimal(form.get("default_price"), "0"),
        notes=(form.get("notes") or "").strip() or None,
    )
    return _close_modal()


@router.post("/items/{item_id}/delete")
async def item_delete(item_id: int, session: Session = Depends(get_session)):
    ItemService.delete(session, DEFAULT_USER_ID, item_id)
    return _close_modal()


# ───────── vouchers (cashbook journal vouchers) ────────────────────


def _all_accounts_for_picker(session: Session, user_id: int) -> list:
    from models import Account as _A
    return list(session.exec(
        select(_A).where(_A.user_id == user_id, _A.is_active == True).order_by(_A.code)  # noqa: E712
    ).all())


@router.get("/vouchers", response_class=HTMLResponse)
async def vouchers_list(
    request: Request,
    type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from services.voucher import VoucherService
    from models import JournalEntryType as _JET
    user_id = DEFAULT_USER_ID
    account_setup.seed_chart_of_accounts(session, user_id)
    entry_type = None
    if type:
        try: entry_type = _JET(type)
        except ValueError: entry_type = None
    entries = VoucherService.list_entries(
        session, user_id, from_date=_parse_date(date_from),
        to_date=_parse_date(date_to), entry_type=entry_type,
    )
    rows = []
    for e in entries:
        total = sum((Decimal(l.debit) for l in e.lines), Decimal("0"))
        rows.append({"entry": e, "total": total})
    return templates.TemplateResponse(
        "trade_vouchers.html",
        _ctx(request, rows=rows, current_type=type or "",
             date_from=date_from or "", date_to=date_to or "",
             types=[t.value for t in _JET]),
    )


@router.get("/vouchers/new", response_class=HTMLResponse)
async def voucher_new_modal(
    request: Request,
    preset: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    account_setup.seed_chart_of_accounts(session, user_id)
    accounts = _all_accounts_for_picker(session, user_id)
    presets = {
        "receipt":   {"type": "journal", "label": "Receipt Voucher",  "hint": "Cash in. DR the cash account, CR the source."},
        "payment":   {"type": "journal", "label": "Payment Voucher",  "hint": "Cash out. CR the cash account, DR the expense / payable."},
        "contra":    {"type": "contra",  "label": "Contra Voucher",   "hint": "Cash <-> Bank transfer."},
        "expense":   {"type": "expense", "label": "Expense Voucher",  "hint": "DR an Expense account, CR the cash account."},
        "owner_in":  {"type": "capital_injection", "label": "Owner Injection", "hint": "DR cash, CR Owner's Capital."},
        "owner_out": {"type": "capital_withdrawal","label": "Owner Withdrawal","hint": "DR Owner's Capital, CR cash."},
        "journal":   {"type": "journal", "label": "Journal Voucher",  "hint": "Free-form adjusting entry."},
    }
    chosen = presets.get(preset or "journal", presets["journal"])
    return templates.TemplateResponse(
        "trade_voucher_modal.html",
        _ctx(request, accounts=accounts, today=date.today(),
             preset=preset or "journal", preset_label=chosen["label"],
             preset_type=chosen["type"], preset_hint=chosen["hint"]),
    )


@router.post("/vouchers")
async def voucher_create(request: Request, session: Session = Depends(get_session)):
    from services.voucher import VoucherService
    from services.posting import PostingError
    from models import JournalEntryType as _JET
    user_id = DEFAULT_USER_ID
    form = await request.form()
    entry_date = _parse_date(form.get("entry_date")) or date.today()
    entry_type_raw = form.get("entry_type") or "journal"
    try: entry_type = _JET(entry_type_raw)
    except ValueError: entry_type = _JET.JOURNAL
    description = (form.get("description") or "").strip() or "Voucher entry"

    line_indices = sorted({
        int(k.split("_")[1]) for k in form.keys()
        if k.startswith("line_") and "_account_id" in k
    })
    lines: list[dict] = []
    for idx in line_indices:
        aid = form.get(f"line_{idx}_account_id")
        if not aid: continue
        dr = _parse_decimal(form.get(f"line_{idx}_debit"), "0")
        cr = _parse_decimal(form.get(f"line_{idx}_credit"), "0")
        ldesc = (form.get(f"line_{idx}_description") or "").strip() or None
        if dr == 0 and cr == 0: continue
        lines.append({"account_id": int(aid), "debit": dr, "credit": cr, "description": ldesc})

    if not lines:
        raise HTTPException(400, "Voucher needs at least one line")
    try:
        VoucherService.post_voucher(session, user_id, entry_date=entry_date,
                                     entry_type=entry_type, description=description, lines=lines)
    except PostingError as e:
        raise HTTPException(400, str(e))
    return _close_modal()


@router.get("/vouchers/expense-quick", response_class=HTMLResponse)
async def expense_quick_modal(request: Request, session: Session = Depends(get_session)):
    """Dead-simple business-expense entry: description + amount + paid-from. The
    account routing (P&L → Capital) is handled automatically on post."""
    from models import Account, AccountSubClass
    user_id = DEFAULT_USER_ID
    account_setup.seed_chart_of_accounts(session, user_id)
    sub = session.exec(select(AccountSubClass).where(
        AccountSubClass.user_id == user_id, AccountSubClass.code == "1100")).first()
    cash = list(session.exec(select(Account).where(
        Account.subclass_id == sub.id, Account.is_active == True)).all()) if sub else []  # noqa: E712
    ceo = next((a for a in session.exec(select(Account).where(Account.user_id == user_id)).all()
                if (a.name or "").strip().lower() in ("ibrahim (ceo)", "ceo", "funding")), None)
    if ceo and ceo.id not in {a.id for a in cash}:
        cash.append(ceo)
    return templates.TemplateResponse(
        "trade_expense_quick_modal.html",
        _ctx(request, cash_accounts=cash, today=date.today(),
             default_id=(ceo.id if ceo else (cash[0].id if cash else None))),
    )


@router.post("/vouchers/expense-quick")
async def expense_quick_post(request: Request, session: Session = Depends(get_session)):
    """Post a business expense with automatic P&L routing + close-to-Capital, so
    it correctly hits net income / ROE AND reduces Capital — with no account
    picking or manual closing. Mirrors the trade-cost / bilty pattern."""
    from models import Account, JournalEntryType as _JET
    from services.posting import PostingEngine, PostingError
    user_id = DEFAULT_USER_ID
    form = await request.form()
    desc = (form.get("description") or "").strip() or "Business expense"
    amt = _parse_decimal(form.get("amount"), "0")
    paid_from_id = form.get("paid_from")
    entry_date = _parse_date(form.get("entry_date")) or date.today()
    if amt <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    if not paid_from_id:
        raise HTTPException(400, "Choose where it was paid from")
    pl = session.exec(select(Account).where(Account.user_id == user_id, Account.code == "3903")).first()
    capital = session.exec(select(Account).where(Account.user_id == user_id, Account.name == "Capital A/C")).first()
    paid = session.get(Account, int(paid_from_id))
    if not (pl and capital and paid and paid.user_id == user_id):
        raise HTTPException(400, "Required accounts not found")
    try:
        # 1) recognise the expense in the P&L (hits net income / ROE), paid from cash
        PostingEngine.post(
            session, user_id, entry_date=entry_date, entry_type=_JET.EXPENSE,
            description=f"Business expense: {desc}",
            lines=[
                {"account_id": pl.id, "debit": amt, "credit": 0, "description": f"Business expense — {desc}"},
                {"account_id": paid.id, "debit": 0, "credit": amt, "description": desc},
            ],
        )
        # 2) close it into Capital (reduces retained equity), nets the P&L to zero
        PostingEngine.post(
            session, user_id, entry_date=entry_date, entry_type=_JET.JOURNAL,
            description=f"Business expense close: {desc}",
            lines=[
                {"account_id": capital.id, "debit": amt, "credit": 0, "description": f"Close business expense to Capital — {desc}"},
                {"account_id": pl.id, "debit": 0, "credit": amt, "description": f"Close business expense — {desc}"},
            ],
        )
    except PostingError as e:
        raise HTTPException(400, str(e))
    return _close_modal()


EDITABLE_VOUCHER_TYPES = None  # populated lazily in _ensure_editable_types


def _editable_voucher_types():
    global EDITABLE_VOUCHER_TYPES
    if EDITABLE_VOUCHER_TYPES is None:
        from models import JournalEntryType as _T
        EDITABLE_VOUCHER_TYPES = {
            _T.JOURNAL, _T.EXPENSE, _T.CONTRA,
            _T.CAPITAL_INJECTION, _T.CAPITAL_WITHDRAWAL,
        }
    return EDITABLE_VOUCHER_TYPES


def _assert_voucher_editable(entry):
    """Raise HTTPException if the entry can't be edited in place."""
    if entry.is_reversed:
        raise HTTPException(400, "Cannot edit a reversed voucher — reverse the reversal first, or create a new voucher.")
    if entry.reversal_of_id:
        raise HTTPException(400, "This is a reversal entry — cannot edit. Create a new corrective voucher instead.")
    if entry.trade_id is not None:
        raise HTTPException(
            400,
            "This voucher is auto-posted by a trade — manage via the trade page (cancel / delete / re-deliver).",
        )
    if entry.entry_type not in _editable_voucher_types():
        raise HTTPException(
            400,
            f"Vouchers of type '{entry.entry_type.value if hasattr(entry.entry_type, 'value') else entry.entry_type}' "
            f"are system-posted and cannot be edited.",
        )


@router.get("/vouchers/{entry_id}/edit", response_class=HTMLResponse)
async def voucher_edit_modal(
    request: Request, entry_id: int, session: Session = Depends(get_session)
):
    from models import JournalEntry, Account
    user_id = DEFAULT_USER_ID
    entry = session.get(JournalEntry, entry_id)
    if not entry or entry.user_id != user_id:
        raise HTTPException(404, "Voucher not found")
    _assert_voucher_editable(entry)
    accounts = list(session.exec(
        select(Account).where(Account.user_id == user_id, Account.is_active == True)  # noqa: E712
        .order_by(Account.code)
    ).all())
    et_value = entry.entry_type.value if hasattr(entry.entry_type, "value") else entry.entry_type
    return templates.TemplateResponse(
        "trade_voucher_modal.html",
        _ctx(
            request,
            preset="journal",
            preset_label=f"Edit Voucher · {entry.reference}",
            preset_hint="Adjust accounts, amounts, or description — the existing entry is replaced in place. Reversed / trade-linked / system vouchers can't be edited.",
            preset_type=et_value,
            accounts=accounts,
            today=date.today(),
            editing=True,
            entry=entry,
            existing_lines=list(entry.lines),
        ),
    )


@router.post("/vouchers/{entry_id}")
async def voucher_update(entry_id: int, request: Request, session: Session = Depends(get_session)):
    """Replace the lines of an existing manual voucher in place."""
    from models import JournalEntry, JournalEntryType, JournalLine
    user_id = DEFAULT_USER_ID
    entry = session.get(JournalEntry, entry_id)
    if not entry or entry.user_id != user_id:
        raise HTTPException(404, "Voucher not found")
    _assert_voucher_editable(entry)

    form = await request.form()
    entry_date = _parse_date(form.get("entry_date")) or entry.entry_date
    try:
        new_type = JournalEntryType(form.get("entry_type") or entry.entry_type.value)
    except ValueError:
        new_type = entry.entry_type
    if new_type not in _editable_voucher_types():
        raise HTTPException(400, f"Cannot switch voucher to non-editable type {new_type}")
    description = (form.get("description") or "").strip() or entry.description

    line_indices = sorted({
        int(k.split("_")[1]) for k in form.keys()
        if k.startswith("line_") and "_account_id" in k
    })
    new_lines = []
    for idx in line_indices:
        aid = form.get(f"line_{idx}_account_id")
        if not aid:
            continue
        dr = _parse_decimal(form.get(f"line_{idx}_debit"), "0")
        cr = _parse_decimal(form.get(f"line_{idx}_credit"), "0")
        ldesc = (form.get(f"line_{idx}_description") or "").strip() or None
        if dr == 0 and cr == 0:
            continue
        new_lines.append({"account_id": int(aid), "debit": dr, "credit": cr, "description": ldesc})

    if not new_lines:
        raise HTTPException(400, "At least one line is required")

    total_dr = sum(l["debit"] for l in new_lines)
    total_cr = sum(l["credit"] for l in new_lines)
    if abs(Decimal(total_dr) - Decimal(total_cr)) > Decimal("0.01"):
        raise HTTPException(
            400, f"Unbalanced — DR {total_dr} ≠ CR {total_cr}. Adjust lines so debits equal credits."
        )

    # Replace lines in place. After flush, expire the relationship so the
    # subsequent setattr/add on `entry` doesn't try to re-cascade the
    # now-deleted children (causes InvalidRequestError otherwise).
    for old in list(entry.lines):
        session.delete(old)
    session.flush()
    session.expire(entry, ["lines"])
    for ln in new_lines:
        session.add(JournalLine(
            journal_entry_id=entry.id,
            account_id=ln["account_id"],
            debit=ln["debit"],
            credit=ln["credit"],
            description=ln["description"],
        ))
    entry.entry_date = entry_date
    entry.entry_type = new_type
    entry.description = description
    session.commit()
    return Response(status_code=204, headers={"HX-Redirect": f"/trade/vouchers/{entry.id}"})


@router.post("/vouchers/{entry_id}/reverse")
async def voucher_reverse(
    entry_id: int,
    reason: str = Form("Reversed by user"),
    session: Session = Depends(get_session),
):
    from services.posting import PostingEngine
    PostingEngine.reverse(session, DEFAULT_USER_ID, entry_id, reason=reason)
    return _close_modal()


@router.post("/vouchers/{entry_id}/delete")
async def voucher_delete(entry_id: int, session: Session = Depends(get_session)):
    """Hard-delete a voucher: removes the journal entry and its lines, plus
    any reversal entry that pointed at it. Refuses if the entry is linked to
    a trade — those must be managed from the trade page (cancel / delete trade)."""
    from models import JournalEntry
    user_id = DEFAULT_USER_ID
    entry = session.get(JournalEntry, entry_id)
    if not entry or entry.user_id != user_id:
        raise HTTPException(404, "Voucher not found")
    if entry.trade_id is not None:
        raise HTTPException(
            400,
            "This voucher is auto-posted by a trade — cancel or delete the trade instead."
        )
    # Delete any reversal that pointed at this entry.
    reversals = list(session.exec(
        select(JournalEntry).where(JournalEntry.reversal_of_id == entry.id)
    ).all())
    for rev in reversals:
        session.delete(rev)
    session.delete(entry)
    session.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.get("/vouchers/{entry_id}", response_class=HTMLResponse)
async def voucher_detail(request: Request, entry_id: int, session: Session = Depends(get_session)):
    from services.voucher import VoucherService
    data = VoucherService.get_with_lines(session, DEFAULT_USER_ID, entry_id)
    if not data:
        raise HTTPException(404, "Voucher not found")
    return templates.TemplateResponse("trade_voucher_detail.html", _ctx(request, **data))


# ───────── chart of accounts management ────────────────────────────


@router.get("/coa", response_class=HTMLResponse)
async def coa_list(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    account_setup.seed_chart_of_accounts(session, user_id)
    groups = account_setup.list_accounts_grouped(session, user_id)
    all_ids = []
    for g in groups:
        for sb in g["subclasses"]:
            all_ids.extend(a.id for a in sb["accounts"])
        all_ids.extend(a.id for a in g["accounts_without_subclass"])
    from services.ledger import balances_for_accounts
    bals = balances_for_accounts(session, all_ids)
    return templates.TemplateResponse("trade_coa.html", _ctx(request, groups=groups, balances=bals))


@router.get("/coa/new", response_class=HTMLResponse)
async def coa_new_modal(request: Request, session: Session = Depends(get_session)):
    from models import AccountSubClass
    user_id = DEFAULT_USER_ID
    account_setup.seed_chart_of_accounts(session, user_id)
    subclasses = list(session.exec(
        select(AccountSubClass).where(AccountSubClass.user_id == user_id).order_by(AccountSubClass.code)
    ).all())
    return templates.TemplateResponse(
        "trade_coa_modal.html",
        _ctx(request, account=None, action="/trade/coa", subclasses=subclasses),
    )


@router.get("/coa/{account_id}/edit", response_class=HTMLResponse)
async def coa_edit_modal(request: Request, account_id: int, session: Session = Depends(get_session)):
    from models import Account
    a = session.get(Account, account_id)
    if not a or a.user_id != DEFAULT_USER_ID:
        raise HTTPException(404, "Account not found")
    return templates.TemplateResponse(
        "trade_coa_modal.html",
        _ctx(request, account=a, action=f"/trade/coa/{account_id}", subclasses=None),
    )


@router.post("/coa")
async def coa_create(
    name: str = Form(...),
    subclass_code: str = Form(...),
    description: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    try:
        account_setup.create_account(
            session, DEFAULT_USER_ID,
            name=name.strip(), subclass_code=subclass_code,
            description=(description or "").strip() or None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _close_modal()


@router.post("/coa/{account_id}")
async def coa_update(
    account_id: int,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    account_setup.update_account(
        session, DEFAULT_USER_ID, account_id,
        name=name.strip(), description=(description or "").strip() or None,
    )
    return _close_modal()


@router.post("/coa/{account_id}/delete")
async def coa_disable(account_id: int, session: Session = Depends(get_session)):
    account_setup.soft_disable_account(session, DEFAULT_USER_ID, account_id)
    return _close_modal()


# ───────── reports ──────────────────────────────────────────────


@router.get("/reports", response_class=HTMLResponse)
async def reports_index(request: Request):
    return templates.TemplateResponse("trade_reports_index.html", _ctx(request))


@router.get("/testing", response_class=HTMLResponse)
async def testing_page(request: Request):
    return templates.TemplateResponse("trade_testing.html", _ctx(request))


@router.get("/reports/sales", response_class=HTMLResponse)
async def reports_sales(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    report = TradeReportService.sales_report(
        session, user_id, _parse_date(date_from), _parse_date(date_to)
    )
    return templates.TemplateResponse(
        "trade_report_sales.html",
        _ctx(request, report=report, date_from=date_from or "", date_to=date_to or ""),
    )


@router.get("/reports/ledger", response_class=HTMLResponse)
async def reports_ledger(
    request: Request,
    party_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    parties = PartyService.list(session, user_id)
    ledger = None
    if party_id:
        ledger = TradeReportService.party_ledger(
            session, user_id, party_id, _parse_date(date_from), _parse_date(date_to)
        )
    return templates.TemplateResponse(
        "trade_report_ledger.html",
        _ctx(
            request,
            parties=parties,
            ledger=ledger,
            party_id=party_id,
            date_from=date_from or "",
            date_to=date_to or "",
        ),
    )


@router.get("/reports/items", response_class=HTMLResponse)
async def reports_items(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    rows = TradeReportService.item_report(
        session, user_id, _parse_date(date_from), _parse_date(date_to)
    )
    return templates.TemplateResponse(
        "trade_report_items.html",
        _ctx(request, rows=rows, date_from=date_from or "", date_to=date_to or ""),
    )


@router.get("/reports/trial-balance", response_class=HTMLResponse)
async def reports_trial_balance(
    request: Request,
    as_of: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    from services.ledger import trial_balance as _tb
    report = _tb(session, user_id, as_of=_parse_date(as_of))
    return templates.TemplateResponse(
        "trade_report_trial_balance.html",
        _ctx(request, report=report, as_of=as_of or "", today=date.today()),
    )


@router.get("/reports/general-ledger", response_class=HTMLResponse)
async def reports_general_ledger(
    request: Request,
    account_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from models import Account as _A
    user_id = DEFAULT_USER_ID
    accounts = list(session.exec(
        select(_A).where(_A.user_id == user_id, _A.is_active == True).order_by(_A.code)  # noqa: E712
    ).all())
    led = None
    if account_id:
        from services.ledger import account_ledger
        led = account_ledger(session, account_id, from_date=_parse_date(date_from), to_date=_parse_date(date_to))
    return templates.TemplateResponse(
        "trade_report_general_ledger.html",
        _ctx(request, accounts=accounts, ledger=led, account_id=account_id,
             date_from=date_from or "", date_to=date_to or ""),
    )


@router.get("/reports/pnl", response_class=HTMLResponse)
async def reports_pnl(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from services.ledger import profit_and_loss
    rpt = profit_and_loss(session, DEFAULT_USER_ID, from_date=_parse_date(date_from), to_date=_parse_date(date_to))
    return templates.TemplateResponse(
        "trade_report_pnl.html",
        _ctx(request, report=rpt, date_from=date_from or "", date_to=date_to or ""),
    )


@router.get("/reports/balance-sheet", response_class=HTMLResponse)
async def reports_balance_sheet(
    request: Request,
    as_of: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from services.ledger import balance_sheet
    rpt = balance_sheet(session, DEFAULT_USER_ID, as_of=_parse_date(as_of))
    return templates.TemplateResponse(
        "trade_report_balance_sheet.html",
        _ctx(request, report=rpt, as_of=as_of or "", today=date.today()),
    )


@router.get("/reports/cashbook", response_class=HTMLResponse)
async def reports_cashbook(
    request: Request,
    account_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from models import Account as _A, AccountSubClass as _ASC
    user_id = DEFAULT_USER_ID
    sub = session.exec(
        select(_ASC).where(_ASC.user_id == user_id, _ASC.code == "1100")
    ).first()
    cash_accounts = []
    if sub:
        cash_accounts = list(session.exec(
            select(_A).where(_A.user_id == user_id, _A.subclass_id == sub.id, _A.is_active == True)  # noqa: E712
        ).all())
    selected_ids = [account_id] if account_id else [a.id for a in cash_accounts]
    from services.ledger import cashbook
    book = cashbook(session, user_id, selected_ids, from_date=_parse_date(date_from), to_date=_parse_date(date_to))
    return templates.TemplateResponse(
        "trade_report_cashbook.html",
        _ctx(request, cash_accounts=cash_accounts, book=book,
             account_id=account_id, date_from=date_from or "", date_to=date_to or ""),
    )


@router.get("/reports/day-book", response_class=HTMLResponse)
async def reports_day_book(
    request: Request,
    on_date: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    d = _parse_date(on_date) or date.today()
    from services.ledger import day_book
    rows = day_book(session, DEFAULT_USER_ID, d)
    return templates.TemplateResponse(
        "trade_report_day_book.html",
        _ctx(request, rows=rows, on_date=d, today=date.today()),
    )


@router.get("/reports/cash-flow", response_class=HTMLResponse)
async def reports_cash_flow(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from services.analytics import cash_flow_statement
    r = cash_flow_statement(session, DEFAULT_USER_ID, _parse_date(date_from), _parse_date(date_to))
    return templates.TemplateResponse(
        "trade_report_cash_flow.html",
        _ctx(request, report=r, date_from=date_from or "", date_to=date_to or ""),
    )


@router.get("/reports/cashflow-management", response_class=HTMLResponse)
async def reports_cashflow_management(
    request: Request,
    horizon: int = Query(120),
    inject: float = Query(0),
    inject_on: str = Query(None),
    session: Session = Depends(get_session),
):
    from services.analytics import cash_flow_management
    # What-if slider overrides arrive as query params d_<party_id>=<days>. They
    # only preview — nothing is saved unless the user clicks Save (POST below).
    overrides = {}
    for k, v in request.query_params.items():
        if k.startswith("d_"):
            try:
                overrides[int(k[2:])] = max(0, min(60, int(float(v))))
            except (ValueError, TypeError):
                pass
    r = cash_flow_management(
        session, DEFAULT_USER_ID, horizon_days=max(30, min(365, horizon)),
        inject_amount=(inject if inject and inject > 0 else None),
        inject_on=_parse_date(inject_on),
        delay_overrides=overrides or None,
    )
    return templates.TemplateResponse(
        "trade_report_cashflow_management.html", _ctx(request, report=r),
    )


@router.post("/reports/cashflow-management/delays")
async def reports_cashflow_save_delays(
    request: Request,
    session: Session = Depends(get_session),
):
    """Persist the vendor max-payment-delay sliders as each party's stored default."""
    form = await request.form()
    for k, v in form.items():
        if not k.startswith("d_"):
            continue
        try:
            pid = int(k[2:]); days = max(0, min(60, int(float(v))))
        except (ValueError, TypeError):
            continue
        p = session.get(Party, pid)
        if p and p.user_id == DEFAULT_USER_ID:
            p.max_payment_delay_days = days
            session.add(p)
    session.commit()
    return RedirectResponse("/trade/reports/cashflow-management", status_code=303)


@router.post("/reports/cashflow-management/expected-date")
async def reports_cashflow_set_expected_date(
    trade_id: int = Form(...),
    expected_date: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    """Owner sets (or clears) the expected arrival date for goods still on order,
    so Cash Flow Management schedules that trade's supply payment from this date
    instead of guessing from vendor history."""
    from models import Trade
    t = session.get(Trade, trade_id)
    if t and t.user_id == DEFAULT_USER_ID:
        t.expected_delivery_date = _parse_date(expected_date)
        session.add(t)
        session.commit()
    return RedirectResponse("/trade/reports/cashflow-management", status_code=303)


@router.get("/reports/customer-profitability", response_class=HTMLResponse)
async def reports_customer_profitability(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from services.analytics import customer_profitability
    r = customer_profitability(session, DEFAULT_USER_ID, _parse_date(date_from), _parse_date(date_to))
    return templates.TemplateResponse(
        "trade_report_customer_profitability.html",
        _ctx(request, report=r, date_from=date_from or "", date_to=date_to or ""),
    )


@router.get("/reports/vendor-performance", response_class=HTMLResponse)
async def reports_vendor_performance(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from services.analytics import vendor_performance
    r = vendor_performance(session, DEFAULT_USER_ID, _parse_date(date_from), _parse_date(date_to))
    return templates.TemplateResponse(
        "trade_report_vendor_performance.html",
        _ctx(request, report=r, date_from=date_from or "", date_to=date_to or ""),
    )


@router.get("/reports/item-profitability", response_class=HTMLResponse)
async def reports_item_profitability(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    by_spec: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from services.analytics import item_profitability
    r = item_profitability(session, DEFAULT_USER_ID, _parse_date(date_from), _parse_date(date_to), group_by_spec=bool(by_spec))
    return templates.TemplateResponse(
        "trade_report_item_profitability.html",
        _ctx(request, report=r, date_from=date_from or "", date_to=date_to or "", by_spec=bool(by_spec)),
    )


@router.get("/reports/working-capital", response_class=HTMLResponse)
async def reports_working_capital(
    request: Request,
    as_of: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from services.analytics import working_capital_metrics, capital_utilization
    metrics = working_capital_metrics(session, DEFAULT_USER_ID, as_of=_parse_date(as_of))
    cap = capital_utilization(session, DEFAULT_USER_ID, as_of=_parse_date(as_of))
    return templates.TemplateResponse(
        "trade_report_working_capital.html",
        _ctx(request, metrics=metrics, capital=cap, as_of=as_of or ""),
    )


@router.get("/reports/forecast", response_class=HTMLResponse)
async def reports_forecast(request: Request, session: Session = Depends(get_session)):
    from services.analytics import bank_position_forecast
    r = bank_position_forecast(session, DEFAULT_USER_ID, net_prepaid=True)
    return templates.TemplateResponse("trade_report_forecast.html", _ctx(request, report=r))


@router.get("/reports/daily-cash", response_class=HTMLResponse)
async def reports_daily_cash(
    request: Request, days: int = Query(30), session: Session = Depends(get_session)
):
    from services.analytics import daily_cash_requirement
    days = max(7, min(int(days or 30), 120))
    r = daily_cash_requirement(session, DEFAULT_USER_ID, horizon_days=days)
    return templates.TemplateResponse("trade_report_daily_cash.html", _ctx(request, report=r, days=days))


# ═════════════════════════════════════════════════════════════════
# Order Projection — plan a batch of orders, see day-wise cash needed
# ═════════════════════════════════════════════════════════════════


@router.get("/projection", response_class=HTMLResponse)
async def projection_page(request: Request, session: Session = Depends(get_session)):
    from services.analytics import order_projection
    report = order_projection(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "trade_projection.html", _ctx(request, report=report, today=date.today()),
    )


@router.post("/projection", response_class=HTMLResponse)
async def projection_save(request: Request, session: Session = Depends(get_session)):
    """Upsert every order line from the editable table, recompute, and return the
    live results partial (headline tiles + day-by-day table) so the page updates
    without a full reload. Newly-created rows get their id echoed back via an
    out-of-band hidden input so the next auto-save updates in place (no dupes)."""
    from models import ProjectionLine
    from services.analytics import order_projection
    user_id = DEFAULT_USER_ID
    form = await request.form()
    idxs = sorted({int(k.split("_")[1]) for k in form.keys()
                   if k.startswith("pline_") and k.endswith("_item_name")})
    created = {}  # idx -> new ProjectionLine (needs id echoed back)
    for i in idxs:
        name = (form.get(f"pline_{i}_item_name") or "").strip()
        if not name:
            continue
        raw_id = form.get(f"pline_{i}_id")
        data = dict(
            item_name=name,
            group_name=(form.get(f"pline_{i}_group") or "Dabbi").strip() or "Dabbi",
            quantity=_parse_decimal(form.get(f"pline_{i}_quantity"), "0"),
            purchase_rate=_parse_decimal(form.get(f"pline_{i}_purchase_rate"), "0"),
            party_old_rate=_parse_decimal(form.get(f"pline_{i}_party_old_rate"), "0"),
            sale_rate=_parse_decimal(form.get(f"pline_{i}_sale_rate"), "0"),
            dye_block_cost=_parse_decimal(form.get(f"pline_{i}_dye_block_cost"), "0"),
            bilty=_parse_decimal(form.get(f"pline_{i}_bilty"), "0"),
            order_date=_parse_date(form.get(f"pline_{i}_order_date")),
            lead_days=int(_parse_decimal(form.get(f"pline_{i}_lead_days"), "15")),
            collection_lag_days=int(_parse_decimal(form.get(f"pline_{i}_collection_lag_days"), "30")),
            pct_advance=_parse_decimal(form.get(f"pline_{i}_pct_advance"), "0"),
            pct_on_delivery=_parse_decimal(form.get(f"pline_{i}_pct_on_delivery"), "0"),
            pct_credit=_parse_decimal(form.get(f"pline_{i}_pct_credit"), "0"),
            credit_days=int(_parse_decimal(form.get(f"pline_{i}_credit_days"), "30")),
            include=bool(form.get(f"pline_{i}_include")),
            dye_active=bool(form.get(f"pline_{i}_dye_active")),
            sort_order=i,
        )
        if raw_id and raw_id.isdigit():
            ln = session.get(ProjectionLine, int(raw_id))
            if ln and ln.user_id == user_id:
                for k, val in data.items():
                    setattr(ln, k, val)
                ln.updated_at = datetime.utcnow()
                session.add(ln)
                continue
        ln = ProjectionLine(user_id=user_id, **data)
        session.add(ln)
        created[i] = ln
    session.commit()
    id_echoes = [{"idx": i, "id": ln.id} for i, ln in created.items()]
    report = order_projection(session, user_id)
    return templates.TemplateResponse(
        "trade_projection_update.html",
        _ctx(request, report=report, id_echoes=id_echoes),
    )


@router.post("/projection/import-sheet")
async def projection_import_sheet(request: Request, session: Session = Depends(get_session)):
    """Pull products from the 'fleure boxes' Numbers sheet (Table 1) and upsert
    projection lines by product name. Requires the app to run on the Mac that has
    Numbers; no-op with a friendly message otherwise."""
    from services.projection_sheet import import_fleure_boxes
    try:
        n = import_fleure_boxes(session, DEFAULT_USER_ID)
        msg = f"Synced {n} product(s) from the fleure boxes sheet."
    except Exception as exc:  # noqa: BLE001 - surface any AppleScript/parse failure
        msg = f"Couldn't read the sheet: {exc}"
    return Response(status_code=204, headers={
        "HX-Redirect": "/trade/projection",
        "X-Sync-Message": msg[:200],
    })


@router.post("/projection/lines/{line_id}/delete")
async def projection_delete_line(line_id: int, session: Session = Depends(get_session)):
    from models import ProjectionLine
    ln = session.get(ProjectionLine, line_id)
    if ln and ln.user_id == DEFAULT_USER_ID:
        session.delete(ln)
        session.commit()
    return Response(status_code=204)


@router.get("/reports/trade-profitability", response_class=HTMLResponse)
async def reports_trade_profitability(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from services.analytics import trade_profitability
    r = trade_profitability(session, DEFAULT_USER_ID, _parse_date(date_from), _parse_date(date_to))
    return templates.TemplateResponse(
        "trade_report_trade_profitability.html",
        _ctx(request, report=r, date_from=date_from or "", date_to=date_to or ""),
    )


@router.get("/reports/aging", response_class=HTMLResponse)
async def reports_aging(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    report = TradeReportService.aging_report(session, user_id)
    return templates.TemplateResponse(
        "trade_report_aging.html", _ctx(request, report=report, today=date.today())
    )


@router.get("/reports/ap-aging", response_class=HTMLResponse)
async def reports_ap_aging(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    report = TradeReportService.ap_aging_report(session, user_id)
    return templates.TemplateResponse(
        "trade_report_ap_aging.html", _ctx(request, report=report, today=date.today())
    )


@router.get("/reports/pending-receivables", response_class=HTMLResponse)
async def reports_pending_receivables(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    report = TradeReportService.pending_receivables(session, user_id)
    return templates.TemplateResponse(
        "trade_report_pending_receivables.html",
        _ctx(request, report=report, today=report["today"]),
    )


@router.get("/reports/vendor-pending", response_class=HTMLResponse)
async def reports_vendor_pending(
    request: Request, vendor_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    """Goods still owed by a single vendor — pick a vendor, then export a PDF
    statement to send them (qty, order date, agreed price, pending value)."""
    user_id = DEFAULT_USER_ID
    vendors = PartyService.list_vendors(session, user_id)
    selected = None
    if vendor_id:
        report = TradeReportService.pending_receivables(session, user_id)
        selected = next((v for v in report["vendors"] if v["vendor_id"] == vendor_id), None)
        if selected is None:
            v = PartyService.get(session, user_id, vendor_id)
            selected = {"vendor_id": vendor_id, "vendor_name": v.name if v else "—",
                        "trades": [], "pending_value": Decimal("0"), "pending_qty": Decimal("0")}
    return templates.TemplateResponse(
        "trade_report_vendor_pending.html",
        _ctx(request, vendors=vendors, selected=selected,
             selected_id=vendor_id, today=date.today()),
    )


@router.get("/reports/vendor-pending/{vendor_id}.pdf")
async def reports_vendor_pending_pdf(vendor_id: int, session: Session = Depends(get_session)):
    from io import BytesIO
    from services.pdf_helper import (
        render_report_pdf, ReportSpec, KpiSpec, TableSpec, SectionTitle, ParagraphBlock, CalloutCard,
    )
    user_id = DEFAULT_USER_ID
    vendor = PartyService.get(session, user_id, vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found")
    report = TradeReportService.pending_receivables(session, user_id)
    v = next((x for x in report["vendors"] if x["vendor_id"] == vendor_id), None)

    def pkr(x):
        try: return f"Rs. {Decimal(str(x)):,.2f}"
        except Exception: return f"Rs. {x}"

    # Group every pending line by BRAND (from its spec map).
    by_brand: dict[str, list] = {}
    total_qty = Decimal("0")
    total_val = Decimal("0")
    if v:
        for tr in v["trades"]:
            for ln in tr["lines"]:
                sm = ln.get("specs_map", {})
                # The brand is the Brand spec if set, else the customer/purchaser
                # name (each customer is effectively a brand in this business).
                brand = sm.get("brand") or tr.get("customer_name") or "Unspecified brand"
                by_brand.setdefault(brand, []).append((tr, ln, sm))
                total_qty += Decimal(ln["pending_qty"])
                total_val += Decimal(ln["pending_value"])

    def qty(x):
        return f"{float(x):,g}"

    sections = [
        SectionTitle("Statement To"),
        ParagraphBlock("<br/>".join(filter(None, [
            f"<b>{vendor.name}</b>",
            vendor.contact_person or "",
            (f"Phone: {vendor.phone}" if vendor.phone else ""),
            (vendor.city or ""),
        ]))),
        SectionTitle("Goods Still To Be Delivered — by Brand"),
    ]
    if not by_brand:
        sections.append(ParagraphBlock("<i>Nothing pending from this vendor — all ordered goods delivered.</i>"))
    for brand in sorted(by_brand):
        rows = []
        b_qty = Decimal("0")
        b_val = Decimal("0")
        for tr, ln, sm in by_brand[brand]:
            # Item NAME in bold, full spec line (size, colours, micron…) beneath.
            specs_line = " · ".join(f"{k}: {val}" for k, val in sm.items() if k != "brand" and val)
            item_html = f"<b><font size='9.5'>{ln['item_name']}</font></b>"
            if specs_line:
                item_html += f"<br/><font color='#65675e' size='8'>{specs_line}</font>"
            rows.append([
                item_html,
                tr["trade_date"].strftime("%d-%b-%Y") if tr["trade_date"] else "—",
                qty(ln["ordered_qty"]),
                qty(ln["received_qty"]),
                qty(ln["pending_qty"]),
                pkr(ln["unit_cost"]),
                pkr(ln["pending_value"]),
            ])
            b_qty += Decimal(ln["pending_qty"])
            b_val += Decimal(ln["pending_value"])
        sections.append(SectionTitle(f"Brand: {brand}", keep_with_next=True))
        sections.append(TableSpec(
            headers=["Item", "Order Date", "Ordered", "Received", "Pending", "Rate", "Pending Value"],
            rows=rows,
            col_widths=[150, 62, 52, 55, 52, 48, 78],
            num_cols={2, 3, 4, 5, 6},
            totals_row=["", "", "", "", qty(b_qty), "Subtotal", pkr(b_val)],
        ))
    sections.append(CalloutCard(label="Total Pending Value", value=pkr(total_val),
                                suffix="Kindly arrange delivery of the above at the earliest."))

    buf = BytesIO()
    render_report_pdf(buf, ReportSpec(
        title="Pending Goods Statement",
        subtitle_parts=[f"Vendor: {vendor.name}", f"As of {date.today().strftime('%B %d, %Y')}"],
        kpis=[
            KpiSpec("Pending Value", pkr(total_val)),
            KpiSpec("Pending Qty", f"{qty(total_qty)} pcs"),
            KpiSpec("Open Trades", str(len(v["trades"]) if v else 0)),
        ],
        sections=sections,
        footer_subtitle="Ibrahim Traders · pending goods",
        generated_label="As of",
        brand="IBRAHIM TRADERS",
    ))
    fname = f"Pending-Goods-{vendor.name.replace(' ','_')}.pdf"
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.get("/reports/customer-pending", response_class=HTMLResponse)
async def reports_customer_pending(
    request: Request, customer_id: Optional[int] = Query(None),
    item_id: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """Goods we still owe to DELIVER to a single customer — pick a customer (and
    optionally an item), then export a delivery-pending list."""
    user_id = DEFAULT_USER_ID
    item_id = int(item_id) if (item_id and str(item_id).strip().isdigit()) else None
    customers = PartyService.list_customers(session, user_id)
    selected = None
    items = []
    if customer_id:
        report = TradeReportService.customer_pending_goods(session, user_id)
        selected = next((c for c in report["customers"] if c["customer_id"] == customer_id), None)
        if selected is None:
            c = PartyService.get(session, user_id, customer_id)
            selected = {"customer_id": customer_id, "customer_name": c.name if c else "—",
                        "trades": [], "pending_value": Decimal("0"), "pending_qty": Decimal("0"),
                        "trade_count": 0}
        else:
            # distinct items in this customer's pending goods (for the item filter)
            seen = {}
            for tr in selected["trades"]:
                for ln in tr["lines"]:
                    if ln.get("item_id") and ln["item_id"] not in seen:
                        seen[ln["item_id"]] = ln["item_name"]
            items = sorted(({"id": k, "name": v} for k, v in seen.items()), key=lambda x: x["name"])
            if item_id:
                selected = _filter_pending_by_item(selected, item_id)
    return templates.TemplateResponse(
        "trade_report_customer_pending.html",
        _ctx(request, customers=customers, selected=selected, items=items,
             selected_id=customer_id, selected_item=item_id, today=date.today()),
    )


def _filter_pending_by_item(selected: dict, item_id: int) -> dict:
    """Keep only lines for the given item; recompute per-trade and customer totals."""
    trades = []
    tot_val = Decimal("0")
    tot_qty = Decimal("0")
    for tr in selected["trades"]:
        lines = [ln for ln in tr["lines"] if ln.get("item_id") == item_id]
        if not lines:
            continue
        pv = sum((Decimal(ln["pending_value"]) for ln in lines), Decimal("0"))
        pq = sum((Decimal(ln["pending_qty"]) for ln in lines), Decimal("0"))
        trades.append({**tr, "lines": lines,
                       "pending_value": pv.quantize(Decimal("0.01")),
                       "pending_qty": pq.quantize(Decimal("0.001"))})
        tot_val += pv
        tot_qty += pq
    return {**selected, "trades": trades,
            "pending_value": tot_val.quantize(Decimal("0.01")),
            "pending_qty": tot_qty.quantize(Decimal("0.001")),
            "trade_count": len(trades)}


@router.get("/reports/customer-pending/{customer_id}.pdf")
async def reports_customer_pending_pdf(
    customer_id: int, item_id: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from io import BytesIO
    from services.pdf_helper import (
        render_report_pdf, ReportSpec, KpiSpec, TableSpec, SectionTitle, ParagraphBlock, CalloutCard,
    )
    user_id = DEFAULT_USER_ID
    customer = PartyService.get(session, user_id, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    report = TradeReportService.customer_pending_goods(session, user_id)
    c = next((x for x in report["customers"] if x["customer_id"] == customer_id), None)
    _iid = int(item_id) if (item_id and str(item_id).strip().isdigit()) else None
    if c and _iid:
        c = _filter_pending_by_item(c, _iid)

    def pkr(x):
        try: return f"Rs. {Decimal(str(x)):,.2f}"
        except Exception: return f"Rs. {x}"

    def qty(x):
        return f"{float(x):,g}"

    # Group every pending line by BRAND (from its spec map), same as the vendor
    # statement, so a delivery/packing list reads brand-by-brand.
    by_brand: dict[str, list] = {}
    total_qty = Decimal("0")
    total_val = Decimal("0")
    if c:
        for tr in c["trades"]:
            for ln in tr["lines"]:
                sm = ln.get("specs_map", {})
                brand = sm.get("brand") or customer.name or "Unspecified brand"
                by_brand.setdefault(brand, []).append((tr, ln, sm))
                total_qty += Decimal(ln["pending_qty"])
                total_val += Decimal(ln["pending_value"])

    sections = [
        SectionTitle("Deliver To"),
        ParagraphBlock("<br/>".join(filter(None, [
            f"<b>{customer.name}</b>",
            customer.contact_person or "",
            (f"Phone: {customer.phone}" if customer.phone else ""),
            (customer.city or ""),
        ]))),
        SectionTitle("Goods Still To Be Delivered — by Brand"),
    ]
    if not by_brand:
        sections.append(ParagraphBlock("<i>Nothing pending for this customer — everything ordered has been delivered.</i>"))
    for brand in sorted(by_brand):
        rows = []
        b_qty = Decimal("0")
        b_val = Decimal("0")
        for tr, ln, sm in by_brand[brand]:
            # Item NAME in bold, with the full spec line (size, colours, micron…)
            # underneath — this statement goes to the customer, who ordered by
            # product name.
            specs_line = " · ".join(f"{k}: {val}" for k, val in sm.items() if k != "brand" and val)
            item_html = f"<b><font size='9.5'>{ln['item_name']}</font></b>"
            if specs_line:
                item_html += f"<br/><font color='#65675e' size='8'>{specs_line}</font>"
            rows.append([
                item_html,
                tr["trade_date"].strftime("%d-%b-%Y") if tr["trade_date"] else "—",
                qty(ln["ordered_qty"]),
                qty(ln["received_qty"]),
                qty(ln["pending_qty"]),
                pkr(ln["unit_price"]),
                pkr(ln["pending_value"]),
            ])
            b_qty += Decimal(ln["pending_qty"])
            b_val += Decimal(ln["pending_value"])
        sections.append(SectionTitle(f"Brand: {brand}", keep_with_next=True))
        sections.append(TableSpec(
            headers=["Item", "Order Date", "Ordered", "Delivered", "Pending", "Rate", "Pending Value"],
            rows=rows,
            col_widths=[150, 62, 52, 55, 52, 48, 78],
            num_cols={2, 3, 4, 5, 6},
            totals_row=["", "", "", "", qty(b_qty), "Subtotal", pkr(b_val)],
        ))
    sections.append(CalloutCard(label="Total Pending Value", value=pkr(total_val),
                                suffix="The goods above are yet to be dispatched to you — we'll deliver them shortly."))

    buf = BytesIO()
    render_report_pdf(buf, ReportSpec(
        title="Pending Deliveries",
        subtitle_parts=[f"Customer: {customer.name}", f"As of {date.today().strftime('%B %d, %Y')}"],
        kpis=[
            KpiSpec("Pending Value", pkr(total_val)),
            KpiSpec("Pending Qty", f"{qty(total_qty)} pcs"),
            KpiSpec("Open Trades", str(len(c["trades"]) if c else 0)),
        ],
        sections=sections,
        footer_subtitle="Ibrahim Traders · pending deliveries",
        generated_label="As of",
        brand="IBRAHIM TRADERS",
    ))
    fname = f"Pending-Deliveries-{customer.name.replace(' ','_')}.pdf"
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.get("/reports/goods-sent", response_class=HTMLResponse)
async def reports_goods_sent(
    request: Request, customer_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """Dated goods-sent (dispatch) statement for a customer, grouped by PO (trade)."""
    user_id = DEFAULT_USER_ID
    customers = PartyService.list_customers(session, user_id)
    report = None
    if customer_id:
        report = TradeReportService.goods_sent_report(
            session, user_id, customer_id,
            from_date=_parse_date(date_from), to_date=_parse_date(date_to))
    return templates.TemplateResponse(
        "trade_report_goods_sent.html",
        _ctx(request, customers=customers, report=report,
             selected_id=customer_id, date_from=date_from or "", date_to=date_to or "",
             today=date.today()),
    )


@router.get("/reports/goods-sent/{customer_id}.pdf")
async def reports_goods_sent_pdf(
    customer_id: int, date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    from io import BytesIO
    from services.pdf_helper import (
        render_report_pdf, ReportSpec, KpiSpec, TableSpec, SectionTitle, ParagraphBlock, CalloutCard,
    )
    user_id = DEFAULT_USER_ID
    customer = PartyService.get(session, user_id, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    df = _parse_date(date_from); dt = _parse_date(date_to)
    report = TradeReportService.goods_sent_report(session, user_id, customer_id, from_date=df, to_date=dt)

    def qty(x):
        return f"{float(x):,g}"

    period = "All dates"
    if df or dt:
        period = f"{df.strftime('%d-%b-%Y') if df else '…'} → {dt.strftime('%d-%b-%Y') if dt else '…'}"

    sections = [
        SectionTitle("Sent To"),
        ParagraphBlock("<br/>".join(filter(None, [
            f"<b>{customer.name}</b>",
            customer.contact_person or "",
            (f"Phone: {customer.phone}" if customer.phone else ""),
            (customer.city or ""),
        ]))),
        SectionTitle("Order vs Delivery — by PO"),
    ]
    if not report["pos"]:
        sections.append(ParagraphBlock("<i>No goods dispatched to this customer in the selected period.</i>"))
    for po in report["pos"]:
        po_bits = [f"ordered {qty(po['ordered'])}", f"sent {qty(po['sent'])}"]
        if po["pending"] > 0:
            po_bits.append(f"pending {qty(po['pending'])}")
        if po["overflow"] > 0:
            po_bits.append(f"over {qty(po['overflow'])}")
        po_title = (f"PO #{po['po_no']} — ordered "
                    f"{po['trade_date'].strftime('%d-%b-%Y') if po['trade_date'] else '—'}"
                    f"   ({' · '.join(po_bits)})")
        sections.append(SectionTitle(po_title, keep_with_next=True))
        for it in po["items"]:
            hdr = (f"<b><font size='9.5'>{it['item_name']}</font></b>"
                   f" &nbsp;<font color='#4338ca' size='8.5'>Ordered {qty(it['ordered'])} {it['unit']}</font>")
            if it["specs"]:
                hdr += f"<br/><font color='#65675e' size='8'>{it['specs']}</font>"
            sections.append(ParagraphBlock(hdr))
            rows = []
            if it["prior_count"]:
                rows.append([f"{it['prior_count']} earlier (before period)", "", f"-{qty(it['prior_qty'])}"])
            for dv in it["deliveries"]:
                rows.append([dv["date"].strftime("%d-%b-%Y"), qty(dv["qty"]), qty(dv["remaining"])])
            if it["pending"] > 0:
                close = f"Pending {qty(it['pending'])}"
            elif it["overflow"] > 0:
                close = f"Over-delivered {qty(it['overflow'])}"
            else:
                close = "Complete"
            sections.append(TableSpec(
                headers=["Sent On", "Quantity", "Remaining"],
                rows=rows, col_widths=[170, 120, 120], num_cols={1, 2},
                totals_row=[f"Delivered {qty(it['delivered'])}", "", close],
            ))
    sections.append(CalloutCard(
        label="For the period",
        value=f"{qty(report['total_qty'])} pcs sent",
        suffix=(f"of {qty(report['total_ordered'])} pcs ordered · "
                f"{qty(report['total_pending'])} pcs still to deliver"
                + (f" · {qty(report['total_overflow'])} pcs over-delivered" if report['total_overflow'] > 0 else "")
                + ".")))

    buf = BytesIO()
    render_report_pdf(buf, ReportSpec(
        title="Goods Sent Statement",
        subtitle_parts=[f"Customer: {customer.name}", f"Period: {period}"],
        kpis=[
            KpiSpec("Ordered", f"{qty(report['total_ordered'])} pcs"),
            KpiSpec("Sent", f"{qty(report['total_qty'])} pcs"),
            KpiSpec("Pending", f"{qty(report['total_pending'])} pcs"),
            KpiSpec("Over-delivered", f"{qty(report['total_overflow'])} pcs"),
        ],
        sections=sections,
        footer_subtitle="Ibrahim Traders · goods sent",
        generated_label="Generated",
        brand="IBRAHIM TRADERS",
    ))
    fname = f"Goods-Sent-{customer.name.replace(' ', '_')}.pdf"
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}"'})


@router.get("/reports/expenses", response_class=HTMLResponse)
async def reports_expenses(
    request: Request,
    date_from: Optional[str] = Query(None), date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """All expense vouchers except bilties, dated, with a per-category summary.

    Defaults to the CURRENT MONTH on first load (no dates given)."""
    user_id = DEFAULT_USER_ID
    if not date_from and not date_to:
        today = date.today()
        first = today.replace(day=1)
        nxt = date(today.year + 1, 1, 1) if today.month == 12 else date(today.year, today.month + 1, 1)
        date_from = first.isoformat()
        date_to = (nxt - timedelta(days=1)).isoformat()
    report = TradeReportService.expenses_report(
        session, user_id, from_date=_parse_date(date_from), to_date=_parse_date(date_to))
    return templates.TemplateResponse(
        "trade_report_expenses.html",
        _ctx(request, report=report, date_from=date_from or "", date_to=date_to or ""),
    )


@router.get("/reports/bilty", response_class=HTMLResponse)
async def reports_bilty(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    """Bilty report — every active bilty row with kgs / terminal / amount / paid-by-customer."""
    from models import TradeBilty, TradeTerminal, JournalEntry, Trade, Party
    user_id = DEFAULT_USER_ID
    df = _parse_date(date_from)
    dt = _parse_date(date_to)
    q = select(TradeBilty).where(TradeBilty.user_id == user_id)
    if df: q = q.where(TradeBilty.delivery_date >= df)
    if dt: q = q.where(TradeBilty.delivery_date <= dt)
    q = q.order_by(TradeBilty.delivery_date.desc(), TradeBilty.id.desc())
    bilties = list(session.exec(q).all())

    rows: list[dict] = []
    total_amount = Decimal("0")
    total_kgs = Decimal("0")
    total_by_cust = Decimal("0")
    total_pieces = Decimal("0")
    for b in bilties:
        je = session.get(JournalEntry, b.journal_entry_id)
        if not je or je.is_reversed:
            continue
        amt = next((Decimal(ln.debit) for ln in je.lines if Decimal(ln.debit) > 0), Decimal("0"))
        trade = session.get(Trade, b.trade_id)
        purchaser = session.get(Party, trade.purchaser_id) if trade else None
        term = session.get(TradeTerminal, b.terminal_id) if b.terminal_id else None
        # Pieces this bilty covers = qty delivered for this trade on this date.
        pieces = Decimal("0")
        if trade:
            for ln in trade.lines:
                for r in (ln.receipts or []):
                    if r.received_on == b.delivery_date:
                        pieces += Decimal(r.received_qty)
        per_pc = (amt / pieces) if pieces > 0 else None
        rows.append({
            "delivery_date": b.delivery_date,
            "trade_ref": trade.reference if trade else "—",
            "trade_id": b.trade_id,
            "customer": purchaser.name if purchaser else "—",
            "customer_city": (purchaser.city if purchaser else None),
            "terminal": term.name if term else None,
            "weight_kgs": b.weight_kgs,
            "amount": amt,
            "pieces": pieces,
            "per_pc": per_pc.quantize(Decimal("0.0001")) if per_pc is not None else None,
            "paid_by_customer": b.paid_by_customer,
            "ref": je.reference,
        })
        total_amount += amt
        if b.weight_kgs: total_kgs += Decimal(b.weight_kgs)
        if b.paid_by_customer: total_by_cust += amt
        total_pieces += pieces

    avg_per_pc = (total_amount / total_pieces).quantize(Decimal("0.0001")) if total_pieces > 0 else None
    return templates.TemplateResponse(
        "trade_report_bilty.html",
        _ctx(
            request,
            rows=rows,
            total_amount=total_amount.quantize(Decimal("0.01")),
            total_kgs=total_kgs,
            total_by_cust=total_by_cust.quantize(Decimal("0.01")),
            total_pieces=total_pieces,
            avg_per_pc=avg_per_pc,
            date_from=date_from or "",
            date_to=date_to or "",
        ),
    )


# ═════════════════════════════════════════════════════════════════
# Quotations
# ═════════════════════════════════════════════════════════════════


@router.get("/quotations", response_class=HTMLResponse)
async def quotations_list(
    request: Request,
    status: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    user_id = DEFAULT_USER_ID
    st = None
    if status:
        try:
            st = QuotationStatus(status)
        except ValueError:
            st = None
    quotations = QuotationService.list(session, user_id, status=st)
    parties_by_id = {p.id: p for p in PartyService.list(session, user_id)}
    return templates.TemplateResponse(
        "trade_quotations.html",
        _ctx(
            request,
            quotations=quotations,
            parties_by_id=parties_by_id,
            current_status=status or "",
            statuses=[s.value for s in QuotationStatus],
            today=date.today(),
        ),
    )


@router.get("/quotations/new", response_class=HTMLResponse)
async def quotation_new_modal(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    return templates.TemplateResponse(
        "trade_quotation_modal.html",
        _ctx(
            request,
            vendors=PartyService.list_vendors(session, user_id),
            customers=PartyService.list_customers(session, user_id),
            items=ItemService.list(session, user_id, active_only=True),
            today=date.today(),
        ),
    )


@router.post("/quotations")
async def quotation_create(request: Request, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    form = await request.form()

    vendor_id = int(form.get("vendor_id") or 0)
    purchaser_id = int(form.get("purchaser_id") or 0)
    if not vendor_id or not purchaser_id:
        raise HTTPException(400, "Vendor and purchaser are required")
    if vendor_id == purchaser_id:
        raise HTTPException(400, "Vendor and purchaser must be different parties")

    customer_terms = int(_parse_decimal(form.get("customer_terms_days"), "30"))
    vendor_terms = int(_parse_decimal(form.get("vendor_terms_days"), "7"))
    quote_date = _parse_date(form.get("quote_date")) or date.today()
    valid_until = _parse_date(form.get("valid_until"))
    notes = (form.get("notes") or "").strip() or None
    terms_text = (form.get("terms_text") or "").strip() or None

    line_indices = sorted({int(k.split("_")[1]) for k in form.keys() if k.startswith("line_") and "_item_name" in k})
    lines: list[dict] = []
    for idx in line_indices:
        name = (form.get(f"line_{idx}_item_name") or "").strip()
        if not name:
            continue
        item_id_raw = form.get(f"line_{idx}_item_id")
        item_id = int(item_id_raw) if item_id_raw else None
        spec_labels = form.getlist(f"line_{idx}_spec_label")
        spec_values = form.getlist(f"line_{idx}_spec_value")
        specs = []
        for lab, val in zip(spec_labels, spec_values):
            if lab.strip() or val.strip():
                specs.append({"label": lab, "value": val})
        lines.append({
            "item_id": item_id,
            "item_name": name,
            "quantity": _parse_decimal(form.get(f"line_{idx}_quantity"), "1"),
            "unit": (form.get(f"line_{idx}_unit") or "pcs").strip(),
            "unit_cost": _parse_decimal(form.get(f"line_{idx}_unit_cost"), "0"),
            "unit_price": _parse_decimal(form.get(f"line_{idx}_unit_price"), "0"),
            "line_notes": (form.get(f"line_{idx}_notes") or "").strip() or None,
            "specs": specs,
        })
    if not lines:
        raise HTTPException(400, "At least one line item is required")

    quo = QuotationService.create(
        session, user_id,
        vendor_id=vendor_id, purchaser_id=purchaser_id,
        customer_terms_days=customer_terms,
        vendor_terms_days=vendor_terms,
        quote_date=quote_date, valid_until=valid_until,
        notes=notes, terms_text=terms_text,
        lines=lines,
    )
    return Response(status_code=204, headers={"HX-Redirect": f"/trade/quotations/{quo.id}"})


@router.get("/quotations/{quotation_id}", response_class=HTMLResponse)
async def quotation_detail(request: Request, quotation_id: int, session: Session = Depends(get_session)):
    user_id = DEFAULT_USER_ID
    quo = QuotationService.get(session, user_id, quotation_id)
    if not quo:
        raise HTTPException(404, "Quotation not found")
    vendor = PartyService.get(session, user_id, quo.vendor_id)
    purchaser = PartyService.get(session, user_id, quo.purchaser_id)
    return templates.TemplateResponse(
        "trade_quotation_detail.html",
        _ctx(
            request,
            quotation=quo,
            vendor=vendor,
            purchaser=purchaser,
            today=date.today(),
        ),
    )


@router.post("/quotations/{quotation_id}/mark-sent")
async def quotation_mark_sent(quotation_id: int, session: Session = Depends(get_session)):
    QuotationService.mark_sent(session, DEFAULT_USER_ID, quotation_id)
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.post("/quotations/{quotation_id}/reject")
async def quotation_reject(quotation_id: int, session: Session = Depends(get_session)):
    QuotationService.mark_rejected(session, DEFAULT_USER_ID, quotation_id)
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.get("/quotations/{quotation_id}/accept-form", response_class=HTMLResponse)
async def quotation_accept_form(
    request: Request, quotation_id: int, session: Session = Depends(get_session),
):
    """Modal asking for the final, negotiated qty / unit cost / unit price
    per line before converting the quote into a Trade."""
    quo = QuotationService.get(session, DEFAULT_USER_ID, quotation_id)
    if not quo:
        raise HTTPException(404, "Quotation not found")
    if quo.trade_id:
        raise HTTPException(400, "This quotation is already linked to a trade")
    return templates.TemplateResponse(
        "trade_quotation_accept_modal.html",
        _ctx(request, quotation=quo),
    )


@router.post("/quotations/{quotation_id}/accept")
async def quotation_accept(
    quotation_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    """Convert quotation → trade. Accepts optional per-line overrides from the
    pre-create modal: qty_<lid>, unit_cost_<lid>, unit_price_<lid>, plus
    customer_terms_days and vendor_terms_days."""
    form = await request.form()
    quo = QuotationService.get(session, DEFAULT_USER_ID, quotation_id)
    if not quo:
        raise HTTPException(404, "Quotation not found")
    line_overrides: dict[int, dict] = {}
    for ln in quo.lines:
        ov: dict = {}
        q = form.get(f"qty_{ln.id}")
        uc = form.get(f"unit_cost_{ln.id}")
        up = form.get(f"unit_price_{ln.id}")
        if q not in (None, ""):
            try: ov["quantity"] = Decimal(str(q))
            except Exception: pass
        if uc not in (None, ""):
            try: ov["unit_cost"] = Decimal(str(uc))
            except Exception: pass
        if up not in (None, ""):
            try: ov["unit_price"] = Decimal(str(up))
            except Exception: pass
        if ov:
            line_overrides[ln.id] = ov
    ct = form.get("customer_terms_days")
    vt = form.get("vendor_terms_days")
    ct_int = int(ct) if ct not in (None, "") else None
    vt_int = int(vt) if vt not in (None, "") else None
    trade = QuotationService.accept(
        session, DEFAULT_USER_ID, quotation_id,
        line_overrides=line_overrides,
        customer_terms_days=ct_int,
        vendor_terms_days=vt_int,
    )
    if not trade:
        raise HTTPException(404, "Quotation not found")
    return Response(status_code=204, headers={"HX-Redirect": f"/trade/trades/{trade.id}"})


@router.post("/quotations/{quotation_id}/delete")
async def quotation_delete(quotation_id: int, session: Session = Depends(get_session)):
    try:
        QuotationService.delete(session, DEFAULT_USER_ID, quotation_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(status_code=204, headers={"HX-Redirect": "/trade/quotations"})


@router.get("/quotations/{quotation_id}/pdf")
async def quotation_pdf(quotation_id: int, session: Session = Depends(get_session)):
    from io import BytesIO
    from services.pdf_helper import (
        render_report_pdf, ReportSpec, KpiSpec, TableSpec,
        SectionTitle, ParagraphBlock, CalloutCard,
    )
    user_id = DEFAULT_USER_ID
    quo = QuotationService.get(session, user_id, quotation_id)
    if not quo:
        raise HTTPException(404, "Quotation not found")
    purchaser = PartyService.get(session, user_id, quo.purchaser_id)

    def pkr(v):
        try: return f"Rs. {Decimal(str(v)):,.2f}"
        except Exception: return f"Rs. {v}"

    status_label = quo.status.value.title() if hasattr(quo.status, "value") else str(quo.status).title()

    kpis = [
        KpiSpec("Total",   pkr(quo.total_sale)),
        KpiSpec("Status",  status_label,
                negative=(quo.status not in (QuotationStatus.ACCEPTED,))),
        KpiSpec("Valid Until",
                quo.valid_until.strftime("%b %d, %Y") if quo.valid_until else "—",
                sub=f"{quo.customer_terms_days} day terms" if quo.customer_terms_days else ""),
        KpiSpec("Items",   str(len(quo.lines))),
    ]

    rows = []
    for ln in quo.lines:
        bullets = [f"{s.label}: {s.value}" for s in (ln.specs or [])]
        if ln.line_notes:
            bullets.append(ln.line_notes)
        name_html = f"<b>{ln.item_name}</b>"
        if bullets:
            name_html += "<br/>" + "<br/>".join(
                f"<font color='#65675e' size='8'>• {b}</font>" for b in bullets
            )
        rows.append([
            name_html,
            f"{float(ln.quantity):g} {ln.unit}",
            pkr(ln.unit_price),
            pkr((Decimal(ln.quantity) * Decimal(ln.unit_price)).quantize(Decimal('0.01'))),
        ])
    charges = TableSpec(
        headers=["Description", "Qty", "Rate", "Amount"],
        rows=rows,
        col_widths=[300, 60, 90, 100],
        num_cols={1, 2, 3},
        totals_row=["", "", "Total", pkr(quo.total_sale)],
    )

    bill_to_lines = [f"<b>{purchaser.name}</b>"]
    if purchaser.address: bill_to_lines.append(purchaser.address)
    if purchaser.phone:   bill_to_lines.append(f"Phone: {purchaser.phone}")
    if purchaser.email:   bill_to_lines.append(f"Email: {purchaser.email}")

    sections = [
        SectionTitle("Quoted To"),
        ParagraphBlock("<br/>".join(bill_to_lines)),
        SectionTitle("Quotation Details"),
        charges,
        CalloutCard(
            label="Total Quoted",
            value=pkr(quo.total_sale),
            suffix=(f"Valid until {quo.valid_until.strftime('%b %d, %Y')}" if quo.valid_until else "Subject to confirmation"),
        ),
    ]
    if quo.terms_text:
        sections.append(SectionTitle("Terms & Conditions"))
        sections.append(ParagraphBlock(quo.terms_text.replace("\n", "<br/>")))
    sections.append(SectionTitle("Acceptance"))
    sections.append(ParagraphBlock(
        f"To accept this quotation, kindly confirm in writing referencing <b>{quo.reference}</b>. "
        f"Upon acceptance the order is converted to a confirmed trade and a separate order "
        f"confirmation is issued."
    ))

    buf = BytesIO()
    render_report_pdf(buf, ReportSpec(
        title="Quotation",
        subtitle_parts=[
            f"Quotation {quo.reference}",
            f"Issued {quo.quote_date.strftime('%B %d, %Y')}",
            f"Quoted to {purchaser.name}",
        ],
        kpis=kpis,
        sections=sections,
        footer_subtitle="Ibrahim Traders · quotations",
        generated_label="Issued",
        brand="IBRAHIM TRADERS",
    ))
    return Response(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="Quotation-{quo.reference}.pdf"'},
    )


# ═════════════════════════════════════════════════════════════════
# Trade attachments (customer PO uploads, etc.)
# ═════════════════════════════════════════════════════════════════


@router.post("/trades/{trade_id}/attachments")
async def trade_attachment_upload(trade_id: int, request: Request, session: Session = Depends(get_session)):
    """Upload one or more files as customer-PO (or `other`) attachments to a trade."""
    from models import TradeAttachment, TradeAttachmentKind
    import os, uuid
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")

    form = await request.form()
    kind_raw = (form.get("kind") or "customer_po").strip()
    try:
        kind = TradeAttachmentKind(kind_raw)
    except ValueError:
        kind = TradeAttachmentKind.CUSTOMER_PO
    notes = (form.get("notes") or "").strip() or None

    upload_dir = "static/uploads/trade_attachments"
    os.makedirs(upload_dir, exist_ok=True)

    files = [f for f in form.getlist("files") if hasattr(f, "filename") and f.filename]
    if not files:
        raise HTTPException(400, "No files received")

    for f in files:
        ext = os.path.splitext(f.filename)[1].lower() or ".bin"
        safe_name = f"{uuid.uuid4().hex}{ext}"
        full_path = os.path.join(upload_dir, safe_name)
        size = 0
        with open(full_path, "wb") as out:
            while True:
                chunk = await f.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                size += len(chunk)
        session.add(TradeAttachment(
            user_id=user_id, trade_id=trade.id, kind=kind,
            filename=f.filename, content_type=getattr(f, "content_type", None) or None,
            size_bytes=size, path=f"/{full_path}", notes=notes,
        ))
    session.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


@router.post("/trades/{trade_id}/attachments/{attachment_id}/delete")
async def trade_attachment_delete(trade_id: int, attachment_id: int, session: Session = Depends(get_session)):
    """Delete a single attachment row and remove its file from disk."""
    from models import TradeAttachment
    import os
    user_id = DEFAULT_USER_ID
    a = session.get(TradeAttachment, attachment_id)
    if not a or a.user_id != user_id or a.trade_id != trade_id:
        raise HTTPException(404, "Attachment not found")
    try:
        fs_path = a.path.lstrip("/")
        if os.path.isfile(fs_path):
            os.remove(fs_path)
    except OSError:
        pass
    session.delete(a)
    session.commit()
    return Response(status_code=204, headers={"HX-Refresh": "true"})


# ═════════════════════════════════════════════════════════════════
# Trade-derived document PDFs (on-demand, no persistence)
# ═════════════════════════════════════════════════════════════════


def _serve_trade_doc(kind: str, trade_id: int, session: Session):
    """Shared helper: load trade + parties → build PDF → inline Response.

    For the Vendor PO, also embeds any `design` attachments at the bottom of
    the PDF so the supplier sees the print-ready artwork inline.
    """
    from services.trade_docs import build_doc_pdf, DocContext
    from services.pdf_helper import SectionTitle, ParagraphBlock, ImageBlock
    from models import TradeAttachment, TradeAttachmentKind
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    vendor = PartyService.get(session, user_id, trade.vendor_id)
    purchaser = PartyService.get(session, user_id, trade.purchaser_id)
    if not vendor or not purchaser:
        raise HTTPException(400, "Trade is missing vendor or purchaser")

    extra_sections = None
    if kind == "vendor_po":
        designs = list(session.exec(
            select(TradeAttachment).where(
                TradeAttachment.user_id == user_id,
                TradeAttachment.trade_id == trade.id,
                TradeAttachment.kind == TradeAttachmentKind.DESIGN,
            ).order_by(TradeAttachment.uploaded_at)
        ).all())
        designs = [d for d in designs
                   if (d.filename.rsplit(".", 1)[-1].lower() if "." in d.filename else "")
                   in ("png", "jpg", "jpeg", "gif", "webp")]
        if designs:
            extra_sections = [
                SectionTitle("Designs / Artwork"),
                ParagraphBlock(
                    f"Print-ready artwork for this PO — {len(designs)} file"
                    f"{'s' if len(designs) > 1 else ''} attached. Please match colours, "
                    "dimensions and bleed to the artwork below."
                ),
            ]
            for d in designs:
                extra_sections.append(ImageBlock(
                    path=d.path,
                    caption=f"{d.filename}" + (f" · {d.notes}" if d.notes else ""),
                    max_width=480, max_height=420,
                ))

    pdf = build_doc_pdf(DocContext(
        kind=kind, trade=trade, vendor=vendor, purchaser=purchaser,
        extra_sections=extra_sections,
    ))
    if kind == "vendor_po":
        # {Customer}-{Mon-DD-YYYY}.pdf, e.g. "Sansa-Jun-29-2026.pdf"
        import re
        safe_customer = re.sub(r"[^\w\-]+", "_", purchaser.name).strip("_") or "customer"
        date_label = date.today().strftime("%b-%d-%Y")
        filename = f"{safe_customer}-{date_label}.pdf"
    else:
        # numeric part only — keep our internal "TRD-" scheme off shared files
        ref_num = (trade.reference or "").split("-")[-1] or (trade.reference or "")
        filename = f"{kind}-{ref_num}.pdf"
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/trades/{trade_id}/order-confirmation.pdf")
async def trade_order_confirmation_pdf(trade_id: int, session: Session = Depends(get_session)):
    return _serve_trade_doc("order_confirm", trade_id, session)


@router.get("/trades/{trade_id}/delivery-note.pdf")
async def trade_delivery_note_pdf(trade_id: int, session: Session = Depends(get_session)):
    return _serve_trade_doc("delivery_note", trade_id, session)


@router.get("/trades/{trade_id}/packing-slip.pdf")
async def trade_packing_slip_pdf(trade_id: int, session: Session = Depends(get_session)):
    return _serve_trade_doc("packing_slip", trade_id, session)


@router.get("/trades/{trade_id}/delivery-pack.pdf")
async def trade_delivery_pack_pdf(trade_id: int, session: Session = Depends(get_session)):
    """Combined Delivery Note + Packing Slip for the WHOLE trade (final qty)."""
    return _serve_trade_doc("delivery_pack", trade_id, session)


@router.get("/trades/{trade_id}/delivery-pack/by-date/{event_date}.pdf")
async def trade_delivery_pack_by_date_pdf(
    trade_id: int, event_date: str, session: Session = Depends(get_session)
):
    """Combined Delivery Note + Packing Slip for receipts dated `event_date`."""
    from services.trade_docs import build_doc_pdf, DocContext
    from decimal import Decimal as _D
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    try:
        d = _parse_date(event_date)
    except Exception:
        raise HTTPException(400, "Invalid date — expected YYYY-MM-DD")
    if d is None:
        raise HTTPException(400, "Invalid date — expected YYYY-MM-DD")

    # Aggregate received_qty per line for receipts dated d.
    qty_per_line: dict[int, _D] = {}
    for ln in trade.lines:
        for r in (ln.receipts or []):
            if r.received_on == d:
                qty_per_line[ln.id] = qty_per_line.get(ln.id, _D("0")) + _D(r.received_qty)
    if not qty_per_line:
        raise HTTPException(404, f"No receipts on {event_date} for this trade")

    vendor = PartyService.get(session, user_id, trade.vendor_id)
    purchaser = PartyService.get(session, user_id, trade.purchaser_id)
    pdf = build_doc_pdf(DocContext(
        kind="delivery_pack",
        trade=trade, vendor=vendor, purchaser=purchaser,
        line_qty_override={lid: q for lid, q in qty_per_line.items()},
        event_label=d.strftime("%B %d, %Y"),
    ))
    filename = f"delivery-pack-{trade.reference}-{event_date}.pdf"
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/trades/{trade_id}/invoice/by-date/{event_date}.pdf")
async def trade_invoice_by_date_pdf(
    trade_id: int, event_date: str, session: Session = Depends(get_session)
):
    """Per-receipt-event invoice — billed for only the qty received on `event_date`.

    If a bilty for that delivery was paid by the customer, the bilty amount is
    deducted from the invoice subtotal (an "Amount Due" callout shows the net).
    """
    from services.trade_docs import build_doc_pdf, DocContext, _pkr, _subtotal_for
    from services.pdf_helper import CalloutCard, SectionTitle, ParagraphBlock, TableSpec
    from decimal import Decimal as _D
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    d = _parse_date(event_date)
    if d is None:
        raise HTTPException(400, "Invalid date — expected YYYY-MM-DD")

    qty_per_line: dict[int, _D] = {}
    for ln in trade.lines:
        for r in (ln.receipts or []):
            if r.received_on == d:
                qty_per_line[ln.id] = qty_per_line.get(ln.id, _D("0")) + _D(r.received_qty)
    if not qty_per_line:
        raise HTTPException(404, f"No receipts on {event_date} for this trade")

    vendor = PartyService.get(session, user_id, trade.vendor_id)
    purchaser = PartyService.get(session, user_id, trade.purchaser_id)

    # Customer-paid bilty for this exact delivery date → deduct from invoice.
    bilty_je = _find_bilty(session, user_id, trade.id, d)
    bilty_paid_by_cust = _D("0")
    bilty_desc = None
    if bilty_je and (bilty_je.description or "").endswith("[paid-by-customer]"):
        bilty_paid_by_cust = next(
            (_D(ln.debit) for ln in bilty_je.lines if _D(ln.debit) > 0),
            _D("0"),
        )
        # Strip the trade-ref prefix and tags for a tidy display.
        raw = bilty_je.description
        if raw.startswith(f"{trade.reference} "):
            raw = raw[len(trade.reference)+1:]
        for tag in (f" [bilty-for:{event_date}]", " [paid-by-customer]"):
            raw = raw.replace(tag, "")
        bilty_desc = raw.strip() or "Bilty paid by customer"

    ctx = DocContext(
        kind="delivery_invoice",
        trade=trade, vendor=vendor, purchaser=purchaser,
        line_qty_override=qty_per_line,
        event_label=d.strftime("%B %d, %Y"),
        event_date=d,
    )

    extra_sections = None
    if bilty_paid_by_cust > 0:
        gross = _subtotal_for(ctx)
        net = (gross - bilty_paid_by_cust).quantize(_D("0.01"))
        extra_sections = [
            SectionTitle("Adjustments"),
            TableSpec(
                headers=["Description", "Amount"],
                rows=[[
                    f"Less: Bilty paid by customer ({bilty_desc})",
                    f"- {_pkr(bilty_paid_by_cust)}",
                ]],
                col_widths=[420, 130],
                num_cols={1},
            ),
            CalloutCard(
                label="Net Amount Due",
                value=_pkr(net),
                suffix=f"After customer-paid bilty for {d.strftime('%b %d, %Y')}",
                negative=net > 0,
            ),
        ]
        ctx.extra_sections = extra_sections

    pdf = build_doc_pdf(ctx)
    filename = f"invoice-{trade.reference}-{event_date}.pdf"
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ═════════════════════════════════════════════════════════════════
# Bilty (per-delivery transport expense) — opens a modal styled like
# the Expense voucher: From cash + To expense + Amount. Zero = no-op.
# ═════════════════════════════════════════════════════════════════


def _bilty_tag(d) -> str:
    """Tag embedded in the journal description to identify a bilty entry."""
    return f"[bilty-for:{d.isoformat()}]"


@router.get("/trades/{trade_id}/bilty/by-date/{event_date}/new", response_class=HTMLResponse)
async def trade_bilty_modal(
    trade_id: int, event_date: str, request: Request,
    session: Session = Depends(get_session),
):
    from models import Account
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    d = _parse_date(event_date)
    if d is None:
        raise HTTPException(400, "Invalid date — expected YYYY-MM-DD")

    accounts = list(session.exec(
        select(Account).where(Account.user_id == user_id, Account.is_active == True)  # noqa: E712
        .order_by(Account.code)
    ).all())

    # Bilty routes through Profit / Loss A/C (3903) per the project convention
    # — locked, not a free choice. Cash side defaults to 1101 if it exists.
    pl_acct = next((a for a in accounts if a.code == "3903"), None)
    default_cash = next((a for a in accounts if a.code == "1101"), None)

    # Purchaser + their A/R account — used when "Paid by customer" is ticked.
    purchaser = PartyService.get(session, user_id, trade.purchaser_id)
    purchaser_acct = account_setup.sync_party_account(session, user_id, purchaser) if purchaser else None

    existing = _find_bilty(session, user_id, trade.id, d)
    existing_by_customer = False
    if existing and (existing.description or "").endswith("[paid-by-customer]"):
        existing_by_customer = True

    # Existing TradeBilty row (for kgs/terminal pre-fill)
    from models import TradeBilty, TradeTerminal
    existing_meta = None
    if existing:
        existing_meta = session.exec(
            select(TradeBilty).where(
                TradeBilty.user_id == user_id,
                TradeBilty.trade_id == trade.id,
                TradeBilty.journal_entry_id == existing.id,
            )
        ).first()
    existing_terminal_name = ""
    if existing_meta and existing_meta.terminal_id:
        t = session.get(TradeTerminal, existing_meta.terminal_id)
        if t:
            existing_terminal_name = t.name

    # All terminals previously used — drive the typeahead datalist
    terminals = list(session.exec(
        select(TradeTerminal).where(TradeTerminal.user_id == user_id)
        .order_by(TradeTerminal.name)
    ).all())

    return templates.TemplateResponse(
        "trade_bilty_modal.html",
        _ctx(
            request, trade=trade, event_date=event_date,
            accounts=accounts,
            pl_acct=pl_acct,
            default_cash_id=(default_cash.id if default_cash else None),
            purchaser=purchaser,
            purchaser_acct=purchaser_acct,
            existing=existing,
            existing_by_customer=existing_by_customer,
            existing_meta=existing_meta,
            existing_terminal_name=existing_terminal_name,
            terminals=terminals,
            today=date.today(),
        ),
    )


@router.post("/trades/{trade_id}/bilty/by-date/{event_date}")
async def trade_bilty_post(
    trade_id: int, event_date: str,
    description: str = Form(""),
    amount: str = Form("0"),
    weight_kgs: str = Form(""),
    terminal: str = Form(""),
    paid_from_id: Optional[int] = Form(None),
    paid_by_customer: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    """Post (or edit, or remove) the bilty expense for the delivery on `event_date`.

    DR side is always Profit / Loss A/C (3903) — locked convention.
    CR side is the cash account picked, OR the purchaser's A/R if
    `paid_by_customer` is set (the customer covered the bilty out of pocket,
    so their receivable reduces).

    Behaviour (edit-in-place — NEVER creates reversal entries):
      • amount > 0, no prior → post a new EXPENSE entry (EXP-XXXX).
      • amount > 0, prior exists → update prior entry's lines / desc IN PLACE.
        Same reference number, no REV entry, voucher list stays clean.
      • amount = 0, prior exists → hard-delete the entry + TradeBilty row.
      • amount = 0, no prior → no-op.
    """
    from models import (
        Account, JournalEntry, JournalEntryType, JournalLine,
        TradeBilty, TradeTerminal,
    )
    from services.posting import PostingEngine, PostingError
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    d = _parse_date(event_date)
    if d is None:
        raise HTTPException(400, "Invalid date — expected YYYY-MM-DD")

    amt = _parse_decimal(amount, "0")
    customer_paid = bool(paid_by_customer)
    try:
        weight = Decimal(weight_kgs) if weight_kgs.strip() else None
    except Exception:
        weight = None
    terminal_name = (terminal or "").strip()

    prior = _find_bilty(session, user_id, trade.id, d)

    # Marker used to find the matching "Bilty cost close" JV for this
    # trade + date (the JV that moves the bilty hit from P&L to Capital).
    close_tag = f"[bilty-close-for:{event_date}]"

    def _find_bilty_close():
        return session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.entry_type == JournalEntryType.JOURNAL,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalEntry.description.contains(close_tag),
            )
        ).first()

    # ── Amount = 0 → remove the bilty entirely (no reversal entry) ─────
    if amt <= 0:
        if prior is not None:
            prior_meta = session.exec(
                select(TradeBilty).where(
                    TradeBilty.trade_id == trade.id,
                    TradeBilty.journal_entry_id == prior.id,
                )
            ).first()
            if prior_meta:
                session.delete(prior_meta)
            session.delete(prior)  # cascades to journal_lines via FK
            # Also drop the matching close JV so P&L stays balanced.
            existing_close = _find_bilty_close()
            if existing_close is not None:
                session.delete(existing_close)
            session.flush()
            session.refresh(trade)
            TradeService._refresh_status(trade, session)
            session.add(trade)
            session.commit()
        return _close_modal()

    # ── DR side: always P&L A/C (3903) per convention ─────────────────
    pl_acct = session.exec(
        select(Account).where(Account.user_id == user_id, Account.code == "3903")
    ).first()
    if not pl_acct:
        raise HTTPException(400, "Profit / Loss A/C (3903) not seeded — cannot post bilty")

    # ── CR side: either cash (default) or purchaser A/R (if customer paid) ─
    if customer_paid:
        purchaser = PartyService.get(session, user_id, trade.purchaser_id)
        if not purchaser:
            raise HTTPException(400, "Purchaser not found on this trade")
        cr_acct = account_setup.sync_party_account(session, user_id, purchaser)
        cr_party_id = purchaser.id
    else:
        if not paid_from_id:
            raise HTTPException(400, "Paid from (cash / bank) is required")
        cr_acct = session.get(Account, paid_from_id)
        if not cr_acct or cr_acct.user_id != user_id:
            raise HTTPException(400, "Invalid 'paid from' account")
        cr_party_id = None

    desc = (description or "").strip() or f"Bilty for delivery on {event_date}"
    tag_suffix = " [paid-by-customer]" if customer_paid else ""
    full_desc = f"{trade.reference} {desc} {_bilty_tag(d)}{tag_suffix}"

    line_payloads = [
        ({"account_id": pl_acct.id, "debit": amt, "credit": Decimal("0"),
          "description": desc, "party_id": None}),
        ({"account_id": cr_acct.id, "debit": Decimal("0"), "credit": amt,
          "description": desc + (" (paid by customer)" if customer_paid else ""),
          "party_id": cr_party_id}),
    ]

    if prior is None:
        # ── Brand-new bilty → post via PostingEngine ──────────────────
        try:
            target_je = PostingEngine.post(
                session, user_id,
                entry_date=d,
                entry_type=JournalEntryType.EXPENSE,
                description=full_desc,
                lines=line_payloads,
                trade_id=trade.id,
            )
        except PostingError as e:
            raise HTTPException(400, str(e))
    else:
        # ── Existing bilty → edit lines + header IN PLACE ─────────────
        # Same JournalEntry id and reference number; no REV-XXXX created.
        for old in list(prior.lines):
            session.delete(old)
        session.flush()
        session.expire(prior, ["lines"])
        for lp in line_payloads:
            session.add(JournalLine(
                journal_entry_id=prior.id,
                account_id=lp["account_id"],
                debit=lp["debit"],
                credit=lp["credit"],
                description=lp["description"],
                party_id=lp["party_id"],
            ))
        prior.entry_date = d
        prior.entry_type = JournalEntryType.EXPENSE
        prior.description = full_desc
        target_je = prior

    # ── Find-or-create the terminal for typeahead suggestions ─────────
    terminal_id = None
    if terminal_name:
        term = session.exec(
            select(TradeTerminal).where(
                TradeTerminal.user_id == user_id,
                TradeTerminal.name == terminal_name,
            )
        ).first()
        if not term:
            term = TradeTerminal(user_id=user_id, name=terminal_name)
            session.add(term)
            session.flush()
        terminal_id = term.id

    # ── Upsert the TradeBilty metadata row ────────────────────────────
    meta = session.exec(
        select(TradeBilty).where(
            TradeBilty.trade_id == trade.id,
            TradeBilty.journal_entry_id == target_je.id,
        )
    ).first()
    if meta:
        meta.weight_kgs = weight
        meta.terminal_id = terminal_id
        meta.paid_by_customer = customer_paid
        meta.delivery_date = d
    else:
        # Stale meta from a previous JE id? Wipe any old ones for this trade+date.
        for stale in session.exec(
            select(TradeBilty).where(
                TradeBilty.trade_id == trade.id,
                TradeBilty.delivery_date == d,
            )
        ).all():
            session.delete(stale)
        session.flush()
        session.add(TradeBilty(
            user_id=user_id,
            trade_id=trade.id,
            delivery_date=d,
            journal_entry_id=target_je.id,
            weight_kgs=weight,
            terminal_id=terminal_id,
            paid_by_customer=customer_paid,
        ))

    # ── Upsert the matching "Bilty cost close" JV ─────────────────────
    # Moves the bilty's P&L hit straight into Capital A/C so P&L A/C
    # stays at zero (same close discipline as trade-event profit close).
    capital_acct = session.exec(
        select(Account).where(
            Account.user_id == user_id, Account.name == "Capital A/C",
        )
    ).first()
    if capital_acct is not None:
        close_desc = (
            f"Bilty cost close — {trade.reference} · {event_date} "
            f"(closes {target_je.reference}) {close_tag}"
        )
        _bcust = session.get(Party, trade.purchaser_id) if trade.purchaser_id else None
        _bwho = _bcust.name if _bcust else "trade"
        _bitems = TradeService.trade_items_descriptor(trade, event_date)
        _bwt = f", {float(weight):g} kg" if weight else ""
        close_lines = [
            {"account_id": capital_acct.id, "debit": amt, "credit": Decimal("0"),
             "description": f"Bilty → Capital: {_bwho} · {_bitems}{_bwt} ({trade.reference} · {event_date})"},
            {"account_id": pl_acct.id, "debit": Decimal("0"), "credit": amt,
             "description": f"Close P&L A/C — bilty for {event_date}"},
        ]
        existing_close = _find_bilty_close()
        if existing_close is None:
            PostingEngine.post(
                session, user_id,
                entry_date=d, entry_type=JournalEntryType.JOURNAL,
                description=close_desc, lines=close_lines, trade_id=trade.id,
            )
        else:
            # Edit-in-place — keep the same JV reference, just rewrite the lines
            # so the amounts track the bilty's current amount.
            for old in list(existing_close.lines):
                session.delete(old)
            session.flush()
            session.expire(existing_close, ["lines"])
            for lp in close_lines:
                session.add(JournalLine(
                    journal_entry_id=existing_close.id,
                    account_id=lp["account_id"],
                    debit=lp["debit"], credit=lp["credit"],
                    description=lp["description"],
                ))
            existing_close.entry_date = d
            existing_close.description = close_desc

    # Bilty changes what counts as settled — recompute the trade's status.
    session.flush()
    session.refresh(trade)
    TradeService._refresh_status(trade, session)
    session.add(trade)
    session.commit()
    return _close_modal()


def _find_bilty(session, user_id: int, trade_id: int, d) -> Optional["JournalEntry"]:
    """Find the (active) bilty journal entry for a given trade + delivery date."""
    from models import JournalEntry
    tag = _bilty_tag(d)
    return session.exec(
        select(JournalEntry).where(
            JournalEntry.user_id == user_id,
            JournalEntry.trade_id == trade_id,
            JournalEntry.is_reversed == False,  # noqa: E712
            JournalEntry.description.like(f"%{tag}%"),
        )
    ).first()


@router.get("/trades/{trade_id}/vendor-po.pdf")
async def trade_vendor_po_pdf(trade_id: int, session: Session = Depends(get_session)):
    return _serve_trade_doc("vendor_po", trade_id, session)


@router.get("/trades/{trade_id}/payments/{payment_id}/receipt.pdf")
async def trade_payment_receipt_pdf(
    trade_id: int, payment_id: int, session: Session = Depends(get_session)
):
    from models import TradePayment, PaymentDirection
    from services.trade_docs import build_doc_pdf, DocContext
    user_id = DEFAULT_USER_ID
    trade = TradeService.get(session, user_id, trade_id)
    if not trade:
        raise HTTPException(404, "Trade not found")
    payment = session.get(TradePayment, payment_id)
    if (not payment or payment.user_id != user_id or payment.trade_id != trade.id):
        raise HTTPException(404, "Payment not found")
    if payment.direction != PaymentDirection.INBOUND:
        raise HTTPException(400, "Receipts are only issued for inbound (customer) payments")
    vendor = PartyService.get(session, user_id, trade.vendor_id)
    purchaser = PartyService.get(session, user_id, trade.purchaser_id)
    pdf = build_doc_pdf(DocContext(
        kind="payment_receipt", trade=trade, vendor=vendor, purchaser=purchaser,
        payment=payment,
    ))
    filename = f"receipt-{trade.reference}-{payment.id}.pdf"
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
