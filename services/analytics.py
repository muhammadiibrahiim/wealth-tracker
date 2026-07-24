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
    """Working-capital metrics on an annualised (365-day) basis.

    DSO/DPO formulas use only *operating* AR/AP — i.e. balances generated by
    sales/purchases inside the system. Pre-existing opening balances seeded at
    go-live are excluded from the numerator; otherwise the ratio divides
    pre-existing AR by tiny in-period sales and reports nonsense days.

    If there's not enough sales/COGS history in the period to make the
    calculation meaningful, the corresponding metric returns None and the
    template renders "—".
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

    # DSO / DPO = amount-weighted AGE of the currently-OUTSTANDING balance, read
    # from the ledger (not nominal trade terms). This answers "how long is money
    # actually tied up right now" and reflects balances being DELAYED — a bill
    # you're sitting on shows its real age. (The older matched-only lag ignored
    # unpaid balances, so deferred payments were invisible and DPO read ~0.)
    # DSO/DPO reuse the trade-scoped AR/AP account ids computed above.
    min_open = Decimal("1000")          # need >Rs 1k outstanding to be meaningful
    dso_raw, dso_open = _avg_open_age(session, ar_ids, invoice_is_debit=True, as_of=as_of)
    dpo_raw, dpo_open = _avg_open_age(session, ap_ids, invoice_is_debit=False, as_of=as_of)
    dso = dso_raw if (dso_raw is not None and dso_open >= min_open) else None
    dpo = dpo_raw if (dpo_raw is not None and dpo_open >= min_open) else None
    ccc = (dso - dpo) if (dso is not None and dpo is not None) else None

    current_assets = cash + ar_balance
    current_ratio  = (current_assets / ap_balance) if ap_balance > 0 else None

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


def _avg_equity_over_period(session, acct_ids, start, end):
    """Time-weighted average of equity (credit-positive) across [start, end] —
    the mean of each DAY's closing balance. This is the capital that was actually
    at work: injecting Rs 1M in the last two days shouldn't count as if it funded
    the whole month. Returns None if there's nothing to average."""
    if not acct_ids or end < start:
        return None
    opening = ZERO
    for aid in acct_ids:
        opening += -balance_asof(session, aid, start - timedelta(days=1))  # credit-positive
    rows = session.exec(
        select(JournalEntry.entry_date,
               func.coalesce(func.sum(JournalLine.debit), 0),
               func.coalesce(func.sum(JournalLine.credit), 0))
        .select_from(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id.in_(acct_ids),
               JournalEntry.is_reversed == False,  # noqa: E712
               JournalEntry.entry_date >= start,
               JournalEntry.entry_date <= end)
        .group_by(JournalEntry.entry_date)
    ).all()
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
    metrics = working_capital_metrics(session, user_id, as_of=as_of, period_days=365)
    cash = metrics["cash_balance"]
    ar = metrics["ar_balance"]
    ap = metrics["ap_balance"]
    capital_deployed = cash + ar - ap

    equity_total = ZERO
    for sub_code in ("3100", "3900"):
        for a in _accounts_in_subclass(session, user_id, sub_code):
            equity_total += -balance_asof(session, a.id, as_of)

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
                total += -balance_asof(session, a.id, ni_to)  # credit-positive
        return total

    funding = _closing("Ibrahim (CEO)", "CEO", "Funding")
    retained = _closing("Capital A/C", "Capital")
    invested_capital = (funding + retained).quantize(Decimal("0.01"))  # closing snapshot

    # Denominator = time-weighted AVERAGE equity over the period (mean of each
    # day's closing balance), so a late-month injection doesn't overstate the
    # base. Falls back to the closing snapshot if the average can't be formed.
    avg_equity = _avg_equity_over_period(session, [a.id for a in equity_accts], ni_from, ni_to)
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
        c_open = -balance_asof(session, capital_acct.id, ni_from - timedelta(days=1))
        c_close = -balance_asof(session, capital_acct.id, ni_to)
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


