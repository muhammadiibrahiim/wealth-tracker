"""
Financial calculations service for investment analysis
Handles NPV, IRR, MIRR, Payback, PI, CAGR, Break-even with edge-case safety
"""
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple
import math


def safe_decimal(value: any, default: Decimal = Decimal("0")) -> Decimal:
    """Safely convert to Decimal"""
    try:
        if value is None:
            return default
        return Decimal(str(value))
    except (ValueError, InvalidOperation):
        return default


def annual_to_monthly_rate(annual_rate_percent: Decimal) -> Decimal:
    """Convert annual rate to monthly: r_m = (1 + r_a)^(1/12) - 1"""
    try:
        if annual_rate_percent == 0:
            return Decimal("0")
        r_annual = annual_rate_percent / Decimal("100")
        r_monthly = (Decimal("1") + r_annual) ** (Decimal("1") / Decimal("12")) - Decimal("1")
        return r_monthly
    except (ValueError, InvalidOperation, OverflowError):
        return Decimal("0")


def monthly_to_annual_rate(monthly_rate: Decimal) -> Decimal:
    """Convert monthly rate to annual: r_a = (1 + r_m)^12 - 1"""
    try:
        r_annual = (Decimal("1") + monthly_rate) ** Decimal("12") - Decimal("1")
        return r_annual * Decimal("100")  # as percentage
    except (ValueError, InvalidOperation, OverflowError):
        return Decimal("0")


def build_cash_flow(
    total_investment: Decimal,
    installments: bool,
    installment_value: Optional[Decimal],
    installment_months: Optional[int],
    gain_percent: Optional[Decimal],
    cadence: Optional[str],
    one_off_inflow: Decimal,
    salvage_value: Decimal,
    horizon_months: int,
    income_increases: bool = False,
    income_increase_rate_percent: Optional[Decimal] = None,
    income_increase_cadence: Optional[str] = None,
    is_leveraged: bool = False,
    leverage_amount: Decimal = Decimal("0"),
    leverage_repayment_type: str = "equal_installments",
    leverage_repayment_months: Optional[int] = None,
    custom_leverage_repayments: Optional[List[tuple[Decimal, int]]] = None,  # List of (amount, month)
    has_revenue: bool = False,
    revenue_amount: Decimal = Decimal("0"),
    revenue_installment_months: Optional[int] = None
) -> List[Decimal]:
    """
    Build monthly cash flow vector CF[0..horizon]
    
    If installments = False:
        CF[0] = -total_investment (pay all upfront)
    If installments = True:
        CF[0] = 0 or minimal
        CF[1..N] = -installment_value (pay over time as outflows)
    
    Then add income gains (with optional growth) and salvage value as inflows
    
    Returns NET cash flows (outflows + inflows) for each period
    """
    cf = [Decimal("0")] * (horizon_months + 1)
    
    # Investment outflow - either upfront or in installments
    # PROJECT METRICS: Show full investment cost WITHOUT leverage effects
    # (No leverage inflow, no loan repayments - pure project economics)
    if installments and installment_value and installment_months:
        # Pay in installments over time (outflows)
        inst_val = abs(safe_decimal(installment_value))
        months = installment_months
        for t in range(1, min(months + 1, horizon_months + 1)):
            cf[t] -= inst_val  # Negative because it's a cost/outflow
    else:
        # Pay entire investment upfront at t=0
        cf[0] = -abs(safe_decimal(total_investment))
    
    # NOTE: For project-level metrics, we DO NOT include:
    # - Leverage as an inflow
    # - Loan repayments as outflows
    # This shows the pure project economics before financing
    
    # Add one-off inflow at t=0 if provided
    if one_off_inflow:
        cf[0] += safe_decimal(one_off_inflow)
    
    # Income gain inflows (with optional growth)
    if gain_percent and cadence:
        base_gain = safe_decimal(total_investment) * (safe_decimal(gain_percent) / Decimal("100"))
        
        # Convert enum to string if needed
        cadence_str = cadence.value if hasattr(cadence, 'value') else str(cadence)
        
        # Determine income payment cadence in months
        income_cadence_months = 1 if cadence_str == "monthly" else (3 if cadence_str == "quarterly" else 12)
        
        # Determine growth cadence in months
        if income_increases and income_increase_rate_percent and income_increase_cadence:
            growth_rate = safe_decimal(income_increase_rate_percent) / Decimal("100")
            income_increase_cadence_str = income_increase_cadence.value if hasattr(income_increase_cadence, 'value') else str(income_increase_cadence)
            growth_cadence_months = 1 if income_increase_cadence_str == "monthly" else (3 if income_increase_cadence_str == "quarterly" else 12)
        else:
            growth_rate = Decimal("0")
            growth_cadence_months = 12  # Doesn't matter if no growth
        
        # Generate income cash flows
        if cadence_str == "monthly":
            for t in range(1, horizon_months + 1):
                # Calculate how many growth periods have passed (use floor division for discrete periods)
                if income_increases and growth_rate > 0:
                    growth_periods = (t - 1) // growth_cadence_months
                    growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                    cf[t] += base_gain * growth_multiplier
                else:
                    cf[t] += base_gain
                    
        elif cadence_str == "quarterly":
            for t in range(3, horizon_months + 1, 3):
                # Calculate how many growth periods have passed by month t (use floor division)
                if income_increases and growth_rate > 0:
                    growth_periods = (t - 1) // growth_cadence_months
                    growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                    cf[t] += (base_gain * Decimal("3")) * growth_multiplier
                else:
                    cf[t] += base_gain * Decimal("3")  # quarterly amount
                    
        elif cadence_str == "yearly":
            for t in range(12, horizon_months + 1, 12):
                # Calculate how many growth periods have passed by month t (use floor division)
                if income_increases and growth_rate > 0:
                    growth_periods = (t - 1) // growth_cadence_months
                    growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                    cf[t] += (base_gain * Decimal("12")) * growth_multiplier
                else:
                    cf[t] += base_gain * Decimal("12")  # yearly amount
    
    # Revenue installments (for business-type investments)
    if has_revenue and revenue_amount and revenue_installment_months:
        revenue_amt = safe_decimal(revenue_amount)
        months = revenue_installment_months
        # Distribute revenue evenly over installment months
        monthly_revenue = revenue_amt / Decimal(months)
        for t in range(1, min(months + 1, horizon_months + 1)):
            cf[t] += monthly_revenue
    
    # Salvage value at end of horizon
    if salvage_value:
        cf[horizon_months] += safe_decimal(salvage_value)
    
    return cf


