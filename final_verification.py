"""Final verification of all fixes for Jan-2025 investment"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import Session, create_engine, select
from models import Investment, InvestmentMetric
from decimal import Decimal

engine = create_engine('sqlite:///./wealth_tracker.db')

print('\n' + '='*90)
print('FINAL VERIFICATION - ALL FIXES FOR JAN-2025 INVESTMENT')
print('='*90)

with Session(engine) as session:
    inv = session.get(Investment, 1)
    m = session.exec(select(InvestmentMetric).where(InvestmentMetric.investment_id == 1)).first()
    
    print('\n📊 INVESTMENT PARAMETERS:')
    print(f'  Investment: {inv.name}')
    print(f'  Total Investment: Rs {float(inv.total_investment_value):,.2f}')
    print(f'  Installments: 2 × Rs {float(inv.installment_value):,.2f} at t=1,2')
    print(f'  Income: Rs 5,000/mo (months 1-12), Rs 6,000/mo (months 13-24)')
    print(f'  Salvage: Rs 86,567.04 at t=24')
    print(f'  Discount Rate: 11% p.a. → 0.873459% monthly')
    print(f'  Reinvestment Rate: 30% p.a. → 2.2122% monthly')
    
    print('\n' + '='*90)
    print('✅ CORRECTED METRICS')
    print('='*90)
    
    # Check each metric
    checks = [
        ('Total Inflows', float(m.total_inflows), 218567.04, 'Rs'),
        ('PV of Inflows', float(m.pv_inflows), 188315.19, 'Rs'),
        ('PV of Outflows', float(m.pv_outflows), 59337.44, 'Rs'),
        ('NPV', float(m.npv), 128977.75, 'Rs'),
        ('Profitability Index', float(m.profitability_index), 3.174, ''),
        ('IRR (annual)', float(m.irr_percent), 242.64, '%'),
        ('MIRR (annual)', float(m.mirr_percent), 120.20, '%'),
        ('Payback', float(m.payback_months), 12.0, 'months'),
        ('Discounted Payback', float(m.discounted_payback_months), 12.5, 'months'),
    ]
    
    all_pass = True
    for name, actual, expected, unit in checks:
        # Tolerance varies by metric
        if 'Inflow' in name or 'NPV' in name or 'Outflow' in name:
            tolerance = 10  # Rs 10
        elif 'PI' in name:
            tolerance = 0.01
        elif '%' in name:
            tolerance = 1  # 1%
        else:
            tolerance = 0.5  # 0.5 months
        
        diff = abs(actual - expected)
        passed = diff < tolerance
        all_pass = all_pass and passed
        
        status = '✅' if passed else '❌'
        if unit == 'Rs':
            print(f'  {status} {name:20s}: Rs {actual:>12,.2f} (expected Rs {expected:,.2f})')
        elif unit == '%':
            print(f'  {status} {name:20s}: {actual:>8,.2f}% (expected ~{expected:.2f}%)')
        elif unit == 'months':
            print(f'  {status} {name:20s}: {actual:>8,.2f} {unit} (expected ~{expected:.1f})')
        else:
            print(f'  {status} {name:20s}: {actual:>8,.3f} (expected {expected:.3f})')
    
    print(f'\n  ROI: {float(m.roi_percent):.2f}% (net deployed base)')
    
    print('\n' + '='*90)
    print('🔍 CALCULATION VERIFICATION')
    print('='*90)
    
    # Verify NPV
    npv_calc = m.pv_inflows - m.pv_outflows
    npv_match = abs(float(npv_calc) - float(m.npv)) < 1
    print(f'\n  NPV Calculation:')
    print(f'    PV(inflows) - PV(outflows) = Rs {float(m.pv_inflows):,.2f} - Rs {float(m.pv_outflows):,.2f}')
    print(f'                                = Rs {float(npv_calc):,.2f}')
    print(f'    Stored NPV                  = Rs {float(m.npv):,.2f}')
    print(f'    {"✅ MATCH" if npv_match else "❌ MISMATCH"}')
    
    # Verify PI
    pi_calc = m.pv_inflows / m.pv_outflows
    pi_match = abs(float(pi_calc) - float(m.profitability_index)) < 0.001
    print(f'\n  PI Calculation:')
    print(f'    PV(inflows) / PV(outflows) = Rs {float(m.pv_inflows):,.2f} / Rs {float(m.pv_outflows):,.2f}')
    print(f'                                = {float(pi_calc):.3f}')
    print(f'    Stored PI                   = {float(m.profitability_index):.3f}')
    print(f'    {"✅ MATCH" if pi_match else "❌ MISMATCH"}')
    
    # Verify inflows composition
    expected_income_y1 = Decimal("5000") * 12
    expected_income_y2 = Decimal("6000") * 12
    expected_salvage = Decimal("86567.04")
    expected_total = expected_income_y1 + expected_income_y2 + expected_salvage
    
    print(f'\n  Total Inflows Composition:')
    print(f'    Year 1 Income  (12 × Rs 5,000) = Rs {float(expected_income_y1):,.2f}')
    print(f'    Year 2 Income  (12 × Rs 6,000) = Rs {float(expected_income_y2):,.2f}')
    print(f'    Salvage Value                  = Rs {float(expected_salvage):,.2f}')
    print(f'    Expected Total                 = Rs {float(expected_total):,.2f}')
    print(f'    Actual Total                   = Rs {float(m.total_inflows):,.2f}')
    print(f'    Difference                     = Rs {float(m.total_inflows - expected_total):,.2f}')
    
    print('\n' + '='*90)
    if all_pass and npv_match and pi_match:
        print('🎉 ALL CALCULATIONS CORRECT - JAN-2025 INVESTMENT FULLY FIXED!')
    else:
        print('⚠️  Some metrics still need adjustment')
    print('='*90 + '\n')
