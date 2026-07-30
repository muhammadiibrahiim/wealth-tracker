"""Business-specific analytics for a flyer / poly-bag trading brokerage."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, func, select

from models import (
    Account,
    AccountSubClass,
    JournalEntry,
    JournalEntryType,
    JournalLine,
    Party,
    PaymentDirection,
    Trade,
    TradeLine,
    TradeLineSpec,
    TradePayment,
    TradeStatus,
)
from services.ledger import balance_asof, profit_and_loss


ZERO = Decimal("0")


def _weighted_payment_lag(session, account_ids: list[int], invoice_is_debit: bool,
                          as_of: Optional[date] = None, include_open: bool = True):
    """Real payment speed from the LEDGER, not a balance proxy.

    FIFO-matches each payment against the invoice it settles, PER ACCOUNT (a
    customer's receipt only pays down that customer's invoices), and returns the
    amount-weighted average lag in days. Advance payments (paid before the
    invoice exists) contribute a NEGATIVE lag.

    With include_open=True (the default), invoices STILL OPEN at `as_of` are also
    counted — aged to `as_of` (days-outstanding-so-far). This is essential: a
    payable you're deliberately DELAYING is unpaid, so a matched-only average
    would ignore it and report that you pay instantly. Counting the open balance
    at its current age makes DSO/DPO reflect what's really happening on the
    ledger — including the money you're sitting on.

    invoice_is_debit=True for A/R  (sale = debit, receipt = credit)
    invoice_is_debit=False for A/P (purchase = credit, payment = debit)
    Returns (weighted_avg_lag_days | None, matched_amount).
    """
    from collections import deque
    total_weighted = ZERO
    total_matched = ZERO
    for aid in account_ids:
        q = (
            select(JournalEntry.entry_date, JournalLine.debit, JournalLine.credit)
            .select_from(JournalLine)
            .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
            .where(
                JournalLine.account_id == aid,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalEntry.entry_type != JournalEntryType.REVERSAL,
            )
        )
        if as_of is not None:
            q = q.where(JournalEntry.entry_date <= as_of)
        rows = session.exec(q.order_by(JournalEntry.entry_date, JournalEntry.id)).all()

        inv_q: deque = deque()  # unmatched invoices (date, amount)
        pay_q: deque = deque()  # unmatched payments (date, amount)
        for edate, debit, credit in rows:
            debit = Decimal(debit or 0)
            credit = Decimal(credit or 0)
            inv_amt = debit if invoice_is_debit else credit
            pay_amt = credit if invoice_is_debit else debit

            if inv_amt > 0:
                amt = inv_amt
                while amt > 0 and pay_q:          # settle against any advances first
                    pdate, pamt = pay_q[0]
                    m = min(amt, pamt)
                    total_weighted += m * Decimal((pdate - edate).days)  # advance → negative
                    total_matched += m
                    amt -= m
                    if pamt - m == 0:
                        pay_q.popleft()
                    else:
                        pay_q[0] = (pdate, pamt - m)
                if amt > 0:
                    inv_q.append((edate, amt))
            if pay_amt > 0:
                amt = pay_amt
                while amt > 0 and inv_q:          # settle oldest open invoice first
                    idate, iamt = inv_q[0]
                    m = min(amt, iamt)
                    total_weighted += m * Decimal((edate - idate).days)  # on/after → positive
                    total_matched += m
                    amt -= m
                    if iamt - m == 0:
                        inv_q.popleft()
                    else:
                        inv_q[0] = (idate, iamt - m)
                if amt > 0:
                    pay_q.append((edate, amt))

        # Count invoices still OPEN at as_of, aged to how long they've been
        # outstanding so far — so delayed (unpaid) balances show their real age.
        if include_open:
            ref = as_of or date.today()
            for idate, iamt in inv_q:
                total_weighted += iamt * Decimal((ref - idate).days)
                total_matched += iamt

    if total_matched > 0:
        return (total_weighted / total_matched), total_matched
    return None, ZERO


def _avg_open_age(session, account_ids: list[int], invoice_is_debit: bool,
                  as_of: Optional[date] = None):
    """Amount-weighted average AGE (days outstanding) of the currently-OPEN
    balance, per account. Runs the same both-directions FIFO as the payment-lag
    (so advances settle the earliest invoices first), then measures how long the
    invoices STILL open at `as_of` have been sitting. This is the honest "how
    long is money tied up right now" — it reflects the balances you're delaying,
    and ignores how fast you happened to settle already-paid ones.

    invoice_is_debit=True for A/R, False for A/P.
    Returns (avg_age_days | None, open_amount)."""
    from collections import deque
    ref = as_of or date.today()
    total_weighted = ZERO
    total_open = ZERO
    for aid in account_ids:
        q = (
            select(JournalEntry.entry_date, JournalLine.debit, JournalLine.credit)
            .select_from(JournalLine)
            .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
            .where(
                JournalLine.account_id == aid,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalEntry.entry_type != JournalEntryType.REVERSAL,
            )
        )
        if as_of is not None:
            q = q.where(JournalEntry.entry_date <= as_of)
        rows = session.exec(q.order_by(JournalEntry.entry_date, JournalEntry.id)).all()
        inv_q: deque = deque()
        pay_q: deque = deque()
        for edate, debit, credit in rows:
            debit = Decimal(debit or 0)
            credit = Decimal(credit or 0)
            inv_amt = debit if invoice_is_debit else credit
            pay_amt = credit if invoice_is_debit else debit
            if inv_amt > 0:
                amt = inv_amt
                while amt > 0 and pay_q:            # advances settle earliest invoices
                    _pd, pamt = pay_q[0]
                    m = min(amt, pamt)
                    amt -= m
                    if pamt - m == 0:
                        pay_q.popleft()
                    else:
                        pay_q[0] = (_pd, pamt - m)
                if amt > 0:
                    inv_q.append((edate, amt))
            if pay_amt > 0:
                amt = pay_amt
                while amt > 0 and inv_q:            # payments settle oldest invoice
                    idate, iamt = inv_q[0]
                    m = min(amt, iamt)
                    amt -= m
                    if iamt - m == 0:
                        inv_q.popleft()
                    else:
                        inv_q[0] = (idate, iamt - m)
                if amt > 0:
                    pay_q.append((edate, amt))
        for idate, iamt in inv_q:
            total_weighted += iamt * Decimal((ref - idate).days)
            total_open += iamt
    if total_open > 0:
        return (total_weighted / total_open), total_open
    return None, ZERO


def _weighted_payment_lag(session, account_ids: list[int], invoice_is_debit: bool,
                          as_of: Optional[date] = None, include_open: bool = True):
    """Amount-weighted average LAG (days) between an invoice and its PAYMENT.

    This is the real collection/payment cycle, not just the age of what's unpaid:

    - FIFO, both directions — payments settle the oldest open invoice; a payment
      that lands BEFORE any invoice (an advance) waits and then settles the next
      invoice, contributing a NEGATIVE lag (paid ahead). So DPO automatically
      folds in advance payments at their real dates.
    - Every settled chunk contributes (payment_date − invoice_date) × amount. A
      PARTIAL payment locks in just that chunk's lag and reduces the invoice's
      still-open weight — exactly "partial payment reduces the weight".
    - Any still-OPEN invoice contributes (as_of − invoice_date) × amount when
      include_open (money still outstanding is still ageing). Unmatched advances
      are ignored — a prepaid isn't "outstanding".

    invoice_is_debit=True for A/R (DSO), False for A/P (DPO).
    Returns (weighted_avg_days | None, total_weight)."""
    from collections import deque
    ref = as_of or date.today()
    total_weighted = ZERO
    total_weight = ZERO
    for aid in account_ids:
        q = (
            select(JournalEntry.entry_date, JournalLine.debit, JournalLine.credit)
            .select_from(JournalLine)
            .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
            .where(
                JournalLine.account_id == aid,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalEntry.entry_type != JournalEntryType.REVERSAL,
            )
        )
        if as_of is not None:
            q = q.where(JournalEntry.entry_date <= as_of)
        rows = session.exec(q.order_by(JournalEntry.entry_date, JournalEntry.id)).all()
        inv_q: deque = deque()   # (date, amount) invoices awaiting payment
        pay_q: deque = deque()   # (date, amount) payments/advances awaiting an invoice
        for edate, debit, credit in rows:
            inv_amt = Decimal(debit or 0) if invoice_is_debit else Decimal(credit or 0)
            pay_amt = Decimal(credit or 0) if invoice_is_debit else Decimal(debit or 0)
            if inv_amt > 0:
                amt = inv_amt
                while amt > 0 and pay_q:                 # match earlier advances
                    pdate, pamt = pay_q[0]
                    m = amt if amt < pamt else pamt
                    total_weighted += m * Decimal((pdate - edate).days)   # pay − invoice (neg = advance)
                    total_weight += m
                    amt -= m
                    if pamt - m == 0:
                        pay_q.popleft()
                    else:
                        pay_q[0] = (pdate, pamt - m)
                if amt > 0:
                    inv_q.append((edate, amt))
            if pay_amt > 0:
                amt = pay_amt
                while amt > 0 and inv_q:                 # settle oldest open invoice
                    idate, iamt = inv_q[0]
                    m = amt if amt < iamt else iamt
                    total_weighted += m * Decimal((edate - idate).days)   # pay − invoice
                    total_weight += m
                    amt -= m
                    if iamt - m == 0:
                        inv_q.popleft()
                    else:
                        inv_q[0] = (idate, iamt - m)
                if amt > 0:
                    pay_q.append((edate, amt))
        if include_open:
            for idate, iamt in inv_q:                    # still outstanding, still ageing
                total_weighted += iamt * Decimal((ref - idate).days)
                total_weight += iamt
    if total_weight > 0:
        return (total_weighted / total_weight), total_weight
    return None, ZERO


def _sum_balance(session: Session, account_ids: list[int], as_of: Optional[date] = None) -> Decimal:
    return sum((balance_asof(session, aid, as_of) for aid in account_ids), ZERO)


def _accounts_in_subclass(session: Session, user_id: int, sub_code: str) -> list[Account]:
    sub = session.exec(
        select(AccountSubClass).where(AccountSubClass.user_id == user_id, AccountSubClass.code == sub_code)
    ).first()
    if not sub:
        return []
    return list(session.exec(select(Account).where(Account.subclass_id == sub.id)).all())


# ──────────────────────── Cash Flow Statement ────────────────────────


def cash_flow_statement(session, user_id, from_date=None, to_date=None) -> dict:
    cash_accts = _accounts_in_subclass(session, user_id, "1100")
    ids = [a.id for a in cash_accts]
    epoch = date(1970, 1, 1)
    beginning = _sum_balance(session, ids, (from_date - timedelta(days=1)) if from_date else epoch)
    ending = _sum_balance(session, ids, to_date)

    pl = profit_and_loss(session, user_id, from_date=from_date, to_date=to_date)
    net_income = pl["net_income"]

    ar_accts = _accounts_in_subclass(session, user_id, "1200")
    ar_begin = _sum_balance(session, [a.id for a in ar_accts], (from_date - timedelta(days=1)) if from_date else epoch)
    ar_end = _sum_balance(session, [a.id for a in ar_accts], to_date)
    delta_ar = ar_end - ar_begin

    ap_accts = _accounts_in_subclass(session, user_id, "2100")
    ap_begin = -_sum_balance(session, [a.id for a in ap_accts], (from_date - timedelta(days=1)) if from_date else epoch)
    ap_end = -_sum_balance(session, [a.id for a in ap_accts], to_date)
    delta_ap = ap_end - ap_begin

    cash_from_ops = (net_income - delta_ar + delta_ap).quantize(Decimal("0.01"))

    fin_q = select(JournalEntry).where(
        JournalEntry.user_id == user_id,
        JournalEntry.entry_type.in_([
            JournalEntryType.CAPITAL_INJECTION,
            JournalEntryType.CAPITAL_WITHDRAWAL,
        ]),
    )
    if from_date: fin_q = fin_q.where(JournalEntry.entry_date >= from_date)
    if to_date: fin_q = fin_q.where(JournalEntry.entry_date <= to_date)
    injections = ZERO
    withdrawals = ZERO
    for e in session.exec(fin_q).all():
        for ln in e.lines:
            a = session.get(Account, ln.account_id)
            if not a or a.subclass_id is None:
                continue
            sub = session.get(AccountSubClass, a.subclass_id)
            if sub and sub.code == "1100":
                if ln.debit > 0: injections += Decimal(ln.debit)
                else: withdrawals += Decimal(ln.credit)

    cash_from_financing = (injections - withdrawals).quantize(Decimal("0.01"))
    net_change = (cash_from_ops + cash_from_financing).quantize(Decimal("0.01"))
    return {
        "period_from": from_date, "period_to": to_date,
        "operating": [
            {"label": "Net Income", "amount": net_income},
            {"label": "Less: Increase in AR (more outstanding)", "amount": -delta_ar.quantize(Decimal('0.01'))},
            {"label": "Plus: Increase in AP (deferred payments)", "amount": delta_ap.quantize(Decimal('0.01'))},
        ],
        "cash_from_ops": cash_from_ops,
        "financing": [
            {"label": "Owner Injection (Capital In)", "amount": injections.quantize(Decimal('0.01'))},
            {"label": "Owner Withdrawal (Capital Out)", "amount": -withdrawals.quantize(Decimal('0.01'))},
        ],
        "cash_from_financing": cash_from_financing,
        "net_change_in_cash": net_change,
        "beginning_cash": beginning.quantize(Decimal("0.01")),
        "ending_cash": ending.quantize(Decimal("0.01")),
        "reconciliation_diff": ((ending - beginning) - net_change).quantize(Decimal("0.01")),
    }


# ──────────────────────── Customer Profitability ────────────────────────


def customer_profitability(session, user_id, from_date=None, to_date=None) -> dict:
    customers = list(session.exec(
        select(Party).where(Party.user_id == user_id, Party.is_customer == True)  # noqa: E712
    ).all())
    rows = []
    today = date.today()
    grand_revenue = ZERO

    for c in customers:
        rev_q = select(func.coalesce(func.sum(JournalLine.credit), 0)).select_from(JournalLine).join(
            JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
        ).where(
            JournalLine.party_id == c.id,
            JournalEntry.entry_type == JournalEntryType.SALE,
        )
        if from_date: rev_q = rev_q.where(JournalEntry.entry_date >= from_date)
        if to_date: rev_q = rev_q.where(JournalEntry.entry_date <= to_date)
        revenue = Decimal(session.exec(rev_q).one() or 0)

        # COGS on the SAME basis as revenue — the cost of goods actually
        # DELIVERED, taken from PURCHASE journal entries (posted per delivery
        # event, mirroring sales). Using full-order quantity×cost here would
        # count undelivered trades' cost against delivered revenue and make GP
        # wildly (and wrongly) negative.
        ctrade_ids = [t.id for t in session.exec(
            select(Trade).where(
                Trade.user_id == user_id,
                Trade.purchaser_id == c.id,
                Trade.status != TradeStatus.CANCELLED,
            )
        ).all()]
        cogs = ZERO
        if ctrade_ids:
            cogs_q = select(func.coalesce(func.sum(JournalLine.debit), 0)).select_from(
                JournalLine
            ).join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id).where(
                JournalEntry.trade_id.in_(ctrade_ids),
                JournalEntry.entry_type == JournalEntryType.PURCHASE,
                JournalEntry.is_reversed == False,  # noqa: E712
            )
            if from_date: cogs_q = cogs_q.where(JournalEntry.entry_date >= from_date)
            if to_date: cogs_q = cogs_q.where(JournalEntry.entry_date <= to_date)
            cogs = Decimal(session.exec(cogs_q).one() or 0)
        gp = revenue - cogs
        gp_pct = (gp / revenue * 100) if revenue > 0 else ZERO

        outstanding = ZERO
        if c.account_id:
            outstanding = balance_asof(session, c.account_id, to_date)

        trades = list(session.exec(
            select(Trade).where(Trade.user_id == user_id, Trade.purchaser_id == c.id,
                                Trade.status != TradeStatus.CANCELLED)
        ).all())
        days_sum = 0
        days_n = 0
        for t in trades:
            if not t.delivered_at: continue
            pays = [p for p in t.payments if p.direction == PaymentDirection.INBOUND]
            days = (today - t.delivered_at).days if not pays else (min(p.paid_on for p in pays) - t.delivered_at).days
            days_sum += days
            days_n += 1
        avg_dso = (days_sum / days_n) if days_n else 0

        rows.append({
            "customer": c,
            "revenue": revenue.quantize(Decimal("0.01")),
            "cogs": cogs.quantize(Decimal("0.01")),
            "gp": gp.quantize(Decimal("0.01")),
            "gp_pct": gp_pct.quantize(Decimal("0.01")),
            "outstanding": outstanding.quantize(Decimal("0.01")),
            "avg_collect_days": round(avg_dso, 1),
            "trade_count": len(trades),
        })
        grand_revenue += revenue

    for r in rows:
        r["share_pct"] = (r["revenue"] / grand_revenue * 100).quantize(Decimal("0.01")) if grand_revenue > 0 else ZERO

    rows.sort(key=lambda r: -r["revenue"])
    top3 = sum((r["revenue"] for r in rows[:3]), ZERO)
    concentration = (top3 / grand_revenue * 100) if grand_revenue > 0 else ZERO
    return {
        "rows": rows,
        "total_revenue": grand_revenue.quantize(Decimal("0.01")),
        "top3_concentration_pct": concentration.quantize(Decimal("0.01")),
        "period_from": from_date,
        "period_to": to_date,
    }


# ──────────────────────── Vendor Performance ────────────────────────


def vendor_performance(session, user_id, from_date=None, to_date=None) -> dict:
    vendors = list(session.exec(
        select(Party).where(Party.user_id == user_id, Party.is_vendor == True)  # noqa: E712
    ).all())
    rows = []
    today = date.today()
    grand_purchases = ZERO

    for v in vendors:
        trades = list(session.exec(
            select(Trade).where(
                Trade.user_id == user_id, Trade.vendor_id == v.id,
                Trade.status != TradeStatus.CANCELLED,
            )
        ).all())
        if from_date: trades = [t for t in trades if t.trade_date >= from_date]
        if to_date: trades = [t for t in trades if t.trade_date <= to_date]

        purchases = sum((Decimal(t.total_cost) for t in trades), ZERO)
        gp_contributed = sum((Decimal(t.total_sale) - Decimal(t.total_cost) for t in trades), ZERO)

        var_sum = ZERO
        var_n = 0
        for t in trades:
            for ln in t.lines:
                if ln.ordered_quantity and ln.ordered_quantity > 0:
                    var_sum += (Decimal(ln.quantity) - Decimal(ln.ordered_quantity)) / Decimal(ln.ordered_quantity)
                    var_n += 1
        avg_variance_pct = (var_sum / var_n * 100) if var_n else ZERO

        days_sum = 0
        days_n = 0
        for t in trades:
            pays = [p for p in t.payments if p.direction == PaymentDirection.OUTBOUND]
            days = (today - t.trade_date).days if not pays else (min(p.paid_on for p in pays) - t.trade_date).days
            days_sum += days
            days_n += 1
        avg_dpo = (days_sum / days_n) if days_n else 0

        outstanding = ZERO
        if v.account_id:
            outstanding = -balance_asof(session, v.account_id, to_date)

        rows.append({
            "vendor": v,
            "purchases": purchases.quantize(Decimal("0.01")),
            "gp_contributed": gp_contributed.quantize(Decimal("0.01")),
            "trade_count": len(trades),
            "avg_pay_days": round(avg_dpo, 1),
            "avg_qty_variance_pct": avg_variance_pct.quantize(Decimal("0.01")),
            "outstanding": outstanding.quantize(Decimal("0.01")),
        })
        grand_purchases += purchases

    for r in rows:
        r["share_pct"] = (r["purchases"] / grand_purchases * 100).quantize(Decimal("0.01")) if grand_purchases > 0 else ZERO

    rows.sort(key=lambda r: -r["purchases"])
    return {
        "rows": rows,
        "total_purchases": grand_purchases.quantize(Decimal("0.01")),
        "period_from": from_date,
        "period_to": to_date,
    }


# ──────────────────────── Item / Spec Profitability ────────────────────────


def item_profitability(session, user_id, from_date=None, to_date=None, group_by_spec=False) -> dict:
    q = select(TradeLine, Trade).join(Trade, TradeLine.trade_id == Trade.id).where(
        Trade.user_id == user_id, Trade.status != TradeStatus.CANCELLED
    )
    if from_date: q = q.where(Trade.trade_date >= from_date)
    if to_date: q = q.where(Trade.trade_date <= to_date)
    rows_raw = list(session.exec(q).all())

    bucket = {}
    for tl, t in rows_raw:
        if group_by_spec:
            specs = list(session.exec(
                select(TradeLineSpec).where(TradeLineSpec.line_id == tl.id).order_by(TradeLineSpec.sort_order)
            ).all())
            spec_key = " · ".join(f"{s.label}={s.value}" for s in specs) or "(no specs)"
            key = f"{tl.item_name} ▸ {spec_key}"
        else:
            key = tl.item_name
        b = bucket.setdefault(key, {
            "label": key, "item_name": tl.item_name,
            "units": ZERO, "revenue": ZERO, "cogs": ZERO, "gp": ZERO, "trade_count": 0,
        })
        qty = Decimal(tl.quantity)
        rev = qty * Decimal(tl.unit_price)
        cst = qty * Decimal(tl.unit_cost)
        b["units"] += qty
        b["revenue"] += rev
        b["cogs"] += cst
        b["gp"] += rev - cst
        b["trade_count"] += 1

    months = max(((to_date - from_date).days / 30.0), 1) if (from_date and to_date) else 1
    rows = []
    for v in bucket.values():
        v["gp_pct"] = (v["gp"] / v["revenue"] * 100).quantize(Decimal("0.01")) if v["revenue"] > 0 else ZERO
        v["velocity_per_month"] = (v["units"] / Decimal(months)).quantize(Decimal("0.01"))
        for k in ("revenue", "cogs", "gp"):
            v[k] = v[k].quantize(Decimal("0.01"))
        rows.append(v)
    rows.sort(key=lambda r: -r["gp"])
    return {"rows": rows, "group_by_spec": group_by_spec,
            "period_from": from_date, "period_to": to_date}


# ──────────────────────── Working Capital + Capital Utilization ────────────────────────


def working_capital_metrics(session, user_id, as_of=None, period_days=365) -> dict:
    """Working-capital metrics.

    DSO / DPO are the amount-weighted LAG between an invoice and its payment,
    FIFO-matched straight from the ledger (see `_weighted_payment_lag`): every
    settled chunk counts its real delivery→payment (DSO) or bill→payment (DPO)
    days, a partial payment locks in just that chunk, still-unpaid amounts keep
    ageing at their current age, and vendor advances (paid before the bill) fold
    in as a negative lag. This answers "how long do customers actually take to
    pay me / how long do I take to pay vendors", independent of the sales window.

    `sales_in_period` / `cogs_in_period` and the current ratio still use the
    365-day window and live balances. If there's < Rs 1k of matched+open weight,
    DSO/DPO return None and the template renders "—".
    """
    as_of = as_of or date.today()
    period_from = as_of - timedelta(days=period_days)
    pl = profit_and_loss(session, user_id, from_date=period_from, to_date=as_of)
    sales = pl["total_income"]
    cogs = pl["total_cogs"]

    # Scope receivables/payables to the parties we actually TRADE with — the
    # party that appears as a trade's purchaser (AR) or vendor (AP). This keeps
    # the funding/equity ledgers (Capital A/C, CEO) — which live under Accounts
    # Payable but aren't trade payables — out of AR/AP, and correctly counts a
    # customer's receivable even if their ledger sits under the AP subclass.
    trade_rows = session.exec(
        select(Trade.vendor_id, Trade.purchaser_id).where(Trade.user_id == user_id)
    ).all()
    vendor_pids = {v for v, _ in trade_rows if v}
    customer_pids = {c for _, c in trade_rows if c}
    parties = list(session.exec(select(Party).where(Party.user_id == user_id)).all())
    ar_ids = [p.account_id for p in parties if p.id in customer_pids and p.account_id]
    ap_ids = [p.account_id for p in parties if p.id in vendor_pids and p.account_id]

    ar_balance = _sum_balance(session, ar_ids, as_of)          # customers owe us (DR+)
    ap_balance = -_sum_balance(session, ap_ids, as_of)         # we owe vendors (CR+ → flip)
    cash       = _sum_balance(session, [a.id for a in _accounts_in_subclass(session, user_id, "1100")], as_of)

    # Strip opening balances out of AR/AP so the DSO/DPO denominator is
    # comparable. Done per-party: for each party with an associated A/R or A/P
    # account, the *operating* balance is (current − opening). Positive
    # deltas roll up to operating AR (customer balance grew due to new sales),
    # negative deltas roll up to operating AP (we owe vendor for new purchases).
    #
    # Aggregating opening balances and subtracting from total AR is wrong:
    # a single customer paying down their opening balance below 0 would offset
    # another customer's brand-new receivable and the metric would silently
    # report DSO of zero days.
    parties = list(session.exec(select(Party).where(Party.user_id == user_id)).all())
    opening_ar = ZERO
    opening_ap = ZERO
    operating_ar = ZERO
    operating_ap = ZERO
    for p in parties:
        if not p.account_id:
            continue
        current = balance_asof(session, p.account_id, as_of)
        opening = Decimal(p.opening_balance or 0)
        delta = current - opening
        if opening > 0:
            opening_ar += opening
        elif opening < 0:
            opening_ap += -opening
        if delta > 0:
            operating_ar += delta
        elif delta < 0:
            operating_ap += -delta

    # DSO / DPO = amount-weighted LAG between an invoice and its PAYMENT, FIFO-
    # matched from the ledger (not nominal terms). Each settled chunk counts its
    # real delivery→payment (or bill→payment) days; a partial payment locks in
    # just that chunk and reduces the still-open weight; anything still unpaid
    # keeps ageing at its current age. DPO folds in advance payments at their
    # real dates (an advance before the bill contributes a negative lag).
    # DSO/DPO reuse the trade-scoped AR/AP account ids computed above.
    min_open = Decimal("1000")          # need >Rs 1k of weight to be meaningful
    dso_raw, dso_open = _weighted_payment_lag(session, ar_ids, invoice_is_debit=True, as_of=as_of)
    dpo_raw, dpo_open = _weighted_payment_lag(session, ap_ids, invoice_is_debit=False, as_of=as_of)
    dso = dso_raw if (dso_raw is not None and dso_open >= min_open) else None
    dpo = dpo_raw if (dpo_raw is not None and dpo_open >= min_open) else None
    ccc = (dso - dpo) if (dso is not None and dpo is not None) else None

    # Current ratio: split EACH party account by sign instead of netting a
    # prepaid to one party against a payable to another. A DR balance (customer
    # owes us, or we've prepaid a vendor) is a current ASSET; a CR balance (we
    # owe a vendor, or a customer paid in advance) is a current LIABILITY. Netting
    # them (e.g. HI's prepaid against Ahmed's payable) understates liabilities and
    # flatters the ratio — a prepaid to HI can't settle a payable to Ahmed.
    current_assets = cash
    current_liabilities = ZERO
    for aid in set(ar_ids) | set(ap_ids):
        b = balance_asof(session, aid, as_of)
        if b > 0:
            current_assets += b
        elif b < 0:
            current_liabilities += -b
    current_ratio = (current_assets / current_liabilities) if current_liabilities > 0 else None

    def _flt(v):
        return round(float(v), 1) if v is not None else None

    return {
        "as_of": as_of, "period_days": period_days,
        "sales_in_period": sales, "cogs_in_period": cogs,
        "ar_balance":      ar_balance.quantize(Decimal("0.01")),
        "ap_balance":      ap_balance.quantize(Decimal("0.01")),
        "cash_balance":    cash.quantize(Decimal("0.01")),
        "opening_ar":      opening_ar.quantize(Decimal("0.01")),
        "opening_ap":      opening_ap.quantize(Decimal("0.01")),
        "operating_ar":    operating_ar.quantize(Decimal("0.01")),
        "operating_ap":    operating_ap.quantize(Decimal("0.01")),
        "dso": _flt(dso),
        "dpo": _flt(dpo),
        "ccc": _flt(ccc),
        "current_ratio": round(float(current_ratio), 2) if current_ratio is not None else None,
        "current_assets": current_assets.quantize(Decimal("0.01")),
        "current_liabilities": current_liabilities.quantize(Decimal("0.01")),
        # Tag the metric as low-confidence when there's < 60 days of sales history
        # (the user can see the warning in the dashboard tile).
        "limited_history": dso is None or dpo is None,
    }


def _bilty_by_trade(session, user_id) -> dict:
    """Per-trade total of customer/self-paid bilty (delivery freight), read from
    the P&L A/C (3903) debit side of active bilty EXPENSE entries."""
    pl = session.exec(
        select(Account).where(Account.user_id == user_id, Account.code == "3903")
    ).first()
    out: dict[int, Decimal] = {}
    if not pl:
        return out
    rows = session.exec(
        select(JournalEntry.trade_id, func.coalesce(func.sum(JournalLine.debit), 0))
        .select_from(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(
            JournalEntry.user_id == user_id,
            JournalEntry.entry_type == JournalEntryType.EXPENSE,
            JournalEntry.is_reversed == False,  # noqa: E712
            JournalEntry.description.like("%[bilty-for:%"),
            JournalLine.account_id == pl.id,
        )
        .group_by(JournalEntry.trade_id)
    ).all()
    for tid, amt in rows:
        if tid is not None:
            out[tid] = Decimal(amt or 0)
    return out


def time_based_performance(session, user_id, as_of=None) -> dict:
    """Year-to-date, month-to-date, average-monthly profit, and the capital
    efficiency metric: net profit earned per Rs of capital per 30 days, using
    each trade's REAL holding period (deploy → collect). Late/unpaid collections
    stretch the holding period, which lowers the per-30-day return — so the
    number automatically reflects payment timing.
    """
    as_of = as_of or date.today()
    year_start = date(as_of.year, 1, 1)
    month_start = as_of.replace(day=1)
    realised = (
        TradeStatus.DELIVERED, TradeStatus.PARTIALLY_PAID,
        TradeStatus.PAID, TradeStatus.CLOSED,
    )

    trades = list(session.exec(
        select(Trade).where(Trade.user_id == user_id, Trade.status != TradeStatus.CANCELLED)
    ).all())
    bilty = _bilty_by_trade(session, user_id)

    def net_profit(t) -> Decimal:
        return (Decimal(t.total_sale) - Decimal(t.total_cost) - bilty.get(t.id, ZERO))

    ytd_sales = ytd_profit = ZERO
    mtd_sales = mtd_profit = ZERO
    first_trade_date = None

    # Capital-efficiency accumulators (rupee-day weighted).
    total_net = ZERO
    rupee_days = ZERO
    cap_sum = ZERO
    weighted_days = ZERO

    for t in trades:
        if first_trade_date is None or t.trade_date < first_trade_date:
            first_trade_date = t.trade_date
        # Sales and profit on the SAME basis — every non-cancelled trade in the
        # period (back-to-back margins are locked at order time, so open orders
        # count too and profit tracks the sales figure).
        if t.trade_date >= year_start:
            ytd_sales += Decimal(t.total_sale)
            ytd_profit += net_profit(t)
        if t.trade_date >= month_start:
            mtd_sales += Decimal(t.total_sale)
            mtd_profit += net_profit(t)

        if t.status in realised:
            capital = Decimal(t.total_cost)
            if capital <= 0:
                continue
            # Collection date = latest customer payment if fully collected,
            # else today (money still tied up → holding period keeps growing).
            fully_paid = Decimal(t.paid_by_customer) >= Decimal(t.total_sale) and t.total_sale > 0
            inbound_dates = [p.paid_on for p in t.payments
                             if p.direction == PaymentDirection.INBOUND and p.paid_on]
            if fully_paid and inbound_dates:
                collect = max(inbound_dates)
            else:
                collect = as_of
            holding = max(1, (collect - t.trade_date).days)
            npf = net_profit(t)
            total_net += npf
            rupee_days += capital * holding
            cap_sum += capital
            weighted_days += capital * holding

    # Average monthly profit — total realised profit ÷ months in business.
    all_time_profit = sum((net_profit(t) for t in trades if t.status in realised), ZERO)
    if first_trade_date:
        months_active = (as_of.year - first_trade_date.year) * 12 + (as_of.month - first_trade_date.month) + 1
    else:
        months_active = 1
    months_active = max(1, months_active)
    avg_monthly_profit = all_time_profit / months_active

    return_per_rs_30d = (total_net / rupee_days * 30) if rupee_days > 0 else ZERO
    avg_holding_days = (weighted_days / cap_sum) if cap_sum > 0 else ZERO

    return {
        "as_of": as_of,
        "ytd_sales": ytd_sales.quantize(Decimal("0.01")),
        "ytd_profit": ytd_profit.quantize(Decimal("0.01")),
        "mtd_sales": mtd_sales.quantize(Decimal("0.01")),
        "mtd_profit": mtd_profit.quantize(Decimal("0.01")),
        "avg_monthly_profit": avg_monthly_profit.quantize(Decimal("0.01")),
        "months_active": months_active,
        "return_per_rs_30d": return_per_rs_30d.quantize(Decimal("0.0001")),
        "return_pct_30d": (return_per_rs_30d * 100).quantize(Decimal("0.01")),
        "avg_holding_days": avg_holding_days.quantize(Decimal("0.1")),
        "capital_working": cap_sum.quantize(Decimal("0.01")),
        "realised_profit": total_net.quantize(Decimal("0.01")),
    }


def _avg_equity_over_period(session, acct_ids, start, end, exclude_types=None):
    """Time-weighted average of equity (credit-positive) across [start, end] —
    the mean of each DAY's closing balance. This is the capital that was actually
    at work: injecting Rs 1M in the last two days shouldn't count as if it funded
    the whole month. Returns None if there's nothing to average."""
    if not acct_ids or end < start:
        return None
    opening = ZERO
    for aid in acct_ids:
        opening += -balance_asof(session, aid, start - timedelta(days=1),
                                 exclude_types=exclude_types)  # credit-positive
    q = (select(JournalEntry.entry_date,
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0))
         .select_from(JournalLine)
         .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
         .where(JournalLine.account_id.in_(acct_ids),
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalEntry.entry_date >= start,
                JournalEntry.entry_date <= end))
    if exclude_types:
        q = q.where(JournalEntry.entry_type.notin_(list(exclude_types)))
    rows = session.exec(q.group_by(JournalEntry.entry_date)).all()
    delta = {d: (Decimal(cr) - Decimal(dr)) for d, dr, cr in rows}  # equity delta = CR − DR
    running = opening
    total = ZERO
    n = 0
    d = start
    while d <= end:
        running += delta.get(d, ZERO)
        total += running
        n += 1
        d += timedelta(days=1)
    return (total / n) if n else opening