def build_equity_cash_flow(
    total_investment: Decimal,
    leverage_amount: Decimal,
    installments: bool,
    installment_value: Optional[Decimal],
    installment_months: Optional[int],
    gain_percent: Optional[Decimal],
    cadence: Optional[str],
    one_off_inflow: Decimal,
    salvage_value: Decimal,
    horizon_months: int,
    income_increases: bool = False,
    income_increase_rate_percent: Optional[Decimal] = None,
    income_increase_cadence: Optional[str] = None,
    leverage_repayment_type: str = "equal_installments",
    leverage_repayment_months: Optional[int] = None,
    custom_leverage_repayments: Optional[List[tuple[Decimal, int]]] = None,
    has_revenue: bool = False,
    revenue_amount: Decimal = Decimal("0"),
    revenue_installment_months: Optional[int] = None
) -> List[Decimal]:
    """
    Build monthly equity cash flow - return on actual invested capital
    
    Equity perspective:
    - Initial outflow: total_investment - leverage_amount (only user's capital)
    - All project inflows (gains, revenue, salvage) are equity inflows
    - All loan repayments are equity outflows
    
    This shows the return on the user's actual invested capital, accounting for debt service.
    """
    cf = [Decimal("0")] * (horizon_months + 1)
    
    # Initial equity investment (user's capital only)
    equity_invested = safe_decimal(total_investment) - safe_decimal(leverage_amount)
    
    if installments and installment_value and installment_months:
        # Pay equity portion in installments
        inst_val = abs(safe_decimal(installment_value))
        months = min(installment_months, horizon_months)
        # User pays only the equity portion of each installment
        equity_portion = inst_val * (equity_invested / safe_decimal(total_investment))
        for t in range(1, months + 1):
            cf[t] -= equity_portion
    else:
        # Pay equity portion upfront
        cf[0] -= equity_invested
    
    # Add all project inflows (these belong to equity holder)
    # Income gains
    if gain_percent and cadence:
        base_gain = safe_decimal(total_investment) * (safe_decimal(gain_percent) / Decimal("100"))
        cadence_str = cadence.lower() if cadence else "monthly"
        
        # Income growth parameters
        growth_rate = Decimal("0")
        growth_cadence_months = 12  # default yearly
        if income_increases and income_increase_rate_percent:
            growth_rate = safe_decimal(income_increase_rate_percent) / Decimal("100")
            if income_increase_cadence:
                growth_cadence_map = {"monthly": 1, "quarterly": 3, "yearly": 12}
                growth_cadence_months = growth_cadence_map.get(income_increase_cadence.lower(), 12)
        
        # Apply income gains based on cadence
        if cadence_str == "monthly":
            for t in range(1, horizon_months + 1):
                if income_increases and growth_rate > 0:
                    growth_periods = (t - 1) // growth_cadence_months
                    growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                    cf[t] += base_gain * growth_multiplier
                else:
                    cf[t] += base_gain
                    
        elif cadence_str == "quarterly":
            for t in range(3, horizon_months + 1, 3):
                if income_increases and growth_rate > 0:
                    growth_periods = (t - 1) // growth_cadence_months
                    growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                    cf[t] += (base_gain * Decimal("3")) * growth_multiplier
                else:
                    cf[t] += base_gain * Decimal("3")
                    
        elif cadence_str == "yearly":
            for t in range(12, horizon_months + 1, 12):
                if income_increases and growth_rate > 0:
                    growth_periods = (t - 1) // growth_cadence_months
                    growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                    cf[t] += (base_gain * Decimal("12")) * growth_multiplier
                else:
                    cf[t] += base_gain * Decimal("12")
    
    # Revenue installments
    if has_revenue and revenue_amount and revenue_installment_months:
        revenue_amt = safe_decimal(revenue_amount)
        months = revenue_installment_months
        monthly_revenue = revenue_amt / Decimal(months)
        for t in range(1, min(months + 1, horizon_months + 1)):
            cf[t] += monthly_revenue
    
    # One-off inflow
    if one_off_inflow:
        cf[1] += safe_decimal(one_off_inflow)
    
    # Salvage value at end
    if salvage_value:
        cf[horizon_months] += safe_decimal(salvage_value)
    
    # Subtract loan repayments (equity outflows)
    if leverage_repayment_type == "equal_installments" and leverage_repayment_months:
        monthly_repayment = safe_decimal(leverage_amount) / Decimal(leverage_repayment_months)
        for t in range(1, min(leverage_repayment_months + 1, horizon_months + 1)):
            cf[t] -= monthly_repayment
    elif leverage_repayment_type == "custom_schedule" and custom_leverage_repayments:
        for amount, month in custom_leverage_repayments:
            if 0 <= month <= horizon_months:
                cf[month] -= safe_decimal(amount)
    
    return cf


