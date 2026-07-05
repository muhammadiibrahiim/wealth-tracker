"""
Seed script to create demo data
"""
from sqlmodel import Session
from database import engine
from services.assets import AssetService
from services.wealth import WealthService
from decimal import Decimal
from utils import get_current_year_month, prev_year_month


def seed_data():
    """Seed the database with demo data"""
    with Session(engine) as session:
        print("Seeding demo data...")
        
        # Create demo user_id = 1
        user_id = 1
        
        # Create 3 demo assets
        try:
            asset1 = AssetService.create_asset(session, user_id, "Savings Account")
            print(f"Created asset: {asset1.name}")
        except ValueError:
            print("Asset 'Savings Account' already exists")
        
        try:
            asset2 = AssetService.create_asset(session, user_id, "Investment Portfolio")
            print(f"Created asset: {asset2.name}")
        except ValueError:
            print("Asset 'Investment Portfolio' already exists")
        
        try:
            asset3 = AssetService.create_asset(session, user_id, "Real Estate")
            print(f"Created asset: {asset3.name}")
        except ValueError:
            print("Asset 'Real Estate' already exists")
        
        print("Seed data complete!")


if __name__ == "__main__":
    seed_data()
