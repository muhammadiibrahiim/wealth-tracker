"""
SQLModel data models for Wealth Tracker
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from enum import Enum
from sqlmodel import Field, SQLModel, Relationship, Index, Column, String, DECIMAL, ForeignKey, Date


class InvestmentCadence(str, Enum):
    """Income cadence for investment gains"""
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class InvestmentType(str, Enum):
    """Type of investment"""
    ASSET = "asset"  # Appreciating asset with salvage value (real estate, equipment)
    BUSINESS = "business"  # Business/project with returns but no salvage (ventures, loans)


class LeverageRepaymentType(str, Enum):
    """Method of leverage repayment"""
    EQUAL_INSTALLMENTS = "equal_installments"  # Repay evenly over N months
    CUSTOM_SCHEDULE = "custom_schedule"  # Specify exact amounts and dates


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


class Investment(SQLModel, table=True):
    """Investment model for Phase 2 financial analysis"""
    __tablename__ = "investment"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=255)
    
    # Investment type and start date
    investment_type: InvestmentType = Field(default=InvestmentType.ASSET)
    investment_start_date: date = Field(default_factory=date.today, sa_column=Column(Date))  # When investment began
    
    # Investment inputs
    total_investment_value: Decimal = Field(sa_column=Column(DECIMAL(15, 2)))
    installments: bool = Field(default=False)
    installment_value: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(15, 2)))
    installment_months: Optional[int] = Field(default=None)
    
    # Leverage (borrowed money)
    is_leveraged: bool = Field(default=False)
    leverage_amount: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    leverage_repayment_type: LeverageRepaymentType = Field(default=LeverageRepaymentType.EQUAL_INSTALLMENTS, sa_column=Column(String(50)))
    leverage_repayment_months: Optional[int] = Field(default=None)  # For equal installments
    leverage_monthly_repayment: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))  # Auto-calculated for equal installments
    
    # Relationships
    leverage_repayments: List["LeverageRepayment"] = Relationship(back_populates="investment", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    # Revenue (for business type - one-time sale received in installments)
    has_revenue: bool = Field(default=False)
    revenue_amount: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    revenue_installment_months: Optional[int] = Field(default=None)
    
    # Asset appreciation/depreciation
    asset_appreciates: bool = Field(default=False)
    appreciation_rate_percent: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(6, 3)))
    appreciation_cadence: InvestmentCadence = Field(default=InvestmentCadence.YEARLY)
    
    # Income gains
    gain_in_income_value: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    gain_in_income_percent: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(6, 3)))
    cadence: InvestmentCadence = Field(default=InvestmentCadence.MONTHLY)
    
    # Income growth
    income_increases: bool = Field(default=False)
    income_increase_rate_percent: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(6, 3)))
    income_increase_cadence: InvestmentCadence = Field(default=InvestmentCadence.YEARLY)
    
    one_off_inflow_value: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    salvage_value: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    
    # Discount rates
    discount_rate_annual_percent: Decimal = Field(default=Decimal("15.000"), sa_column=Column(DECIMAL(6, 3)))
    reinvestment_rate_annual_percent: Decimal = Field(default=Decimal("15.000"), sa_column=Column(DECIMAL(6, 3)))
    
    # Analysis parameters
    analysis_horizon_months: int = Field(default=60)
    
    # Break-even analysis inputs
    break_even_fixed_costs: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    break_even_price_per_unit: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    break_even_variable_cost_per_unit: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    
    # Metadata
    notes: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_investment_user_id", "user_id"),
        Index("idx_investment_name", "name"),
    )


class LeverageRepayment(SQLModel, table=True):
    """Custom leverage repayment schedule entry"""
    __tablename__ = "leverage_repayment"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    investment_id: int = Field(sa_column=Column(ForeignKey("investment.id", ondelete="CASCADE")))
    amount: Decimal = Field(sa_column=Column(DECIMAL(15, 2)))
    repayment_date: date = Field(sa_column=Column(Date))
    repayment_month: int = Field(default=0)  # Calculated: months from investment_start_date
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    investment: Optional["Investment"] = Relationship(back_populates="leverage_repayments")
    
    __table_args__ = (
        Index("idx_leverage_repayment_investment_id", "investment_id"),
    )


class InvestmentMetric(SQLModel, table=True):
    """Calculated financial metrics for an investment"""
    __tablename__ = "investment_metric"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    investment_id: int = Field(sa_column=Column(ForeignKey("investment.id", ondelete="CASCADE")))
    user_id: int = Field(index=True)
    
    # Project-level calculated metrics (includes leverage as inflow)
    roi_percent: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 3)))
    npv: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(15, 2)))
    pv_inflows: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(15, 2)))
    pv_outflows: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(15, 2)))
    total_inflows: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(15, 2)))
    irr_percent: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 3)))
    mirr_percent: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 3)))
    payback_months: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 2)))
    discounted_payback_months: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 2)))
    profitability_index: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 3)))
    cagr_percent: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 3)))
    break_even_units: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(15, 2)))
    
    # Equity-level calculated metrics (return on actual invested capital)
    equity_roi_percent: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 3)))
    equity_npv: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(15, 2)))
    equity_irr_percent: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 3)))
    equity_mirr_percent: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 3)))
    equity_profitability_index: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 3)))
    equity_payback_months: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 2)))
    equity_discounted_payback_months: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(10, 2)))
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_investment_metric_investment_id", "investment_id"),
        Index("idx_investment_metric_user_id", "user_id"),
    )


# ============================================================
# Atomic Habits Models
# ============================================================

class LifeAspect(SQLModel, table=True):
    """Life aspect/category for habits (e.g., Business, Deen, Health)"""
    __tablename__ = "life_aspects"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=100)
    icon: str = Field(default="📌", max_length=10)  # emoji
    color: str = Field(default="#3B82F6", max_length=7)  # hex color
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    habits: List["Habit"] = Relationship(
        back_populates="aspect",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    __table_args__ = (
        Index("idx_life_aspect_user", "user_id"),
    )


class Habit(SQLModel, table=True):
    """Individual habit or daily task"""
    __tablename__ = "habits"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    aspect_id: int = Field(sa_column=Column(ForeignKey("life_aspects.id", ondelete="CASCADE")))
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    is_recurring: bool = Field(default=True)  # True = recurring daily, False = one-off task
    target_per_week: int = Field(default=7)  # e.g., 5 = aim for 5 days/week
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    aspect: Optional[LifeAspect] = Relationship(back_populates="habits")
    logs: List["HabitLog"] = Relationship(
        back_populates="habit",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    __table_args__ = (
        Index("idx_habit_user", "user_id"),
        Index("idx_habit_aspect", "aspect_id"),
    )


class CashAccount(SQLModel, table=True):
    """A cash/bank account that receives or pays out money."""
    __tablename__ = "trade_cash_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=120)
    kind: str = Field(default="bank", max_length=30)  # bank | cash | mobile_wallet | other
    bank_name: Optional[str] = Field(default=None, max_length=120)
    account_number: Optional[str] = Field(default=None, max_length=60)
    opening_balance: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    is_active: bool = Field(default=True)
    notes: Optional[str] = Field(default=None, max_length=500)
    # Link to the GL Account that represents this cash/bank in the chart of accounts.
    account_id: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    payments: List["TradePayment"] = Relationship(back_populates="cash_account")

    __table_args__ = (
        Index("idx_cash_account_user", "user_id"),
    )


class Party(SQLModel, table=True):
    """A counterparty: a vendor we buy from, a customer we sell to, or both."""
    __tablename__ = "trade_parties"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=200)
    is_vendor: bool = Field(default=False)
    is_customer: bool = Field(default=True)
    contact_person: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=160)
    address: Optional[str] = Field(default=None, max_length=500)
    # Pakistani city — used as a shipping-destination hint on bilty / delivery docs.
    city: Optional[str] = Field(default=None, max_length=80)
    tax_id: Optional[str] = Field(default=None, max_length=60)
    default_customer_terms_days: int = Field(default=30)  # used when this party is purchaser
    default_vendor_terms_days: int = Field(default=7)  # used when this party is vendor
    # Max extra days we can stretch a payment to this VENDOR beyond its due date
    # before cash MUST be found (from collections or a capital injection). Cash
    # Flow Management defers this vendor's payables to due_date + this many days.
    max_payment_delay_days: int = Field(default=1)
    # Opening ledger balance carried from before the system started.
    # Positive = they owe us (receivable). Negative = we owe them (payable).
    opening_balance: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    opening_balance_date: Optional[date] = Field(default=None, sa_column=Column(Date))
    is_active: bool = Field(default=True)
    notes: Optional[str] = Field(default=None, max_length=1000)
    # Link to GL Account representing this party in the chart of accounts.
    account_id: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_party_user", "user_id"),
        Index("idx_party_user_name", "user_id", "name"),
    )


class Item(SQLModel, table=True):
    """A reusable catalog item (e.g. 'Flyer', 'Banner')."""
    __tablename__ = "trade_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=160)
    sku: Optional[str] = Field(default=None, max_length=60)
    unit: str = Field(default="pcs", max_length=20)  # pcs, kg, m, hr, ...
    default_cost: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    default_price: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    is_active: bool = Field(default=True)
    notes: Optional[str] = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    spec_fields: List["ItemSpecField"] = Relationship(
        back_populates="item",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "ItemSpecField.sort_order"},
    )

    __table_args__ = (
        Index("idx_item_user", "user_id"),
    )


class ItemSpecField(SQLModel, table=True):
    """A spec field on an item template (e.g. for Flyer: 'size', 'sides', 'paper GSM')."""
    __tablename__ = "trade_item_spec_fields"

    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: int = Field(sa_column=Column(ForeignKey("trade_items.id", ondelete="CASCADE")))
    label: str = Field(max_length=80)
    default_value: Optional[str] = Field(default=None, max_length=200)
    sort_order: int = Field(default=0)

    item: Optional[Item] = Relationship(back_populates="spec_fields")

    __table_args__ = (
        Index("idx_item_spec_field_item", "item_id"),
    )


class ItemVendorQuote(SQLModel, table=True):
    """A vendor's quoted buy rate for an item — reference only, so the owner
    can compare vendors before deciding who to purchase from. Not linked to
    any trade or purchase; purely a price-history note."""
    __tablename__ = "trade_item_vendor_quotes"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    item_id: int = Field(sa_column=Column(ForeignKey("trade_items.id", ondelete="CASCADE")))
    vendor_id: int = Field(sa_column=Column(ForeignKey("trade_parties.id", ondelete="CASCADE")))
    quoted_rate: Decimal = Field(sa_column=Column(DECIMAL(15, 4)))
    quoted_date: date = Field(default_factory=date.today, sa_column=Column(Date))
    notes: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_item_vendor_quote_item", "item_id"),
        Index("idx_item_vendor_quote_vendor", "vendor_id"),
    )


class TradeStatus(str, Enum):
    OPEN = "open"
    DELIVERED = "delivered"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    COMPLETED = "completed"   # fully delivered AND fully paid — the cycle is done
    CLOSED = "closed"
    CANCELLED = "cancelled"


class Trade(SQLModel, table=True):
    """A back-to-back trade: we buy from a vendor and sell to a purchaser."""
    __tablename__ = "trades"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    reference: str = Field(max_length=40, index=True)  # human-friendly e.g. TRD-0001

    vendor_id: int = Field(sa_column=Column(ForeignKey("trade_parties.id")))
    purchaser_id: int = Field(sa_column=Column(ForeignKey("trade_parties.id")))

    trade_date: date = Field(default_factory=date.today, sa_column=Column(Date))
    customer_terms_days: int = Field(default=30)
    vendor_terms_days: int = Field(default=7)
    # Split payment terms (percentages). Each side splits into:
    #   advance  → paid on the trade date
    #   delivery → paid on delivery (delivered_at)
    #   credit   → paid {terms_days} after delivery
    # Defaults 0/0/100 reproduce the old behaviour: everything on credit terms.
    cust_advance_pct: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(6, 2)))
    cust_delivery_pct: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(6, 2)))
    cust_credit_pct: Decimal = Field(default=Decimal("100"), sa_column=Column(DECIMAL(6, 2)))
    vend_advance_pct: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(6, 2)))
    vend_delivery_pct: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(6, 2)))
    vend_credit_pct: Decimal = Field(default=Decimal("100"), sa_column=Column(DECIMAL(6, 2)))
    # Optional SECOND customer credit tranche — some customers pay their credit
    # portion in two chunks at two different day-counts after delivery (e.g.
    # "50% at 30 days, 50% at 40 days") instead of all of cust_credit_pct on
    # one date. When cust_credit2_pct is 0 (the default), customer_billing_events
    # behaves exactly as before — the whole credit portion is due on ONE date
    # (customer_terms_days). When it's non-zero, cust_credit_pct is split
    # proportionally between the two day-counts: customer_terms_days (tranche 1)
    # and customer_terms2_days (tranche 2).
    cust_credit2_pct: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(6, 2)))
    customer_terms2_days: int = Field(default=0)

    status: TradeStatus = Field(default=TradeStatus.OPEN, sa_column=Column(String(30)))
    delivered_at: Optional[date] = Field(default=None, sa_column=Column(Date))
    customer_due_date: Optional[date] = Field(default=None, sa_column=Column(Date))
    vendor_due_date: Optional[date] = Field(default=None, sa_column=Column(Date))
    # Owner-set expected arrival date for goods still ON ORDER. When set, Cash
    # Flow Management schedules this trade's supply payment (and the resulting
    # customer collection) from THIS date instead of guessing from vendor history.
    expected_delivery_date: Optional[date] = Field(default=None, sa_column=Column(Date))

    # Cached totals (recomputed on line changes)
    total_cost: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    total_sale: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))

    # Cached payment progress
    paid_to_vendor: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    paid_by_customer: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))

    cancellation_reason: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    lines: List["TradeLine"] = Relationship(
        back_populates="trade",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "TradeLine.id"},
    )
    payments: List["TradePayment"] = Relationship(
        back_populates="trade",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "TradePayment.paid_on"},
    )

    __table_args__ = (
        Index("idx_trade_user_status", "user_id", "status"),
        Index("idx_trade_user_date", "user_id", "trade_date"),
        Index("idx_trade_user_ref", "user_id", "reference", unique=True),
    )


class TradeLine(SQLModel, table=True):
    """One line item on a trade."""
    __tablename__ = "trade_lines"

    id: Optional[int] = Field(default=None, primary_key=True)
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id", ondelete="CASCADE")))
    item_id: Optional[int] = Field(default=None, sa_column=Column(ForeignKey("trade_items.id", ondelete="SET NULL")))
    item_name: str = Field(max_length=160)  # snapshot at line creation
    # ordered_quantity is the original qty at trade creation. quantity is the
    # current/final qty — they diverge when actual delivery comes in over or short.
    ordered_quantity: Decimal = Field(default=Decimal("1"), sa_column=Column(DECIMAL(15, 3)))
    quantity: Decimal = Field(default=Decimal("1"), sa_column=Column(DECIMAL(15, 3)))
    unit: str = Field(default="pcs", max_length=20)
    # unit_cost is the EFFECTIVE (weighted-average) purchase rate. When
    # cost_pending is True the sale rate is fixed but the cost is filled in later
    # by recording purchases; unit_cost is then derived from those purchases.
    unit_cost: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 4)))
    unit_price: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    cost_pending: bool = Field(default=False)
    line_notes: Optional[str] = Field(default=None, max_length=500)

    trade: Optional[Trade] = Relationship(back_populates="lines")
    specs: List["TradeLineSpec"] = Relationship(
        back_populates="line",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "TradeLineSpec.sort_order"},
    )
    receipts: List["TradeLineReceipt"] = Relationship(
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "TradeLineReceipt.received_on"},
    )

    __table_args__ = (
        Index("idx_trade_line_trade", "trade_id"),
        Index("idx_trade_line_item", "item_id"),
    )


class TradeLineReceipt(SQLModel, table=True):
    """A partial delivery against a TradeLine.

    Multiple receipts can be recorded against a single line — the running total
    converges to the ordered quantity. When the user marks the trade Complete,
    the sum of receipts becomes the line's final quantity and the SALE+PURCHASE
    journal entries get posted. Each receipt may carry a vendor invoice image.
    """
    __tablename__ = "trade_line_receipts"

    id: Optional[int] = Field(default=None, primary_key=True)
    line_id: int = Field(sa_column=Column(ForeignKey("trade_lines.id", ondelete="CASCADE")))
    received_qty: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 3)))
    received_on: date = Field(default_factory=date.today, sa_column=Column(Date))
    vendor_invoice_path: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_trade_line_receipt_line", "line_id"),
    )


class TradePurchase(SQLModel, table=True):
    """A recorded purchase of goods for a trade line — a quantity bought at a
    specific rate. A line's cost is the weighted average of its purchases, so
    the SAME product bought across several batches at different rates lives on
    ONE line instead of being split into separate line items.

    Recorded via the 'Record Purchase' action, independently of physical
    delivery receipts. Total line cost = Σ(qty × rate) across its purchases."""
    __tablename__ = "trade_purchases"

    id: Optional[int] = Field(default=None, primary_key=True)
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id", ondelete="CASCADE")))
    line_id: int = Field(sa_column=Column(ForeignKey("trade_lines.id", ondelete="CASCADE")))
    quantity: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 3)))
    unit_cost: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 4)))
    purchased_on: date = Field(default_factory=date.today, sa_column=Column(Date))
    vendor_invoice_path: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_trade_purchase_trade", "trade_id"),
        Index("idx_trade_purchase_line", "line_id"),
    )


class TradeAttachmentKind(str, Enum):
    CUSTOMER_PO = "customer_po"
    DESIGN = "design"          # artwork / proof to send to the vendor
    OTHER = "other"


class TradeAttachment(SQLModel, table=True):
    """A document attached to a Trade — e.g. the customer's purchase order.

    Multiple attachments per trade are allowed (a customer may send a revised PO,
    a signed copy, etc.). File bytes live on disk under static/uploads/trade_attachments/;
    the row holds the URL path and metadata so the UI can list/preview/delete.
    """
    __tablename__ = "trade_attachments"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id", ondelete="CASCADE")))
    kind: TradeAttachmentKind = Field(default=TradeAttachmentKind.CUSTOMER_PO,
                                      sa_column=Column(String(40)))
    filename: str = Field(max_length=255)
    content_type: Optional[str] = Field(default=None, max_length=120)
    size_bytes: int = Field(default=0)
    path: str = Field(max_length=500)
    notes: Optional[str] = Field(default=None, max_length=500)
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_trade_attachment_trade", "trade_id"),
    )


class TradeDocument(SQLModel, table=True):
    """A standalone document in the Trade module's document library — NOT
    tied to any specific trade (unlike TradeAttachment). Paste/drop a file,
    name it, find it later via search. File bytes live on disk under
    static/uploads/trade_documents/; the row holds the URL path and metadata.
    """
    __tablename__ = "trade_documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=200)
    filename: str = Field(max_length=255)
    content_type: Optional[str] = Field(default=None, max_length=120)
    size_bytes: int = Field(default=0)
    path: str = Field(max_length=500)
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_trade_document_user", "user_id"),
    )


class TradeTerminal(SQLModel, table=True):
    """A bilty terminal — e.g. 'Lahore Thokar / Faysal Movers'.

    Auto-created on first use from the bilty modal. Stored as a flat catalog so
    the typeahead can suggest previously-used terminals across all trades.
    """
    __tablename__ = "trade_terminals"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=200, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_terminal_user_name", "user_id", "name", unique=True),
    )


class TradeBilty(SQLModel, table=True):
    """Bilty metadata for a delivery event — links to its journal entry.

    One row per active bilty (per trade, per delivery date). Persists kgs +
    terminal info so the bilty report can pivot on them. When the underlying
    journal entry is reversed (amount = 0, or a fresh bilty replaces it), the
    matching row is deleted so live data always reflects the current state.
    """
    __tablename__ = "trade_bilties"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id", ondelete="CASCADE")))
    delivery_date: date = Field(sa_column=Column(Date))
    journal_entry_id: int = Field(sa_column=Column(ForeignKey("journal_entries.id", ondelete="CASCADE")))
    weight_kgs: Optional[Decimal] = Field(default=None, sa_column=Column(DECIMAL(12, 3)))
    terminal_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("trade_terminals.id", ondelete="SET NULL")),
    )
    paid_by_customer: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_bilty_trade_date", "trade_id", "delivery_date"),
        Index("idx_bilty_user", "user_id"),
    )


class TradeLineSpec(SQLModel, table=True):
    """A spec label/value captured against a trade line (e.g. 'size = 12x12')."""
    __tablename__ = "trade_line_specs"

    id: Optional[int] = Field(default=None, primary_key=True)
    line_id: int = Field(sa_column=Column(ForeignKey("trade_lines.id", ondelete="CASCADE")))
    label: str = Field(max_length=80)
    value: str = Field(default="", max_length=400)
    sort_order: int = Field(default=0)

    line: Optional[TradeLine] = Relationship(back_populates="specs")


class Partner(SQLModel, table=True):
    """An equity partner (investor). Each partner owns a fixed % of the business
    and has an equity capital account. The OWNER is NOT stored here — the owner is
    the implicit remainder (100% − sum of partner %s) and keeps all pre-existing
    capital. Monthly profit is split into partner capital accounts by their %.
    """
    __tablename__ = "partners"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=160)
    account_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("accounts.id", ondelete="SET NULL")))
    pct: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(7, 4)))  # ownership %
    joined_on: date = Field(default_factory=date.today, sa_column=Column(Date))
    is_active: bool = Field(default=True)
    # The OWNER's own capital account (e.g. "Ibrahim Capital"). Exactly one row
    # should carry this. Its % is the remainder (100 − Σ others); the monthly
    # split routes the owner's share here so the Capital A/C pool empties.
    is_owner: bool = Field(default=False)
    notes: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (Index("idx_partner_user", "user_id"),)


class PartnerAllocation(SQLModel, table=True):
    """One monthly profit/loss allocation posted to partner capital accounts.

    period = the FIRST day of the allocated calendar month. The unique (user,
    period) index makes the monthly run idempotent — it can only post once per
    month, so opening the app repeatedly (or catching up missed months) never
    double-counts. profit is signed (negative in a loss month).
    """
    __tablename__ = "partner_allocations"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    period: date = Field(sa_column=Column(Date))
    profit: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    journal_entry_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("journal_entries.id", ondelete="SET NULL")))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (Index("idx_partner_alloc_period", "user_id", "period", unique=True),)


# ────────────────────────── Quotations ──────────────────────────


class QuotationStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"     # converted into a Trade — trade_id is set
    REJECTED = "rejected"
    EXPIRED = "expired"


class Quotation(SQLModel, table=True):
    """A pre-trade proposal sent to a prospective customer.

    Shares the same back-to-back shape as Trade (vendor + purchaser + lines)
    so the data flows cleanly into a Trade on Accept. No journal entries are
    posted until acceptance.
    """
    __tablename__ = "quotations"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    reference: str = Field(max_length=40, index=True)  # human-friendly e.g. QO-0001

    vendor_id: int = Field(sa_column=Column(ForeignKey("trade_parties.id")))
    purchaser_id: int = Field(sa_column=Column(ForeignKey("trade_parties.id")))

    quote_date: date = Field(default_factory=date.today, sa_column=Column(Date))
    valid_until: Optional[date] = Field(default=None, sa_column=Column(Date))
    customer_terms_days: int = Field(default=30)
    vendor_terms_days: int = Field(default=7)

    status: QuotationStatus = Field(default=QuotationStatus.DRAFT, sa_column=Column(String(30)))
    accepted_at: Optional[date] = Field(default=None, sa_column=Column(Date))
    trade_id: Optional[int] = Field(
        default=None,
        sa_column=Column(ForeignKey("trades.id", ondelete="SET NULL")),
    )

    total_cost: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    total_sale: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))

    notes: Optional[str] = Field(default=None, max_length=2000)
    terms_text: Optional[str] = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    lines: List["QuotationLine"] = Relationship(
        back_populates="quotation",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "QuotationLine.id"},
    )

    __table_args__ = (
        Index("idx_quotation_user_status", "user_id", "status"),
        Index("idx_quotation_user_date", "user_id", "quote_date"),
        Index("idx_quotation_user_ref", "user_id", "reference", unique=True),
    )


class QuotationLine(SQLModel, table=True):
    __tablename__ = "quotation_lines"

    id: Optional[int] = Field(default=None, primary_key=True)
    quotation_id: int = Field(sa_column=Column(ForeignKey("quotations.id", ondelete="CASCADE")))
    item_id: Optional[int] = Field(default=None, sa_column=Column(ForeignKey("trade_items.id", ondelete="SET NULL")))
    item_name: str = Field(max_length=160)
    quantity: Decimal = Field(default=Decimal("1"), sa_column=Column(DECIMAL(15, 3)))
    unit: str = Field(default="pcs", max_length=20)
    unit_cost: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    unit_price: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    line_notes: Optional[str] = Field(default=None, max_length=500)

    quotation: Optional[Quotation] = Relationship(back_populates="lines")
    specs: List["QuotationLineSpec"] = Relationship(
        back_populates="line",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "QuotationLineSpec.sort_order"},
    )

    __table_args__ = (
        Index("idx_quotation_line_quotation", "quotation_id"),
    )


class QuotationLineSpec(SQLModel, table=True):
    __tablename__ = "quotation_line_specs"

    id: Optional[int] = Field(default=None, primary_key=True)
    line_id: int = Field(sa_column=Column(ForeignKey("quotation_lines.id", ondelete="CASCADE")))
    label: str = Field(max_length=80)
    value: str = Field(default="", max_length=400)
    sort_order: int = Field(default=0)

    line: Optional[QuotationLine] = Relationship(back_populates="specs")

    __table_args__ = (
        Index("idx_trade_line_spec_line", "line_id"),
    )


# Backfill: TradeLineReceipt → TradeLine via relationship.
# (Done here because forward references aren't easy from above.)


class PaymentDirection(str, Enum):
    INBOUND = "inbound"   # customer paid us
    OUTBOUND = "outbound" # we paid the vendor


class TradePayment(SQLModel, table=True):
    """A payment received from a customer or paid to a vendor against a trade."""
    __tablename__ = "trade_payments"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id", ondelete="CASCADE")))
    # Exactly one of cash_account_id / account_id is set: a payment lands either
    # in a managed cash/bank account or directly on any GL ledger account.
    cash_account_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("trade_cash_accounts.id"), nullable=True)
    )
    account_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("accounts.id"), nullable=True)
    )
    direction: PaymentDirection = Field(sa_column=Column(String(20)))
    amount: Decimal = Field(sa_column=Column(DECIMAL(15, 2)))
    paid_on: date = Field(default_factory=date.today, sa_column=Column(Date))
    method: Optional[str] = Field(default=None, max_length=40)  # cash, transfer, cheque, ...
    reference: Optional[str] = Field(default=None, max_length=120)  # cheque#, txn id
    notes: Optional[str] = Field(default=None, max_length=500)
    # Uploaded proof-of-payment image (bank screenshot, receipt) — served path
    # under /static/uploads/payments/. Shown on the trade and in party ledgers.
    proof_path: Optional[str] = Field(default=None, max_length=300)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    trade: Optional[Trade] = Relationship(back_populates="payments")
    cash_account: Optional[CashAccount] = Relationship(back_populates="payments")
    gl_account: Optional["Account"] = Relationship()

    __table_args__ = (
        Index("idx_trade_payment_trade", "trade_id"),
        Index("idx_trade_payment_user_date", "user_id", "paid_on"),
    )


class CustomerCredit(SQLModel, table=True):
    """An unapplied credit balance reserved for a customer — value owed to
    them (or earmarked for them) that isn't attributed to any specific trade
    yet, e.g. the leftover of a loan offset once the part that fit the
    current invoice has been applied. Draws down as it's applied against
    trades — oldest credit first — either automatically the moment a new
    trade is created for that customer, or manually against an existing one.

    source_account_id is OPTIONAL and almost always left blank: most of the
    time this credit is just an amount already sitting on the CUSTOMER'S OWN
    account (recorded there via a plain Receipt/Payment voucher against that
    same party — e.g. money the customer personally lent the business). This
    row is then just a bookkeeping note earmarking part of that balance for
    a future invoice; applying it moves the earmark from "general" to
    "tagged to this trade" on the customer's own account (net zero effect on
    their overall balance — one ledger, not two). Only set source_account_id
    when the credit genuinely originates from a DIFFERENT account than the
    customer's own (a distinct third-party lender, an owner-funded discount,
    etc.) — that case still posts a real cross-account entry when applied."""
    __tablename__ = "trade_customer_credits"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    customer_id: int = Field(sa_column=Column(ForeignKey("trade_parties.id", ondelete="CASCADE")))
    source_account_id: Optional[int] = Field(default=None, sa_column=Column(ForeignKey("accounts.id"), nullable=True))
    amount: Decimal = Field(sa_column=Column(DECIMAL(15, 2)))
    remaining_amount: Decimal = Field(sa_column=Column(DECIMAL(15, 2)))
    entry_date: date = Field(default_factory=date.today, sa_column=Column(Date))
    notes: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    source_account: Optional["Account"] = Relationship()

    __table_args__ = (
        Index("idx_customer_credit_customer", "customer_id"),
    )


# ════════════════════════════════════════════════════════════════════════
# Chart of Accounts & Double-Entry Bookkeeping
# ════════════════════════════════════════════════════════════════════════


class AccountNature(str, Enum):
    """The natural side of an account class — drives report grouping + sign."""
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"


class JournalEntryType(str, Enum):
    """The type of journal entry. Used for filtering/reporting."""
    OPENING = "opening"
    SALE = "sale"
    PURCHASE = "purchase"
    CUSTOMER_RECEIPT = "customer_receipt"
    VENDOR_PAYMENT = "vendor_payment"
    EXPENSE = "expense"
    CAPITAL_INJECTION = "capital_injection"
    CAPITAL_WITHDRAWAL = "capital_withdrawal"
    CONTRA = "contra"
    JOURNAL = "journal"
    REVERSAL = "reversal"
    PARTNER_ALLOCATION = "partner_allocation"  # equity split among partners — hidden from dashboard


class AccountClass(SQLModel, table=True):
    """Top-level account class (e.g. 1000 Assets, 2000 Liabilities)."""
    __tablename__ = "account_classes"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    code: str = Field(max_length=10)
    name: str = Field(max_length=120)
    nature: AccountNature = Field(sa_column=Column(String(20)))
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_account_class_user_code", "user_id", "code", unique=True),
    )


class AccountSubClass(SQLModel, table=True):
    """Sub-classification under an AccountClass."""
    __tablename__ = "account_subclasses"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    class_id: int = Field(sa_column=Column(ForeignKey("account_classes.id", ondelete="CASCADE")))
    code: str = Field(max_length=10)
    name: str = Field(max_length=120)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_account_subclass_user_code", "user_id", "code", unique=True),
        Index("idx_account_subclass_class", "class_id"),
    )


class Account(SQLModel, table=True):
    """A leaf account in the chart of accounts. Code auto-generated by the service layer."""
    __tablename__ = "accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    code: str = Field(max_length=20)
    name: str = Field(max_length=200)
    class_id: int = Field(sa_column=Column(ForeignKey("account_classes.id")))
    subclass_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("account_subclasses.id"))
    )
    description: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = Field(default=True)
    is_system: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_account_user_code", "user_id", "code", unique=True),
        Index("idx_account_user_name", "user_id", "name"),
        Index("idx_account_class", "class_id"),
    )


class JournalEntry(SQLModel, table=True):
    """Header for a balanced set of debit/credit lines."""
    __tablename__ = "journal_entries"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    reference: str = Field(max_length=40, index=True)
    entry_date: date = Field(sa_column=Column(Date))
    entry_type: JournalEntryType = Field(sa_column=Column(String(40)))
    description: str = Field(max_length=500)
    trade_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("trades.id", ondelete="SET NULL"))
    )
    payment_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("trade_payments.id", ondelete="SET NULL"))
    )
    is_reversed: bool = Field(default=False)
    reversed_at: Optional[datetime] = Field(default=None)
    reversal_of_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("journal_entries.id"))
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = Field(default=None, max_length=80)
    # Uploaded payment screenshot / receipt for standalone vouchers (Payment,
    # Receipt, Expense, Contra, Owner In/Out) — these aren't a TradePayment
    # (that has its own proof_path) so there's nowhere else to hang this.
    proof_path: Optional[str] = Field(default=None, max_length=300)

    lines: List["JournalLine"] = Relationship(
        back_populates="entry",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "JournalLine.id"},
    )

    __table_args__ = (
        Index("idx_journal_entry_user_date", "user_id", "entry_date"),
        Index("idx_journal_entry_user_ref", "user_id", "reference", unique=True),
        Index("idx_journal_entry_type", "entry_type"),
        Index("idx_journal_entry_trade", "trade_id"),
    )


class JournalLine(SQLModel, table=True):
    """One debit or credit line. Dimensional tags drive analytics."""
    __tablename__ = "journal_lines"

    id: Optional[int] = Field(default=None, primary_key=True)
    journal_entry_id: int = Field(
        sa_column=Column(ForeignKey("journal_entries.id", ondelete="CASCADE"))
    )
    account_id: int = Field(sa_column=Column(ForeignKey("accounts.id")))
    debit: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    credit: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    description: Optional[str] = Field(default=None, max_length=500)
    sort_order: int = Field(default=0)
    # Dimensional tags — nullable, used by Customer/Vendor/Item Profitability reports.
    item_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("trade_items.id", ondelete="SET NULL"))
    )
    party_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("trade_parties.id", ondelete="SET NULL"))
    )
    trade_line_id: Optional[int] = Field(
        default=None, sa_column=Column(ForeignKey("trade_lines.id", ondelete="SET NULL"))
    )

    entry: Optional[JournalEntry] = Relationship(back_populates="lines")

    __table_args__ = (
        Index("idx_journal_line_entry", "journal_entry_id"),
        Index("idx_journal_line_account", "account_id"),
        Index("idx_journal_line_item", "item_id"),
        Index("idx_journal_line_party", "party_id"),
    )


class HabitLog(SQLModel, table=True):
    """Daily log entry for a habit"""
    __tablename__ = "habit_logs"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    habit_id: int = Field(sa_column=Column(ForeignKey("habits.id", ondelete="CASCADE")))
    log_date: date = Field(sa_column=Column(Date))
    completed: bool = Field(default=True)
    notes: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    habit: Optional[Habit] = Relationship(back_populates="logs")
    
    __table_args__ = (
        Index("idx_habit_log_user_date", "user_id", "log_date"),
        Index("idx_habit_log_habit_date", "habit_id", "log_date", unique=True),
    )


class ProjectionLine(SQLModel, table=True):
    """A planned (not-yet-committed) order line for the cash-requirement
    projection tool. Lets the owner model a batch of orders — cost, sale,
    dye/block, bilty and timing — to see the day-wise cash they'd need."""
    __tablename__ = "projection_lines"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    item_name: str = Field(max_length=200)
    # Product group for the planner (e.g. "Dabbi" for boxes, "Stickers"). Purely
    # for visual grouping of the planned-order rows; doesn't affect any calc.
    group_name: str = Field(default="Dabbi", sa_column=Column(String(80), nullable=False, server_default="Dabbi"))
    quantity: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 3)))
    purchase_rate: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 4)))
    # The vendor/party's OLD buy rate (their previous price) — reference only, so
    # the owner can decide their new buy/sale rate against it. Not used in any calc.
    party_old_rate: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 4)))
    sale_rate: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 4)))
    dye_block_cost: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    bilty: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(15, 2)))
    # Calendar date this order is placed (day 0 for this line). Null = "today".
    order_date: Optional[date] = Field(default=None, sa_column=Column(Date, nullable=True))
    # Timing (days) — order → delivery, then delivery → cash collected.
    lead_days: int = Field(default=15)
    collection_lag_days: int = Field(default=30)
    # Vendor payment split (percentages of the purchase cost):
    #   advance  -> paid on the order date
    #   on_delivery -> paid when goods arrive (order date + lead days)
    #   credit   -> paid credit_days AFTER delivery
    # They should total 100; the projection normalises if they don't.
    pct_advance: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(6, 2)))
    pct_on_delivery: Decimal = Field(default=Decimal("100"), sa_column=Column(DECIMAL(6, 2)))
    pct_credit: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(6, 2)))
    credit_days: int = Field(default=30)
    # Deprecated (superseded by the percentage split); kept for back-compat.
    pay_on_delivery: bool = Field(default=True)
    include: bool = Field(default=True)
    # Whether the one-time Dye/Block cost still applies. Turn off to model the
    # NEXT cycle (blocks already made) — excludes it from cash-out and KPIs.
    dye_active: bool = Field(default=True)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_projection_line_user", "user_id"),
    )