def capital_utilization(session, user_id, as_of=None, ni_from=None, ni_to=None) -> dict:
    """Capital efficiency as of `as_of`. Net income for ROCE/ROE is measured over
    [ni_from, ni_to] — default the trailing 365 days, but the dashboard passes a
    single month so those returns read for the selected month. ROE is measured
    against the TIME-WEIGHTED AVERAGE equity over the period (not the closing
    balance), so it reflects the capital actually deployed through the month."""
    as_of = as_of or date.today()
    # Dashboard capital metrics stay BLIND to the partner sub-ledger — the equity
    # split among partners (moving the owner's capital into a named account and
    # dividing monthly profit) must not move these numbers. Excluding this entry
    # type means the dashboard reads the business as one owner's, as before.
    PART_EXCL = ("partner_allocation",)
    metrics = working_capital_metrics(session, user_id, as_of=as_of, period_days=365)
    cash = metrics["cash_balance"]
    ar = metrics["ar_balance"]
    ap = metrics["ap_balance"]
    capital_deployed = cash + ar - ap

    equity_total = ZERO
    for sub_code in ("3100", "3900"):
        for a in _accounts_in_subclass(session, user_id, sub_code):
            equity_total += -balance_asof(session, a.id, as_of, exclude_types=PART_EXCL)

    ni_from = ni_from or (as_of - timedelta(days=365))
    ni_to = ni_to or as_of
    pl = profit_and_loss(session, user_id, from_date=ni_from, to_date=ni_to)
    trailing_ni = pl["net_income"]
    roce = (trailing_ni / capital_deployed * 100) if capital_deployed > 0 else ZERO

    # ── Invested capital & ROI ─────────────────────────────────────────
    # The owner's money in the business sits in two ledger accounts:
    #   • the funding account (CEO) — cash the owner actually injected;
    #   • the Capital A/C — trading profit earned and retained inside.
    # ROI is measured against that total stake. Accounts are matched by name
    # (they live under Accounts Payable in this chart), with graceful fallback
    # if a business renamed them.
    equity_names = ("ibrahim (ceo)", "ceo", "funding", "capital a/c", "capital")
    equity_accts = [a for a in session.exec(
        select(Account).where(Account.user_id == user_id)).all()
        if (a.name or "").strip().lower() in equity_names]

    def _closing(*names) -> Decimal:
        total = ZERO
        for a in equity_accts:
            if (a.name or "").strip().lower() in [n.lower() for n in names]:
                total += -balance_asof(session, a.id, ni_to, exclude_types=PART_EXCL)  # credit-positive
        return total

    funding = _closing("Ibrahim (CEO)", "CEO", "Funding")
    retained = _closing("Capital A/C", "Capital")
    invested_capital = (funding + retained).quantize(Decimal("0.01"))  # closing snapshot

    # Denominator = time-weighted AVERAGE equity over the period (mean of each
    # day's closing balance), so a late-month injection doesn't overstate the
    # base. Falls back to the closing snapshot if the average can't be formed.
    avg_equity = _avg_equity_over_period(session, [a.id for a in equity_accts], ni_from, ni_to,
                                         exclude_types=PART_EXCL)
    if avg_equity is None or avg_equity <= 0:
        avg_equity = invested_capital
    avg_invested_capital = Decimal(avg_equity).quantize(Decimal("0.01"))
    # Earnings per rupee of your own money, over the period, on the average base.
    roi_pct = (trailing_ni / avg_invested_capital * 100) if avg_invested_capital > 0 else ZERO
    # Total profit earned per rupee the owner funded, since inception.
    roi_since_inception = (retained / funding * 100) if funding > 0 else ZERO

    # ── Actual Capital A/C growth over the period (what equity really grew by)
    # vs the PROFIT booked into it. They differ when a non-P&L entry (settlement,
    # owner draw, manual adjustment) hits Capital directly. capital_other surfaces
    # that difference so it isn't mistaken for profit.
    capital_acct = next((a for a in equity_accts
                         if (a.name or "").strip().lower() in ("capital a/c", "capital")), None)
    if capital_acct is not None:
        c_open = -balance_asof(session, capital_acct.id, ni_from - timedelta(days=1), exclude_types=PART_EXCL)
        c_close = -balance_asof(session, capital_acct.id, ni_to, exclude_types=PART_EXCL)
        capital_growth = (c_close - c_open)
    else:
        capital_growth = ZERO
    profit_booked = trailing_ni                       # net income posted this period
    capital_other = (capital_growth - profit_booked)  # non-profit Capital movements

    return {
        "as_of": as_of,
        "profit_booked": profit_booked.quantize(Decimal("0.01")),
        "capital_growth": capital_growth.quantize(Decimal("0.01")),
        "capital_other": capital_other.quantize(Decimal("0.01")),
        "components": [
            {"label": "Cash & Bank", "amount": cash},
            {"label": "Customer Receivables", "amount": ar},
            {"label": "Less: Vendor Payables", "amount": -ap},
        ],
        "capital_deployed": capital_deployed.quantize(Decimal("0.01")),
        "equity_total": equity_total.quantize(Decimal("0.01")),
        "trailing_net_income": trailing_ni,
        "roce_pct": roce.quantize(Decimal("0.01")),
        "funding_ceo": funding.quantize(Decimal("0.01")),
        "retained_capital": retained.quantize(Decimal("0.01")),
        "invested_capital": invested_capital,
        "avg_invested_capital": avg_invested_capital,
        "roi_pct": roi_pct.quantize(Decimal("0.01")),
        "roi_since_inception_pct": roi_since_inception.quantize(Decimal("0.01")),
    }


