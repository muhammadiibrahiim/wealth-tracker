"""
Routes for asset management
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from typing import Optional

from database import get_session
from services.assets import AssetService
from schemas import AssetCreate, AssetRename, AssetResponse
from config import DEFAULT_USER_ID

router = APIRouter(prefix="/wealth/assets", tags=["assets"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def list_assets(
    request: Request,
    query: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """List all assets with optional search"""
    user_id = DEFAULT_USER_ID
    assets = AssetService.list_assets(session, user_id, query)
    
    # Check if this is an HTMX request for search
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/asset_list_rows.html",
            {"request": request, "assets": assets}
        )
    
    return templates.TemplateResponse(
        "assets_list.html",
        {"request": request, "assets": assets, "query": query or ""}
    )


@router.get("/new", response_class=HTMLResponse)
async def new_asset_form(request: Request):
    """Display form for creating new asset"""
    return templates.TemplateResponse(
        "asset_new_modal.html",
        {"request": request}
    )


@router.post("", response_class=HTMLResponse)
async def create_asset(
    request: Request,
    asset_name: str = Form(...),
    session: Session = Depends(get_session)
):
    """Create a new asset"""
    user_id = DEFAULT_USER_ID
    
    try:
        asset = AssetService.create_asset(session, user_id, asset_name)
        
        # Return updated asset list
        assets = AssetService.list_assets(session, user_id)
        return templates.TemplateResponse(
            "partials/asset_list_rows.html",
            {"request": request, "assets": assets, "success_message": f"Asset '{asset.name}' created successfully"}
        )
    except ValueError as e:
        # Return error in modal
        return templates.TemplateResponse(
            "asset_new_modal.html",
            {"request": request, "error": str(e), "asset_name": asset_name},
            status_code=400
        )


@router.get("/{asset_id}/edit", response_class=HTMLResponse)
async def edit_asset_form(
    request: Request,
    asset_id: int,
    session: Session = Depends(get_session)
):
    """Display form for editing asset"""
    user_id = DEFAULT_USER_ID
    asset = AssetService.get_asset(session, user_id, asset_id)
    
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    return templates.TemplateResponse(
        "asset_edit_modal.html",
        {"request": request, "asset": asset}
    )


@router.post("/{asset_id}/rename", response_class=HTMLResponse)
async def rename_asset(
    request: Request,
    asset_id: int,
    new_name: str = Form(...),
    session: Session = Depends(get_session)
):
    """Rename an existing asset"""
    user_id = DEFAULT_USER_ID
    
    try:
        asset = AssetService.rename_asset(session, user_id, asset_id, new_name)
        
        # Return updated asset list
        assets = AssetService.list_assets(session, user_id)
        return templates.TemplateResponse(
            "partials/asset_list_rows.html",
            {"request": request, "assets": assets, "success_message": f"Asset renamed to '{asset.name}'"}
        )
    except ValueError as e:
        # Return error in modal
        asset = AssetService.get_asset(session, user_id, asset_id)
        return templates.TemplateResponse(
            "asset_edit_modal.html",
            {"request": request, "asset": asset, "error": str(e)},
            status_code=400
        )


@router.post("/{asset_id}/delete", response_class=HTMLResponse)
async def delete_asset(
    request: Request,
    asset_id: int,
    session: Session = Depends(get_session)
):
    """Delete an asset"""
    user_id = DEFAULT_USER_ID
    
    deleted = AssetService.delete_asset(session, user_id, asset_id)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Return updated asset list
    assets = AssetService.list_assets(session, user_id)
    return templates.TemplateResponse(
        "partials/asset_list_rows.html",
        {"request": request, "assets": assets, "success_message": "Asset deleted successfully"}
    )
