
import yfinance as yf
import pandas as pd

def check_rates():
    print("Fetching USD/JPY rates for 2025/07 - 2025/11...")
    
    start_date = "2025-07-01"
    end_date = "2025-11-23"
    
    try:
        df = yf.download(
            "USDJPY=X",
            start=start_date,
            end=end_date,
            progress=False,
            threads=False,
            auto_adjust=True
        )
        
        if df.empty:
            print("No data returned.")
            return

        # Handle MultiIndex columns if present (common in new yfinance)
        if isinstance(df.columns, pd.MultiIndex):
            # Try to find 'Close'
            try:
                close_series = df['Close']['USDJPY=X']
            except KeyError:
                 # Fallback if structure is different
                close_series = df.iloc[:, 0] # Take first column
        else:
            if 'Close' in df.columns:
                close_series = df['Close']
            else:
                close_series = df.iloc[:, 0]

        print(f"Data points: {len(close_series)}")
        
        start_val = float(close_series.iloc[0])
        end_val = float(close_series.iloc[-1])
        
        print(f"Start Rate ({df.index[0].date()}): {start_val:.2f}")
        print(f"End Rate ({df.index[-1].date()}): {end_val:.2f}")
        
        # Monthly Stats
        # Create a temporary DF for resampling
        temp_df = pd.DataFrame({'Close': close_series})
        temp_df['Month'] = temp_df.index.to_period('M')
        
        monthly = temp_df.groupby('Month')['Close'].agg(['first', 'last'])
        monthly['Change'] = monthly['last'] - monthly['first']
        monthly['Change%'] = ((monthly['last'] - monthly['first']) / monthly['first']) * 100
        
        print("\nMonthly Changes:")
        print(monthly)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_rates()
