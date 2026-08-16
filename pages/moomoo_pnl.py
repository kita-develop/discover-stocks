import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import plotly.graph_objects as go
from utils.db import get_connection

# 定数
TRADING_FEES_RATE = 0.0  # 必要に応じて調整
TAX_RATE = 0.0 # 必要に応じて調整
DEFAULT_EXCHANGE_RATE = 150.0  # 為替レート取得失敗時のデフォルト値
QUANTITY_TOLERANCE = 0.0001  # 数量の誤差許容範囲

def get_exchange_rate(date_str):
    """
    指定日のUSD/JPY為替レートを取得する関数（簡易キャッシュ）
    """
    try:
        # yfinanceで取得
        ticker = "USDJPY=X"
        start_date = (pd.Timestamp(date_str) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        end_date = (pd.Timestamp(date_str) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        
        df = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=True)
        
        if df.empty:
            return DEFAULT_EXCHANGE_RATE  # デフォルト値（エラー時）

        # 指定日以前の最新のデータを取得
        target_ts = pd.Timestamp(date_str)
        valid_rows = df[df.index <= target_ts]
        
        if not valid_rows.empty:
            close_value = valid_rows['Close'].iloc[-1]
            # MultiIndex列の場合やSeriesの場合に対応
            if hasattr(close_value, 'item'):
                return float(close_value.item())
            return float(close_value)
        
        return DEFAULT_EXCHANGE_RATE
    except Exception as e:
        # st.error(f"為替レート取得エラー: {e}")
        return DEFAULT_EXCHANGE_RATE

def get_current_price(ticker):
    """
    現在の株価を取得
    """
    try:
        # 日本株の場合（先頭文字が数字なら日本株として扱う）
        if ticker[0].isdigit():
            yf_ticker = f"{ticker}.T"
        else:
            yf_ticker = ticker
            
        stock = yf.Ticker(yf_ticker)
        history = stock.history(period="1d")
        if not history.empty:
            close_value = history['Close'].iloc[-1]
            # MultiIndex列の場合やSeriesの場合に対応
            if hasattr(close_value, 'item'):
                return float(close_value.item())
            return float(close_value)
        return None
    except Exception:
        return None

def parse_moomoo_csv(file):
    """
    moomoo証券のCSVを解析する
    """
    try:
        # CSVを読み込む（エンコーディングはShift-JISまたはUTF-8を想定）
        # ファイルポインタを先頭に戻す
        file.seek(0)
        try:
            df = pd.read_csv(file, encoding='shift_jis')
        except UnicodeDecodeError:
            file.seek(0)  # 再度先頭に戻す
            df = pd.read_csv(file, encoding='utf-8')

        # 必要なカラムが存在するか確認
        required_columns = ['方向', '銘柄コード', '銘柄名', '注文状況', '約定数量', '約定価格', '約定日時', '通貨', '取引手数料', '消費税']
        # カラム名の空白削除などの正規化
        df.columns = [c.strip() for c in df.columns]
        
        # データ処理用のリスト
        trades = []
        
        # 前行のデータを保持する変数（分割約定用）
        last_valid_row = None
        
        for index, row in df.iterrows():
            # 注文状況が「約定済」または空欄（分割約定の続き）の場合のみ処理
            status = str(row['注文状況']).strip() if pd.notna(row['注文状況']) else ""
            
            # 約定数量がある行を有効な約定データとみなす
            exec_qty = row['約定数量']
            if pd.isna(exec_qty) or str(exec_qty).strip() == "":
                continue
                
            try:
                qty = float(str(exec_qty).replace(',', ''))
            except ValueError:
                continue
                
            if qty <= 0:
                continue

            # 親注文情報の補完
            if status == "約定済":
                last_valid_row = row
            elif status == "" and last_valid_row is not None:
                # 空欄の場合は前の行の情報を引き継ぐべき項目をコピー
                # ただし、約定ごとの固有情報（数量、価格、日時など）は現在の行を使用
                pass
            else:
                # 約定済でも分割の続きでもない（例：取消済など）はスキップ
                continue

            # データの抽出（親行の情報が必要な場合はlast_valid_rowを使用）
            current_row_source = row if status == "約定済" else row
            parent_row_source = last_valid_row if last_valid_row is not None else row
            
            # 銘柄コード、方向、通貨は親行から取得
            ticker = str(parent_row_source['銘柄コード']).strip()
            name = str(parent_row_source['銘柄名']).strip()
            side = str(parent_row_source['方向']).strip()
            currency = str(parent_row_source['通貨']).strip()
            
            # 約定価格、約定日時は現在の行から取得
            try:
                price = float(str(row['約定価格']).replace(',', ''))
            except ValueError:
                price = 0.0
                
            date_str = str(row['約定日時']).strip()
            
            # 手数料などは、行ごとに記載があれば加算、なければ親行につく場合もあるが、
            # サンプルを見ると各行に手数料が書いてあるわけではなさそう？
            # サンプル: Line 2 (約定済) has fees. Line 27 (約定済, split parent) has fees?
            # Line 27: fees 0. Line 28: fees empty.
            # 手数料は「約定済」の行にまとめて記載されている場合と、各約定にある場合があるかもしれない。
            # 今回は行にある数値をそのまま使う。
            
            fee = 0.0
            if '取引手数料' in row and pd.notna(row['取引手数料']) and str(row['取引手数料']).strip() != "":
                fee += float(str(row['取引手数料']).replace(',', ''))
            if '消費税' in row and pd.notna(row['消費税']) and str(row['消費税']).strip() != "":
                fee += float(str(row['消費税']).replace(',', ''))
            if 'システム利用料' in row and pd.notna(row['システム利用料']) and str(row['システム利用料']).strip() != "":
                fee += float(str(row['システム利用料']).replace(',', ''))

            # 日付のパース (ET/JSTの処理)
            # 2025/11/25 08:38:23 ET -> 2025-11-25 08:38:23
            try:
                # タイムゾーン部分（ET/JST）を除去してパース
                # 例: "2025/11/25 08:38:23 ET" -> "2025/11/25 08:38:23"
                date_str_clean = date_str.replace(' ET', '').replace(' JST', '').strip()
                trade_datetime = datetime.strptime(date_str_clean, "%Y/%m/%d %H:%M:%S")
                trade_date = trade_datetime.date()
            except ValueError:
                # 時刻がない場合は日付のみ
                try:
                    date_part = date_str.split(' ')[0]
                    trade_date = datetime.strptime(date_part, "%Y/%m/%d").date()
                    trade_datetime = datetime.combine(trade_date, datetime.min.time())
                except ValueError:
                    continue

            trades.append({
                'date': trade_date,
                'datetime': trade_datetime,  # ソート用に日時も保存
                'ticker': ticker,
                'name': name,
                'side': side,
                'currency': currency,
                'qty': qty,
                'price': price,
                'fee': fee,
                'original_line': index + 2 # 1-based index for header + 1
            })
            
        return pd.DataFrame(trades)
        
    except Exception as e:
        st.error(f"CSV読み込みエラー: {e}")
        return pd.DataFrame()

def calculate_pnl(df):
    """
    損益計算を行う
    """
    if df.empty:
        return [], [], []

    # 日時順にソート（古い順）- 同日の取引も正しい順序で処理
    df = df.sort_values('datetime')
    
    # 保有ポジション {ticker: {'qty': 0, 'total_cost': 0.0, 'avg_cost': 0.0}}
    holdings = {}
    
    realized_pnl = []
    warnings = []  # 警告情報を記録
    
    for _, row in df.iterrows():
        ticker = row['ticker']
        side = row['side']
        qty = row['qty']
        price = row['price']
        fee = row['fee']
        currency = row['currency']
        date = row['date']
        
        if ticker not in holdings:
            holdings[ticker] = {'qty': 0, 'total_cost': 0.0, 'avg_cost': 0.0, 'currency': currency, 'name': row['name']}
            
        position = holdings[ticker]
        
        if side == '買い':
            # 取得コスト計算（手数料含む）
            cost = (price * qty) + fee
            position['qty'] += qty
            position['total_cost'] += cost
            if position['qty'] > 0:
                position['avg_cost'] = position['total_cost'] / position['qty']
                
        elif side == '売り':
            if position['qty'] > 0:
                # 売却コスト（手数料引く前の売却額 - コスト）
                # 実現損益 = (売却単価 - 平均取得単価) * 数量 - 手数料
                
                # 売却前の平均取得単価を保存
                avg_cost_at_sell = position['avg_cost']
                
                # 平均取得単価に基づくコスト
                cost_basis = position['avg_cost'] * qty
                
                # 売却額
                sell_proceeds = (price * qty)
                
                # 損益 (現地通貨ベース)
                pnl_local = sell_proceeds - cost_basis - fee
                
                # 残高更新
                position['qty'] -= qty
                position['total_cost'] -= cost_basis # 平均法なので比例配分で減らす
                
                # 誤差修正（数量0ならコストも0）
                if abs(position['qty']) < QUANTITY_TOLERANCE:
                    position['qty'] = 0
                    position['total_cost'] = 0
                    position['avg_cost'] = 0
                
                # 円換算
                rate = 1.0
                if currency == 'USD':
                    rate = get_exchange_rate(date.strftime("%Y-%m-%d"))
                
                pnl_jpy = pnl_local * rate
                
                realized_pnl.append({
                    'month': date.strftime("%Y-%m"),
                    'date': date,
                    'ticker': ticker,
                    'name': row['name'],
                    'qty': qty,
                    'avg_cost': avg_cost_at_sell,  # 売却前の平均取得単価
                    'sell_price': price,
                    'currency': currency,
                    'pnl_local': pnl_local,
                    'pnl_jpy': pnl_jpy,
                    'rate': rate
                })
            else:
                # 買い情報がない状態で売りが発生（データ欠損）
                warnings.append({
                    'type': '買い情報欠損',
                    'ticker': ticker,
                    'name': row['name'],
                    'date': date,
                    'qty': qty,
                    'message': f'銘柄 {ticker}({row["name"]}) の売り注文に対応する買い情報がありません（{date}, {qty}株）'
                })

    # 含み損益計算
    unrealized_pnl = []
    current_rate = get_exchange_rate(datetime.now().strftime("%Y-%m-%d"))
    
    for ticker, pos in holdings.items():
        if pos['qty'] > QUANTITY_TOLERANCE:
            current_price = get_current_price(ticker)
            
            if current_price is not None:
                market_value_local = current_price * pos['qty']
                cost_basis_local = pos['total_cost']
                pnl_local = market_value_local - cost_basis_local
                
                rate = 1.0
                if pos['currency'] == 'USD':
                    rate = current_rate
                    
                market_value_jpy = market_value_local * rate
                cost_basis_jpy = cost_basis_local * rate
                pnl_jpy = pnl_local * rate
                
                unrealized_pnl.append({
                    'ticker': ticker,
                    'name': pos['name'],
                    'qty': pos['qty'],
                    'avg_cost': pos['avg_cost'],
                    'current_price': current_price,
                    'market_value_jpy': market_value_jpy,
                    'cost_basis_jpy': cost_basis_jpy,
                    'pnl_jpy': pnl_jpy,
                    'currency': pos['currency']
                })
            else:
                # 株価取得失敗
                warnings.append({
                    'type': '株価取得失敗',
                    'ticker': ticker,
                    'name': pos['name'],
                    'qty': pos['qty'],
                    'avg_cost': pos['avg_cost'],
                    'currency': pos['currency'],
                    'message': f'銘柄 {ticker}({pos["name"]}) の現在株価を取得できませんでした（保有: {pos["qty"]}株）'
                })
                
    return realized_pnl, unrealized_pnl, warnings

def show(selected_date=None):
    st.title("moomoo証券 損益分析")
    
    st.markdown("""
    moomoo証券の取引履歴CSVをアップロードして、実現損益と含み損益を表示します。
    - 米国株は取引日の為替レートで円換算されます。
    - 含み損益は現在の株価と為替レートで計算されます。
    """)
    
    uploaded_file = st.file_uploader("取引履歴CSVをアップロード", type=['csv'])
    
    if uploaded_file is not None:
        if st.button("計算実行"):
            with st.spinner("計算中..."):
                df = parse_moomoo_csv(uploaded_file)
                
                if not df.empty:
                    # st.dataframe(df) # デバッグ用
                    realized, unrealized, warnings = calculate_pnl(df)
                    
                    # --- 警告情報 ---
                    if warnings:
                        st.header("⚠️ 警告情報")
                        with st.expander(f"警告: {len(warnings)}件の問題があります", expanded=True):
                            for w in warnings:
                                if w['type'] == '株価取得失敗':
                                    st.warning(f"📉 **{w['type']}**: {w['ticker']} ({w['name']}) - 保有: {w['qty']}株, 平均取得単価: {w['avg_cost']:,.2f} {w['currency']}")
                                elif w['type'] == '買い情報欠損':
                                    st.error(f"🚨 **{w['type']}**: {w['ticker']} ({w['name']}) - 日付: {w['date']}, 数量: {w['qty']}株")
                    
                    # --- 年初来サマリー ---
                    st.header("📈 年初来サマリー")
                    
                    # 実現損益合計
                    total_realized = sum([r['pnl_jpy'] for r in realized]) if realized else 0
                    # 含み損益合計
                    total_unrealized = sum([u['pnl_jpy'] for u in unrealized]) if unrealized else 0
                    # 総合損益
                    total_pnl = total_realized + total_unrealized
                    
                    col1, col2, col3 = st.columns(3)
                    col1.metric("実現損益", f"{total_realized:,.0f} 円", delta=f"{total_realized/10000:,.0f}万円")
                    col2.metric("含み損益", f"{total_unrealized:,.0f} 円", delta=f"{total_unrealized/10000:,.0f}万円")
                    col3.metric("総合損益", f"{total_pnl:,.0f} 円", delta=f"{total_pnl/10000:,.0f}万円")
                    
                    # --- 日本株・米国株別サマリー ---
                    if realized:
                        # 日本株・米国株に分ける
                        jp_realized = [r for r in realized if r['currency'] == 'JPY']
                        us_realized = [r for r in realized if r['currency'] == 'USD']
                        
                        jp_unrealized = [u for u in unrealized if u['currency'] == 'JPY']
                        us_unrealized = [u for u in unrealized if u['currency'] == 'USD']
                        
                        # 勝率とRR比率を計算する関数
                        def calc_win_rate_and_rr(pnl_list):
                            if not pnl_list:
                                return 0, 0, 0, 0
                            wins = [r['pnl_jpy'] for r in pnl_list if r['pnl_jpy'] > 0]
                            losses = [r['pnl_jpy'] for r in pnl_list if r['pnl_jpy'] < 0]
                            total_trades = len(pnl_list)
                            win_count = len(wins)
                            win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
                            avg_win = sum(wins) / len(wins) if wins else 0
                            avg_loss = abs(sum(losses) / len(losses)) if losses else 0
                            rr_ratio = avg_win / avg_loss if avg_loss > 0 else 0
                            return win_rate, rr_ratio, total_trades, win_count
                        
                        # 全体の勝率・RR比率
                        total_win_rate, total_rr, total_trades, total_wins = calc_win_rate_and_rr(realized)
                        
                        # 日本株の勝率・RR比率
                        jp_win_rate, jp_rr, jp_trades, jp_wins = calc_win_rate_and_rr(jp_realized)
                        jp_total_realized = sum([r['pnl_jpy'] for r in jp_realized])
                        jp_total_unrealized = sum([u['pnl_jpy'] for u in jp_unrealized])
                        
                        # 米国株の勝率・RR比率
                        us_win_rate, us_rr, us_trades, us_wins = calc_win_rate_and_rr(us_realized)
                        us_total_realized = sum([r['pnl_jpy'] for r in us_realized])
                        us_total_unrealized = sum([u['pnl_jpy'] for u in us_unrealized])
                        
                        st.markdown("---")
                        st.subheader("市場別サマリー")
                        
                        # 全体
                        st.markdown(f"**全体**: 勝率 {total_win_rate:.1f}% ({total_wins}/{total_trades}), RR比率 {total_rr:.2f}")
                        
                        col_jp, col_us = st.columns(2)
                        
                        with col_jp:
                            st.markdown("#### 🇯🇵 日本株")
                            st.metric("実現損益", f"{jp_total_realized:,.0f} 円", delta=f"{jp_total_realized/10000:,.0f}万円")
                            st.metric("含み損益", f"{jp_total_unrealized:,.0f} 円", delta=f"{jp_total_unrealized/10000:,.0f}万円")
                            st.markdown(f"**勝率**: {jp_win_rate:.1f}% ({jp_wins}/{jp_trades})")
                            st.markdown(f"**RR比率**: {jp_rr:.2f}")
                        
                        with col_us:
                            st.markdown("#### 🇺🇸 米国株")
                            st.metric("実現損益", f"{us_total_realized:,.0f} 円", delta=f"{us_total_realized/10000:,.0f}万円")
                            st.metric("含み損益", f"{us_total_unrealized:,.0f} 円", delta=f"{us_total_unrealized/10000:,.0f}万円")
                            st.markdown(f"**勝率**: {us_win_rate:.1f}% ({us_wins}/{us_trades})")
                            st.markdown(f"**RR比率**: {us_rr:.2f}")
                    
                    # --- 年初来累計損益の折れ線グラフ ---
                    if realized:
                        df_realized = pd.DataFrame(realized)
                        # 日付順にソート
                        df_realized = df_realized.sort_values('date')
                        # 累計損益を計算
                        df_realized['cumulative_pnl'] = df_realized['pnl_jpy'].cumsum()
                        # 万円単位
                        df_realized['cumulative_pnl_man'] = (df_realized['cumulative_pnl'] / 10000).round(0)
                        
                        # 日本株・米国株別の累計損益
                        df_jp = df_realized[df_realized['currency'] == 'JPY'].copy()
                        df_us = df_realized[df_realized['currency'] == 'USD'].copy()
                        
                        if not df_jp.empty:
                            df_jp = df_jp.sort_values('date')
                            df_jp['cumulative_pnl_man'] = (df_jp['pnl_jpy'].cumsum() / 10000).round(0)
                        
                        if not df_us.empty:
                            df_us = df_us.sort_values('date')
                            df_us['cumulative_pnl_man'] = (df_us['pnl_jpy'].cumsum() / 10000).round(0)
                        
                        st.subheader("年初来実現損益の推移")
                        fig_cumulative = go.Figure()
                        
                        # 全体の累計損益
                        fig_cumulative.add_trace(go.Scatter(
                            x=df_realized['date'],
                            y=df_realized['cumulative_pnl_man'],
                            mode='lines+markers',
                            name='全体',
                            line=dict(color='blue', width=3),
                            hovertemplate='%{x}<br>全体: %{y:.0f}万円<extra></extra>'
                        ))
                        
                        # 日本株の累計損益
                        if not df_jp.empty:
                            fig_cumulative.add_trace(go.Scatter(
                                x=df_jp['date'],
                                y=df_jp['cumulative_pnl_man'],
                                mode='lines+markers',
                                name='日本株',
                                line=dict(color='red', width=2, dash='dot'),
                                hovertemplate='%{x}<br>日本株: %{y:.0f}万円<extra></extra>'
                            ))
                        
                        # 米国株の累計損益
                        if not df_us.empty:
                            fig_cumulative.add_trace(go.Scatter(
                                x=df_us['date'],
                                y=df_us['cumulative_pnl_man'],
                                mode='lines+markers',
                                name='米国株',
                                line=dict(color='green', width=2, dash='dash'),
                                hovertemplate='%{x}<br>米国株: %{y:.0f}万円<extra></extra>'
                            ))
                        # 0ラインを追加
                        fig_cumulative.add_hline(y=0, line_dash="dash", line_color="gray")
                        fig_cumulative.update_layout(
                            xaxis_title='日付',
                            yaxis_title='累計損益（万円）',
                            showlegend=True,
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                        )
                        st.plotly_chart(fig_cumulative, use_container_width=True)
                    
                    # --- 実現損益 ---
                    st.header("実現損益 (月次)")
                    if realized:
                        df_realized = pd.DataFrame(realized)
                        
                        # 月次集計（全体）
                        monthly_pnl = df_realized.groupby('month')['pnl_jpy'].sum().reset_index()
                        monthly_pnl = monthly_pnl.sort_values('month')
                        monthly_pnl['pnl_man'] = (monthly_pnl['pnl_jpy'] / 10000).round(0).astype(int)
                        
                        # 日本株・米国株別の月次集計
                        df_jp_monthly = df_realized[df_realized['currency'] == 'JPY'].groupby('month')['pnl_jpy'].sum().reset_index()
                        df_jp_monthly.columns = ['month', 'jp_pnl_jpy']
                        df_us_monthly = df_realized[df_realized['currency'] == 'USD'].groupby('month')['pnl_jpy'].sum().reset_index()
                        df_us_monthly.columns = ['month', 'us_pnl_jpy']
                        
                        # マージして統合テーブル作成
                        monthly_all = monthly_pnl[['month', 'pnl_jpy', 'pnl_man']].copy()
                        monthly_all = monthly_all.merge(df_jp_monthly, on='month', how='left')
                        monthly_all = monthly_all.merge(df_us_monthly, on='month', how='left')
                        monthly_all = monthly_all.fillna(0)
                        monthly_all['jp_pnl_man'] = (monthly_all['jp_pnl_jpy'] / 10000).round(0).astype(int)
                        monthly_all['us_pnl_man'] = (monthly_all['us_pnl_jpy'] / 10000).round(0).astype(int)
                        
                        # Plotlyでグラフ作成（グループ化された棒グラフ）
                        fig = go.Figure()
                        
                        # 全体
                        fig.add_trace(go.Bar(
                            x=monthly_all['month'],
                            y=monthly_all['pnl_man'],
                            name='全体',
                            marker_color='blue',
                            hovertemplate='%{x}<br>全体: %{y}万円<extra></extra>'
                        ))
                        
                        # 日本株
                        fig.add_trace(go.Bar(
                            x=monthly_all['month'],
                            y=monthly_all['jp_pnl_man'],
                            name='日本株',
                            marker_color='red',
                            hovertemplate='%{x}<br>日本株: %{y}万円<extra></extra>'
                        ))
                        
                        # 米国株
                        fig.add_trace(go.Bar(
                            x=monthly_all['month'],
                            y=monthly_all['us_pnl_man'],
                            name='米国株',
                            marker_color='green',
                            hovertemplate='%{x}<br>米国株: %{y}万円<extra></extra>'
                        ))
                        
                        fig.update_layout(
                            xaxis_title='月',
                            yaxis_title='損益（万円）',
                            barmode='group',
                            showlegend=True,
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                        )
                        st.plotly_chart(fig, use_container_width=True)
                        
                        # テーブル（日本語カラム名、日本株・米国株別追加）
                        monthly_pnl_display = monthly_all[['month', 'pnl_jpy', 'pnl_man', 'jp_pnl_jpy', 'jp_pnl_man', 'us_pnl_jpy', 'us_pnl_man']].copy()
                        monthly_pnl_display.columns = ['月', '全体（円）', '全体（万円）', '日本株（円）', '日本株（万円）', '米国株（円）', '米国株（万円）']
                        st.dataframe(monthly_pnl_display.style.format({
                            '全体（円）': '{:,.0f}', 
                            '全体（万円）': '{:,}',
                            '日本株（円）': '{:,.0f}', 
                            '日本株（万円）': '{:,}',
                            '米国株（円）': '{:,.0f}', 
                            '米国株（万円）': '{:,}'
                        }))
                        
                        # 詳細
                        with st.expander("詳細取引履歴"):
                            df_realized_display = df_realized.copy()
                            df_realized_display.columns = ['月', '日付', '銘柄コード', '銘柄名', '数量', '平均取得単価', '決済単価', '通貨', '損益（現地通貨）', '損益（円）', '為替レート']
                            st.dataframe(df_realized_display.style.format({
                                '数量': '{:,.0f}',
                                '平均取得単価': '{:,.2f}',
                                '決済単価': '{:,.2f}',
                                '損益（現地通貨）': '{:,.2f}', 
                                '損益（円）': '{:,.0f}',
                                '為替レート': '{:,.2f}'
                            }))
                        
                        total_realized = df_realized['pnl_jpy'].sum()
                        st.metric("累計実現損益", f"{total_realized:,.0f} 円")
                        
                    else:
                        st.info("実現損益データはありません。")
                        
                    # --- 含み損益 ---
                    st.header("含み損益 (現在)")
                    if unrealized:
                        df_unrealized = pd.DataFrame(unrealized)
                        
                        total_unrealized = df_unrealized['pnl_jpy'].sum()
                        total_market_value = df_unrealized['market_value_jpy'].sum()
                        
                        col1, col2 = st.columns(2)
                        col1.metric("評価額合計", f"{total_market_value:,.0f} 円")
                        col2.metric("含み損益合計", f"{total_unrealized:,.0f} 円", 
                                   delta_color="normal" if total_unrealized >= 0 else "inverse")
                        
                        # テーブル（日本語カラム名）
                        df_unrealized_display = df_unrealized.copy()
                        df_unrealized_display.columns = ['銘柄コード', '銘柄名', '保有数量', '平均取得単価', '現在価格', '評価額（円）', '取得原価（円）', '含み損益（円）', '通貨']
                        st.dataframe(df_unrealized_display.style.format({
                            '保有数量': '{:,.4f}',
                            '平均取得単価': '{:,.2f}',
                            '現在価格': '{:,.2f}',
                            '評価額（円）': '{:,.0f}',
                            '取得原価（円）': '{:,.0f}',
                            '含み損益（円）': '{:,.0f}'
                        }))
                    else:
                        st.info("保有銘柄はありません。")
                        
                else:
                    st.error("有効な取引データが見つかりませんでした。")