# ─────────────────────────── Personal Accounts (Money Manager) ───────────────────────────


class MoneyAccountType(str, Enum):
    """Classification for a personal account imported from Money Manager.
    Purely for grouping / net-worth composition; the user can re-type freely."""
    cash = "cash"
    bank = "bank"
    wallet = "wallet"
    person = "person"        # a person you lend to / borrow from
    business = "business"    # a venture (Ibrahim Traders, Cambrify, Adify …)
    investment = "investment"
    asset = "asset"          # plot, macbook, car …
    expense = "expense"      # expense-tracking pseudo account (Home exp, Trip exp …)
    other = "other"


class MoneyTxnKind(str, Enum):
    transfer = "transfer"
    income = "income"
    expense = "expense"
    balance = "balance"      # opening / initial-balance setting entry


class MoneyAccount(SQLModel, table=True):
    """A personal account mirrored from the Money Manager cashbook export
    (cash, banks, wallets, people you lend to, ventures, assets …).

    Kept entirely separate from the business (Trade) chart of accounts — this
    is the owner's PERSONAL book. A cross-link to the trade module (personal
    'IBRAHIM TRADERS' ↔ business CEO funding) is intentionally deferred."""
    __tablename__ = "money_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    name: str = Field(max_length=200, index=True)
    type: MoneyAccountType = Field(default=MoneyAccountType.other, sa_column=Column(String(20)))
    is_active: bool = Field(default=True)
    # Whether this account counts toward net worth / totals. Balances are always
    # computed; excluded accounts simply don't add into the headline figures.
    include_in_networth: bool = Field(default=True)
    # The Money Manager group this account belongs to (for exact-match grouping).
    # Null = fall back to type-based grouping.
    group_name: Optional[str] = Field(default=None, sa_column=Column(String(80), nullable=True))
    sort_order: int = Field(default=0)
    notes: Optional[str] = Field(default=None, sa_column=Column(String(500), nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_money_account_user", "user_id"),
    )

    @property
    def type_label(self) -> str:
        """The account type as text, safe to render.

        `type` is annotated as MoneyAccountType but backed by a plain
        String(20) column, so the enum is only applied when the object is
        BUILT in Python. Loaded from the database it comes back as a bare str,
        where `.value` is undefined — which is why templates using
        `acct.type.value` silently rendered nothing. This reads right either way.
        """
        return getattr(self.type, "value", self.type) or ""


class MoneyTxn(SQLModel, table=True):
    """One row of the Money Manager cashbook (per-account view). Transfers appear
    as two rows — one Transfer-Out on the source account and one Transfer-In on
    the destination — so each row affects exactly its own `account_id`, and an
    account balance is simply sum(in) − sum(out) over its rows.

    `source_hash` makes imports idempotent / append-only: a row is inserted only
    if its hash isn't already present for the user."""
    __tablename__ = "money_txns"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    occurred_at: datetime = Field(index=True)
    account_id: int = Field(foreign_key="money_accounts.id", index=True)
    counter_account_id: Optional[int] = Field(default=None, foreign_key="money_accounts.id")
    category: Optional[str] = Field(default=None, sa_column=Column(String(200), nullable=True))
    subcategory: Optional[str] = Field(default=None, sa_column=Column(String(200), nullable=True))
    note: Optional[str] = Field(default=None, sa_column=Column(String(500), nullable=True))
    description: Optional[str] = Field(default=None, sa_column=Column(String(500), nullable=True))
    amount: Decimal = Field(default=Decimal("0"), sa_column=Column(DECIMAL(16, 2)))
    direction: str = Field(sa_column=Column(String(4)))          # "in" | "out"
    kind: MoneyTxnKind = Field(default=MoneyTxnKind.transfer, sa_column=Column(String(12)))
    currency: str = Field(default="PKR", sa_column=Column(String(8)))
    source_hash: str = Field(sa_column=Column(String(64), index=True))
    import_batch: Optional[str] = Field(default=None, sa_column=Column(String(40), nullable=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index("idx_money_txn_user_hash", "user_id", "source_hash"),
        Index("idx_money_txn_account", "account_id"),
    )