def bank_position_forecast(session, user_id, horizon_days=30, include_funding=True) -> dict:
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

        # Delivered value + the date of the latest delivery, for the firm part.
        if t.delivered_at:
            delivered_value = Decimal(t.total_sale)
            deliv_date = t.delivered_at
        else:
            delivered_value = ZERO
            recdates = []
            for ln in t.lines:
                for r in (ln.receipts or []):
                    delivered_value += Decimal(r.received_qty) * Decimal(ln.unit_price)
                    recdates.append(r.received_on)
            deliv_date = max(recdates) if recdates else None

        # FIRM: delivered goods not yet collected. Schedule the outstanding
        # across the customer's payment SPLIT (advance/on-delivery/credit),
        # applying what's already been paid to the earliest stages first.
        paid_total = Decimal(t.paid_by_customer) + TradeService._customer_credits(session, t)
        if delivered_value > 0 and deliv_date:
            sched = TradeService.payment_schedule(t, "customer",
                                                  total=delivered_value, delivery_date=deliv_date)
            rem_paid = paid_total
            for stg in sched:
                amt = Decimal(stg["amount"])
                applied = min(amt, rem_paid) if rem_paid > 0 else ZERO
                rem_paid -= applied
                out = amt - applied
                if out > Decimal("0.005") and stg["date"]:
                    # credit stage respects late-payer behaviour; advance/delivery are firm dates
                    due = stg["date"]
                    if stg["stage"] == "credit":
                        due = deliv_date + timedelta(days=pay_lag)
                    inflows.append({"trade": t, "amount": out.quantize(Decimal("0.01")),
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
    fc = bank_position_forecast(session, user_id)
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
                         inject_amount=None, inject_on=None) -> dict:
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
            od = cost * dely / tot
            cr = cost * cred / tot
            if od > Decimal("0.5"):
                projected.append({"date": max(today, ddate), "vendor": vname,
                                  "amount": od.quantize(cent), "ref": t.reference,
                                  "trade_id": tid, "stage": "on delivery"})
                projected_total += od
            if cr > Decimal("0.5"):
                cd = max(today, ddate + timedelta(days=cdays))
                projected.append({"date": cd, "vendor": vname,
                                  "amount": cr.quantize(cent), "ref": t.reference,
                                  "trade_id": tid, "stage": f"credit +{cdays}d"})
                projected_total += cr
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

    day_flow = defaultdict(lambda: ZERO)
    for r in receipts:
        day_flow[r["date"]] += r["amount"]
    for v in vendors:
        day_flow[max(today, v["due_date"] or today)] -= v["owed"]
    for p in projected:
        day_flow[p["date"]] -= p["amount"]
    if inj_amt > 0:
        day_flow[inj_when] += inj_amt
    spare = cash_today if cash_today > 0 else ZERO
    running_sim = spare
    trough = ZERO      # deepest the balance dips (= amount needed)
    onset = None       # FIRST day it dips negative (= have the cash by then)
    for d in sorted(day_flow.keys()):
        running_sim += day_flow[d]
        if running_sim < trough:
            trough = running_sim
        if onset is None and running_sim < -eps:
            onset = d
    injection = (-trough).quantize(cent) if trough < 0 else ZERO
    inj_date = onset

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

    vstate = {}

    def _ensure(vid, name, pid):
        if vid not in vstate:
            vstate[vid] = {**_meta(pid, name), "remaining": ZERO, "paid": ZERO,
                           "owed_hard": ZERO, "proj": ZERO, "due_date": None,
                           "ref": None, "trade_id": None}
        return vstate[vid]

    obligations = []
    for v in vendors:
        st = _ensure(v["id"], v["name"], v["id"] if isinstance(v["id"], int) else None)
        st["owed_hard"] = v["owed"]
        st["due_date"] = v["due_date"]
        refs = ref_by_vendor.get(v["name"], [])
        st["ref"] = refs[0][1] if refs else None
        st["trade_id"] = refs[0][0] if refs else None
        obligations.append({"vid": v["id"], "amount": v["owed"],
                            "due": max(today, v["due_date"] or today), "kind": "owed"})
    for p in projected:
        pid = name_to_pid.get(p["vendor"])
        vid = pid if pid is not None else p["vendor"]
        st = _ensure(vid, p["vendor"], pid)
        st["proj"] += p["amount"]
        if st["trade_id"] is None:
            st["trade_id"] = p.get("trade_id"); st["ref"] = p.get("ref")
        obligations.append({"vid": vid, "amount": p["amount"], "due": p["date"],
                            "kind": "projected"})
    obligations.sort(key=lambda o: o["due"])
    total_obligations = sum((o["amount"] for o in obligations), ZERO)

    def distribute(pool):
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
    pool = cash_today if cash_today > 0 else ZERO
    oblig_idx = 0
    injected_done = False
    instructions = []
    cleared_date = None
    for d in event_dates:
        newly_due = ZERO
        while oblig_idx < len(obligations) and obligations[oblig_idx]["due"] <= d:
            o = obligations[oblig_idx]
            oblig_idx += 1
            vstate[o["vid"]]["remaining"] += o["amount"]
            if o["kind"] == "projected":
                newly_due += o["amount"]
        r = rmap.get(d)
        receipt_amt = r["amount"] if r else ZERO
        inj_now = ZERO
        if inj_amt > 0 and not injected_done and d >= inj_when:
            inj_now = inj_amt
            injected_done = True
        pool += receipt_amt + inj_now
        alloc = distribute(pool)
        payments = []
        total_paid = ZERO
        for i, a in alloc.items():
            if a > eps:
                st = vstate[i]
                st["remaining"] -= a
                st["paid"] += a
                total_paid += a
                payments.append({
                    "vendor": st["name"], "amount": a.quantize(cent),
                    "tier": st["tier"], "reason": st["reason"],
                    "remaining_after": st["remaining"].quantize(cent) if st["remaining"] > eps else ZERO,
                    "trade_id": st["trade_id"], "ref": st["ref"],
                })
        pool -= total_paid
        payments.sort(key=lambda x: -x["amount"])
        if not payments and receipt_amt <= eps and newly_due <= eps and inj_now <= eps:
            continue
        instructions.append({
            "date": d, "days_out": max(0, (d - today).days),
            "opening": False,
            "receipt": receipt_amt.quantize(cent),
            "injected": inj_now.quantize(cent),
            "sources": r["sources"] if r else [],
            "new_due": newly_due.quantize(cent),
            "payments": payments,
            "paid_out": total_paid.quantize(cent),
            "carried": pool.quantize(cent),
        })
        if (cleared_date is None and oblig_idx >= len(obligations)
                and sum((vstate[i]["remaining"] for i in vstate), ZERO) <= eps
                and total_obligations > 0):
            cleared_date = d

    total_paid_plan = sum((vstate[i]["paid"] for i in vstate), ZERO)
    still_owed = (total_obligations - total_paid_plan)
    if still_owed < 0:
        still_owed = ZERO

    vendor_summary = sorted(
        [{"name": st["name"], "tier": st["tier"], "reason": st["reason"],
          "trades": st["trades"], "tenure_days": st["tenure_days"],
          "owed": st["owed_hard"].quantize(cent), "proj": st["proj"].quantize(cent),
          "paid": st["paid"].quantize(cent),
          "remaining": max(ZERO, st["owed_hard"] + st["proj"] - st["paid"]).quantize(cent),
          "due_date": st["due_date"]}
         for st in vstate.values()],
        key=lambda x: ({"new": 0, "recent": 1, "growing": 2, "established": 3}[x["tier"]],
                       -(x["owed"] + x["proj"])))

    return {
        "today": today,
        "horizon_days": horizon_days,
        "cash_today": cash_today.quantize(cent),
        "total_to_collect": total_to_collect.quantize(cent),
        "total_owed": total_owed.quantize(cent),
        "total_obligations": total_obligations.quantize(cent),
        "total_paid_plan": total_paid_plan.quantize(cent),
        "still_owed": still_owed.quantize(cent),
        "cleared_date": cleared_date,
        "vendor_count": len(vstate),
        "instructions": instructions,
        "vendor_summary": vendor_summary,
        "projected_pointers": projected_pointers,
        "projected_total": projected_total.quantize(cent),
        "injection": injection,
        "injection_date": inj_date,
        "applied_injection": inj_amt.quantize(cent),
        "applied_injection_date": (inj_when if inj_amt > 0 else None),
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