# ──────────────────────── Bank Position Forecast ────────────────────────


def _avg_delivery_lag_days(session, user_id, vendor_id, default=7) -> int:
    """Average days from trade creation to goods arriving, for a vendor —
    learned from history so we can predict when open orders will deliver."""
    trades = list(session.exec(select(Trade).where(
        Trade.user_id == user_id, Trade.vendor_id == vendor_id
    )).all())
    lags = []
    for t in trades:
        deliv = t.delivered_at
        if not deliv:
            recs = [r.received_on for ln in t.lines for r in (ln.receipts or [])]
            deliv = min(recs) if recs else None
        if deliv and t.trade_date:
            lags.append(max(0, (deliv - t.trade_date).days))
    return round(sum(lags) / len(lags)) if lags else default


def _vendor_delivery_profile(session, user_id, vendor_id):
    """Learn a vendor's PARTIAL-delivery pattern from history so open orders can
    be projected as batches, not a single dump:
      • first_lag  — avg days from trade open to the first batch
      • batch_qty  — avg pcs per delivery batch (None if no receipt history)
      • interval   — avg days between consecutive batches
    """
    trades = list(session.exec(select(Trade).where(
        Trade.user_id == user_id, Trade.vendor_id == vendor_id
    )).all())
    first_lags, batch_qtys, intervals = [], [], []
    for t in trades:
        recs = sorted(
            [r for ln in t.lines for r in (ln.receipts or [])],
            key=lambda r: r.received_on,
        )
        if not recs:
            if t.delivered_at:
                first_lags.append(max(0, (t.delivered_at - t.trade_date).days))
            continue
        first_lags.append(max(0, (recs[0].received_on - t.trade_date).days))
        for r in recs:
            batch_qtys.append(Decimal(str(r.received_qty)))
        for a, b in zip(recs, recs[1:]):
            intervals.append(max(1, (b.received_on - a.received_on).days))
    first_lag = round(sum(first_lags) / len(first_lags)) if first_lags else 7
    batch_qty = (sum(batch_qtys) / len(batch_qtys)) if batch_qtys else None
    interval = round(sum(intervals) / len(intervals)) if intervals else 14
    return first_lag, batch_qty, max(1, interval)


