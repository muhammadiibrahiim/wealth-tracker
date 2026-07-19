"""Import & analytics for the personal Money Manager cashbook.

The Money Manager XLSX export is a per-account, double-entry cashbook:
every transfer is two rows (Transfer-Out on the source, Transfer-In on the
destination). We store each row against its own account, so an account's
balance is simply sum(in) − sum(out) over its rows.

Import is APPEND-ONLY and idempotent: each row gets a stable `source_hash`
and is inserted only if that hash isn't already present for the user, so
re-importing an overlapping export can never create duplicates.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, select

from models import MoneyAccount, MoneyAccountType, MoneyTxn, MoneyTxnKind

ZERO = Decimal("0")

# Money Manager "Income/Expense" column -> (kind, direction)
_TYPE_MAP = {
    "transfer-in": (MoneyTxnKind.transfer, "in"),
    "transfer-out": (MoneyTxnKind.transfer, "out"),
    "income": (MoneyTxnKind.income, "in"),
    "exp.": (MoneyTxnKind.expense, "out"),
    "expense": (MoneyTxnKind.expense, "out"),
    "income balance": (MoneyTxnKind.balance, "in"),
    "expense balance": (MoneyTxnKind.balance, "out"),
}


def _norm(name) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip())


def _dec(v) -> Decimal:
    if v in (None, ""):
        return ZERO
    try:
        return Decimal(str(v).replace(",", ""))
    except (InvalidOperation, ValueError):
        return ZERO


def classify(name: str) -> MoneyAccountType:
    """Best-effort account type from its name. The user can re-type later."""
    n = name.lower()
    if any(w in n for w in ("bank", "meezan", "allied", "faysal", "hbl", "ubl", "askari")):
        return MoneyAccountType.bank
    if any(w in n for w in ("cash",)):
        return MoneyAccountType.cash
    if any(w in n for w in ("easypaisa", "jazz", "nayapay", "naya pay", "sadapay",
                            "binance", "wallet", "paypal")):
        return MoneyAccountType.wallet
    if any(w in n for w in ("ibrahim traders", "cambrify", "adify", "ma foods", "kleid",
                            "fleure", "flyers", "ecom", "ownership", "website", "trendy")):
        return MoneyAccountType.business
    if any(w in n for w in ("investment", "pool", "binance", "plot", "gold")):
        return MoneyAccountType.investment
    if any(w in n for w in ("macbook", "car", "bike", "gym", "laptop", "phone", "iphone")):
        return MoneyAccountType.asset
    if any(w in n for w in ("exp", "expense", "donation", "home ", "trip", "stall",
                            "food", "personal", "license", "card fees", "kids")):
        return MoneyAccountType.expense
    return MoneyAccountType.other


def _hash(occurred: datetime, account: str, category: str, type_raw: str,
          amount: Decimal, note: str, desc: str, occ: int) -> str:
    """Stable dedup key. Deliberately normalises the volatile bits so the SAME
    transaction hashes identically whether it comes from the 2-year export or a
    later monthly export: the datetime is formatted to whole seconds and the
    amount is quantised to 2dp (so 5000 / 5000.0 / 5000.00 all match)."""
    occ_key = occurred.strftime("%Y-%m-%d %H:%M:%S")
    amt_key = str(amount.quantize(Decimal("0.01")))
    raw = "|".join([occ_key, account.lower(), category.lower(), type_raw.lower(),
                    amt_key, note.lower(), desc.lower(), str(occ)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def import_cashbook(session: Session, user_id: int, file_path: str) -> dict:
    """Parse a Money Manager XLSX and append new rows. Returns import stats."""
    import openpyxl

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {"error": "empty file"}
    data = rows[1:]  # skip header

    # existing accounts (upsert by normalised name — preserve user-set type/notes)
    accounts = {
        _norm(a.name).lower(): a
        for a in session.exec(select(MoneyAccount).where(MoneyAccount.user_id == user_id)).all()
    }
    existing_hashes = set(session.exec(
        select(MoneyTxn.source_hash).where(MoneyTxn.user_id == user_id)
    ).all())

    def get_account(name: str) -> MoneyAccount | None:
        name = _norm(name)
        if not name:
            return None
        key = name.lower()
        acc = accounts.get(key)
        if acc is None:
            acc = MoneyAccount(user_id=user_id, name=name, type=classify(name),
                               sort_order=len(accounts))
            session.add(acc)
            session.flush()  # get id
            accounts[key] = acc
        return acc

    batch = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    occ_counter: dict = defaultdict(int)
    inserted = 0
    skipped = 0
    new_accounts_before = len(accounts)
    pending: list = []

    for r in data:
        # tolerate short rows
        period = r[0] if len(r) > 0 else None
        account_raw = r[1] if len(r) > 1 else None
        category = r[2] if len(r) > 2 else None
        subcat = r[3] if len(r) > 3 else None
        note = r[4] if len(r) > 4 else None
        pkr = r[5] if len(r) > 5 else None
        type_raw = r[6] if len(r) > 6 else None
        desc = r[7] if len(r) > 7 else None
        amount_col = r[8] if len(r) > 8 else None
        currency = r[9] if len(r) > 9 else "PKR"

        account_name = _norm(account_raw)
        if not account_name or not type_raw:
            continue
        kd = _TYPE_MAP.get(str(type_raw).strip().lower())
        if kd is None:
            continue
        kind, direction = kd

        # occurred_at
        if isinstance(period, datetime):
            occurred = period
        else:
            try:
                occurred = datetime.fromisoformat(str(period))
            except (ValueError, TypeError):
                continue
        amount = _dec(pkr if pkr not in (None, "") else amount_col)
        if amount <= 0:
            continue

        base = _hash(occurred, account_name, _norm(category),
                     str(type_raw).strip(), amount, _norm(note), _norm(desc), 0)
        occ = occ_counter[base]
        occ_counter[base] += 1
        h = _hash(occurred, account_name, _norm(category),
                  str(type_raw).strip(), amount, _norm(note), _norm(desc), occ)

        if h in existing_hashes:
            skipped += 1
            continue
        existing_hashes.add(h)

        acc = get_account(account_name)
        counter = get_account(category) if kind == MoneyTxnKind.transfer else None

        pending.append(MoneyTxn(
            user_id=user_id,
            occurred_at=occurred,
            account_id=acc.id,
            counter_account_id=counter.id if counter else None,
            category=_norm(category) or None,
            subcategory=_norm(subcat) or None,
            note=_norm(note) or None,
            description=_norm(desc) or None,
            amount=amount,
            direction=direction,
            kind=kind,
            currency=_norm(currency) or "PKR",
            source_hash=h,
            import_batch=batch,
        ))
        inserted += 1

    session.add_all(pending)
    session.commit()

    return {
        "inserted": inserted,
        "skipped": skipped,
        "new_accounts": len(accounts) - new_accounts_before,
        "total_accounts": len(accounts),
        "batch": batch,
    }


# ─────────────────────────── analytics ───────────────────────────


def account_balances(session: Session, user_id: int) -> dict:
    """account_id -> Decimal balance (sum in − sum out)."""
    bal: dict = defaultdict(lambda: ZERO)
    rows = session.exec(
        select(MoneyTxn.account_id, MoneyTxn.direction, MoneyTxn.amount)
        .where(MoneyTxn.user_id == user_id)
    ).all()
    for account_id, direction, amount in rows:
        amt = Decimal(amount)
        bal[account_id] += amt if direction == "in" else -amt
    return bal


# high-level grouping of account types into net-worth buckets
_GROUP = {
    MoneyAccountType.cash: "Cash & Bank",
    MoneyAccountType.bank: "Cash & Bank",
    MoneyAccountType.wallet: "Cash & Bank",
    MoneyAccountType.person: "People (loans)",
    MoneyAccountType.business: "Businesses",
    MoneyAccountType.investment: "Investments",
    MoneyAccountType.asset: "Assets",
    MoneyAccountType.expense: "Expense tracking",
    MoneyAccountType.other: "Other",
}
_GROUP_ORDER = ["Cash & Bank", "People (loans)", "Businesses", "Investments",
                "Assets", "Expense tracking", "Other"]

# Money Manager's own group order (used when accounts carry a group_name).
MM_GROUP_ORDER = ["Cash", "Accounts", "Investments", "Bank accounts",
                  "Equity holdings", "Friends", "company accounts", "Family",
                  "Flyers business", "Assets"]


def overview(session: Session, user_id: int) -> dict:
    """Net-worth composition + per-account balances grouped to mirror Money
    Manager (by each account's group_name; type-based fallback for the rest)."""
    accts = session.exec(
        select(MoneyAccount).where(MoneyAccount.user_id == user_id)
        .order_by(MoneyAccount.sort_order, MoneyAccount.name)
    ).all()
    bal = account_balances(session, user_id)

    groups: dict = {}                    # group name -> dict, created on demand
    group_seq: list = []                 # insertion order of groups we actually see

    def group_slot(name: str) -> dict:
        if name not in groups:
            groups[name] = {"name": name, "total": ZERO, "accounts": []}
            group_seq.append(name)
        return groups[name]

    total = ZERO
    total_assets = ZERO
    total_liabilities = ZERO
    excluded_count = 0
    active_count = 0
    inactive = []               # deleted-in-Money-Manager accounts, kept for history
    ungrouped = []              # active accounts with no group yet (e.g. new from a sync)
    for a in accts:
        b = bal.get(a.id, ZERO)
        if not a.is_active:
            inactive.append({"acct": a, "balance": b})
            continue
        active_count += 1
        included = bool(a.include_in_networth)
        if included:
            total += b
            if b >= 0:
                total_assets += b
            else:
                total_liabilities += b
        else:
            excluded_count += 1
        entry = {"acct": a, "balance": b, "included": included}
        if a.group_name:
            slot = group_slot(a.group_name)
            slot["accounts"].append(entry)
            if included:
                slot["total"] += b
        else:
            ungrouped.append(entry)

    # order groups: Money Manager order first, then any others as encountered
    ordered_names = [g for g in MM_GROUP_ORDER if g in groups]
    ordered_names += [g for g in group_seq if g not in ordered_names]
    group_list = [groups[g] for g in ordered_names if groups[g]["accounts"]]
    for g in group_list:
        g["accounts"].sort(key=lambda x: x["balance"], reverse=True)
    inactive.sort(key=lambda x: x["balance"], reverse=True)
    ungrouped.sort(key=lambda x: x["balance"], reverse=True)
    # options for the group picker: MM order first, then any custom groups in use
    all_group_names = list(MM_GROUP_ORDER)
    for g in ordered_names:
        if g not in all_group_names:
            all_group_names.append(g)

    txn_count = session.exec(
        select(MoneyTxn.id).where(MoneyTxn.user_id == user_id)
    ).all()
    last = session.exec(
        select(MoneyTxn.occurred_at).where(MoneyTxn.user_id == user_id)
        .order_by(MoneyTxn.occurred_at.desc()).limit(1)
    ).first()

    return {
        "groups": group_list,
        "net_worth": total,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "account_count": len(accts),
        "active_count": active_count,
        "excluded_count": excluded_count,
        "inactive": inactive,
        "ungrouped": ungrouped,
        "all_group_names": all_group_names,
        "txn_count": len(txn_count),
        "last_txn": last,
    }


def _period_bounds(from_date, to_date):
    """date -> datetime bounds (inclusive day)."""
    lo = datetime(from_date.year, from_date.month, from_date.day) if from_date else None
    hi = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59) if to_date else None
    return lo, hi