def build_cash_flow_detailed(
    total_investment: Decimal,
    installments: bool,
    installment_value: Optional[Decimal],
    installment_months: Optional[int],
    gain_percent: Optional[Decimal],
    cadence: Optional[str],
    one_off_inflow: Decimal,
    salvage_value: Decimal,
    horizon_months: int,
    income_increases: bool = False,
    income_increase_rate_percent: Optional[Decimal] = None,
    income_increase_cadence: Optional[str] = None,
    is_leveraged: bool = False,
    leverage_amount: Decimal = Decimal("0"),
    leverage_repayment_type: str = "equal_installments",
    leverage_repayment_months: Optional[int] = None,
    custom_leverage_repayments: Optional[List[tuple[Decimal, int]]] = None,
    has_revenue: bool = False,
    revenue_amount: Decimal = Decimal("0"),
    revenue_installment_months: Optional[int] = None
) -> tuple[List[Decimal], List[Decimal]]:
    """
    Build detailed cash flow vectors with SEPARATE inflows and outflows
    
    Returns: (inflows, outflows) as two separate lists
    """
    inflows = [Decimal("0")] * (horizon_months + 1)
    outflows = [Decimal("0")] * (horizon_months + 1)
    
    # Investment outflow - either upfront or in installments
    if installments and installment_value and installment_months:
        # Pay in installments over time (outflows)
        inst_val = abs(safe_decimal(installment_value))
        months = installment_months
        for t in range(1, min(months + 1, horizon_months + 1)):
            outflows[t] += inst_val
    else:
        # Pay entire investment upfront at t=0
        outflows[0] = abs(safe_decimal(total_investment))
    
    # Leverage (borrowed money) - inflow at t=0, repayment based on type
    if is_leveraged and leverage_amount and leverage_amount > 0:
        leverage_amt = safe_decimal(leverage_amount)
        # Leverage is borrowed money - inflow at t=0
        inflows[0] += leverage_amt
        
        # Repayment handling based on type
        if leverage_repayment_type == "equal_installments":
            # Equal monthly installments
            if leverage_repayment_months and leverage_repayment_months > 0:
                monthly_repayment = leverage_amt / Decimal(leverage_repayment_months)
                for t in range(1, min(leverage_repayment_months + 1, horizon_months + 1)):
                    outflows[t] += monthly_repayment
        elif leverage_repayment_type == "custom_schedule":
            # Custom repayment schedule
            if custom_leverage_repayments:
                for amount, month in custom_leverage_repayments:
                    if 0 < month <= horizon_months:
                        outflows[month] += safe_decimal(amount)
    
    # Add one-off inflow at t=0 if provided
    if one_off_inflow:
        inflows[0] += safe_decimal(one_off_inflow)
    
    # Income gain inflows (with optional growth)
    if gain_percent and cadence:
        base_gain = safe_decimal(total_investment) * (safe_decimal(gain_percent) / Decimal("100"))
        
        # Convert enum to string if needed
        cadence_str = cadence.value if hasattr(cadence, 'value') else str(cadence)
        
        # Determine growth cadence in months
        if income_increases and income_increase_rate_percent and income_increase_cadence:
            growth_rate = safe_decimal(income_increase_rate_percent) / Decimal("100")
            income_increase_cadence_str = income_increase_cadence.value if hasattr(income_increase_cadence, 'value') else str(income_increase_cadence)
            growth_cadence_months = 1 if income_increase_cadence_str == "monthly" else (3 if income_increase_cadence_str == "quarterly" else 12)
        else:
            growth_rate = Decimal("0")
            growth_cadence_months = 12
        
        # Generate income cash flows
        if cadence_str == "monthly":
            for t in range(1, horizon_months + 1):
                if income_increases and growth_rate > 0:
                    growth_periods = (t - 1) // growth_cadence_months
                    growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                    inflows[t] += base_gain * growth_multiplier
                else:
                    inflows[t] += base_gain
                    
        elif cadence_str == "quarterly":
            for t in range(3, horizon_months + 1, 3):
                if income_increases and growth_rate > 0:
                    growth_periods = (t - 1) // growth_cadence_months
                    growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                    inflows[t] += (base_gain * Decimal("3")) * growth_multiplier
                else:
                    inflows[t] += base_gain * Decimal("3")
                    
        elif cadence_str == "yearly":
            for t in range(12, horizon_months + 1, 12):
                if income_increases and growth_rate > 0:
                    growth_periods = (t - 1) // growth_cadence_months
                    growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                    inflows[t] += (base_gain * Decimal("12")) * growth_multiplier
                else:
                    inflows[t] += base_gain * Decimal("12")
    
    # Revenue installments (for business-type investments)
    if has_revenue and revenue_amount and revenue_installment_months:
        revenue_amt = safe_decimal(revenue_amount)
        months = revenue_installment_months
        # Distribute revenue evenly over installment months
        monthly_revenue = revenue_amt / Decimal(months)
        for t in range(1, min(months + 1, horizon_months + 1)):
            inflows[t] += monthly_revenue
    
    # Salvage value at end of horizon
    if salvage_value:
        inflows[horizon_months] += safe_decimal(salvage_value)
    
    return inflows, outflows


