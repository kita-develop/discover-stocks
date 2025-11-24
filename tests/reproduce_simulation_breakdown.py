
import sys
import os
from datetime import date
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock streamlit
import streamlit as st
st.progress = MagicMock()
st.empty = MagicMock()
st.error = print
st.write = print

# Import necessary modules from the app
try:
    from pages.investment_simulation import (
        simulate_investment, calculate_monthly_pnl, calculate_pnl_breakdown
    )
except ImportError:
    print("Import failed.")
    sys.exit(1)

def verify_app_fix():
    start_date = date(2025, 7, 1)
    end_date = date(2025, 11, 23)
    initial_jpy = 5000000
    initial_usd = 5000000
    # Default ratios
    allocation = [25, 20, 15, 10, 5, 5, 5, 5, 5, 5]
    
    print("Running original simulation...")
    results, history = simulate_investment(start_date, end_date, initial_jpy, initial_usd, allocation, allocation)
    
    print(f"Simulation complete. Days: {len(results)}")
    
    # Use the App's new helper function to get PnL data
    print("Calculating PnL Breakdown using App's new logic...")
    daily_pnl_data = calculate_pnl_breakdown(results, history)
    
    # Aggregate by Month
    monthly_agg = {}
    
    for date_obj, data in daily_pnl_data.items():
        month_key = date_obj.strftime('%Y-%m')
        if month_key not in monthly_agg:
            monthly_agg[month_key] = {
                'realized_pnl': 0,
                'unrealized_pnl': 0,
                'total_pnl': 0
            }
        
        monthly_agg[month_key]['realized_pnl'] += data['realized_pnl']
        monthly_agg[month_key]['unrealized_pnl'] += data['unrealized_pnl']
        monthly_agg[month_key]['total_pnl'] += data['total_pnl']

    print("\nMonthly PnL Breakdown (App Logic - Fixed) [Unit: JPY]:")
    print(f"{'Month':<10} {'Total PnL':>15} {'Realized':>15} {'Unrealized':>15} {'Other':>15}")
    print("-" * 75)
    
    for month in range(7, 12):
        month_key = f"2025-{month:02d}"
        
        # Calculate Monthly Total PnL (Asset Value Change)
        # Note: calculate_monthly_pnl returns the PnL amount for the month
        pnl_info = calculate_monthly_pnl(results, 2025, month)
        total_pnl_amount = pnl_info['pnl_amount'] if pnl_info else 0
        
        # Get aggregated values
        agg = monthly_agg.get(month_key, {'realized_pnl': 0, 'unrealized_pnl': 0})
        realized = agg['realized_pnl']
        unrealized = agg['unrealized_pnl']
        
        # Other = Total - (Realized + Unrealized)
        other = total_pnl_amount - (realized + unrealized)
        
        print(f"{month_key:<10} {total_pnl_amount:>15,.0f} {realized:>15,.0f} {unrealized:>15,.0f} {other:>15,.0f}")

if __name__ == "__main__":
    verify_app_fix()
