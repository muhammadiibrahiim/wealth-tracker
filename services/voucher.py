"""Voucher service — manual multi-line journal voucher (cashbook entry)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from models import Account, JournalEntry, JournalEntryType, JournalLine
from services.posting import PostingEngine, PostingError


class VoucherService:
    @staticmethod
    def list_entries(session, user_id, from_date=None, to_date=None, entry_type=None):
        q = select(JournalEntry).where(JournalEntry.user_id == user_id)
        if from_date is not None:
            q = q.where(JournalEntry.entry_date >= from_date)
        if to_date is not None:
            q = q.where(JournalEntry.entry_date <= to_date)
        if entry_type is not None:
            q = q.where(JournalEntry.entry_type == entry_type)
        q = q.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
        return list(session.exec(q).all())

    @staticmethod
    def get_with_lines(session, user_id, entry_id):
        e = session.get(JournalEntry, entry_id)
        if not e or e.user_id != user_id:
            return None
        lines = []
        for ln in e.lines:
            a = session.get(Account, ln.account_id)
            lines.append({"line": ln, "account": a})
        return {"entry": e, "lines": lines}

    @staticmethod
    def post_voucher(session, user_id, entry_date, entry_type, description, lines,
                      reference=None, proof_path=None):
        entry = PostingEngine.post(
            session, user_id, entry_date=entry_date, entry_type=entry_type,
            description=description, lines=lines, reference=reference, created_by="user",
        )
        # Standalone vouchers aren't a TradePayment (which has its own
        # proof_path) — set it directly here rather than growing the shared
        # PostingEngine.post() signature that every other caller uses too.
        if proof_path:
            entry.proof_path = proof_path
            session.add(entry)
            session.commit()
            session.refresh(entry)
        return entry