def data_range(session: Session, user_id: int):
    """(earliest, latest) occurred_at for this user, or (None, None)."""
    lo = session.exec(select(MoneyTxn.occurred_at).where(MoneyTxn.user_id == user_id)
                      .order_by(MoneyTxn.occurred_at).limit(1)).first()
    hi = session.exec(select(MoneyTxn.occurred_at).where(MoneyTxn.user_id == user_id)
                      .order_by(MoneyTxn.occurred_at.desc()).limit(1)).first()
    return lo, hi


def income_expense(session: Session, user_id: int, from_date=None, to_date=None) -> dict:
    """Real income vs expense by category (transfers & opening balances excluded).

    Transfers just move money between your own accounts, so they aren't income
    or spending — only `income` and `expense` rows count."""
    lo, hi = _period_bounds(from_date, to_date)
    q = select(MoneyTxn.kind, MoneyTxn.category, MoneyTxn.amount).where(
        MoneyTxn.user_id == user_id,
        MoneyTxn.kind.in_([MoneyTxnKind.income, MoneyTxnKind.expense]),
    )
    if lo is not None:
        q = q.where(MoneyTxn.occurred_at >= lo)
    if hi is not None:
        q = q.where(MoneyTxn.occurred_at <= hi)

    inc: dict = defaultdict(lambda: ZERO)
    exp: dict = defaultdict(lambda: ZERO)
    for kind, category, amount in session.exec(q).all():
        cat = (category or "Uncategorised")
        if str(kind) == MoneyTxnKind.income or kind == MoneyTxnKind.income:
            inc[cat] += Decimal(amount)
        else:
            exp[cat] += Decimal(amount)

    inc_rows = sorted(({"category": c, "amount": a} for c, a in inc.items()),
                      key=lambda x: x["amount"], reverse=True)
    exp_rows = sorted(({"category": c, "amount": a} for c, a in exp.items()),
                      key=lambda x: x["amount"], reverse=True)
    total_inc = sum((r["amount"] for r in inc_rows), ZERO)
    total_exp = sum((r["amount"] for r in exp_rows), ZERO)
    return {
        "income": inc_rows, "expense": exp_rows,
        "total_income": total_inc, "total_expense": total_exp,
        "net": total_inc - total_exp,
    }


