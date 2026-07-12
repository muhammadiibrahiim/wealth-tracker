"""One-time chart of accounts setup + migration of legacy opening balances.

Customized for a flyer / poly-bag trading business.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from models import (
    Account,
    AccountClass,
    AccountNature,
    AccountSubClass,
    CashAccount,
    JournalEntryType,
    JournalLine,
    Party,
)
from services.posting import PostingEngine


ZERO = Decimal("0")


# Class → Subclass hierarchy
COA_SEED = [
    ("1000", "Assets", AccountNature.ASSET, [
        ("1100", "Cash & Bank"),
        ("1200", "Accounts Receivable"),
        ("1300", "Inventory / WIP"),
        ("1900", "Other Assets"),
    ]),
    ("2000", "Liabilities", AccountNature.LIABILITY, [
        ("2100", "Accounts Payable"),
        ("2900", "Other Liabilities"),
    ]),
    ("3000", "Equity", AccountNature.EQUITY, [
        ("3100", "Owner's Capital"),
        ("3900", "Equity Adjustments"),
    ]),
    ("4000", "Income", AccountNature.INCOME, [
        ("4100", "Sales Revenue"),
        ("4900", "Other Income"),
    ]),
    ("5000", "Expenses", AccountNature.EXPENSE, [
        ("5100", "Cost of Goods Sold"),
        ("5200", "Operating Expenses"),
        ("5300", "Selling Expenses"),
        ("5400", "Admin Expenses"),
        ("5900", "Other Expenses"),
    ]),
]


# Pre-seeded leaf accounts: code, name, subclass_code, is_system
SYSTEM_ACCOUNTS = [
    # System-protected
    ("4101", "Sales Revenue",              "4100", True),
    ("5101", "Cost of Goods Sold",         "5100", True),
    ("3901", "Opening Balance Equity",     "3900", True),
    ("3902", "Retained Earnings",          "3900", True),
    # Trading clearing account — every trade flows DR/CR through here and
    # the closing entry zeroes it back to nil into Capital A/C.
    ("3903", "Profit / Loss A/C",          "3900", True),
    # Owner's capital — where P&L closes into and where trade costs land via
    # Record Cost. Every code path that reads Account.name == "Capital A/C"
    # depends on this row existing on every install.
    ("3101", "Capital A/C",                "3100", True),
    # Operating expenses common to a flyer printing brokerage (editable)
    ("5201", "Rent — Office / Warehouse",  "5200", False),
    ("5202", "Utilities — Electricity",    "5200", False),
    ("5203", "Staff Salaries",             "5200", False),
    ("5204", "Transport / Delivery",       "5200", False),
    ("5205", "Internet / Phone",           "5200", False),
    ("5206", "Office Supplies",            "5200", False),
    ("5301", "Marketing & Advertising",    "5300", False),
    ("5302", "Sales Commissions",          "5300", False),
    ("5401", "Bank Charges",               "5400", False),
    ("5402", "Stationery & Printing",      "5400", False),
    ("5403", "Repairs & Maintenance",      "5400", False),
    ("4901", "Other Income",               "4900", False),
    ("5901", "Other Expenses",             "5900", False),
]


def seed_chart_of_accounts(session: Session, user_id: int) -> None:
    """Idempotent: ensure class/subclass hierarchy + pre-seeded accounts exist."""
    class_by_code: dict[str, AccountClass] = {}
    for sort, (code, name, nature, _subs) in enumerate(COA_SEED):
        existing = session.exec(
            select(AccountClass).where(AccountClass.user_id == user_id, AccountClass.code == code)
        ).first()
        if existing:
            class_by_code[code] = existing
            continue
        cls = AccountClass(user_id=user_id, code=code, name=name, nature=nature, sort_order=sort)
        session.add(cls)
        session.flush()
        class_by_code[code] = cls

    subclass_by_code: dict[str, AccountSubClass] = {}
    for class_code, _, _, subs in COA_SEED:
        cls = class_by_code[class_code]
        for sort, (sub_code, sub_name) in enumerate(subs):
            existing = session.exec(
                select(AccountSubClass).where(AccountSubClass.user_id == user_id, AccountSubClass.code == sub_code)
            ).first()
            if existing:
                subclass_by_code[sub_code] = existing
                continue
            sub = AccountSubClass(
                user_id=user_id, class_id=cls.id, code=sub_code, name=sub_name, sort_order=sort
            )
            session.add(sub)
            session.flush()
            subclass_by_code[sub_code] = sub

    for code, name, sub_code, is_system in SYSTEM_ACCOUNTS:
        existing = session.exec(
            select(Account).where(Account.user_id == user_id, Account.code == code)
        ).first()
        if existing:
            continue
        sub = subclass_by_code[sub_code]
        session.add(Account(
            user_id=user_id, code=code, name=name,
            class_id=sub.class_id, subclass_id=sub.id, is_system=is_system,
        ))
    session.commit()


def next_account_code(session: Session, user_id: int, subclass_code: str) -> str:
    """Find the next free leaf code under a subclass (e.g. 1201, 1202, …)."""
    base = int(subclass_code)
    lo = base + 1
    hi = base + 99
    rows = list(session.exec(
        select(Account).where(
            Account.user_id == user_id,
            Account.code >= str(lo),
            Account.code <= str(hi),
        ).order_by(Account.code.desc())
    ).all())
    if not rows:
        return str(lo)
    last = int(rows[0].code)
    nxt = last + 1
    if nxt > hi:
        raise ValueError(f"Subclass {subclass_code} is full (codes {lo}-{hi})")
    return str(nxt)


def create_account(
    session: Session,
    user_id: int,
    *,
    name: str,
    subclass_code: str,
    is_system: bool = False,
    description: Optional[str] = None,
) -> Account:
    """Create a leaf account under the named subclass with an auto-numbered code."""
    sub = session.exec(
        select(AccountSubClass).where(
            AccountSubClass.user_id == user_id, AccountSubClass.code == subclass_code
        )
    ).first()
    if not sub:
        raise ValueError(f"Subclass {subclass_code} not found — run seed_chart_of_accounts first")
    code = next_account_code(session, user_id, subclass_code)
    a = Account(
        user_id=user_id, code=code, name=name,
        class_id=sub.class_id, subclass_id=sub.id,
        description=description, is_system=is_system,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def sync_party_account(session: Session, user_id: int, party: Party) -> Account:
    """Create or return the Account linked to a party. Customer → AR, Vendor → AP."""
    if party.account_id:
        a = session.get(Account, party.account_id)
        if a:
            return a
    sub_code = "1200" if party.is_customer else "2100"
    a = create_account(session, user_id, name=party.name, subclass_code=sub_code,
                       description=f"Party ledger for {party.name}")
    party.account_id = a.id
    session.add(party)
    session.commit()
    return a


def sync_cash_account(session: Session, user_id: int, cash: CashAccount) -> Account:
    """Create or return the Account linked to a CashAccount."""
    if cash.account_id:
        a = session.get(Account, cash.account_id)
        if a:
            return a
    sub_code = "3100" if cash.kind == "capital" else "1100"
    a = create_account(session, user_id, name=cash.name, subclass_code=sub_code,
                       description=f"{cash.kind} account")
    cash.account_id = a.id
    session.add(cash)
    session.commit()
    return a


def list_accounts_grouped(session: Session, user_id: int) -> list[dict]:
    """All accounts grouped by class → subclass → leaf."""
    classes = list(session.exec(
        select(AccountClass).where(AccountClass.user_id == user_id).order_by(AccountClass.code)
    ).all())
    subclasses = list(session.exec(
        select(AccountSubClass).where(AccountSubClass.user_id == user_id).order_by(AccountSubClass.code)
    ).all())
    accounts = list(session.exec(
        select(Account).where(Account.user_id == user_id).order_by(Account.code)
    ).all())

    subs_by_class: dict[int, list[AccountSubClass]] = {}
    for s in subclasses:
        subs_by_class.setdefault(s.class_id, []).append(s)
    accts_by_sub: dict[int, list[Account]] = {}
    accts_by_class_only: dict[int, list[Account]] = {}
    for a in accounts:
        if a.subclass_id:
            accts_by_sub.setdefault(a.subclass_id, []).append(a)
        else:
            accts_by_class_only.setdefault(a.class_id, []).append(a)

    out = []
    for cls in classes:
        sub_blocks = []
        for sub in subs_by_class.get(cls.id, []):
            sub_blocks.append({"subclass": sub, "accounts": accts_by_sub.get(sub.id, [])})
        out.append({
            "class": cls,
            "subclasses": sub_blocks,
            "accounts_without_subclass": accts_by_class_only.get(cls.id, []),
        })
    return out


def soft_disable_account(session: Session, user_id: int, account_id: int) -> bool:
    a = session.get(Account, account_id)
    if not a or a.user_id != user_id or a.is_system:
        return False
    a.is_active = False
    a.updated_at = datetime.utcnow()
    session.add(a)
    session.commit()
    return True


def update_account(session: Session, user_id: int, account_id: int, *,
                   name: str, description: Optional[str]) -> Optional[Account]:
    a = session.get(Account, account_id)
    if not a or a.user_id != user_id:
        return None
    a.name = name
    a.description = description
    a.updated_at = datetime.utcnow()
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def migrate_opening_balances(session: Session, user_id: int) -> dict:
    """Wire every Party/CashAccount to an Account, then post one OPENING journal entry."""
    seed_chart_of_accounts(session, user_id)

    parties = list(session.exec(
        select(Party).where(Party.user_id == user_id, Party.is_active == True)  # noqa: E712
    ).all())
    cash_accounts = list(session.exec(
        select(CashAccount).where(CashAccount.user_id == user_id, CashAccount.is_active == True)  # noqa: E712
    ).all())

    party_accounts = [(p, sync_party_account(session, user_id, p)) for p in parties]
    cash_account_pairs = [(c, sync_cash_account(session, user_id, c)) for c in cash_accounts]

    # Check if an OPENING entry already exists — idempotent migration.
    from models import JournalEntry
    existing_opening = session.exec(
        select(JournalEntry).where(
            JournalEntry.user_id == user_id,
            JournalEntry.entry_type == JournalEntryType.OPENING,
        )
    ).first()
    if existing_opening:
        return {
            "parties_synced": len(party_accounts),
            "cash_synced": len(cash_account_pairs),
            "opening_entry": existing_opening.reference,
            "note": "OPENING entry already posted; skipping re-post",
        }

    lines: list[dict] = []
    total_dr = ZERO
    total_cr = ZERO

    for c, a in cash_account_pairs:
        ob = Decimal(c.opening_balance or 0)
        if ob == 0:
            continue
        if c.kind == "capital":
            lines.append({"account_id": a.id, "debit": 0, "credit": ob, "description": "Opening balance"})
            total_cr += ob
        else:
            lines.append({"account_id": a.id, "debit": ob, "credit": 0, "description": "Opening balance"})
            total_dr += ob

    for p, a in party_accounts:
        ob = Decimal(p.opening_balance or 0)
        if ob == 0:
            continue
        side = "receivable" if p.is_customer else "payable"
        desc = f"Opening balance — {p.name} ({side})"
        if p.is_customer:
            if ob > 0:
                lines.append({"account_id": a.id, "debit": ob, "credit": 0,
                              "description": desc, "party_id": p.id})
                total_dr += ob
            else:
                lines.append({"account_id": a.id, "debit": 0, "credit": -ob,
                              "description": desc, "party_id": p.id})
                total_cr += -ob
        else:
            if ob < 0:
                lines.append({"account_id": a.id, "debit": 0, "credit": -ob,
                              "description": desc, "party_id": p.id})
                total_cr += -ob
            else:
                lines.append({"account_id": a.id, "debit": ob, "credit": 0,
                              "description": desc, "party_id": p.id})
                total_dr += ob

    plug = total_dr - total_cr
    if abs(plug) > Decimal("0.005"):
        obe = session.exec(
            select(Account).where(Account.user_id == user_id, Account.code == "3901")
        ).first()
        if not obe:
            raise RuntimeError("3901 Opening Balance Equity not seeded")
        if plug > 0:
            lines.append({"account_id": obe.id, "debit": 0, "credit": plug, "description": "Opening balance plug"})
        else:
            lines.append({"account_id": obe.id, "debit": -plug, "credit": 0, "description": "Opening balance plug"})

    if not lines:
        return {"parties_synced": len(party_accounts), "cash_synced": len(cash_account_pairs),
                "opening_entry": None}

    je = PostingEngine.post(
        session, user_id,
        entry_date=date.today(),
        entry_type=JournalEntryType.OPENING,
        description="Migration: opening balances captured from operational records",
        lines=lines,
        reference=None,
        created_by="migration",
    )
    return {
        "parties_synced": len(party_accounts),
        "cash_synced": len(cash_account_pairs),
        "opening_entry": je.reference,
        "lines": len(lines),
    }
