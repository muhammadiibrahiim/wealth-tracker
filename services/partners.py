"""Equity partners + monthly profit allocation.

Partners each own a fixed % of the business and hold an equity capital account
(subclass 3100, "Owner's Capital"). The OWNER is the implicit remainder
(100% − Σ partner %) and keeps ALL pre-existing capital — only profit earned
going forward is split.

Each completed month, `run_due_allocations` posts ONE idempotent journal entry
that reclassifies the realised trade profit from the pool (Capital A/C 2102)
into partner capital accounts. Profit is split PER TRADE: each trade's profit
goes only to the partners who were in when that trade OPENED (joined_on <=
trade_date), so a partner shares trades started on/after they joined — never
ones already running. The owner takes the residual of every trade. Only profit
realised after the capital-setup epoch counts (earlier profit is the moved
capital). It's a pure equity reallocation — no cash moves.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from models import (Partner, PartnerAllocation, Account, JournalEntry,
                    JournalLine, JournalEntryType, Trade)
from services.posting import PostingEngine
from services.account_setup import create_account

ZERO = Decimal("0")
CENT = Decimal("0.01")
POOL_CODE = "2102"          # Capital A/C — owner's retained-earnings pool + capital
FUNDING_CODE = "2103"       # CEO — owner's funding/drawings current account (NOT capital)


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
        # Tagged PARTNER_ALLOCATION so the whole partner sub-ledger (contributions
        # + monthly splits + the capital move) stays invisible to the dashboard.
        PostingEngine.post(
            session, user_id, entry_date=p.joined_on,
            entry_type=JournalEntryType.PARTNER_ALLOCATION,
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


def _owner_partner(session, user_id) -> Optional[Partner]:
    """The owner's own capital account (is_owner), if set up."""
    return next((p for p in list_partners(session, user_id) if p.is_owner), None)


def _non_owner_partners(session, user_id) -> list[Partner]:
    return [p for p in list_partners(session, user_id) if not p.is_owner]


def total_partner_pct(session, user_id) -> Decimal:
    return sum((Decimal(p.pct) for p in _non_owner_partners(session, user_id)), ZERO)


# ── cap table ────────────────────────────────────────────────────────────
def cap_table(session, user_id, as_of=None) -> dict:
    non_owner = _non_owner_partners(session, user_id)
    owner = _owner_partner(session, user_id)
    rows = []
    partner_total_cap = ZERO
    partner_total_pct = ZERO
    for p in non_owner:
        cap = _equity_balance(session, p.account_id, as_of) if p.account_id else ZERO
        partner_total_cap += cap
        partner_total_pct += Decimal(p.pct)
        rows.append({
            "id": p.id, "name": p.name, "pct": Decimal(p.pct),
            "capital": cap, "joined_on": p.joined_on, "account_id": p.account_id,
        })
    owner_pct = (Decimal(100) - partner_total_pct)
    # The Capital A/C pool (2102) holds any profit not yet split; the owner's own
    # capital lives in their named account (e.g. "Ibrahim Capital") once set up.
    pool = _account_by_code(session, user_id, POOL_CODE)
    pool_bal = _equity_balance(session, pool.id, as_of) if pool else ZERO
    if owner and owner.account_id:
        owner_cap = _equity_balance(session, owner.account_id, as_of) + pool_bal
        owner_name = owner.name
    else:
        owner_cap = pool_bal
        owner_name = "You"
    # CEO funding account — fluctuating funding/drawings, NOT capital (info only).
    fund_acct = _account_by_code(session, user_id, FUNDING_CODE)
    owner_funding = _equity_balance(session, fund_acct.id, as_of) if fund_acct else ZERO
    total_cap = owner_cap + partner_total_cap
    return {
        "owner_pct": owner_pct, "owner_capital": owner_cap, "owner_name": owner_name,
        "owner_is_setup": bool(owner),
        "owner_funding": owner_funding,   # CEO current account — info only, not equity
        "partners": rows,
        "partner_total_pct": partner_total_pct,
        "partner_total_capital": partner_total_cap,
        "total_capital": total_cap,
        "as_of": as_of or date.today(),
        "over_allocated": partner_total_pct > Decimal(100),
    }


