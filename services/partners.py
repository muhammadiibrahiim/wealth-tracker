"""Equity partners + monthly profit allocation.

Partners each own a fixed % of the business and hold an equity capital account
(subclass 3100, "Owner's Capital"). The OWNER is the implicit remainder
(100% − Σ partner %) and keeps ALL pre-existing capital — only profit earned
going forward is split.

Each completed month, `run_due_allocations` posts ONE idempotent journal entry
that reclassifies the partners' share of that month's profit from the owner's
retained-earnings pool (Capital A/C 2102) into their capital accounts (and the
reverse in a loss month). It's a pure equity reallocation — no cash moves; the
money stays working in the business until a partner actually withdraws.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from models import (Partner, PartnerAllocation, Account, JournalEntry,
                    JournalLine, JournalEntryType)
from services.posting import PostingEngine
from services.account_setup import create_account
from services.ledger import profit_and_loss

ZERO = Decimal("0")
CENT = Decimal("0.01")
POOL_CODE = "2102"          # Capital A/C — owner's retained earnings pool
OWNER_CODES = ("2102", "2103")   # Capital A/C + CEO funding = owner's equity


# ── date helpers ─────────────────────────────────────────────────────────
def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _next_month(d: date) -> date:
    d = _first_of_month(d)
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def _last_of_month(d: date) -> date:
    return _next_month(d) - timedelta(days=1)


# ── balances (DR − CR; equity accounts are CR-normal so we flip to positive) ──
def _raw_balance(session: Session, account_id: int, as_of: Optional[date] = None) -> Decimal:
    q = (select(JournalLine.debit, JournalLine.credit)
         .select_from(JournalLine)
         .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
         .where(JournalLine.account_id == account_id,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalEntry.entry_type != JournalEntryType.REVERSAL))
    if as_of is not None:
        q = q.where(JournalEntry.entry_date <= as_of)
    total = ZERO
    for dr, cr in session.exec(q).all():
        total += Decimal(dr or 0) - Decimal(cr or 0)
    return total


def _equity_balance(session, account_id, as_of=None) -> Decimal:
    """Positive capital held in an equity account (credit balance)."""
    return (-_raw_balance(session, account_id, as_of)).quantize(CENT)


def _account_by_code(session, user_id, code) -> Optional[Account]:
    return session.exec(select(Account).where(
        Account.user_id == user_id, Account.code == code)).first()


# ── partners CRUD ────────────────────────────────────────────────────────
def list_partners(session, user_id, active_only=True) -> list[Partner]:
    q = select(Partner).where(Partner.user_id == user_id)
    if active_only:
        q = q.where(Partner.is_active == True)  # noqa: E712
    return list(session.exec(q.order_by(Partner.pct.desc(), Partner.id)).all())


def add_partner(session, user_id, name, pct, joined_on=None,
                contribution=ZERO, contribution_account_id=None, notes=None) -> Partner:
    """Create a partner: a new equity capital account + the Partner row. If a
    contribution and the asset account the money landed in are given, post
    DR <that account> / CR partner capital."""
    acct = create_account(session, user_id, name=f"{name} — Capital",
                          subclass_code="3100",
                          description=f"Partner capital account · {name}")
    p = Partner(user_id=user_id, name=name.strip(),
                account_id=acct.id, pct=Decimal(str(pct or 0)),
                joined_on=joined_on or date.today(), notes=(notes or None))
    session.add(p)
    session.commit()
    session.refresh(p)

    contribution = Decimal(str(contribution or 0))
    if contribution > 0 and contribution_account_id:
        PostingEngine.post(
            session, user_id, entry_date=p.joined_on,
            entry_type=JournalEntryType.CAPITAL_INJECTION,
            description=f"Capital contribution · {name}",
            lines=[
                {"account_id": int(contribution_account_id), "debit": contribution, "credit": 0},
                {"account_id": acct.id, "debit": 0, "credit": contribution},
            ])
    return p


def update_partner(session, user_id, partner_id, *, pct=None, name=None,
                   is_active=None, notes=None) -> Optional[Partner]:
    p = session.get(Partner, partner_id)
    if not p or p.user_id != user_id:
        return None
    if pct is not None:
        p.pct = Decimal(str(pct))
    if name is not None:
        p.name = name.strip()
    if is_active is not None:
        p.is_active = bool(is_active)
    if notes is not None:
        p.notes = notes or None
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def total_partner_pct(session, user_id) -> Decimal:
    return sum((Decimal(p.pct) for p in list_partners(session, user_id)), ZERO)


# ── cap table ────────────────────────────────────────────────────────────
def cap_table(session, user_id, as_of=None) -> dict:
    partners = list_partners(session, user_id)
    rows = []
    partner_total_cap = ZERO
    partner_total_pct = ZERO
    for p in partners:
        cap = _equity_balance(session, p.account_id, as_of) if p.account_id else ZERO
        partner_total_cap += cap
        partner_total_pct += Decimal(p.pct)
        rows.append({
            "id": p.id, "name": p.name, "pct": Decimal(p.pct),
            "capital": cap, "joined_on": p.joined_on, "account_id": p.account_id,
        })
    owner_pct = (Decimal(100) - partner_total_pct)
    owner_cap = ZERO
    for code in OWNER_CODES:
        a = _account_by_code(session, user_id, code)
        if a:
            owner_cap += _equity_balance(session, a.id, as_of)
    total_cap = owner_cap + partner_total_cap
    return {
        "owner_pct": owner_pct, "owner_capital": owner_cap,
        "partners": rows,
        "partner_total_pct": partner_total_pct,
        "partner_total_capital": partner_total_cap,
        "total_capital": total_cap,
        "as_of": as_of or date.today(),
        "over_allocated": partner_total_pct > Decimal(100),
    }


# ── monthly allocation ───────────────────────────────────────────────────
def _allocate_month(session, user_id, month_first: date, active_partners, pool) -> dict:
    month_last = _last_of_month(month_first)
    # partners who owned for the WHOLE month (joined on/before the 1st)
    parts = [p for p in active_partners if p.joined_on <= month_first]
    pl = profit_and_loss(session, user_id, from_date=month_first, to_date=month_last)
    profit = Decimal(str(pl.get("net_income", 0) or 0))

    je_id = None
    breakdown = []
    if parts and abs(profit) > Decimal("0.005"):
        lines = []
        partner_total = ZERO
        for p in parts:
            share = (profit * Decimal(p.pct) / Decimal(100)).quantize(CENT)
            if share == 0:
                continue
            partner_total += share
            breakdown.append({"partner": p.name, "share": share})
            if share > 0:      # profit → increase partner equity (CR)
                lines.append({"account_id": p.account_id, "debit": 0, "credit": share})
            else:              # loss → decrease partner equity (DR)
                lines.append({"account_id": p.account_id, "debit": -share, "credit": 0})
        if lines and partner_total != 0:
            if partner_total > 0:   # balancing DR out of the owner's retained pool
                lines.append({"account_id": pool.id, "debit": partner_total, "credit": 0})
            else:
                lines.append({"account_id": pool.id, "debit": 0, "credit": -partner_total})
            kind = "profit" if profit > 0 else "loss"
            je = PostingEngine.post(
                session, user_id, entry_date=month_last,
                entry_type=JournalEntryType.JOURNAL,
                description=(f"Partner {kind} allocation · {month_first.strftime('%b %Y')} "
                            f"· {kind} {abs(profit):,.2f}"),
                lines=lines)
            je_id = je.id

    alloc = PartnerAllocation(user_id=user_id, period=month_first,
                              profit=profit.quantize(CENT), journal_entry_id=je_id)
    session.add(alloc)
    session.commit()
    return {"period": month_first, "profit": profit.quantize(CENT),
            "je_id": je_id, "partner_count": len(parts), "breakdown": breakdown}


def run_due_allocations(session, user_id, as_of=None) -> list[dict]:
    """Idempotent catch-up: allocate every COMPLETED month from the earliest
    partner's join month up to last month that hasn't been allocated yet.
    Safe to call on every app open — the unique (user, period) row + the
    'already-done' check mean it never double-posts."""
    as_of = as_of or date.today()
    active = [p for p in list_partners(session, user_id)
              if Decimal(p.pct) > 0 and p.account_id]
    if not active:
        return []
    pool = _account_by_code(session, user_id, POOL_CODE)
    if not pool:
        return []
    done = {a.period for a in session.exec(
        select(PartnerAllocation).where(PartnerAllocation.user_id == user_id)).all()}

    earliest = _first_of_month(min(p.joined_on for p in active))
    current_month = _first_of_month(as_of)
    results = []
    m = earliest
    guard = 0
    while m < current_month and guard < 120:
        guard += 1
        if m not in done:
            results.append(_allocate_month(session, user_id, m, active, pool))
        m = _next_month(m)
    return results


def allocation_history(session, user_id, limit=24) -> list[dict]:
    rows = session.exec(select(PartnerAllocation).where(
        PartnerAllocation.user_id == user_id)
        .order_by(PartnerAllocation.period.desc())).all()
    out = []
    for a in list(rows)[:limit]:
        out.append({"period": a.period, "profit": Decimal(a.profit),
                    "je_id": a.journal_entry_id})
    return out
