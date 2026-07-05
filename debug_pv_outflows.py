"""Debug PV Outflows calculation"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from decimal import Decimal
from sqlmodel import Session, create_engine
from models import Investment
from services import fincalc

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

discount_rate_monthly = fincalc.annual_to_monthly_rate(inv.discount_rate_annual_percent)

print('\n' + '='*90)
print('PV OUTFLOWS DEBUG')
print('='*90)

print(f'\nDiscount Rate:')
print(f'  Annual: {float(inv.discount_rate_annual_percent)}%')
print(f'  Monthly: {float(discount_rate_monthly * Decimal("100")):.6f}%')
print(f'  Monthly factor: {float(discount_rate_monthly):.8f}')

print(f'\nCash Flow Analysis (first 5 months):')
pv_outflows_manual = Decimal("0")
for t in range(5):
    cf = cash_flows[t]
    if cf < 0:
        disc_factor = (Decimal("1") + discount_rate_monthly) ** Decimal(t)
        pv_cf = abs(cf) / disc_factor
        pv_outflows_manual += pv_cf
        print(f'  Month {t}: CF = Rs {float(cf):,.2f}, PV = Rs {float(pv_cf):,.2f}')
    else:
        print(f'  Month {t}: CF = Rs {float(cf):,.2f} (inflow - not counted)')

# Calculate using function
pv_outflows_func = fincalc.calculate_pv_outflows(cash_flows, discount_rate_monthly)

print(f'\nPV Outflows Calculation:')
print(f'  Manual (months 1-2): Rs {float(pv_outflows_manual):,.2f}')
print(f'  Via function: Rs {float(pv_outflows_func):,.2f}')

print(f'\nExpected PV Outflows:')
r_m = Decimal("0.0087346")
pv1 = Decimal("30058") / (Decimal("1") + r_m)
pv2 = Decimal("30058") / ((Decimal("1") + r_m) ** 2)
print(f'  t=1: Rs 30,058 / {float(Decimal("1") + r_m):.8f} = Rs {float(pv1):,.2f}')
print(f'  t=2: Rs 30,058 / {float((Decimal("1") + r_m) ** 2):.8f} = Rs {float(pv2):,.2f}')
print(f'  Total: Rs {float(pv1 + pv2):,.2f}')

print('\n' + '='*90)
print('ISSUE DIAGNOSIS:')
print('='*90)
print(f'The cash flows at t=1 and t=2 are NET (installment - income):')
print(f'  Month 1: -Rs 30,058 + Rs 4,999.85 = Rs {float(cash_flows[1]):,.2f}')
print(f'  Month 2: -Rs 30,058 + Rs 4,999.85 = Rs {float(cash_flows[2]):,.2f}')
print(f'\nPV Outflows function is discounting the NET negative flows, not the gross installments!')
print(f'For the expected calculation, we need to track the gross installments separately.')

print('\n' + '='*90 + '\n')