def _last_delivery_date(session, user_id, vendor_id):
    """Most recent date this vendor actually delivered anything — the anchor for
    projecting the NEXT batch at their real cadence."""
    dates = []
    for t in session.exec(select(Trade).where(
        Trade.user_id == user_id, Trade.vendor_id == vendor_id
    )).all():
        if t.delivered_at:
            dates.append(t.delivered_at)
        for ln in t.lines:
            for r in (ln.receipts or []):
                dates.append(r.received_on)
    return max(dates) if dates else None


def _avg_payment_lag_days(session, user_id, customer_id, fallback) -> int:
    """Average days a customer ACTUALLY takes to pay after delivery — from
    real receipts. Falls back to the nominal terms when there's no history.
    (Terms say 25 days but they pay in 30–31? This captures the real number.)"""
    trades = list(session.exec(select(Trade).where(
        Trade.user_id == user_id, Trade.purchaser_id == customer_id
    )).all())
    lags = []
    for t in trades:
        if not t.delivered_at:
            continue
        pays = [p.paid_on for p in t.payments
                if p.direction == PaymentDirection.INBOUND and p.paid_on]
        if pays:
            lags.append(max(0, (min(pays) - t.delivered_at).days))
    return round(sum(lags) / len(lags)) if lags else int(fallback or 0)


def bank_position_forecast(session, user_id, horizon_days=30, include_funding=True,
                           net_prepaid=False) -> dict:
    """Bank-position forecast (inflows/outflows over the horizon).

    net_prepaid=False (default): projected supply outflows are the GROSS on-order
    cost at the delivery date — consumed by cash_flow_management, which does its
    own stage-split + prepaid netting on top, so it must stay raw here.

    net_prepaid=True (Cash Forecast / Daily Cash reports): stage-split each
    projected supply into advance (now + max delay) / on delivery (arrival + max
    delay) / on credit (arrival + terms + max delay), then net any advance already
    prepaid to that vendor (FIFO, earliest date first) — so the standalone
    forecasts agree with Cash Flow Management and AP Aging.
    """
    from services.trade import TradeService  # lazy import — avoid circular dep
    today = date.today()
    cash_today = _sum_balance(session, [a.id for a in _accounts_in_subclass(session, user_id, "1100")], today)
    # The funding account (CEO) is the real cash conduit — every receipt and
    # payment flows through it. Its balance (credit = money the owner has net
    # advanced) is a NEGATIVE cash position for the business, i.e. a running
    # draw on the owner. Include it so "cash today" reflects the true float
    # instead of Rs 0. balance_asof returns DR−CR, so a credit balance comes
    # through as the negative it should be.
    #
    # include_funding=False treats that already-advanced owner capital as sunk
    # (it's cash already invested, not a shortfall to re-fund) — used by the
    # cash-flow-management planner so the CEO draw doesn't inflate the gap.
    if include_funding:
        for a in session.exec(select(Account).where(Account.user_id == user_id)).all():
            nm = (a.name or "").strip().lower()
            if nm in ("ibrahim (ceo)", "ceo", "funding"):
                cash_today += balance_asof(session, a.id, today)

    all_trades = list(session.exec(select(Trade).where(Trade.user_id == user_id)).all())
    open_trades = [t for t in all_trades if t.status in (
        TradeStatus.OPEN, TradeStatus.DELIVERED, TradeStatus.PARTIALLY_PAID,
    )]

    # ── Inflows, predicted from real behaviour ─────────────────────────────
    # FIRM (goods already delivered): collection date = delivery + this
    #   customer's AVERAGE actual payment lag (not the nominal terms).
    # PROJECTED (open order, not yet delivered): predict the delivery date from
    #   the vendor's average delivery lag, then add the customer's payment lag —
    #   so upcoming deliverables and their value show up in the forecast.
    inflows = []
    proj_outflows = []   # projected vendor purchases for open-order batches
    vendor_queue = {}    # vendor_id -> FIFO list of undelivered order chunks
    for t in sorted(open_trades, key=lambda x: x.trade_date):
        # Expected collection = delivery + payment lag. Never expect payment
        # EARLIER than the invoice terms (so a delivered invoice with 25-day
        # terms shows its real due date, not "today"); but if the customer
        # historically pays LATER than terms, use that longer actual lag.
        pay_lag = max(int(t.customer_terms_days or 0),
                      _avg_payment_lag_days(session, user_id, t.purchaser_id, t.customer_terms_days))

        # Per-delivery events (date → value delivered that day), so an EARLY
        # delivery's invoice is scheduled from ITS own date, not the latest one.
        ev_map = {}
        if t.delivered_at:
            ev_map[t.delivered_at] = ev_map.get(t.delivered_at, ZERO) + Decimal(t.total_sale)
        else:
            for ln in t.lines:
                for r in (ln.receipts or []):
                    ev_map[r.received_on] = ev_map.get(r.received_on, ZERO) + \
                        Decimal(r.received_qty) * Decimal(ln.unit_price)
        events = sorted(ev_map.items())
        deliv_date = events[-1][0] if events else None   # latest delivery (for projected part)

        # FIRM: schedule EACH delivery event across the payment split, applying
        # what's already been paid FIFO (oldest delivery first). So a 17 Jul
        # delivery on 30-day terms is due 16 Aug and a 25 Jul delivery due 24 Aug
        # — as separate collections, not one lump at the latest date.
        paid_total = Decimal(t.paid_by_customer) + TradeService._customer_credits(session, t)
        rem_paid = paid_total
        for ev_date, ev_value in events:
            applied = min(ev_value, rem_paid) if rem_paid > 0 else ZERO
            rem_paid -= applied
            ev_out = ev_value - applied
            if ev_out <= Decimal("0.005"):
                continue
            for stg in TradeService.payment_schedule(t, "customer", total=ev_out, delivery_date=ev_date):
                amt = Decimal(stg["amount"])
                if amt <= Decimal("0.005") or not stg["date"]:
                    continue
                due = stg["date"]
                if stg["stage"] == "credit":
                    due = ev_date + timedelta(days=pay_lag)
                inflows.append({"trade": t, "amount": amt.quantize(Decimal("0.01")),
                                "days_out": (due - today).days, "due_date": due,
                                "kind": "delivered"})

        # PROJECTED: collect undelivered goods into a per-vendor FIFO QUEUE.
        # We DON'T schedule per-trade here — instead (below) each vendor delivers
        # its whole backlog at its real throughput, oldest orders first. That
        # way, if several orders are overdue, they clear over the coming weeks
        # at the vendor's pace rather than all landing today.
        und_qty = und_value = und_cost = ZERO
        for ln in t.lines:
            recv = sum((Decimal(r.received_qty) for r in (ln.receipts or [])), ZERO)
            uq = Decimal(ln.quantity) - recv
            if uq > 0:
                und_qty += uq
                und_value += uq * Decimal(ln.unit_price)
                und_cost += uq * Decimal(ln.unit_cost)
        if und_qty > 0:
            vendor_queue.setdefault(t.vendor_id, []).append({
                "trade": t, "qty": und_qty, "value": und_value,
                "cost": und_cost, "pay_lag": pay_lag,
            })

    # ── Deliver each vendor's backlog at their real throughput ─────────────
    # batch size + interval learned from history; the next batch is scheduled
    # from the vendor's LAST actual delivery + interval (or today if they're
    # already behind), then every interval after. Oldest orders fill first.
    for vendor_id, queue in vendor_queue.items():
        # Trades with an OWNER-SET expected arrival date are scheduled exactly on
        # that date (overrides any history-based guess); the rest fall back to the
        # vendor's learned throughput below.
        dated = [it for it in queue if getattr(it["trade"], "expected_delivery_date", None)]
        for item in dated:
            est_delivery = max(today, item["trade"].expected_delivery_date)
            proj_outflows.append({"label": vendor_id, "ref": item["trade"].reference,
                                  "trade_id": item["trade"].id,
                                  "amount": item["cost"].quantize(Decimal("0.01")),
                                  "days_out": (est_delivery - today).days,
                                  "due_date": est_delivery, "kind": "projected"})
            collect = est_delivery + timedelta(days=item["pay_lag"])
            inflows.append({"trade": item["trade"], "amount": item["value"].quantize(Decimal("0.01")),
                            "days_out": (collect - today).days, "due_date": collect,
                            "kind": "projected"})
        queue = [it for it in queue if not getattr(it["trade"], "expected_delivery_date", None)]
        if not queue:
            continue
        first_lag, batch_qty, interval = _vendor_delivery_profile(session, user_id, vendor_id)
        total_und = sum((item["qty"] for item in queue), ZERO)
        if not batch_qty or batch_qty <= 0:
            batch_qty = total_und or Decimal("1")
        last_deliv = _last_delivery_date(session, user_id, vendor_id)
        if last_deliv:
            first_batch = max(today, last_deliv + timedelta(days=interval))
        else:
            first_batch = today + timedelta(days=first_lag)
        idx = 0
        rem_item = queue[0]["qty"] if queue else ZERO
        batch_no = 0
        while idx < len(queue) and batch_no < 60:
            est_delivery = first_batch + timedelta(days=int(batch_no * interval))
            batch_rem = batch_qty
            while batch_rem > 0 and idx < len(queue):
                item = queue[idx]
                take = min(batch_rem, rem_item)
                frac = (take / item["qty"]) if item["qty"] else ZERO
                cost_part = item["cost"] * frac
                value_part = item["value"] * frac
                proj_outflows.append({"label": vendor_id, "ref": item["trade"].reference,
                                      "trade_id": item["trade"].id,
                                      "amount": cost_part.quantize(Decimal("0.01")),
                                      "days_out": (est_delivery - today).days,
                                      "due_date": est_delivery, "kind": "projected"})
                collect = est_delivery + timedelta(days=item["pay_lag"])
                inflows.append({"trade": item["trade"], "amount": value_part.quantize(Decimal("0.01")),
                                "days_out": (collect - today).days, "due_date": collect,
                                "kind": "projected"})
                batch_rem -= take
                rem_item -= take
                if rem_item <= 0:
                    idx += 1
                    rem_item = queue[idx]["qty"] if idx < len(queue) else ZERO
            batch_no += 1

    # ── Outflows: what we ACTUALLY still owe each vendor, from the ledger — not
    # total_cost. Vendor payments are made from the funding account (journal
    # entries), so per-trade paid_to_vendor is 0 and would wildly overstate what
    # is due. The true payable is the vendor's current credit balance. ──
    vendor_pids = {t.vendor_id for t in all_trades if t.vendor_id}
    parties = list(session.exec(select(Party).where(Party.user_id == user_id)).all())
    vendor_name = {p.id: p.name for p in parties}
    outflows = []
    for p in parties:
        if p.id not in vendor_pids or not p.account_id:
            continue
        owed = -balance_asof(session, p.account_id, today)   # CR-positive → we owe
        if owed <= 0:
            continue
        # Stage this vendor's CURRENT ledger balance across the payment SPLIT
        # (advance/on-delivery/credit) of its open trades. Build each trade's
        # stage schedule on its RECEIVED (posted) cost — so the gross matches the
        # ledger — then apply what's already been paid (gross − owed) to the
        # earliest stages and schedule the rest at their split dates (overdue →
        # today). Any residual not covered by splits lands at "now".
        stages = []
        gross = ZERO
        for t in open_trades:
            if t.vendor_id != p.id:
                continue
            recv_cost = ZERO
            recdates = []
            for ln in t.lines:
                rq = sum((Decimal(r.received_qty) for r in (ln.receipts or [])), ZERO)
                if rq > 0:
                    recv_cost += rq * Decimal(ln.unit_cost)
                    recdates += [r.received_on for r in (ln.receipts or [])]
            if recv_cost <= 0:
                continue
            dv = t.delivered_at or (max(recdates) if recdates else None)
            for st in TradeService.payment_schedule(t, "vendor", total=recv_cost, delivery_date=dv):
                if st["date"]:
                    stages.append({"date": st["date"], "amount": Decimal(st["amount"]),
                                   "ref": t.reference, "trade_id": t.id})
                    gross += Decimal(st["amount"])
        stages.sort(key=lambda s: s["date"])
        rem_paid = gross - owed
        if rem_paid < 0:
            rem_paid = ZERO
        scheduled = ZERO
        for st in stages:
            applied = min(st["amount"], rem_paid) if rem_paid > 0 else ZERO
            rem_paid -= applied
            out = st["amount"] - applied
            if out > Decimal("0.005"):
                due = max(today, st["date"])
                outflows.append({"label": p.name, "vendor": p.name,
                                 "ref": st["ref"], "trade_id": st["trade_id"],
                                 "amount": out.quantize(Decimal("0.01")),
                                 "days_out": (due - today).days, "due_date": due,
                                 "kind": "delivered"})
                scheduled += out
        leftover = owed - scheduled
        if leftover > Decimal("0.005"):
            outflows.append({"label": p.name, "vendor": p.name, "ref": None, "trade_id": None,
                             "amount": leftover.quantize(Decimal("0.01")),
                             "days_out": 0, "due_date": today, "kind": "delivered"})

    # Optionally re-stage projected supply (advance/on-delivery/on-credit, each on
    # its own due date + the vendor's max-payment stretch) and net any advance
    # already prepaid to that vendor — so the standalone forecasts match the Cash
    # Flow Management planner. Left off by default (cash_flow_management re-stages
    # the raw gross chunks itself and would otherwise double-count).
    if net_prepaid:
        EPS = Decimal("0.005")
        delay_by_vid = {p.id: max(0, int(getattr(p, "max_payment_delay_days", 1) or 1))
                        for p in parties}
        staged = []
        for o in proj_outflows:
            t = session.get(Trade, o["trade_id"]) if o.get("trade_id") else None
            cost = Decimal(o["amount"])
            dd = o["due_date"]
            if not t:
                staged.append(dict(o)); continue
            adv = Decimal(t.vend_advance_pct or 0)
            dely = Decimal(t.vend_delivery_pct or 0)
            cred = Decimal(t.vend_credit_pct or 0)
            tot = adv + dely + cred
            if tot <= 0:
                dely, cred, tot = Decimal("100"), ZERO, Decimal("100")
            cdays = int(t.vendor_terms_days or 0)
            dly = timedelta(days=delay_by_vid.get(t.vendor_id, 1))
            for stage, pct, sdate in (
                ("advance", adv, today),
                ("on delivery", dely, dd),
                ("on credit", cred, dd + timedelta(days=cdays)),
            ):
                amt = cost * pct / tot
                if amt > Decimal("0.5"):
                    due = max(today, sdate + dly)
                    staged.append({**o, "amount": amt.quantize(Decimal("0.01")),
                                   "due_date": due, "days_out": (due - today).days,
                                   "stage": stage})
        prepaid_by_vid = {}
        for p in parties:
            if p.account_id:
                bal = balance_asof(session, p.account_id, today)
                if bal > EPS:
                    prepaid_by_vid[p.id] = bal
        staged.sort(key=lambda x: x["due_date"])
        netted = []
        for o in staged:
            vid = o["label"]
            amt = Decimal(o["amount"])
            avail = prepaid_by_vid.get(vid, ZERO)
            if avail > EPS:
                applied = avail if avail < amt else amt
                prepaid_by_vid[vid] = avail - applied
                amt -= applied
            if amt > EPS:
                netted.append({**o, "amount": amt.quantize(Decimal("0.01"))})
        proj_outflows = netted

    # PROJECTED outflows: the per-batch cost of buying goods for open orders
    # (built alongside the projected inflows above, at the vendor's real
    # delivery cadence). Resolve the vendor id to a name for display.
    for o in proj_outflows:
        vname = vendor_name.get(o['label'], 'Vendor')
        outflows.append({
            "label": f"{vname} · {o['ref']}",
            "vendor": vname, "ref": o["ref"], "trade_id": o.get("trade_id"),
            "amount": o["amount"], "days_out": o["days_out"],
            "due_date": o["due_date"], "kind": "projected",
        })

    buckets = {30: cash_today, 60: cash_today, 90: cash_today}
    for h in buckets:
        for f in inflows:
            if f["days_out"] <= h:
                buckets[h] += f["amount"]
        for o in outflows:
            if o["days_out"] <= h:
                buckets[h] -= o["amount"]

    inflows.sort(key=lambda r: r["days_out"])
    outflows.sort(key=lambda r: r["days_out"])
    # Warn only if the position drops BELOW where it is today (a genuine extra
    # shortfall needing more funding) — not merely because deployed capital
    # leaves the float negative while it's still recovering.
    floor = min(cash_today, ZERO)
    return {
        "today": today,
        "cash_today": cash_today.quantize(Decimal("0.01")),
        "projected": {h: v.quantize(Decimal("0.01")) for h, v in buckets.items()},
        "inflows": inflows,
        "outflows": outflows,
        "negative_at": next((h for h in sorted(buckets) if buckets[h] < floor), None),
    }


