"""Add pv_outflows column to investment_metric table"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from sqlmodel import create_engine
from sqlalchemy import text

DATABASE_URL = "sqlite:///./wealth_tracker.db"
engine = create_engine(DATABASE_URL)

print("\nAdding pv_outflows column to investment_metric table...")

with engine.connect() as conn:
    # Add the column
    conn.execute(text("""
        ALTER TABLE investment_metric 
        ADD COLUMN pv_outflows DECIMAL(15, 2)
    """))
    conn.commit()

print("✓ Column added successfully!\n")