# ── owner capital account setup (one-time) ───────────────────────────────
def setup_owner_capital(session, user_id, name, joined_on=None) -> Partner:
    """Create the owner's own capital account and move ALL current retained
    capital (the Capital A/C pool) into it, so the pool starts empty for the
    partnership era. The move is a PARTNER_ALLOCATION entry — hidden from the
    dashboard, which stays blind to the whole partner sub-ledger."""
    existing = _owner_partner(session, user_id)
    if existing:
        return existing
    acct = create_account(session, user_id, name=name.strip(),
                          subclass_code="3100",
                          description="Owner's capital account")
    p = Partner(user_id=user_id, name=name.strip(), account_id=acct.id,
                pct=ZERO, joined_on=joined_on or date.today(), is_owner=True)
    session.add(p)
    session.commit()
    session.refresh(p)
    pool = _account_by_code(session, user_id, POOL_CODE)
    if pool:
        bal = _equity_balance(session, pool.id)   # credit-positive capital sitting in the pool
        if abs(bal) > CENT:
            if bal > 0:   # pool holds capital → move it out (DR pool / CR owner)
                lines = [{"account_id": pool.id, "debit": bal, "credit": 0},
                         {"account_id": acct.id, "debit": 0, "credit": bal}]
            else:         # pool net-debit (rare) → mirror
                lines = [{"account_id": pool.id, "debit": 0, "credit": -bal},
                         {"account_id": acct.id, "debit": -bal, "credit": 0}]
            PostingEngine.post(
                session, user_id, entry_date=date.today(),
                entry_type=JournalEntryType.PARTNER_ALLOCATION,
                description=f"Move retained capital to {name.strip()} (partnership baseline)",
                lines=lines)
    return p


# ── per-trade monthly allocation ─────────────────────────────────────────
def _realized_by_trade(session, user_id, pool, month_first, month_last, epoch):
    """Profit realized into the pool (2102) this month, per TRADE — from the
    trade closing entries (DR P&L / CR Capital A/C). Only closings dated AFTER
    the epoch (the capital-setup date) count, so the retained capital already
    moved into the owner's account is never re-allocated. Returns {trade_id:
    signed_profit}."""
    from datetime import timedelta as _td
    lo = month_first
    if epoch and epoch >= month_first:
        lo = epoch + _td(days=1)          # strictly after setup
    if lo > month_last:
        return {}
    rows = session.exec(
        select(JournalEntry.trade_id, JournalLine.debit, JournalLine.credit)
        .select_from(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == pool.id,
               JournalEntry.trade_id != None,   # noqa: E711
               JournalEntry.is_reversed == False,  # noqa: E712
               JournalEntry.entry_type != JournalEntryType.PARTNER_ALLOCATION,
               JournalEntry.entry_date >= lo,
               JournalEntry.entry_date <= month_last)).all()
    realized = {}
    for tid, dr, cr in rows:
        realized[tid] = realized.get(tid, ZERO) + (Decimal(cr or 0) - Decimal(dr or 0))
    return {t: v for t, v in realized.items() if v != 0}


