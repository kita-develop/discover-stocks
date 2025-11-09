import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import calendar
from utils.db import get_connection, init_price_cache_table
from utils.common import get_stock_name, get_ticker
from functools import lru_cache
import json

# デフォルトの投資配分比率
DEFAULT_ALLOCATION = [25, 20, 15, 10, 5, 5, 5, 5, 5, 5]

# 取引コスト設定
TRADING_COSTS = {
    'commission_rate': 0.001,  # 0.1%の手数料
    'slippage_rate': 0.0005,   # 0.05%のスリッページ
    'spread_rate': 0.0002       # 0.02%のスプレッド
}

def get_price_from_cache(stock_code, date_str):
    """
    キャッシュから株価を取得

    Parameters:
    stock_code (str): 銘柄コード（為替の場合は'USDJPY=X'）
    date_str (str): 日付（YYYY-MM-DD形式）

    Returns:
    float: 株価 または None
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT price FROM price_cache
            WHERE stock_code = ? AND date = ?
        """, (stock_code, date_str))

        result = cursor.fetchone()
        conn.close()

        if result:
            return float(result[0])
        return None

    except Exception as e:
        return None

def save_price_to_cache(stock_code, date_str, price, currency):
    """
    株価をキャッシュに保存

    Parameters:
    stock_code (str): 銘柄コード（為替の場合は'USDJPY=X'）
    date_str (str): 日付（YYYY-MM-DD形式）
    price (float): 株価
    currency (str): 通貨（'JPY', 'USD', 'FX'）
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        updated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # INSERT OR REPLACE を使用して更新
        cursor.execute("""
            INSERT OR REPLACE INTO price_cache
            (stock_code, date, price, currency, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (stock_code, date_str, price, currency, updated_at))

        conn.commit()
        conn.close()

    except Exception as e:
        pass  # エラーが発生してもキャッシュ保存の失敗は無視

