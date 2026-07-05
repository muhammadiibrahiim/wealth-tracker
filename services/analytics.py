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

        cogs_q = select(func.coalesce(func.sum(TradeLine.quantity * TradeLine.unit_cost), 0)).select_from(
            TradeLine
        ).join(Trade, TradeLine.trade_id == Trade.id).where(
            Trade.user_id == user_id,
            Trade.purchaser_id == c.id,
            Trade.status != TradeStatus.CANCELLED,
        )
        if from_date: cogs_q = cogs_q.where(Trade.trade_date >= from_date)
        if to_date: cogs_q = cogs_q.where(Trade.trade_date <= to_date)
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

    ar_balance = _sum_balance(session, [a.id for a in _accounts_in_subclass(session, user_id, "1200")], as_of)
    ap_balance = -_sum_balance(session, [a.id for a in _accounts_in_subclass(session, user_id, "2100")], as_of)
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

    # Need at least a token amount of in-period sales / cogs before the ratio is
    # meaningful — otherwise dividing a big AR by tiny sales gives 900+ days.
    min_for_ratio = Decimal("1000")     # less than Rs 1k of activity → "—"
    dso = (operating_ar / sales * period_days) if sales >= min_for_ratio else None
    dpo = (operating_ap / cogs  * period_days) if cogs  >= min_for_ratio else None
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
        "limited_history": sales < min_for_ratio or cogs < min_for_ratio,
    }


def capital_utilization(session, user_id, as_of=None) -> dict:
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

    pl = profit_and_loss(session, user_id, from_date=as_of - timedelta(days=365), to_date=as_of)
    trailing_ni = pl["net_income"]
    roce = (trailing_ni / capital_deployed * 100) if capital_deployed > 0 else ZERO
    return {
        "as_of": as_of,
        "components": [
            {"label": "Cash & Bank", "amount": cash},
            {"label": "Customer Receivables", "amount": ar},
            {"label": "Less: Vendor Payables", "amount": -ap},
        ],
        "capital_deployed": capital_deployed.quantize(Decimal("0.01")),
        "equity_total": equity_total.quantize(Decimal("0.01")),
        "trailing_net_income": trailing_ni,
        "roce_pct": roce.quantize(Decimal("0.01")),
    }


# ──────────────────────── Bank Position Forecast ────────────────────────


def bank_position_forecast(session, user_id, horizon_days=30) -> dict:
    today = date.today()
    cash_today = _sum_balance(session, [a.id for a in _accounts_in_subclass(session, user_id, "1100")], today)

    open_trades = list(session.exec(
        select(Trade).where(
            Trade.user_id == user_id, Trade.status.in_([
                TradeStatus.OPEN, TradeStatus.DELIVERED, TradeStatus.PARTIALLY_PAID,
            ])
        )
    ).all())

    buckets = {30: cash_today, 60: cash_today, 90: cash_today}
    inflows, outflows = [], []
    for t in open_trades:
        ar_due = Decimal(t.total_sale) - Decimal(t.paid_by_customer)
        ap_due = Decimal(t.total_cost) - Decimal(t.paid_to_vendor)
        if ar_due > 0 and t.customer_due_date:
            inflows.append({"trade": t, "amount": ar_due, "days_out": (t.customer_due_date - today).days, "due_date": t.customer_due_date})
        if ap_due > 0 and t.vendor_due_date:
            outflows.append({"trade": t, "amount": ap_due, "days_out": (t.vendor_due_date - today).days, "due_date": t.vendor_due_date})

    for h in buckets:
        for f in inflows:
            if f["days_out"] <= h: buckets[h] += f["amount"]
        for o in outflows:
            if o["days_out"] <= h: buckets[h] -= o["amount"]

    inflows.sort(key=lambda r: r["days_out"])
    outflows.sort(key=lambda r: r["days_out"])
    return {
        "today": today,
        "cash_today": cash_today.quantize(Decimal("0.01")),
        "projected": {h: v.quantize(Decimal("0.01")) for h, v in buckets.items()},
        "inflows": inflows[:50],
        "outflows": outflows[:50],
        "negative_at": next((h for h, v in buckets.items() if v < 0), None),
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
