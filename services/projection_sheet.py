"""Import planned-order products from the 'fleure boxes' Numbers sheet.

Reads Table 1 on Sheet 1 via AppleScript and upserts ProjectionLine rows by
product name. Column mapping (Table 1):
    [1] Item name        -> item_name
    [3] New buy rate     -> sale_rate      (rate the customer buys at)
    [4] New purchase rate-> purchase_rate  (rate we pay the manufacturer)
    [6] Quantity         -> quantity
    [9] Dye/Block cost   -> dye_block_cost
    [10] Bilty           -> bilty
    [12] Include         -> include

Timing columns (lead/collection/pay-on-delivery) don't exist on the sheet, so
on first import they default to 15 / 30 / pay-on-delivery; re-imports preserve
whatever the user has since tuned in the app.
"""
from __future__ import annotations

import subprocess
from decimal import Decimal, InvalidOperation

from sqlmodel import Session, select

DOC_NAME = "fleure boxes"
DOC_PATH = "/Users/muhammadibrahim/Documents/fleure boxes.numbers"

_APPLESCRIPT = f'''
tell application "Numbers"
  if not (exists document "{DOC_NAME}") then
    open POSIX file "{DOC_PATH}"
  end if
  tell document "{DOC_NAME}"
    tell table "Table 1" of sheet "Sheet 1"
      set nr to count of rows
      set out to ""
      repeat with r from 2 to nr
        set nm to value of cell 1 of row r
        if nm is missing value then set nm to ""
        set nm to nm as string
        if nm is not "" then
          set qy to my cellval(r, 6)
          set pu to my cellval(r, 4)
          set sa to my cellval(r, 3)
          set dy to my cellval(r, 9)
          set bl to my cellval(r, 10)
          set inc to value of cell 12 of row r
          if inc is missing value then set inc to false
          set out to out & nm & tab & qy & tab & pu & tab & sa & tab & dy & tab & bl & tab & (inc as string) & linefeed
        end if
      end repeat
      return out
    end tell
  end tell
end tell

on cellval(r, c)
  tell application "Numbers"
    tell document "{DOC_NAME}"
      tell table "Table 1" of sheet "Sheet 1"
        set v to value of cell c of row r
      end tell
    end tell
  end tell
  if v is missing value then return "0"
  return v as string
end cellval
'''


def _dec(s: str, default: str = "0") -> Decimal:
    s = (s or "").strip()
    if not s:
        return Decimal(default)
    try:
        return Decimal(str(float(s)))  # float() copes with sci-notation "1.0E+4"
    except (InvalidOperation, ValueError):
        return Decimal(default)


def import_fleure_boxes(session: Session, user_id: int) -> int:
    from models import ProjectionLine

    proc = subprocess.run(
        ["osascript", "-e", _APPLESCRIPT],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "AppleScript failed").strip())

    existing = {
        (ln.item_name or "").strip().lower(): ln
        for ln in session.exec(
            select(ProjectionLine).where(ProjectionLine.user_id == user_id)
        ).all()
    }
    max_order = max((ln.sort_order for ln in existing.values()), default=-1)

    count = 0
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        name, qty, pur, sale, dye, bilty, inc = (p.strip() for p in parts[:7])
        if not name:
            continue
        key = name.lower()
        include = inc.lower() == "true"
        ln = existing.get(key)
        if ln is None:
            max_order += 1
            ln = ProjectionLine(user_id=user_id, item_name=name, sort_order=max_order)
            session.add(ln)
            existing[key] = ln
        ln.item_name = name
        ln.quantity = _dec(qty)
        ln.purchase_rate = _dec(pur)
        ln.sale_rate = _dec(sale)
        ln.dye_block_cost = _dec(dye)
        ln.bilty = _dec(bilty)
        ln.include = include
        count += 1

    session.commit()
    return count