def calculate_npv(cash_flows: List[Decimal], discount_rate_monthly: Decimal) -> Optional[Decimal]:
    """Calculate Net Present Value with edge-case handling"""
    try:
        npv = Decimal("0")
        for t, cf_t in enumerate(cash_flows):
            if discount_rate_monthly == 0:
                npv += cf_t
            else:
                npv += cf_t / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
        
        if math.isnan(float(npv)) or math.isinf(float(npv)):
            return None
        return npv
    except (ValueError, InvalidOperation, OverflowError, ZeroDivisionError):
        return None


def calculate_pv_inflows(cash_flows: List[Decimal], discount_rate_monthly: Decimal) -> Optional[Decimal]:
    """
    Calculate Present Value of all future inflows (positive cash flows only)
    
    Note: This calculates PV based on NET positive cash flows.
    For gross revenue inflows, use calculate_gross_pv_inflows instead.
    """
    try:
        pv_inflows = Decimal("0")
        for t, cf_t in enumerate(cash_flows):
            if cf_t > 0:  # Only consider positive cash flows (inflows)
                if discount_rate_monthly == 0:
                    pv_inflows += cf_t
                else:
                    pv_inflows += cf_t / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
        
        if math.isnan(float(pv_inflows)) or math.isinf(float(pv_inflows)):
            return None
        return pv_inflows
    except (ValueError, InvalidOperation, OverflowError, ZeroDivisionError):
        return None


def calculate_pv_outflows(cash_flows: List[Decimal], discount_rate_monthly: Decimal) -> Optional[Decimal]:
    """
    Calculate Present Value of all outflows (negative cash flows only)
    Used for PI calculation and financial analysis
    
    Note: This discounts NET negative cash flows.
    For gross investment outflows, use calculate_gross_pv_outflows instead.
    """
    try:
        pv_outflows = Decimal("0")
        for t, cf_t in enumerate(cash_flows):
            if cf_t < 0:  # Only consider negative cash flows (outflows)
                if discount_rate_monthly == 0:
                    pv_outflows += abs(cf_t)
                else:
                    pv_outflows += abs(cf_t) / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
        
        if math.isnan(float(pv_outflows)) or math.isinf(float(pv_outflows)):
            return None
        return pv_outflows
    except (ValueError, InvalidOperation, OverflowError, ZeroDivisionError):
        return None


