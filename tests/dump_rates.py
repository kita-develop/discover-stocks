
import sqlite3
import pandas as pd

def dump_cached_rates():
    db_path = 'survey.db'
    print(f"Reading rates from {db_path}...")
    
    try:
        conn = sqlite3.connect(db_path)
        query = """
            SELECT date, price 
            FROM price_cache 
            WHERE stock_code = 'USDJPY=X' 
            ORDER BY date
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            print("No cached rates found for USDJPY=X.")
            return

        print(f"Cached data points: {len(df)}")
        
        # Filter for 2025
        df['date'] = pd.to_datetime(df['date'])
        df_2025 = df[(df['date'] >= '2025-07-01') & (df['date'] <= '2025-11-23')]
        
        if df_2025.empty:
            print("No cached rates found for the simulation period (2025/07-11).")
            # Print recent ones just in case
            print("Recent cached rates:")
            print(df.tail())
            return
            
        print("\nCached Rates (2025/07-11):")
        print(f"Start ({df_2025.iloc[0]['date'].date()}): {df_2025.iloc[0]['price']:.2f}")
        print(f"End ({df_2025.iloc[-1]['date'].date()}): {df_2025.iloc[-1]['price']:.2f}")
        
        # Monthly Stats
        df_2025['Month'] = df_2025['date'].dt.to_period('M')
        monthly = df_2025.groupby('Month')['price'].agg(['first', 'last'])
        monthly['Change'] = monthly['last'] - monthly['first']
        monthly['Change%'] = ((monthly['last'] - monthly['first']) / monthly['first']) * 100
        
        print("\nMonthly Changes (Cached):")
        print(monthly)
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    dump_cached_rates()
