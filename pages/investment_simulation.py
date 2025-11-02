import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import calendar
from utils.db import get_connection
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

@lru_cache(maxsize=1000)
def get_exchange_rate(target_date):
    """
    指定日のUSD/JPY為替レートを取得する関数（キャッシュ付き）
    
    Parameters:
    target_date (str): 対象日（YYYY-MM-DD形式）
    
    Returns:
    float: USD/JPY為替レート または None
    """
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
            return float(df.loc[closest_date]["Close"].iloc[0])
        
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
            
            # 異常な評価額をチェック（1億円を超える場合は無効）
            if stock_value > 100000000:
                continue
                
            total_value += stock_value
    
    return total_value

def simulate_investment(start_date, initial_jpy, initial_usd, jpy_allocation_ratios, usd_allocation_ratios):
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
    end_date = datetime.now().date()
    
    while current_date <= end_date:
        # 火曜日(1)または土曜日(5)の場合
        if current_date.weekday() in [1, 5]:
            vote_date_str = current_date.strftime("%Y-%m-%d")
            jpy_stocks, usd_stocks = get_vote_results_for_date_separated(vote_date_str)
            
            if jpy_stocks or usd_stocks:
                # 次の営業日に売買を実行
                trade_date = get_next_business_day(current_date)
                
                # 現在のポートフォリオ価値を計算
                current_jpy_prices = {}
                current_usd_prices = {}
                
                # 為替レートを取得
                exchange_rate = get_exchange_rate(trade_date.strftime("%Y-%m-%d"))
                
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
                
                # 既存のポートフォリオを売却（取引履歴に記録）
                for stock_code, shares in jpy_portfolio.items():
                    if stock_code in current_jpy_prices and current_jpy_prices[stock_code] is not None:
                        sell_price = current_jpy_prices[stock_code]
                        sell_value = shares * sell_price
                        
                        # 取引履歴に記録
                        trade_history.append({
                            'date': trade_date,
                            'vote_date': current_date,
                            'stock_code': stock_code,
                            'stock_name': get_stock_name(stock_code),
                            'action': '売却',
                            'shares': shares,
                            'price': sell_price,
                            'value': sell_value,
                            'currency': 'JPY',
                            'exchange_rate': None
                        })
                
                for stock_code, shares in usd_portfolio.items():
                    if stock_code in current_usd_prices and current_usd_prices[stock_code] is not None:
                        sell_price = current_usd_prices[stock_code]
                        sell_value = shares * sell_price
                        
                        # 取引履歴に記録
                        trade_history.append({
                            'date': trade_date,
                            'vote_date': current_date,
                            'stock_code': stock_code,
                            'stock_name': get_stock_name(stock_code),
                            'action': '売却',
                            'shares': shares,
                            'price': sell_price,
                            'value': sell_value,
                            'currency': 'USD',
                            'exchange_rate': exchange_rate
                        })
                
                # 新しいポートフォリオを構築
                new_jpy_portfolio = {}
                new_usd_portfolio = {}
                
                # 日本株と米国株は既に分けられている
                # jpy_stocks, usd_stocks は既に取得済み
                
                # 投資対象の総資産価値を決定
                # 最初の取引の場合は初期投資額を使用、それ以降は現在のポートフォリオ価値を使用
                if not jpy_portfolio and not usd_portfolio:
                    # 最初の取引
                    jpy_investment_value = initial_jpy  # 円
                    usd_investment_value_usd = usd_cash  # ドル
                else:
                    # 既存のポートフォリオがある場合
                    # 異常な価値の場合は初期投資額を使用
                    if total_value > initial_total_value * 50:  # 初期投資額の50倍を超える場合は異常
                        jpy_investment_value = initial_jpy
                        usd_investment_value_usd = initial_usd / initial_exchange_rate
                    else:
                        # 現在のポートフォリオ価値に基づいて日本株と米国株の資金を配分
                        jpy_investment_value = jpy_portfolio_value + jpy_cash  # 円
                        # 米国株の価値をドルで計算
                        usd_portfolio_value_usd = calculate_portfolio_value(usd_portfolio, current_usd_prices, None)  # ドル建て
                        usd_investment_value_usd = usd_portfolio_value_usd + usd_cash  # ドル
                
                # 取引コストを考慮した総資産価値
                total_trading_cost = 0
                
                # 日本株の配分
                jpy_remaining_cash = jpy_investment_value
                for i, (stock_code, vote_count) in enumerate(jpy_stocks):
                    if i < len(jpy_allocation_ratios):
                        allocation_ratio = jpy_allocation_ratios[i] / 100.0
                        target_value = jpy_investment_value * allocation_ratio
                        
                        price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                        if price is not None and price > 0:
                            
                            # 取引コストを考慮
                            trading_cost = calculate_trading_cost(target_value)
                            total_trading_cost += trading_cost
                            
                            # コストを差し引いた価値で株数を計算
                            net_value = target_value - trading_cost
                            shares = int(net_value / price)  # 1株未満は切捨て
                            
                            if shares > 0:
                                actual_cost = shares * price + trading_cost
                                jpy_remaining_cash -= actual_cost
                                new_jpy_portfolio[stock_code] = shares
                                
                                # 取引履歴に記録（購入）
                                trade_history.append({
                                    'date': trade_date,
                                    'vote_date': current_date,
                                    'stock_code': stock_code,
                                    'stock_name': get_stock_name(stock_code),
                                    'action': '購入',
                                    'shares': shares,
                                    'price': price,
                                    'value': shares * price,
                                    'currency': 'JPY',
                                    'exchange_rate': None,
                                    'buy_price': price,
                                    'sell_price': None
                                })
                
                # 米国株の配分（ドル建て）
                usd_remaining_cash = usd_investment_value_usd  # ドル
                for i, (stock_code, vote_count) in enumerate(usd_stocks):
                    if i < len(usd_allocation_ratios):
                        allocation_ratio = usd_allocation_ratios[i] / 100.0
                        target_value_usd = usd_investment_value_usd * allocation_ratio  # ドル

                        price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                        if price is not None and price > 0:

                            # 取引コストを考慮（ドル建て）
                            trading_cost_usd = calculate_trading_cost(target_value_usd)
                            total_trading_cost += trading_cost_usd * exchange_rate  # 円換算

                            # コストを差し引いた価値で株数を計算（ドル建て）
                            net_value_usd = target_value_usd - trading_cost_usd
                            shares = int(net_value_usd / price)  # 1株未満は切捨て

                            if shares > 0:
                                actual_cost_usd = shares * price + trading_cost_usd  # ドル
                                usd_remaining_cash -= actual_cost_usd  # ドル
                                new_usd_portfolio[stock_code] = shares

                                # 取引履歴に記録（購入）
                                trade_history.append({
                                    'date': trade_date,
                                    'vote_date': current_date,
                                    'stock_code': stock_code,
                                    'stock_name': get_stock_name(stock_code),
                                    'action': '購入',
                                    'shares': shares,
                                    'price': price,
                                    'value': shares * price,  # ドル建て
                                    'currency': 'USD',
                                    'exchange_rate': exchange_rate,
                                    'buy_price': price,
                                    'sell_price': None
                                })
                
                # ポートフォリオを更新
                jpy_portfolio = new_jpy_portfolio
                usd_portfolio = new_usd_portfolio

                # 現金を更新（余った資金を保持）
                jpy_cash = jpy_remaining_cash  # 円
                usd_cash = usd_remaining_cash  # ドル

                # 新しいポートフォリオの価値を計算（購入直後の価格で）
                new_jpy_prices = {}
                new_usd_prices = {}

                # 新しい日本株ポートフォリオの価格を取得
                for stock_code in jpy_portfolio.keys():
                    price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                    if price is not None:
                        new_jpy_prices[stock_code] = price

                # 新しい米国株ポートフォリオの価格を取得
                for stock_code in usd_portfolio.keys():
                    price = get_stock_price_cached(stock_code, trade_date.strftime("%Y-%m-%d"))
                    if price is not None:
                        new_usd_prices[stock_code] = price

                # 新しいポートフォリオの価値を計算（円換算）
                new_jpy_portfolio_value = calculate_portfolio_value(jpy_portfolio, new_jpy_prices, None)
                new_usd_portfolio_value = calculate_portfolio_value(usd_portfolio, new_usd_prices, None, exchange_rate)

                # 最終的な総資産価値を計算（すべて円換算）
                final_total_value = new_jpy_portfolio_value + jpy_cash + new_usd_portfolio_value + (usd_cash * exchange_rate if exchange_rate else 0)
                
                # 結果を記録
                simulation_results.append({
                    'date': trade_date,
                    'vote_date': current_date,
                    'jpy_portfolio': jpy_portfolio.copy(),
                    'usd_portfolio': usd_portfolio.copy(),
                    'jpy_cash': jpy_cash,  # 円
                    'usd_cash': usd_cash,  # ドル
                    'total_value': final_total_value,  # 円換算の総資産
                    'exchange_rate': exchange_rate,
                    'jpy_portfolio_value': new_jpy_portfolio_value,  # 円
                    'usd_portfolio_value': new_usd_portfolio_value,  # 円換算
                    'trading_cost': total_trading_cost  # 円換算
                })
        
        current_date += timedelta(days=1)
    
    return simulation_results, trade_history

