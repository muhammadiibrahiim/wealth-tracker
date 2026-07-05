"""
Routes for Atomic Habits tracking
"""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from typing import Optional

from database import get_session
from services.habits import HabitsService
from config import DEFAULT_USER_ID

router = APIRouter(prefix="/habits", tags=["habits"])
templates = Jinja2Templates(directory="templates")


# ─── Pages ───────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse)
async def habits_dashboard(
    request: Request,
    d: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    session: Session = Depends(get_session)
):
    """Main habits dashboard — daily view"""
    user_id = DEFAULT_USER_ID
    
    # Seed defaults on first visit
    HabitsService.seed_defaults(session, user_id)
    
    if d:
        try:
            view_date = date.fromisoformat(d)
        except ValueError:
            view_date = date.today()
    else:
        view_date = date.today()
    
    daily = HabitsService.get_daily_view(session, user_id, view_date)
    prev_date = (view_date - timedelta(days=1)).isoformat()
    next_date = (view_date + timedelta(days=1)).isoformat()
    
    return templates.TemplateResponse(
        "habits_dashboard.html",
        {
            "request": request,
            "daily": daily,
            "view_date": view_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "today": date.today()
        }
    )


@router.get("/aspects", response_class=HTMLResponse)
async def aspects_page(
    request: Request,
    session: Session = Depends(get_session)
):
    """Manage life aspects page"""
    user_id = DEFAULT_USER_ID
    aspects = HabitsService.list_aspects(session, user_id)
    
    # Count habits per aspect
    aspect_data = []
    for aspect in aspects:
        habits = HabitsService.list_habits(session, user_id, aspect_id=aspect.id, active_only=False)
        aspect_data.append({
            "aspect": aspect,
            "habit_count": len(habits),
            "habits": habits
        })
    
    return templates.TemplateResponse(
        "habits_aspects.html",
        {
            "request": request,
            "aspect_data": aspect_data,
        }
    )


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(
    request: Request,
    session: Session = Depends(get_session)
):
    """Statistics and progress page"""
    user_id = DEFAULT_USER_ID
    
    habits = HabitsService.list_habits(session, user_id, active_only=True)
    
    # Get streaks for each habit
    habit_streaks = []
    for habit in habits:
        if habit.is_recurring:
            streak = HabitsService.get_streak(session, user_id, habit.id)
            habit_streaks.append({
                "habit": habit,
                **streak
            })
    
    # Weekly summary
    weekly = HabitsService.get_weekly_summary(session, user_id)
    
    # Overall score
    overall = HabitsService.get_overall_score(session, user_id)
    
    # Progress chart data
    chart_data = HabitsService.get_progress_chart_data(session, user_id, days=30)
    
    # Heatmap data
    heatmap = HabitsService.get_heatmap_data(session, user_id, months=6)
    
    # Pre-compute heatmap days for the template
    heatmap_days = []
    current = heatmap["start_date"]
    end = heatmap["end_date"]
    while current <= end:
        day_str = current.isoformat()
        heatmap_days.append({
            "date": day_str,
            "score": heatmap["data"].get(day_str, 0)
        })
        current += timedelta(days=1)
    
    return templates.TemplateResponse(
        "habits_stats.html",
        {
            "request": request,
            "habit_streaks": habit_streaks,
            "weekly": weekly,
            "overall": overall,
            "chart_data": chart_data,
            "heatmap": heatmap,
            "heatmap_days": heatmap_days
        }
    )


# ─── HTMX Endpoints ─────────────────────────────────────────


@router.post("/toggle/{habit_id}", response_class=HTMLResponse)
async def toggle_habit(
    request: Request,
    habit_id: int,
    log_date: str = Form(...),
    session: Session = Depends(get_session)
):
    """Toggle a habit completion for a date"""
    user_id = DEFAULT_USER_ID
    d = date.fromisoformat(log_date)
    
    result = HabitsService.toggle_habit(session, user_id, habit_id, d)
    habit = HabitsService.get_habit(session, user_id, habit_id)
    
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    
    # Return updated checkbox partial
    return templates.TemplateResponse(
        "partials/habit_checkbox.html",
        {
            "request": request,
            "habit": habit,
            "completed": result["completed"],
            "view_date": d
        }
    )


@router.post("/aspects/create", response_class=HTMLResponse)
async def create_aspect(
    request: Request,
    name: str = Form(...),
    icon: str = Form(default="📌"),
    color: str = Form(default="#3B82F6"),
    session: Session = Depends(get_session)
):
    """Create a new life aspect"""
    user_id = DEFAULT_USER_ID
    
    aspects = HabitsService.list_aspects(session, user_id)
    sort_order = len(aspects) + 1
    
    HabitsService.create_aspect(session, user_id, name, icon, color, sort_order)
    
    # Return updated aspect list
    aspects = HabitsService.list_aspects(session, user_id)
    aspect_data = []
    for aspect in aspects:
        habits = HabitsService.list_habits(session, user_id, aspect_id=aspect.id, active_only=False)
        aspect_data.append({
            "aspect": aspect,
            "habit_count": len(habits),
            "habits": habits
        })
    
    return templates.TemplateResponse(
        "partials/aspect_list.html",
        {
            "request": request,
            "aspect_data": aspect_data
        }
    )


