"""Global search for the command palette.

Two endpoints:
    GET /api/search?q=…     pages + live records, ranked, capped
    GET /api/search/pages   the full static page registry + the code→url map,
                            fetched once so the palette can filter pages with
                            no round-trip and the G-shortcut works even if the
                            record search is unavailable.

There is no authentication anywhere in this app by design (single local user),
so neither endpoint has an auth guard.

THE PALETTE MUST NEVER 500. The record-search section is wrapped so that a
renamed model field or an empty table degrades to "pages only" rather than
breaking the search box.
"""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlmodel import Session, select, or_

from database import engine
from services.search_index import PAGES, all_codes, search_pages

router = APIRouter(prefix="/api", tags=["search"])
log = logging.getLogger("uvicorn")

PER_TYPE_CAP = 6
TOTAL_CAP = 30


def _records(term: str) -> list:
    """Live record hits. Any failure here is logged and swallowed."""
    from models import (Trade, Party, Item, CashAccount, Account,
                        JournalEntry, Investment, Asset)

    like = f"%{term}%"
    out = []

    with Session(engine) as s:
        # --- Trades: match the reference, or the counterparty's name ---------
        try:
            party_ids = [
                p.id for p in s.exec(
                    select(Party).where(Party.name.ilike(like)).limit(20)
                ).all()
            ]
            cond = Trade.reference.ilike(like)
            if party_ids:
                cond = or_(cond,
                           Trade.vendor_id.in_(party_ids),
                           Trade.purchaser_id.in_(party_ids))
            names = {p.id: p.name for p in s.exec(select(Party)).all()}
            for t in s.exec(select(Trade).where(cond)
                            .order_by(Trade.id.desc()).limit(PER_TYPE_CAP)).all():
                vend = names.get(t.vendor_id, "—")
                cust = names.get(t.purchaser_id, "—")
                status = getattr(t.status, "value", t.status) or ""
                out.append({
                    "type": "Trade", "title": t.reference or f"Trade #{t.id}",
                    "subtitle": f"{vend} → {cust}" + (f" · {status}" if status else ""),
                    "url": f"/trade/trades/{t.id}", "code": "",
                })
        except Exception as e:
            log.warning(f"[search] trades: {e}")

        # --- Parties ---------------------------------------------------------
        try:
            for p in s.exec(select(Party).where(Party.name.ilike(like))
                            .limit(PER_TYPE_CAP)).all():
                kinds = []
                if getattr(p, "is_customer", False):
                    kinds.append("customer")
                if getattr(p, "is_vendor", False):
                    kinds.append("vendor")
                out.append({
                    "type": "Party", "title": p.name,
                    "subtitle": " · ".join(kinds) or "party",
                    "url": "/trade/parties", "code": "",
                })
        except Exception as e:
            log.warning(f"[search] parties: {e}")

        # --- Items -----------------------------------------------------------
        try:
            for it in s.exec(select(Item).where(
                    or_(Item.name.ilike(like), Item.sku.ilike(like))
            ).limit(PER_TYPE_CAP)).all():
                out.append({
                    "type": "Item", "title": it.name,
                    "subtitle": (it.sku or "") + (f" · {it.unit}" if it.unit else ""),
                    "url": "/trade/items", "code": "",
                })
        except Exception as e:
            log.warning(f"[search] items: {e}")

        # --- Cash accounts ---------------------------------------------------
        try:
            for a in s.exec(select(CashAccount).where(CashAccount.name.ilike(like))
                            .limit(PER_TYPE_CAP)).all():
                kind = getattr(a.kind, "value", a.kind) or ""
                out.append({
                    "type": "Cash A/C", "title": a.name,
                    "subtitle": " · ".join(x for x in [kind, a.bank_name] if x) or "cash account",
                    "url": "/trade/accounts", "code": "",
                })
        except Exception as e:
            log.warning(f"[search] cash accounts: {e}")

        # --- Chart of accounts (code + name) ---------------------------------
        try:
            for a in s.exec(select(Account).where(
                    or_(Account.code.ilike(like), Account.name.ilike(like))
            ).limit(PER_TYPE_CAP)).all():
                out.append({
                    "type": "Account", "title": f"{a.code} — {a.name}",
                    "subtitle": "chart of accounts",
                    "url": f"/trade/reports/general-ledger?account_id={a.id}",
                    "code": "",
                })
        except Exception as e:
            log.warning(f"[search] chart of accounts: {e}")

        # --- Vouchers --------------------------------------------------------
        try:
            for j in s.exec(select(JournalEntry).where(
                    or_(JournalEntry.reference.ilike(like),
                        JournalEntry.description.ilike(like))
            ).order_by(JournalEntry.id.desc()).limit(PER_TYPE_CAP)).all():
                et = getattr(j.entry_type, "value", j.entry_type) or "entry"
                when = j.entry_date.strftime("%d %b %Y") if j.entry_date else ""
                out.append({
                    "type": "Voucher", "title": j.reference or f"Entry #{j.id}",
                    "subtitle": " · ".join(x for x in [et, when, j.description] if x)[:80],
                    "url": f"/trade/vouchers/{j.id}", "code": "",
                })
        except Exception as e:
            log.warning(f"[search] vouchers: {e}")

        # --- Investments -----------------------------------------------------
        try:
            for i in s.exec(select(Investment).where(Investment.name.ilike(like))
                            .limit(PER_TYPE_CAP)).all():
                out.append({
                    "type": "Investment", "title": i.name,
                    "subtitle": getattr(i.investment_type, "value", i.investment_type) or "investment",
                    "url": f"/investments/{i.id}", "code": "",
                })
        except Exception as e:
            log.warning(f"[search] investments: {e}")

        # --- Assets ----------------------------------------------------------
        try:
            for a in s.exec(select(Asset).where(Asset.name.ilike(like))
                            .limit(PER_TYPE_CAP)).all():
                out.append({
                    "type": "Asset", "title": a.name, "subtitle": "wealth asset",
                    "url": "/wealth/assets", "code": "",
                })
        except Exception as e:
            log.warning(f"[search] assets: {e}")

    return out


@router.get("/search")
def api_search(q: str = "") -> JSONResponse:
    """Pages first, then live records. Never raises."""
    term = (q or "").strip()
    results = search_pages(term, limit=8)
    if len(term) >= 1:
        try:
            results = results + _records(term)
        except Exception as e:                      # belt and braces
            log.warning(f"[search] record search failed entirely: {e}")
    return JSONResponse({"results": results[:TOTAL_CAP]})


@router.get("/search/pages")
def api_search_pages() -> JSONResponse:
    """The full static page registry + the code→url map, fetched once on first
    palette open so page filtering is instant and G-codes work offline of the
    record search."""
    return JSONResponse({
        "pages": [
            {"type": "Page", "title": p["title"], "subtitle": p["module"],
             "url": p["url"], "code": p["code"], "keys": p["keys"]}
            for p in PAGES
        ],
        "codes": all_codes(),
    })