def monthly_cashflow(session: Session, user_id: int) -> dict:
    """Per-month real income, expense and net (transfers/balances excluded)."""
    rows = session.exec(
        select(MoneyTxn.occurred_at, MoneyTxn.kind, MoneyTxn.amount).where(
            MoneyTxn.user_id == user_id,
            MoneyTxn.kind.in_([MoneyTxnKind.income, MoneyTxnKind.expense]),
        )
    ).all()
    buckets: dict = defaultdict(lambda: {"income": ZERO, "expense": ZERO})
    for occurred, kind, amount in rows:
        key = (occurred.year, occurred.month)
        if kind == MoneyTxnKind.income or str(kind) == MoneyTxnKind.income:
            buckets[key]["income"] += Decimal(amount)
        else:
            buckets[key]["expense"] += Decimal(amount)

    months = []
    for (y, m) in sorted(buckets.keys(), reverse=True):
        b = buckets[(y, m)]
        months.append({
            "year": y, "month": m,
            "label": datetime(y, m, 1).strftime("%b %Y"),
            "income": b["income"], "expense": b["expense"],
            "net": b["income"] - b["expense"],
        })
    tot_inc = sum((mo["income"] for mo in months), ZERO)
    tot_exp = sum((mo["expense"] for mo in months), ZERO)
    return {"months": months, "total_income": tot_inc, "total_expense": tot_exp,
            "net": tot_inc - tot_exp, "peak_month": max(months, key=lambda x: x["expense"], default=None)}


