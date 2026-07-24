"""
Service layer for the Trade module:
parties, cash accounts, items, trades, payments, and reports.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select, func, or_

from models import (
    Account,
    CashAccount,
    Item,
    ItemSpecField,
    JournalEntry,
    JournalEntryType,
    JournalLine,
    Party,
    PaymentDirection,
    Quotation,
    QuotationLine,
    QuotationLineSpec,
    QuotationStatus,
    Trade,
    TradeAttachment,
    TradeAttachmentKind,
    TradeLine,
    TradeLineReceipt,
    TradeLineSpec,
    TradePurchase,
    TradePayment,
    TradeStatus,
)


ZERO = Decimal("0")


# ─────────────────────────── Parties ────────────────────────────


class PartyService:
    @staticmethod
    def list(session: Session, user_id: int, active_only: bool = False) -> list[Party]:
        q = select(Party).where(Party.user_id == user_id)
        if active_only:
            q = q.where(Party.is_active == True)  # noqa: E712
        q = q.order_by(Party.name)
        return list(session.exec(q).all())

    @staticmethod
    def list_vendors(session: Session, user_id: int) -> list[Party]:
        q = (
            select(Party)
            .where(Party.user_id == user_id, Party.is_vendor == True, Party.is_active == True)  # noqa: E712
            .order_by(Party.name)
        )
        return list(session.exec(q).all())

    @staticmethod
    def list_customers(session: Session, user_id: int) -> list[Party]:
        q = (
            select(Party)
            .where(Party.user_id == user_id, Party.is_customer == True, Party.is_active == True)  # noqa: E712
            .order_by(Party.name)
        )
        return list(session.exec(q).all())

    @staticmethod
    def get(session: Session, user_id: int, party_id: int) -> Optional[Party]:
        p = session.get(Party, party_id)
        if p and p.user_id == user_id:
            return p
        return None

    @staticmethod
    def create(session: Session, user_id: int, **data) -> Party:
        p = Party(user_id=user_id, **data)
        session.add(p)
        session.commit()
        session.refresh(p)
        return p

    @staticmethod
    def update(session: Session, user_id: int, party_id: int, **data) -> Optional[Party]:
        p = PartyService.get(session, user_id, party_id)
        if not p:
            return None
        for k, v in data.items():
            setattr(p, k, v)
        p.updated_at = datetime.utcnow()
        session.add(p)
        session.commit()
        session.refresh(p)
        return p

    @staticmethod
    def delete(session: Session, user_id: int, party_id: int) -> bool:
        p = PartyService.get(session, user_id, party_id)
        if not p:
            return False
        # Soft-disable so existing trades keep their party reference intact.
        p.is_active = False
        p.updated_at = datetime.utcnow()
        session.add(p)
        session.commit()
        return True


# ──────────────────────── Cash Accounts ─────────────────────────


class CashAccountService:
    @staticmethod
    def list(session: Session, user_id: int, active_only: bool = False) -> list[CashAccount]:
        q = select(CashAccount).where(CashAccount.user_id == user_id)
        if active_only:
            q = q.where(CashAccount.is_active == True)  # noqa: E712
        q = q.order_by(CashAccount.name)
        return list(session.exec(q).all())

    @staticmethod
    def get(session: Session, user_id: int, account_id: int) -> Optional[CashAccount]:
        a = session.get(CashAccount, account_id)
        if a and a.user_id == user_id:
            return a
        return None

    @staticmethod
    def create(session: Session, user_id: int, **data) -> CashAccount:
        a = CashAccount(user_id=user_id, **data)
        session.add(a)
        session.commit()
        session.refresh(a)
        return a

    @staticmethod
    def update(session: Session, user_id: int, account_id: int, **data) -> Optional[CashAccount]:
        a = CashAccountService.get(session, user_id, account_id)
        if not a:
            return None
        for k, v in data.items():
            setattr(a, k, v)
        a.updated_at = datetime.utcnow()
        session.add(a)
        session.commit()
        session.refresh(a)
        return a

    @staticmethod
    def delete(session: Session, user_id: int, account_id: int) -> bool:
        a = CashAccountService.get(session, user_id, account_id)
        if not a:
            return False
        a.is_active = False
        a.updated_at = datetime.utcnow()
        session.add(a)
        session.commit()
        return True

    @staticmethod
    def balance(session: Session, user_id: int, account_id: int) -> Decimal:
        """Opening balance + sum(inbound) - sum(outbound) across all trades."""
        acc = CashAccountService.get(session, user_id, account_id)
        if not acc:
            return ZERO
        inbound = session.exec(
            select(func.coalesce(func.sum(TradePayment.amount), 0)).where(
                TradePayment.cash_account_id == account_id,
                TradePayment.direction == PaymentDirection.INBOUND,
            )
        ).one()
        outbound = session.exec(
            select(func.coalesce(func.sum(TradePayment.amount), 0)).where(
                TradePayment.cash_account_id == account_id,
                TradePayment.direction == PaymentDirection.OUTBOUND,
            )
        ).one()
        return Decimal(acc.opening_balance) + Decimal(inbound or 0) - Decimal(outbound or 0)


# ──────────────────────────── Items ─────────────────────────────


class ItemService:
    @staticmethod
    def list(session: Session, user_id: int, active_only: bool = False) -> list[Item]:
        q = select(Item).where(Item.user_id == user_id)
        if active_only:
            q = q.where(Item.is_active == True)  # noqa: E712
        q = q.order_by(Item.name)
        return list(session.exec(q).all())

    @staticmethod
    def get(session: Session, user_id: int, item_id: int) -> Optional[Item]:
        i = session.get(Item, item_id)
        if i and i.user_id == user_id:
            return i
        return None

    @staticmethod
    def create(session: Session, user_id: int, spec_labels: Optional[list[str]] = None, **data) -> Item:
        i = Item(user_id=user_id, **data)
        session.add(i)
        session.flush()
        if spec_labels:
            for idx, label in enumerate(spec_labels):
                clean = label.strip()
                if clean:
                    session.add(ItemSpecField(item_id=i.id, label=clean, sort_order=idx))
        session.commit()
        session.refresh(i)
        return i

    @staticmethod
    def update(
        session: Session,
        user_id: int,
        item_id: int,
        spec_labels: Optional[list[str]] = None,
        **data,
    ) -> Optional[Item]:
        i = ItemService.get(session, user_id, item_id)
        if not i:
            return None
        for k, v in data.items():
            setattr(i, k, v)
        i.updated_at = datetime.utcnow()
        if spec_labels is not None:
            # Replace spec fields wholesale. Detach from the relationship
            # collection BEFORE deleting so SQLAlchemy doesn't try to re-cascade
            # the now-deleted rows back when we save the parent.
            for f in list(i.spec_fields):
                session.delete(f)
            session.flush()
            session.expire(i, ["spec_fields"])
            for idx, label in enumerate(spec_labels):
                clean = label.strip()
                if clean:
                    session.add(ItemSpecField(item_id=i.id, label=clean, sort_order=idx))
        session.commit()
        session.refresh(i)
        return i

    @staticmethod
    def delete(session: Session, user_id: int, item_id: int) -> bool:
        i = ItemService.get(session, user_id, item_id)
        if not i:
            return False
        i.is_active = False
        i.updated_at = datetime.utcnow()
        session.add(i)
        session.commit()
        return True


# ──────────────────────────── Trades ────────────────────────────


def _next_reference(session: Session, user_id: int) -> str:
    # Max existing number + 1 — a plain count collides with existing
    # references whenever a trade has been deleted (the gap gets recounted).
    refs = session.exec(
        select(Trade.reference).where(Trade.user_id == user_id)
    ).all()
    top = 0
    for r in refs:
        try:
            top = max(top, int(str(r).rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"TRD-{top + 1:04d}"


class TradeService:
    @staticmethod
    def list(
        session: Session,
        user_id: int,
        status: Optional[TradeStatus] = None,
        party_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> list[Trade]:
        q = select(Trade).where(Trade.user_id == user_id)
        if status:
            q = q.where(Trade.status == status)
        if party_id:
            q = q.where((Trade.vendor_id == party_id) | (Trade.purchaser_id == party_id))
        if date_from:
            q = q.where(Trade.trade_date >= date_from)
        if date_to:
            q = q.where(Trade.trade_date <= date_to)
        q = q.order_by(Trade.trade_date.desc(), Trade.id.desc())
        return list(session.exec(q).all())

    @staticmethod
    def get(session: Session, user_id: int, trade_id: int) -> Optional[Trade]:
        t = session.get(Trade, trade_id)
        if t and t.user_id == user_id:
            return t
        return None

    @staticmethod
    def create(
        session: Session,
        user_id: int,
        vendor_id: int,
        purchaser_id: int,
        customer_terms_days: int,
        vendor_terms_days: int,
        trade_date: Optional[date] = None,
        notes: Optional[str] = None,
        lines: Optional[list[dict]] = None,
        **split,
    ) -> Trade:
        split_fields = {k: v for k, v in split.items() if k in (
            "cust_advance_pct", "cust_delivery_pct", "cust_credit_pct",
            "vend_advance_pct", "vend_delivery_pct", "vend_credit_pct")}
        trade = Trade(
            user_id=user_id,
            reference=_next_reference(session, user_id),
            vendor_id=vendor_id,
            purchaser_id=purchaser_id,
            trade_date=trade_date or date.today(),
            customer_terms_days=customer_terms_days,
            vendor_terms_days=vendor_terms_days,
            notes=notes,
            status=TradeStatus.OPEN,
            **split_fields,
        )
        session.add(trade)
        session.flush()
        for ln in lines or []:
            TradeService._add_line_inner(session, trade, ln)
        TradeService._recompute_totals(trade)
        session.add(trade)
        session.commit()
        session.refresh(trade)
        # Recognise the vendor advance we owe from the moment the trade opens
        # (cost-pending lines accrue nothing until their buy rate is filled in).
        TradeService._post_advance_accrual(session, trade)
        session.commit()
        session.refresh(trade)
        return trade

    @staticmethod
    def _add_line_inner(session: Session, trade: Trade, ln: dict) -> TradeLine:
        qty = Decimal(str(ln.get("quantity") or "1"))
        unit_cost = Decimal(str(ln.get("unit_cost") or "0"))
        line = TradeLine(
            trade_id=trade.id,
            item_id=ln.get("item_id"),
            item_name=ln["item_name"],
            ordered_quantity=qty,
            quantity=qty,
            unit=ln.get("unit") or "pcs",
            unit_cost=unit_cost,
            unit_price=Decimal(str(ln.get("unit_price") or "0")),
            # A blank/zero buy rate means the cost is pending — the owner will
            # fill it in later via Record Purchase (weighted-average costing).
            cost_pending=(unit_cost == 0),
            line_notes=ln.get("line_notes"),
        )
        session.add(line)
        session.flush()
        for idx, spec in enumerate(ln.get("specs") or []):
            label = (spec.get("label") or "").strip()
            value = (spec.get("value") or "").strip()
            if label or value:
                session.add(
                    TradeLineSpec(
                        line_id=line.id,
                        label=label or "Spec",
                        value=value,
                        sort_order=idx,
                    )
                )
        return line

    @staticmethod
    def add_line(session: Session, user_id: int, trade_id: int, ln: dict) -> Optional[Trade]:
        trade = TradeService.get(session, user_id, trade_id)
        if not trade or trade.status == TradeStatus.CANCELLED:
            return None
        TradeService._add_line_inner(session, trade, ln)
        session.flush()
        session.refresh(trade)
        TradeService._recompute_totals(trade)
        TradeService._refresh_status(trade, session)
        session.add(trade)
        session.commit()
        session.refresh(trade)
        TradeService._post_advance_accrual(session, trade)
        session.commit()
        session.refresh(trade)
        return trade

    @staticmethod
    def delete_line(session: Session, user_id: int, trade_id: int, line_id: int) -> Optional[Trade]:
        trade = TradeService.get(session, user_id, trade_id)
        if not trade:
            return None
        line = session.get(TradeLine, line_id)
        if not line or line.trade_id != trade.id:
            return None
        session.delete(line)
        session.flush()
        session.refresh(trade)
        TradeService._recompute_totals(trade)
        TradeService._refresh_status(trade, session)
        session.add(trade)
        session.commit()
        session.refresh(trade)
        TradeService._post_advance_accrual(session, trade)
        session.commit()
        session.refresh(trade)
        return trade

    @staticmethod
    def _post_trade_journals(session: Session, trade: Trade) -> None:
        """Post SALE + PURCHASE entries for a trade, routed through the
        Profit / Loss A/C clearing account, plus a closing entry that
        transfers net profit (or loss) directly into Capital A/C. Idempotent.

        Per-trade flow:
            SALE entry      : DR Customer A/R   / CR Profit / Loss A/C
            PURCHASE entry  : DR Profit / Loss  / CR Vendor A/P
            CLOSING entry   : DR Profit / Loss  / CR Capital A/C   (if profit)
                              DR Capital A/C    / CR Profit / Loss (if loss)

        After all three post, Profit / Loss A/C balances to zero and Capital A/C
        carries the cumulative trading profit. Traditional Sales Revenue (4101)
        and COGS (5101) accounts are no longer touched by trades.
        """
        from services.posting import PostingEngine
        from services import account_setup

        if trade.total_sale == 0 and trade.total_cost == 0:
            return

        vendor = session.get(Party, trade.vendor_id) if trade.vendor_id else None
        customer = session.get(Party, trade.purchaser_id) if trade.purchaser_id else None
        if vendor is None or customer is None:
            return
        customer_acct = account_setup.sync_party_account(session, trade.user_id, customer)
        vendor_acct = account_setup.sync_party_account(session, trade.user_id, vendor)

        pl_acct = session.exec(
            select(Account).where(Account.user_id == trade.user_id, Account.code == "3903")
        ).first()
        capital_acct = session.exec(
            select(Account).where(
                Account.user_id == trade.user_id, Account.name == "Capital A/C",
            )
        ).first()
        if not pl_acct or not capital_acct:
            # Chart of accounts hasn't been fully seeded yet — bail without posting.
            # Caller will get a clear error on the next attempt once seeding completes.
            return

        entry_date = trade.delivered_at or trade.trade_date

        def _line_summary(tl, rate: Decimal) -> str:
            """e.g. 'Flyer 50000 pcs @ 13.75' — used inside the AR/AP/P&L line descriptions."""
            return f"{tl.item_name} {float(tl.quantity):g} {tl.unit} @ {Decimal(rate):.2f}"

        def _multi_summary(rate_attr: str) -> str:
            parts = [_line_summary(tl, getattr(tl, rate_attr)) for tl in trade.lines
                     if Decimal(tl.quantity) * Decimal(getattr(tl, rate_attr)) > 0]
            return ", ".join(parts) if parts else ""

        # ── Sale entry: DR Customer A/R / CR Profit & Loss A/C ───────────
        existing_sale = session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.entry_type == JournalEntryType.SALE,
                JournalEntry.is_reversed == False,  # noqa: E712
            )
        ).first()
        if not existing_sale and Decimal(trade.total_sale) > 0:
            ar_desc = f"Sale of {customer.name} {_multi_summary('unit_price')}"
            sale_lines = [
                {"account_id": customer_acct.id, "debit": Decimal(trade.total_sale),
                 "credit": 0, "description": ar_desc,
                 "party_id": customer.id}
            ]
            for tl in trade.lines:
                tl_rev = Decimal(tl.quantity) * Decimal(tl.unit_price)
                if tl_rev <= 0:
                    continue
                sale_lines.append({
                    "account_id": pl_acct.id, "debit": 0, "credit": tl_rev,
                    "description": f"Sale of {customer.name} {_line_summary(tl, tl.unit_price)}",
                    "item_id": tl.item_id, "party_id": customer.id, "trade_line_id": tl.id,
                })
            PostingEngine.post(
                session, trade.user_id, entry_date=entry_date,
                entry_type=JournalEntryType.SALE,
                description=f"Sale to {customer.name} ({trade.reference})",
                lines=sale_lines, trade_id=trade.id,
            )

        # ── Purchase entry: DR Profit & Loss A/C / CR Vendor A/P ─────────
        existing_purchase = session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.entry_type == JournalEntryType.PURCHASE,
                JournalEntry.is_reversed == False,  # noqa: E712
            )
        ).first()
        if not existing_purchase and Decimal(trade.total_cost) > 0:
            ap_desc = f"Purchase of {customer.name} {_multi_summary('unit_cost')}"
            cogs_lines = []
            for tl in trade.lines:
                tl_cost = Decimal(tl.quantity) * Decimal(tl.unit_cost)
                if tl_cost <= 0:
                    continue
                cogs_lines.append({
                    "account_id": pl_acct.id, "debit": tl_cost, "credit": 0,
                    "description": f"Purchase of {customer.name} {_line_summary(tl, tl.unit_cost)}",
                    "item_id": tl.item_id, "party_id": vendor.id, "trade_line_id": tl.id,
                })
            cogs_lines.append({
                "account_id": vendor_acct.id, "debit": 0, "credit": Decimal(trade.total_cost),
                "description": ap_desc, "party_id": vendor.id,
            })
            PostingEngine.post(
                session, trade.user_id, entry_date=entry_date,
                entry_type=JournalEntryType.PURCHASE,
                description=f"Purchase from {vendor.name} ({trade.reference})",
                lines=cogs_lines, trade_id=trade.id,
            )

        # ── Closing entry: zero out Profit & Loss A/C into Capital A/C ───
        # Idempotent — only posts once per trade.
        existing_closing = session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.entry_type == JournalEntryType.JOURNAL,
                JournalEntry.description.like("Profit closing —%"),
                JournalEntry.is_reversed == False,  # noqa: E712
            )
        ).first()
        sale = Decimal(trade.total_sale)
        cost = Decimal(trade.total_cost)
        profit = sale - cost
        if not existing_closing and profit != 0:
            _items = TradeService.trade_items_descriptor(trade)
            _who = customer.name if customer else "trade"
            if profit > 0:
                closing_lines = [
                    {"account_id": pl_acct.id, "debit": profit, "credit": 0,
                     "description": f"Close P&L A/C to Capital — profit ({trade.reference})"},
                    {"account_id": capital_acct.id, "debit": 0, "credit": profit,
                     "description": f"Profit → Capital: {_who} · {_items} ({trade.reference})"},
                ]
            else:  # profit < 0  →  loss
                loss = -profit
                closing_lines = [
                    {"account_id": capital_acct.id, "debit": loss, "credit": 0,
                     "description": f"Loss absorbed by Capital: {_who} · {_items} ({trade.reference})"},
                    {"account_id": pl_acct.id, "debit": 0, "credit": loss,
                     "description": f"Close P&L A/C to Capital — loss ({trade.reference})"},
                ]
            PostingEngine.post(
                session, trade.user_id, entry_date=entry_date,
                entry_type=JournalEntryType.JOURNAL,
                description=f"Profit closing — {trade.reference}",
                lines=closing_lines, trade_id=trade.id,
            )

    # ── Vendor advance accrual (single-source-of-truth payables) ────────────
    # The moment a trade opens (or its cost becomes known), recognise the
    # advance we owe the vendor so the vendor A/P ledger reflects it — WITHOUT
    # touching P&L / Capital:
    #     DR Advance to Vendors (asset)  /  CR Vendor A/P     (= advance% × cost)
    # On each delivery the purchase posting CONSUMES this advance (credits the
    # asset) instead of piling a second payable on top, so the vendor never
    # double-counts. The accrual is re-derived from the trade's CURRENT
    # total_cost whenever the cost changes (Record Purchase, line edits), so a
    # cost-pending trade accrues nothing until its buy rate is filled in.
    ADVANCE_TAG = "[vendor-advance]"

    @staticmethod
    def _advance_to_vendors_acct(session: Session, user_id: int):
        acct = session.exec(select(Account).where(
            Account.user_id == user_id, Account.name == "Advance to Vendors")).first()
        if acct:
            return acct
        from services import account_setup
        try:
            return account_setup.create_account(
                session, user_id, name="Advance to Vendors", subclass_code="1900",
                is_system=True,
                description="Advances committed to vendors (payable recognised at trade open)")
        except Exception:
            return None

    @staticmethod
    def _vendor_advance_amount(trade: Trade) -> Decimal:
        """The advance we owe the vendor = normalised advance% of total_cost."""
        adv = Decimal(trade.vend_advance_pct or 0)
        dely = Decimal(trade.vend_delivery_pct or 0)
        cred = Decimal(trade.vend_credit_pct or 0)
        tot = adv + dely + cred
        if tot <= 0 or Decimal(trade.total_cost) <= 0:
            return ZERO
        return (Decimal(trade.total_cost) * adv / tot).quantize(Decimal("0.01"))

    @staticmethod
    def _advance_asset_balance(session: Session, trade: Trade, acct_id: int) -> Decimal:
        """Outstanding Advance-to-Vendors asset for this trade = accrual debits −
        consumption credits, read from the ledger."""
        rows = session.exec(
            select(JournalLine).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).where(
                JournalEntry.trade_id == trade.id,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalLine.account_id == acct_id,
            )
        ).all()
        return sum((Decimal(ln.debit) - Decimal(ln.credit) for ln in rows), ZERO)

    @staticmethod
    def _purge_advance_accrual(session: Session, trade: Trade) -> None:
        """Hard-delete the vendor-advance accrual entry (+ any reversals) so
        re-deriving the advance leaves no correction clutter."""
        entries = list(session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.description.contains(TradeService.ADVANCE_TAG),
            )
        ).all())
        if not entries:
            return
        refs = {e.reference for e in entries}
        je_ids = {e.id for e in entries}
        rev_chain = list(session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.entry_type == JournalEntryType.REVERSAL,
            )
        ).all())
        for r in rev_chain:
            if r.description and any(r.description.startswith(f"REVERSAL of {ref}:") for ref in refs):
                je_ids.add(r.id)
        for je_id in je_ids:
            session.exec(JournalLine.__table__.delete().where(
                JournalLine.journal_entry_id == je_id))
            e = session.get(JournalEntry, je_id)
            if e:
                session.delete(e)
        session.flush()

    @staticmethod
    def _post_advance_accrual(session: Session, trade: Trade) -> None:
        """(Re)post the vendor-advance accrual so it matches the trade's current
        advance amount. Idempotent: if it already matches, no-op; if the amount
        changed (or dropped to 0), purge and repost. Posts as a JOURNAL entry so
        it is never confused with a delivery PURCHASE by the event-posting
        idempotency/legacy checks."""
        from services.posting import PostingEngine
        from services import account_setup
        if trade.status == TradeStatus.CANCELLED or not trade.vendor_id:
            return
        target = TradeService._vendor_advance_amount(trade)
        existing = session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalEntry.description.contains(TradeService.ADVANCE_TAG),
            )
        ).first()
        current = sum((Decimal(ln.debit) for ln in existing.lines), ZERO) if existing else ZERO
        if existing and abs(current - target) <= Decimal("0.005"):
            return
        if existing:
            TradeService._purge_advance_accrual(session, trade)
        if target <= Decimal("0.005"):
            return
        vendor = session.get(Party, trade.vendor_id)
        adv_acct = TradeService._advance_to_vendors_acct(session, trade.user_id)
        vendor_acct = account_setup.sync_party_account(session, trade.user_id, vendor)
        if not adv_acct or not vendor_acct:
            return
        PostingEngine.post(
            session, trade.user_id, entry_date=trade.trade_date,
            entry_type=JournalEntryType.JOURNAL,
            description=f"Vendor advance accrual — {vendor.name} ({trade.reference}) {TradeService.ADVANCE_TAG}",
            lines=[
                {"account_id": adv_acct.id, "debit": target, "credit": 0,
                 "description": f"Advance committed to {vendor.name} ({trade.reference})",
                 "party_id": vendor.id},
                {"account_id": vendor_acct.id, "debit": 0, "credit": target,
                 "description": f"Advance payable to {vendor.name} ({trade.reference})",
                 "party_id": vendor.id},
            ],
            trade_id=trade.id,
        )

    @staticmethod
    def payment_schedule(trade: Trade, side: str, total=None, delivery_date=None) -> list:
        """Split a side's payment into dated stages from its advance/delivery/
        credit percentages. Returns [{stage, date, amount}] (percentages are
        normalised to 100; a zero split falls back to 100% on credit terms).

          side='customer' → total_sale, customer_terms_days
          side='vendor'   → total_cost, vendor_terms_days
        Anchors: advance → trade_date, delivery → delivered_at (or the passed
        delivery_date estimate), credit → that delivery + terms_days.
        """
        if side == "customer":
            adv = Decimal(trade.cust_advance_pct or 0)
            dely = Decimal(trade.cust_delivery_pct or 0)
            cred = Decimal(trade.cust_credit_pct or 0)
            terms = int(trade.customer_terms_days or 0)
            base = Decimal(trade.total_sale) if total is None else Decimal(str(total))
        else:
            adv = Decimal(trade.vend_advance_pct or 0)
            dely = Decimal(trade.vend_delivery_pct or 0)
            cred = Decimal(trade.vend_credit_pct or 0)
            terms = int(trade.vendor_terms_days or 0)
            base = Decimal(trade.total_cost) if total is None else Decimal(str(total))
        tot = adv + dely + cred
        if tot <= 0:
            adv, dely, cred, tot = ZERO, ZERO, Decimal("100"), Decimal("100")
        dv = delivery_date or trade.delivered_at
        stages = []
        if adv > 0:
            stages.append({"stage": "advance", "date": trade.trade_date,
                           "amount": (base * adv / tot)})
        if dely > 0 and dv:
            stages.append({"stage": "delivery", "date": dv,
                           "amount": (base * dely / tot)})
        if cred > 0:
            cd = (dv + timedelta(days=terms)) if dv else None
            stages.append({"stage": "credit", "date": cd,
                           "amount": (base * cred / tot)})
        return stages

    @staticmethod
    def terms_label(trade: Trade, side: str) -> str:
        """Human-readable terms, e.g. '30% advance · 50% on delivery · 20% in 25 days'."""
        if side == "customer":
            adv, dely, cred, terms = (trade.cust_advance_pct, trade.cust_delivery_pct,
                                      trade.cust_credit_pct, trade.customer_terms_days)
        else:
            adv, dely, cred, terms = (trade.vend_advance_pct, trade.vend_delivery_pct,
                                      trade.vend_credit_pct, trade.vendor_terms_days)
        adv, dely, cred = Decimal(adv or 0), Decimal(dely or 0), Decimal(cred or 0)
        tot = adv + dely + cred
        if tot <= 0:
            adv, dely, cred, tot = ZERO, ZERO, Decimal("100"), Decimal("100")
        adv, dely, cred = adv / tot * 100, dely / tot * 100, cred / tot * 100
        d = int(terms or 0)
        parts = []
        if adv > 0:
            parts.append(f"{float(adv):g}% advance")
        if dely > 0:
            parts.append(f"{float(dely):g}% on delivery")
        if cred > 0:
            parts.append(f"{float(cred):g}% " + (f"in {d} days" if d else "on delivery"))
        return " · ".join(parts) if parts else f"Net {d} days"

    @staticmethod
    def _spec_val(ln, label: str) -> str:
        for sp in (getattr(ln, "specs", None) or []):
            if (sp.label or "").strip().lower() == label.lower():
                return (sp.value or "").strip()
        return ""

    @staticmethod
    def items_descriptor(line_qtys) -> str:
        """Concise 'Item qty unit [Brand · Size]' summary for a set of
        (line, qty) pairs — used to make ledger descriptions self-explanatory."""
        parts = []
        for ln, q in line_qtys:
            if q is None or Decimal(str(q)) <= 0:
                continue
            brand = TradeService._spec_val(ln, "brand")
            size = TradeService._spec_val(ln, "size")
            tags = " · ".join(x for x in (brand, size) if x)
            seg = f"{ln.item_name} {float(Decimal(str(q))):g} {ln.unit}"
            if tags:
                seg += f" [{tags}]"
            parts.append(seg)
        return "; ".join(parts)

    @staticmethod
    def trade_items_descriptor(trade: Trade, event_date: Optional[date] = None) -> str:
        """Descriptor for a whole trade, or just goods delivered on `event_date`."""
        pairs = []
        for ln in trade.lines:
            if event_date is not None:
                q = sum((Decimal(r.received_qty) for r in (ln.receipts or [])
                         if r.received_on == event_date), ZERO)
            else:
                q = Decimal(ln.quantity)
            if q > 0:
                pairs.append((ln, q))
        return TradeService.items_descriptor(pairs)

    @staticmethod
    def _post_event_journals(
        session: Session,
        trade: Trade,
        event_date: date,
        line_qty_map: dict[int, Decimal],
    ) -> None:
        """Post the SALE + PURCHASE + closing journals for a single delivery
        event on `event_date`. `line_qty_map` maps trade_line.id → qty moved
        on that date.

        Each entry's description ends with ` · YYYY-MM-DD` so events are
        addressable on their own (used by `_reverse_event_journals` and by
        idempotency checks below).

        Trades that were already booked via the legacy full-trade path (no
        ` · ` marker in description) are left alone — re-posting would
        double-count.
        """
        from services.posting import PostingEngine
        from services import account_setup

        if not line_qty_map:
            return
        line_qty_map = {lid: Decimal(str(q)) for lid, q in line_qty_map.items()
                        if Decimal(str(q)) > 0}
        if not line_qty_map:
            return

        vendor = session.get(Party, trade.vendor_id) if trade.vendor_id else None
        customer = session.get(Party, trade.purchaser_id) if trade.purchaser_id else None
        if vendor is None or customer is None:
            return

        # Skip if this trade has any legacy (no-marker) un-reversed sale/purchase.
        legacy = session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.entry_type.in_([JournalEntryType.SALE, JournalEntryType.PURCHASE]),
                JournalEntry.is_reversed == False,  # noqa: E712
                ~JournalEntry.description.contains(" · "),
            )
        ).first()
        if legacy:
            return

        event_tag = f" · {event_date.isoformat()}"

        # Idempotency: this exact event already posted?
        already = session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalEntry.description.contains(event_tag),
            )
        ).first()
        if already:
            return

        customer_acct = account_setup.sync_party_account(session, trade.user_id, customer)
        vendor_acct = account_setup.sync_party_account(session, trade.user_id, vendor)
        pl_acct = session.exec(
            select(Account).where(Account.user_id == trade.user_id, Account.code == "3903")
        ).first()
        capital_acct = session.exec(
            select(Account).where(
                Account.user_id == trade.user_id, Account.name == "Capital A/C",
            )
        ).first()
        if not pl_acct or not capital_acct:
            return

        line_objs: list[tuple[TradeLine, Decimal]] = []
        for lid, qty in line_qty_map.items():
            ln = session.get(TradeLine, lid)
            if ln and ln.trade_id == trade.id:
                line_objs.append((ln, qty))
        if not line_objs:
            return

        event_sale = sum((q * Decimal(ln.unit_price) for ln, q in line_objs), ZERO)
        event_cost = sum((q * Decimal(ln.unit_cost) for ln, q in line_objs), ZERO)

        def _summary(rate_attr: str) -> str:
            parts = []
            for ln, q in line_objs:
                rate = Decimal(getattr(ln, rate_attr))
                if q * rate > 0:
                    parts.append(f"{ln.item_name} {float(q):g} {ln.unit} @ {rate:.2f}")
            return ", ".join(parts)

        # SALE entry: DR Customer A/R / CR P&L
        if event_sale > 0:
            sale_lines = [{
                "account_id": customer_acct.id, "debit": event_sale, "credit": 0,
                "description": f"Sale of {customer.name} {_summary('unit_price')}",
                "party_id": customer.id,
            }]
            for ln, q in line_objs:
                rev = q * Decimal(ln.unit_price)
                if rev <= 0:
                    continue
                sale_lines.append({
                    "account_id": pl_acct.id, "debit": 0, "credit": rev,
                    "description": f"Sale of {customer.name} {ln.item_name} {float(q):g} {ln.unit} @ {Decimal(ln.unit_price):.2f}",
                    "item_id": ln.item_id, "party_id": customer.id, "trade_line_id": ln.id,
                })
            PostingEngine.post(
                session, trade.user_id, entry_date=event_date,
                entry_type=JournalEntryType.SALE,
                description=f"Sale to {customer.name} ({trade.reference}{event_tag})",
                lines=sale_lines, trade_id=trade.id,
            )

        # PURCHASE entry: DR P&L / CR Vendor A/P — but first CONSUME any vendor
        # advance already accrued for this trade (credit the advance asset
        # instead of raising a second payable), so the vendor never double-books.
        if event_cost > 0:
            adv_acct = TradeService._advance_to_vendors_acct(session, trade.user_id)
            adv_avail = (TradeService._advance_asset_balance(session, trade, adv_acct.id)
                         if adv_acct else ZERO)
            consume = event_cost if event_cost < adv_avail else adv_avail
            if consume < 0:
                consume = ZERO
            cogs_lines = []
            for ln, q in line_objs:
                cost = q * Decimal(ln.unit_cost)
                if cost <= 0:
                    continue
                cogs_lines.append({
                    "account_id": pl_acct.id, "debit": cost, "credit": 0,
                    "description": f"Purchase of {customer.name} {ln.item_name} {float(q):g} {ln.unit} @ {Decimal(ln.unit_cost):.2f}",
                    "item_id": ln.item_id, "party_id": vendor.id, "trade_line_id": ln.id,
                })
            if consume > 0:
                cogs_lines.append({
                    "account_id": adv_acct.id, "debit": 0, "credit": consume,
                    "description": f"Advance applied — {vendor.name} ({trade.reference}{event_tag})",
                    "party_id": vendor.id,
                })
            vendor_credit = event_cost - consume
            if vendor_credit > 0:
                cogs_lines.append({
                    "account_id": vendor_acct.id, "debit": 0, "credit": vendor_credit,
                    "description": f"Purchase of {customer.name} {_summary('unit_cost')}",
                    "party_id": vendor.id,
                })
            PostingEngine.post(
                session, trade.user_id, entry_date=event_date,
                entry_type=JournalEntryType.PURCHASE,
                description=f"Purchase from {vendor.name} ({trade.reference}{event_tag})",
                lines=cogs_lines, trade_id=trade.id,
            )

        # CLOSING entry: zero this event's P&L into Capital
        event_profit = event_sale - event_cost
        if event_profit != 0:
            _items = TradeService.items_descriptor(line_objs)
            _who = customer.name if customer else "trade"
            if event_profit > 0:
                closing_lines = [
                    {"account_id": pl_acct.id, "debit": event_profit, "credit": 0,
                     "description": f"Close P&L A/C to Capital — profit ({trade.reference}{event_tag})"},
                    {"account_id": capital_acct.id, "debit": 0, "credit": event_profit,
                     "description": f"Profit → Capital: {_who} · {_items} ({trade.reference}{event_tag})"},
                ]
            else:
                loss = -event_profit
                closing_lines = [
                    {"account_id": capital_acct.id, "debit": loss, "credit": 0,
                     "description": f"Loss absorbed by Capital: {_who} · {_items} ({trade.reference}{event_tag})"},
                    {"account_id": pl_acct.id, "debit": 0, "credit": loss,
                     "description": f"Close P&L A/C to Capital — loss ({trade.reference}{event_tag})"},
                ]
            PostingEngine.post(
                session, trade.user_id, entry_date=event_date,
                entry_type=JournalEntryType.JOURNAL,
                description=f"Profit closing — {trade.reference}{event_tag}",
                lines=closing_lines, trade_id=trade.id,
            )

    @staticmethod
    def _reverse_event_journals(
        session: Session, trade: Trade, event_date: date, reason: str,
    ) -> None:
        """Reverse every un-reversed journal entry tied to this trade for a
        specific delivery event (matched by the ` · YYYY-MM-DD` marker)."""
        from services.posting import PostingEngine
        event_tag = f" · {event_date.isoformat()}"
        entries = list(session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalEntry.description.contains(event_tag),
            )
        ).all())
        for e in entries:
            PostingEngine.reverse(session, trade.user_id, e.id, reason=reason)

    @staticmethod
    def _purge_event_journals(session: Session, trade: Trade, event_date: date) -> None:
        """Hard-delete a delivery event's sale/purchase/profit-close journals
        (and any reversals already chained off them) — used when a receipt is
        edited or deleted, so corrections leave NO reversal clutter in the
        ledger. Bilty entries (tagged differently) are untouched.
        """
        event_tag = f" · {event_date.isoformat()}"
        entries = list(session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.description.contains(event_tag),
            )
        ).all())
        if not entries:
            return
        refs = {e.reference for e in entries}
        je_ids = {e.id for e in entries}
        rev_chain = list(session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.entry_type == JournalEntryType.REVERSAL,
            )
        ).all())
        for r in rev_chain:
            if r.description and any(
                r.description.startswith(f"REVERSAL of {ref}:") for ref in refs
            ):
                je_ids.add(r.id)
        for je_id in je_ids:
            session.exec(
                JournalLine.__table__.delete().where(JournalLine.journal_entry_id == je_id)
            )
            e = session.get(JournalEntry, je_id)
            if e:
                session.delete(e)
        session.flush()

    @staticmethod
    def _reverse_trade_journals(session: Session, trade: Trade, reason: str) -> None:
        """Reverse every un-reversed journal entry tied to this trade."""
        from services.posting import PostingEngine
        entries = list(session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == trade.user_id,
                JournalEntry.trade_id == trade.id,
                JournalEntry.is_reversed == False,  # noqa: E712
            )
        ).all())
        for e in entries:
            PostingEngine.reverse(session, trade.user_id, e.id, reason=reason)

    @staticmethod
    def mark_delivered(
        session: Session,
        user_id: int,
        trade_id: int,
        delivered_on: Optional[date] = None,
        final_quantities: Optional[dict[int, Decimal]] = None,
    ) -> Optional[Trade]:
        """Mark a trade as delivered, optionally overriding each line's final quantity.

        `final_quantities` maps trade_line.id → the actual delivered qty. Lines not
        in the map keep their current quantity. Totals are recomputed.
        """
        trade = TradeService.get(session, user_id, trade_id)
        if not trade or trade.status == TradeStatus.CANCELLED:
            return None
        if final_quantities:
            for ln in trade.lines:
                if ln.id in final_quantities:
                    new_qty = Decimal(str(final_quantities[ln.id]))
                    if new_qty < 0:
                        new_qty = Decimal("0")
                    ln.quantity = new_qty
                    session.add(ln)
            session.flush()
            session.refresh(trade)
            TradeService._recompute_totals(trade)
        d = delivered_on or date.today()
        trade.delivered_at = d
        trade.customer_due_date = d + timedelta(days=trade.customer_terms_days)
        trade.vendor_due_date = trade.trade_date + timedelta(days=trade.vendor_terms_days)
        if trade.status == TradeStatus.OPEN:
            trade.status = TradeStatus.DELIVERED
        TradeService._refresh_status(trade, session)
        trade.updated_at = datetime.utcnow()
        session.add(trade)
        session.commit()
        session.refresh(trade)
        # Post the residual (full qty − partial receipts) on delivered_at.
        # If partial receipts already covered the full qty, this is a no-op.
        # If no receipts were ever recorded, residual == full qty, so the
        # whole trade posts here in one event tagged `· {delivered_at}`.
        residual: dict[int, Decimal] = {}
        for ln in trade.lines:
            received = ReceiptService.line_received_total(session, ln.id)
            rem = Decimal(ln.quantity) - received
            if rem > 0:
                residual[ln.id] = rem
        # Re-reverse any prior delivered_at event so re-Mark-Complete updates
        # cleanly (e.g. final qty was edited). Only when there is a residual to
        # re-post — otherwise a receipt event on the same date would get
        # reversed and never replaced, silently dropping the sale from the books.
        TradeService._post_advance_accrual(session, trade)
        if residual:
            TradeService._purge_event_journals(session, trade, d)
            TradeService._post_event_journals(session, trade, d, residual)
        return trade

    @staticmethod
    def cancel(session: Session, user_id: int, trade_id: int, reason: Optional[str]) -> Optional[Trade]:
        trade = TradeService.get(session, user_id, trade_id)
        if not trade:
            return None
        # Reverse all journal entries tied to this trade before flipping status.
        TradeService._reverse_trade_journals(session, trade, reason=reason or "Trade cancelled")
        trade.status = TradeStatus.CANCELLED
        trade.cancellation_reason = reason
        trade.updated_at = datetime.utcnow()
        session.add(trade)
        session.commit()
        session.refresh(trade)
        return trade

    @staticmethod
    def close(session: Session, user_id: int, trade_id: int) -> Optional[Trade]:
        trade = TradeService.get(session, user_id, trade_id)
        if not trade:
            return None
        trade.status = TradeStatus.CLOSED
        trade.updated_at = datetime.utcnow()
        session.add(trade)
        session.commit()
        session.refresh(trade)
        return trade

    @staticmethod
    def delete(session: Session, user_id: int, trade_id: int) -> bool:
        """Permanently delete a trade — hard-purges its journal entries from the
        ledger so deleted trades leave no orphan rows in party ledgers. (Use
        `cancel` instead if you need the trade row + reversal entries preserved
        for audit.)
        """
        trade = TradeService.get(session, user_id, trade_id)
        if not trade:
            return False
        # Find every JE tied to this trade (originals AND any reversals chained
        # off them by description).
        originals = list(session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == user_id,
                JournalEntry.trade_id == trade.id,
            )
        ).all())
        je_ids = {e.id for e in originals}
        original_refs = {e.reference for e in originals}
        if original_refs:
            rev_chain = list(session.exec(
                select(JournalEntry).where(
                    JournalEntry.user_id == user_id,
                    JournalEntry.entry_type == JournalEntryType.REVERSAL,
                )
            ).all())
            for r in rev_chain:
                # Reversal descriptions look like: "REVERSAL of SAL-0001: reason"
                for ref in original_refs:
                    if r.description and r.description.startswith(f"REVERSAL of {ref}:"):
                        je_ids.add(r.id)
                        break
        for je_id in je_ids:
            session.exec(
                JournalLine.__table__.delete().where(JournalLine.journal_entry_id == je_id)
            )
            entry = session.get(JournalEntry, je_id)
            if entry:
                session.delete(entry)
        # Cascade deletes for trade_payments, trade_lines + their specs/receipts
        # are configured on the FKs; deleting the Trade row is enough.
        session.delete(trade)
        session.commit()
        return True

    @staticmethod
    def _recompute_totals(trade: Trade) -> None:
        cost = ZERO
        sale = ZERO
        for ln in trade.lines:
            cost += Decimal(ln.quantity) * Decimal(ln.unit_cost)
            sale += Decimal(ln.quantity) * Decimal(ln.unit_price)
        trade.total_cost = cost.quantize(Decimal("0.01"))
        trade.total_sale = sale.quantize(Decimal("0.01"))

    @staticmethod
    def _repost_cost(session: Session, trade: Trade) -> None:
        """Re-post every delivery-event journal after a line cost (or qty) change
        so the ledger's COGS/vendor-A-P reflects the current line costs. Mirrors
        the receipt/deliver posting exactly: one event per receipt date, plus the
        residual (undelivered qty) on delivered_at. The SALE side is unchanged;
        only the cost amounts move. No-op for trades with no delivery events yet
        (the cost simply stays pending until goods flow)."""
        session.refresh(trade)
        TradeService._recompute_totals(trade)
        session.add(trade)
        session.commit()
        session.refresh(trade)

        deliv = trade.delivered_at
        receipt_dates = sorted({r.received_on for ln in trade.lines
                                for r in (ln.receipts or [])})
        # Purge ALL delivery events up front, then re-derive the vendor-advance
        # accrual, so each event's advance consumption re-allocates cleanly (in
        # date order) against a fresh advance asset.
        for _d in (set(receipt_dates) | ({deliv} if deliv else set())):
            TradeService._purge_event_journals(session, trade, _d)
        TradeService._post_advance_accrual(session, trade)
        for d in receipt_dates:
            if deliv and d == deliv:
                continue  # delivered_at handled as the residual below
            totals: dict[int, Decimal] = {}
            for ln in trade.lines:
                q = sum((Decimal(r.received_qty) for r in (ln.receipts or [])
                         if r.received_on == d), ZERO)
                if q > 0:
                    totals[ln.id] = q
            TradeService._purge_event_journals(session, trade, d)
            if totals:
                TradeService._post_event_journals(session, trade, d, totals)

        if deliv:
            # everything not posted on a prior receipt date = full qty − receipts
            # strictly before delivered_at (receipts ON delivered_at fold in here)
            TradeService._purge_event_journals(session, trade, deliv)
            residual: dict[int, Decimal] = {}
            for ln in trade.lines:
                before = sum((Decimal(r.received_qty) for r in (ln.receipts or [])
                              if r.received_on < deliv), ZERO)
                rem = Decimal(ln.quantity) - before
                if rem > 0:
                    residual[ln.id] = rem
            if residual:
                TradeService._post_event_journals(session, trade, deliv, residual)

        TradeService._refresh_status(trade, session)
        trade.updated_at = datetime.utcnow()
        session.add(trade)
        session.commit()

    @staticmethod
    def _customer_credits(session: Session, trade: Trade) -> Decimal:
        """Credits on the customer's ledger that settle the invoice like cash:
        paid-by-customer costs (bilty, Record Cost) AND residual write-offs."""
        purchaser = session.get(Party, trade.purchaser_id)
        acct_id = purchaser.account_id if purchaser else None
        rows = session.exec(
            select(JournalLine).join(
                JournalEntry, JournalLine.journal_entry_id == JournalEntry.id
            ).where(
                JournalEntry.trade_id == trade.id,
                JournalEntry.is_reversed == False,  # noqa: E712
                JournalLine.credit > 0,
                or_(
                    JournalEntry.description.like("%[paid-by-customer]"),
                    JournalEntry.description.like("%[writeoff-residual]"),
                ),
            )
        ).all()
        total = ZERO
        for ln in rows:
            if ln.party_id == trade.purchaser_id or (acct_id and ln.account_id == acct_id):
                total += Decimal(ln.credit)
        return total

    @staticmethod
    def _refresh_status(trade: Trade, session: Optional[Session] = None) -> None:
        """Recompute paid totals and bump status based on customer payment progress.
        With a session, customer-paid costs (bilty) count toward settlement."""
        inbound = sum(
            (Decimal(p.amount) for p in trade.payments if p.direction == PaymentDirection.INBOUND),
            ZERO,
        )
        outbound = sum(
            (Decimal(p.amount) for p in trade.payments if p.direction == PaymentDirection.OUTBOUND),
            ZERO,
        )
        trade.paid_by_customer = Decimal(inbound).quantize(Decimal("0.01"))
        trade.paid_to_vendor = Decimal(outbound).quantize(Decimal("0.01"))

        if trade.status in (TradeStatus.CANCELLED, TradeStatus.CLOSED):
            return

        settled = trade.paid_by_customer
        if session is not None:
            settled += TradeService._customer_credits(session, trade)

        if trade.total_sale > ZERO and settled >= Decimal(trade.total_sale):
            trade.status = TradeStatus.PAID
        elif settled > ZERO:
            trade.status = TradeStatus.PARTIALLY_PAID
        elif trade.delivered_at is not None:
            trade.status = TradeStatus.DELIVERED
        else:
            trade.status = TradeStatus.OPEN

    @staticmethod
    def customer_outstanding(session: Session, trade: Trade) -> Decimal:
        """What the customer still owes: invoice − cash received − credits."""
        return (
            Decimal(trade.total_sale)
            - Decimal(trade.paid_by_customer)
            - TradeService._customer_credits(session, trade)
        ).quantize(Decimal("0.01"))

    @staticmethod
    def writeoff_residual(session: Session, user_id: int, trade_id: int,
                          threshold: Decimal = Decimal("100")):
        """Write off a tiny remaining customer balance to expense and mark paid.
        Returns (ok, message). Posts DR Other Expenses / CR customer A/R."""
        from services.posting import PostingEngine
        from services import account_setup

        trade = TradeService.get(session, user_id, trade_id)
        if not trade:
            return False, "Trade not found"
        residual = TradeService.customer_outstanding(session, trade)
        if residual <= 0:
            return False, "Nothing outstanding to write off"
        if residual > threshold:
            return False, f"Balance {residual} exceeds the write-off limit ({threshold})"

        purchaser = session.get(Party, trade.purchaser_id)
        if not purchaser:
            return False, "Purchaser not found"
        cust_acct = account_setup.sync_party_account(session, user_id, purchaser)

        # Expense account: reuse "Other Expenses" (5901); create under 5900 if
        # a business has renamed/removed it.
        exp = session.exec(
            select(Account).where(Account.user_id == user_id, Account.code == "5901")
        ).first()
        if not exp:
            exp = session.exec(
                select(Account).where(
                    Account.user_id == user_id, Account.name == "Other Expenses"
                )
            ).first()
        if not exp:
            exp = account_setup.create_account(
                session, user_id, name="Discounts & Write-offs",
                subclass_code="5900", description="Small residual write-offs",
            )

        PostingEngine.post(
            session, user_id, entry_date=date.today(),
            entry_type=JournalEntryType.EXPENSE,
            description=f"{trade.reference} residual write-off [writeoff-residual]",
            lines=[
                {"account_id": exp.id, "debit": residual, "credit": ZERO,
                 "description": f"Residual under-collection written off — {trade.reference}"},
                {"account_id": cust_acct.id, "debit": ZERO, "credit": residual,
                 "description": f"Clear residual receivable — {trade.reference}",
                 "party_id": purchaser.id},
            ],
            trade_id=trade.id,
        )
        session.flush()
        session.refresh(trade)
        TradeService._refresh_status(trade, session)
        trade.updated_at = datetime.utcnow()
        session.add(trade)
        session.commit()
        return True, "written off"


# ─────────────────────────── Purchases (per-line cost) ───────────────────────────


class PurchaseService:
    """Records purchases of goods for a trade line. A line's cost is the
    weighted-average rate across its purchases, so the same product bought at
    several rates lives on ONE line. Recomputing the cost re-posts the trade's
    ledger so COGS reflects what was actually paid."""

    @staticmethod
    def list_for_trade(session: Session, trade_id: int) -> list[TradePurchase]:
        return list(session.exec(
            select(TradePurchase).where(TradePurchase.trade_id == trade_id)
            .order_by(TradePurchase.purchased_on, TradePurchase.id)
        ).all())

    @staticmethod
    def list_for_line(session: Session, line_id: int) -> list[TradePurchase]:
        return list(session.exec(
            select(TradePurchase).where(TradePurchase.line_id == line_id)
            .order_by(TradePurchase.purchased_on, TradePurchase.id)
        ).all())

    @staticmethod
    def line_purchased_qty(session: Session, line_id: int) -> Decimal:
        rows = PurchaseService.list_for_line(session, line_id)
        return sum((Decimal(p.quantity) for p in rows), ZERO)

    @staticmethod
    def recompute_line_cost(session: Session, line: TradeLine) -> None:
        """Set a line's unit_cost to the weighted-average purchase rate. Leaves
        unit_cost untouched if the line has no purchases (legacy fixed-cost)."""
        rows = PurchaseService.list_for_line(session, line.id)
        tot_qty = sum((Decimal(p.quantity) for p in rows), ZERO)
        tot_cost = sum((Decimal(p.quantity) * Decimal(p.unit_cost) for p in rows), ZERO)
        if tot_qty > 0:
            # keep 4dp so qty × rate reconstructs the exact total purchase cost
            # (2dp rounding of the weighted average would drift the line total)
            line.unit_cost = (tot_cost / tot_qty).quantize(Decimal("0.0001"))
            session.add(line)

    @staticmethod
    def record(session: Session, user_id: int, trade_id: int, line_id: int,
               quantity: Decimal, unit_cost: Decimal, purchased_on: Optional[date] = None,
               vendor_invoice_path: Optional[str] = None,
               notes: Optional[str] = None) -> Optional[TradePurchase]:
        trade = TradeService.get(session, user_id, trade_id)
        if not trade:
            return None
        line = session.get(TradeLine, line_id)
        if not line or line.trade_id != trade_id:
            return None
        p = TradePurchase(
            trade_id=trade_id, line_id=line_id,
            quantity=Decimal(str(quantity)), unit_cost=Decimal(str(unit_cost)),
            purchased_on=purchased_on or date.today(),
            vendor_invoice_path=vendor_invoice_path, notes=notes,
        )
        session.add(p)
        session.commit()
        session.refresh(line)
        PurchaseService.recompute_line_cost(session, line)
        session.commit()
        TradeService._repost_cost(session, trade)
        session.refresh(p)
        return p

    @staticmethod
    def delete(session: Session, user_id: int, purchase_id: int) -> bool:
        p = session.get(TradePurchase, purchase_id)
        if not p:
            return False
        trade = TradeService.get(session, user_id, p.trade_id)
        line = session.get(TradeLine, p.line_id)
        session.delete(p)
        session.commit()
        if line:
            session.refresh(line)
            PurchaseService.recompute_line_cost(session, line)
            session.commit()
        if trade:
            TradeService._repost_cost(session, trade)
        return True


# ─────────────────────────── Receipts ───────────────────────────


class ReceiptService:
    """Manages partial deliveries against a trade line."""

    @staticmethod
    def line_received_total(session: Session, line_id: int) -> Decimal:
        rows = session.exec(
            select(TradeLineReceipt).where(TradeLineReceipt.line_id == line_id)
        ).all()
        return sum((Decimal(r.received_qty) for r in rows), ZERO).quantize(Decimal("0.001"))

    @staticmethod
    def list_for_line(session: Session, line_id: int) -> list[TradeLineReceipt]:
        return list(session.exec(
            select(TradeLineReceipt)
            .where(TradeLineReceipt.line_id == line_id)
            .order_by(TradeLineReceipt.received_on, TradeLineReceipt.id)
        ).all())

    @staticmethod
    def record(
        session: Session,
        user_id: int,
        trade_id: int,
        per_line: dict[int, Decimal],
        received_on: date,
        invoice_paths: dict[int, Optional[str]] | None = None,
        notes: Optional[str] = None,
    ) -> Optional[Trade]:
        """Record receipts against trade lines. `per_line` maps line_id → qty.
        `invoice_paths` maps line_id → saved file path (optional)."""
        trade = TradeService.get(session, user_id, trade_id)
        if not trade or trade.status not in (TradeStatus.OPEN, TradeStatus.DELIVERED, TradeStatus.PARTIALLY_PAID):
            return None
        invoice_paths = invoice_paths or {}
        event_map: dict[int, Decimal] = {}
        for ln in trade.lines:
            qty = per_line.get(ln.id)
            if not qty or Decimal(qty) <= 0:
                continue
            session.add(TradeLineReceipt(
                line_id=ln.id,
                received_qty=Decimal(qty),
                received_on=received_on,
                vendor_invoice_path=invoice_paths.get(ln.id),
                notes=notes,
            ))
            event_map[ln.id] = event_map.get(ln.id, ZERO) + Decimal(qty)
        session.commit()
        session.refresh(trade)
        # Post the per-event SALE + PURCHASE + closing journals.
        # Aggregate against any prior receipts on the same date so the entry
        # reflects the full day's movement (existing entry is reversed first).
        if event_map:
            same_day_existing: dict[int, Decimal] = {}
            for ln in trade.lines:
                for r in (ln.receipts or []):
                    if r.received_on == received_on:
                        same_day_existing[ln.id] = same_day_existing.get(ln.id, ZERO) + Decimal(r.received_qty)
            # same_day_existing now contains the NEW totals (including this insert).
            TradeService._purge_event_journals(session, trade, received_on)
            TradeService._post_event_journals(session, trade, received_on, same_day_existing)
            # If trade was already Mark Complete'd, the residual on delivered_at
            # may have shrunk — re-post.
            if trade.delivered_at:
                TradeService._purge_event_journals(session, trade, trade.delivered_at)
                residual: dict[int, Decimal] = {}
                for ln in trade.lines:
                    rem = Decimal(ln.quantity) - ReceiptService.line_received_total(session, ln.id)
                    if rem > 0:
                        residual[ln.id] = rem
                if residual:
                    TradeService._post_event_journals(
                        session, trade, trade.delivered_at, residual,
                    )
        return trade

    @staticmethod
    def delete(session: Session, user_id: int, receipt_id: int) -> bool:
        r = session.get(TradeLineReceipt, receipt_id)
        if not r:
            return False
        line = session.get(TradeLine, r.line_id)
        if not line:
            session.delete(r)
            session.commit()
            return True
        trade = TradeService.get(session, user_id, line.trade_id)
        if not trade:
            return False
        event_date = r.received_on
        session.delete(r)
        session.commit()
        session.refresh(trade)

        # Reverse this date's event journals, then re-post for any receipts
        # that remain on the same date.
        TradeService._purge_event_journals(session, trade, event_date)
        remaining: dict[int, Decimal] = {}
        for ln in trade.lines:
            for rcpt in (ln.receipts or []):
                if rcpt.received_on == event_date:
                    remaining[ln.id] = remaining.get(ln.id, ZERO) + Decimal(rcpt.received_qty)
        if remaining:
            TradeService._post_event_journals(session, trade, event_date, remaining)

        # If trade was Mark Complete'd, the residual on delivered_at grew —
        # refresh that event too.
        if trade.delivered_at and trade.delivered_at != event_date:
            TradeService._purge_event_journals(session, trade, trade.delivered_at)
            residual: dict[int, Decimal] = {}
            for ln in trade.lines:
                rem = Decimal(ln.quantity) - ReceiptService.line_received_total(session, ln.id)
                if rem > 0:
                    residual[ln.id] = rem
            if residual:
                TradeService._post_event_journals(
                    session, trade, trade.delivered_at, residual,
                )
        return True


# ─────────────────────────── Payments ───────────────────────────


class PaymentService:
    @staticmethod
    def record(
        session: Session,
        user_id: int,
        trade_id: int,
        cash_account_id: Optional[int] = None,
        direction: PaymentDirection = PaymentDirection.INBOUND,
        amount: Decimal = Decimal("0"),
        paid_on: Optional[date] = None,
        method: Optional[str] = None,
        reference: Optional[str] = None,
        notes: Optional[str] = None,
        gl_account_id: Optional[int] = None,
    ) -> Optional[TradePayment]:
        trade = TradeService.get(session, user_id, trade_id)
        if not trade:
            return None
        account = None
        gl_account = None
        if cash_account_id is not None:
            account = CashAccountService.get(session, user_id, cash_account_id)
            if not account:
                return None
        elif gl_account_id is not None:
            gl_account = session.get(Account, gl_account_id)
            if not gl_account or gl_account.user_id != user_id:
                return None
        else:
            return None

        # Safety net: never let a payment be booked where the source account
        # equals the trade's own counterparty. That produces a same-account
        # DR/CR journal (nets to zero, hides the money). This mirrors the
        # dropdown-exclusion in payment_new_modal so the invariant holds
        # even for direct API calls.
        counterparty_party = None
        if direction == PaymentDirection.INBOUND:
            counterparty_party = session.get(Party, trade.purchaser_id) if trade.purchaser_id else None
        else:
            counterparty_party = session.get(Party, trade.vendor_id) if trade.vendor_id else None
        if counterparty_party and gl_account and counterparty_party.account_id == gl_account.id:
            side = "customer (purchaser)" if direction == PaymentDirection.INBOUND else "vendor"
            raise ValueError(
                f"Cannot post this payment: the destination account is the "
                f"trade's own {side} — that would DR and CR the same account "
                f"and hide the payment. Pick a bank / cash / CEO / other GL "
                f"account instead."
            )
        p = TradePayment(
            user_id=user_id,
            trade_id=trade.id,
            cash_account_id=account.id if account else None,
            account_id=gl_account.id if gl_account else None,
            direction=direction,
            amount=Decimal(str(amount)),
            paid_on=paid_on or date.today(),
            method=method,
            reference=reference,
            notes=notes,
        )
        session.add(p)
        session.flush()
        session.refresh(trade)
        TradeService._refresh_status(trade, session)
        trade.updated_at = datetime.utcnow()
        session.add(trade)
        session.commit()
        session.refresh(p)

        # Post the money-side journal entry against the chosen ledger account.
        if gl_account is not None or account.kind != "capital":
            from services.posting import PostingEngine
            from services import account_setup
            cash_acct = gl_account if gl_account is not None else account_setup.sync_cash_account(session, user_id, account)
            party = session.get(
                Party,
                trade.purchaser_id if direction == PaymentDirection.INBOUND else trade.vendor_id,
            )
            if party is not None:
                party_acct = account_setup.sync_party_account(session, user_id, party)
                method_tag = f" via {p.method}" if p.method else ""
                if direction == PaymentDirection.INBOUND:
                    PostingEngine.post(
                        session, user_id, entry_date=p.paid_on,
                        entry_type=JournalEntryType.CUSTOMER_RECEIPT,
                        description=f"Receipt from {party.name} for {trade.reference}",
                        lines=[
                            {"account_id": cash_acct.id, "debit": Decimal(p.amount), "credit": 0,
                             "description": f"Cash received from {party.name} for {trade.reference}{method_tag}"},
                            {"account_id": party_acct.id, "debit": 0, "credit": Decimal(p.amount),
                             "description": f"Receipt from {party.name} for {trade.reference}{method_tag}",
                             "party_id": party.id},
                        ],
                        trade_id=trade.id, payment_id=p.id,
                    )
                else:
                    PostingEngine.post(
                        session, user_id, entry_date=p.paid_on,
                        entry_type=JournalEntryType.VENDOR_PAYMENT,
                        description=f"Payment to {party.name} for {trade.reference}",
                        lines=[
                            {"account_id": party_acct.id, "debit": Decimal(p.amount), "credit": 0,
                             "description": f"Payment to {party.name} for {trade.reference}{method_tag}",
                             "party_id": party.id},
                            {"account_id": cash_acct.id, "debit": 0, "credit": Decimal(p.amount),
                             "description": f"Cash paid to {party.name} for {trade.reference}{method_tag}"},
                        ],
                        trade_id=trade.id, payment_id=p.id,
                    )
        return p

    @staticmethod
    def delete(session: Session, user_id: int, payment_id: int) -> bool:
        p = session.get(TradePayment, payment_id)
        if not p or p.user_id != user_id:
            return False
        # Reverse any journal entry linked to this payment first.
        from services.posting import PostingEngine
        je_list = list(session.exec(
            select(JournalEntry).where(
                JournalEntry.user_id == user_id,
                JournalEntry.payment_id == p.id,
                JournalEntry.is_reversed == False,  # noqa: E712
            )
        ).all())
        for e in je_list:
            PostingEngine.reverse(session, user_id, e.id, reason="Payment deleted")
        trade = TradeService.get(session, user_id, p.trade_id)
        session.delete(p)
        session.flush()
        if trade:
            session.refresh(trade)
            TradeService._refresh_status(trade, session)
            session.add(trade)
        session.commit()
        return True


# ─────────────────────────── Quotations ─────────────────────────


def _next_quotation_reference(session: Session, user_id: int) -> str:
    n = session.exec(
        select(func.count()).select_from(Quotation).where(Quotation.user_id == user_id)
    ).one() or 0
    return f"QO-{int(n) + 1:04d}"


class QuotationService:
    @staticmethod
    def list(
        session: Session,
        user_id: int,
        status: Optional[QuotationStatus] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> list[Quotation]:
        q = select(Quotation).where(Quotation.user_id == user_id)
        if status:
            q = q.where(Quotation.status == status)
        if date_from:
            q = q.where(Quotation.quote_date >= date_from)
        if date_to:
            q = q.where(Quotation.quote_date <= date_to)
        q = q.order_by(Quotation.quote_date.desc(), Quotation.id.desc())
        return list(session.exec(q).all())

    @staticmethod
    def get(session: Session, user_id: int, quotation_id: int) -> Optional[Quotation]:
        q = session.get(Quotation, quotation_id)
        return q if (q and q.user_id == user_id) else None

    @staticmethod
    def create(
        session: Session,
        user_id: int,
        vendor_id: int,
        purchaser_id: int,
        customer_terms_days: int,
        vendor_terms_days: int,
        quote_date: Optional[date] = None,
        valid_until: Optional[date] = None,
        notes: Optional[str] = None,
        terms_text: Optional[str] = None,
        lines: Optional[list[dict]] = None,
    ) -> Quotation:
        quo = Quotation(
            user_id=user_id,
            reference=_next_quotation_reference(session, user_id),
            vendor_id=vendor_id,
            purchaser_id=purchaser_id,
            quote_date=quote_date or date.today(),
            valid_until=valid_until,
            customer_terms_days=customer_terms_days,
            vendor_terms_days=vendor_terms_days,
            notes=notes,
            terms_text=terms_text,
            status=QuotationStatus.DRAFT,
        )
        session.add(quo)
        session.flush()
        for ln in lines or []:
            QuotationService._add_line_inner(session, quo, ln)
        QuotationService._recompute_totals(quo)
        session.add(quo)
        session.commit()
        session.refresh(quo)
        return quo

    @staticmethod
    def _add_line_inner(session: Session, quo: Quotation, ln: dict) -> QuotationLine:
        qty = Decimal(str(ln.get("quantity") or "1"))
        line = QuotationLine(
            quotation_id=quo.id,
            item_id=ln.get("item_id"),
            item_name=ln["item_name"],
            quantity=qty,
            unit=ln.get("unit") or "pcs",
            unit_cost=Decimal(str(ln.get("unit_cost") or "0")),
            unit_price=Decimal(str(ln.get("unit_price") or "0")),
            line_notes=ln.get("line_notes"),
        )
        session.add(line)
        session.flush()
        for idx, sp in enumerate(ln.get("specs") or []):
            label = (sp.get("label") or "").strip()
            if not label:
                continue
            session.add(QuotationLineSpec(
                line_id=line.id, label=label,
                value=(sp.get("value") or "").strip(),
                sort_order=idx,
            ))
        return line

    @staticmethod
    def _recompute_totals(quo: Quotation) -> None:
        quo.total_cost = sum(
            (Decimal(ln.quantity) * Decimal(ln.unit_cost) for ln in quo.lines), ZERO
        ).quantize(Decimal("0.01"))
        quo.total_sale = sum(
            (Decimal(ln.quantity) * Decimal(ln.unit_price) for ln in quo.lines), ZERO
        ).quantize(Decimal("0.01"))
        quo.updated_at = datetime.utcnow()

    @staticmethod
    def mark_sent(session: Session, user_id: int, quotation_id: int) -> Optional[Quotation]:
        quo = QuotationService.get(session, user_id, quotation_id)
        if not quo:
            return None
        if quo.status == QuotationStatus.DRAFT:
            quo.status = QuotationStatus.SENT
            quo.updated_at = datetime.utcnow()
            session.add(quo); session.commit(); session.refresh(quo)
        return quo

    @staticmethod
    def mark_rejected(session: Session, user_id: int, quotation_id: int) -> Optional[Quotation]:
        quo = QuotationService.get(session, user_id, quotation_id)
        if not quo:
            return None
        if quo.status in (QuotationStatus.DRAFT, QuotationStatus.SENT):
            quo.status = QuotationStatus.REJECTED
            quo.updated_at = datetime.utcnow()
            session.add(quo); session.commit(); session.refresh(quo)
        return quo

    @staticmethod
    def accept(
        session: Session,
        user_id: int,
        quotation_id: int,
        line_overrides: Optional[dict[int, dict]] = None,
        customer_terms_days: Optional[int] = None,
        vendor_terms_days: Optional[int] = None,
    ) -> Optional[Trade]:
        """Convert an accepted quotation into a Trade. Idempotent — if already
        accepted, returns the existing Trade.

        `line_overrides` maps quotation_line.id → {qty, unit_cost, unit_price}
        so the user can record the *negotiated* final values at accept time
        while the original quotation stays as the historic record.
        """
        quo = QuotationService.get(session, user_id, quotation_id)
        if not quo:
            return None
        if quo.trade_id:
            return session.get(Trade, quo.trade_id)
        overrides = line_overrides or {}
        # Copy lines + specs into the new trade payload, applying any overrides.
        line_payload = []
        for ln in quo.lines:
            ov = overrides.get(ln.id, {})
            line_payload.append({
                "item_id": ln.item_id,
                "item_name": ln.item_name,
                "quantity": ov.get("quantity", ln.quantity),
                "unit": ln.unit,
                "unit_cost": ov.get("unit_cost", ln.unit_cost),
                "unit_price": ov.get("unit_price", ln.unit_price),
                "line_notes": ln.line_notes,
                "specs": [{"label": s.label, "value": s.value} for s in ln.specs],
            })
        trade = TradeService.create(
            session, user_id,
            vendor_id=quo.vendor_id,
            purchaser_id=quo.purchaser_id,
            customer_terms_days=customer_terms_days if customer_terms_days is not None else quo.customer_terms_days,
            vendor_terms_days=vendor_terms_days if vendor_terms_days is not None else quo.vendor_terms_days,
            trade_date=date.today(),
            notes=f"Created from quotation {quo.reference}" + (f"\n\n{quo.notes}" if quo.notes else ""),
            lines=line_payload,
        )
        quo.status = QuotationStatus.ACCEPTED
        quo.accepted_at = date.today()
        quo.trade_id = trade.id
        quo.updated_at = datetime.utcnow()
        session.add(quo); session.commit(); session.refresh(quo)
        return trade

    @staticmethod
    def delete(session: Session, user_id: int, quotation_id: int) -> bool:
        quo = QuotationService.get(session, user_id, quotation_id)
        if not quo:
            return False
        if quo.trade_id is not None:
            raise ValueError("Cannot delete a quotation that's been accepted — delete the linked trade instead.")
        session.delete(quo)
        session.commit()
        return True


# ─────────────────────────── Reports ────────────────────────────


class TradeReportService:
    @staticmethod
    def dashboard_kpis(session: Session, user_id: int, as_of: Optional[date] = None) -> dict:
        """KPIs for the trade dashboard, as of `as_of` (default today). When a
        past month-end is passed, ledger balances are taken at that date and the
        "this-month" sales/profit are scoped to that month.

        Receivable / payable totals come from the *general ledger* (the actual
        balance on every A/R and A/P account), NOT from a Party.opening_balance
        + open-trade total. The ledger already includes openings (via OPN-…),
        sale entries, payments, adjustments and everything else, so summing
        ledger balances gives the right answer. The old per-trade roll-up
        double-counted whenever an opening balance was already posted and the
        same exposure was also implicit in a delivered trade.
        """
        from sqlmodel import select as _select
        from models import Account as _Account, AccountSubClass as _AccountSubClass
        from services.ledger import balance_asof as _balance_asof

        trades = list(session.exec(select(Trade).where(Trade.user_id == user_id)).all())
        today = as_of or date.today()

        open_count = sum(
            1
            for t in trades
            if t.status in (TradeStatus.OPEN, TradeStatus.DELIVERED, TradeStatus.PARTIALLY_PAID)
        )

        # ── Receivable / payable from the ledger ─────────────────────────
        ar_sub = session.exec(_select(_AccountSubClass).where(
            _AccountSubClass.user_id == user_id, _AccountSubClass.code == "1200"
        )).first()
        ap_sub = session.exec(_select(_AccountSubClass).where(
            _AccountSubClass.user_id == user_id, _AccountSubClass.code == "2100"
        )).first()
        outstanding_receivable = ZERO
        outstanding_payable = ZERO
        if ar_sub:
            for a in session.exec(_select(_Account).where(_Account.subclass_id == ar_sub.id)).all():
                outstanding_receivable += _balance_asof(session, a.id, today)
        if ap_sub:
            # AP accounts have natural CREDIT balances; flip sign so the dashboard
            # reads as "money we owe (positive)".
            for a in session.exec(_select(_Account).where(_Account.subclass_id == ap_sub.id)).all():
                outstanding_payable -= _balance_asof(session, a.id, today)

        # ── Overdue is still per-trade (uses customer_due_date) ──────────
        # Net out customer-paid costs and write-offs (not just cash) so a trade
        # settled via bilty/adjustment doesn't linger as a phantom overdue.
        overdue_receivable = ZERO
        for t in trades:
            if t.status in (TradeStatus.CANCELLED, TradeStatus.PAID, TradeStatus.CLOSED):
                continue
            ar = TradeService.customer_outstanding(session, t)
            if ar > 0 and t.customer_due_date and t.customer_due_date < today:
                overdue_receivable += ar

        # ── This-month sales / profit ────────────────────────────────────
        # Both on the same basis: every non-cancelled trade placed this month.
        # In back-to-back trading the buy/sale rates are agreed up front, so an
        # open order's profit is effectively locked — showing it (and matching
        # sales) is more useful than waiting for delivery to book it.
        month_start = today.replace(day=1)
        this_month = [t for t in trades
                      if month_start <= t.trade_date <= today and t.status != TradeStatus.CANCELLED]
        month_sales = sum((Decimal(t.total_sale) for t in this_month), ZERO)
        month_profit = sum((Decimal(t.total_sale) - Decimal(t.total_cost)
                            for t in this_month), ZERO)

        # ── Capital A/C closing balance (equity: retained trade profit net of
        # absorbed costs). Credit-positive, so negate the DR−CR balance. ──
        capital_acct = session.exec(_select(_Account).where(
            _Account.user_id == user_id, _Account.name == "Capital A/C")).first()
        capital_balance = (-_balance_asof(session, capital_acct.id, today)) if capital_acct else ZERO

        return {
            "open_trades": open_count,
            "overdue_receivable": overdue_receivable.quantize(Decimal("0.01")),
            "outstanding_receivable": outstanding_receivable.quantize(Decimal("0.01")),
            "outstanding_payable": outstanding_payable.quantize(Decimal("0.01")),
            "month_sales": month_sales.quantize(Decimal("0.01")),
            "month_profit": month_profit.quantize(Decimal("0.01")),
            "capital_balance": capital_balance.quantize(Decimal("0.01")),
            "capital_account_id": capital_acct.id if capital_acct else None,
        }

    @staticmethod
    def sales_report(
        session: Session,
        user_id: int,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict:
        q = select(Trade).where(Trade.user_id == user_id, Trade.status != TradeStatus.CANCELLED)
        if date_from:
            q = q.where(Trade.trade_date >= date_from)
        if date_to:
            q = q.where(Trade.trade_date <= date_to)
        trades = list(session.exec(q.order_by(Trade.trade_date)).all())

        by_month: dict[str, dict] = {}
        total_sales = ZERO
        total_cost = ZERO
        for t in trades:
            key = t.trade_date.strftime("%Y-%m")
            bucket = by_month.setdefault(
                key,
                {"month": key, "sales": ZERO, "cost": ZERO, "profit": ZERO, "trades": 0},
            )
            bucket["sales"] += Decimal(t.total_sale)
            bucket["cost"] += Decimal(t.total_cost)
            bucket["profit"] += Decimal(t.total_sale) - Decimal(t.total_cost)
            bucket["trades"] += 1
            total_sales += Decimal(t.total_sale)
            total_cost += Decimal(t.total_cost)

        rows = sorted(by_month.values(), key=lambda r: r["month"])
        for r in rows:
            r["sales"] = r["sales"].quantize(Decimal("0.01"))
            r["cost"] = r["cost"].quantize(Decimal("0.01"))
            r["profit"] = r["profit"].quantize(Decimal("0.01"))
        return {
            "rows": rows,
            "total_sales": total_sales.quantize(Decimal("0.01")),
            "total_cost": total_cost.quantize(Decimal("0.01")),
            "total_profit": (total_sales - total_cost).quantize(Decimal("0.01")),
            "trade_count": len(trades),
        }

    @staticmethod
    def party_ledger(
        session: Session,
        user_id: int,
        party_id: int,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict:
        """Per-party ledger backed by journal lines on the linked Account."""
        party = PartyService.get(session, user_id, party_id)
        if not party:
            return {"party": None, "entries": [], "balance": ZERO}
        from services import account_setup
        from services.ledger import account_ledger
        acct = account_setup.sync_party_account(session, user_id, party)
        led = account_ledger(session, acct.id, from_date=date_from, to_date=date_to)
        entries = []
        for r in led["lines"]:
            entries.append({
                "date": r["date"],
                "trade_id": 0,
                "ref": r["reference"],
                "kind": r["description"],
                "debit": r["debit"],
                "credit": r["credit"],
                "balance": r["balance"],
            })
        return {"party": party, "entries": entries,
                "balance": led["closing_balance"],
                "opening_balance": led["opening_balance"]}

    @staticmethod
    def item_report(
        session: Session,
        user_id: int,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> list[dict]:
        q = select(Trade).where(Trade.user_id == user_id, Trade.status != TradeStatus.CANCELLED)
        if date_from:
            q = q.where(Trade.trade_date >= date_from)
        if date_to:
            q = q.where(Trade.trade_date <= date_to)
        trades = list(session.exec(q).all())

        buckets: dict[str, dict] = {}
        for t in trades:
            for ln in t.lines:
                key = ln.item_name.strip().lower() or "(unnamed)"
                b = buckets.setdefault(
                    key,
                    {
                        "item_name": ln.item_name,
                        "units": ZERO,
                        "revenue": ZERO,
                        "cost": ZERO,
                        "profit": ZERO,
                        "trades": 0,
                    },
                )
                qty = Decimal(ln.quantity)
                rev = qty * Decimal(ln.unit_price)
                cst = qty * Decimal(ln.unit_cost)
                b["units"] += qty
                b["revenue"] += rev
                b["cost"] += cst
                b["profit"] += rev - cst
                b["trades"] += 1

        rows = sorted(buckets.values(), key=lambda r: r["revenue"], reverse=True)
        for r in rows:
            r["revenue"] = r["revenue"].quantize(Decimal("0.01"))
            r["cost"] = r["cost"].quantize(Decimal("0.01"))
            r["profit"] = r["profit"].quantize(Decimal("0.01"))
        return rows

    @staticmethod
    def trial_balance(
        session: Session,
        user_id: int,
        period_from: Optional[date] = None,
        period_to: Optional[date] = None,
    ) -> dict:
        """Compute a trial balance.

        Assets (DR):
          - Cash/bank accounts: opening + inbound − outbound across all payments
          - Customer parties: opening + sales − receipts (only the positive net)
        Liabilities (CR):
          - Vendor parties: -opening + bills − payments (only the positive net)
        Equity (CR):
          - Capital accounts: opening balance
          - Net profit for the period (revenue − cost)
        Income (CR):
          - Total revenue (sum of total_sale within the period)
        Expense / COGS (DR):
          - Total cost (sum of total_cost within the period)

        Real-world opening balances may not balance perfectly — we surface any
        residual as a "Difference" line so it's visible rather than hidden.
        """
        parties = list(session.exec(select(Party).where(Party.user_id == user_id)).all())
        accounts = list(session.exec(select(CashAccount).where(CashAccount.user_id == user_id)).all())
        trades = list(
            session.exec(
                select(Trade).where(Trade.user_id == user_id, Trade.status != TradeStatus.CANCELLED)
            ).all()
        )

        if period_from is not None or period_to is not None:
            period_trades = [
                t
                for t in trades
                if (period_from is None or t.trade_date >= period_from)
                and (period_to is None or t.trade_date <= period_to)
            ]
        else:
            period_trades = trades

        # Cash / bank accounts (assets) and capital accounts (equity).
        assets: list[dict] = []
        equity: list[dict] = []
        for a in accounts:
            bal = CashAccountService.balance(session, user_id, a.id)
            if a.kind == "capital":
                if bal != 0:
                    equity.append({"label": a.name, "amount": bal})
            else:
                if bal != 0:
                    assets.append({"label": f"{a.name} ({a.kind})", "amount": bal})

        # Per-party net positions. For each party, compute the running balance
        # using the same logic as party_ledger to stay consistent.
        receivables: list[dict] = []
        payables: list[dict] = []
        for p in parties:
            opening = Decimal(p.opening_balance or 0)
            net = opening
            for t in trades:
                if p.id == t.purchaser_id:
                    net += Decimal(t.total_sale)
                if p.id == t.vendor_id:
                    net -= Decimal(t.total_cost)
                for pay in t.payments:
                    if p.id == t.purchaser_id and pay.direction == PaymentDirection.INBOUND:
                        net -= Decimal(pay.amount)
                    if p.id == t.vendor_id and pay.direction == PaymentDirection.OUTBOUND:
                        net += Decimal(pay.amount)
            net = net.quantize(Decimal("0.01"))
            if net > 0:
                receivables.append({"label": p.name, "amount": net})
            elif net < 0:
                payables.append({"label": p.name, "amount": -net})

        revenue = sum((Decimal(t.total_sale) for t in period_trades), ZERO).quantize(Decimal("0.01"))
        cogs = sum((Decimal(t.total_cost) for t in period_trades), ZERO).quantize(Decimal("0.01"))
        net_profit = (revenue - cogs).quantize(Decimal("0.01"))

        sum_assets = sum((Decimal(r["amount"]) for r in assets), ZERO)
        sum_receivables = sum((Decimal(r["amount"]) for r in receivables), ZERO)
        sum_payables = sum((Decimal(r["amount"]) for r in payables), ZERO)
        sum_equity = sum((Decimal(r["amount"]) for r in equity), ZERO)

        debit_total = (sum_assets + sum_receivables + cogs).quantize(Decimal("0.01"))
        credit_total = (sum_payables + sum_equity + revenue).quantize(Decimal("0.01"))
        # Period net profit closes to equity, so its credit side balances cogs - revenue.
        # We include it as an equity line for clarity; debit/credit totals already capture it
        # implicitly via revenue/cogs above.
        difference = (debit_total - credit_total).quantize(Decimal("0.01"))

        return {
            "assets": sorted(assets, key=lambda r: -r["amount"]),
            "receivables": sorted(receivables, key=lambda r: -r["amount"]),
            "payables": sorted(payables, key=lambda r: -r["amount"]),
            "equity": sorted(equity, key=lambda r: -r["amount"]),
            "net_profit": net_profit,
            "revenue": revenue,
            "cogs": cogs,
            "sum_assets": sum_assets.quantize(Decimal("0.01")),
            "sum_receivables": sum_receivables.quantize(Decimal("0.01")),
            "sum_payables": sum_payables.quantize(Decimal("0.01")),
            "sum_equity": sum_equity.quantize(Decimal("0.01")),
            "debit_total": debit_total,
            "credit_total": credit_total,
            "difference": difference,
        }

    @staticmethod
    def aging_report(session: Session, user_id: int) -> dict:
        """Per-delivery-event AR aging, sorted by earliest payment due first.

        One row per delivery event (a date the customer received goods):
          • If a trade has partial-receipt rows → one event per unique receipt date.
          • If the trade was Mark Complete'd without partial receipts → one event
            on delivered_at for the full sale.
          • If the trade has both → receipts plus a residual event on delivered_at
            for any uncovered amount.

        For each event:
          gross_invoice  = sum(qty_received_that_day × line.unit_price)
          bilty_credit   = customer-paid bilty tagged to that exact date (if any)
          cash_applied   = unallocated customer cash + customer-paid non-bilty
                           cost entries, applied FIFO across events ordered by
                           due date (oldest-due first).
          outstanding    = gross_invoice − bilty_credit − cash_applied
          due_date       = event_date + customer_terms_days
          days_overdue   = max(0, today − due_date)

        Rows with outstanding ≤ 0 are dropped. The remaining rows are sorted by
        due_date ASC so the most urgent collections sit at the top.
        """
        from datetime import timedelta
        from models import Trade, TradeLineReceipt, JournalEntry, JournalEntryType
        from services import account_setup
        today = date.today()
        BUCKET_NAMES = ("not_due", "1_30", "31_60", "61_90", "90_plus")
        buckets = {k: ZERO for k in BUCKET_NAMES}
        bucket_count = {k: 0 for k in BUCKET_NAMES}

        def _bucket_for(days_over: int) -> str:
            if days_over <= 0:    return "not_due"
            if days_over <= 30:   return "1_30"
            if days_over <= 60:   return "31_60"
            if days_over <= 90:   return "61_90"
            return "90_plus"

        trades = list(session.exec(
            select(Trade).where(
                Trade.user_id == user_id,
                Trade.status != TradeStatus.CANCELLED,
                Trade.status != TradeStatus.CLOSED,
            )
        ).all())

        rows: list[dict] = []
        for t in trades:
            customer = session.get(Party, t.purchaser_id)
            customer_name = customer.name if customer else "—"
            customer_city = customer.city if (customer and customer.city) else None
            terms = int(t.customer_terms_days or 0)

            # ── 1. Build per-event gross invoices from receipts ──────────
            event_by_date: dict[date, Decimal] = {}
            for ln in t.lines:
                price = Decimal(ln.unit_price)
                for r in (ln.receipts or []):
                    qty = Decimal(r.received_qty)
                    if qty <= 0:
                        continue
                    event_by_date[r.received_on] = event_by_date.get(r.received_on, ZERO) + qty * price

            # ── 2. If the trade was Mark Complete'd, ensure a "residual"
            #       event on delivered_at covers anything the partial receipts
            #       didn't account for (or the whole sale if no partials). ─
            if t.delivered_at and Decimal(t.total_sale) > 0:
                covered = sum(event_by_date.values(), ZERO)
                residual = Decimal(t.total_sale) - covered
                if residual > Decimal("0.005"):
                    event_by_date[t.delivered_at] = event_by_date.get(t.delivered_at, ZERO) + residual

            if not event_by_date:
                # Trade not delivered yet (no receipts, no delivered_at) → nothing
                # has been invoiced to the customer, so it's not in aging.
                continue

            # ── 3. Bilty paid by customer, tagged to a specific date ─────
            bilty_by_date: dict[date, Decimal] = {}
            bilty_entries = session.exec(
                select(JournalEntry).where(
                    JournalEntry.user_id == user_id,
                    JournalEntry.trade_id == t.id,
                    JournalEntry.entry_type == JournalEntryType.EXPENSE,
                    JournalEntry.is_reversed == False,                       # noqa: E712
                    JournalEntry.description.like("%[paid-by-customer]"),
                )
            ).all()
            for e in bilty_entries:
                # Extract [bilty-for:YYYY-MM-DD] from the description.
                desc = e.description or ""
                tag_start = desc.find("[bilty-for:")
                if tag_start < 0:
                    continue
                tag_end = desc.find("]", tag_start)
                if tag_end < 0:
                    continue
                date_str = desc[tag_start + len("[bilty-for:"):tag_end]
                try:
                    bd = date.fromisoformat(date_str)
                except ValueError:
                    continue
                # The DR (expense) line amount is the bilty value.
                amt = next((Decimal(ln.debit) for ln in e.lines if Decimal(ln.debit) > 0), ZERO)
                bilty_by_date[bd] = bilty_by_date.get(bd, ZERO) + amt

            # ── 4. Customer credits NOT tied to a specific event date —
            #       cash payments + customer-paid trade costs from Record Cost
            #       (not bilty). These get applied FIFO across events by due date.
            unallocated_credit = Decimal(t.paid_by_customer or 0)
            cost_entries = session.exec(
                select(JournalEntry).where(
                    JournalEntry.user_id == user_id,
                    JournalEntry.trade_id == t.id,
                    JournalEntry.entry_type == JournalEntryType.JOURNAL,
                    JournalEntry.is_reversed == False,                       # noqa: E712
                    JournalEntry.description.like(f"{t.reference} cost:%"),
                )
            ).all()
            purchaser_acct = account_setup.sync_party_account(session, user_id, customer) if customer else None
            purchaser_acct_id = purchaser_acct.id if purchaser_acct else None
            for e in cost_entries:
                if not (e.description or "").endswith("[paid-by-customer]"):
                    continue
                if not purchaser_acct_id:
                    continue
                cr_to_purchaser = next(
                    (Decimal(ln.credit) for ln in e.lines if ln.account_id == purchaser_acct_id),
                    ZERO,
                )
                unallocated_credit += cr_to_purchaser

            # ── 5. Build event records sorted by due date (FIFO target) ──
            events = []
            for evt_date, gross in event_by_date.items():
                due_date = evt_date + timedelta(days=terms)
                bilty_credit = bilty_by_date.get(evt_date, ZERO)
                events.append({
                    "event_date": evt_date,
                    "due_date":   due_date,
                    "gross":      gross.quantize(Decimal("0.01")),
                    "bilty_credit": bilty_credit.quantize(Decimal("0.01")),
                    "net":        (gross - bilty_credit).quantize(Decimal("0.01")),
                })
            events.sort(key=lambda x: x["due_date"])

            # FIFO-apply the unallocated credit to events by due date.
            for e in events:
                take = min(e["net"], unallocated_credit) if e["net"] > 0 else ZERO
                take = max(take, ZERO)
                e["cash_applied"] = take.quantize(Decimal("0.01"))
                e["outstanding"]  = (e["net"] - take).quantize(Decimal("0.01"))
                unallocated_credit -= take

            # ── 6. Emit a row per event with outstanding > 0 ─────────────
            for e in events:
                if e["outstanding"] <= Decimal("0.005"):
                    continue
                days_over = max(0, (today - e["due_date"]).days)
                bucket = _bucket_for(days_over)
                buckets[bucket] += e["outstanding"]
                bucket_count[bucket] += 1
                rows.append({
                    "trade_id":      t.id,
                    "trade_ref":     t.reference,
                    "customer":      customer_name,
                    "customer_city": customer_city,
                    "event_date":    e["event_date"],
                    "due_date":      e["due_date"],
                    "days_over":     days_over,
                    "gross":         e["gross"],
                    "bilty_credit":  e["bilty_credit"],
                    "cash_applied":  e["cash_applied"],
                    "outstanding":   e["outstanding"],
                    "bucket":        bucket,
                })

        # ── 7. Sort globally by due date — earliest payment due at the top ─
        rows.sort(key=lambda r: r["due_date"])

        total_outstanding = sum((r["outstanding"] for r in rows), ZERO).quantize(Decimal("0.01"))
        return {
            "rows": rows,
            "buckets": {k: v.quantize(Decimal("0.01")) for k, v in buckets.items()},
            "bucket_count": bucket_count,
            "total_outstanding": total_outstanding,
            "today": today,
        }

    @staticmethod
    def pending_receivables(session: Session, user_id: int) -> dict:
        """Pending receivable QUANTITY from each vendor, broken down per trade.

        For every active trade (status not CANCELLED / CLOSED), we list every
        line where qty ordered > qty already received via partial deliveries.
        Grouped by vendor → trade → line so the user can see, vendor by vendor,
        what's still owed to come in.
        """
        today = date.today()
        trades = session.exec(
            select(Trade).where(Trade.user_id == user_id).order_by(Trade.trade_date)
        ).all()

        # vendor_id → {vendor_name, trades: [...], pending_value, pending_qty}
        by_vendor: dict[int, dict] = {}
        total_pending_value = ZERO
        total_pending_qty = ZERO
        trade_count = 0
        line_count = 0

        for t in trades:
            if t.status in (TradeStatus.CANCELLED, TradeStatus.CLOSED):
                continue
            # A trade with delivered_at set went through Mark Complete — its
            # residual (ordered − received) was posted as delivered, so nothing
            # is still owed by the vendor. Trades still awaiting full delivery
            # (delivered_at is None) CAN have pending qty regardless of their
            # PAYMENT status: a customer payment flips status to partially_paid
            # without the vendor having delivered everything.
            if t.delivered_at is not None:
                continue
            vendor = session.get(Party, t.vendor_id) if t.vendor_id else None
            customer = session.get(Party, t.purchaser_id) if t.purchaser_id else None
            if vendor is None:
                continue

            line_rows = []
            trade_pending_value = ZERO
            trade_pending_qty = ZERO
            for ln in t.lines:
                received = sum(
                    (Decimal(r.received_qty) for r in (ln.receipts or [])), ZERO
                )
                ordered = Decimal(ln.quantity)
                pending = ordered - received
                if pending <= 0:
                    continue
                specs_parts = [
                    f"{(sp.label or '').strip()}: {(sp.value or '').strip()}"
                    for sp in (ln.specs or [])
                    if (sp.label or sp.value)
                ]
                specs_map = {
                    (sp.label or "").strip().lower(): (sp.value or "").strip()
                    for sp in (ln.specs or []) if (sp.label or "").strip()
                }
                # This statement goes to the VENDOR, so it must reflect the actual
                # rates AGREED per batch — not our internal weighted-average cost.
                # If the line was bought across several purchases at different
                # rates, break the pending out per batch (received filled FIFO in
                # purchase order). Batches with a rate of 0 (unpriced) fall back
                # to the line cost so the value is never understated.
                purchases = PurchaseService.list_for_line(session, ln.id)
                batches = []   # (batch_ordered, batch_received, batch_pending, rate)
                if purchases:
                    rem = Decimal(received)
                    covered = ZERO
                    for pu in purchases:
                        bo = Decimal(pu.quantity)
                        covered += bo
                        br = min(bo, rem) if rem > 0 else ZERO
                        rem -= br
                        bp = bo - br
                        rate = Decimal(pu.unit_cost) if Decimal(pu.unit_cost) > 0 else Decimal(ln.unit_cost)
                        if bp > 0:
                            batches.append((bo, br, bp, rate))
                    uncovered = ordered - covered
                    if uncovered > 0:
                        br = min(uncovered, rem) if rem > 0 else ZERO
                        bp = uncovered - br
                        if bp > 0:
                            batches.append((uncovered, br, bp, Decimal(ln.unit_cost)))
                else:
                    batches.append((ordered, Decimal(received), pending, Decimal(ln.unit_cost)))

                for bo, br, bp, rate in batches:
                    pending_value = (bp * rate).quantize(Decimal("0.01"))
                    line_rows.append({
                        "item_name": ln.item_name,
                        "specs": " · ".join(specs_parts),
                        "specs_map": specs_map,
                        "unit": ln.unit or "pcs",
                        "ordered_qty": bo.quantize(Decimal("0.001")),
                        "received_qty": br.quantize(Decimal("0.001")),
                        "pending_qty": bp.quantize(Decimal("0.001")),
                        "unit_cost": rate.quantize(Decimal("0.01")),
                        "pending_value": pending_value,
                    })
                    trade_pending_value += pending_value
                    trade_pending_qty += bp
                    line_count += 1

            if not line_rows:
                continue
            trade_count += 1
            total_pending_value += trade_pending_value
            total_pending_qty += trade_pending_qty

            days_open = (today - t.trade_date).days if t.trade_date else 0
            v_bucket = by_vendor.setdefault(vendor.id, {
                "vendor_id": vendor.id,
                "vendor_name": vendor.name,
                "trades": [],
                "pending_value": ZERO,
                "pending_qty": ZERO,
            })
            v_bucket["trades"].append({
                "trade_id": t.id,
                "trade_ref": t.reference,
                "trade_date": t.trade_date,
                "status": t.status.value if hasattr(t.status, "value") else t.status,
                "customer_name": customer.name if customer else "—",
                "days_open": days_open,
                "lines": line_rows,
                "pending_value": trade_pending_value.quantize(Decimal("0.01")),
                "pending_qty": trade_pending_qty.quantize(Decimal("0.001")),
            })
            v_bucket["pending_value"] += trade_pending_value
            v_bucket["pending_qty"] += trade_pending_qty

        vendors = sorted(by_vendor.values(), key=lambda v: -v["pending_value"])
        for v in vendors:
            v["pending_value"] = v["pending_value"].quantize(Decimal("0.01"))
            v["pending_qty"] = v["pending_qty"].quantize(Decimal("0.001"))
            v["trade_count"] = len(v["trades"])

        return {
            "today": today,
            "vendors": vendors,
            "total_pending_value": total_pending_value.quantize(Decimal("0.01")),
            "total_pending_qty": total_pending_qty.quantize(Decimal("0.001")),
            "trade_count": trade_count,
            "line_count": line_count,
            "vendor_count": len(vendors),
        }
