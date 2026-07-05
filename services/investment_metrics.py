"""
Investment metrics calculation and persistence service
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from sqlmodel import Session, select
from models import Investment, InvestmentMetric
from services import fincalc


class InvestmentMetricsService:
    """Service for calculating and storing investment metrics"""
    
    @staticmethod
    def compute_and_save_metrics(session: Session, investment: Investment) -> InvestmentMetric:
        """
        Compute all financial metrics for an investment and persist them
        Calculates both project-level and equity-level metrics (if leveraged)
        """
        # Prepare custom leverage repayments if using custom schedule
        custom_leverage_repayments = None
        if investment.is_leveraged and investment.leverage_repayment_type == "custom_schedule":
            # Get custom repayments and convert to list of (amount, month) tuples
            custom_leverage_repayments = [
                (rep.amount, rep.repayment_month) 
                for rep in investment.leverage_repayments
            ]
        
        # Build PROJECT-LEVEL cash flow vector (includes leverage as inflow)
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
        
        # Convert discount rate to monthly
        discount_rate_monthly = fincalc.annual_to_monthly_rate(investment.discount_rate_annual_percent)
        reinvestment_rate_monthly = fincalc.annual_to_monthly_rate(investment.reinvestment_rate_annual_percent)
        
        # Calculate PROJECT-LEVEL metrics
        roi = fincalc.calculate_roi(cash_flows)
        npv = fincalc.calculate_npv(cash_flows, discount_rate_monthly)
        
        # Calculate PV of Outflows using GROSS investment costs (for PI and analysis)
        pv_outflows = fincalc.calculate_gross_pv_outflows(
            total_investment=investment.total_investment_value,
            installments=investment.installments,
            installment_value=investment.installment_value,
            installment_months=investment.installment_months,
            discount_rate_monthly=discount_rate_monthly,
            is_leveraged=False,  # Project metrics exclude leverage
            leverage_amount=None,
            leverage_repayment_type=None,
            leverage_repayment_months=None,
            custom_leverage_repayments=None
        )
        
        # Use GROSS inflows (total revenue before netting against costs)
        total_inflows = fincalc.calculate_gross_inflows(
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
        
        pv_inflows = fincalc.calculate_gross_pv_inflows(
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
        
        irr = fincalc.calculate_irr(cash_flows, horizon_months=investment.analysis_horizon_months)
        mirr = fincalc.calculate_mirr(cash_flows, discount_rate_monthly, reinvestment_rate_monthly)
        payback = fincalc.calculate_payback(cash_flows)
        discounted_payback = fincalc.calculate_discounted_payback(cash_flows, discount_rate_monthly)
        
        # Calculate PI using GROSS inflows / PV outflows
        pi = fincalc.calculate_profitability_index_gross(pv_inflows, pv_outflows)
        
        cagr = fincalc.calculate_cagr(cash_flows, investment.analysis_horizon_months)
        break_even = fincalc.calculate_break_even_units(
            investment.break_even_fixed_costs,
            investment.break_even_price_per_unit,
            investment.break_even_variable_cost_per_unit
        )
        
        # Calculate EQUITY-LEVEL metrics (if leveraged)
        equity_roi = None
        equity_npv = None
        equity_irr = None
        equity_mirr = None
        equity_pi = None
        equity_payback = None
        equity_discounted_payback = None
        
        if investment.is_leveraged and investment.leverage_amount and investment.leverage_amount > 0:
            # Build EQUITY cash flow (return on actual invested capital)
            equity_cash_flows = fincalc.build_equity_cash_flow(
                total_investment=investment.total_investment_value,
                leverage_amount=investment.leverage_amount,
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
                leverage_repayment_type=investment.leverage_repayment_type,
                leverage_repayment_months=investment.leverage_repayment_months,
                custom_leverage_repayments=custom_leverage_repayments,
                has_revenue=investment.has_revenue,
                revenue_amount=investment.revenue_amount,
                revenue_installment_months=investment.revenue_installment_months
            )
            
            # Calculate EQUITY metrics
            # For equity ROI, use actual equity invested as base (not total outflows which include loan repayments)
            equity_invested = investment.total_investment_value - investment.leverage_amount
            total_equity_inflows = sum(cf for cf in equity_cash_flows if cf > 0)
            total_equity_outflows = abs(sum(cf for cf in equity_cash_flows if cf < 0))
            net_equity_gain = total_equity_inflows - total_equity_outflows
            # Equity ROI = Net Gain / Equity Invested × 100
            equity_roi = (net_equity_gain / equity_invested) * Decimal("100") if equity_invested > 0 else None
            
            equity_npv = fincalc.calculate_npv(equity_cash_flows, discount_rate_monthly)
            equity_irr = fincalc.calculate_irr(equity_cash_flows, horizon_months=investment.analysis_horizon_months)
            equity_mirr = fincalc.calculate_mirr(equity_cash_flows, discount_rate_monthly, reinvestment_rate_monthly)
            equity_pi = fincalc.calculate_profitability_index(equity_cash_flows, discount_rate_monthly)
            equity_payback = fincalc.calculate_payback(equity_cash_flows)
            equity_discounted_payback = fincalc.calculate_discounted_payback(equity_cash_flows, discount_rate_monthly)
        
        # Check if metrics already exist
        existing = session.exec(
            select(InvestmentMetric)
            .where(InvestmentMetric.investment_id == investment.id)
        ).first()
        
        if existing:
            # Update existing with both project and equity metrics
            existing.roi_percent = roi
            existing.npv = npv
            existing.pv_inflows = pv_inflows
            existing.pv_outflows = pv_outflows
            existing.total_inflows = total_inflows
            existing.irr_percent = irr
            existing.mirr_percent = mirr
            existing.payback_months = payback
            existing.discounted_payback_months = discounted_payback
            existing.profitability_index = pi
            existing.cagr_percent = cagr
            existing.break_even_units = break_even
            existing.equity_roi_percent = equity_roi
            existing.equity_npv = equity_npv
            existing.equity_irr_percent = equity_irr
            existing.equity_mirr_percent = equity_mirr
            existing.equity_profitability_index = equity_pi
            existing.equity_payback_months = equity_payback
            existing.equity_discounted_payback_months = equity_discounted_payback
            existing.updated_at = datetime.utcnow()
            
            session.add(existing)
            session.commit()
            session.refresh(existing)
            
            return existing
        else:
            # Create new with both project and equity metrics
            metric = InvestmentMetric(
                investment_id=investment.id,
                user_id=investment.user_id,
                roi_percent=roi,
                npv=npv,
                pv_inflows=pv_inflows,
                pv_outflows=pv_outflows,
                total_inflows=total_inflows,
                irr_percent=irr,
                mirr_percent=mirr,
                payback_months=payback,
                discounted_payback_months=discounted_payback,
                profitability_index=pi,
                cagr_percent=cagr,
                break_even_units=break_even,
                equity_roi_percent=equity_roi,
                equity_npv=equity_npv,
                equity_irr_percent=equity_irr,
                equity_mirr_percent=equity_mirr,
                equity_profitability_index=equity_pi,
                equity_payback_months=equity_payback,
                equity_discounted_payback_months=equity_discounted_payback,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            session.add(metric)
            session.commit()
            session.refresh(metric)
            
            return metric
    
    @staticmethod
    def get_metrics(session: Session, investment_id: int) -> Optional[InvestmentMetric]:
        """Get metrics for an investment"""
        return session.exec(
            select(InvestmentMetric)
            .where(InvestmentMetric.investment_id == investment_id)
        ).first()
    
    @staticmethod
    def get_cash_flow_table(investment: Investment) -> List[Dict[str, Any]]:
        """
        Generate cash flow table for display
        Returns list of {month, inflow, outflow, net, discounted_net}
        """
        # Prepare custom leverage repayments if using custom schedule
        custom_leverage_repayments = None
        if investment.is_leveraged and investment.leverage_repayment_type == "custom_schedule":
            custom_leverage_repayments = [
                (rep.amount, rep.repayment_month) 
                for rep in investment.leverage_repayments
            ]
        
        # Get separate inflows and outflows
        inflows, outflows = fincalc.build_cash_flow_detailed(
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
        
        table = []
        total_inflow = Decimal("0")
        total_outflow = Decimal("0")
        total_net = Decimal("0")
        total_discounted = Decimal("0")
        
        for t in range(len(inflows)):
            net_cf = inflows[t] - outflows[t]
            
            if discount_rate_monthly == 0:
                discounted = net_cf
            else:
                discounted = net_cf / ((Decimal("1") + discount_rate_monthly) ** Decimal(t))
            
            table.append({
                "month": t,
                "inflow": inflows[t],
                "outflow": outflows[t],
                "net": net_cf,
                "discounted_net": discounted
            })
            
            # Accumulate totals
            total_inflow += inflows[t]
            total_outflow += outflows[t]
            total_net += net_cf
            total_discounted += discounted
        
        # Add totals row
        table.append({
            "month": "TOTAL",
            "inflow": total_inflow,
            "outflow": total_outflow,
            "net": total_net,
            "discounted_net": total_discounted
        })
        
        return table
