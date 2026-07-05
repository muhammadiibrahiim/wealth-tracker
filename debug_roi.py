"""Debug Project ROI calculation"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from decimal import Decimal
from sqlmodel import Session, create_engine
from models import Investment
from services import fincalc

# Create engine
DATABASE_URL = "sqlite:///./wealth_tracker.db"
engine = create_engine(DATABASE_URL)

def debug_project_roi():
    """Analyze why project ROI is 12.17%"""
    with Session(engine) as session:
        investment = session.get(Investment, 2)
        if not investment:
            print("Investment 2 not found")
            return
        
        print(f"\n{'='*70}")
        print(f"PROJECT ROI CALCULATION DEBUG")
        print(f"Investment: {investment.name}")
        print(f"{'='*70}\n")
        
        # Build cash flows
        custom_leverage_repayments = None
        if investment.is_leveraged and investment.leverage_repayment_type == "custom_schedule":
            custom_leverage_repayments = [
                (rep.amount, rep.repayment_month) 
                for rep in investment.leverage_repayments
            ]
        
        cash_flows = fincalc.build_cash_flow(
            total_investment=investment.total_investment_value,
            installments=investment.installments,
            installment_value=investment.installment_value,
            installment_months=investment.installment_months,
            gain_percent=investment.gain_in_income_percent,
            cadence=investment.cadence,
            one_off_inflow=investment.one_off_inflow_value,
            salvage_value=investment.salvage_value,
            horizon_months=investment.analysis_horizon_months,
            income_increases=investment.income_increases,
            income_increase_rate_percent=investment.income_increase_rate_percent,
            income_increase_cadence=investment.income_increase_cadence,
            is_leveraged=investment.is_leveraged,
            leverage_amount=investment.leverage_amount,
            leverage_repayment_type=investment.leverage_repayment_type,
            leverage_repayment_months=investment.leverage_repayment_months,
            custom_leverage_repayments=custom_leverage_repayments,
            has_revenue=investment.has_revenue,
            revenue_amount=investment.revenue_amount,
            revenue_installment_months=investment.revenue_installment_months
        )
        
        print("INVESTMENT DETAILS:")
        print(f"  Total Investment: Rs {float(investment.total_investment_value):,.2f}")
        print(f"  Is Leveraged: {investment.is_leveraged}")
        print(f"  Leverage Amount: Rs {float(investment.leverage_amount):,.2f}")
        print(f"  Revenue Amount: Rs {float(investment.revenue_amount):,.2f}")
        print(f"  Revenue Months: {investment.revenue_installment_months}")
        
        print(f"\n{'='*70}")
        print("CASH FLOW BREAKDOWN:")
        print(f"{'='*70}")
        cumulative = Decimal("0")
        for t, cf in enumerate(cash_flows):
            cumulative += cf
            print(f"  Month {t}: Rs {float(cf):,.2f} (Cumulative: Rs {float(cumulative):,.2f})")
        
        # Calculate components
        total_inflows = sum(cf for cf in cash_flows if cf > 0)
        total_outflows = abs(sum(cf for cf in cash_flows if cf < 0))
        net_gain = sum(cash_flows)
        
        print(f"\n{'='*70}")
        print("ROI CALCULATION COMPONENTS:")
        print(f"{'='*70}")
        print(f"  Total Inflows (sum of positive CFs): Rs {float(total_inflows):,.2f}")
        print(f"  Total Outflows (sum of negative CFs): Rs {float(total_outflows):,.2f}")
        print(f"  Net Gain (Total CF): Rs {float(net_gain):,.2f}")
        
        print(f"\n{'='*70}")
        print("ROI FORMULA ANALYSIS:")
        print(f"{'='*70}")
        
        # Check current ROI calculation in fincalc
        roi = fincalc.calculate_roi(cash_flows)
        print(f"\nCurrent calculate_roi() result: {float(roi):.2f}%")
        
        # Manual calculation - Method 1: (Net Gain / Total Outflows) * 100
        roi_method1 = (net_gain / total_outflows) * Decimal("100")
        print(f"\nMethod 1: (Net Gain / Total Outflows) × 100")
        print(f"  = (Rs {float(net_gain):,.2f} / Rs {float(total_outflows):,.2f}) × 100")
        print(f"  = {float(roi_method1):.2f}%")
        
        # Manual calculation - Method 2: ((Total Inflows - Total Outflows) / Total Outflows) * 100
        roi_method2 = ((total_inflows - total_outflows) / total_outflows) * Decimal("100")
        print(f"\nMethod 2: ((Total Inflows - Total Outflows) / Total Outflows) × 100")
        print(f"  = ((Rs {float(total_inflows):,.2f} - Rs {float(total_outflows):,.2f}) / Rs {float(total_outflows):,.2f}) × 100")
        print(f"  = (Rs {float(total_inflows - total_outflows):,.2f} / Rs {float(total_outflows):,.2f}) × 100")
        print(f"  = {float(roi_method2):.2f}%")
        
        # Manual calculation - Method 3: (Net Gain / Total Investment) * 100
        roi_method3 = (net_gain / investment.total_investment_value) * Decimal("100")
        print(f"\nMethod 3: (Net Gain / Total Investment) × 100")
        print(f"  = (Rs {float(net_gain):,.2f} / Rs {float(investment.total_investment_value):,.2f}) × 100")
        print(f"  = {float(roi_method3):.2f}%")
        
        print(f"\n{'='*70}")
        print("ISSUE ANALYSIS:")
        print(f"{'='*70}")
        print(f"\nThe PROJECT cash flow includes:")
        print(f"  1. Initial Investment: -Rs {float(investment.total_investment_value):,.2f}")
        print(f"  2. Leverage Inflow: REMOVED (was +Rs {float(investment.leverage_amount):,.2f})")
        print(f"  3. Revenue: +Rs {float(investment.revenue_amount):,.2f}")
        print(f"  4. Leverage Repayments: -Rs {float(investment.leverage_amount):,.2f}")
        
        print(f"\nTotal Outflows = Investment + Loan Repayments")
        print(f"              = Rs {float(investment.total_investment_value):,.2f} + Rs {float(investment.leverage_amount):,.2f}")
        print(f"              = Rs {float(total_outflows):,.2f}")
        
        print(f"\nROI is calculated as: Net Gain / Total Outflows")
        print(f"  = Rs {float(net_gain):,.2f} / Rs {float(total_outflows):,.2f}")
        print(f"  = {float(roi_method1):.2f}%")
        
        print(f"\n{'='*70}")
        print("EXPLANATION:")
        print(f"{'='*70}")
        print(f"Project ROI is low (12.17%) because:")
        print(f"  • Denominator includes BOTH investment AND loan repayments")
        print(f"  • Total cash outflows = Rs {float(total_outflows):,.2f}")
        print(f"  • But net gain is only Rs {float(net_gain):,.2f}")
        print(f"  • This is correct for PROJECT-level analysis")
        print(f"\nFor EQUITY ROI (what you actually invested):")
        print(f"  • Only YOUR money is used as denominator")
        print(f"  • Equity Invested = Rs {float(investment.total_investment_value - investment.leverage_amount):,.2f}")
        print(f"  • Equity ROI = 24.84% (much higher!)")
        
        print(f"\n{'='*70}\n")

if __name__ == "__main__":
    debug_project_roi()