def calculate_gross_pv_outflows(
    total_investment: Decimal,
    installments: bool,
    installment_value: Optional[Decimal],
    installment_months: Optional[int],
    discount_rate_monthly: Decimal,
    is_leveraged: bool = False,
    leverage_amount: Optional[Decimal] = None,
    leverage_repayment_type: Optional[str] = None,
    leverage_repayment_months: Optional[int] = None,
    custom_leverage_repayments: Optional[List[tuple]] = None
) -> Decimal:
    """
    Calculate Present Value of GROSS outflows (investment costs before netting against inflows)
    This gives the PV of total investment regardless of when income is received
    
    For PI calculation: PI = PV(gross inflows) / PV(gross outflows)
    """
    try:
        pv_outflows = Decimal("0")
        
        # Investment outflows
        if installments and installment_value and installment_months:
            # Discount each installment payment
            inst_val = safe_decimal(installment_value)
            for t in range(1, installment_months + 1):
                if discount_rate_monthly == 0:
                    pv_outflows += inst_val
                else:
                    pv_outflows += inst_val / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
        else:
            # Upfront payment at t=0
            pv_outflows = safe_decimal(total_investment)
        
        # Leverage repayments (if applicable for project-level)
        # Note: For pure project metrics, we don't include leverage repayments
        # This is only for cases where we want to track all cash outflows
        if is_leveraged and leverage_amount and leverage_amount > 0:
            leverage_amt = safe_decimal(leverage_amount)
            
            if leverage_repayment_type == "equal_installments":
                if leverage_repayment_months and leverage_repayment_months > 0:
                    monthly_repayment = leverage_amt / Decimal(leverage_repayment_months)
                    for t in range(1, leverage_repayment_months + 1):
                        if discount_rate_monthly == 0:
                            pv_outflows += monthly_repayment
                        else:
                            pv_outflows += monthly_repayment / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
            
            elif leverage_repayment_type == "custom_schedule":
                if custom_leverage_repayments:
                    for amount, month in custom_leverage_repayments:
                        if discount_rate_monthly == 0:
                            pv_outflows += safe_decimal(amount)
                        else:
                            pv_outflows += safe_decimal(amount) / ((Decimal("1") + discount_rate_monthly) ** Decimal(month))
        
        return pv_outflows
    except (ValueError, InvalidOperation, OverflowError, ZeroDivisionError):
        return Decimal("0")


def calculate_gross_inflows(
    has_revenue: bool,
    revenue_amount: Decimal,
    gain_percent: Optional[Decimal],
    total_investment: Decimal,
    cadence: Optional[str],
    horizon_months: int,
    one_off_inflow: Decimal,
    salvage_value: Decimal,
    income_increases: bool = False,
    income_increase_rate_percent: Optional[Decimal] = None,
    income_increase_cadence: Optional[str] = None
) -> Decimal:
    """
    Calculate gross inflows (total revenue before netting against costs)
    This represents the actual revenue/income generated by the investment
    """
    try:
        gross_inflows = Decimal("0")
        
        # Revenue installments
        if has_revenue and revenue_amount:
            gross_inflows += safe_decimal(revenue_amount)
        
        # Income gains
        if gain_percent and cadence:
            base_gain = safe_decimal(total_investment) * (safe_decimal(gain_percent) / Decimal("100"))
            cadence_str = cadence.value if hasattr(cadence, 'value') else str(cadence)
            
            # Determine growth parameters
            if income_increases and income_increase_rate_percent and income_increase_cadence:
                growth_rate = safe_decimal(income_increase_rate_percent) / Decimal("100")
                income_increase_cadence_str = income_increase_cadence.value if hasattr(income_increase_cadence, 'value') else str(income_increase_cadence)
                growth_cadence_months = 1 if income_increase_cadence_str == "monthly" else (3 if income_increase_cadence_str == "quarterly" else 12)
            else:
                growth_rate = Decimal("0")
                growth_cadence_months = 12
            
            # Calculate total income based on cadence
            if cadence_str == "monthly":
                for t in range(1, horizon_months + 1):
                    if income_increases and growth_rate > 0:
                        growth_periods = (t - 1) // growth_cadence_months
                        growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                        gross_inflows += base_gain * growth_multiplier
                    else:
                        gross_inflows += base_gain
            elif cadence_str == "quarterly":
                num_quarters = horizon_months // 3
                for q in range(num_quarters):
                    if income_increases and growth_rate > 0:
                        growth_periods = (q * 3) // growth_cadence_months
                        growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                        gross_inflows += (base_gain * Decimal("3")) * growth_multiplier
                    else:
                        gross_inflows += base_gain * Decimal("3")
            elif cadence_str == "yearly":
                num_years = horizon_months // 12
                for y in range(num_years):
                    if income_increases and growth_rate > 0:
                        growth_periods = (y * 12) // growth_cadence_months
                        growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                        gross_inflows += (base_gain * Decimal("12")) * growth_multiplier
                    else:
                        gross_inflows += base_gain * Decimal("12")
        
        # One-off inflow
        if one_off_inflow:
            gross_inflows += safe_decimal(one_off_inflow)
        
        # Salvage value
        if salvage_value:
            gross_inflows += safe_decimal(salvage_value)
        
        return gross_inflows
    except (ValueError, InvalidOperation, OverflowError):
        return Decimal("0")


