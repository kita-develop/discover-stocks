import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import time
from utils.db import get_connection, get_vote_results_top_n
from utils.scorer import StockScorer
from utils.common import get_ticker, get_stock_name

def fetch_stock_data(stock_code, end_date_str, days_back=180):
    """
    指定日(end_date)を基準に過去days_back日分のデータを取得する
    end_date_str: "YYYY-MM-DD" (この日を含む)
    """
    try:
        # 終了日の翌日を計算 (yfinanceはendがexclusive)
        end_dt = pd.Timestamp(end_date_str)
        start_dt = end_dt - pd.Timedelta(days=days_back)
        
        yf_end = (end_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        yf_start = start_dt.strftime("%Y-%m-%d")
        
        ticker = get_ticker(stock_code)
        
        # yfinanceでダウンロード
        df = yf.download(
            ticker,
            start=yf_start,
            end=yf_end,
            progress=False,
            threads=False,
            auto_adjust=True
        )
        
        # データが空、または直近の日付が古すぎる（上場廃止やデータ欠損）場合のチェック
        if df.empty:
            return None

        # マルチインデックスの場合はレベル0を選択 (yfinanceの仕様変更対策)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # 取得した最後のデータの日付が、指定したend_dateとあまりに離れていたら除外（例: 5日以上）
        # ただし休日の場合もあるので厳密にはカレンダーチェックが必要だが、簡易的に
        last_date = df.index[-1]
        if (end_dt - last_date).days > 10:
            # print(f"Warning: {stock_code} data is too old (last: {last_date}, target: {end_date_str})")
            return None
            
        return df
        
    except Exception as e:
        print(f"Error fetching data for {stock_code}: {e}")
        return None

def save_results(analysis_date, results):
    """分析結果をDBに保存"""
    conn = get_connection()
    try:
        c = conn.cursor()
        
        # 同一日付・同一銘柄の既存データがあれば削除（再実行時用）
        stock_codes = [r['code'] for r in results]
        if not stock_codes:
            return

        # プレースホルダの生成 (?,?,...)
        placeholders = ','.join(['?'] * len(stock_codes))
        
        delete_sql = f"DELETE FROM analysis_results WHERE analysis_date = ? AND stock_code IN ({placeholders})"
        c.execute(delete_sql, [analysis_date] + stock_codes)
        
        # 挿入
        insert_sql = """
            INSERT INTO analysis_results (
                analysis_date, stock_code, total_score, rank,
                score_trend, score_stability, score_liquidity, score_penalty,
                raw_slope, raw_r2, raw_volatility, raw_mdd, raw_volume_ratio
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        data_to_insert = []
        for r in results:
            data_to_insert.append((
                analysis_date,
                r['code'],
                r['total_score'],
                r['rank'],
                r['score_trend'],
                r['score_stability'],
                r['score_liquidity'],
                r['score_penalty'],
                r['slope'],
                r['r2'],
                r['volatility'],
                r['mdd'],
                r.get('volume_ratio', 0)
            ))
            
        c.executemany(insert_sql, data_to_insert)
        conn.commit()
        
    finally:
        conn.close()

def run_batch_analysis(target_date_str, top_n=20):
    """
    指定日の投票上位銘柄に対してスコアリングを実行する
    """
    print(f"Starting analysis for {target_date_str}...")
    
    # 1. 対象銘柄を取得
    vote_results = get_vote_results_top_n(target_date_str, top_n=top_n)
    if not vote_results:
        print(f"No vote results found for {target_date_str}")
        return []
    
    target_codes = [code for code, _ in vote_results]
    print(f"Found {len(target_codes)} stocks to analyze.")
    
    # 2. データ取得 & 辞書化
    stock_data_dict = {}
    for code in target_codes:
        df = fetch_stock_data(code, target_date_str)
        if df is not None:
            stock_data_dict[code] = df
        else:
            print(f"Skipping {code} (No data)")
            
    if not stock_data_dict:
        print("No valid stock data available.")
        return []

    # 3. スコアリング実行
    scorer = StockScorer(stock_data_dict)
    results = scorer.compute_scores()
    
    # 4. 結果保存
    if results:
        save_results(target_date_str, results)
        print(f"Saved {len(results)} analysis results.")
    
    return results

if __name__ == "__main__":
    # テスト実行用 (今日の日付など)
    today = datetime.now().strftime("%Y-%m-%d")
    # run_batch_analysis(today)
    pass
