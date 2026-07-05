"""
Service layer for wealth tracking and valuation management
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlmodel import Session, select
from models import Asset, AssetValuation, MonthNetworth
from utils import (
    parse_year_month,
    prev_year_month,
    quantize_decimal,
    months_in_range
)
from config import (
    DONATION_PERCENTAGE,
    PERSONAL_EXP_PERCENTAGE,
    INVESTMENT_PERCENTAGE,
    DECIMAL_PLACES
)


class WealthService:
    """Service class for wealth tracking operations"""
    
    @staticmethod
    def upsert_valuation(
        session: Session,
        user_id: int,
        asset_id: int,
        year_month: str,
        value: Decimal
    ) -> AssetValuation:
        """
        Create or update a valuation for an asset in a specific month
        
        Args:
            session: Database session
            user_id: User ID
            asset_id: Asset ID
            year_month: Month in YYYY-MM format
            value: Valuation amount (can be negative for liabilities)
            
        Returns:
            AssetValuation object
            
        Raises:
            ValueError: If validation fails
        """
        # Validate year_month format
        parse_year_month(year_month)
        
        # Quantize value (negative values allowed for liabilities)
        value = quantize_decimal(value, DECIMAL_PLACES)
        
        # Check if valuation already exists
        existing = session.exec(
            select(AssetValuation)
            .where(AssetValuation.user_id == user_id)
            .where(AssetValuation.asset_id == asset_id)
            .where(AssetValuation.year_month == year_month)
        ).first()
        
        if existing:
            # Update existing valuation
            existing.value = value
            existing.updated_at = datetime.utcnow()
            session.add(existing)
            valuation = existing
        else:
            # Create new valuation
            valuation = AssetValuation(
                user_id=user_id,
                asset_id=asset_id,
                year_month=year_month,
                value=value,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(valuation)
        
        session.commit()
        session.refresh(valuation)
        
        # Recalculate month networth cache
        WealthService.recalc_month_networth_cache(session, user_id, year_month)
        
        return valuation
    
    @staticmethod
    def get_month_snapshot(session: Session, user_id: int, year_month: str) -> dict[int, Decimal]:
        """
        Get all asset valuations for a specific month
        
        Args:
            session: Database session
            user_id: User ID
            year_month: Month in YYYY-MM format
            
        Returns:
            Dictionary mapping asset_id to value
        """
        valuations = session.exec(
            select(AssetValuation)
            .where(AssetValuation.user_id == user_id)
            .where(AssetValuation.year_month == year_month)
        ).all()
        
        return {v.asset_id: v.value for v in valuations}
    
    @staticmethod
    def get_previous_month_snapshot(
        session: Session,
        user_id: int,
        year_month: str
    ) -> dict[int, Decimal]:
        """
        Get the snapshot from the latest month before the given month
        If no previous month exists, return empty dict
        
        Args:
            session: Database session
            user_id: User ID
            year_month: Current month in YYYY-MM format
            
        Returns:
            Dictionary mapping asset_id to value from previous month
        """
        # Get all months before current month
        months = WealthService.list_months(session, user_id)
        prev_months = [m for m in months if m < year_month]
        
        if not prev_months:
            return {}
        
        # Get the latest previous month
        latest_prev = max(prev_months)
        return WealthService.get_month_snapshot(session, user_id, latest_prev)
    
    @staticmethod
    def compute_changes(session: Session, user_id: int, year_month: str) -> dict:
        """
        Compute changes for all assets in a given month compared to previous month
        
        Args:
            session: Database session
            user_id: User ID
            year_month: Month in YYYY-MM format
            
        Returns:
            Dictionary with per-asset changes and totals
        """
        # Get current and previous month snapshots
        curr_snapshot = WealthService.get_month_snapshot(session, user_id, year_month)
        prev_snapshot = WealthService.get_previous_month_snapshot(session, user_id, year_month)
        
        # Get all assets involved
        all_asset_ids = set(curr_snapshot.keys()) | set(prev_snapshot.keys())
        
        # Fetch asset details
        assets = session.exec(
            select(Asset)
            .where(Asset.user_id == user_id)
            .where(Asset.id.in_(list(all_asset_ids)))
        ).all()
        
        asset_map = {a.id: a for a in assets}
        
        # Compute per-asset changes
        per_asset = []
        networth_curr = Decimal("0")
        networth_prev = Decimal("0")
        
        for asset_id in sorted(all_asset_ids):
            prev_val = quantize_decimal(prev_snapshot.get(asset_id, Decimal("0")))
            curr_val = quantize_decimal(curr_snapshot.get(asset_id, Decimal("0")))
            change = quantize_decimal(curr_val - prev_val)
            
            networth_curr += curr_val
            networth_prev += prev_val
            
            asset = asset_map.get(asset_id)
            asset_name = asset.name if asset else f"Unknown Asset {asset_id}"
            
            per_asset.append({
                "asset_id": asset_id,
                "asset_name": asset_name,
                "prev_value": prev_val,
                "curr_value": curr_val,
                "change": change
            })
        
        networth_change = quantize_decimal(networth_curr - networth_prev)
        
        # Calculate allocations based on total change (only if positive)
        if networth_change > 0:
            total_change = networth_change
            donation = quantize_decimal(total_change * Decimal(DONATION_PERCENTAGE) / 100)
            personal_exp = quantize_decimal(total_change * Decimal(PERSONAL_EXP_PERCENTAGE) / 100)
            investment = quantize_decimal(total_change * Decimal(INVESTMENT_PERCENTAGE) / 100)
        else:
            total_change = networth_change
            donation = Decimal("0")
            personal_exp = Decimal("0")
            investment = Decimal("0")
        
        return {
            "year_month": year_month,
            "per_asset": per_asset,
            "total_change": total_change,
            "donation": donation,
            "personal_exp": personal_exp,
            "investment": investment,
            "networth_prev": networth_prev,
            "networth_curr": networth_curr,
            "networth_change": networth_change
        }
    
    @staticmethod
    def list_months(session: Session, user_id: int) -> list[str]:
        """
        Get list of all months that have valuations, sorted ascending
        
        Args:
            session: Database session
            user_id: User ID
            
        Returns:
            List of YYYY-MM strings sorted
        """
        result = session.exec(
            select(AssetValuation.year_month)
            .where(AssetValuation.user_id == user_id)
            .distinct()
            .order_by(AssetValuation.year_month)
        ).all()
        
        return list(result)
    
    @staticmethod
    def range_stats(
        session: Session,
        user_id: int,
        start_month: Optional[str] = None,
        end_month: Optional[str] = None
    ) -> dict:
        """
        Calculate statistics for a range of months
        
        Args:
            session: Database session
            user_id: User ID
            start_month: Start month (inclusive), None for earliest
            end_month: End month (inclusive), None for latest
            
        Returns:
            Dictionary with months, networth_by_month, and avg_monthly_networth_gain
        """
        all_months = WealthService.list_months(session, user_id)
        
        if not all_months:
            return {
                "start_month": start_month,
                "end_month": end_month,
                "months": [],
                "networth_by_month": [],
                "avg_monthly_networth_gain": Decimal("0")
            }
        
        # Determine actual range
        if start_month is None:
            start_month = all_months[0]
        if end_month is None:
            end_month = all_months[-1]
        
        # Filter months in range
        months_in_range_list = [m for m in all_months if start_month <= m <= end_month]
        
        if not months_in_range_list:
            return {
                "start_month": start_month,
                "end_month": end_month,
                "months": [],
                "networth_by_month": [],
                "avg_monthly_networth_gain": Decimal("0")
            }
        
        # Calculate networth for each month
        networth_by_month = []
        for month in months_in_range_list:
            snapshot = WealthService.get_month_snapshot(session, user_id, month)
            networth = quantize_decimal(sum(snapshot.values(), Decimal("0")))
            networth_by_month.append({
                "month": month,
                "networth": networth
            })
        
        # Calculate average monthly gain
        if len(networth_by_month) >= 2:
            start_networth = networth_by_month[0]["networth"]
            end_networth = networth_by_month[-1]["networth"]
            num_gaps = len(networth_by_month) - 1  # Number of month transitions
            
            if num_gaps > 0:
                avg_gain = quantize_decimal((end_networth - start_networth) / num_gaps)
            else:
                avg_gain = Decimal("0")
        else:
            avg_gain = Decimal("0")
        
        return {
            "start_month": start_month,
            "end_month": end_month,
            "months": months_in_range_list,
            "networth_by_month": networth_by_month,
            "avg_monthly_networth_gain": avg_gain
        }
    
    @staticmethod
    def recalc_month_networth_cache(session: Session, user_id: int, year_month: str):
        """
        Recalculate and update the MonthNetworth cache for a specific month
        
        Args:
            session: Database session
            user_id: User ID
            year_month: Month in YYYY-MM format
        """
        snapshot = WealthService.get_month_snapshot(session, user_id, year_month)
        networth = quantize_decimal(sum(snapshot.values(), Decimal("0")))
        
        # Check if cache entry exists
        existing = session.exec(
            select(MonthNetworth)
            .where(MonthNetworth.user_id == user_id)
            .where(MonthNetworth.year_month == year_month)
        ).first()
        
        if existing:
            existing.networth = networth
            existing.updated_at = datetime.utcnow()
            session.add(existing)
        else:
            cache_entry = MonthNetworth(
                user_id=user_id,
                year_month=year_month,
                networth=networth,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(cache_entry)
        
        session.commit()