def calculate_gross_pv_inflows(
    has_revenue: bool,
    revenue_amount: Decimal,
    revenue_installment_months: Optional[int],
    gain_percent: Optional[Decimal],
    total_investment: Decimal,
    cadence: Optional[str],
    horizon_months: int,
    one_off_inflow: Decimal,
    salvage_value: Decimal,
    discount_rate_monthly: Decimal,
    income_increases: bool = False,
    income_increase_rate_percent: Optional[Decimal] = None,
    income_increase_cadence: Optional[str] = None
) -> Decimal:
    """
    Calculate Present Value of gross inflows (discounting each inflow component)
    This gives the PV of total revenue regardless of when costs are incurred
    """
    try:
        pv_gross = Decimal("0")
        
        # Revenue installments - discount each monthly payment
        if has_revenue and revenue_amount and revenue_installment_months:
            revenue_amt = safe_decimal(revenue_amount)
            months = revenue_installment_months
            monthly_revenue = revenue_amt / Decimal(months)
            for t in range(1, min(months + 1, horizon_months + 1)):
                if discount_rate_monthly == 0:
                    pv_gross += monthly_revenue
                else:
                    pv_gross += monthly_revenue / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
        
        # Income gains - discount each payment
        if gain_percent and cadence:
            base_gain = safe_decimal(total_investment) * (safe_decimal(gain_percent) / Decimal("100"))
            cadence_str = cadence.value if hasattr(cadence, 'value') else str(cadence)
            
            # Determine growth parameters
            if income_increases and income_increase_rate_percent and income_increase_cadence:
                growth_rate = safe_decimal(income_increase_rate_percent) / Decimal("100")
                income_increase_cadence_str = income_increase_cadence.value if hasattr(income_increase_cadence, 'value') else str(income_increase_cadence)
                growth_cadence_months = 1 if income_increase_cadence_str == "monthly" else (3 if income_increase_cadence_str == "quarterly" else 12)
            else:
                growth_rate = Decimal("0")
                growth_cadence_months = 12
            
            # Discount each income payment
            if cadence_str == "monthly":
                for t in range(1, horizon_months + 1):
                    if income_increases and growth_rate > 0:
                        growth_periods = (t - 1) // growth_cadence_months
                        growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                        inflow = base_gain * growth_multiplier
                    else:
                        inflow = base_gain
                    
                    if discount_rate_monthly == 0:
                        pv_gross += inflow
                    else:
                        pv_gross += inflow / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
            
            elif cadence_str == "quarterly":
                for t in range(3, horizon_months + 1, 3):
                    if income_increases and growth_rate > 0:
                        growth_periods = (t - 1) // growth_cadence_months
                        growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                        inflow = (base_gain * Decimal("3")) * growth_multiplier
                    else:
                        inflow = base_gain * Decimal("3")
                    
                    if discount_rate_monthly == 0:
                        pv_gross += inflow
                    else:
                        pv_gross += inflow / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
            
            elif cadence_str == "yearly":
                for t in range(12, horizon_months + 1, 12):
                    if income_increases and growth_rate > 0:
                        growth_periods = (t - 1) // growth_cadence_months
                        growth_multiplier = (Decimal("1") + growth_rate) ** growth_periods
                        inflow = (base_gain * Decimal("12")) * growth_multiplier
                    else:
                        inflow = base_gain * Decimal("12")
                    
                    if discount_rate_monthly == 0:
                        pv_gross += inflow
                    else:
                        pv_gross += inflow / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
        
        # One-off inflow at t=0
        if one_off_inflow:
            pv_gross += safe_decimal(one_off_inflow)
        
        # Salvage value at end
        if salvage_value:
            salvage_val = safe_decimal(salvage_value)
            if discount_rate_monthly == 0:
                pv_gross += salvage_val
            else:
                pv_gross += salvage_val / ((Decimal("1") + discount_rate_monthly) ** Decimal(horizon_months))
        
        return pv_gross
    except (ValueError, InvalidOperation, OverflowError, ZeroDivisionError):
        return Decimal("0")


def calculate_total_inflows(cash_flows: List[Decimal]) -> Optional[Decimal]:
    """
    Calculate total inflows (sum of all positive cash flows, non-discounted)
    
    Note: This calculates total based on NET positive cash flows.
    For gross revenue inflows, use calculate_gross_inflows instead.
    """
    try:
        total_inflows = sum(cf for cf in cash_flows if cf > 0)
        if math.isnan(float(total_inflows)) or math.isinf(float(total_inflows)):
            return None
        return total_inflows
    except (ValueError, InvalidOperation, OverflowError):
        return None


