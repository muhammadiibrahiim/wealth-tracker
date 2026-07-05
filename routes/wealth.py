"""
Routes for wealth tracking and valuations
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from typing import Optional
from decimal import Decimal

from database import get_session
from services.assets import AssetService
from services.wealth import WealthService
from config import DEFAULT_USER_ID
from utils import format_currency, format_delta, get_current_year_month

router = APIRouter(prefix="/wealth", tags=["wealth"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def wealth_home(request: Request):
    """Main wealth tracker page"""
    return templates.TemplateResponse(
        "wealth_home.html",
        {"request": request}
    )


@router.get("/entries", response_class=HTMLResponse)
async def list_entries(
    request: Request,
    session: Session = Depends(get_session)
):
    """List wealth entries with month selector"""
    user_id = DEFAULT_USER_ID
    months = WealthService.list_months(session, user_id)
    
    # Get the last entered month's data
    last_month_data = None
    if months:
        last_month = months[-1]
        last_month_data = WealthService.compute_changes(session, user_id, last_month)
    
    return templates.TemplateResponse(
        "wealth_entries_list.html",
        {
            "request": request,
            "months": months,
            "last_month_data": last_month_data,
            "format_currency": format_currency,
            "format_delta": format_delta
        }
    )


@router.get("/entries/new", response_class=HTMLResponse)
async def new_entry_form(
    request: Request,
    month: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """Form to add new wealth entries for a month"""
    user_id = DEFAULT_USER_ID
    
    # Default to current month if not provided
    if not month:
        month = get_current_year_month()
    
    # Get all assets for dropdown
    assets = AssetService.list_assets(session, user_id)
    
    # Get existing valuations for this month
    snapshot = WealthService.get_month_snapshot(session, user_id, month)
    
    # Enrich with asset names
    existing_valuations = []
    for asset in assets:
        if asset.id in snapshot:
            existing_valuations.append({
                "asset_id": asset.id,
                "asset_name": asset.name,
                "value": snapshot[asset.id]
            })
    
    return templates.TemplateResponse(
        "wealth_entries_new.html",
        {
            "request": request,
            "month": month,
            "assets": assets,
            "existing_valuations": existing_valuations,
            "format_currency": format_currency
        }
    )


@router.post("/entries/add_row", response_class=HTMLResponse)
async def add_valuation_row(
    request: Request,
    month: str = Form(...),
    asset_id: int = Form(...),
    value: Decimal = Form(...),
    session: Session = Depends(get_session)
):
    """Add or update a valuation row"""
    user_id = DEFAULT_USER_ID
    
    try:
        # Upsert the valuation
        WealthService.upsert_valuation(session, user_id, asset_id, month, value)
        
        # Get updated snapshot
        snapshot = WealthService.get_month_snapshot(session, user_id, month)
        assets = AssetService.list_assets(session, user_id)
        
        # Enrich with asset names
        existing_valuations = []
        for asset in assets:
            if asset.id in snapshot:
                existing_valuations.append({
                    "asset_id": asset.id,
                    "asset_name": asset.name,
                    "value": snapshot[asset.id]
                })
        
        return templates.TemplateResponse(
            "partials/valuation_rows.html",
            {
                "request": request,
                "existing_valuations": existing_valuations,
                "format_currency": format_currency,
                "success_message": "Valuation saved"
            }
        )
    except ValueError as e:
        return HTMLResponse(content=f"<div class='text-red-600'>{str(e)}</div>", status_code=400)


@router.get("/entries/summary", response_class=HTMLResponse)
async def summary_view(
    request: Request,
    start_month: Optional[str] = Query(None),
    end_month: Optional[str] = Query(None),
    session: Session = Depends(get_session)
):
    """Summary view with range statistics"""
    user_id = DEFAULT_USER_ID
    
    # Get all available months for the selector
    all_months = WealthService.list_months(session, user_id)
    
    # Default to last 6 months if not specified
    if not start_month and all_months:
        if len(all_months) > 6:
            start_month = all_months[-6]
        else:
            start_month = all_months[0]
    
    if not end_month and all_months:
        end_month = all_months[-1]
    
    # Get range stats
    stats = WealthService.range_stats(session, user_id, start_month, end_month)
    
    return templates.TemplateResponse(
        "wealth_summary.html",
        {
            "request": request,
            "stats": stats,
            "all_months": all_months,
            "start_month": start_month or "",
            "end_month": end_month or "",
            "format_currency": format_currency,
            "format_delta": format_delta
        }
    )


@router.get("/entries/summary/csv")
async def export_summary_csv(
    request: Request,
    start_month: Optional[str] = Query(None),
    end_month: Optional[str] = Query(None),
    session: Session = Depends(get_session)
):
    """Export summary as CSV"""
    user_id = DEFAULT_USER_ID
    
    stats = WealthService.range_stats(session, user_id, start_month, end_month)
    
    # Build CSV
    csv_lines = ["Month,Networth"]
    for item in stats["networth_by_month"]:
        csv_lines.append(f"{item['month']},{item['networth']}")
    
    csv_content = "\n".join(csv_lines)
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=wealth_summary.csv"}
    )


@router.get("/entries/{year_month}", response_class=HTMLResponse)
async def month_detail(
    request: Request,
    year_month: str,
    session: Session = Depends(get_session)
):
    """Detail view for a specific month showing changes"""
    user_id = DEFAULT_USER_ID
    
    try:
        changes = WealthService.compute_changes(session, user_id, year_month)
        
        return templates.TemplateResponse(
            "wealth_month_detail.html",
            {
                "request": request,
                "changes": changes,
                "format_currency": format_currency,
                "format_delta": format_delta
            }
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/entries/{year_month}/edit/{asset_id}", response_class=HTMLResponse)
async def edit_asset_valuation(
    request: Request,
    year_month: str,
    asset_id: int,
    session: Session = Depends(get_session)
):
    """Return edit form for a specific asset valuation"""
    user_id = DEFAULT_USER_ID
    
    try:
        changes = WealthService.compute_changes(session, user_id, year_month)
        
        # Find the specific asset in the changes
        asset_data = None
        for asset in changes["per_asset"]:
            if asset["asset_id"] == asset_id:
                asset_data = asset
                break
        
        if not asset_data:
            raise HTTPException(status_code=404, detail="Asset not found in this month")
        
        return templates.TemplateResponse(
            "partials/asset_row_edit.html",
            {
                "request": request,
                "asset": asset_data,
                "year_month": year_month,
                "format_currency": format_currency,
                "format_delta": format_delta
            }
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/entries/{year_month}/update/{asset_id}", response_class=HTMLResponse)
async def update_asset_valuation(
    request: Request,
    year_month: str,
    asset_id: int,
    value: Decimal = Form(...),
    session: Session = Depends(get_session)
):
    """Update a specific asset valuation"""
    user_id = DEFAULT_USER_ID
    
    try:
        # Update the valuation
        WealthService.upsert_valuation(
            session, 
            user_id=user_id, 
            asset_id=asset_id,
            year_month=year_month,
            value=value
        )
        
        # Recompute changes
        changes = WealthService.compute_changes(session, user_id, year_month)
        
        # Find the updated asset in the changes
        asset_data = None
        for asset in changes["per_asset"]:
            if asset["asset_id"] == asset_id:
                asset_data = asset
                break
        
        if not asset_data:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        # Render the row partial
        row_html = templates.TemplateResponse(
            "partials/asset_row_display.html",
            {
                "request": request,
                "asset": asset_data,
                "year_month": year_month,
                "format_currency": format_currency,
                "format_delta": format_delta
            }
        ).body.decode()
        
        # Render OOB swaps for summary cards and allocation section
        summary_html = templates.TemplateResponse(
            "partials/summary_cards.html",
            {
                "request": request,
                "changes": changes,
                "format_currency": format_currency,
                "format_delta": format_delta
            }
        ).body.decode()
        
        allocation_html = templates.TemplateResponse(
            "partials/allocation_section.html",
            {
                "request": request,
                "changes": changes,
                "format_currency": format_currency,
                "format_delta": format_delta
            }
        ).body.decode()
        
        # Add hx-swap-oob to the OOB fragments
        summary_oob = summary_html.replace('id="summary-cards"', 'id="summary-cards" hx-swap-oob="true"', 1)
        allocation_oob = allocation_html.replace('id="allocation-section"', 'id="allocation-section" hx-swap-oob="true"', 1)
        
        return HTMLResponse(content=row_html + summary_oob + allocation_oob)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/entries/{year_month}/cancel/{asset_id}", response_class=HTMLResponse)
async def cancel_edit_valuation(
    request: Request,
    year_month: str,
    asset_id: int,
    session: Session = Depends(get_session)
):
    """Cancel editing and return to display mode"""
    user_id = DEFAULT_USER_ID
    
    try:
        changes = WealthService.compute_changes(session, user_id, year_month)
        
        # Find the asset in the changes
        asset_data = None
        for asset in changes["per_asset"]:
            if asset["asset_id"] == asset_id:
                asset_data = asset
                break
        
        if not asset_data:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        return templates.TemplateResponse(
            "partials/asset_row_display.html",
            {
                "request": request,
                "asset": asset_data,
                "year_month": year_month,
                "format_currency": format_currency,
                "format_delta": format_delta
            }
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/entries/{year_month}/delete/{asset_id}", response_class=HTMLResponse)
async def delete_asset_valuation(
    request: Request,
    year_month: str,
    asset_id: int,
    session: Session = Depends(get_session)
):
    """Delete a specific asset valuation from a month"""
    user_id = DEFAULT_USER_ID
    
    try:
        # Delete the valuation
        from sqlmodel import select
        from models import AssetValuation
        
        valuation = session.exec(
            select(AssetValuation)
            .where(AssetValuation.user_id == user_id)
            .where(AssetValuation.asset_id == asset_id)
            .where(AssetValuation.year_month == year_month)
        ).first()
        
        if not valuation:
            raise HTTPException(status_code=404, detail="Valuation not found")
        
        session.delete(valuation)
        session.commit()
        
        # Recompute changes after deletion
        changes = WealthService.compute_changes(session, user_id, year_month)
        
        # Render OOB swaps for summary cards and allocation section
        summary_html = templates.TemplateResponse(
            "partials/summary_cards.html",
            {
                "request": request,
                "changes": changes,
                "format_currency": format_currency,
                "format_delta": format_delta
            }
        ).body.decode()
        
        allocation_html = templates.TemplateResponse(
            "partials/allocation_section.html",
            {
                "request": request,
                "changes": changes,
                "format_currency": format_currency,
                "format_delta": format_delta
            }
        ).body.decode()
        
        # Add hx-swap-oob to the OOB fragments
        summary_oob = summary_html.replace('id="summary-cards"', 'id="summary-cards" hx-swap-oob="true"', 1)
        allocation_oob = allocation_html.replace('id="allocation-section"', 'id="allocation-section" hx-swap-oob="true"', 1)
        
        # Empty string removes the row, OOB swaps update the rest
        return HTMLResponse(content="" + summary_oob + allocation_oob)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