def create_calendar_heatmap(simulation_results, trade_history, year, month):
    """カレンダー形式のヒートマップを作成"""
    
    # 指定月のデータをフィルタリング
    month_data = []
    for result in simulation_results:
        if result['date'].year == year and result['date'].month == month:
            month_data.append(result)
    
    if not month_data:
        return None
    
    # カレンダーを作成
    cal = calendar.monthcalendar(year, month)
    
    # データを日付でソート
    month_data.sort(key=lambda x: x['date'])
    
    # 日別の損益率を計算（取引履歴に基づく）
    daily_returns = {}
    
    # 指定月の取引履歴を取得
    month_trades = []
    for trade in trade_history:
        if trade['date'].year == year and trade['date'].month == month:
            month_trades.append(trade)
    
    # 日別の取引損益を計算
    daily_pnl = {}
    for trade in month_trades:
        trade_date = trade['date'].day
        
        if trade['action'] == '売却':
            # 売却時の損益を計算
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
                investment_amount = buy_trade['price'] * trade['shares']

                # 円換算（米国株の場合）
                if trade['currency'] == 'USD' and trade['exchange_rate']:
                    pnl_amount *= trade['exchange_rate']
                    investment_amount *= buy_trade['exchange_rate']  # 投資額も円換算

                if trade_date not in daily_pnl:
                    daily_pnl[trade_date] = {'pnl': 0, 'investment': 0}

                daily_pnl[trade_date]['pnl'] += pnl_amount
                daily_pnl[trade_date]['investment'] += investment_amount
    
    # 日別の損益率を計算
    for trade_date, data in daily_pnl.items():
        if data['investment'] > 0:
            daily_return = (data['pnl'] / data['investment']) * 100
            daily_returns[trade_date] = daily_return
        else:
            daily_returns[trade_date] = 0
    
    # 取引がない日は0%とする
    for result in month_data:
        if result['date'].day not in daily_returns:
            daily_returns[result['date'].day] = 0
    
    # カレンダーのHTMLを作成
    month_name = calendar.month_name[month]
    html = f"<h3>{year}年{month}月</h3>"
    html += "<table style='border-collapse: collapse; width: 100%;'>"
    
    # 曜日のヘッダー
    html += "<tr><th>月</th><th>火</th><th>水</th><th>木</th><th>金</th><th>土</th><th>日</th></tr>"
    
    for week in cal:
        html += "<tr>"
        for day in week:
            if day == 0:
                html += "<td></td>"
            else:
                if day in daily_returns:
                    return_rate = daily_returns[day]
                    # 色を決定（赤：マイナス、青：プラス）
                    if return_rate < 0:
                        color = f"rgba(255, 0, 0, {min(abs(return_rate) / 5, 1)})"
                    else:
                        color = f"rgba(0, 0, 255, {min(return_rate / 5, 1)})"
                    
                    html += f"<td style='background-color: {color}; text-align: center; padding: 5px; border: 1px solid #ccc;'>{day}<br/>{return_rate:.1f}%</td>"
                else:
                    html += f"<td style='text-align: center; padding: 5px; border: 1px solid #ccc;'>{day}</td>"
        html += "</tr>"
    
    html += "</table>"
    
    return html

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
    st.title("投資シミュレーション")
    
    # 設定パネル
    with st.expander("シミュレーション設定", expanded=True):
        col1, col2 = st.columns(2)
        
        with col1:
            start_date = st.date_input(
                "開始日",
                value=date(2025, 7, 1),
                min_value=date(2020, 1, 1),
                max_value=datetime.now().date()
            )
            
            initial_jpy = st.number_input(
                "日本株初期資金 (円)",
                value=5000000,
                min_value=0,
                step=100000
            )
        
        with col2:
            initial_usd = st.number_input(
                "米国株初期資金 (円)",
                value=5000000,
                min_value=0,
                step=100000
            )
            
            st.write("**日本株投資配分比率 (%)**")
            jpy_allocation_ratios = []
            for i in range(10):
                ratio = st.number_input(
                    f"日本株第{i+1}位",
                    value=DEFAULT_ALLOCATION[i],
                    min_value=0,
                    max_value=100,
                    step=1,
                    key=f"jpy_allocation_{i}"
                )
                jpy_allocation_ratios.append(ratio)
            
            # 日本株配分の合計を表示
            jpy_total_allocation = sum(jpy_allocation_ratios)
            if jpy_total_allocation != 100:
                st.warning(f"日本株配分の合計が100%ではありません（現在: {jpy_total_allocation}%）")
            
            st.write("**米国株投資配分比率 (%)**")
            usd_allocation_ratios = []
            for i in range(10):
                ratio = st.number_input(
                    f"米国株第{i+1}位",
                    value=DEFAULT_ALLOCATION[i],
                    min_value=0,
                    max_value=100,
                    step=1,
                    key=f"usd_allocation_{i}"
                )
                usd_allocation_ratios.append(ratio)
            
            # 米国株配分の合計を表示
            usd_total_allocation = sum(usd_allocation_ratios)
            if usd_total_allocation != 100:
                st.warning(f"米国株配分の合計が100%ではありません（現在: {usd_total_allocation}%）")
    
    # シミュレーション実行ボタン
    if st.button("シミュレーション実行", type="primary"):
        with st.spinner("シミュレーションを実行中..."):
            try:
                simulation_results, trade_history = simulate_investment(
                    start_date, 
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
            st.metric("初期投資額", f"¥{initial_value:,}")
        with col2:
            st.metric("最終価値", f"¥{final_value:,.0f}")
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
        st.subheader("月別カレンダー")
        
        # 年と月の選択
        if simulation_results:
            min_year = min(result['date'].year for result in simulation_results)
            max_year = max(result['date'].year for result in simulation_results)
            
            col1, col2 = st.columns(2)
            with col1:
                selected_year = st.selectbox("年", range(min_year, max_year + 1), index=max_year - min_year)
            with col2:
                selected_month = st.selectbox("月", range(1, 13))
            
            # カレンダーを表示
            calendar_html = create_calendar_heatmap(simulation_results, st.session_state.trade_history, selected_year, selected_month)
            if calendar_html:
                st.markdown(calendar_html, unsafe_allow_html=True)
            else:
                st.info("選択された月のデータがありません。")
        
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
                '投票日': result['vote_date'].strftime('%Y-%m-%d'),
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