@lru_cache(maxsize=1000)
def get_exchange_rate(target_date):
    """
    指定日のUSD/JPY為替レートを取得する関数（キャッシュ付き）

    Parameters:
    target_date (str): 対象日（YYYY-MM-DD形式）

    Returns:
    float: USD/JPY為替レート または None
    """
    # 1. DBキャッシュから取得を試みる
    cached_rate = get_price_from_cache("USDJPY=X", target_date)
    if cached_rate is not None:
        return cached_rate

    # 2. キャッシュにない場合はyfinanceから取得
    try:
        # 前後3日間のデータを取得して、指定日に最も近い営業日の為替レートを取得
        start_date = (pd.Timestamp(target_date) - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
        end_date = (pd.Timestamp(target_date) + pd.Timedelta(days=3)).strftime("%Y-%m-%d")

        df = yf.download(
            "USDJPY=X",
            start=start_date,
            end=end_date,
            progress=False,
            threads=False,
            auto_adjust=True
        )

        if df.empty:
            return None

        # 指定日に最も近い営業日の終値を取得
        target_timestamp = pd.Timestamp(target_date)
        available_dates = df.index

        # 指定日以前の最新の営業日を探す
        valid_dates = available_dates[available_dates <= target_timestamp]
        if len(valid_dates) > 0:
            closest_date = valid_dates[-1]
            rate = float(df.loc[closest_date]["Close"].iloc[0])

            # 3. 取得した値をDBキャッシュに保存
            save_price_to_cache("USDJPY=X", target_date, rate, "FX")

            return rate

        return None

    except Exception as e:
        return None

@lru_cache(maxsize=1000)
def get_stock_price_cached(stock_code, target_date):
    """
    指定日の株価を取得する関数（キャッシュ付き）

    Parameters:
    stock_code (str): 銘柄コード
    target_date (str): 対象日（YYYY-MM-DD形式）

    Returns:
    float: 終値 または None
    """
    # 1. DBキャッシュから取得を試みる
    cached_price = get_price_from_cache(stock_code, target_date)
    if cached_price is not None:
        return cached_price

    # 2. キャッシュにない場合はyfinanceから取得
    try:
        ticker = get_ticker(stock_code)

        # 前後3日間のデータを取得して、指定日に最も近い営業日の株価を取得
        start_date = (pd.Timestamp(target_date) - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
        end_date = (pd.Timestamp(target_date) + pd.Timedelta(days=3)).strftime("%Y-%m-%d")

        df = yf.download(
            ticker,
            start=start_date,
            end=end_date,
            progress=False,
            threads=False,
            auto_adjust=True
        )

        if df.empty:
            return None

        # 指定日に最も近い営業日の終値を取得
        target_timestamp = pd.Timestamp(target_date)
        available_dates = df.index

        # 指定日以前の最新の営業日を探す
        valid_dates = available_dates[available_dates <= target_timestamp]
        if len(valid_dates) > 0:
            closest_date = valid_dates[-1]
            price = float(df.loc[closest_date]["Close"].iloc[0])

            # 異常に大きな価格をチェック（例：1株あたり100万円を超える場合は無効）
            if price > 1000000 or price <= 0:
                return None

            # 3. 取得した値をDBキャッシュに保存
            # 通貨を判定（日本株かどうか）
            currency = 'JPY' if stock_code[0].isdigit() else 'USD'
            save_price_to_cache(stock_code, target_date, price, currency)

            return price

        return None

    except Exception as e:
        return None

def get_next_business_day(date_obj):
    """次の営業日を取得（土日をスキップ）"""
    next_day = date_obj + timedelta(days=1)
    while next_day.weekday() >= 5:  # 土曜日(5)または日曜日(6)
        next_day += timedelta(days=1)
    return next_day

def get_vote_results_for_date_separated(vote_date):
    """指定日の投票結果を日本株と米国株に分けて取得"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 全投票結果を取得
    cursor.execute("""
        SELECT stock_code, COUNT(*) as vote_count
        FROM vote
        WHERE vote_date = ?
        GROUP BY stock_code
        ORDER BY vote_count DESC
    """, (vote_date,))
    
    all_results = cursor.fetchall()
    conn.close()
    
    # 日本株と米国株に分ける
    jpy_stocks = []
    usd_stocks = []
    
    for stock_code, vote_count in all_results:
        if stock_code[0].isdigit():  # 日本株
            jpy_stocks.append((stock_code, vote_count))
        else:  # 米国株
            usd_stocks.append((stock_code, vote_count))
    
    # それぞれのベスト10を返す
    return jpy_stocks[:10], usd_stocks[:10]

def get_vote_results_for_date(vote_date):
    """指定日の投票結果を取得"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT stock_code, COUNT(*) as vote_count
        FROM vote
        WHERE vote_date = ?
        GROUP BY stock_code
        ORDER BY vote_count DESC
        LIMIT 10
    """, (vote_date,))
    
    results = cursor.fetchall()
    conn.close()
    
    return results

def calculate_trading_cost(trade_value, costs=TRADING_COSTS):
    """取引コストを計算"""
    total_cost_rate = costs['commission_rate'] + costs['slippage_rate'] + costs['spread_rate']
    return trade_value * total_cost_rate

def calculate_portfolio_value(portfolio, current_prices, allocation_ratios, exchange_rate=None):
    """ポートフォリオの現在価値を計算（円換算）"""
    total_value = 0
    for i, (stock_code, shares) in enumerate(portfolio.items()):
        if stock_code in current_prices and current_prices[stock_code] is not None:
            price = current_prices[stock_code]
            
            # 異常な株価をチェック
            if price <= 0 or price > 1000000:  # 0以下または100万円を超える場合は無効
                continue
            
            stock_value = shares * price
            
            # 米国株の場合は円換算
            if not stock_code[0].isdigit() and exchange_rate is not None:
                # 異常な為替レートをチェック
                if exchange_rate <= 0 or exchange_rate > 1000:  # 0以下または1000を超える場合は無効
                    continue
                stock_value *= exchange_rate
            
            # 異常な評価額をチェック（10兆円を超える場合は無効）
            if stock_value > 10000000000000:
                continue
                
            total_value += stock_value
    
    return total_value

def simulate_investment(start_date, end_date, initial_jpy, initial_usd, jpy_allocation_ratios, usd_allocation_ratios):
    """投資シミュレーションを実行"""

    # シミュレーション結果を格納するリスト
    simulation_results = []

    # 取引履歴を格納するリスト
    trade_history = []

    # 初期ポートフォリオ
    jpy_portfolio = {}
    usd_portfolio = {}
    jpy_cash = initial_jpy

    # 米国株の初期資金を円からドルに変換（開始日の為替レートを使用）
    start_date_str = start_date.strftime("%Y-%m-%d")
    initial_exchange_rate = get_exchange_rate(start_date_str)
    if initial_exchange_rate is None or initial_exchange_rate <= 0:
        st.error(f"開始日の為替レートが取得できませんでした: {start_date_str}")
        return [], []

    usd_cash = initial_usd / initial_exchange_rate  # 円→ドルに変換

    # 初期価値を記録（円換算）
    initial_total_value = initial_jpy + initial_usd

    # 火曜日と土曜日の投票日を取得
    current_date = start_date
    previous_total_value = initial_total_value  # 前日の総資産価値を記録

    # プログレスバー用の計算
    total_days = (end_date - start_date).days + 1

    # プログレスバーを初期化
    progress_bar = st.progress(0)
    status_text = st.empty()

    while current_date <= end_date:
        # 進捗を更新（現在の日付の位置で計算）
        days_elapsed = (current_date - start_date).days + 1
        progress = min(days_elapsed / total_days, 1.0)
        progress_bar.progress(progress)
        status_text.text(f"処理中: {current_date.strftime('%Y-%m-%d')} ({days_elapsed}/{total_days}日, {progress*100:.1f}%)")
        
        # 土日をスキップ（市場が開いていない日）
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue

        # 為替レートを取得（毎日必要）
        exchange_rate = get_exchange_rate(current_date.strftime("%Y-%m-%d"))
        if exchange_rate is None or exchange_rate <= 0:
            current_date += timedelta(days=1)
            continue

        # 取引処理: 前日が火曜日(1)または土曜日(5)の投票日だった場合、今日が取引日
        yesterday = current_date - timedelta(days=1)
        # 土日をスキップして実際の前営業日を見つける
        while yesterday.weekday() >= 5:
            yesterday -= timedelta(days=1)

        is_trade_day = yesterday.weekday() in [1, 5]

        # 取引コストを初期化（取引日の場合のみ使用）
        total_trading_cost = 0

        if is_trade_day:
            vote_date_str = yesterday.strftime("%Y-%m-%d")
            jpy_stocks, usd_stocks = get_vote_results_for_date_separated(vote_date_str)

            if jpy_stocks or usd_stocks:
                # 今日が取引日
                trade_date = current_date

                # 現在のポートフォリオ価値を計算
                current_jpy_prices = {}
                current_usd_prices = {}

                # 日本株の現在価格を取得
                for stock_code in jpy_portfolio.keys():
                    price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                    if price is not None:
                        current_jpy_prices[stock_code] = price
                
                # 米国株の現在価格を取得
                for stock_code in usd_portfolio.keys():
                    price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                    if price is not None:
                        current_usd_prices[stock_code] = price
                
                # 現在のポートフォリオ価値を計算（円換算）
                jpy_portfolio_value = calculate_portfolio_value(jpy_portfolio, current_jpy_prices, None)
                usd_portfolio_value = calculate_portfolio_value(usd_portfolio, current_usd_prices, None, exchange_rate)

                # 総資産価値（すべて円換算）
                total_value = jpy_portfolio_value + jpy_cash + usd_portfolio_value + (usd_cash * exchange_rate if exchange_rate else 0)

                # --- 日本株の差分調整 ---
                # 日本株の差分売買を実行
                jpy_cash_from_sales = 0
                jpy_cash_for_purchases = 0

                # まず、売却が必要な銘柄を特定
                stocks_to_sell = {}
                for stock_code, current_shares in jpy_portfolio.items():
                    # 目標ポートフォリオにはまだ計算していないので、一旦全売却候補として記録
                    # 実際の売却判断は、投票結果を確認後に行う
                    stocks_to_sell[stock_code] = current_shares

                # 1. 売却が必要な銘柄を処理（投票結果に含まれない銘柄を全売却）
                temp_jpy_portfolio = jpy_portfolio.copy()
                for stock_code, current_shares in jpy_portfolio.items():
                    # 投票結果にこの銘柄が含まれているか確認
                    in_vote_results = any(sc == stock_code for sc, _ in jpy_stocks)
                    
                    if not in_vote_results:
                        # 投票結果に含まれていない銘柄は全売却
                        if stock_code in current_jpy_prices and current_jpy_prices[stock_code] is not None:
                            sell_price = current_jpy_prices[stock_code]
                            sell_value = current_shares * sell_price
                            sell_cost = calculate_trading_cost(sell_value)

                            # 売却による現金増加（手数料を差し引く）
                            jpy_cash_from_sales += sell_value - sell_cost
                            total_trading_cost += sell_cost

                            # 取引履歴に記録
                            trade_history.append({
                                'date': trade_date,
                                'vote_date': yesterday,
                                'stock_code': stock_code,
                                'stock_name': get_stock_name(stock_code),
                                'action': '売却',
                                'shares': current_shares,
                                'price': sell_price,
                                'value': sell_value,
                                'currency': 'JPY',
                                'exchange_rate': None
                            })

                            # 一時ポートフォリオから削除
                            del temp_jpy_portfolio[stock_code]

                # 現金を更新（売却による現金増加を追加）
                jpy_cash += jpy_cash_from_sales

                # 2. 保有銘柄の調整を事前に計算（減額が必要な場合の売却額を把握）
                # まず、現在のポートフォリオ価値と現金から投資額を計算（暫定）
                temp_jpy_portfolio_value = calculate_portfolio_value(temp_jpy_portfolio, current_jpy_prices, None)
                
                if not temp_jpy_portfolio and not usd_portfolio:
                    # 最初の取引
                    temp_jpy_investment_value = initial_jpy  # 円
                else:
                    temp_total_value = temp_jpy_portfolio_value + jpy_cash + usd_portfolio_value + (usd_cash * exchange_rate if exchange_rate else 0)
                    
                    # 異常な価値の場合は初期投資額を使用
                    if temp_total_value > initial_total_value * 50:
                        temp_jpy_investment_value = initial_jpy
                    else:
                        temp_jpy_investment_value = temp_jpy_portfolio_value + jpy_cash  # 円

                # 暫定の目標ポートフォリオを計算
                temp_target_jpy_portfolio = {}
                for i, (stock_code, vote_count) in enumerate(jpy_stocks):
                    if i < len(jpy_allocation_ratios):
                        allocation_ratio = jpy_allocation_ratios[i] / 100.0
                        target_value = temp_jpy_investment_value * allocation_ratio

                        price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                        if price is not None and price > 0:
                            trading_cost = calculate_trading_cost(target_value)
                            net_value = target_value - trading_cost
                            target_shares = int(net_value / price)

                            if target_shares > 0:
                                temp_target_jpy_portfolio[stock_code] = target_shares

                # 減額売却が必要な場合の追加売却額を計算
                additional_cash_from_sales = 0
                for stock_code, current_shares in temp_jpy_portfolio.items():
                    target_shares = temp_target_jpy_portfolio.get(stock_code, 0)

                    if target_shares < current_shares:
                        shares_to_sell = current_shares - target_shares

                        if stock_code in current_jpy_prices and current_jpy_prices[stock_code] is not None:
                            sell_price = current_jpy_prices[stock_code]
                            sell_value = shares_to_sell * sell_price
                            sell_cost = calculate_trading_cost(sell_value)
                            additional_cash_from_sales += sell_value - sell_cost

                # すべての売却後の最終投資額を計算
                final_jpy_cash = jpy_cash + additional_cash_from_sales
                
                # 投資対象の総資産価値を決定（すべての売却後の価値を使用）
                if not temp_jpy_portfolio and not usd_portfolio:
                    # 最初の取引
                    jpy_investment_value = initial_jpy  # 円
                    usd_investment_value_usd = usd_cash  # ドル
                else:
                    # 減額売却後のポートフォリオ価値を計算
                    final_jpy_portfolio_value = temp_jpy_portfolio_value
                    # 減額売却される株の価値を差し引く
                    for stock_code, current_shares in temp_jpy_portfolio.items():
                        target_shares = temp_target_jpy_portfolio.get(stock_code, 0)
                        if target_shares < current_shares:
                            shares_to_sell = current_shares - target_shares
                            if stock_code in current_jpy_prices and current_jpy_prices[stock_code] is not None:
                                final_jpy_portfolio_value -= shares_to_sell * current_jpy_prices[stock_code]
                    
                    # 総資産価値を再計算（すべての売却後の価値）
                    final_total_value = final_jpy_portfolio_value + final_jpy_cash + usd_portfolio_value + (usd_cash * exchange_rate if exchange_rate else 0)
                    
                    # 異常な価値の場合は初期投資額を使用
                    if final_total_value > initial_total_value * 50:
                        jpy_investment_value = initial_jpy
                        usd_investment_value_usd = initial_usd / initial_exchange_rate
                    else:
                        # すべての売却後のポートフォリオ価値に基づいて日本株と米国株の資金を配分
                        jpy_investment_value = final_jpy_portfolio_value + final_jpy_cash  # 円
                        # 米国株の価値をドルで計算
                        usd_portfolio_value_usd = calculate_portfolio_value(usd_portfolio, current_usd_prices, None)  # ドル建て
                        usd_investment_value_usd = usd_portfolio_value_usd + usd_cash  # ドル

                # 新しい目標ポートフォリオを計算（すべての売却後の投資額を使用）
                target_jpy_portfolio = {}
                for i, (stock_code, vote_count) in enumerate(jpy_stocks):
                    if i < len(jpy_allocation_ratios):
                        allocation_ratio = jpy_allocation_ratios[i] / 100.0
                        target_value = jpy_investment_value * allocation_ratio

                        price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                        if price is not None and price > 0:
                            # 取引コストを考慮して目標株数を計算
                            trading_cost = calculate_trading_cost(target_value)
                            net_value = target_value - trading_cost
                            target_shares = int(net_value / price)  # 1株未満は切捨て

                            if target_shares > 0:
                                target_jpy_portfolio[stock_code] = target_shares

                # 3. 保有銘柄の調整（減額が必要な場合の売却）を実行
                for stock_code, current_shares in temp_jpy_portfolio.items():
                    target_shares = target_jpy_portfolio.get(stock_code, 0)

                    if target_shares < current_shares:
                        # 売却が必要
                        shares_to_sell = current_shares - target_shares

                        if stock_code in current_jpy_prices and current_jpy_prices[stock_code] is not None:
                            sell_price = current_jpy_prices[stock_code]
                            sell_value = shares_to_sell * sell_price
                            sell_cost = calculate_trading_cost(sell_value)

                            # 取引コストを記録
                            total_trading_cost += sell_cost

                            # 取引履歴に記録
                            trade_history.append({
                                'date': trade_date,
                                'vote_date': yesterday,
                                'stock_code': stock_code,
                                'stock_name': get_stock_name(stock_code),
                                'action': '売却',
                                'shares': shares_to_sell,
                                'price': sell_price,
                                'value': sell_value,
                                'currency': 'JPY',
                                'exchange_rate': None
                            })

                            # 一時ポートフォリオを更新
                            temp_jpy_portfolio[stock_code] = target_shares

                # 追加売却による現金を更新
                jpy_cash += additional_cash_from_sales

                # 4. 購入が必要な銘柄を処理
                for stock_code, target_shares in target_jpy_portfolio.items():
                    current_shares = temp_jpy_portfolio.get(stock_code, 0)

                    if target_shares > current_shares:
                        # 購入が必要
                        shares_to_buy = target_shares - current_shares

                        price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                        if price is not None and price > 0:
                            buy_value = shares_to_buy * price
                            buy_cost = calculate_trading_cost(buy_value)
                            total_cost = buy_value + buy_cost

                            # 現金が足りる場合のみ購入
                            if total_cost <= jpy_cash:
                                jpy_cash -= total_cost
                                jpy_cash_for_purchases += total_cost
                                total_trading_cost += buy_cost

                                # 取引履歴に記録
                                trade_history.append({
                                    'date': trade_date,
                                    'vote_date': yesterday,
                                    'stock_code': stock_code,
                                    'stock_name': get_stock_name(stock_code),
                                    'action': '購入',
                                    'shares': shares_to_buy,
                                    'price': price,
                                    'value': buy_value,
                                    'currency': 'JPY',
                                    'exchange_rate': None,
                                    'buy_price': price,
                                    'sell_price': None
                                })

                                # 一時ポートフォリオを更新
                                temp_jpy_portfolio[stock_code] = target_shares
                            else:
                                # 現金が足りない場合は、購入できる分だけ購入
                                available_shares = int((jpy_cash * 0.99) / (price * (1 + TRADING_COSTS['commission_rate'] + TRADING_COSTS['slippage_rate'] + TRADING_COSTS['spread_rate'])))
                                if available_shares > 0:
                                    shares_to_buy = available_shares
                                    buy_value = shares_to_buy * price
                                    buy_cost = calculate_trading_cost(buy_value)
                                    total_cost = buy_value + buy_cost

                                    if total_cost <= jpy_cash:
                                        jpy_cash -= total_cost
                                        jpy_cash_for_purchases += total_cost
                                        total_trading_cost += buy_cost

                                        # 取引履歴に記録
                                        trade_history.append({
                                            'date': trade_date,
                                            'vote_date': yesterday,
                                            'stock_code': stock_code,
                                            'stock_name': get_stock_name(stock_code),
                                            'action': '購入',
                                            'shares': shares_to_buy,
                                            'price': price,
                                            'value': buy_value,
                                            'currency': 'JPY',
                                            'exchange_rate': None,
                                            'buy_price': price,
                                            'sell_price': None
                                        })

                                        # 一時ポートフォリオを更新
                                        temp_jpy_portfolio[stock_code] = current_shares + shares_to_buy

                # 日本株ポートフォリオを更新
                jpy_portfolio = temp_jpy_portfolio.copy()

                # --- 米国株の差分調整 ---
                # 米国株の差分売買を実行
                usd_cash_from_sales = 0
                usd_cash_for_purchases = 0

                # 1. 売却が必要な銘柄を処理（投票結果に含まれない銘柄を全売却）
                temp_usd_portfolio = usd_portfolio.copy()
                for stock_code, current_shares in usd_portfolio.items():
                    # 投票結果にこの銘柄が含まれているか確認
                    in_vote_results = any(sc == stock_code for sc, _ in usd_stocks)
                    
                    if not in_vote_results:
                        # 投票結果に含まれていない銘柄は全売却
                        if stock_code in current_usd_prices and current_usd_prices[stock_code] is not None:
                            sell_price = current_usd_prices[stock_code]
                            sell_value_usd = current_shares * sell_price
                            sell_cost_usd = calculate_trading_cost(sell_value_usd)

                            # 売却による現金増加（手数料を差し引く、ドル建て）
                            usd_cash_from_sales += sell_value_usd - sell_cost_usd
                            total_trading_cost += sell_cost_usd * exchange_rate  # 円換算

                            # 取引履歴に記録
                            trade_history.append({
                                'date': trade_date,
                                'vote_date': yesterday,
                                'stock_code': stock_code,
                                'stock_name': get_stock_name(stock_code),
                                'action': '売却',
                                'shares': current_shares,
                                'price': sell_price,
                                'value': sell_value_usd,
                                'currency': 'USD',
                                'exchange_rate': exchange_rate
                            })

                            # 一時ポートフォリオから削除
                            del temp_usd_portfolio[stock_code]

                # 現金を更新（売却による現金増加を追加、ドル建て）
                usd_cash += usd_cash_from_sales

                # 売却後のポートフォリオ価値を再計算（ドル建て）
                temp_usd_portfolio_value_usd = calculate_portfolio_value(temp_usd_portfolio, current_usd_prices, None)  # ドル建て

                # 投資対象の総資産価値を決定（売却後の価値を使用）
                if not jpy_portfolio and not temp_usd_portfolio:
                    # 最初の取引
                    usd_investment_value_usd = usd_cash  # ドル
                else:
                    # 既存のポートフォリオがある場合
                    # 総資産価値を再計算（売却後の価値）
                    temp_total_value = jpy_portfolio_value + jpy_cash + (temp_usd_portfolio_value_usd * exchange_rate) + (usd_cash * exchange_rate if exchange_rate else 0)
                    
                    # 異常な価値の場合は初期投資額を使用
                    if temp_total_value > initial_total_value * 50:
                        usd_investment_value_usd = initial_usd / initial_exchange_rate
                    else:
                        # 売却後のポートフォリオ価値に基づいて米国株の資金を配分（ドル建て）
                        usd_investment_value_usd = temp_usd_portfolio_value_usd + usd_cash  # ドル

                # 2. 保有銘柄の調整を事前に計算（減額が必要な場合の売却額を把握）
                # まず、現在のポートフォリオ価値と現金から投資額を計算（暫定）
                
                if not jpy_portfolio and not temp_usd_portfolio:
                    # 最初の取引
                    temp_usd_investment_value_usd = initial_usd / initial_exchange_rate  # ドル
                else:
                    temp_total_value = jpy_portfolio_value + jpy_cash + (temp_usd_portfolio_value_usd * exchange_rate) + (usd_cash * exchange_rate if exchange_rate else 0)
                    
                    # 異常な価値の場合は初期投資額を使用
                    if temp_total_value > initial_total_value * 50:
                        temp_usd_investment_value_usd = initial_usd / initial_exchange_rate
                    else:
                        temp_usd_investment_value_usd = temp_usd_portfolio_value_usd + usd_cash  # ドル

                # 暫定の目標ポートフォリオを計算
                temp_target_usd_portfolio = {}
                for i, (stock_code, vote_count) in enumerate(usd_stocks):
                    if i < len(usd_allocation_ratios):
                        allocation_ratio = usd_allocation_ratios[i] / 100.0
                        target_value_usd = temp_usd_investment_value_usd * allocation_ratio  # ドル

                        price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                        if price is not None and price > 0:
                            trading_cost_usd = calculate_trading_cost(target_value_usd)
                            net_value_usd = target_value_usd - trading_cost_usd
                            target_shares = int(net_value_usd / price)  # 1株未満は切捨て

                            if target_shares > 0:
                                temp_target_usd_portfolio[stock_code] = target_shares

                # 減額売却が必要な場合の追加売却額を計算
                additional_usd_cash_from_sales = 0
                for stock_code, current_shares in temp_usd_portfolio.items():
                    target_shares = temp_target_usd_portfolio.get(stock_code, 0)

                    if target_shares < current_shares:
                        shares_to_sell = current_shares - target_shares

                        if stock_code in current_usd_prices and current_usd_prices[stock_code] is not None:
                            sell_price = current_usd_prices[stock_code]
                            sell_value_usd = shares_to_sell * sell_price
                            sell_cost_usd = calculate_trading_cost(sell_value_usd)
                            additional_usd_cash_from_sales += sell_value_usd - sell_cost_usd

                # すべての売却後の最終投資額を計算
                final_usd_cash = usd_cash + additional_usd_cash_from_sales
                
                # 投資対象の総資産価値を決定（すべての売却後の価値を使用）
                if not jpy_portfolio and not temp_usd_portfolio:
                    # 最初の取引
                    usd_investment_value_usd = initial_usd / initial_exchange_rate  # ドル
                else:
                    # 減額売却後のポートフォリオ価値を計算（ドル建て）
                    final_usd_portfolio_value_usd = temp_usd_portfolio_value_usd
                    # 減額売却される株の価値を差し引く
                    for stock_code, current_shares in temp_usd_portfolio.items():
                        target_shares = temp_target_usd_portfolio.get(stock_code, 0)
                        if target_shares < current_shares:
                            shares_to_sell = current_shares - target_shares
                            if stock_code in current_usd_prices and current_usd_prices[stock_code] is not None:
                                final_usd_portfolio_value_usd -= shares_to_sell * current_usd_prices[stock_code]
                    
                    # 総資産価値を再計算（すべての売却後の価値）
                    final_total_value = jpy_portfolio_value + jpy_cash + (final_usd_portfolio_value_usd * exchange_rate) + (final_usd_cash * exchange_rate if exchange_rate else 0)
                    
                    # 異常な価値の場合は初期投資額を使用
                    if final_total_value > initial_total_value * 50:
                        usd_investment_value_usd = initial_usd / initial_exchange_rate
                    else:
                        # すべての売却後のポートフォリオ価値に基づいて米国株の資金を配分（ドル建て）
                        usd_investment_value_usd = final_usd_portfolio_value_usd + final_usd_cash  # ドル

                # 新しい目標ポートフォリオを計算（すべての売却後の投資額を使用）
                target_usd_portfolio = {}
                for i, (stock_code, vote_count) in enumerate(usd_stocks):
                    if i < len(usd_allocation_ratios):
                        allocation_ratio = usd_allocation_ratios[i] / 100.0
                        target_value_usd = usd_investment_value_usd * allocation_ratio  # ドル

                        price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                        if price is not None and price > 0:
                            # 取引コストを考慮して目標株数を計算（ドル建て）
                            trading_cost_usd = calculate_trading_cost(target_value_usd)
                            net_value_usd = target_value_usd - trading_cost_usd
                            target_shares = int(net_value_usd / price)  # 1株未満は切捨て

                            if target_shares > 0:
                                target_usd_portfolio[stock_code] = target_shares

                # 3. 保有銘柄の調整（減額が必要な場合の売却）を実行
                for stock_code, current_shares in temp_usd_portfolio.items():
                    target_shares = target_usd_portfolio.get(stock_code, 0)

                    if target_shares < current_shares:
                        # 売却が必要
                        shares_to_sell = current_shares - target_shares

                        if stock_code in current_usd_prices and current_usd_prices[stock_code] is not None:
                            sell_price = current_usd_prices[stock_code]
                            sell_value_usd = shares_to_sell * sell_price
                            sell_cost_usd = calculate_trading_cost(sell_value_usd)

                            # 取引コストを記録
                            total_trading_cost += sell_cost_usd * exchange_rate  # 円換算

                            # 取引履歴に記録
                            trade_history.append({
                                'date': trade_date,
                                'vote_date': yesterday,
                                'stock_code': stock_code,
                                'stock_name': get_stock_name(stock_code),
                                'action': '売却',
                                'shares': shares_to_sell,
                                'price': sell_price,
                                'value': sell_value_usd,
                                'currency': 'USD',
                                'exchange_rate': exchange_rate
                            })

                            # 一時ポートフォリオを更新
                            temp_usd_portfolio[stock_code] = target_shares

                # 追加売却による現金を更新（ドル建て）
                usd_cash += additional_usd_cash_from_sales

                # 4. 購入が必要な銘柄を処理
                for stock_code, target_shares in target_usd_portfolio.items():
                    current_shares = temp_usd_portfolio.get(stock_code, 0)

                    if target_shares > current_shares:
                        # 購入が必要
                        shares_to_buy = target_shares - current_shares

                        price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                        if price is not None and price > 0:
                            buy_value_usd = shares_to_buy * price
                            buy_cost_usd = calculate_trading_cost(buy_value_usd)
                            total_cost_usd = buy_value_usd + buy_cost_usd

                            # 現金が足りる場合のみ購入（ドル建て）
                            if total_cost_usd <= usd_cash:
                                usd_cash -= total_cost_usd
                                usd_cash_for_purchases += total_cost_usd
                                total_trading_cost += buy_cost_usd * exchange_rate  # 円換算

                                # 取引履歴に記録
                                trade_history.append({
                                    'date': trade_date,
                                    'vote_date': yesterday,
                                    'stock_code': stock_code,
                                    'stock_name': get_stock_name(stock_code),
                                    'action': '購入',
                                    'shares': shares_to_buy,
                                    'price': price,
                                    'value': buy_value_usd,  # ドル建て
                                    'currency': 'USD',
                                    'exchange_rate': exchange_rate,
                                    'buy_price': price,
                                    'sell_price': None
                                })

                                # 一時ポートフォリオを更新
                                temp_usd_portfolio[stock_code] = target_shares
                            else:
                                # 現金が足りない場合は、購入できる分だけ購入
                                available_shares = int((usd_cash * 0.99) / (price * (1 + TRADING_COSTS['commission_rate'] + TRADING_COSTS['slippage_rate'] + TRADING_COSTS['spread_rate'])))
                                if available_shares > 0:
                                    shares_to_buy = available_shares
                                    buy_value_usd = shares_to_buy * price
                                    buy_cost_usd = calculate_trading_cost(buy_value_usd)
                                    total_cost_usd = buy_value_usd + buy_cost_usd

                                    if total_cost_usd <= usd_cash:
                                        usd_cash -= total_cost_usd
                                        usd_cash_for_purchases += total_cost_usd
                                        total_trading_cost += buy_cost_usd * exchange_rate  # 円換算

                                        # 取引履歴に記録
                                        trade_history.append({
                                            'date': trade_date,
                                            'vote_date': yesterday,
                                            'stock_code': stock_code,
                                            'stock_name': get_stock_name(stock_code),
                                            'action': '購入',
                                            'shares': shares_to_buy,
                                            'price': price,
                                            'value': buy_value_usd,  # ドル建て
                                            'currency': 'USD',
                                            'exchange_rate': exchange_rate,
                                            'buy_price': price,
                                            'sell_price': None
                                        })

                                        # 一時ポートフォリオを更新
                                        temp_usd_portfolio[stock_code] = current_shares + shares_to_buy

                # 米国株ポートフォリオを更新
                usd_portfolio = temp_usd_portfolio.copy()

        # 毎日の終値でポートフォリオ価値を計算して記録
        # 当日の終値を取得
        daily_jpy_prices = {}
        daily_usd_prices = {}

        # 日本株の終値を取得
        for stock_code in jpy_portfolio.keys():
            price = get_stock_price_cached(stock_code, current_date.strftime("%Y-%m-%d"))
            if price is not None:
                daily_jpy_prices[stock_code] = price

        # 米国株の終値を取得
        for stock_code in usd_portfolio.keys():
            price = get_stock_price_cached(stock_code, current_date.strftime("%Y-%m-%d"))
            if price is not None:
                daily_usd_prices[stock_code] = price

        # 終値でのポートフォリオ価値を計算（円換算）
        daily_jpy_portfolio_value = calculate_portfolio_value(jpy_portfolio, daily_jpy_prices, None)
        daily_usd_portfolio_value = calculate_portfolio_value(usd_portfolio, daily_usd_prices, None, exchange_rate)

        # 当日の総資産価値を計算（すべて円換算）
        daily_total_value = daily_jpy_portfolio_value + jpy_cash + daily_usd_portfolio_value + (usd_cash * exchange_rate if exchange_rate else 0)

        # 日次損益率を計算
        daily_pnl_rate = 0

        # 前日終値との比較（取引日も含む）
        # 取引日の場合は、取引による影響（実現損益など）も含まれる
        if previous_total_value > 0:
            daily_pnl_rate = ((daily_total_value - previous_total_value) / previous_total_value) * 100

        # 結果を記録
        simulation_results.append({
            'date': current_date,
            'vote_date': yesterday if is_trade_day else None,
            'jpy_portfolio': jpy_portfolio.copy(),
            'usd_portfolio': usd_portfolio.copy(),
            'jpy_cash': jpy_cash,  # 円
            'usd_cash': usd_cash,  # ドル
            'total_value': daily_total_value,  # 円換算の総資産
            'exchange_rate': exchange_rate,
            'jpy_portfolio_value': daily_jpy_portfolio_value,  # 円
            'usd_portfolio_value': daily_usd_portfolio_value,  # 円換算
            'trading_cost': total_trading_cost if is_trade_day else 0,  # 円換算
            'daily_pnl_rate': daily_pnl_rate,  # 日次損益率
            'is_trade_day': is_trade_day  # 取引日フラグ
        })

        # 次の日のために前日の総資産価値を更新
        previous_total_value = daily_total_value

        current_date += timedelta(days=1)
    
    # プログレスバーを完了状態にする
    progress_bar.progress(1.0)
    final_days = (end_date - start_date).days + 1
    status_text.text(f"完了: {end_date.strftime('%Y-%m-%d')} ({final_days}/{total_days}日, 100%)")
    
    return simulation_results, trade_history

def calculate_monthly_pnl(simulation_results, year, month):
    """
    指定月の月次損益を計算

    Parameters:
    simulation_results (list): シミュレーション結果
    year (int): 年
    month (int): 月

    Returns:
    dict: {'pnl_rate': 損益率, 'pnl_amount': 損益額} または None
    """
    # 指定月のデータをフィルタリング
    month_data = []
    for result in simulation_results:
        if result['date'].year == year and result['date'].month == month:
            month_data.append(result)

    if not month_data:
        return None

    # 日付でソート
    month_data.sort(key=lambda x: x['date'])

    # 月末の価値を取得
    end_value = month_data[-1]['total_value']

    # 月初の価値を取得（前月末の価値、なければ月初の1日前の想定値）
    # シミュレーション結果全体から前月末の価値を探す
    start_value = None
    month_start_date = month_data[0]['date']

    # 前日の価値を探す
    for result in simulation_results:
        if result['date'] < month_start_date:
            start_value = result['total_value']
        else:
            break

    # 前日の価値が見つからない場合は、月初の最初の日の価値を使用
    if start_value is None:
        start_value = month_data[0]['total_value']

    # 損益率と損益額を計算
    if start_value > 0:
        pnl_amount = end_value - start_value
        pnl_rate = (pnl_amount / start_value) * 100
        return {
            'pnl_rate': pnl_rate,
            'pnl_amount': pnl_amount
        }

    return None

def create_calendar_heatmap(simulation_results, trade_history, year, month):
    """カレンダー形式のヒートマップを作成（実現損益 + 含み損益）"""

    # 指定月のデータをフィルタリング
    month_data = []
    for result in simulation_results:
        if result['date'].year == year and result['date'].month == month:
            month_data.append(result)

    if not month_data:
        return None, []

    # カレンダーを作成
    cal = calendar.monthcalendar(year, month)

    # データを日付でソート
    month_data.sort(key=lambda x: x['date'])

    # 日別の損益を計算（実現損益 + 含み損益）
    daily_pnl_data = {}
    
    # 直前の営業日の実現損益・含み損益を保持（日次変化を計算するため）
    prev_realized_pnl = 0
    prev_unrealized_pnl = 0
    
    # 全シミュレーション結果をソート（直前の営業日を探すため）
    all_results_sorted = sorted(simulation_results, key=lambda x: x['date'])
    
    # 月初日の直前の営業日の累積損益を計算
    if month_data:
        first_date = month_data[0]['date']
        # 直前の営業日を探す
        for prev_result in reversed(all_results_sorted):
            if prev_result['date'] < first_date:
                # 直前の営業日の累積実現損益・含み損益を計算
                prev_date_str = prev_result['date'].strftime('%Y-%m-%d')
                
                # 累積実現損益を計算
                for trade in trade_history:
                    if trade['date'] <= prev_result['date'] and trade['action'] == '売却':
                        buy_trade = None
                        for buy in trade_history:
                            if (buy['stock_code'] == trade['stock_code'] and
                                buy['action'] == '購入' and
                                buy['date'] < trade['date']):
                                if buy_trade is None or buy['date'] > buy_trade['date']:
                                    buy_trade = buy
                        if buy_trade:
                            pnl_per_share = trade['price'] - buy_trade['price']
                            pnl_amount = pnl_per_share * trade['shares']
                            if trade['currency'] == 'USD' and trade['exchange_rate']:
                                pnl_amount *= trade['exchange_rate']
                            prev_realized_pnl += pnl_amount
                
                # 累積含み損益を計算
                prev_holdings = {}
                for trade in trade_history:
                    if trade['date'] <= prev_result['date']:
                        stock_code = trade['stock_code']
                        if stock_code not in prev_holdings:
                            prev_holdings[stock_code] = {
                                'total_shares': 0,
                                'total_cost': 0,
                                'currency': trade['currency']
                            }
                        if trade['action'] == '購入':
                            prev_holdings[stock_code]['total_shares'] += trade['shares']
                            cost = trade['price'] * trade['shares']
                            if trade['currency'] == 'USD' and trade.get('exchange_rate'):
                                cost *= trade['exchange_rate']
                            prev_holdings[stock_code]['total_cost'] += cost
                        elif trade['action'] == '売却':
                            if prev_holdings[stock_code]['total_shares'] > 0:
                                sell_ratio = trade['shares'] / prev_holdings[stock_code]['total_shares']
                                prev_holdings[stock_code]['total_shares'] -= trade['shares']
                                prev_holdings[stock_code]['total_cost'] *= (1 - sell_ratio)
                
                for stock_code, holding in prev_holdings.items():
                    if holding['total_shares'] > 0:
                        current_price = get_stock_price_cached(stock_code, prev_date_str)
                        if current_price is not None and current_price > 0:
                            current_value = current_price * holding['total_shares']
                            if holding['currency'] == 'USD' and prev_result.get('exchange_rate'):
                                current_value *= prev_result['exchange_rate']
                            prev_unrealized_pnl += current_value - holding['total_cost']
                
                break

    # 指定月の全ての日付について処理
    for result in month_data:
        day = result['date'].day
        date_str = result['date'].strftime('%Y-%m-%d')

        # === 1. 実現損益の計算（累積値） ===
        cumulative_realized_pnl = 0
        realized_detail = []

        # 当日以前の全売却取引から実現損益を計算
        for trade in trade_history:
            if trade['date'] <= result['date'] and trade['action'] == '売却':
                # 対応する購入取引を探す（同じ銘柄で最も近い購入）
                buy_trade = None
                for buy in trade_history:
                    if (buy['stock_code'] == trade['stock_code'] and
                        buy['action'] == '購入' and
                        buy['date'] < trade['date']):
                        if buy_trade is None or buy['date'] > buy_trade['date']:
                            buy_trade = buy

                if buy_trade:
                    pnl_per_share = trade['price'] - buy_trade['price']
                    pnl_amount = pnl_per_share * trade['shares']

                    # 円換算（米国株の場合）
                    if trade['currency'] == 'USD' and trade['exchange_rate']:
                        pnl_amount *= trade['exchange_rate']

                    cumulative_realized_pnl += pnl_amount
                    
                    # 当日の売却取引のみ詳細に記録
                    if (trade['date'].year == year and
                        trade['date'].month == month and
                        trade['date'].day == day):
                        realized_detail.append({
                            'stock_code': trade['stock_code'],
                            'pnl': pnl_amount
                        })

        # === 2. 含み損益の計算（累積値） ===
        cumulative_unrealized_pnl = 0
        unrealized_detail = []

        # 当日時点での保有銘柄の購入価格を計算（加重平均）
        holdings = {}  # {stock_code: {'total_shares': X, 'total_cost': Y, 'currency': Z}}

        # 当日以前の全取引履歴から保有状況を再構築
        for trade in trade_history:
            if trade['date'] <= result['date']:
                stock_code = trade['stock_code']

                if stock_code not in holdings:
                    holdings[stock_code] = {
                        'total_shares': 0,
                        'total_cost': 0,
                        'currency': trade['currency']
                    }

                if trade['action'] == '購入':
                    # 購入：株数と総コストを加算
                    holdings[stock_code]['total_shares'] += trade['shares']
                    cost = trade['price'] * trade['shares']

                    # 円換算で保存（米国株の場合）
                    if trade['currency'] == 'USD' and trade.get('exchange_rate'):
                        cost *= trade['exchange_rate']

                    holdings[stock_code]['total_cost'] += cost

                elif trade['action'] == '売却':
                    # 売却：株数と総コストを比例配分で減算
                    if holdings[stock_code]['total_shares'] > 0:
                        sell_ratio = trade['shares'] / holdings[stock_code]['total_shares']
                        holdings[stock_code]['total_shares'] -= trade['shares']
                        holdings[stock_code]['total_cost'] *= (1 - sell_ratio)

        # 当日の保有銘柄について含み損益を計算
        for stock_code, holding in holdings.items():
            if holding['total_shares'] > 0:
                # 現在価格を取得
                current_price = get_stock_price_cached(stock_code, date_str)

                if current_price is not None and current_price > 0:
                    # 評価額を計算
                    current_value = current_price * holding['total_shares']

                    # 米国株の場合は円換算
                    if holding['currency'] == 'USD' and result.get('exchange_rate'):
                        current_value *= result['exchange_rate']

                    # 含み損益 = 評価額 - 取得原価
                    pnl = current_value - holding['total_cost']
                    cumulative_unrealized_pnl += pnl
                    unrealized_detail.append({
                        'stock_code': stock_code,
                        'pnl': pnl
                    })

        # === 3. 日次変化を計算 ===
        # 実現損益の日次変化（当日の累積値 - 前日の累積値）
        daily_realized_pnl_change = cumulative_realized_pnl - prev_realized_pnl
        
        # 含み損益の日次変化（当日の累積値 - 前日の累積値）
        daily_unrealized_pnl_change = cumulative_unrealized_pnl - prev_unrealized_pnl
        
        # 合計損益の日次変化
        total_pnl_change = daily_realized_pnl_change + daily_unrealized_pnl_change

        # 日次損益率を取得
        daily_pnl_rate = result.get('daily_pnl_rate', 0)

        daily_pnl_data[day] = {
            'total_pnl': total_pnl_change,  # 日次変化
            'realized_pnl': daily_realized_pnl_change,  # 日次変化
            'unrealized_pnl': daily_unrealized_pnl_change,  # 日次変化
            'realized_detail': realized_detail,
            'unrealized_detail': unrealized_detail,
            'daily_pnl_rate': daily_pnl_rate,
            # 累積値も保持（次の日の計算のため）
            '_cumulative_realized_pnl': cumulative_realized_pnl,
            '_cumulative_unrealized_pnl': cumulative_unrealized_pnl
        }
        
        # 次の日のために前日の累積値を更新
        prev_realized_pnl = cumulative_realized_pnl
        prev_unrealized_pnl = cumulative_unrealized_pnl

    # 月次損益を計算
    monthly_pnl = calculate_monthly_pnl(simulation_results, year, month)

    # カレンダーのHTMLを作成
    month_name = calendar.month_name[month]
    title = f"{year}年{month}月"

    # 月次損益情報を追加
    if monthly_pnl:
        pnl_rate = monthly_pnl['pnl_rate']
        pnl_amount = monthly_pnl['pnl_amount']

        # プラスマイナスの符号を付ける
        pnl_rate_str = f"+{pnl_rate:.2f}" if pnl_rate >= 0 else f"{pnl_rate:.2f}"
        pnl_amount_str = f"+{pnl_amount:,.0f}" if pnl_amount >= 0 else f"{pnl_amount:,.0f}"

        # 色を設定（プラスは青、マイナスは赤）
        color = "blue" if pnl_rate >= 0 else "red"

        title += f" | <span style='color: {color};'>損益率: {pnl_rate_str}% | 損益額: {pnl_amount_str}円</span>"

    html = f"<h3>{title}</h3>"
    # darkモード対応のスタイルを追加（Streamlitのテーマに合わせる）
    html += """
    <style>
        table.calendar-table {
            border-collapse: collapse;
            width: 100%;
            background-color: transparent;
            color: inherit;
        }
        table.calendar-table th {
            background-color: transparent;
            color: inherit;
            padding: 8px;
            border: 1px solid rgba(250, 250, 250, 0.2);
        }
        table.calendar-table td {
            background-color: transparent;
            color: inherit;
        }
    </style>
    """
    html += "<table class='calendar-table' style='border-collapse: collapse; width: 100%;'>"

    # 曜日のヘッダー
    html += "<tr><th>月</th><th>火</th><th>水</th><th>木</th><th>金</th><th>土</th><th>日</th></tr>"

    for week in cal:
        html += "<tr>"
        for day in week:
            if day == 0:
                html += "<td></td>"
            else:
                if day in daily_pnl_data:
                    data = daily_pnl_data[day]
                    total_pnl = data['total_pnl']
                    realized_pnl = data['realized_pnl']
                    unrealized_pnl = data['unrealized_pnl']
                    daily_pnl_rate = data.get('daily_pnl_rate', 0)

                    # 枠線の色を決定（損益に関係なく固定色）
                    border_width = 2
                    border_color = "rgba(128, 128, 128, 0.6)"  # グレー（固定、Light/Dark両方で見える）

                    # ツールチップ用のタイトルを作成（日次変化）
                    tooltip = f"合計(日次変化): {total_pnl:,.0f}円\\n実現(日次変化): {realized_pnl:,.0f}円\\n含み(日次変化): {unrealized_pnl:,.0f}円\\n損益率: {daily_pnl_rate:.2f}%"

                    # 表示テキストを作成（万円単位、日次変化）
                    # 色を決定（プラスは青、マイナスは赤）
                    total_color = "blue" if total_pnl >= 0 else "red"
                    realized_color = "blue" if realized_pnl >= 0 else "red"
                    unrealized_color = "blue" if unrealized_pnl >= 0 else "red"
                    rate_color = "blue" if daily_pnl_rate >= 0 else "red"
                    
                    display_text = f"<strong style='font-size: 14px;'>{day}</strong><br/>"
                    display_text += f"<small style='color: {total_color};'>合計: {total_pnl/10000:+,.0f}万</small><br/>"
                    display_text += f"<small style='color: {realized_color};'>実: {realized_pnl/10000:+,.0f}万</small><br/>"
                    display_text += f"<small style='color: {unrealized_color};'>含: {unrealized_pnl/10000:+,.0f}万</small><br/>"

                    # 損益率を追加（色付き）
                    rate_sign = "+" if daily_pnl_rate >= 0 else ""
                    display_text += f"<small style='color: {rate_color}; font-weight: bold;'>{rate_sign}{daily_pnl_rate:.2f}%</small>"

                    # darkモード対応の背景色（透明にしてStreamlitのテーマに合わせる）
                    html += f"<td style='background-color: transparent; text-align: center; padding: 5px; border: {border_width}px solid {border_color};' title='{tooltip}'>{display_text}</td>"
                else:
                    html += f"<td style='background-color: transparent; text-align: center; padding: 5px; border: 2px solid rgba(128, 128, 128, 0.6);'>{day}</td>"
        html += "</tr>"

    html += "</table>"
    html += "<p style='font-size: 12px; color: #666;'>※ 合計=実現損益+含み損益の日次変化、実=実現損益の日次変化、含=含み損益の日次変化（単位：万円、直前の営業日との差分）、損益率=日次損益率（%）</p>"

    # グラフ用のデータを準備
    chart_data = []
    for day, data in sorted(daily_pnl_data.items()):
        chart_data.append({
            'day': day,
            'total_pnl': data['total_pnl']
        })

    return html, chart_data

def create_yearly_summary(simulation_results, year):
    """
    指定年の月別損益サマリーを作成

    Parameters:
    simulation_results (list): シミュレーション結果
    year (int): 年

    Returns:
    pd.DataFrame: 月別損益サマリー
    """
    monthly_data = []

    for month in range(1, 13):
        monthly_pnl = calculate_monthly_pnl(simulation_results, year, month)

        if monthly_pnl:
            pnl_rate = monthly_pnl['pnl_rate']
            pnl_amount = monthly_pnl['pnl_amount']

            # プラスマイナスの符号を付ける
            pnl_rate_str = f"+{pnl_rate:.2f}%" if pnl_rate >= 0 else f"{pnl_rate:.2f}%"
            pnl_amount_str = f"+{pnl_amount:,.0f}" if pnl_amount >= 0 else f"{pnl_amount:,.0f}"

            monthly_data.append({
                '月': f"{month}月",
                '損益率': pnl_rate_str,
                '損益額（円）': pnl_amount_str,
                '_pnl_rate_value': pnl_rate,  # ソート用の数値
                '_pnl_amount_value': pnl_amount  # ソート用の数値
            })
        else:
            monthly_data.append({
                '月': f"{month}月",
                '損益率': '-',
                '損益額（円）': '-',
                '_pnl_rate_value': 0,
                '_pnl_amount_value': 0
            })

    df = pd.DataFrame(monthly_data)

    return df

def calculate_risk_metrics(simulation_results):
    """リスク指標を計算"""
    if len(simulation_results) < 2:
        return {}
    
    values = [result['total_value'] for result in simulation_results]
    
    # 日次リターンを計算
    daily_returns = []
    for i in range(1, len(values)):
        if values[i-1] > 0:
            daily_return = (values[i] - values[i-1]) / values[i-1]
            # 極端に大きな日次リターンを制限（±50%）
            if daily_return > 0.5:
                daily_return = 0.5
            elif daily_return < -0.5:
                daily_return = -0.5
            daily_returns.append(daily_return)
    
    if not daily_returns:
        return {}
    
    # 年率リターン
    total_return = (values[-1] - values[0]) / values[0] if values[0] > 0 else 0
    days = len(simulation_results)
    
    # オーバーフローを防ぐため、極端に大きなリターンの場合は制限
    if total_return > 10:  # 1000%を超える場合は制限
        total_return = 10
    elif total_return < -0.9:  # -90%を下回る場合は制限
        total_return = -0.9
    
    try:
        annual_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0
    except OverflowError:
        # オーバーフローが発生した場合は安全な値を使用
        annual_return = 10 if total_return > 0 else -0.9
    
    # 年率ボラティリティ
    daily_volatility = np.std(daily_returns)
    annual_volatility = daily_volatility * np.sqrt(365)
    
    # シャープレシオ（リスクフリーレートを2%と仮定）
    risk_free_rate = 0.02
    sharpe_ratio = (annual_return - risk_free_rate) / annual_volatility if annual_volatility > 0 else 0
    
    # 最大ドローダウン
    peak = values[0]
    max_drawdown = 0
    for value in values:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak
        max_drawdown = max(max_drawdown, drawdown)
    
    return {
        'annual_return': annual_return * 100,
        'annual_volatility': annual_volatility * 100,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown * 100,
        'total_trades': len(simulation_results)
    }

def create_performance_chart(simulation_results, initial_investment):
    """パフォーマンス推移チャートを作成"""
    if not simulation_results:
        return None

    # シミュレーション結果のデータを取得
    dates = [result['date'] for result in simulation_results]
    values = [result['total_value'] for result in simulation_results]

    # 万単位に変換
    values_in_man = [value / 10000 for value in values]
    initial_investment_in_man = initial_investment / 10000

    # 初期投資額からの変化率を計算
    returns = [((value - initial_investment) / initial_investment) * 100 if initial_investment > 0 else 0 for value in values]

    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=('ポートフォリオ価値', '累積リターン(%)'),
        vertical_spacing=0.1
    )

    # ポートフォリオ価値のチャート（万単位）
    fig.add_trace(
        go.Scatter(x=dates, y=values_in_man, mode='lines', name='ポートフォリオ価値', line=dict(color='blue')),
        row=1, col=1
    )

    # 初期投資額の水平線を追加
    fig.add_trace(
        go.Scatter(
            x=[dates[0], dates[-1]],
            y=[initial_investment_in_man, initial_investment_in_man],
            mode='lines',
            name='初期投資額',
            line=dict(color='red', dash='dash', width=2)
        ),
        row=1, col=1
    )

    # 累積リターンのチャート
    fig.add_trace(
        go.Scatter(x=dates, y=returns, mode='lines', name='累積リターン(%)', line=dict(color='green')),
        row=2, col=1
    )

    # 0%の水平線を追加（リターンチャート用）
    fig.add_trace(
        go.Scatter(
            x=[dates[0], dates[-1]],
            y=[0, 0],
            mode='lines',
            name='0%ライン',
            line=dict(color='gray', dash='dash', width=1),
            showlegend=False
        ),
        row=2, col=1
    )

    fig.update_layout(
        height=600,
        showlegend=True,
        title_text="投資シミュレーション結果"
    )

    fig.update_xaxes(title_text="日付", row=2, col=1)
    fig.update_yaxes(title_text="価値 (万円)", row=1, col=1)
    fig.update_yaxes(title_text="リターン (%)", row=2, col=1)

    return fig

def show(selected_date):
    # 株価キャッシュテーブルを初期化
    init_price_cache_table()

    st.title("投資シミュレーション")

    # 設定パネル
    with st.expander("シミュレーション設定", expanded=True):
        # 1行目: 開始日、終了日
        col1_row1, col2_row1 = st.columns(2)
        with col1_row1:
            start_date = st.date_input(
                "開始日",
                value=date(2025, 7, 1),
                min_value=date(2020, 1, 1),
                max_value=datetime.now().date()
            )
        with col2_row1:
            end_date = st.date_input(
                "終了日",
                value=datetime.now().date(),
                min_value=date(2020, 1, 1),
                max_value=datetime.now().date()
            )
        
        # 2行目: 日本株初期資金、米国株初期資金
        col1_row2, col2_row2 = st.columns(2)
        with col1_row2:
            initial_jpy = st.number_input(
                "日本株初期資金 (円)",
                value=5000000,
                min_value=0,
                step=100000
            )
        with col2_row2:
            initial_usd = st.number_input(
                "米国株初期資金 (円)",
                value=5000000,
                min_value=0,
                step=100000
            )
        
        # 3行目以降: 投資配分比率
        st.write("**投資配分比率 (%)**")
        jpy_allocation_ratios = []
        usd_allocation_ratios = []
        
        for i in range(10):
            col1, col2 = st.columns(2)
            with col1:
                jpy_ratio = st.number_input(
                    f"日本株第{i+1}位",
                    value=DEFAULT_ALLOCATION[i],
                    min_value=0,
                    max_value=100,
                    step=1,
                    key=f"jpy_allocation_{i}"
                )
                jpy_allocation_ratios.append(jpy_ratio)
            
            with col2:
                usd_ratio = st.number_input(
                    f"米国株第{i+1}位",
                    value=DEFAULT_ALLOCATION[i],
                    min_value=0,
                    max_value=100,
                    step=1,
                    key=f"usd_allocation_{i}"
                )
                usd_allocation_ratios.append(usd_ratio)
        
        # 配分の合計を表示
        jpy_total_allocation = sum(jpy_allocation_ratios)
        usd_total_allocation = sum(usd_allocation_ratios)
        
        if jpy_total_allocation != 100:
            st.warning(f"日本株配分の合計が100%ではありません（現在: {jpy_total_allocation}%）")
        if usd_total_allocation != 100:
            st.warning(f"米国株配分の合計が100%ではありません（現在: {usd_total_allocation}%）")
    
    # シミュレーション実行ボタン
    if st.button("シミュレーション実行", type="primary"):
        # 日付の妥当性チェック
        if start_date > end_date:
            st.error("開始日は終了日より前である必要があります。")
        else:
            with st.spinner("シミュレーションを実行中..."):
                try:
                    simulation_results, trade_history = simulate_investment(
                        start_date,
                        end_date,
                        initial_jpy,
                        initial_usd,
                        jpy_allocation_ratios,
                        usd_allocation_ratios
                    )

                    if simulation_results:
                        st.session_state.simulation_results = simulation_results
                        st.session_state.trade_history = trade_history
                        st.success("シミュレーションが完了しました！")
                    else:
                        st.warning("シミュレーション対象のデータが見つかりませんでした。")
                except Exception as e:
                    st.error(f"シミュレーション実行中にエラーが発生しました: {str(e)}")
    
    # 結果表示
    if 'simulation_results' in st.session_state and st.session_state.simulation_results:
        simulation_results = st.session_state.simulation_results
        
        # サマリー情報
        st.subheader("シミュレーション結果サマリー")
        
        initial_value = initial_jpy + initial_usd
        final_value = simulation_results[-1]['total_value'] if simulation_results else initial_value
        total_return = ((final_value - initial_value) / initial_value) * 100 if initial_value > 0 else 0
        
        # リスク指標を計算
        risk_metrics = calculate_risk_metrics(simulation_results)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("初期投資額", f"¥{initial_value/10000:,.0f}万")
        with col2:
            st.metric("最終価値", f"¥{final_value/10000:,.0f}万")
        with col3:
            st.metric("総リターン", f"{total_return:.2f}%")
        with col4:
            st.metric("取引回数", len(simulation_results))
        
        # リスク指標の表示
        if risk_metrics:
            st.subheader("リスク指標")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("年率リターン", f"{risk_metrics['annual_return']:.2f}%")
            with col2:
                st.metric("年率ボラティリティ", f"{risk_metrics['annual_volatility']:.2f}%")
            with col3:
                st.metric("シャープレシオ", f"{risk_metrics['sharpe_ratio']:.2f}")
            with col4:
                st.metric("最大ドローダウン", f"{risk_metrics['max_drawdown']:.2f}%")
        
        # パフォーマンスチャート
        st.subheader("パフォーマンス推移")
        fig = create_performance_chart(simulation_results, initial_value)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        
        # カレンダー表示
        st.subheader("損益カレンダー")

        # 表示モード選択
        display_mode = st.radio("表示モード", ["月別表示", "年間表示"], horizontal=True)

        # 年の選択
        if simulation_results:
            min_year = min(result['date'].year for result in simulation_results)
            max_year = max(result['date'].year for result in simulation_results)

            if display_mode == "月別表示":
                # 月別表示モード
                # 前月・次月のナビゲーション
                # 初期表示を終了日の年・月にする
                if 'selected_year_monthly' not in st.session_state or 'selected_month_monthly' not in st.session_state:
                    # 終了日（最後のシミュレーション結果の日付）の年・月を取得
                    if simulation_results:
                        end_date_result = simulation_results[-1]['date']
                        st.session_state.selected_year_monthly = end_date_result.year
                        st.session_state.selected_month_monthly = end_date_result.month
                    else:
                        st.session_state.selected_year_monthly = max_year
                        st.session_state.selected_month_monthly = 12
                
                col1, col2, col3, col4 = st.columns([1, 2, 2, 1])
                
                # 前月ボタン
                with col1:
                    if st.button("◀", key="prev_month", help="前月"):
                        st.session_state.selected_month_monthly -= 1
                        if st.session_state.selected_month_monthly < 1:
                            st.session_state.selected_month_monthly = 12
                            st.session_state.selected_year_monthly -= 1
                            if st.session_state.selected_year_monthly < min_year:
                                st.session_state.selected_year_monthly = min_year
                                st.session_state.selected_month_monthly = 1
                        st.rerun()
                
                # 年選択
                with col2:
                    year_index = list(range(min_year, max_year + 1)).index(st.session_state.selected_year_monthly) if st.session_state.selected_year_monthly in range(min_year, max_year + 1) else max_year - min_year
                    selected_year = st.selectbox("年", range(min_year, max_year + 1), index=year_index, key="year_monthly")
                    if selected_year != st.session_state.selected_year_monthly:
                        st.session_state.selected_year_monthly = selected_year
                
                # 月選択
                with col3:
                    month_index = st.session_state.selected_month_monthly - 1 if 1 <= st.session_state.selected_month_monthly <= 12 else 11
                    selected_month = st.selectbox("月", range(1, 13), index=month_index, key="month_monthly")
                    if selected_month != st.session_state.selected_month_monthly:
                        st.session_state.selected_month_monthly = selected_month
                
                # 次月ボタン
                with col4:
                    if st.button("▶", key="next_month", help="次月"):
                        st.session_state.selected_month_monthly += 1
                        if st.session_state.selected_month_monthly > 12:
                            st.session_state.selected_month_monthly = 1
                            st.session_state.selected_year_monthly += 1
                            if st.session_state.selected_year_monthly > max_year:
                                st.session_state.selected_year_monthly = max_year
                                st.session_state.selected_month_monthly = 12
                        st.rerun()
                
                # session_stateから値を取得（ボタンで変更された場合に反映）
                selected_year = st.session_state.selected_year_monthly
                selected_month = st.session_state.selected_month_monthly

                # カレンダーを表示
                result = create_calendar_heatmap(simulation_results, st.session_state.trade_history, selected_year, selected_month)
                if result:
                    calendar_html, chart_data = result
                    st.markdown(calendar_html, unsafe_allow_html=True)
                    
                    # 棒グラフを表示
                    # 1ヶ月分の日付を生成（データがない日も含める）
                    days_in_month = calendar.monthrange(selected_year, selected_month)[1]
                    all_days = list(range(1, days_in_month + 1))
                    
                    # データがある日付を辞書に変換
                    chart_dict = {}
                    if chart_data:
                        chart_dict = {row['day']: row['total_pnl'] / 10000 for row in chart_data}
                    
                    # 全日のデータを作成（データがない日は0）
                    full_chart_data = []
                    for day in all_days:
                        pnl_value = chart_dict.get(day, 0)
                        full_chart_data.append({
                            'day': day,
                            'total_pnl_man': pnl_value
                        })
                    
                    chart_df = pd.DataFrame(full_chart_data)
                    
                    fig = px.bar(
                        chart_df,
                        x='day',
                        y='total_pnl_man',
                        title=f"{selected_year}年{selected_month}月 日次損益推移",
                        labels={'total_pnl_man': '損益額（万円）', 'day': '日付'},
                        color='total_pnl_man',
                        color_continuous_scale=['red', 'white', 'blue'],
                        color_continuous_midpoint=0
                    )
                    fig.update_layout(
                        height=400,
                        showlegend=False,
                        xaxis_title="日付",
                        yaxis_title="損益額（万円）",
                        xaxis=dict(
                            tickmode='linear',
                            tick0=1,
                            dtick=1,
                            range=[0.5, days_in_month + 0.5]
                        )
                    )
                    # ホバー時の表示をカスタマイズ（小数点以下1桁、四捨五入）
                    fig.update_traces(
                        marker_line_width=0,
                        hovertemplate='日付: %{x}日<br>損益額: %{y:.1f}万円<extra></extra>'
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("選択された月のデータがありません。")

            else:
                # 年間表示モード
                selected_year = st.selectbox("年", range(min_year, max_year + 1), index=max_year - min_year, key="year_yearly")

                # 年間サマリーを作成
                yearly_df = create_yearly_summary(simulation_results, selected_year)

                if not yearly_df.empty:
                    # 表示用のDataFrameを作成（ソート用カラムを除外）
                    display_df = yearly_df[['月', '損益率', '損益額（円）']].copy()

                    # DataFrameのスタイリング関数
                    def style_yearly_summary(df):
                        def color_cells(row):
                            # 対応する行のインデックスを取得
                            idx = row.name
                            pnl_rate_value = yearly_df.loc[idx, '_pnl_rate_value']

                            # 色を決定
                            if pnl_rate_value > 0:
                                color = 'blue'
                            elif pnl_rate_value < 0:
                                color = 'red'
                            else:
                                color = 'black'

                            # 各セルにスタイルを適用
                            return [''] + [f'color: {color}'] * 2  # 月列以外に色を適用

                        return df.style.apply(color_cells, axis=1)

                    # スタイル付きのDataFrameを表示
                    st.dataframe(style_yearly_summary(display_df), use_container_width=True, height=500)

                    # 年間合計を計算
                    total_pnl_amount = yearly_df['_pnl_amount_value'].sum()
                    total_pnl_amount_str = f"+{total_pnl_amount:,.0f}" if total_pnl_amount >= 0 else f"{total_pnl_amount:,.0f}"

                    st.info(f"**{selected_year}年 年間合計損益額: {total_pnl_amount_str}円**")
                    
                    # 棒グラフを表示
                    chart_df = yearly_df.copy()
                    chart_df['month_num'] = range(1, 13)
                    chart_df['date'] = pd.to_datetime(f"{selected_year}-" + chart_df['month_num'].astype(str) + "-01")
                    chart_df['_pnl_amount_value_man'] = chart_df['_pnl_amount_value'] / 10000  # 万円単位に変換
                    
                    fig = px.bar(
                        chart_df,
                        x='date',
                        y='_pnl_amount_value_man',
                        title=f"{selected_year}年 月別損益推移",
                        labels={'_pnl_amount_value_man': '損益額（万円）', 'date': '月'},
                        color='_pnl_amount_value_man',
                        color_continuous_scale=['red', 'white', 'blue'],
                        color_continuous_midpoint=0
                    )
                    fig.update_layout(
                        height=400,
                        showlegend=False,
                        xaxis_title="月",
                        yaxis_title="損益額（万円）",
                        xaxis=dict(
                            tickmode='array',
                            tickvals=chart_df['date'],
                            ticktext=[f"{i}月" for i in range(1, 13)]
                        )
                    )
                    # ホバー時の表示をカスタマイズ（小数点以下1桁、四捨五入）
                    fig.update_traces(
                        marker_line_width=0,
                        hovertemplate='月: %{x}<br>損益額: %{y:.1f}万円<extra></extra>'
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("選択された年のデータがありません。")
        
        # ポートフォリオ詳細表示
        st.subheader("ポートフォリオ詳細")
        
        if simulation_results:
            latest_result = simulation_results[-1]
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**日本株ポートフォリオ**")
                if latest_result['jpy_portfolio']:
                    jpy_df = pd.DataFrame([
                        {
                            '銘柄コード': stock_code,
                            '銘柄名': get_stock_name(stock_code),
                            '保有株数': f"{shares:.2f}",
                            '現在価格': f"¥{get_stock_price_cached(stock_code, latest_result['date'].strftime('%Y-%m-%d')) or 0:.2f}",
                            '評価額': f"¥{shares * (get_stock_price_cached(stock_code, latest_result['date'].strftime('%Y-%m-%d')) or 0):,.0f}"
                        }
                        for stock_code, shares in latest_result['jpy_portfolio'].items()
                    ])
                    st.dataframe(jpy_df, use_container_width=True)
                else:
                    st.info("日本株の保有はありません")
            
            with col2:
                st.write("**米国株ポートフォリオ**")
                if latest_result['usd_portfolio']:
                    usd_df = pd.DataFrame([
                        {
                            '銘柄コード': stock_code,
                            '銘柄名': get_stock_name(stock_code),
                            '保有株数': f"{shares:.2f}",
                            '現在価格': f"${get_stock_price_cached(stock_code, latest_result['date'].strftime('%Y-%m-%d')) or 0:.2f}",
                            '評価額': f"¥{shares * (get_stock_price_cached(stock_code, latest_result['date'].strftime('%Y-%m-%d')) or 0) * (latest_result['exchange_rate'] or 1):,.0f}"
                        }
                        for stock_code, shares in latest_result['usd_portfolio'].items()
                    ])
                    st.dataframe(usd_df, use_container_width=True)
                else:
                    st.info("米国株の保有はありません")
        
        # 取引履歴の詳細表示
        st.subheader("取引履歴詳細")
        
        if 'trade_history' in st.session_state and st.session_state.trade_history:
            trade_history = st.session_state.trade_history
            
            # 取引履歴を銘柄ごとに整理して損益を計算
            trade_summary = {}
            for trade in trade_history:
                stock_code = trade['stock_code']
                if stock_code not in trade_summary:
                    trade_summary[stock_code] = {
                        'stock_name': trade['stock_name'],
                        'currency': trade['currency'],
                        'buy_trades': [],
                        'sell_trades': []
                    }
                
                if trade['action'] == '購入':
                    trade_summary[stock_code]['buy_trades'].append(trade)
                else:
                    trade_summary[stock_code]['sell_trades'].append(trade)
            
            # 銘柄毎の損益を計算（簡易版）
            detailed_trades = []
            for stock_code, summary in trade_summary.items():
                # 購入と売却を時系列でソート
                buy_trades = sorted(summary['buy_trades'], key=lambda x: x['date'])
                sell_trades = sorted(summary['sell_trades'], key=lambda x: x['date'])
                
                # 購入と売却を1対1でペアリング
                for i, sell_trade in enumerate(sell_trades):
                    if i < len(buy_trades):
                        buy_trade = buy_trades[i]
                        
                        # 損益を計算
                        pnl_per_share = sell_trade['price'] - buy_trade['price']
                        pnl_amount = pnl_per_share * sell_trade['shares']
                        pnl_rate = (pnl_per_share / buy_trade['price']) * 100 if buy_trade['price'] > 0 else 0
                        
                        # 円換算の損益（米国株の場合）
                        currency = buy_trade['currency']
                        exchange_rate = buy_trade['exchange_rate']
                        if currency == 'USD' and exchange_rate:
                            pnl_amount_jpy = pnl_amount * exchange_rate
                        else:
                            pnl_amount_jpy = pnl_amount
                        
                        detailed_trades.append({
                            '購入日': buy_trade['date'].strftime('%Y-%m-%d'),
                            '売却日': sell_trade['date'].strftime('%Y-%m-%d'),
                            '銘柄コード': stock_code,
                            '銘柄名': summary['stock_name'],
                            '通貨': currency,
                            '株数': sell_trade['shares'],
                            '購入価格': buy_trade['price'],
                            '売却価格': sell_trade['price'],
                            '損益額': pnl_amount,
                            '損益率(%)': round(pnl_rate, 2),
                            '損益額(円)': round(pnl_amount_jpy, 0) if currency == 'USD' else round(pnl_amount, 0)
                        })
            
            if detailed_trades:
                df_trades = pd.DataFrame(detailed_trades)
                
                # 損益額でソート
                df_trades = df_trades.sort_values('損益額(円)', ascending=False)
                
                # スタイリング
                def style_pnl(df):
                    def color_row(row):
                        color = 'red' if row['損益率(%)'] < 0 else 'blue'
                        return [f'color: {color}'] * len(row)
                    return df.style.apply(color_row, axis=1)
                
                st.dataframe(style_pnl(df_trades), use_container_width=True)
                
                # CSVダウンロード
                csv = df_trades.to_csv(index=False).encode('shift-jis', errors='replace')
                st.download_button(
                    label="取引履歴詳細をCSVダウンロード",
                    data=csv,
                    file_name=f"trade_history_detail_{start_date.strftime('%Y%m%d')}.csv",
                    mime='text/csv',
                )
                
                # 統計情報
                st.subheader("取引統計")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    total_trades = len(df_trades)
                    st.metric("総取引回数", total_trades)
                with col2:
                    winning_trades = len(df_trades[df_trades['損益率(%)'] > 0])
                    st.metric("勝ちトレード", winning_trades)
                with col3:
                    losing_trades = len(df_trades[df_trades['損益率(%)'] < 0])
                    st.metric("負けトレード", losing_trades)
                with col4:
                    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
                    st.metric("勝率", f"{win_rate:.1f}%")
            else:
                st.info("取引履歴がありません。")
        
        # 詳細データテーブル
        st.subheader("ポートフォリオ変更履歴")
        
        # データフレームを作成
        df_data = []
        for result in simulation_results:
            df_data.append({
                '取引日': result['date'].strftime('%Y-%m-%d'),
                '投票日': result['vote_date'].strftime('%Y-%m-%d') if result['vote_date'] else '-',
                'ポートフォリオ価値': f"¥{result['total_value']:,.0f}",
                '日本株価値': f"¥{result['jpy_portfolio_value']:,.0f}",
                '米国株価値': f"¥{result['usd_portfolio_value']:,.0f}",
                '日本株現金': f"¥{result['jpy_cash']:,.0f}",
                '米国株現金': f"${result['usd_cash']:,.2f}",
                '為替レート': f"{result['exchange_rate']:.2f}" if result['exchange_rate'] else "N/A",
                '取引コスト': f"¥{result['trading_cost']:,.0f}",
                '日本株銘柄数': len(result['jpy_portfolio']),
                '米国株銘柄数': len(result['usd_portfolio'])
            })
        
        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True)
        
        # CSVダウンロード
        csv = df.to_csv(index=False).encode('shift-jis', errors='replace')
        st.download_button(
            label="シミュレーション結果をCSVダウンロード",
            data=csv,
            file_name=f"investment_simulation_{start_date.strftime('%Y%m%d')}.csv",
            mime='text/csv',
        )

        # 損益詳細テーブル
        st.subheader("損益詳細")

        # 損益詳細データを作成（カレンダー表示と同じロジック）
        pnl_detail_data = []
        
        # 直前の営業日の実現損益・含み損益を保持（日次変化を計算するため）
        prev_realized_pnl = 0
        prev_unrealized_pnl = 0

        for result in simulation_results:
            result_date = result['date']
            date_str = result_date.strftime('%Y-%m-%d')

            # === 実現損益の計算（累積値） ===
            cumulative_realized_pnl = 0
            realized_trades = []

            # 当日以前の全売却取引から実現損益を計算
            for trade in st.session_state.trade_history:
                if trade['date'] <= result_date and trade['action'] == '売却':
                    # 対応する購入取引を探す
                    buy_trade = None
                    for buy in st.session_state.trade_history:
                        if (buy['stock_code'] == trade['stock_code'] and
                            buy['action'] == '購入' and
                            buy['date'] < trade['date']):
                            if buy_trade is None or buy['date'] > buy_trade['date']:
                                buy_trade = buy

                    if buy_trade:
                        pnl_per_share = trade['price'] - buy_trade['price']
                        pnl_amount = pnl_per_share * trade['shares']

                        # 円換算（米国株の場合）
                        if trade['currency'] == 'USD' and trade['exchange_rate']:
                            pnl_amount *= trade['exchange_rate']

                        cumulative_realized_pnl += pnl_amount
                        
                        # 当日の売却取引のみ詳細に記録
                        if trade['date'] == result_date:
                            realized_trades.append(f"{trade['stock_code']}:{pnl_amount/10000:.1f}万")

            # === 含み損益の計算（累積値） ===
            cumulative_unrealized_pnl = 0
            holdings = {}

            # 当日以前の全取引履歴から保有状況を再構築
            for trade in st.session_state.trade_history:
                if trade['date'] <= result_date:
                    stock_code = trade['stock_code']

                    if stock_code not in holdings:
                        holdings[stock_code] = {
                            'total_shares': 0,
                            'total_cost': 0,
                            'currency': trade['currency']
                        }

                    if trade['action'] == '購入':
                        holdings[stock_code]['total_shares'] += trade['shares']
                        cost = trade['price'] * trade['shares']

                        if trade['currency'] == 'USD' and trade.get('exchange_rate'):
                            cost *= trade['exchange_rate']

                        holdings[stock_code]['total_cost'] += cost

                    elif trade['action'] == '売却':
                        if holdings[stock_code]['total_shares'] > 0:
                            sell_ratio = trade['shares'] / holdings[stock_code]['total_shares']
                            holdings[stock_code]['total_shares'] -= trade['shares']
                            holdings[stock_code]['total_cost'] *= (1 - sell_ratio)

            # 含み損益を計算
            unrealized_holdings = []
            for stock_code, holding in holdings.items():
                if holding['total_shares'] > 0:
                    current_price = get_stock_price_cached(stock_code, date_str)

                    if current_price is not None and current_price > 0:
                        current_value = current_price * holding['total_shares']

                        if holding['currency'] == 'USD' and result.get('exchange_rate'):
                            current_value *= result['exchange_rate']

                        pnl = current_value - holding['total_cost']
                        cumulative_unrealized_pnl += pnl
                        unrealized_holdings.append(f"{stock_code}:{pnl/10000:.1f}万")

            # === 日次変化を計算 ===
            # 実現損益の日次変化（当日の累積値 - 前日の累積値）
            daily_realized_pnl_change = cumulative_realized_pnl - prev_realized_pnl
            
            # 含み損益の日次変化（当日の累積値 - 前日の累積値）
            daily_unrealized_pnl_change = cumulative_unrealized_pnl - prev_unrealized_pnl
            
            # 合計損益の日次変化
            total_pnl_change = daily_realized_pnl_change + daily_unrealized_pnl_change

            pnl_detail_data.append({
                '日付': date_str,
                '曜日': ['月', '火', '水', '木', '金', '土', '日'][result_date.weekday()],
                '合計損益（万円）': f"{total_pnl_change/10000:+,.1f}",
                '実現損益（万円）': f"{daily_realized_pnl_change/10000:+,.1f}",
                '含み損益（万円）': f"{daily_unrealized_pnl_change/10000:+,.1f}",
                '日次損益率（%）': f"{result.get('daily_pnl_rate', 0):.2f}",
                'ポートフォリオ価値（万円）': f"{result['total_value']/10000:,.1f}",
                '実現損益詳細': '|'.join(realized_trades) if realized_trades else '-',
                '含み損益詳細': '|'.join(unrealized_holdings) if unrealized_holdings else '-'
            })
            
            # 次の日のために前日の累積値を更新
            prev_realized_pnl = cumulative_realized_pnl
            prev_unrealized_pnl = cumulative_unrealized_pnl

        pnl_df = pd.DataFrame(pnl_detail_data)
        st.dataframe(pnl_df, use_container_width=True)

        # 損益詳細CSVダウンロード
        pnl_csv = pnl_df.to_csv(index=False).encode('shift-jis', errors='replace')
        st.download_button(
            label="損益詳細をCSVダウンロード",
            data=pnl_csv,
            file_name=f"pnl_detail_{start_date.strftime('%Y%m%d')}.csv",
            mime='text/csv',
        )