def daily_cash_requirement(session, user_id, horizon_days=30) -> dict:
    """Day-by-day cash requirement, starting from ZERO cash (the owner's CEO
    funding is deliberately ignored — this answers 'how much external cash must
    I put in, and when'). Reuses the smart batch-based inflows/outflows: each
    day nets collections against payments; whenever the running balance dips
    below zero, that dip is cash you must inject by that day.
    """
    fc = bank_position_forecast(session, user_id, net_prepaid=True)
    today = date.today()
    end = today + timedelta(days=horizon_days)

    # Bucket each cash event onto a day; overdue items land on today.
    per_day: dict = {}
    for f in fc["inflows"]:
        d = f["due_date"] if f["due_date"] > today else today
        if d <= end:
            per_day.setdefault(d, {"in": ZERO, "out": ZERO})["in"] += Decimal(f["amount"])
    for o in fc["outflows"]:
        d = o["due_date"] if o["due_date"] > today else today
        if d <= end:
            per_day.setdefault(d, {"in": ZERO, "out": ZERO})["out"] += Decimal(o["amount"])

    rows = []
    running = ZERO          # cash on hand assuming NO owner funding
    peak_shortfall = ZERO   # cumulative funding needed so far
    total_in = total_out = ZERO
    d = today
    while d <= end:
        day = per_day.get(d, {"in": ZERO, "out": ZERO})
        cin, cout = day["in"], day["out"]
        net = cin - cout
        running += net
        total_in += cin
        total_out += cout
        shortfall = -running if running < 0 else ZERO
        extra_today = shortfall - peak_shortfall if shortfall > peak_shortfall else ZERO
        peak_shortfall = max(peak_shortfall, shortfall)
        if cin or cout or d == today:   # keep active days (and always day 0)
            rows.append({
                "date": d,
                "days_out": (d - today).days,
                "cash_in": cin.quantize(Decimal("0.01")),
                "cash_out": cout.quantize(Decimal("0.01")),
                "net": net.quantize(Decimal("0.01")),
                "running": running.quantize(Decimal("0.01")),
                "extra_needed": extra_today.quantize(Decimal("0.01")),
                "funding_to_date": shortfall.quantize(Decimal("0.01")),
            })
        d += timedelta(days=1)

    # The day the funding requirement peaks (max cash you'll ever be down).
    peak_day = None
    running2 = ZERO
    worst = ZERO
    d = today
    while d <= end:
        day = per_day.get(d, {"in": ZERO, "out": ZERO})
        running2 += day["in"] - day["out"]
        if running2 < worst:
            worst = running2
            peak_day = d
        d += timedelta(days=1)

    return {
        "today": today,
        "horizon_days": horizon_days,
        "rows": rows,
        "peak_funding_needed": peak_shortfall.quantize(Decimal("0.01")),
        "peak_day": peak_day,
        "ending_balance": running.quantize(Decimal("0.01")),
        "total_in": total_in.quantize(Decimal("0.01")),
        "total_out": total_out.quantize(Decimal("0.01")),
    }


# ──────────────────────── Order Projection (cash planner) ────────────────────────


def order_projection(session, user_id) -> dict:
    """Dated cash-requirement calendar for a set of PLANNED (not-yet-committed)
    orders. Each line has its own order date; money flows on real calendar dates:

      • dye/block         → paid on the order date
      • purchase (vendor) → split by percentage into
            advance      (order date),
            on-delivery  (order date + lead days),
            credit       (delivery + credit days)
      • bilty             → paid at delivery
      • sale (customer)   → collected at delivery + collection lag

    We collect every movement on its date, then walk the dated events from a
    zero-cash start to find the PEAK cash you'd need and when you recover.
    Only dates that actually have movement produce a row, and each row carries
    the list of receipts / payments happening that day.
    """
    from models import ProjectionLine
    lines = list(session.exec(
        select(ProjectionLine).where(ProjectionLine.user_id == user_id)
        .order_by(ProjectionLine.sort_order, ProjectionLine.id)
    ).all())
    active = [ln for ln in lines if ln.include]

    today = date.today()
    # date -> {"in": Decimal, "out": Decimal, "events": [ {dir, text, amount} ]}
    per_date: dict = {}

    def add(d: date, key: str, amount: Decimal, text: str):
        if amount is None or amount <= 0:
            return
        slot = per_date.setdefault(d, {"in": ZERO, "out": ZERO, "events": []})
        slot[key] += amount
        slot["events"].append({
            "dir": "in" if key == "in" else "out",
            "text": text,
            "amount": amount.quantize(Decimal("0.01")),
        })

    total_purchase = total_dye = total_bilty = total_sale = total_qty = ZERO
    for ln in active:
        qty = Decimal(ln.quantity)
        total_qty += qty
        purchase = qty * Decimal(ln.purchase_rate)
        sale = qty * Decimal(ln.sale_rate)
        # one-time dye/block — excluded from cash-out and KPIs when toggled off
        # (models the next cycle where the block is already paid for).
        dye = Decimal(ln.dye_block_cost) if getattr(ln, "dye_active", True) else ZERO
        bilty = Decimal(ln.bilty)
        lead = int(ln.lead_days or 0)
        collect_lag = int(ln.collection_lag_days or 0)
        credit_lag = int(ln.credit_days or 0)
        order_d = ln.order_date or today
        delivery_d = order_d + timedelta(days=lead)
        name = ln.item_name or "order"

        # normalise the vendor payment split so the purchase is always fully paid
        adv = Decimal(ln.pct_advance or 0)
        dely = Decimal(ln.pct_on_delivery or 0)
        cred = Decimal(ln.pct_credit or 0)
        tot_pct = adv + dely + cred
        if tot_pct <= 0:
            adv, dely, cred = ZERO, Decimal("100"), ZERO
            tot_pct = Decimal("100")

        add(order_d, "out", dye, f"Pay {name} — dye/block")
        add(order_d, "out", purchase * adv / tot_pct, f"Pay {name} — advance")
        add(delivery_d, "out", purchase * dely / tot_pct, f"Pay {name} — on delivery")
        add(delivery_d + timedelta(days=credit_lag), "out",
            purchase * cred / tot_pct, f"Pay {name} — credit")
        add(delivery_d, "out", bilty, f"Pay {name} — bilty")
        add(delivery_d + timedelta(days=collect_lag), "in", sale, f"Collect {name}")

        total_purchase += purchase
        total_dye += dye
        total_bilty += bilty
        total_sale += sale

    total_out = total_purchase + total_dye + total_bilty
    net_profit = (total_sale - total_out).quantize(Decimal("0.01"))
    roi_pct = (net_profit / total_out * 100).quantize(Decimal("0.01")) if total_out > 0 else ZERO
    # average net profit earned on each piece across the whole batch
    profit_per_unit = (net_profit / total_qty).quantize(Decimal("0.01")) if total_qty > 0 else ZERO

    rows = []
    running = ZERO
    peak_shortfall = ZERO
    peak_day = None
    peak_date = None
    recovery_day = None
    recovery_date = None
    for d in sorted(per_date.keys()):
        slot = per_date[d]
        cin, cout = slot["in"], slot["out"]
        net = cin - cout
        running += net
        offset = (d - today).days
        shortfall = -running if running < 0 else ZERO
        extra = shortfall - peak_shortfall if shortfall > peak_shortfall else ZERO
        if shortfall > peak_shortfall:
            peak_shortfall = shortfall
            peak_day = offset
            peak_date = d
        if recovery_day is None and peak_shortfall > 0 and running >= 0:
            recovery_day = offset
            recovery_date = d
        rows.append({
            "day": offset,
            "date": d,
            "cash_in": cin.quantize(Decimal("0.01")),
            "cash_out": cout.quantize(Decimal("0.01")),
            "net": net.quantize(Decimal("0.01")),
            "running": running.quantize(Decimal("0.01")),
            "extra_needed": extra.quantize(Decimal("0.01")),
            "events": slot["events"],
        })

    return {
        "lines": lines,
        "active_count": len(active),
        "rows": rows,
        "peak_funding": peak_shortfall.quantize(Decimal("0.01")),
        "peak_day": peak_day,
        "peak_date": peak_date,
        "recovery_day": recovery_day,
        "recovery_date": recovery_date,
        "ending_balance": running.quantize(Decimal("0.01")),
        "total_purchase": total_purchase.quantize(Decimal("0.01")),
        "total_dye": total_dye.quantize(Decimal("0.01")),
        "total_bilty": total_bilty.quantize(Decimal("0.01")),
        "total_investment": total_out.quantize(Decimal("0.01")),
        "total_sale": total_sale.quantize(Decimal("0.01")),
        "net_profit": net_profit,
        "roi_pct": roi_pct,
        "total_qty": total_qty.quantize(Decimal("0.01")),
        "profit_per_unit": profit_per_unit,
    }