def _allocate_month(session, user_id, month_first, non_owner_active, owner_partner,
                    pool, epoch) -> dict:
    month_last = _last_of_month(month_first)
    realized = _realized_by_trade(session, user_id, pool, month_first, month_last, epoch)
    total_profit = sum(realized.values(), ZERO)

    # Split EACH trade's realised profit among the non-owner partners who were in
    # when that TRADE OPENED (joined_on <= trade_date) — partners only share trades
    # started on/after they joined. The owner takes the residual of every trade.
    acct_amt: dict[int, Decimal] = {}
    name_by_acct: dict[int, str] = {}
    for tid, p_t in realized.items():
        t = session.get(Trade, tid)
        opened = t.trade_date if t else month_first
        non_owner_share = ZERO
        for p in non_owner_active:
            if p.joined_on <= opened:
                share = (p_t * Decimal(p.pct) / Decimal(100)).quantize(CENT)
                if share != 0:
                    acct_amt[p.account_id] = acct_amt.get(p.account_id, ZERO) + share
                    name_by_acct[p.account_id] = p.name
                    non_owner_share += share
        if owner_partner and owner_partner.account_id:
            owner_share = (p_t - non_owner_share).quantize(CENT)   # residual
            if owner_share != 0:
                acct_amt[owner_partner.account_id] = acct_amt.get(owner_partner.account_id, ZERO) + owner_share
                name_by_acct[owner_partner.account_id] = owner_partner.name

    je_id = None
    breakdown = []
    lines = []
    pool_move = ZERO
    for aid, amt in acct_amt.items():
        amt = amt.quantize(CENT)
        if amt == 0:
            continue
        if amt > 0:
            lines.append({"account_id": aid, "debit": 0, "credit": amt})
        else:
            lines.append({"account_id": aid, "debit": -amt, "credit": 0})
        pool_move += amt
        breakdown.append({"partner": name_by_acct.get(aid, "?"), "share": amt})
    if lines and pool_move != 0:
        if pool_move > 0:      # balancing DR out of the retained-earnings pool
            lines.append({"account_id": pool.id, "debit": pool_move, "credit": 0})
        else:
            lines.append({"account_id": pool.id, "debit": 0, "credit": -pool_move})
        kind = "profit" if total_profit >= 0 else "loss"
        je = PostingEngine.post(
            session, user_id, entry_date=month_last,
            entry_type=JournalEntryType.PARTNER_ALLOCATION,
            description=(f"Partner {kind} allocation · {month_first.strftime('%b %Y')} "
                        f"· {len(realized)} trade(s) · {kind} {abs(total_profit):,.2f}"),
            lines=lines)
        je_id = je.id

    alloc = PartnerAllocation(user_id=user_id, period=month_first,
                              profit=Decimal(total_profit).quantize(CENT), journal_entry_id=je_id)
    session.add(alloc)
    session.commit()
    return {"period": month_first, "profit": Decimal(total_profit).quantize(CENT),
            "je_id": je_id, "trade_count": len(realized), "breakdown": breakdown}


def run_due_allocations(session, user_id, as_of=None) -> list[dict]:
    """Idempotent catch-up: for every COMPLETED month since the partnership began,
    split that month's realised trade profit among partners (per trade, by the
    partners in when each trade opened). Safe to call on every app open — the
    unique (user, period) row + the 'already-done' check never double-post."""
    as_of = as_of or date.today()
    non_owner = [p for p in _non_owner_partners(session, user_id)
                 if Decimal(p.pct) > 0 and p.account_id]
    owner = _owner_partner(session, user_id)
    if not (non_owner or owner):
        return []
    pool = _account_by_code(session, user_id, POOL_CODE)
    if not pool:
        return []
    # Epoch = the owner-capital setup date (2102 was zeroed then). Only profit
    # realised after it is up for allocation; earlier profit is the moved capital.
    epoch = owner.joined_on if owner else min(p.joined_on for p in non_owner)
    done = {a.period for a in session.exec(
        select(PartnerAllocation).where(PartnerAllocation.user_id == user_id)).all()}

    earliest = _first_of_month(min([p.joined_on for p in non_owner]
                                   + ([owner.joined_on] if owner else [])))
    current_month = _first_of_month(as_of)
    results = []
    m = earliest
    guard = 0
    while m < current_month and guard < 120:
        guard += 1
        if m not in done:
            results.append(_allocate_month(session, user_id, m, non_owner, owner, pool, epoch))
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
