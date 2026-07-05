"""Debug Jan-2025 Cash Flows"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import create_engine, Session, select
from models import Investment
from services import fincalc
from decimal import Decimal

engine = create_engine('sqlite:///./wealth_tracker.db')
session = Session(engine)

inv = session.get(Investment, 1)

# Build cash flows
cash_flows = fincalc.build_cash_flow(
    total_investment=inv.total_investment_value,
    installments=inv.installments,
    installment_value=inv.installment_value,
    installment_months=inv.installment_months,
    gain_percent=inv.gain_in_income_percent,
    cadence=inv.cadence,
    one_off_inflow=inv.one_off_inflow_value,
    salvage_value=inv.salvage_value,
    horizon_months=inv.analysis_horizon_months,
    income_increases=inv.income_increases,
    income_increase_rate_percent=inv.income_increase_rate_percent,
    income_increase_cadence=inv.income_increase_cadence,
    is_leveraged=False,
    leverage_amount=None,
    leverage_repayment_type=None,
    leverage_repayment_months=None,
    custom_leverage_repayments=None,
    has_revenue=False,
    revenue_amount=None,
    revenue_installment_months=None
)

print('\n' + '='*90)
print('CASH FLOW ANALYSIS - Jan-2025 Investment')
print('='*90)

print('\nMONTHLY CASH FLOWS:')
cumulative = Decimal("0")
for t, cf in enumerate(cash_flows):
    cumulative += cf
    if t <= 14 or t >= 22:  # Show first 15 and last 3 months
        print(f'  Month {t:2d}: Rs {float(cf):>10,.2f} (Cumulative: Rs {float(cumulative):>12,.2f})')
    elif t == 15:
        print(f'  ... (months 15-21 omitted)')

# Calculate components
total_inflows = sum(cf for cf in cash_flows if cf > 0)
total_outflows = abs(sum(cf for cf in cash_flows if cf < 0))

print('\n' + '='*90)
print('CALCULATED TOTALS:')
print('='*90)
print(f'  Total Inflows (positive CFs): Rs {float(total_inflows):,.2f}')
print(f'  Total Outflows (negative CFs): Rs {float(total_outflows):,.2f}')
print(f'  Net: Rs {float(total_inflows - total_outflows):,.2f}')

print('\n' + '='*90)
print('EXPECTED vs ACTUAL:')
print('='*90)

# Calculate expected income
base_income = inv.total_investment_value * (inv.gain_in_income_percent / Decimal("100"))
increased_income = base_income * (Decimal("1") + inv.income_increase_rate_percent / Decimal("100"))

print(f'\nBase Income (8.317% of Rs 60,116):')
print(f'  = Rs {float(base_income):,.2f} per month')
print(f'\nIncreased Income (base × 1.20):')
print(f'  = Rs {float(increased_income):,.2f} per month')

print(f'\nExpected Income Calculation:')
print(f'  Months 1-12: 12 × Rs {float(base_income):,.2f} = Rs {float(12 * base_income):,.2f}')
print(f'  Months 13-24: 12 × Rs {float(increased_income):,.2f} = Rs {float(12 * increased_income):,.2f}')
print(f'  Salvage (t=24): Rs 86,567.04')
print(f'  Expected Total Inflows: Rs {float(12 * base_income + 12 * increased_income + Decimal("86567.04")):,.2f}')

# Use gross inflows calculation
gross_inflows = fincalc.calculate_gross_inflows(
    has_revenue=False,
    revenue_amount=None,
    gain_percent=inv.gain_in_income_percent,
    total_investment=inv.total_investment_value,
    cadence=inv.cadence,
    horizon_months=inv.analysis_horizon_months,
    one_off_inflow=inv.one_off_inflow_value,
    salvage_value=inv.salvage_value,
    income_increases=inv.income_increases,
    income_increase_rate_percent=inv.income_increase_rate_percent,
    income_increase_cadence=inv.income_increase_cadence
)

print(f'\nGross Inflows (via calculate_gross_inflows): Rs {float(gross_inflows):,.2f}')

print('\n' + '='*90)
print('ISSUE DIAGNOSIS:')
print('='*90)
print(f'Missing Amount: Rs {218567.04 - float(gross_inflows):,.2f}')
print('\nThe salvage value calculation might be different.')
print(f'Current salvage in model: Rs {float(inv.salvage_value):,.2f}')

print('\n' + '='*90 + '\n')
