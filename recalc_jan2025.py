"""Recalculate metrics for Jan-2025 investment with all fixes"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import Session, create_engine, select
from models import Investment, InvestmentMetric
from services.investment_metrics import InvestmentMetricsService

engine = create_engine('sqlite:///./wealth_tracker.db')

with Session(engine) as session:
    inv = session.get(Investment, 1)
    
    print('\n' + '='*80)
    print('RECALCULATING METRICS FOR JAN-2025 INVESTMENT')
    print('='*80)
    
    # Recalculate
    metrics = InvestmentMetricsService.compute_and_save_metrics(session, inv)
    
    print('\n  UPDATED METRICS:')
    print(f'  Total Inflows: Rs {float(metrics.total_inflows):,.2f} (Expected: Rs 218,567.04)')
    print(f'  PV of Inflows: Rs {float(metrics.pv_inflows):,.2f} (Expected: Rs 188,315.19)')
    print(f'  PV of Outflows: Rs {float(metrics.pv_outflows):,.2f} (Expected: Rs 59,337.44)')
    print(f'  NPV: Rs {float(metrics.npv):,.2f} (Expected: Rs 128,977.75)')
    print(f'  Profitability Index: {float(metrics.profitability_index):.3f} (Expected: 3.174)')
    print(f'  ROI: {float(metrics.roi_percent):.2f}%')
    print(f'  IRR: {float(metrics.irr_percent):.2f}% (Expected: ~242.64%)')
    print(f'  MIRR: {float(metrics.mirr_percent):.2f}% (Expected: ~120.20%)')
    print(f'  Payback: {float(metrics.payback_months):.2f} months (Expected: ~12.0)')
    print(f'  Discounted Payback: {float(metrics.discounted_payback_months):.2f} months (Expected: ~12.5)')
    
    print('\n' + '='*80)
    print('VERIFICATION:')
    print('='*80)
    
    # Check calculations
    total_inflows_match = abs(float(metrics.total_inflows) - 218567.04) < 10
    pv_inflows_match = abs(float(metrics.pv_inflows) - 188315.19) < 10
    pv_outflows_match = abs(float(metrics.pv_outflows) - 59337.44) < 10
    npv_match = abs(float(metrics.npv) - 128977.75) < 10
    pi_match = abs(float(metrics.profitability_index) - 3.174) < 0.01
    irr_match = abs(float(metrics.irr_percent) - 242.64) < 1
    mirr_match = abs(float(metrics.mirr_percent) - 120.20) < 1
    
    print(f'  Total Inflows: {"✓ PASS" if total_inflows_match else "✗ FAIL"}')
    print(f'  PV Inflows: {"✓ PASS" if pv_inflows_match else "✗ FAIL"}')
    print(f'  PV Outflows: {"✓ PASS" if pv_outflows_match else "✗ FAIL"}')
    print(f'  NPV: {"✓ PASS" if npv_match else "✗ FAIL"}')
    print(f'  PI: {"✓ PASS" if pi_match else "✗ FAIL"}')
    print(f'  IRR: {"✓ PASS" if irr_match else "✗ FAIL"}')
    print(f'  MIRR: {"✓ PASS" if mirr_match else "✗ FAIL"}')
    
    print('\n' + '='*80)
    print('MANUAL VERIFICATION:')
    print('='*80)
    print(f'  NPV = PV(inflows) - PV(outflows)')
    print(f'      = Rs {float(metrics.pv_inflows):,.2f} - Rs {float(metrics.pv_outflows):,.2f}')
    print(f'      = Rs {float(metrics.pv_inflows - metrics.pv_outflows):,.2f}')
    print(f'  Stored NPV: Rs {float(metrics.npv):,.2f}')
    print(f'  Match: {"✓ YES" if abs(float(metrics.npv) - float(metrics.pv_inflows - metrics.pv_outflows)) < 1 else "✗ NO"}')
    
    print(f'\n  PI = PV(inflows) / PV(outflows)')
    print(f'     = Rs {float(metrics.pv_inflows):,.2f} / Rs {float(metrics.pv_outflows):,.2f}')
    print(f'     = {float(metrics.pv_inflows / metrics.pv_outflows):.3f}')
    print(f'  Stored PI: {float(metrics.profitability_index):.3f}')
    print(f'  Match: {"✓ YES" if abs(float(metrics.profitability_index) - float(metrics.pv_inflows / metrics.pv_outflows)) < 0.001 else "✗ NO"}')
    
    print('\n' + '='*80 + '\n')
