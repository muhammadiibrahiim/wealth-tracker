"""
Application configuration
"""
import os

# Application settings
APP_NAME = "Wealth Tracker"
APP_VERSION = "1.0.0"

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wealth_tracker.db")

# Default user for single-user mode
DEFAULT_USER_ID = 1

# Decimal precision
DECIMAL_PLACES = 2

# Currency settings
CURRENCY_SYMBOL = "Rs"  # Pakistani Rupee
CURRENCY_CODE = "PKR"

# Allocations
DONATION_PERCENTAGE = 10
PERSONAL_EXP_PERCENTAGE = 20
INVESTMENT_PERCENTAGE = 70
