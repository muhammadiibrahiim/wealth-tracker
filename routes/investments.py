"""
Investment routes for Phase 2 feature
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session
from typing import Optional, Dict, List
from decimal import Decimal
from datetime import date, datetime

from database import get_session
from models import Investment, InvestmentCadence, InvestmentMetric, InvestmentType, LeverageRepaymentType, LeverageRepayment
from services.investments import InvestmentService
from services.investment_metrics import InvestmentMetricsService
from utils import get_current_user_id


async def get_custom_repayments(request: Request) -> Dict[str, Dict[str, str]]:
    """Parse custom repayment entries from form data"""
    form_data = await request.form()
    repayment_entries = {}
    
    # Group amounts and dates by index
    for key, value in form_data.items():
        if key.startswith("custom_repayment_amount_"):
            index = key.split("_")[-1]
            if index not in repayment_entries:
                repayment_entries[index] = {}
            repayment_entries[index]["amount"] = value
        elif key.startswith("custom_repayment_date_"):
            index = key.split("_")[-1]
            if index not in repayment_entries:
                repayment_entries[index] = {}
            repayment_entries[index]["date"] = value
    
    return repayment_entries

router = APIRouter(prefix="/investments", tags=["investments"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def list_investments(
    request: Request,
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id)
):
    """Display list of investments"""
    investments = InvestmentService.list_investments(session, user_id)
    return templates.TemplateResponse("investment_list.html", {
        "request": request,
        "investments": investments
    })


@router.get("/select-type", response_class=HTMLResponse)
def select_investment_type(
    request: Request,
    user_id: int = Depends(get_current_user_id)
):
    """Show modal for selecting investment type"""
    return templates.TemplateResponse("investment_type_select_modal.html", {
        "request": request
    })


@router.get("/new", response_class=HTMLResponse)
def new_investment_modal(
    request: Request,
    type: str = "asset",
    user_id: int = Depends(get_current_user_id)
):
    """Show modal for creating new investment"""
    from datetime import date
    return templates.TemplateResponse("investment_new_modal.html", {
        "request": request,
        "investment_type": type,
        "cadence_options": [c.value for c in InvestmentCadence],
        "today": date.today().isoformat()
    })


@router.post("/", response_class=HTMLResponse)
async def create_investment(
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
    custom_repayments_form: Dict[str, Dict[str, str]] = Depends(get_custom_repayments),
    investment_start_date: str = Form(...),
    name: str = Form(...),
    investment_type: str = Form("asset"),
    total_investment_value: Decimal = Form(...),
    installments: bool = Form(False),
    installment_value: Optional[Decimal] = Form(None),
    installment_months: Optional[int] = Form(None),
    is_leveraged: bool = Form(False),
    leverage_amount: Decimal = Form(Decimal("0")),
    leverage_repayment_type: str = Form("equal_installments"),
    leverage_repayment_months: Optional[int] = Form(None),
    has_revenue: bool = Form(False),
    revenue_amount: Decimal = Form(Decimal("0")),
    revenue_installment_months: Optional[int] = Form(None),
    asset_appreciates: bool = Form(False),
    appreciation_rate_percent: Decimal = Form(Decimal("0.000")),
    appreciation_cadence: str = Form(InvestmentCadence.YEARLY.value),
    gain_in_income_value: Decimal = Form(Decimal("0")),
    cadence: str = Form(InvestmentCadence.MONTHLY.value),
    income_increases: bool = Form(False),
    income_increase_rate_percent: Decimal = Form(Decimal("0.000")),
    income_increase_cadence: str = Form(InvestmentCadence.YEARLY.value),
    one_off_inflow_value: Decimal = Form(Decimal("0")),
    salvage_value: Decimal = Form(Decimal("0")),
    discount_rate_annual_percent: Decimal = Form(Decimal("15.000")),
    reinvestment_rate_annual_percent: Decimal = Form(Decimal("15.000")),
    analysis_horizon_months: int = Form(60),
    break_even_fixed_costs: Decimal = Form(Decimal("0")),
    break_even_price_per_unit: Decimal = Form(Decimal("0")),
    break_even_variable_cost_per_unit: Decimal = Form(Decimal("0")),
    notes: Optional[str] = Form(None)
):
    """Create new investment and compute metrics"""
    # Validate discount rate range
    if not (Decimal("0") <= discount_rate_annual_percent <= Decimal("200")):
        raise HTTPException(status_code=400, detail="Discount rate must be between 0 and 200")
    
    # Validate reinvestment rate range
    if not (Decimal("0") <= reinvestment_rate_annual_percent <= Decimal("200")):
        raise HTTPException(status_code=400, detail="Reinvestment rate must be between 0 and 200")
    
    # Calculate percentage from absolute value
    if total_investment_value > 0 and gain_in_income_value > 0:
        gain_in_income_percent = (gain_in_income_value / total_investment_value) * Decimal("100")
    else:
        gain_in_income_percent = Decimal("0")
    
    # Parse investment start date
    try:
        start_date = datetime.strptime(investment_start_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid investment start date format")
    
    # Handle custom leverage repayments
    custom_repayments_data = []
    if is_leveraged and leverage_amount > 0 and leverage_repayment_type == "custom_schedule":
        # Validate and prepare custom repayments from parsed form data
        total_custom_repayments = Decimal("0")
        for entry in custom_repayments_form.values():
            amount_str = entry.get("amount", "")
            date_str = entry.get("date", "")
            
            if amount_str and date_str:
                try:
                    amount = Decimal(amount_str)
                    if amount > 0:
                        repayment_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        
                        # Calculate month number from start date
                        days_diff = (repayment_date - start_date).days
                        repayment_month = int(days_diff / 30) + 1  # Convert days to months (1-indexed)
                        
                        custom_repayments_data.append({
                            "amount": amount,
                            "repayment_date": repayment_date,
                            "repayment_month": repayment_month
                        })
                        total_custom_repayments += amount
                except (ValueError, Decimal.InvalidOperation):
                    continue
        
        # Validate total equals leverage amount
        if abs(total_custom_repayments - leverage_amount) > Decimal("0.01"):
            raise HTTPException(
                status_code=400, 
                detail=f"Total custom repayments (Rs {total_custom_repayments}) must equal leverage amount (Rs {leverage_amount})"
            )
    
    # Calculate leverage monthly repayment (for equal installments only)
    leverage_monthly_repayment = Decimal("0")
    if is_leveraged and leverage_amount > 0 and leverage_repayment_type == "equal_installments" and leverage_repayment_months and leverage_repayment_months > 0:
        leverage_monthly_repayment = leverage_amount / Decimal(leverage_repayment_months)
    
    # For business type, auto-calculate analysis horizon based on payment periods
    inv_type = InvestmentType(investment_type)
    if inv_type == InvestmentType.BUSINESS:
        max_period = 1
        if leverage_repayment_type == "equal_installments" and leverage_repayment_months:
            max_period = max(max_period, leverage_repayment_months)
        elif leverage_repayment_type == "custom_schedule" and custom_repayments_data:
            # For custom schedule, use the latest repayment month
            max_repayment_month = max(r["repayment_month"] for r in custom_repayments_data)
            max_period = max(max_period, max_repayment_month)
        if revenue_installment_months:
            max_period = max(max_period, revenue_installment_months)
        analysis_horizon_months = max_period
    
    # Create investment
    investment = InvestmentService.create_investment(
        session=session,
        user_id=user_id,
        investment_start_date=start_date,
        name=name,
        investment_type=inv_type,
        total_investment_value=total_investment_value,
        installments=installments,
        installment_value=installment_value,
        installment_months=installment_months,
        is_leveraged=is_leveraged,
        leverage_amount=leverage_amount,
        leverage_repayment_type=LeverageRepaymentType(leverage_repayment_type),
        leverage_repayment_months=leverage_repayment_months,
        leverage_monthly_repayment=leverage_monthly_repayment,
        has_revenue=has_revenue,
        revenue_amount=revenue_amount,
        revenue_installment_months=revenue_installment_months,
        asset_appreciates=asset_appreciates,
        appreciation_rate_percent=appreciation_rate_percent,
        appreciation_cadence=InvestmentCadence(appreciation_cadence),
        gain_in_income_value=gain_in_income_value,
        gain_in_income_percent=gain_in_income_percent,
        cadence=InvestmentCadence(cadence),
        income_increases=income_increases,
        income_increase_rate_percent=income_increase_rate_percent,
        income_increase_cadence=InvestmentCadence(income_increase_cadence),
        one_off_inflow_value=one_off_inflow_value,
        salvage_value=salvage_value,
        discount_rate_annual_percent=discount_rate_annual_percent,
        reinvestment_rate_annual_percent=reinvestment_rate_annual_percent,
        analysis_horizon_months=analysis_horizon_months,
        break_even_fixed_costs=break_even_fixed_costs,
        break_even_price_per_unit=break_even_price_per_unit,
        break_even_variable_cost_per_unit=break_even_variable_cost_per_unit,
        notes=notes
    )
    
    # Create custom leverage repayment records
    if custom_repayments_data:
        for repayment_data in custom_repayments_data:
            leverage_repayment = LeverageRepayment(
                investment_id=investment.id,
                amount=repayment_data["amount"],
                repayment_date=repayment_data["repayment_date"],
                repayment_month=repayment_data["repayment_month"]
            )
            session.add(leverage_repayment)
        session.commit()
    
    # Compute metrics
    InvestmentMetricsService.compute_and_save_metrics(session, investment)
    
    # Redirect to list page
    return RedirectResponse(url="/investments", status_code=303)


@router.get("/{investment_id}", response_class=HTMLResponse)
def investment_detail(
    request: Request,
    investment_id: int,
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id)
):
    """Show investment detail with metrics and cash flow table"""
    investment = InvestmentService.get_investment(session, user_id, investment_id)
    if not investment:
        raise HTTPException(status_code=404, detail="Investment not found")
    
    metrics = InvestmentMetricsService.get_metrics(session, investment_id)
    cash_flow_table = InvestmentMetricsService.get_cash_flow_table(investment)
    
    return templates.TemplateResponse("investment_detail.html", {
        "request": request,
        "investment": investment,
        "metrics": metrics,
        "cash_flow_table": cash_flow_table
    })


@router.get("/{investment_id}/edit", response_class=HTMLResponse)
def edit_investment_modal(
    request: Request,
    investment_id: int,
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id)
):
    """Show modal for editing investment"""
    investment = InvestmentService.get_investment(session, user_id, investment_id)
    if not investment:
        raise HTTPException(status_code=404, detail="Investment not found")
    
    return templates.TemplateResponse("investment_edit_modal.html", {
        "request": request,
        "investment": investment,
        "cadence_options": [c.value for c in InvestmentCadence]
    })


@router.post("/{investment_id}", response_class=HTMLResponse)
def update_investment(
    request: Request,
    investment_id: int,
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id),
    name: str = Form(...),
    total_investment_value: Decimal = Form(...),
    installments: bool = Form(False),
    installment_value: Optional[Decimal] = Form(None),
    installment_months: Optional[int] = Form(None),
    gain_in_income_value: Decimal = Form(Decimal("0")),
    cadence: str = Form(InvestmentCadence.MONTHLY.value),
    one_off_inflow_value: Decimal = Form(Decimal("0")),
    salvage_value: Decimal = Form(Decimal("0")),
    discount_rate_annual_percent: Decimal = Form(Decimal("15.000")),
    reinvestment_rate_annual_percent: Decimal = Form(Decimal("15.000")),
    analysis_horizon_months: int = Form(60),
    break_even_fixed_costs: Decimal = Form(Decimal("0")),
    break_even_price_per_unit: Decimal = Form(Decimal("0")),
    break_even_variable_cost_per_unit: Decimal = Form(Decimal("0")),
    notes: Optional[str] = Form(None)
):
    """Update investment and recompute metrics"""
    # Validate discount rate range
    if not (Decimal("0") <= discount_rate_annual_percent <= Decimal("200")):
        raise HTTPException(status_code=400, detail="Discount rate must be between 0 and 200")
    
    # Validate reinvestment rate range
    if not (Decimal("0") <= reinvestment_rate_annual_percent <= Decimal("200")):
        raise HTTPException(status_code=400, detail="Reinvestment rate must be between 0 and 200")
    
    # Calculate percentage from absolute value
    if total_investment_value > 0 and gain_in_income_value > 0:
        gain_in_income_percent = (gain_in_income_value / total_investment_value) * Decimal("100")
    else:
        gain_in_income_percent = Decimal("0")
    
    # Update investment
    investment = InvestmentService.update_investment(
        session=session,
        user_id=user_id,
        investment_id=investment_id,
        name=name,
        total_investment_value=total_investment_value,
        installments=installments,
        installment_value=installment_value,
        installment_months=installment_months,
        gain_in_income_value=gain_in_income_value,
        gain_in_income_percent=gain_in_income_percent,
        cadence=InvestmentCadence(cadence),
        one_off_inflow_value=one_off_inflow_value,
        salvage_value=salvage_value,
        discount_rate_annual_percent=discount_rate_annual_percent,
        reinvestment_rate_annual_percent=reinvestment_rate_annual_percent,
        analysis_horizon_months=analysis_horizon_months,
        break_even_fixed_costs=break_even_fixed_costs,
        break_even_price_per_unit=break_even_price_per_unit,
        break_even_variable_cost_per_unit=break_even_variable_cost_per_unit,
        notes=notes
    )
    
    # Recompute metrics
    InvestmentMetricsService.compute_and_save_metrics(session, investment)
    
    # Redirect to detail page
    return RedirectResponse(url=f"/investments/{investment_id}", status_code=303)


@router.post("/{investment_id}/recalculate", response_class=HTMLResponse)
def recalculate_metrics(
    request: Request,
    investment_id: int,
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id)
):
    """Recalculate metrics for an investment"""
    investment = InvestmentService.get_investment(session, user_id, investment_id)
    if not investment:
        raise HTTPException(status_code=404, detail="Investment not found")
    
    # Recalculate and save metrics
    InvestmentMetricsService.compute_and_save_metrics(session, investment)
    
    # Redirect to detail page
    return RedirectResponse(url=f"/investments/{investment_id}", status_code=303)


@router.post("/{investment_id}/delete", response_class=HTMLResponse)
def delete_investment(
    request: Request,
    investment_id: int,
    session: Session = Depends(get_session),
    user_id: int = Depends(get_current_user_id)
):
    """Delete investment and its metrics"""
    InvestmentService.delete_investment(session, user_id, investment_id)
    
    # Redirect to list page
    return RedirectResponse(url="/investments", status_code=303)
