"""Update investment metrics with corrected gross inflows calculations"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import Session, create_engine
from models import Investment
from services.investment_metrics import InvestmentMetricsService

# Create engine
DATABASE_URL = "sqlite:///./wealth_tracker.db"
engine = create_engine(DATABASE_URL)

def update_investment_metrics(investment_id: int):
    """Recalculate and update metrics for an investment"""
    with Session(engine) as session:
        investment = session.get(Investment, investment_id)
        if not investment:
            print(f"Investment {investment_id} not found")
            return
        
        print(f"\n{'='*70}")
        print(f"UPDATING METRICS FOR INVESTMENT: {investment.name}")
        print(f"{'='*70}")
        
        # Recalculate metrics
        metrics = InvestmentMetricsService.compute_and_save_metrics(session, investment)
        
        print(f"\nUPDATED PROJECT METRICS:")
        print(f"  Total Inflows: Rs {metrics.total_inflows:,.2f}")
        print(f"  PV of Inflows: Rs {metrics.pv_inflows:,.2f}")
        print(f"  NPV: Rs {metrics.npv:,.2f}")
        print(f"  ROI: {metrics.roi_percent:.2f}%")
        print(f"  IRR: {metrics.irr_percent:.2f}%")
        print(f"  Payback: {metrics.payback_months:.2f} months")
        
        if metrics.equity_roi_percent:
            print(f"\nUPDATED EQUITY METRICS:")
            print(f"  Equity ROI: {metrics.equity_roi_percent:.2f}%")
            print(f"  Equity NPV: Rs {metrics.equity_npv:,.2f}")
            print(f"  Equity IRR: {metrics.equity_irr_percent:.2f}%")
            print(f"  Equity Payback: {metrics.equity_payback_months:.2f} months")
        
        print(f"\n{'='*70}")
        print("Metrics updated successfully in database!")
        print(f"{'='*70}\n")

if __name__ == "__main__":
    # Update investment 2 (Solar investment)
    update_investment_metrics(2)
