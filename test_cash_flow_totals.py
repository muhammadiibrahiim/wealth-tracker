"""Test cash flow table with totals"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from services.investment_metrics import InvestmentMetricsService
from sqlmodel import create_engine, Session
from models import Investment

engine = create_engine('sqlite:///./wealth_tracker.db')
session = Session(engine)

inv = session.get(Investment, 2)
table = InvestmentMetricsService.get_cash_flow_table(inv)

print('\n' + '='*95)
print(f"{'Month':>6} | {'Inflow':>14} | {'Outflow':>14} | {'Net CF':>14} | {'Discounted':>14}")
print('='*95)

for row in table:
    month_str = str(row['month'])
    inflow_str = f"Rs {float(row['inflow']):>11,.2f}" if row['inflow'] > 0 else ""
    outflow_str = f"Rs {float(row['outflow']):>11,.2f}" if row['outflow'] > 0 else ""
    net_str = f"Rs {float(row['net']):>11,.2f}"
    disc_str = f"Rs {float(row['discounted_net']):>11,.2f}"
    
    if month_str == "TOTAL":
        print('='*95)
    
    print(f"{month_str:>6} | {inflow_str:>14} | {outflow_str:>14} | {net_str:>14} | {disc_str:>14}")

print('='*95 + '\n')
