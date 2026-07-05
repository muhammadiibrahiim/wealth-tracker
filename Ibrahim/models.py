"""
SQLModel data models for Wealth Tracker
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlmodel import Field, SQLModel, Relationship, Index, Column, String, DECIMAL, ForeignKey


class Asset(SQLModel, table=True):
    """Asset model representing user-defined assets"""
    __tablename__ = "assets"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=255)
    slug: str = Field(max_length=255, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    valuations: list["AssetValuation"] = Relationship(
        back_populates="asset",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    __table_args__ = (
        Index("idx_user_slug", "user_id", "slug", unique=True),
    )


class AssetValuation(SQLModel, table=True):
    """Asset valuation for a specific month"""
    __tablename__ = "asset_valuations"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    asset_id: int = Field(sa_column=Column(ForeignKey("assets.id", ondelete="CASCADE")))
    year_month: str = Field(max_length=7)  # YYYY-MM format
    value: Decimal = Field(sa_column=Column(DECIMAL(18, 2)))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    asset: Optional[Asset] = Relationship(back_populates="valuations")
    
    __table_args__ = (
        Index("idx_user_asset_month", "user_id", "asset_id", "year_month", unique=True),
        Index("idx_user_month", "user_id", "year_month"),
    )


class MonthNetworth(SQLModel, table=True):
    """Materialized cache of networth per month per user"""
    __tablename__ = "month_networth"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    year_month: str = Field(max_length=7)  # YYYY-MM format
    networth: Decimal = Field(sa_column=Column(DECIMAL(18, 2)))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_user_month_networth", "user_id", "year_month", unique=True),
    )