@router.post("/aspects/{aspect_id}/update", response_class=HTMLResponse)
async def update_aspect(
    request: Request,
    aspect_id: int,
    name: str = Form(...),
    icon: str = Form(default="📌"),
    color: str = Form(default="#3B82F6"),
    session: Session = Depends(get_session)
):
    """Update a life aspect"""
    user_id = DEFAULT_USER_ID
    
    HabitsService.update_aspect(session, user_id, aspect_id, name=name, icon=icon, color=color)
    
    # Return updated aspect list
    aspects = HabitsService.list_aspects(session, user_id)
    aspect_data = []
    for aspect in aspects:
        habits = HabitsService.list_habits(session, user_id, aspect_id=aspect.id, active_only=False)
        aspect_data.append({
            "aspect": aspect,
            "habit_count": len(habits),
            "habits": habits
        })
    
    return templates.TemplateResponse(
        "partials/aspect_list.html",
        {
            "request": request,
            "aspect_data": aspect_data
        }
    )


@router.delete("/aspects/{aspect_id}", response_class=HTMLResponse)
async def delete_aspect(
    request: Request,
    aspect_id: int,
    session: Session = Depends(get_session)
):
    """Delete a life aspect"""
    user_id = DEFAULT_USER_ID
    
    HabitsService.delete_aspect(session, user_id, aspect_id)
    
    # Return updated aspect list
    aspects = HabitsService.list_aspects(session, user_id)
    aspect_data = []
    for aspect in aspects:
        habits = HabitsService.list_habits(session, user_id, aspect_id=aspect.id, active_only=False)
        aspect_data.append({
            "aspect": aspect,
            "habit_count": len(habits),
            "habits": habits
        })
    
    return templates.TemplateResponse(
        "partials/aspect_list.html",
        {
            "request": request,
            "aspect_data": aspect_data
        }
    )


@router.post("/habits/create", response_class=HTMLResponse)
async def create_habit(
    request: Request,
    aspect_id: int = Form(...),
    name: str = Form(...),
    description: str = Form(default=""),
    is_recurring: str = Form(default="true"),
    target_per_week: int = Form(default=7),
    session: Session = Depends(get_session)
):
    """Create a new habit"""
    user_id = DEFAULT_USER_ID
    
    HabitsService.create_habit(
        session, user_id, aspect_id, name, 
        description=description or None,
        is_recurring=is_recurring.lower() == "true",
        target_per_week=target_per_week
    )
    
    # Return updated aspect list
    aspects = HabitsService.list_aspects(session, user_id)
    aspect_data = []
    for aspect in aspects:
        habits = HabitsService.list_habits(session, user_id, aspect_id=aspect.id, active_only=False)
        aspect_data.append({
            "aspect": aspect,
            "habit_count": len(habits),
            "habits": habits
        })
    
    return templates.TemplateResponse(
        "partials/aspect_list.html",
        {
            "request": request,
            "aspect_data": aspect_data
        }
    )


@router.post("/habits/{habit_id}/update", response_class=HTMLResponse)
async def update_habit(
    request: Request,
    habit_id: int,
    name: str = Form(...),
    description: str = Form(default=""),
    is_recurring: str = Form(default="true"),
    target_per_week: int = Form(default=7),
    is_active: Optional[str] = Form(default=None),
    session: Session = Depends(get_session)
):
    """Update a habit"""
    user_id = DEFAULT_USER_ID
    
    HabitsService.update_habit(
        session, user_id, habit_id,
        name=name,
        description=description or None,
        is_recurring=is_recurring.lower() == "true",
        target_per_week=target_per_week,
        is_active=is_active is not None and is_active.lower() == "true"
    )
    
    # Return updated aspect list
    aspects = HabitsService.list_aspects(session, user_id)
    aspect_data = []
    for aspect in aspects:
        habits = HabitsService.list_habits(session, user_id, aspect_id=aspect.id, active_only=False)
        aspect_data.append({
            "aspect": aspect,
            "habit_count": len(habits),
            "habits": habits
        })
    
    return templates.TemplateResponse(
        "partials/aspect_list.html",
        {
            "request": request,
            "aspect_data": aspect_data
        }
    )


@router.delete("/habits/{habit_id}", response_class=HTMLResponse)
async def delete_habit(
    request: Request,
    habit_id: int,
    session: Session = Depends(get_session)
):
    """Delete a habit"""
    user_id = DEFAULT_USER_ID
    
    HabitsService.delete_habit(session, user_id, habit_id)
    
    # Return updated aspect list
    aspects = HabitsService.list_aspects(session, user_id)
    aspect_data = []
    for aspect in aspects:
        habits = HabitsService.list_habits(session, user_id, aspect_id=aspect.id, active_only=False)
        aspect_data.append({
            "aspect": aspect,
            "habit_count": len(habits),
            "habits": habits
        })
    
    return templates.TemplateResponse(
        "partials/aspect_list.html",
        {
            "request": request,
            "aspect_data": aspect_data
        }
    )


@router.get("/daily-content", response_class=HTMLResponse)
async def daily_content(
    request: Request,
    d: Optional[str] = Query(None),
    session: Session = Depends(get_session)
):
    """HTMX endpoint to refresh just the daily content area"""
    user_id = DEFAULT_USER_ID
    
    if d:
        try:
            view_date = date.fromisoformat(d)
        except ValueError:
            view_date = date.today()
    else:
        view_date = date.today()
    
    daily = HabitsService.get_daily_view(session, user_id, view_date)
    prev_date = (view_date - timedelta(days=1)).isoformat()
    next_date = (view_date + timedelta(days=1)).isoformat()
    
    return templates.TemplateResponse(
        "partials/daily_habits_content.html",
        {
            "request": request,
            "daily": daily,
            "view_date": view_date,
            "prev_date": prev_date,
            "next_date": next_date,
            "today": date.today()
        }
    )
