"""
Pydantic schemas for request/response validation
"""
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


# ===== Asset Schemas =====

class AssetCreate(BaseModel):
    """Schema for creating a new asset"""
    asset_name: str = Field(..., min_length=1, max_length=255)


class AssetRename(BaseModel):
    """Schema for renaming an asset"""
    new_name: str = Field(..., min_length=1, max_length=255)


class AssetResponse(BaseModel):
    """Schema for asset response"""
    id: int
    user_id: int
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ===== Valuation Schemas =====

class ValuationCreate(BaseModel):
    """Schema for creating/updating a valuation (allows negative values for debts/liabilities)"""
    asset_id: int
    year_month: str = Field(..., pattern=r'^\d{4}-\d{2}$')
    value: Decimal = Field(..., decimal_places=2, description="Value in PKR (can be negative for liabilities)")


class ValuationResponse(BaseModel):
    """Schema for valuation response"""
    id: int
    user_id: int
    asset_id: int
    year_month: str
    value: Decimal
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ===== Wealth Computation Schemas =====

class AssetChangeDetail(BaseModel):
    """Detail of change for one asset"""
    asset_id: int
    asset_name: str
    prev_value: Decimal
    curr_value: Decimal
    change: Decimal


class MonthChangeResponse(BaseModel):
    """Response for month change computation"""
    year_month: str
    per_asset: list[AssetChangeDetail]
    total_change: Decimal
    donation: Decimal
    personal_exp: Decimal
    investment: Decimal
    networth_prev: Decimal
    networth_curr: Decimal
    networth_change: Decimal


class MonthNetworthSummary(BaseModel):
    """Summary of networth for a specific month"""
    month: str
    networth: Decimal


class RangeStatsResponse(BaseModel):
    """Response for range statistics"""
    start_month: Optional[str]
    end_month: Optional[str]
    months: list[str]
    networth_by_month: list[MonthNetworthSummary]
    avg_monthly_networth_gain: Decimal


# ===== Search/Filter Schemas =====

class AssetSearchParams(BaseModel):
    """Parameters for searching assets"""
    query: Optional[str] = None


class MonthRangeParams(BaseModel):
    """Parameters for month range filtering"""
    start_month: Optional[str] = Field(None, pattern=r'^\d{4}-\d{2}$')
    end_month: Optional[str] = Field(None, pattern=r'^\d{4}-\d{2}$')
