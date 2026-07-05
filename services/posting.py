"""Double-entry posting engine.

All accounting movements pass through PostingEngine.post() which guarantees
that debits = credits, each line has only debit OR credit (not both), no
negative values, and all referenced accounts exist. Posted entries are
immutable — corrections use reverse().
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select, func

from models import Account, JournalEntry, JournalEntryType, JournalLine


ZERO = Decimal("0")


class PostingError(Exception):
    """Raised when a posting attempt fails validation."""


class PostingEngine:
    """Posts and reverses balanced double-entry journal entries."""

    @staticmethod
    def _next_reference(session: Session, user_id: int, entry_type: JournalEntryType) -> str:
        prefix_map = {
            JournalEntryType.OPENING: "OPN",
            JournalEntryType.SALE: "SAL",
            JournalEntryType.PURCHASE: "PUR",
            JournalEntryType.CUSTOMER_RECEIPT: "REC",
            JournalEntryType.VENDOR_PAYMENT: "PAY",
            JournalEntryType.EXPENSE: "EXP",
            JournalEntryType.CAPITAL_INJECTION: "CIN",
            JournalEntryType.CAPITAL_WITHDRAWAL: "CWD",
            JournalEntryType.CONTRA: "CON",
            JournalEntryType.JOURNAL: "JV",
            JournalEntryType.REVERSAL: "REV",
        }
        prefix = prefix_map.get(entry_type, "JE")
        # Use the highest existing numeric suffix + 1 rather than COUNT(*) + 1.
        # COUNT-based numbering collides when historical entries were deleted
        # (e.g. cleanup of reversed pairs) leaving non-contiguous numbers — the
        # next COUNT could land on a still-existing reference and the unique
        # index would reject the insert.
        refs = session.exec(
            select(JournalEntry.reference).where(
                JournalEntry.user_id == user_id,
                JournalEntry.reference.like(f"{prefix}-%"),
            )
        ).all()
        max_n = 0
        for r in refs:
            tail = (r or "").rsplit("-", 1)[-1]
            try:
                max_n = max(max_n, int(tail))
            except ValueError:
                continue
        return f"{prefix}-{max_n + 1:04d}"

    @staticmethod
    def post(
        session: Session,
        user_id: int,
        entry_date: date,
        entry_type: JournalEntryType,
        description: str,
        lines: list[dict],
        trade_id: Optional[int] = None,
        payment_id: Optional[int] = None,
        reference: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> JournalEntry:
        """Post a balanced journal entry."""
        if not lines:
            raise PostingError("Journal entry has no lines")

        norm: list[dict] = []
        for ln in lines:
            dr = Decimal(str(ln.get("debit") or 0))
            cr = Decimal(str(ln.get("credit") or 0))
            if dr < 0 or cr < 0:
                raise PostingError("Negative debit or credit not allowed")
            if dr > 0 and cr > 0:
                raise PostingError("Line cannot have both debit and credit")
            if dr == 0 and cr == 0:
                continue
            norm.append({
                "account_id": int(ln["account_id"]),
                "debit": dr.quantize(Decimal("0.01")),
                "credit": cr.quantize(Decimal("0.01")),
                "description": ln.get("description"),
                "item_id": ln.get("item_id"),
                "party_id": ln.get("party_id"),
                "trade_line_id": ln.get("trade_line_id"),
            })
        if not norm:
            raise PostingError("Journal entry has no non-zero lines")

        total_dr = sum((l["debit"] for l in norm), ZERO)
        total_cr = sum((l["credit"] for l in norm), ZERO)
        if total_dr != total_cr:
            raise PostingError(f"Entry not balanced: debits={total_dr}, credits={total_cr}")
        if total_dr == ZERO:
            raise PostingError("Journal entry has zero value")

        ids = list({l["account_id"] for l in norm})
        accounts = session.exec(
            select(Account).where(Account.id.in_(ids), Account.user_id == user_id)
        ).all()
        if len(accounts) != len(ids):
            present = {a.id for a in accounts}
            missing = [i for i in ids if i not in present]
            raise PostingError(f"Unknown accounts: {missing}")

        ref = reference or PostingEngine._next_reference(session, user_id, entry_type)

        entry = JournalEntry(
            user_id=user_id,
            reference=ref,
            entry_date=entry_date,
            entry_type=entry_type,
            description=description,
            trade_id=trade_id,
            payment_id=payment_id,
            created_by=created_by,
        )
        session.add(entry)
        session.flush()

        for idx, ln in enumerate(norm):
            session.add(JournalLine(
                journal_entry_id=entry.id,
                account_id=ln["account_id"],
                debit=ln["debit"],
                credit=ln["credit"],
                description=ln["description"],
                sort_order=idx,
                item_id=ln.get("item_id"),
                party_id=ln.get("party_id"),
                trade_line_id=ln.get("trade_line_id"),
            ))
        session.commit()
        session.refresh(entry)
        return entry

    @staticmethod
    def reverse(
        session: Session,
        user_id: int,
        entry_id: int,
        reason: str,
        reversal_date: Optional[date] = None,
    ) -> Optional[JournalEntry]:
        """Create a reversing entry (swapped debit/credit) for entry_id."""
        original = session.get(JournalEntry, entry_id)
        if not original or original.user_id != user_id:
            return None
        if original.is_reversed:
            raise PostingError(f"Entry {original.reference} is already reversed")

        rev_lines = [
            {
                "account_id": ln.account_id,
                "debit": ln.credit,
                "credit": ln.debit,
                "description": ln.description,
                "item_id": ln.item_id,
                "party_id": ln.party_id,
                "trade_line_id": ln.trade_line_id,
            }
            for ln in original.lines
        ]
        rev = PostingEngine.post(
            session, user_id,
            entry_date=reversal_date or date.today(),
            entry_type=JournalEntryType.REVERSAL,
            description=f"REVERSAL of {original.reference}: {reason}",
            lines=rev_lines,
            trade_id=original.trade_id,
            payment_id=original.payment_id,
            reference=None,
            created_by="system",
        )
        rev.reversal_of_id = original.id
        original.is_reversed = True
        original.reversed_at = datetime.utcnow()
        session.add(original)
        session.add(rev)
        session.commit()
        session.refresh(rev)
        return rev