def calculate_roi(cash_flows: List[Decimal]) -> Optional[Decimal]:
    """
    ROI % = 100 × (Total net gain / Total investment)
    Handles both upfront and installment payments
    """
    try:
        # Calculate total investment (all negative cash flows)
        total_investment = sum(abs(cf) for cf in cash_flows if cf < 0)
        if total_investment == 0:
            return None
        
        # Calculate total returns (all positive cash flows)
        total_inflows = sum(cf for cf in cash_flows if cf > 0)
        
        # ROI = (Net Profit / Investment) × 100
        roi = ((total_inflows - total_investment) / total_investment) * Decimal("100")
        
        if math.isnan(float(roi)) or math.isinf(float(roi)):
            return None
        return roi
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return None


def calculate_irr(cash_flows: List[Decimal], max_iterations: int = 100, horizon_months: Optional[int] = None) -> Optional[Decimal]:
    """
    Calculate IRR using Newton-Raphson method
    Returns annualized IRR as percentage
    
    For short-term investments (< 12 months), uses simple annualization (nominal APR)
    For longer-term investments, uses compounding (effective annual rate)
    """
    try:
        # Check if all cash flows are same sign (no IRR possible)
        if all(cf >= 0 for cf in cash_flows) or all(cf <= 0 for cf in cash_flows):
            return None
        
        # Initial guess
        rate = Decimal("0.1")
        
        for _ in range(max_iterations):
            npv = Decimal("0")
            npv_derivative = Decimal("0")
            
            for t, cf_t in enumerate(cash_flows):
                if cf_t == 0:
                    continue
                denominator = (Decimal("1") + rate) ** Decimal(t)
                npv += cf_t / denominator
                if t > 0:
                    npv_derivative -= Decimal(t) * cf_t / (denominator * (Decimal("1") + rate))
            
            if abs(npv) < Decimal("0.0001"):  # converged
                # For short-term investments (< 12 months), use simple annualization
                # For longer investments, use compounding
                if horizon_months and horizon_months < 12:
                    # Simple annualization (nominal APR): monthly_rate × 12
                    irr_annual = rate * Decimal("12") * Decimal("100")
                else:
                    # Compound annualization (effective): (1 + r_m)^12 - 1
                    irr_annual = monthly_to_annual_rate(rate)
                
                if math.isnan(float(irr_annual)) or math.isinf(float(irr_annual)):
                    return None
                return irr_annual
            
            if npv_derivative == 0:
                return None
            
            rate = rate - npv / npv_derivative
            
            # Prevent extreme values
            if rate < Decimal("-0.99") or rate > Decimal("10"):
                return None
        
        return None  # Did not converge
    except (ValueError, InvalidOperation, OverflowError, ZeroDivisionError):
        return None


def calculate_mirr(
    cash_flows: List[Decimal],
    discount_rate_monthly: Decimal,
    reinvestment_rate_monthly: Decimal
) -> Optional[Decimal]:
    """
    Calculate MIRR (Modified Internal Rate of Return)
    MIRR = ((FV_positive / -PV_negative)^(1/n) - 1) × 100
    Returns annualized MIRR as percentage
    """
    try:
        n = len(cash_flows) - 1
        if n <= 0:
            return None
        
        # Future value of positive cash flows (reinvested)
        fv_positive = Decimal("0")
        for t, cf_t in enumerate(cash_flows):
            if cf_t > 0:
                periods_to_end = n - t
                fv_positive += cf_t * ((Decimal("1") + reinvestment_rate_monthly) ** Decimal(periods_to_end))
        
        # Present value of negative cash flows (financed)
        pv_negative = Decimal("0")
        for t, cf_t in enumerate(cash_flows):
            if cf_t < 0:
                pv_negative += cf_t / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
        
        if pv_negative == 0 or fv_positive == 0:
            return None
        
        # MIRR calculation
        mirr_monthly = (fv_positive / abs(pv_negative)) ** (Decimal("1") / Decimal(n)) - Decimal("1")
        mirr_annual = monthly_to_annual_rate(mirr_monthly)
        
        if math.isnan(float(mirr_annual)) or math.isinf(float(mirr_annual)):
            return None
        return mirr_annual
    except (ValueError, InvalidOperation, OverflowError, ZeroDivisionError):
        return None


def calculate_payback(cash_flows: List[Decimal]) -> Optional[Decimal]:
    """
    Calculate simple payback period in months with interpolation
    Returns number of months to break even
    """
    try:
        cumulative = Decimal("0")
        for t, cf_t in enumerate(cash_flows):
            cumulative += cf_t
            if cumulative >= 0:
                # If we break even at t=0 with positive or zero initial cash flow, 
                # and there are future outflows, this is not a true payback
                if t == 0 and any(cf < 0 for cf in cash_flows[1:]):
                    continue
                if t == 0:
                    return Decimal("0")
                # Interpolate
                prev_cumulative = cumulative - cf_t
                if cf_t == 0:
                    return Decimal(t)
                fraction = abs(prev_cumulative) / cf_t
                payback = Decimal(t - 1) + fraction
                return payback
        
        return None  # Never breaks even
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return None


