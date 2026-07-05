"""Ledger / balance computation. All balances derive from journal_lines."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, and_, func, select

from models import (
    Account,
    AccountClass,
    AccountNature,
    AccountSubClass,
    JournalEntry,
    JournalLine,
)


ZERO = Decimal("0")


def _nature_sign(nature: AccountNature) -> int:
    if nature in (AccountNature.ASSET, AccountNature.EXPENSE):
        return 1
    return -1


def balance_asof(session: Session, account_id: int, as_of: Optional[date] = None) -> Decimal:
    q = (
        select(
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .select_from(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(
            JournalLine.account_id == account_id,
        )  # Both original and its reversal are kept; together they net to zero.
    )
    if as_of is not None:
        q = q.where(JournalEntry.entry_date <= as_of)
    dr, cr = session.exec(q).one()
    return (Decimal(dr or 0) - Decimal(cr or 0)).quantize(Decimal("0.01"))


def balances_for_accounts(
    session: Session, account_ids: list[int], as_of: Optional[date] = None
) -> dict[int, Decimal]:
    if not account_ids:
        return {}
    q = (
        select(
            JournalLine.account_id,
            func.coalesce(func.sum(JournalLine.debit), 0),
            func.coalesce(func.sum(JournalLine.credit), 0),
        )
        .select_from(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(
            JournalLine.account_id.in_(account_ids),
        )  # Both original and its reversal are kept; together they net to zero.
    )
    if as_of is not None:
        q = q.where(JournalEntry.entry_date <= as_of)
    q = q.group_by(JournalLine.account_id)
    rows = session.exec(q).all()
    out = {aid: (Decimal(dr or 0) - Decimal(cr or 0)).quantize(Decimal("0.01")) for aid, dr, cr in rows}
    for aid in account_ids:
        out.setdefault(aid, ZERO)
    return out


def normalized_balance(session: Session, account_id: int, as_of: Optional[date] = None) -> Decimal:
    raw = balance_asof(session, account_id, as_of)
    acct = session.get(Account, account_id)
    if not acct:
        return raw
    cls = session.get(AccountClass, acct.class_id)
    if not cls:
        return raw
    return raw * _nature_sign(cls.nature)


def trial_balance(session: Session, user_id: int, as_of: Optional[date] = None) -> dict:
    classes = list(
        session.exec(
            select(AccountClass).where(AccountClass.user_id == user_id).order_by(AccountClass.code)
        ).all()
    )
    accounts = list(
        session.exec(
            select(Account).where(Account.user_id == user_id).order_by(Account.code)
        ).all()
    )
    if not accounts:
        return {"classes": [], "total_debit": ZERO, "total_credit": ZERO, "difference": ZERO, "is_balanced": True}

    balances = balances_for_accounts(session, [a.id for a in accounts], as_of)

    by_class: dict[int, list[dict]] = {}
    for a in accounts:
        bal = balances.get(a.id, ZERO)
        if bal == 0:
            continue
        if bal > 0:
            dr, cr = bal, ZERO
        else:
            dr, cr = ZERO, -bal
        by_class.setdefault(a.class_id, []).append(
            {"account": a, "debit": dr, "credit": cr, "balance": bal}
        )

    out_classes: list[dict] = []
    total_dr = ZERO
    total_cr = ZERO
    for cls in classes:
        rows = by_class.get(cls.id, [])
        if not rows:
            continue
        cdr = sum((r["debit"] for r in rows), ZERO)
        ccr = sum((r["credit"] for r in rows), ZERO)
        total_dr += cdr
        total_cr += ccr
        out_classes.append({"class": cls, "rows": rows, "totals": {"debit": cdr, "credit": ccr}})

    diff = (total_dr - total_cr).quantize(Decimal("0.01"))
    return {
        "classes": out_classes,
        "total_debit": total_dr.quantize(Decimal("0.01")),
        "total_credit": total_cr.quantize(Decimal("0.01")),
        "difference": diff,
        "is_balanced": abs(diff) < Decimal("0.01"),
    }


def account_ledger(
    session: Session,
    account_id: int,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> dict:
    acct = session.get(Account, account_id)
    if not acct:
        return {"account": None, "opening_balance": ZERO, "lines": [], "closing_balance": ZERO}

    opening = ZERO
    if from_date is not None:
        opening = balance_asof(session, account_id, from_date - timedelta(days=1))

    q = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == account_id)  # both originals and reversals shown
    )
    if from_date is not None:
        q = q.where(JournalEntry.entry_date >= from_date)
    if to_date is not None:
        q = q.where(JournalEntry.entry_date <= to_date)
    q = q.order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
    rows = session.exec(q).all()

    running = opening
    total_dr = ZERO
    total_cr = ZERO
    lines = []
    for ln, e in rows:
        running += Decimal(ln.debit) - Decimal(ln.credit)
        total_dr += Decimal(ln.debit)
        total_cr += Decimal(ln.credit)
        lines.append({
            "date": e.entry_date,
            "entry_id": e.id,
            "reference": e.reference,
            "entry_type": e.entry_type,
            "description": ln.description or e.description,
            "debit": Decimal(ln.debit),
            "credit": Decimal(ln.credit),
            "balance": running.quantize(Decimal("0.01")),
        })

    return {
        "account": acct,
        "opening_balance": opening.quantize(Decimal("0.01")),
        "lines": lines,
        "closing_balance": running.quantize(Decimal("0.01")),
        "total_debit": total_dr.quantize(Decimal("0.01")),
        "total_credit": total_cr.quantize(Decimal("0.01")),
        "period_from": from_date,
        "period_to": to_date,
    }


def profit_and_loss(
    session: Session, user_id: int, from_date: Optional[date] = None, to_date: Optional[date] = None
) -> dict:
    classes = list(
        session.exec(
            select(AccountClass).where(
                AccountClass.user_id == user_id,
                AccountClass.nature.in_([AccountNature.INCOME, AccountNature.EXPENSE]),
            )
        ).all()
    )
    nature_by_class = {c.id: c.nature for c in classes}
    accounts = list(
        session.exec(
            select(Account).where(Account.user_id == user_id, Account.class_id.in_([c.id for c in classes]))
        ).all()
    )

    movement: dict[int, Decimal] = {}
    if accounts:
        q = (
            select(
                JournalLine.account_id,
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0),
            )
            .select_from(JournalLine)
            .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
            .where(JournalLine.account_id.in_([a.id for a in accounts]))
        )
        if from_date is not None:
            q = q.where(JournalEntry.entry_date >= from_date)
        if to_date is not None:
            q = q.where(JournalEntry.entry_date <= to_date)
        q = q.group_by(JournalLine.account_id)
        for aid, dr, cr in session.exec(q).all():
            movement[aid] = (Decimal(dr or 0) - Decimal(cr or 0))

    income_rows = []
    cogs_rows = []
    expense_rows = []
    total_income = ZERO
    total_cogs = ZERO
    total_expense = ZERO

    for a in accounts:
        raw = movement.get(a.id, ZERO)
        nature = nature_by_class.get(a.class_id)
        if nature == AccountNature.INCOME:
            amt = -raw
            if amt == 0:
                continue
            income_rows.append({"account": a, "amount": amt.quantize(Decimal("0.01"))})
            total_income += amt
        elif nature == AccountNature.EXPENSE:
            amt = raw
            if amt == 0:
                continue
            if a.code.startswith("51"):
                cogs_rows.append({"account": a, "amount": amt.quantize(Decimal("0.01"))})
                total_cogs += amt
            else:
                expense_rows.append({"account": a, "amount": amt.quantize(Decimal("0.01"))})
                total_expense += amt

    gross_profit = (total_income - total_cogs).quantize(Decimal("0.01"))
    net_income = (gross_profit - total_expense).quantize(Decimal("0.01"))
    return {
        "income": sorted(income_rows, key=lambda r: -r["amount"]),
        "cogs": sorted(cogs_rows, key=lambda r: -r["amount"]),
        "expenses": sorted(expense_rows, key=lambda r: -r["amount"]),
        "total_income": total_income.quantize(Decimal("0.01")),
        "total_cogs": total_cogs.quantize(Decimal("0.01")),
        "gross_profit": gross_profit,
        "total_expenses": total_expense.quantize(Decimal("0.01")),
        "net_income": net_income,
        "period_from": from_date,
        "period_to": to_date,
    }


def balance_sheet(session: Session, user_id: int, as_of: Optional[date] = None) -> dict:
    classes = list(
        session.exec(
            select(AccountClass).where(
                AccountClass.user_id == user_id,
                AccountClass.nature.in_([
                    AccountNature.ASSET,
                    AccountNature.LIABILITY,
                    AccountNature.EQUITY,
                ]),
            )
        ).all()
    )
    nature_by_class = {c.id: c.nature for c in classes}
    accounts = list(
        session.exec(
            select(Account).where(
                Account.user_id == user_id, Account.class_id.in_([c.id for c in classes])
            )
        ).all()
    )
    balances = balances_for_accounts(session, [a.id for a in accounts], as_of) if accounts else {}

    assets, liabilities, equity = [], [], []
    total_a = ZERO
    total_l = ZERO
    total_e = ZERO
    for a in accounts:
        raw = balances.get(a.id, ZERO)
        nature = nature_by_class.get(a.class_id)
        if nature == AccountNature.ASSET:
            if raw == 0:
                continue
            assets.append({"account": a, "balance": raw})
            total_a += raw
        elif nature == AccountNature.LIABILITY:
            amt = -raw
            if amt == 0:
                continue
            liabilities.append({"account": a, "balance": amt})
            total_l += amt
        elif nature == AccountNature.EQUITY:
            amt = -raw
            if amt == 0:
                continue
            equity.append({"account": a, "balance": amt})
            total_e += amt

    pl = profit_and_loss(session, user_id, from_date=None, to_date=as_of)
    retained = pl["net_income"]
    if retained != 0:
        equity.append({"account": None, "label": "Retained Earnings (computed)", "balance": retained})
        total_e += retained

    diff = (total_a - (total_l + total_e)).quantize(Decimal("0.01"))
    return {
        "assets": sorted(assets, key=lambda r: -r["balance"]),
        "liabilities": sorted(liabilities, key=lambda r: -r["balance"]),
        "equity": equity,
        "total_assets": total_a.quantize(Decimal("0.01")),
        "total_liabilities": total_l.quantize(Decimal("0.01")),
        "total_equity": total_e.quantize(Decimal("0.01")),
        "retained_earnings": retained,
        "is_balanced": abs(diff) < Decimal("0.01"),
        "difference": diff,
        "as_of": as_of,
    }


def cashbook(
    session: Session,
    user_id: int,
    cash_account_ids: list[int],
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> dict:
    if not cash_account_ids:
        return {"opening_balance": ZERO, "lines": [], "closing_balance": ZERO,
                "total_debit": ZERO, "total_credit": ZERO}

    opening = ZERO
    if from_date is not None:
        for aid in cash_account_ids:
            opening += balance_asof(session, aid, from_date - timedelta(days=1))

    q = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id.in_(cash_account_ids))
    )
    if from_date is not None:
        q = q.where(JournalEntry.entry_date >= from_date)
    if to_date is not None:
        q = q.where(JournalEntry.entry_date <= to_date)
    q = q.order_by(JournalEntry.entry_date, JournalEntry.id, JournalLine.id)
    rows = session.exec(q).all()

    cash_set = set(cash_account_ids)
    running = opening
    total_dr = ZERO
    total_cr = ZERO
    out = []
    for ln, e in rows:
        other_lines = session.exec(
            select(JournalLine).where(
                JournalLine.journal_entry_id == e.id,
                JournalLine.account_id.notin_(list(cash_set)),
            )
        ).all()
        if other_lines:
            other_accts = session.exec(
                select(Account).where(Account.id.in_([l.account_id for l in other_lines]))
            ).all()
            particulars = ", ".join(a.name for a in other_accts) or e.description
        else:
            particulars = e.description

        cash_acct = session.get(Account, ln.account_id)
        running += Decimal(ln.debit) - Decimal(ln.credit)
        total_dr += Decimal(ln.debit)
        total_cr += Decimal(ln.credit)
        out.append({
            "date": e.entry_date,
            "entry_id": e.id,
            "reference": e.reference,
            "entry_type": e.entry_type,
            "particulars": particulars,
            "account_name": cash_acct.name if cash_acct else "",
            "debit": Decimal(ln.debit),
            "credit": Decimal(ln.credit),
            "balance": running.quantize(Decimal("0.01")),
        })

    return {
        "opening_balance": opening.quantize(Decimal("0.01")),
        "lines": out,
        "closing_balance": running.quantize(Decimal("0.01")),
        "total_debit": total_dr.quantize(Decimal("0.01")),
        "total_credit": total_cr.quantize(Decimal("0.01")),
    }


def day_book(session: Session, user_id: int, on_date: date) -> list[dict]:
    entries = list(
        session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == user_id,
                JournalEntry.entry_date == on_date,
            ).order_by(JournalEntry.id)
        ).all()
    )
    out = []
    for e in entries:
        lines = []
        for ln in e.lines:
            a = session.get(Account, ln.account_id)
            lines.append({
                "account": a,
                "debit": Decimal(ln.debit),
                "credit": Decimal(ln.credit),
                "description": ln.description,
            })
        out.append({"entry": e, "lines": lines})
    return out