def _vendor_pay_tier(trades, tenure_days):
    """Smart, non-binding priority for splitting incoming cash across vendors.
    NEWER vendors (few trades / short relationship) are favoured — they get a
    bigger slice of each receipt relative to what they're owed. LONG-STANDING
    vendors have more goodwill, so we can push their credit and pay them a
    smaller proportional slice. Returns (tier_key, weight_multiplier, reason)."""
    if trades <= 1 or tenure_days <= 30:
        return ("new", Decimal("2.0"), "New vendor — pay on priority")
    if trades == 2 or tenure_days <= 75:
        return ("recent", Decimal("1.5"), "Recent vendor — favour in the split")
    if trades <= 5:
        return ("growing", Decimal("1.15"), "Growing relationship")
    return ("established", Decimal("0.9"), "Long-standing — credit can be pushed")


def cash_flow_management(session, user_id, horizon_days=120,
                         inject_amount=None, inject_on=None, delay_overrides=None) -> dict:
    """Smart payment instructions for the EXISTING trades (no projection).

    The report answers one question: as customer money lands, exactly how much
    should I hand to each vendor so NOBODY gets starved? It

      • lists every receipt you expect (from delivered/open existing trades),
      • takes what you currently owe each vendor (from the ledger), and
      • on each receipt date, distributes the cash on hand across ALL vendors
        with a balance — proportional to what they're owed, but WEIGHTED so
        newer vendors are favoured and long-standing vendors are pushed a bit.

    Every vendor with a balance gets a slice of each disbursement (they can get
    proportionally less than due, but never zero), and the split tilts toward
    new relationships. Output is a dated list of "collect X → pay A/B/C" steps.
    """
    from collections import defaultdict
    cent = Decimal("0.01")
    eps = Decimal("0.01")
    today = date.today()
    fc = bank_position_forecast(session, user_id, horizon_days, include_funding=True)
    cash_today = Decimal(fc["cash_today"])

    parties = list(session.exec(select(Party).where(Party.user_id == user_id)).all())
    party_name = {p.id: p.name for p in parties}
    # Max days each vendor's payable can be stretched past its due date before
    # cash must be found. Payables are deferred by this much, so the plan uses
    # collections up to the deadline and only then flags an injection.
    # `delay_overrides` (party_id -> days) lets the UI slider preview a what-if
    # without persisting — it wins over the stored setting for that vendor.
    delay_overrides = delay_overrides or {}
    delay_by_name = {}
    for p in parties:
        d = max(0, int(getattr(p, "max_payment_delay_days", 1) or 1))
        if p.id in delay_overrides:
            d = max(0, int(delay_overrides[p.id]))
        delay_by_name[p.name] = d
    def _delay(name):
        return timedelta(days=delay_by_name.get(name, 1))

    # ── how long / how much we've traded with each vendor (relationship depth) ──
    all_trades = list(session.exec(
        select(Trade).where(Trade.user_id == user_id,
                            Trade.status != TradeStatus.CANCELLED)).all())
    v_trades = defaultdict(int)
    v_first = {}
    for t in all_trades:
        if not t.vendor_id:
            continue
        v_trades[t.vendor_id] += 1
        if t.vendor_id not in v_first or t.trade_date < v_first[t.vendor_id]:
            v_first[t.vendor_id] = t.trade_date

    # ── what we owe each vendor across their open trades (current ledger debt +
    #    the cost of goods still on order), grouped by vendor, with earliest due ──
    name_to_pid = {p.name: p.id for p in parties}
    ref_by_vendor = defaultdict(list)
    agg = defaultdict(lambda: {"owed": ZERO, "due": None})
    for o in fc["outflows"]:
        # Owed = what the LEDGER shows we owe (advance accrued at trade open +
        # goods received but unpaid). Exclude projected future purchases for
        # goods still on order — those aren't a debt until received/advanced.
        if o.get("kind") == "projected":
            continue
        name = o.get("vendor") or o.get("label")
        a = agg[name]
        a["owed"] += Decimal(o["amount"])
        d = o.get("due_date")
        if d is not None and (a["due"] is None or d < a["due"]):
            a["due"] = d
        if o.get("ref"):
            ref_by_vendor[name].append((o.get("trade_id"), o.get("ref")))

    vendors = []
    for name, a in agg.items():
        if a["owed"] <= eps:
            continue
        pid = name_to_pid.get(name)
        trades = v_trades.get(pid, 0)
        tenure = (today - v_first[pid]).days if pid in v_first else 0
        tier, mult, reason = _vendor_pay_tier(trades, tenure)
        vendors.append({
            "id": pid if pid is not None else name, "name": name,
            "trades": trades, "tenure_days": tenure,
            "tier": tier, "mult": mult, "reason": reason,
            "owed": a["owed"].quantize(cent), "remaining": a["owed"],
            "due_date": a["due"],
        })
    total_owed = sum((v["owed"] for v in vendors), ZERO)

    # ── receipts: money coming in, grouped per date, with its customer sources ──
    rp = defaultdict(lambda: {"amount": ZERO, "sources": {}, "days_out": 0})

    def _add_src(slot, name, ref, tid, amt):
        s = slot["sources"].get((name, ref))
        if s is None:
            s = {"trade_id": tid, "amount": ZERO}
            slot["sources"][(name, ref)] = s
        s["amount"] += amt

    for f in fc["inflows"]:
        t = f.get("trade")
        if t is not None:
            cust = party_name.get(getattr(t, "purchaser_id", None), "customer")
            ref = getattr(t, "reference", "") or ""
            tid = getattr(t, "id", None)
        else:
            cust, ref, tid = "trade", "", None
        key = max(today, f["due_date"])       # overdue receivables collapse to "now"
        amt = Decimal(f["amount"])
        rp[key]["amount"] += amt
        rp[key]["days_out"] = max(0, (key - today).days)
        _add_src(rp[key], cust, ref, tid, amt)

    receipts = [
        {"date": d, "amount": v["amount"], "days_out": v["days_out"],
         "sources": [{"name": k[0], "ref": k[1], "trade_id": val["trade_id"],
                      "amount": val["amount"].quantize(cent)}
                     for k, val in sorted(v["sources"].items(), key=lambda x: -x[1]["amount"])]}
        for d, v in sorted(rp.items()) if v["amount"] > 0
    ]

    total_to_collect = sum((r["amount"] for r in receipts), ZERO)

    # ── Projected upcoming vendor payables ─────────────────────────────────
    # For goods still ON ORDER, the on-delivery + credit portions that will
    # fall due WHEN they arrive (the advance portion is already in the hard
    # 'owed' above). Delivery timing is predicted from each vendor's historical
    # supply cadence (bank_position_forecast projected outflows); the amount is
    # split by that trade's vendor terms. Kept SEPARATE from hard owed — it's an
    # estimate, not a booked debt.
    proj_by_trade = defaultdict(list)
    for o in fc["outflows"]:
        if o.get("kind") == "projected" and o.get("trade_id"):
            proj_by_trade[o["trade_id"]].append((o["due_date"], Decimal(o["amount"])))
    projected = []
    projected_total = ZERO
    trade_cache = {}
    for tid, chunks in proj_by_trade.items():
        t = trade_cache.get(tid) or session.get(Trade, tid)
        if not t:
            continue
        trade_cache[tid] = t
        vname = party_name.get(t.vendor_id, "vendor")
        adv = Decimal(t.vend_advance_pct or 0)
        dely = Decimal(t.vend_delivery_pct or 0)
        cred = Decimal(t.vend_credit_pct or 0)
        tot = adv + dely + cred
        if tot <= 0:
            dely, cred, tot = Decimal("100"), ZERO, Decimal("100")
        cdays = int(t.vendor_terms_days or 0)
        for ddate, cost in chunks:
            # Three real stages, each on its own date. The advance % is due NOW
            # (the order is already placed) — dated today so the timeline's
            # +max-delay stretch lands it at "now + max delay". Delivery is due
            # when the goods arrive; the credit tail at arrival + terms. What
            # you've already pre-paid is the vendor's DR balance, netted below
            # (earliest date first, so it clears the advance before delivery) —
            # do NOT drop the advance portion or the prepaid gets credited twice.
            av = cost * adv / tot
            od = cost * dely / tot
            cr = cost * cred / tot
            if av > Decimal("0.5"):
                projected.append({"date": today, "vendor": vname,
                                  "amount": av.quantize(cent), "ref": t.reference,
                                  "trade_id": tid, "stage": "advance"})
                projected_total += av
            if od > Decimal("0.5"):
                projected.append({"date": max(today, ddate), "vendor": vname,
                                  "amount": od.quantize(cent), "ref": t.reference,
                                  "trade_id": tid, "stage": "on delivery"})
                projected_total += od
            if cr > Decimal("0.5"):
                cd = max(today, ddate + timedelta(days=cdays))
                projected.append({"date": cd, "vendor": vname,
                                  "amount": cr.quantize(cent), "ref": t.reference,
                                  "trade_id": tid,
                                  "stage": "on credit" if cdays == 0 else f"on credit +{cdays}d"})
                projected_total += cr
    # Credit any ADVANCE already prepaid to a vendor (a DR balance on their A/P)
    # against their upcoming supply payments — you don't pay twice for goods you
    # already funded. Applied to the earliest projected chunks first.
    _acct_by_name = {pp.name: pp.account_id for pp in parties}
    _prepaid = {}
    for vname in {p["vendor"] for p in projected}:
        aid = _acct_by_name.get(vname)
        if aid:
            bal = balance_asof(session, aid, today)   # DR − CR ; DR (>0) = we've prepaid
            if bal > eps:
                _prepaid[vname] = bal
    if _prepaid:
        _adj = []
        for p in sorted(projected, key=lambda x: x["date"]):
            avail = _prepaid.get(p["vendor"], ZERO)
            if avail > eps:
                applied = avail if avail < p["amount"] else p["amount"]
                _prepaid[p["vendor"]] = avail - applied
                net = p["amount"] - applied
                if net > eps:
                    q = dict(p)
                    q["amount"] = net.quantize(cent)
                    _adj.append(q)
            else:
                _adj.append(p)
        projected = _adj
        projected_total = sum((p["amount"] for p in projected), ZERO)

    # Per-trade payment schedule (post-prepaid), each stage on the date it is
    # actually DUE = its stage date + the vendor's max-payment stretch. Lets the
    # "Expected supply arrivals" section show, per trade, "advance Rs X due <now +
    # max delay>", "on delivery Rs Y due <arrival + max delay>".
    proj_sched_by_trade = defaultdict(list)
    for p in projected:
        proj_sched_by_trade[p["trade_id"]].append({
            "stage": p.get("stage", ""),
            "amount": p["amount"].quantize(cent),
            "due": max(today, p["date"] + _delay(p["vendor"])),
        })
    for tid in proj_sched_by_trade:
        proj_sched_by_trade[tid].sort(key=lambda x: x["due"])

    proj_by_date = defaultdict(lambda: {"amount": ZERO, "items": []})
    for p in projected:
        slot = proj_by_date[p["date"]]
        slot["amount"] += p["amount"]
        slot["items"].append(p)
    projected_pointers = [
        {"date": d, "days_out": max(0, (d - today).days),
         "amount": v["amount"].quantize(cent),
         "items": sorted(v["items"], key=lambda x: -x["amount"])}
        for d, v in sorted(proj_by_date.items())
    ]

    # ── Recommended capital injection ──────────────────────────────────────
    # Simulate meeting EVERY obligation by its due date (hard owed at its
    # earliest due date + projected payables at theirs), funded by receipts plus
    # any spare cash today. The deepest the running balance dips is the extra
    # capital you'd need to inject, and by when.
    # A capital injection the owner plans to make (amount + date) is treated as
    # cash arriving on that date; the recommended figure below becomes the
    # RESIDUAL still needed after it.
    inj_amt = Decimal(str(inject_amount)) if inject_amount else ZERO
    if inj_amt < 0:
        inj_amt = ZERO
    inj_when = max(today, inject_on) if (inj_amt > 0 and inject_on) else today
    # (the capital-injection figure is derived from the cash-flow timeline below)

    # ── Unified obligation plan: current owed (due now / by terms) AND the
    #    projected supply payments (due when goods land) are ONE pool. Each
    #    obligation "activates" on its due date; receipts + carried cash are then
    #    split across whatever is currently due, weighted to favour new vendors. ──
    def _meta(pid, name):
        trades = v_trades.get(pid, 0) if pid is not None else 0
        tenure = (today - v_first[pid]).days if (pid is not None and pid in v_first) else 0
        tier, mult, reason = _vendor_pay_tier(trades, tenure)
        return {"name": name, "tier": tier, "mult": mult, "reason": reason,
                "trades": trades, "tenure_days": tenure}

    # ── Per-vendor PLAN TRACKER (also seeds the obligation plan below) ───────
    # The plan is a FIXED staged schedule to clear each vendor (built on the
    # received cost × the trade's payment split). As you actually pay — by ANY
    # means that hits the ledger (a vendor payment, or a customer settling the
    # vendor direct) — those payments TICK OFF the schedule from the front.
    # Progress needs no saved state: paid = plan_total − current ledger owed, so
    # it self-updates every open. The UNPAID slices (with their real due dates)
    # then drive the "collect → pay out" plan, so it's payment-aware: paid slices
    # are already disbursed and never re-instructed.
    from services.trade import TradeService  # lazy import — avoid circular dep
    acct_by_pid = {p.id: p.account_id for p in parties}
    vplan_stages = defaultdict(list)
    for t in all_trades:
        if not t.vendor_id or t.status == TradeStatus.CANCELLED:
            continue
        recv_cost = ZERO
        recdates = []
        for ln in t.lines:
            rq = sum((Decimal(r.received_qty) for r in (ln.receipts or [])), ZERO)
            if rq > 0:
                recv_cost += rq * Decimal(ln.unit_cost)
                recdates += [r.received_on for r in (ln.receipts or [])]
        if recv_cost <= 0:
            continue
        dv = t.delivered_at or (max(recdates) if recdates else None)
        for stg in TradeService.payment_schedule(t, "vendor", total=recv_cost, delivery_date=dv):
            if stg["date"]:
                vplan_stages[t.vendor_id].append({
                    "date": stg["date"], "amount": Decimal(stg["amount"]),
                    "ref": t.reference, "trade_id": t.id, "stage": stg.get("stage") or "",
                })

    vendor_plans = []
    for pid, stages in vplan_stages.items():
        gross = sum((s["amount"] for s in stages), ZERO)
        if gross <= eps:
            continue
        aid = acct_by_pid.get(pid)
        owed = (-balance_asof(session, aid, today)) if aid else gross
        if owed < 0:
            owed = ZERO
        paid = gross - owed
        if paid < 0:
            paid = ZERO
        if paid > gross:
            paid = gross
        remaining = gross - paid
        name = party_name.get(pid, "vendor")
        meta = _meta(pid, name)
        stages.sort(key=lambda s: (s["date"], s["ref"]))
        rem = paid
        sched = []
        for s in stages:
            amt = s["amount"]
            if rem >= amt - eps:
                status, pd = "paid", amt
                rem -= amt
            elif rem > eps:
                status, pd = "partial", rem
                rem = ZERO
            else:
                status, pd = "pending", ZERO
            sched.append({
                "date": s["date"], "days_out": (s["date"] - today).days,
                "overdue": s["date"] < today and status != "paid",
                "amount": amt.quantize(cent), "paid": pd.quantize(cent),
                "outstanding": (amt - pd).quantize(cent),
                "status": status, "ref": s["ref"], "trade_id": s["trade_id"],
                "stage": s["stage"],
            })
        vendor_plans.append({
            "id": pid, "name": name, "tier": meta["tier"], "reason": meta["reason"],
            "trades": meta["trades"], "tenure_days": meta["tenure_days"],
            "plan_total": gross.quantize(cent), "paid": paid.quantize(cent),
            "remaining": remaining.quantize(cent),
            "pct_paid": int(paid / gross * 100) if gross > 0 else 0,
            "done": remaining <= eps,
            "schedule": sched,
        })
    # active plans first (most still-to-pay on top), fully-cleared ones last
    vendor_plans.sort(key=lambda v: (v["done"], -v["remaining"]))
    plan_by_vid = {vp["id"]: vp for vp in vendor_plans}

    # ── STABLE CHECKLIST: one flat chronological list you follow top-to-bottom.
    # The amounts are FIXED (each trade's received cost × its payment split), so
    # making a payment NEVER reshuffles the numbers — it only advances the ✓ (a
    # paid slice moves from ○ to ✓). This is the "follow the plan, watch it get
    # followed, not rebuilt" view. Sorted by due date.
    plan_steps = []
    for vp in vendor_plans:
        for sl in vp["schedule"]:
            plan_steps.append({
                "date": sl["date"], "days_out": sl["days_out"], "overdue": sl["overdue"],
                "vendor": vp["name"], "tier": vp["tier"], "reason": vp["reason"],
                "amount": sl["amount"], "paid": sl["paid"], "outstanding": sl["outstanding"],
                "status": sl["status"], "ref": sl["ref"], "trade_id": sl["trade_id"],
            })
    plan_steps.sort(key=lambda s: (s["date"], s["vendor"]))
    plan_total_amount = sum((s["amount"] for s in plan_steps), ZERO)
    plan_paid_amount = sum((s["paid"] for s in plan_steps), ZERO)

    # ── CASH-FLOW TIMELINE (running balance) — the heart of the report ───────
    # Merge every payment DUE (unpaid payables + projected supply) and every
    # collection EXPECTED, by date, and walk a running balance from the cash you
    # actually have. Where it dips is the working capital you must float; the
    # deepest dip is the capital to inject, and it recovers when collections
    # catch up. Paying a vendor just removes that outflow — the dip shrinks.
    # Nothing reshuffles: amounts are the real ledger balances, by real dates.
    start_cash = _sum_balance(
        session, [a.id for a in _accounts_in_subclass(session, user_id, "1100")], today)

    ev = defaultdict(lambda: {"in": ZERO, "out": ZERO, "in_items": [], "out_items": []})
    for vp in vendor_plans:                       # OUT: unpaid payables, by due date (+ max stretch)
        for sl in vp["schedule"]:
            if sl["outstanding"] > eps:
                d = max(today, sl["date"] + _delay(vp["name"]))
                ev[d]["out"] += sl["outstanding"]
                ev[d]["out_items"].append({"name": vp["name"], "tier": vp["tier"],
                    "ref": sl["ref"], "trade_id": sl["trade_id"],
                    "amount": sl["outstanding"].quantize(cent), "kind": "owed"})
    for p in projected:                           # OUT: projected supply (goods on order)
        d = max(today, p["date"] + _delay(p["vendor"]))
        ev[d]["out"] += p["amount"]
        ev[d]["out_items"].append({"name": p["vendor"], "tier": None,
            "ref": p["ref"], "trade_id": p["trade_id"],
            "amount": p["amount"].quantize(cent), "kind": "projected", "stage": p.get("stage", "")})
    for r in receipts:                            # IN: expected collections
        d = r["date"]
        ev[d]["in"] += r["amount"]
        for src in r["sources"]:
            ev[d]["in_items"].append({"name": src["name"], "ref": src["ref"],
                "trade_id": src["trade_id"], "amount": src["amount"], "kind": "collect"})
    if inj_amt > 0:                               # IN: a planned capital injection
        ev[inj_when]["in"] += inj_amt
        ev[inj_when]["in_items"].append({"name": "Capital injection", "ref": None,
            "trade_id": None, "amount": inj_amt.quantize(cent), "kind": "injection"})

    timeline = []
    running = start_cash
    peak_short = ZERO
    peak_date = None
    onset_date = None
    recovery_date = None
    dipped = False
    for d in sorted(ev.keys()):
        e = ev[d]
        opening = running
        running += e["in"] - e["out"]
        if running < peak_short:
            peak_short = running
            peak_date = d
        if running < -eps and onset_date is None:
            onset_date = d
        if running < -eps:
            dipped = True
        elif dipped and running >= -eps and recovery_date is None:
            recovery_date = d
        timeline.append({
            "date": d, "days_out": max(0, (d - today).days),
            "inflow": e["in"].quantize(cent), "outflow": e["out"].quantize(cent),
            "opening": opening.quantize(cent), "running": running.quantize(cent),
            "short": running < -eps,
            "in_items": sorted(e["in_items"], key=lambda x: -x["amount"]),
            "out_items": sorted(e["out_items"], key=lambda x: -x["amount"]),
        })
    injection = (-peak_short).quantize(cent) if peak_short < 0 else ZERO
    inj_date = onset_date
    end_balance = running

    # ── RECEIVABLES CHECKLIST — what to COLLECT, by customer (mirror of payables)
    cust_group = {}
    for t in all_trades:
        if t.status == TradeStatus.CANCELLED:
            continue
        cust = session.get(Party, t.purchaser_id) if t.purchaser_id else None
        if not cust:
            continue
        sale = Decimal(t.total_sale)
        if sale <= 0:
            continue
        collected = Decimal(t.paid_by_customer) + TradeService._customer_credits(session, t)
        outstanding = sale - collected
        g = cust_group.setdefault(cust.id, {"id": cust.id, "name": cust.name,
            "total": ZERO, "collected": ZERO, "outstanding": ZERO, "items": []})
        g["total"] += sale
        g["collected"] += collected
        if outstanding > Decimal("1"):
            g["outstanding"] += outstanding
            due = t.customer_due_date
            if due is None and t.delivered_at is not None:
                due = t.delivered_at + timedelta(days=int(t.customer_terms_days or 0))
            g["items"].append({"ref": t.reference, "trade_id": t.id, "due": due,
                "amount": outstanding.quantize(cent),
                "delivered": t.delivered_at is not None,
                "overdue": bool(due and due < today),
                "status": t.status.value if hasattr(t.status, "value") else t.status})
    customer_plans = []
    for g in cust_group.values():
        if g["outstanding"] <= eps:
            continue
        g["pct"] = int(g["collected"] / g["total"] * 100) if g["total"] > 0 else 0
        g["total"] = g["total"].quantize(cent)
        g["collected"] = g["collected"].quantize(cent)
        g["outstanding"] = g["outstanding"].quantize(cent)
        g["items"].sort(key=lambda x: (x["due"] or date(2099, 1, 1)))
        customer_plans.append(g)
    customer_plans.sort(key=lambda g: -g["outstanding"])
    receivables_total = sum((g["outstanding"] for g in customer_plans), ZERO)

    # ── Vendor priority summary, rebuilt from the checklist ──────────────────
    proj_by_vendor = defaultdict(lambda: ZERO)
    for p in projected:
        proj_by_vendor[p["vendor"]] += p["amount"]
    vendor_summary = sorted(
        [{"name": vp["name"], "tier": vp["tier"], "reason": vp["reason"],
          "trades": vp["trades"], "tenure_days": vp["tenure_days"],
          "owed": vp["remaining"], "proj": proj_by_vendor.get(vp["name"], ZERO).quantize(cent),
          "paid": vp["paid"],
          "remaining": (vp["remaining"] + proj_by_vendor.get(vp["name"], ZERO)).quantize(cent),
          "due_date": min((sl["date"] for sl in vp["schedule"] if sl["outstanding"] > eps), default=None)}
         for vp in vendor_plans if (vp["remaining"] > eps or proj_by_vendor.get(vp["name"], ZERO) > eps)],
        key=lambda x: ({"new": 0, "recent": 1, "growing": 2, "established": 3}[x["tier"]],
                       -(x["owed"] + x["proj"])))
    payables_total = sum((vp["remaining"] for vp in vendor_plans), ZERO)

    # ── SMART DIVISION: as each receipt lands, how to split it across VENDORS
    # (not per trade), weighted by the priority factors — newer vendors favoured,
    # long-standing ones pushed a little, but nobody skipped. This is the "collect
    # → pay out" guidance the owner follows. ──
    vstate = {}

    def _ensure(vid, name, pid):
        if vid not in vstate:
            vstate[vid] = {**_meta(pid, name), "remaining": ZERO, "paid": ZERO, "due_date": None}
        return vstate[vid]

    obligations = []
    for vp in vendor_plans:                       # per UNPAID slice, at its real deadline
        if vp["remaining"] <= eps:
            continue
        vid = vp["id"]
        st = _ensure(vid, vp["name"], vid if isinstance(vid, int) else None)
        deadlines = []
        for sl in vp["schedule"]:
            if sl["outstanding"] > eps:
                dd = max(today, sl["date"] + _delay(vp["name"]))   # due + max stretch
                obligations.append({"vid": vid, "amount": sl["outstanding"], "due": dd, "kind": "owed"})
                deadlines.append(dd)
        st["due_date"] = min(deadlines) if deadlines else today
    for p in projected:                           # upcoming supply payments (goods on order)
        pid = name_to_pid.get(p["vendor"])
        vid = pid if pid is not None else p["vendor"]
        _ensure(vid, p["vendor"], pid)
        obligations.append({"vid": vid, "amount": p["amount"],
                            "due": max(today, p["date"] + _delay(p["vendor"])), "kind": "projected"})
    obligations.sort(key=lambda o: o["due"])

    def _distribute(pool):
        ids = list(vstate.keys())
        alloc = {i: ZERO for i in ids}
        pool = min(pool, sum((vstate[i]["remaining"] for i in ids), ZERO))
        for _ in range(40):
            if pool <= eps:
                break
            active = [i for i in ids if (vstate[i]["remaining"] - alloc[i]) > eps]
            if not active:
                break
            tw = sum(((vstate[i]["remaining"] - alloc[i]) * vstate[i]["mult"] for i in active), ZERO)
            if tw <= 0:
                break
            made = ZERO
            for i in active:
                room = vstate[i]["remaining"] - alloc[i]
                want = pool * ((vstate[i]["remaining"] - alloc[i]) * vstate[i]["mult"]) / tw
                pay = want if want < room else room
                alloc[i] += pay
                made += pay
            pool -= made
            if made <= eps:
                break
        return alloc

    rmap = {r["date"]: r for r in receipts}
    event_dates = sorted(set(rmap.keys()) | {o["due"] for o in obligations}
                         | ({inj_when} if inj_amt > 0 else set()))
    pool = start_cash if start_cash > 0 else ZERO
    oblig_idx = 0
    injected_done = False
    instructions = []
    cleared_date = None
    for d in event_dates:
        while oblig_idx < len(obligations) and obligations[oblig_idx]["due"] <= d:
            o = obligations[oblig_idx]
            oblig_idx += 1
            vstate[o["vid"]]["remaining"] += o["amount"]
        r = rmap.get(d)
        receipt_amt = r["amount"] if r else ZERO
        inj_now = ZERO
        if inj_amt > 0 and not injected_done and d >= inj_when:
            inj_now = inj_amt
            injected_done = True
        pool += receipt_amt + inj_now
        alloc = _distribute(pool)
        payments = []
        total_paid = ZERO
        for i, a in alloc.items():
            if a > eps:
                st = vstate[i]
                st["remaining"] -= a
                st["paid"] += a
                total_paid += a
                payments.append({"vendor": st["name"], "amount": a.quantize(cent),
                                 "tier": st["tier"], "reason": st["reason"],
                                 "remaining_after": st["remaining"].quantize(cent) if st["remaining"] > eps else ZERO})
        pool -= total_paid
        # ── AUTO-INJECTION ──────────────────────────────────────────────────
        # Anything still unpaid at this point has passed its deadline (every
        # activated obligation is due ≤ today's date) — collections can't be
        # stretched any further, so cash MUST be found now. Inject exactly that
        # shortfall and clear those vendors. This is the "when / how much / to
        # whom" the owner asked for.
        auto_inj = ZERO
        for i in list(vstate.keys()):
            st = vstate[i]
            if st["remaining"] > eps:
                amt = st["remaining"]
                st["remaining"] = ZERO
                st["paid"] += amt
                auto_inj += amt
                payments.append({"vendor": st["name"], "amount": amt.quantize(cent),
                                 "tier": st["tier"], "reason": st["reason"],
                                 "remaining_after": ZERO, "from_injection": True})
        if auto_inj > eps:
            inj_now += auto_inj
            total_paid += auto_inj
        payments.sort(key=lambda x: (-(1 if x.get("from_injection") else 0), -x["amount"]))
        if not payments and receipt_amt <= eps and inj_now <= eps:
            continue
        instructions.append({"date": d, "days_out": max(0, (d - today).days),
                             "receipt": receipt_amt.quantize(cent), "injected": inj_now.quantize(cent),
                             "auto_injected": auto_inj.quantize(cent),
                             "sources": r["sources"] if r else [],
                             "payments": payments, "paid_out": total_paid.quantize(cent),
                             "carried": pool.quantize(cent)})
        if (cleared_date is None and oblig_idx >= len(obligations)
                and sum((vstate[i]["remaining"] for i in vstate), ZERO) <= eps):
            cleared_date = d

    # ── Payments you've ALREADY MADE recently — shown as ✓ done above the plan,
    # so following the plan visibly ticks off. Sourced from the ledger so both
    # Record-Payment and manual vouchers count. ──
    recent_payments = []
    _cut = today - timedelta(days=30)
    for pp in session.exec(
        select(TradePayment).where(
            TradePayment.user_id == user_id,
            TradePayment.direction == PaymentDirection.OUTBOUND,
            TradePayment.paid_on >= _cut,
        ).order_by(TradePayment.paid_on.desc(), TradePayment.id.desc())
    ).all():
        _t = session.get(Trade, pp.trade_id)
        _v = session.get(Party, _t.vendor_id) if (_t and _t.vendor_id) else None
        recent_payments.append({
            "date": pp.paid_on, "vendor": _v.name if _v else "vendor",
            "amount": Decimal(pp.amount).quantize(cent),
            "ref": _t.reference if _t else None,
            "trade_id": _t.id if _t else None,
            "method": pp.method,
        })
    recent_paid_total = sum((p["amount"] for p in recent_payments), ZERO)

    # ── On-order trades: goods NOT yet delivered. The owner can set an expected
    #    arrival date so the forecast schedules the supply payment (and resulting
    #    collection) from that date. Vendors with NO delivery history are flagged
    #    — the model can't guess their timing, so a date is required from you. ──
    on_order = []
    for t in all_trades:
        if t.delivered_at is not None:
            continue
        pend_cost = ZERO
        pend_sale = ZERO
        for ln in t.lines:
            recv = sum((Decimal(str(r.received_qty)) for r in (ln.receipts or [])), ZERO)
            uq = Decimal(str(ln.quantity)) - recv
            if uq > 0:
                pend_cost += uq * Decimal(str(ln.unit_cost))
                pend_sale += uq * Decimal(str(ln.unit_price))
        if pend_cost <= eps and pend_sale <= eps:
            continue
        has_hist = _last_delivery_date(session, user_id, t.vendor_id) is not None
        sched = proj_sched_by_trade.get(t.id, [])
        on_order.append({
            "trade_id": t.id, "ref": t.reference,
            "vendor": party_name.get(t.vendor_id, "vendor"),
            "customer": party_name.get(t.purchaser_id, "customer"),
            "pending_cost": pend_cost.quantize(cent),
            "pending_sale": pend_sale.quantize(cent),
            "expected_date": t.expected_delivery_date,
            "no_history": not has_hist,
            # what you'll actually pay this vendor for this trade, by stage, on the
            # date it's due (net of any advance already prepaid)
            "pay_schedule": sched,
            "net_payable": sum((x["amount"] for x in sched), ZERO).quantize(cent),
        })
    on_order.sort(key=lambda x: (x["expected_date"] or date(2099, 1, 1), x["ref"] or ""))
    on_order_needs_date = [o for o in on_order if o["no_history"] and o["expected_date"] is None]

    # ── Injection requirement: on which dates you must top the account up, how
    #    much, and which vendor payment each injection unblocks. ──
    injection_events = []
    for ins in instructions:
        ai = Decimal(str(ins.get("auto_injected", 0) or 0))
        if ai <= eps:
            continue
        vends = []
        for p in ins.get("payments", []):
            if p.get("from_injection") and p.get("vendor") not in vends:
                vends.append(p.get("vendor"))
        injection_events.append({
            "date": ins["date"], "days_out": ins.get("days_out"),
            "amount": ai.quantize(cent), "vendors": vends,
        })
    total_injection_needed = sum((e["amount"] for e in injection_events), ZERO)

    # ── Plain-language: what it MEANS, and HOW to divide the payments ────────
    def _rs(x):
        return f"Rs {float(x):,.0f}"

    summary_bullets = []
    summary_bullets.append(
        f"Customers owe you {_rs(receivables_total)}. You owe vendors {_rs(payables_total)} right now"
        + (f", plus about {_rs(projected_total)} more once goods on order arrive." if projected_total > eps else "."))
    if injection > 0:
        when = f" around {peak_date.strftime('%d %b')}" if peak_date else ""
        summary_bullets.append(
            f"You hit a timing gap: at the deepest you're short about {_rs(injection)}{when}, "
            "because vendor payments fall due before the big customer collections land.")
        if recovery_date:
            summary_bullets.append(
                f"It's a bridge, not a loss — collections catch up by {recovery_date.strftime('%d %b')}, "
                f"and you finish about {_rs(end_balance)} in the black.")
    else:
        summary_bullets.append(
            f"Your collections cover every payment as it falls due — no cash gap. "
            f"You finish about {_rs(end_balance)} in the black.")

    action_bullets = []
    if injection > 0:
        by = f" by {onset_date.strftime('%d %b')}" if onset_date else ""
        action_bullets.append(
            f"Keep about {_rs(injection)} of working capital ready{by} to bridge the gap "
            "— or collect sooner / hold off a long-standing vendor.")
    pay_order = [vp for vp in vendor_plans if vp["remaining"] > eps]
    if len(pay_order) == 1:
        vp = pay_order[0]
        action_bullets.append(
            f"Put every rupee you collect toward {vp['name']} until their {_rs(vp['remaining'])} is cleared.")
    elif len(pay_order) > 1:
        order = ", then ".join(f"{vp['name']} {_rs(vp['remaining'])}" for vp in pay_order)
        action_bullets.append(
            f"As money comes in, split it newest-vendor-first: pay {order}. "
            "New vendors get priority; long-standing ones can wait a little.")
    if projected_total > eps:
        action_bullets.append(
            f"Upcoming supply ({_rs(projected_total)}) only falls due when those goods arrive "
            "— you've already prepaid part as advance.")
    chase = [g for g in customer_plans][:3]
    if chase:
        action_bullets.append(
            "To fund the payments, chase collections — biggest first: "
            + ", ".join(f"{g['name']} {_rs(g['outstanding'])}" for g in chase) + ".")

    # Vendors shown in the delay what-if slider: those we currently owe or have
    # goods on order with. `days` reflects the override in effect (preview) or
    # the stored setting. `saved_days` is what's persisted, so the UI can show a
    # "Save" affordance only when the slider differs from the stored value.
    stored_delay = {p.id: max(0, int(getattr(p, "max_payment_delay_days", 1) or 1)) for p in parties}
    vd_ids = {v["id"] for v in vendors if isinstance(v.get("id"), int)}
    for o in on_order:
        pid = name_to_pid.get(o["vendor"])
        if pid:
            vd_ids.add(pid)
    vendor_delays = []
    for p in parties:
        if p.id in vd_ids:
            vendor_delays.append({
                "id": p.id, "name": p.name,
                "days": int(delay_overrides.get(p.id, stored_delay[p.id])),
                "saved_days": stored_delay[p.id],
            })
    vendor_delays.sort(key=lambda x: x["name"])

    return {
        "summary_bullets": summary_bullets,
        "action_bullets": action_bullets,
        "instructions": instructions,
        "cleared_date": cleared_date,
        "recent_payments": recent_payments,
        "recent_paid_total": recent_paid_total.quantize(cent),
        "today": today,
        "horizon_days": horizon_days,
        "cash_today": cash_today.quantize(cent),          # incl. CEO draw (info only)
        "start_cash": start_cash.quantize(cent),          # liquid spendable cash
        "total_to_collect": total_to_collect.quantize(cent),
        "receivables_total": receivables_total.quantize(cent),
        "payables_total": payables_total.quantize(cent),
        "projected_total": projected_total.quantize(cent),
        # cash-flow timeline (the centrepiece)
        "timeline": timeline,
        "peak_shortfall": injection,
        "peak_date": peak_date,
        "onset_date": onset_date,
        "recovery_date": recovery_date,
        "end_balance": end_balance.quantize(cent),
        # capital injection
        "injection": injection,
        "injection_date": inj_date,
        "applied_injection": inj_amt.quantize(cent),
        "applied_injection_date": (inj_when if inj_amt > 0 else None),
        # payables checklist
        "plan_steps": plan_steps,
        "plan_total_amount": plan_total_amount.quantize(cent),
        "plan_paid_amount": plan_paid_amount.quantize(cent),
        "plan_remaining_amount": (plan_total_amount - plan_paid_amount).quantize(cent),
        "vendor_plans": vendor_plans,
        "vendor_summary": vendor_summary,
        "vendor_count": len(vendor_plans),
        # receivables checklist
        "customer_plans": customer_plans,
        "projected_pointers": projected_pointers,
        # on-order supply arrivals (owner-editable expected dates)
        "on_order": on_order,
        "on_order_needs_date": on_order_needs_date,
        # injection requirement summary (inject X on Z to pay Y)
        "injection_events": injection_events,
        "total_injection_needed": total_injection_needed.quantize(cent),
        # vendor max-payment-delay what-if sliders
        "vendor_delays": vendor_delays,
        "delay_overridden": bool(delay_overrides),
    }