def calculate_discounted_payback(cash_flows: List[Decimal], discount_rate_monthly: Decimal) -> Optional[Decimal]:
    """Calculate discounted payback period in months"""
    try:
        cumulative = Decimal("0")
        for t, cf_t in enumerate(cash_flows):
            if discount_rate_monthly == 0:
                discounted_cf = cf_t
            else:
                discounted_cf = cf_t / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
            
            cumulative += discounted_cf
            if cumulative >= 0:
                # If we break even at t=0 with positive or zero initial cash flow,
                # and there are future outflows, this is not a true payback
                if t == 0 and any(cf < 0 for cf in cash_flows[1:]):
                    continue
                if t == 0:
                    return Decimal("0")
                # Interpolate
                prev_cumulative = cumulative - discounted_cf
                if discounted_cf == 0:
                    return Decimal(t)
                fraction = abs(prev_cumulative) / discounted_cf
                payback = Decimal(t - 1) + fraction
                return payback
        
        return None
    except (ValueError, InvalidOperation, OverflowError, ZeroDivisionError):
        return None


def calculate_profitability_index(cash_flows: List[Decimal], discount_rate_monthly: Decimal) -> Optional[Decimal]:
    """
    Profitability Index = PV(inflows) / PV(outflows)
    Handles both upfront and installment payments
    """
    try:
        # Calculate present value of all outflows (investments)
        pv_outflows = Decimal("0")
        for t, cf in enumerate(cash_flows):
            if cf < 0:
                if discount_rate_monthly == 0:
                    pv_outflows += abs(cf)
                else:
                    pv_outflows += abs(cf) / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
        
        if pv_outflows == 0:
            return None
        
        # Calculate present value of all inflows (returns)
        pv_inflows = Decimal("0")
        for t, cf in enumerate(cash_flows):
            if cf > 0:
                if discount_rate_monthly == 0:
                    pv_inflows += cf
                else:
                    pv_inflows += cf / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
        
        pi = pv_inflows / pv_outflows
        
        if math.isnan(float(pi)) or math.isinf(float(pi)):
            return None
        return pi
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return None


def calculate_profitability_index_gross(
    pv_inflows: Decimal,
    pv_outflows: Decimal
) -> Optional[Decimal]:
    """
    Calculate Profitability Index using GROSS inflows
    PI = PV(inflows) / PV(outflows)
    
    Use this with calculate_gross_pv_inflows and calculate_pv_outflows
    for accurate PI calculation that doesn't miss netted inflows.
    """
    try:
        if pv_outflows == 0 or pv_outflows is None or pv_inflows is None:
            return None
        
        pi = pv_inflows / pv_outflows
        
        if math.isnan(float(pi)) or math.isinf(float(pi)):
            return None
        return pi
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return None


def calculate_cagr(cash_flows: List[Decimal], horizon_months: int) -> Optional[Decimal]:
    """
    CAGR % = ((Ending Value / Beginning Value)^(1/years) - 1) × 100
    Handles both upfront and installment payments
    """
    try:
        # Calculate total investment (all negative cash flows)
        beginning = sum(abs(cf) for cf in cash_flows if cf < 0)
        if beginning == 0:
            return None
        
        # Ending value = sum of all positive cash flows (returns)
        ending = sum(cf for cf in cash_flows if cf > 0)
        
        if ending == 0:
            return None
        
        years = Decimal(horizon_months) / Decimal("12")
        if years == 0:
            return None
        
        cagr = ((ending / beginning) ** (Decimal("1") / years) - Decimal("1")) * Decimal("100")
        
        if math.isnan(float(cagr)) or math.isinf(float(cagr)):
            return None
        return cagr
    except (ValueError, InvalidOperation, OverflowError, ZeroDivisionError):
        return None


def calculate_break_even_units(
    fixed_costs: Optional[Decimal],
    price_per_unit: Optional[Decimal],
    variable_cost_per_unit: Optional[Decimal]
) -> Optional[Decimal]:
    """
    Break-even units = Fixed Costs / (Price - Variable Cost)
    """
    try:
        if not all([fixed_costs, price_per_unit, variable_cost_per_unit]):
            return None
        
        fc = safe_decimal(fixed_costs)
        price = safe_decimal(price_per_unit)
        var_cost = safe_decimal(variable_cost_per_unit)
        
        contribution = price - var_cost
        if contribution == 0:
            return None
        
        units = fc / contribution
        
        if math.isnan(float(units)) or math.isinf(float(units)) or units < 0:
            return None
        return units
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return None
