from sqlmodel import Session, create_engine, select
from models import Investment
from services import fincalc
from decimal import Decimal

engine = create_engine('sqlite:///./wealth_tracker.db')
session = Session(engine)

inv = session.exec(select(Investment).where(Investment.id == 2)).first()

custom_repayments = [(rep.amount, rep.repayment_month) for rep in inv.leverage_repayments]

# Build cash flows
project_cf = fincalc.build_cash_flow(
    inv.total_investment_value,
    inv.installments,
    inv.installment_value,
    inv.installment_months,
    inv.gain_in_income_percent,
    inv.cadence,
    inv.one_off_inflow_value,
    inv.salvage_value,
    inv.analysis_horizon_months,
    inv.income_increases,
    inv.income_increase_rate_percent,
    inv.income_increase_cadence,
    inv.is_leveraged,
    inv.leverage_amount,
    inv.leverage_repayment_type,
    inv.leverage_repayment_months,
    custom_repayments,
    inv.has_revenue,
    inv.revenue_amount,
    inv.revenue_installment_months
)

equity_cf = fincalc.build_equity_cash_flow(
    inv.total_investment_value,
    inv.leverage_amount,
    inv.installments,
    inv.installment_value,
    inv.installment_months,
    inv.gain_in_income_percent,
    inv.cadence,
    inv.one_off_inflow_value,
    inv.salvage_value,
    inv.analysis_horizon_months,
    inv.income_increases,
    inv.income_increase_rate_percent,
    inv.income_increase_cadence,
    inv.leverage_repayment_type,
    inv.leverage_repayment_months,
    custom_repayments,
    inv.has_revenue,
    inv.revenue_amount,
    inv.revenue_installment_months
)

discount_rate = fincalc.annual_to_monthly_rate(inv.discount_rate_annual_percent)

print('='*70)
print('REVENUE CONFIGURATION')
print('='*70)
print(f'Has Revenue: {inv.has_revenue}')
print(f'Revenue Amount: Rs {inv.revenue_amount:,.2f}')
print(f'Revenue Installment Months: {inv.revenue_installment_months}')
print(f'Monthly Revenue: Rs {inv.revenue_amount / inv.revenue_installment_months:,.2f}')
print()

print('='*70)
print('PROJECT CASH FLOW BREAKDOWN')
print('='*70)
cumulative = Decimal(0)
for i, cf in enumerate(project_cf):
    if cf != 0:
        cumulative += cf
        print(f'  Month {i}: Rs {cf:,.2f} (Cumulative: Rs {cumulative:,.2f})')
print()

print('='*70)
print('PROJECT METRICS')
print('='*70)
project_total_inflows_sum = sum(cf for cf in project_cf if cf > 0)
project_total_inflows_func = fincalc.calculate_total_inflows(project_cf)
project_pv_inflows = fincalc.calculate_pv_inflows(project_cf, discount_rate)

print(f'Total Inflows (sum of positive CF): Rs {project_total_inflows_sum:,.2f}')
print(f'Total Inflows (via function):       Rs {project_total_inflows_func:,.2f}')
print(f'PV of Inflows:                      Rs {project_pv_inflows:,.2f}')
print()

print('Expected Project Total Inflows: Rs 375,400 (revenue amount)')
print(f'Difference: Rs {375400 - float(project_total_inflows_sum):,.2f}')
print()

print('='*70)
print('EQUITY CASH FLOW BREAKDOWN')
print('='*70)
cumulative = Decimal(0)
for i, cf in enumerate(equity_cf):
    if cf != 0:
        cumulative += cf
        print(f'  Month {i}: Rs {cf:,.2f} (Cumulative: Rs {cumulative:,.2f})')
print()

print('='*70)
print('EQUITY METRICS')
print('='*70)
equity_total_inflows_sum = sum(cf for cf in equity_cf if cf > 0)
equity_total_inflows_func = fincalc.calculate_total_inflows(equity_cf)
equity_pv_inflows = fincalc.calculate_pv_inflows(equity_cf, discount_rate)

print(f'Total Inflows (sum of positive CF): Rs {equity_total_inflows_sum:,.2f}')
print(f'Total Inflows (via function):       Rs {equity_total_inflows_func:,.2f}')
print(f'PV of Inflows:                      Rs {equity_pv_inflows:,.2f}')
print()

print('='*70)
print('ANALYSIS')
print('='*70)
print(f'Discount Rate (annual): {inv.discount_rate_annual_percent}%')
print(f'Discount Rate (monthly effective): {discount_rate * 100:.6f}%')
print()

# Manual PV calculation for verification
print('Manual PV Calculation (first 3 inflows):')
for i, cf in enumerate(project_cf[:4]):
    if cf > 0:
        discount_factor = (Decimal('1') + discount_rate) ** Decimal(i)
        pv = cf / discount_factor
        print(f'  Month {i}: CF = Rs {cf:,.2f}, Factor = {discount_factor:.6f}, PV = Rs {pv:,.2f}')

session.close()