def all_statements(session: Session, user_id: int) -> list:
    """Every account with its balance and txn count, grouped for a statements index."""
    accts = session.exec(
        select(MoneyAccount).where(MoneyAccount.user_id == user_id)
        .order_by(MoneyAccount.name)
    ).all()
    bal = account_balances(session, user_id)
    counts: dict = defaultdict(int)
    for aid in session.exec(
        select(MoneyTxn.account_id).where(MoneyTxn.user_id == user_id)
    ).all():
        counts[aid] += 1
    return [{"acct": a, "balance": bal.get(a.id, ZERO), "count": counts.get(a.id, 0)}
            for a in accts]


def account_ledger(session: Session, user_id: int, account_id: int, limit: int = 500) -> dict:
    """A single account's transactions with a running balance (oldest→newest)."""
    acct = session.get(MoneyAccount, account_id)
    if not acct or acct.user_id != user_id:
        return {"account": None, "rows": [], "balance": ZERO}

    txns = session.exec(
        select(MoneyTxn).where(MoneyTxn.user_id == user_id, MoneyTxn.account_id == account_id)
        .order_by(MoneyTxn.occurred_at)
    ).all()
    # counter account names
    ca_ids = {t.counter_account_id for t in txns if t.counter_account_id}
    ca_names = {}
    if ca_ids:
        for a in session.exec(select(MoneyAccount).where(MoneyAccount.id.in_(ca_ids))).all():
            ca_names[a.id] = a.name

    rows = []
    running = ZERO
    for t in txns:
        amt = Decimal(t.amount)
        running += amt if t.direction == "in" else -amt
        rows.append({
            "txn": t,
            "counter": ca_names.get(t.counter_account_id) or t.category or "—",
            "running": running,
        })
    rows.reverse()  # newest first for display
    return {"account": acct, "rows": rows, "balance": running, "count": len(txns)}
