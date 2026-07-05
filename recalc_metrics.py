"""Script to recalculate metrics for an investment"""
from database import get_session
from services.investments import InvestmentService
from services.investment_metrics import InvestmentMetricsService

def recalculate_investment_metrics(investment_id: int, user_id: int = 1):
    """Recalculate metrics for a specific investment"""
    session = next(get_session())
    try:
        # Get the investment
        inv = InvestmentService.get_investment(session, user_id, investment_id)
        if not inv:
            print(f"Investment {investment_id} not found")
            return
        
        # Recalculate metrics
        metrics = InvestmentMetricsService.compute_and_save_metrics(session, inv)
        
        print(f"✅ Metrics recalculated for '{inv.name}'")
        print(f"ROI: {metrics.roi_percent}%")
        print(f"NPV: Rs {metrics.npv}")
        print(f"Total Inflows: Rs {metrics.total_inflows}")
        print(f"PV Inflows: Rs {metrics.pv_inflows}")
        print(f"IRR: {metrics.irr_percent}%")
        print(f"MIRR: {metrics.mirr_percent}%")
        print(f"Payback: {metrics.payback_months} months")
        print(f"Discounted Payback: {metrics.discounted_payback_months} months")
        print(f"PI: {metrics.profitability_index}")
        print(f"CAGR: {metrics.cagr_percent}%")
        
    finally:
        session.close()

if __name__ == "__main__":
    recalculate_investment_metrics(1)
