"""Verify the inflows calculation fix"""
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

def verify_inflows_fix():
    """Compare old (net positive CFs) vs new (gross revenue) inflows calculations"""
    with Session(engine) as session:
        investment = session.get(Investment, 2)
        if not investment:
            print("Investment 2 not found")
            return
        
        print(f"\n{'='*70}")
        print(f"INFLOWS CALCULATION VERIFICATION")
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
        
        discount_rate_monthly = fincalc.annual_to_monthly_rate(investment.discount_rate_annual_percent)
        
        # OLD METHOD: Sum of NET positive cash flows
        old_total_inflows = sum(cf for cf in cash_flows if cf > 0)
        old_pv_inflows = Decimal("0")
        for t, cf_t in enumerate(cash_flows):
            if cf_t > 0:
                if discount_rate_monthly == 0:
                    old_pv_inflows += cf_t
                else:
                    old_pv_inflows += cf_t / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
        
        # NEW METHOD: GROSS revenue inflows
        new_total_inflows = fincalc.calculate_gross_inflows(
            has_revenue=investment.has_revenue,
            revenue_amount=investment.revenue_amount,
            gain_percent=investment.gain_in_income_percent,
            total_investment=investment.total_investment_value,
            cadence=investment.cadence,
            horizon_months=investment.analysis_horizon_months,
            one_off_inflow=investment.one_off_inflow_value,
            salvage_value=investment.salvage_value,
            income_increases=investment.income_increases,
            income_increase_rate_percent=investment.income_increase_rate_percent,
            income_increase_cadence=investment.income_increase_cadence
        )
        
        new_pv_inflows = fincalc.calculate_gross_pv_inflows(
            has_revenue=investment.has_revenue,
            revenue_amount=investment.revenue_amount,
            revenue_installment_months=investment.revenue_installment_months,
            gain_percent=investment.gain_in_income_percent,
            total_investment=investment.total_investment_value,
            cadence=investment.cadence,
            horizon_months=investment.analysis_horizon_months,
            one_off_inflow=investment.one_off_inflow_value,
            salvage_value=investment.salvage_value,
            discount_rate_monthly=discount_rate_monthly,
            income_increases=investment.income_increases,
            income_increase_rate_percent=investment.income_increase_rate_percent,
            income_increase_cadence=investment.income_increase_cadence
        )
        
        print("INVESTMENT DETAILS:")
        print(f"  Revenue Amount: Rs {float(investment.revenue_amount):,.2f}")
        print(f"  Revenue Installment Months: {investment.revenue_installment_months}")
        print(f"  Monthly Revenue: Rs {float(investment.revenue_amount / investment.revenue_installment_months):,.2f}")
        print(f"  Total Investment: Rs {float(investment.total_investment_value):,.2f}")
        print(f"  Discount Rate (annual): {float(investment.discount_rate_annual_percent):.2f}%")
        
        print(f"\n{'='*70}")
        print("CASH FLOW ANALYSIS:")
        print(f"{'='*70}")
        print(f"  Month 1 CF: Rs {float(cash_flows[0]):,.2f} (Investment + Revenue)")
        print(f"  Months 2-7 CF: Rs {float(cash_flows[1]):,.2f} each (Pure Revenue)")
        print(f"  Number of positive CF months: {sum(1 for cf in cash_flows if cf > 0)}")
        
        print(f"\n{'='*70}")
        print("OLD METHOD (Net Positive Cash Flows):")
        print(f"{'='*70}")
        print(f"  Total Inflows: Rs {float(old_total_inflows):,.2f}")
        print(f"  PV of Inflows: Rs {float(old_pv_inflows):,.2f}")
        print(f"  Issue: Excludes month 1 revenue (Rs {float(investment.revenue_amount / investment.revenue_installment_months):,.2f})")
        print(f"         because net CF is negative after investment")
        
        print(f"\n{'='*70}")
        print("NEW METHOD (Gross Revenue Inflows):")
        print(f"{'='*70}")
        print(f"  Total Inflows: Rs {float(new_total_inflows):,.2f}")
        print(f"  PV of Inflows: Rs {float(new_pv_inflows):,.2f}")
        print(f"  Includes: All 7 months of revenue")
        
        print(f"\n{'='*70}")
        print("COMPARISON:")
        print(f"{'='*70}")
        print(f"  Total Inflows Difference: Rs {float(new_total_inflows - old_total_inflows):,.2f}")
        print(f"  PV Inflows Difference: Rs {float(new_pv_inflows - old_pv_inflows):,.2f}")
        print(f"  % Increase in Total Inflows: {float((new_total_inflows - old_total_inflows) / old_total_inflows * 100):.2f}%")
        print(f"  % Increase in PV Inflows: {float((new_pv_inflows - old_pv_inflows) / old_pv_inflows * 100):.2f}%")
        
        print(f"\n{'='*70}")
        print("VERIFICATION:")
        print(f"{'='*70}")
        expected_total = investment.revenue_amount
        expected_monthly = investment.revenue_amount / investment.revenue_installment_months
        print(f"  Expected Total Inflows: Rs {float(expected_total):,.2f}")
        print(f"  Actual Total Inflows: Rs {float(new_total_inflows):,.2f}")
        print(f"  Match: {'✓ YES' if abs(new_total_inflows - expected_total) < Decimal('0.01') else '✗ NO'}")
        print(f"\n  Missing from old calculation: Rs {float(expected_monthly):,.2f} (1 month)")
        print(f"  This is exactly the month 1 revenue that was netted against investment")
        print(f"\n{'='*70}\n")

if __name__ == "__main__":
    verify_inflows_fix()
