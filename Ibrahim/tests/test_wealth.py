"""
Tests for wealth service and valuation logic
"""
import pytest
from decimal import Decimal
from sqlmodel import Session
from services.assets import AssetService
from services.wealth import WealthService


def test_upsert_valuation(session: Session):
    """Test creating and updating a valuation"""
    asset = AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    # Create valuation
    valuation = WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id, 
        year_month="2024-01", value=Decimal("1000.00")
    )
    
    assert valuation.asset_id == asset.id
    assert valuation.year_month == "2024-01"
    assert valuation.value == Decimal("1000.00")
    
    # Update valuation
    updated = WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-01", value=Decimal("1500.00")
    )
    
    assert updated.id == valuation.id
    assert updated.value == Decimal("1500.00")


def test_valuation_negative_value_allowed(session: Session):
    """Test that negative valuations are allowed (for liabilities/debts)"""
    asset = AssetService.create_asset(session, user_id=1, name="Credit Card Debt")
    
    # Should not raise an error
    valuation = WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-01", value=Decimal("-100.00")
    )
    
    assert valuation.value == Decimal("-100.00")
    assert valuation.asset_id == asset.id


def test_get_month_snapshot(session: Session):
    """Test retrieving month snapshot"""
    asset1 = AssetService.create_asset(session, user_id=1, name="Asset 1")
    asset2 = AssetService.create_asset(session, user_id=1, name="Asset 2")
    
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset1.id,
        year_month="2024-01", value=Decimal("1000.00")
    )
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset2.id,
        year_month="2024-01", value=Decimal("2000.00")
    )
    
    snapshot = WealthService.get_month_snapshot(session, user_id=1, year_month="2024-01")
    
    assert len(snapshot) == 2
    assert snapshot[asset1.id] == Decimal("1000.00")
    assert snapshot[asset2.id] == Decimal("2000.00")


def test_compute_changes_first_month(session: Session):
    """Test computing changes for first month (no previous data)"""
    asset = AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-01", value=Decimal("1000.00")
    )
    
    changes = WealthService.compute_changes(session, user_id=1, year_month="2024-01")
    
    assert changes["networth_curr"] == Decimal("1000.00")
    assert changes["networth_prev"] == Decimal("0.00")
    assert changes["networth_change"] == Decimal("1000.00")
    assert changes["total_change"] == Decimal("1000.00")
    assert changes["donation"] == Decimal("100.00")  # 10%
    assert changes["personal_exp"] == Decimal("200.00")  # 20%
    assert changes["investment"] == Decimal("700.00")  # 70%


def test_compute_changes_with_previous_month(session: Session):
    """Test computing changes with previous month data"""
    asset = AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    # Previous month
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-01", value=Decimal("1000.00")
    )
    
    # Current month
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-02", value=Decimal("1500.00")
    )
    
    changes = WealthService.compute_changes(session, user_id=1, year_month="2024-02")
    
    assert len(changes["per_asset"]) == 1
    assert changes["per_asset"][0]["prev_value"] == Decimal("1000.00")
    assert changes["per_asset"][0]["curr_value"] == Decimal("1500.00")
    assert changes["per_asset"][0]["change"] == Decimal("500.00")
    assert changes["networth_change"] == Decimal("500.00")


def test_compute_changes_negative_change(session: Session):
    """Test computing changes with negative growth"""
    asset = AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-01", value=Decimal("1000.00")
    )
    
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-02", value=Decimal("800.00")
    )
    
    changes = WealthService.compute_changes(session, user_id=1, year_month="2024-02")
    
    assert changes["networth_change"] == Decimal("-200.00")
    assert changes["total_change"] == Decimal("-200.00")
    # No allocation for negative change
    assert changes["donation"] == Decimal("0.00")
    assert changes["personal_exp"] == Decimal("0.00")
    assert changes["investment"] == Decimal("0.00")


def test_list_months(session: Session):
    """Test listing all months with data"""
    asset = AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-01", value=Decimal("1000.00")
    )
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-03", value=Decimal("1100.00")
    )
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-02", value=Decimal("1050.00")
    )
    
    months = WealthService.list_months(session, user_id=1)
    
    assert months == ["2024-01", "2024-02", "2024-03"]


def test_range_stats(session: Session):
    """Test calculating range statistics"""
    asset = AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    # Create 3 months of data
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-01", value=Decimal("1000.00")
    )
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-02", value=Decimal("1200.00")
    )
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-03", value=Decimal("1400.00")
    )
    
    stats = WealthService.range_stats(session, user_id=1, start_month="2024-01", end_month="2024-03")
    
    assert len(stats["months"]) == 3
    assert len(stats["networth_by_month"]) == 3
    assert stats["networth_by_month"][0]["networth"] == Decimal("1000.00")
    assert stats["networth_by_month"][-1]["networth"] == Decimal("1400.00")
    
    # Average monthly gain = (1400 - 1000) / 2 = 200
    assert stats["avg_monthly_networth_gain"] == Decimal("200.00")


def test_range_stats_all_time(session: Session):
    """Test range statistics with no specified range"""
    asset = AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-01", value=Decimal("1000.00")
    )
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-02", value=Decimal("1500.00")
    )
    
    stats = WealthService.range_stats(session, user_id=1)
    
    assert stats["start_month"] == "2024-01"
    assert stats["end_month"] == "2024-02"
    assert stats["avg_monthly_networth_gain"] == Decimal("500.00")


def test_month_networth_cache(session: Session):
    """Test that month networth cache is updated"""
    asset = AssetService.create_asset(session, user_id=1, name="Test Asset")
    
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset.id,
        year_month="2024-01", value=Decimal("1000.00")
    )
    
    # Cache should be created automatically
    from models import MonthNetworth
    from sqlmodel import select
    
    cache = session.exec(
        select(MonthNetworth)
        .where(MonthNetworth.user_id == 1)
        .where(MonthNetworth.year_month == "2024-01")
    ).first()
    
    assert cache is not None
    assert cache.networth == Decimal("1000.00")


def test_compute_changes_missing_asset_in_previous_month(session: Session):
    """Test that missing assets in previous month are treated as 0"""
    asset1 = AssetService.create_asset(session, user_id=1, name="Asset 1")
    asset2 = AssetService.create_asset(session, user_id=1, name="Asset 2")
    
    # Only asset1 in first month
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset1.id,
        year_month="2024-01", value=Decimal("1000.00")
    )
    
    # Both assets in second month
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset1.id,
        year_month="2024-02", value=Decimal("1200.00")
    )
    WealthService.upsert_valuation(
        session, user_id=1, asset_id=asset2.id,
        year_month="2024-02", value=Decimal("500.00")
    )
    
    changes = WealthService.compute_changes(session, user_id=1, year_month="2024-02")
    
    # Find asset2 in changes
    asset2_change = next(a for a in changes["per_asset"] if a["asset_id"] == asset2.id)
    
    assert asset2_change["prev_value"] == Decimal("0.00")
    assert asset2_change["curr_value"] == Decimal("500.00")
    assert asset2_change["change"] == Decimal("500.00")
