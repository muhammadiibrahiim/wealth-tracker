"""Check Jan-2025 Investment Parameters and Metrics"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import create_engine, Session, select
from models import Investment, InvestmentMetric
from decimal import Decimal

engine = create_engine('sqlite:///./wealth_tracker.db')
session = Session(engine)

inv = session.get(Investment, 1)
m = session.exec(select(InvestmentMetric).where(InvestmentMetric.investment_id == 1)).first()

print('\n' + '='*70)
print('JAN-2025 INVESTMENT (ID 1) - CURRENT STATE')
print('='*70)

print('\nINVESTMENT PARAMETERS:')
print(f'  Name: {inv.name}')
print(f'  Total Investment: Rs {float(inv.total_investment_value):,.2f}')
print(f'  Installments: {inv.installments}')
print(f'  Installment Value: Rs {float(inv.installment_value):,.2f}')
print(f'  Installment Months: {inv.installment_months}')
print(f'  Gain in Income %: {float(inv.gain_in_income_percent) if inv.gain_in_income_percent else "N/A"}')
print(f'  Cadence: {inv.cadence}')
print(f'  Income Increases: {inv.income_increases}')
print(f'  Income Increase Rate %: {float(inv.income_increase_rate_percent) if inv.income_increase_rate_percent else "N/A"}')
print(f'  Income Increase Cadence: {inv.income_increase_cadence}')
print(f'  Salvage Value: Rs {float(inv.salvage_value):,.2f}')
print(f'  Discount Rate: {float(inv.discount_rate_annual_percent)}%')
print(f'  Reinvestment Rate: {float(inv.reinvestment_rate_annual_percent)}%')
print(f'  Horizon: {inv.analysis_horizon_months} months')

print('\nCURRENT METRICS:')
print(f'  Total Inflows: Rs {float(m.total_inflows):,.2f} (Expected: Rs 218,567.04)')
print(f'  PV of Inflows: Rs {float(m.pv_inflows):,.2f} (Expected: Rs 188,315.19)')
print(f'  NPV: Rs {float(m.npv):,.2f} (Expected: Rs 128,977.75)')
print(f'  ROI: {float(m.roi_percent):.2f}%')
print(f'  IRR: {float(m.irr_percent):.2f}% (Expected: ~242.64%)')
print(f'  MIRR: {float(m.mirr_percent):.2f}% (Expected: ~120.20%)')
print(f'  PI: {float(m.profitability_index):.3f} (Expected: 3.174)')
print(f'  Payback: {float(m.payback_months):.2f} months (Expected: ~12.0)')
print(f'  Discounted Payback: {float(m.discounted_payback_months):.2f} months (Expected: ~12.5)')

print('\nEXPECTED CASH FLOWS:')
print('  Months 1-2: Installments of Rs 30,058 each (outflows)')
print('  Months 1-12: Income Rs 5,000 per month')
print('  Months 13-24: Income Rs 6,000 per month')
print('  Month 24: Salvage Rs 86,567.04')

print('\nEXPECTED TOTALS:')
print('  Total Inflows = 12×5,000 + 12×6,000 + 86,567.04 = Rs 218,567.04')
print('  Total Outflows = 2×30,058 = Rs 60,116')

print('\n' + '='*70 + '\n')