# ──────────────────────── Trade Profitability Dashboard ────────────────────────


def trade_profitability(session, user_id, from_date=None, to_date=None, limit=10) -> dict:
    q = select(Trade).where(Trade.user_id == user_id, Trade.status != TradeStatus.CANCELLED)
    if from_date: q = q.where(Trade.trade_date >= from_date)
    if to_date: q = q.where(Trade.trade_date <= to_date)
    trades = list(session.exec(q).all())

    enriched = []
    today = date.today()
    for t in trades:
        gp = Decimal(t.total_sale) - Decimal(t.total_cost)
        gp_pct = (gp / Decimal(t.total_sale) * 100) if t.total_sale > 0 else ZERO
        ar_out = Decimal(t.total_sale) - Decimal(t.paid_by_customer)
        ap_out = Decimal(t.total_cost) - Decimal(t.paid_to_vendor)
        biggest_var = ZERO
        for ln in t.lines:
            if ln.ordered_quantity and ln.ordered_quantity > 0:
                v = abs(Decimal(ln.quantity) - Decimal(ln.ordered_quantity))
                if v > biggest_var: biggest_var = v
        enriched.append({
            "trade": t,
            "gp": gp.quantize(Decimal("0.01")),
            "gp_pct": gp_pct.quantize(Decimal("0.01")),
            "ar_outstanding": ar_out.quantize(Decimal("0.01")),
            "ap_outstanding": ap_out.quantize(Decimal("0.01")),
            "days_since_delivered": ((today - t.delivered_at).days) if t.delivered_at else None,
            "biggest_qty_variance": biggest_var,
        })

    top_by_gp = sorted(enriched, key=lambda r: -r["gp"])[:limit]
    biggest_var = sorted([e for e in enriched if e["biggest_qty_variance"] > 0],
                        key=lambda r: -r["biggest_qty_variance"])[:limit]
    oldest_unsettled = sorted([e for e in enriched if e["ar_outstanding"] > 0],
                              key=lambda r: -(r["days_since_delivered"] or 0))[:limit]

    by_month = {}
    for e in enriched:
        m = e["trade"].trade_date.strftime("%Y-%m")
        b = by_month.setdefault(m, {"month": m, "revenue": ZERO, "cogs": ZERO})
        b["revenue"] += Decimal(e["trade"].total_sale)
        b["cogs"] += Decimal(e["trade"].total_cost)
    trend = []
    for m in sorted(by_month):
        b = by_month[m]
        gp = b["revenue"] - b["cogs"]
        pct = (gp / b["revenue"] * 100) if b["revenue"] > 0 else ZERO
        trend.append({
            "month": m,
            "revenue": b["revenue"].quantize(Decimal("0.01")),
            "cogs": b["cogs"].quantize(Decimal("0.01")),
            "gp": gp.quantize(Decimal("0.01")),
            "gp_pct": pct.quantize(Decimal("0.01")),
        })

    return {
        "top_by_gp": top_by_gp,
        "biggest_variances": biggest_var,
        "oldest_unsettled": oldest_unsettled,
        "monthly_trend": trend,
        "period_from": from_date, "period_to": to_date,
    }
