"""Personal Accounts module — a Money Manager mirror.

Top-level (NOT under /trade): the owner's personal book of accounts, imported
from the Money Manager XLSX cashbook. Kept separate from the business (Trade)
ledger; a cross-link is deferred.
"""
import glob
import json
import os
import tempfile
from datetime import date, datetime

from fastapi import APIRouter, Depends, Form, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from config import DEFAULT_USER_ID, CURRENCY_SYMBOL
from database import get_session
from models import MoneyAccount, MoneyAccountType, MoneyTxn
from services.money_manager import (
    import_cashbook, overview, account_ledger,
    income_expense, monthly_cashflow, all_statements, data_range,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])
templates = Jinja2Templates(directory="templates")

DOWNLOADS = os.path.expanduser("~/Downloads")
SYNC_STATE_FILE = os.path.abspath(".mm_sync_state.json")


def _load_sync_state() -> dict:
    try:
        with open(SYNC_STATE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_sync_state(state: dict) -> None:
    try:
        with open(SYNC_STATE_FILE, "w") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def _file_sig(f: dict) -> str:
    return f"{f['name']}:{int(f['mtime'].timestamp())}"


def _auto_sync(session: Session, force: bool = False) -> dict | None:
    """Import the newest detected export if it differs from the last one we
    synced. Dedup makes this safe to run on every page load — overlapping
    months add only their new rows. Returns import stats (or None if nothing
    new to do)."""
    files = _detected_files()
    if not files:
        return None
    newest = files[0]
    sig = _file_sig(newest)
    state = _load_sync_state()
    if not force and state.get("last_sig") == sig:
        return None  # already synced this exact file
    try:
        result = import_cashbook(session, DEFAULT_USER_ID, newest["path"])
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Auto-sync failed: {exc}", "file": newest["name"]}
    state["last_sig"] = sig
    state["last_file"] = newest["name"]
    state["last_synced_at"] = datetime.utcnow().isoformat(timespec="seconds")
    _save_sync_state(state)
    result["file"] = newest["name"]
    return result


def _ctx(request: Request, **extra) -> dict:
    base = {"request": request, "currency": CURRENCY_SYMBOL}
    base.update(extra)
    return base


def _parse_date(s: str):
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip())
    except (ValueError, AttributeError):
        return None


def _detected_files() -> list:
    """Money Manager exports sitting in ~/Downloads, newest first."""
    hits = glob.glob(os.path.join(DOWNLOADS, "CASHBOOK_*.xlsx"))
    hits += glob.glob(os.path.join(DOWNLOADS, "*[Cc]ashbook*.xlsx"))
    seen, out = set(), []
    for p in sorted(set(hits), key=lambda x: os.path.getmtime(x), reverse=True):
        if p not in seen:
            seen.add(p)
            out.append({"path": p, "name": os.path.basename(p),
                        "mtime": datetime.fromtimestamp(os.path.getmtime(p)),
                        "size_kb": round(os.path.getsize(p) / 1024)})
    return out


@router.get("", response_class=HTMLResponse)
async def accounts_dashboard(request: Request, session: Session = Depends(get_session)):
    sync = _auto_sync(session)  # auto-catch the newest export (dedup-safe)
    ov = overview(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "accounts_dashboard.html",
        _ctx(request, ov=ov, has_data=ov["account_count"] > 0, sync=sync),
    )


@router.post("/sync-latest")
async def accounts_sync_latest(session: Session = Depends(get_session)):
    """Force-import the newest detected export now."""
    _auto_sync(session, force=True)
    return Response(status_code=204, headers={"HX-Redirect": "/accounts"})


@router.get("/import", response_class=HTMLResponse)
async def accounts_import_form(request: Request, session: Session = Depends(get_session)):
    ov = overview(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "accounts_import.html",
        _ctx(request, detected=_detected_files(), ov=ov, result=None),
    )


@router.post("/import", response_class=HTMLResponse)
async def accounts_import_run(
    request: Request,
    session: Session = Depends(get_session),
    server_path: str = Form(default=""),
    upload: UploadFile = File(default=None),
):
    """Append-import from either a detected server file or an uploaded file."""
    path = None
    tmp = None
    try:
        if upload is not None and upload.filename:
            suffix = os.path.splitext(upload.filename)[1] or ".xlsx"
            fd, tmp = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(fd, "wb") as fh:
                fh.write(await upload.read())
            path = tmp
        elif server_path and os.path.isfile(server_path):
            path = server_path

        if not path:
            result = {"error": "No file selected. Pick a detected file or upload one."}
        else:
            result = import_cashbook(session, DEFAULT_USER_ID, path)
    except Exception as exc:  # noqa: BLE001
        result = {"error": f"Import failed: {exc}"}
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)

    ov = overview(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "accounts_import.html",
        _ctx(request, detected=_detected_files(), ov=ov, result=result),
    )


@router.get("/reports", response_class=HTMLResponse)
async def reports_index(request: Request, session: Session = Depends(get_session)):
    ov = overview(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "accounts_reports_index.html", _ctx(request, ov=ov),
    )


@router.get("/reports/trial-balance", response_class=HTMLResponse)
async def report_trial_balance(request: Request, session: Session = Depends(get_session)):
    ov = overview(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "accounts_report_trial_balance.html", _ctx(request, ov=ov),
    )


@router.get("/reports/statements", response_class=HTMLResponse)
async def report_statements(request: Request, session: Session = Depends(get_session)):
    rows = all_statements(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "accounts_report_statements.html", _ctx(request, rows=rows),
    )


@router.get("/reports/income-expense", response_class=HTMLResponse)
async def report_income_expense(request: Request, session: Session = Depends(get_session),
                                frm: str = Query(default="", alias="from"),
                                to: str = Query(default="")):
    lo, hi = data_range(session, DEFAULT_USER_ID)
    from_date = _parse_date(frm) or (lo.date() if lo else None)
    to_date = _parse_date(to) or (hi.date() if hi else None)
    rep = income_expense(session, DEFAULT_USER_ID, from_date, to_date)
    return templates.TemplateResponse(
        "accounts_report_income_expense.html",
        _ctx(request, rep=rep, from_date=from_date, to_date=to_date),
    )


@router.get("/reports/cashflow", response_class=HTMLResponse)
async def report_cashflow(request: Request, session: Session = Depends(get_session)):
    rep = monthly_cashflow(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "accounts_report_cashflow.html", _ctx(request, rep=rep),
    )


@router.get("/{account_id}", response_class=HTMLResponse)
async def account_detail(account_id: int, request: Request,
                         session: Session = Depends(get_session)):
    led = account_ledger(session, DEFAULT_USER_ID, account_id)
    if led["account"] is None:
        return Response("Account not found", status_code=404)
    known_groups = [g for g in session.exec(
        select(MoneyAccount.group_name).where(
            MoneyAccount.user_id == DEFAULT_USER_ID, MoneyAccount.group_name.is_not(None)
        ).distinct()
    ).all() if g]
    return templates.TemplateResponse(
        "account_detail.html",
        _ctx(request, led=led, types=list(MoneyAccountType), groups=sorted(known_groups)),
    )


@router.post("/{account_id}/toggle-networth", response_class=HTMLResponse)
async def account_toggle_networth(account_id: int, request: Request,
                                  session: Session = Depends(get_session)):
    """Flip whether an account counts toward net worth, then return the
    re-rendered dashboard body so the totals update live."""
    acc = session.get(MoneyAccount, account_id)
    if acc and acc.user_id == DEFAULT_USER_ID:
        acc.include_in_networth = not acc.include_in_networth
        acc.updated_at = datetime.utcnow()
        session.add(acc)
        session.commit()
    ov = overview(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "accounts_dashboard_body.html", _ctx(request, ov=ov),
    )


@router.post("/{account_id}/toggle-active", response_class=HTMLResponse)
async def account_toggle_active(account_id: int, request: Request,
                                session: Session = Depends(get_session)):
    """Inactivate (or restore) an account. Inactivating keeps all its history
    but drops it from net worth and sinks it to the Inactive section. Returns
    the re-rendered dashboard body so it moves live."""
    acc = session.get(MoneyAccount, account_id)
    if acc and acc.user_id == DEFAULT_USER_ID:
        acc.is_active = not acc.is_active
        acc.updated_at = datetime.utcnow()
        session.add(acc)
        session.commit()
    ov = overview(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "accounts_dashboard_body.html", _ctx(request, ov=ov),
    )


@router.post("/{account_id}/set-group", response_class=HTMLResponse)
async def account_set_group(account_id: int, request: Request,
                           session: Session = Depends(get_session),
                           group_name: str = Form(default="")):
    """Assign an account to a group inline from the dashboard, then re-render."""
    acc = session.get(MoneyAccount, account_id)
    if acc and acc.user_id == DEFAULT_USER_ID:
        acc.group_name = group_name.strip() or None
        acc.updated_at = datetime.utcnow()
        session.add(acc)
        session.commit()
    ov = overview(session, DEFAULT_USER_ID)
    return templates.TemplateResponse(
        "accounts_dashboard_body.html", _ctx(request, ov=ov),
    )


@router.post("/{account_id}/edit")
async def account_edit(account_id: int, session: Session = Depends(get_session),
                       name: str = Form(...), type: str = Form(...),
                       notes: str = Form(default=""), is_active: str = Form(default=""),
                       group_name: str = Form(default="")):
    acc = session.get(MoneyAccount, account_id)
    if acc and acc.user_id == DEFAULT_USER_ID:
        acc.name = name.strip() or acc.name
        try:
            acc.type = MoneyAccountType(type)
        except ValueError:
            pass
        acc.notes = notes.strip() or None
        acc.is_active = bool(is_active)
        acc.group_name = group_name.strip() or None
        acc.updated_at = datetime.utcnow()
        session.add(acc)
        session.commit()
    return Response(status_code=204, headers={"HX-Redirect": f"/accounts/{account_id}"})
