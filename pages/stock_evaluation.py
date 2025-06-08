import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
import plotly.express as px
from utils.db import get_connection
from utils.common import get_stock_name, get_ticker
from functools import lru_cache

@lru_cache(maxsize=400)
def get_stock_price(stock_code, start_date, end_date):
    """
    株価を取得する関数（キャッシュ付き）
    
    Parameters:
    stock_code (str): 銘柄コード
    start_date (str): 開始日（YYYY-MM-DD形式）
    end_date (str): 終了日（YYYY-MM-DD形式）
    
    Returns:
    tuple: (始値, 終値) または (None, None)
    """
    try:
        # yfinanceのTicker形式に変換
        ticker = get_ticker(stock_code)
        
        # 終了日を翌日にずらす（yfinanceは[start, end)の半開区間）
        end_date_plus_one = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        
        # 株価データを取得
        df = yf.download(
            ticker,
            start=start_date,
            end=end_date_plus_one,
            progress=False,
            threads=False,
            auto_adjust=True
        )
        
        if df.empty:
            return None, None
            
        # 開始日と終了日の株価を取得
        start_price = float(df.iloc[0]["Open"].iloc[0])
        end_price = float(df.iloc[-1]["Close"].iloc[0])
        
        return start_price, end_price
        
    except Exception as e:
        return None, None

def create_treemap(df, title, currency_symbol, value_type='投票数'):
    """
    ヒートマップを作成する関数
    
    Parameters:
    df (DataFrame): 表示するデータ
    title (str): グラフのタイトル
    currency_symbol (str): 通貨記号（円または$）
    value_type (str): サイズの基準となる値の種類（'投票数'または'損益率'）
    
    Returns:
    Figure: plotlyのFigureオブジェクト
    """
    df = df.copy()
    df['表示ラベル'] = (df['銘柄名'] + '<br>銘柄コード: ' + df['銘柄コード'].astype(str) +
                     '<br>投票数: ' + df['投票数'].astype(str) +
                     '<br>損益率: ' + df['損益率(%)'].astype(str) + '%' +
                     '<br>損益額: ' + df[f'損益額({currency_symbol})'].astype(str) + currency_symbol)
    df['絶対損益率'] = df['損益率(%)'].abs()
    
    # 上昇と下落でカテゴリ分け
    df['カテゴリ'] = df['損益率(%)'].apply(lambda x: '上昇' if x >= 0 else '下落')
    
    # インデックスかどうかを判定
    df['インデックス'] = df['銘柄コード'].isin(['^N225', 'NDX'])
    
    # サイズの基準となる値を選択
    if value_type == '損益率':
        values = '絶対損益率'
    else:
        values = '投票数'
    
    fig = px.treemap(df,
                    path=[px.Constant(title), 'カテゴリ', '銘柄名'],
                    values=values,
                    color='損益率(%)',
                    color_continuous_scale='RdBu',
                    color_continuous_midpoint=0,
                    custom_data=['表示ラベル', 'インデックス'])

    # インデックスの場合、枠線を太くして強調
    fig.update_traces(
        textinfo='text',
        text=df['表示ラベル'],
        hovertemplate='%{customdata[0]}',
        marker=dict(
            line=dict(
                width=[2 if idx else 1 for idx in df['インデックス']],
                color=['yellow' if idx else 'black' for idx in df['インデックス']]
            )
        )
    )

    fig.update_layout(margin=dict(t=50, l=25, r=25, b=25))
    return fig

def create_scatter(df, title, currency_symbol):
    """
    投票数と損益率の散布図を作成する関数
    
    Parameters:
    df (DataFrame): 表示するデータ
    title (str): グラフのタイトル
    currency_symbol (str): 通貨記号（円または$）
    
    Returns:
    Figure: plotlyのFigureオブジェクト
    """
    df = df.copy()
    df['表示ラベル'] = (df['銘柄名'] + '<br>銘柄コード: ' + df['銘柄コード'].astype(str) +
                     '<br>投票数: ' + df['投票数'].astype(str) +
                     '<br>損益率: ' + df['損益率(%)'].astype(str) + '%' +
                     '<br>損益額: ' + df[f'損益額({currency_symbol})'].astype(str) + currency_symbol)
    
    # インデックスかどうかを判定
    df['インデックス'] = df['銘柄コード'].isin(['^N225', 'NDX'])
    
    # インデックスと通常の銘柄で別々のトレースを作成
    index_df = df[df['インデックス']]
    normal_df = df[~df['インデックス']]
    
    fig = px.scatter(normal_df,
                    x='投票数',
                    y='損益率(%)',
                    color='損益率(%)',
                    color_continuous_scale='RdBu',
                    color_continuous_midpoint=0,
                    size='投票数',
                    hover_name='銘柄名',
                    custom_data=['表示ラベル'])
    
    # インデックスのトレースを追加
    if not index_df.empty:
        fig.add_trace(
            px.scatter(index_df,
                      x='投票数',
                      y='損益率(%)',
                      color='損益率(%)',
                      color_continuous_scale='RdBu',
                      color_continuous_midpoint=0,
                      size='投票数',
                      hover_name='銘柄名',
                      custom_data=['表示ラベル'])
            .update_traces(
                marker=dict(
                    symbol='star',
                    size=10,
                    line=dict(
                        width=1,
                        color='yellow'
                    )
                ),
                showlegend=False
            )
            .data[0]
        )
    
    fig.update_traces(hovertemplate='%{customdata[0]}')
    
    fig.update_layout(
        xaxis_title='投票数',
        yaxis_title='損益率(%)',
        margin=dict(t=50, l=25, r=25, b=25)
    )
    return fig

def show(selected_date):
    st.title("投票結果株価評価")
    
    # 日付選択
    col1, col2 = st.columns(2)
    with col1:
        # 投票日の選択
        selected_date = st.date_input(
            "投票日を選択",
            value=selected_date,
            min_value=datetime(2020, 1, 1).date(),
            max_value=datetime.now().date()
        )
    
    # データベース接続
    conn = get_connection()
    cursor = conn.cursor(buffered=True)
    
    # 投票日の銘柄コード一覧を取得
    selected_date_str = selected_date.strftime("%Y-%m-%d")
    
    cursor.execute("""
        SELECT DISTINCT stock_code, COUNT(*) as vote_count
        FROM vote
        WHERE vote_date = %s
        GROUP BY stock_code
    """, (selected_date_str,))
    
    voted_stocks = cursor.fetchall()
    
    if not voted_stocks:
        st.warning("指定された日付に投票された銘柄はありません。")
        return
    
    with col2:
        # 期間最終日の設定
        default_end_date = selected_date + timedelta(days=7)
        if default_end_date > datetime.now().date():
            default_end_date = datetime.now().date()
        
        end_date = st.date_input(
            "評価期間最終日",
            value=default_end_date,
            min_value=selected_date,
            max_value=datetime.now().date()
        )
    
    # セッション状態の初期化
    if 'japan_df' not in st.session_state:
        st.session_state.japan_df = None
    if 'us_df' not in st.session_state:
        st.session_state.us_df = None
    if 'japan_value_type' not in st.session_state:
        st.session_state.japan_value_type = '投票数'
    if 'us_value_type' not in st.session_state:
        st.session_state.us_value_type = '投票数'
    
    if st.button("株価を取得"):
        japan_results = []
        us_results = []
        progress_bar = st.progress(0)
        total_stocks = len(voted_stocks)
        
        # デフォルトのインデックスを追加
        default_indices = [
            {'銘柄コード': '^N225', '銘柄名': '日経平均株価', '投票数': 1},
            {'銘柄コード': 'NDX', '銘柄名': 'NASDAQ-100', '投票数': 1}
        ]
        
        for i, (stock_code, vote_count) in enumerate(voted_stocks):
            try:
                # 進捗バーの更新
                progress = (i + 1) / total_stocks
                progress_bar.progress(progress)
                
                # 投票日の翌日を開始日として設定
                start_date = (selected_date + timedelta(days=1)).strftime("%Y-%m-%d")
                end_date_str = end_date.strftime("%Y-%m-%d")
                
                # 株価を取得
                start_price, end_price = get_stock_price(stock_code, start_date, end_date_str)
                
                if start_price is not None and end_price is not None:
                    # 損益率と損益額の計算
                    profit_rate = ((end_price - start_price) / start_price) * 100
                    profit_amount = end_price - start_price
                    
                    result = {
                        '銘柄コード': stock_code,
                        '銘柄名': get_stock_name(stock_code),
                        '投票数': vote_count,
                        '始値': start_price,
                        '終値': end_price,
                        '損益率(%)': round(profit_rate, 2),
                        '損益額': round(profit_amount, 2)
                    }
                    
                    # 日本株と米国株で分ける
                    if stock_code[0].isdigit():
                        japan_results.append(result)
                    else:
                        us_results.append(result)
                
            except Exception as e:
                st.error(f"銘柄コード {stock_code} の株価取得中にエラーが発生しました: {str(e)}")
        
        progress_bar.progress(1.0)
        
        # 日本株の結果を表示
        if japan_results:
            st.subheader("日本株")
            st.session_state.japan_df = pd.DataFrame(japan_results)
            st.session_state.japan_df = st.session_state.japan_df.rename(columns={'損益額': '損益額(円)'})
            
            # デフォルトのインデックスを追加
            for index in default_indices:
                if index['銘柄コード'] == '^N225':
                    start_date = (selected_date + timedelta(days=1)).strftime("%Y-%m-%d")
                    end_date_str = end_date.strftime("%Y-%m-%d")
                    start_price, end_price = get_stock_price(index['銘柄コード'], start_date, end_date_str)
                    if start_price is not None and end_price is not None:
                        profit_rate = ((end_price - start_price) / start_price) * 100
                        profit_amount = end_price - start_price
                        index_data = {
                            '銘柄コード': index['銘柄コード'],
                            '銘柄名': index['銘柄名'],
                            '投票数': index['投票数'],
                            '始値': start_price,
                            '終値': end_price,
                            '損益率(%)': round(profit_rate, 2),
                            '損益額(円)': round(profit_amount, 2)
                        }
                        st.session_state.japan_df = pd.concat([st.session_state.japan_df, pd.DataFrame([index_data])], ignore_index=True)
            
            # 投票数で降順ソート
            st.session_state.japan_df = st.session_state.japan_df.sort_values('投票数', ascending=False)
            
            # No.列を追加
            st.session_state.japan_df.insert(0, 'No.', range(1, len(st.session_state.japan_df) + 1))
            
            # 小数点の桁数を設定
            format_dict = {
                '始値': '{:.1f}',
                '終値': '{:.1f}',
                '損益率(%)': '{:.1f}',
                '損益額(円)': '{:.1f}'
            }
            
            # 損益率と損益額のスタイリング
            def style_df(df):
                # インデックス用のスタイル
                def color_row(row):
                    color = '#FF0000' if row['損益率(%)'] < 0 else 'royalblue'  # マイナスは濃い赤、プラスはロイヤルブルー
                    is_index = row['銘柄コード'] in ['^N225', 'NDX']
                    if is_index:
                        return [f'color: {color}; background-color: rgba(211, 211, 211, 0.2)'] * len(row)
                    return [f'color: {color}'] * len(row)

                styled = df.style.format(format_dict).apply(color_row, axis=1).hide(axis='index')
                return styled

            # 日本株のデータフレーム表示
            st.dataframe(style_df(st.session_state.japan_df), hide_index=True)
            
            # 日本株のヒートマップ表示
            st.subheader("日本株 損益率ヒートマップ")
            value_type = st.radio(
                "サイズの基準",
                ["投票数", "損益率"],
                key="japan_value_type",
                horizontal=True
            )
            fig = create_treemap(st.session_state.japan_df, "日本株", "円", value_type)
            st.plotly_chart(fig, use_container_width=True)
            
            # 日本株の散布図表示
            st.subheader("日本株 投票数と損益率の関係")
            fig = create_scatter(st.session_state.japan_df, "日本株", "円")
            st.plotly_chart(fig, use_container_width=True)
            
            # 日本株のCSVダウンロードボタン
            japan_csv = st.session_state.japan_df.to_csv(index=False).encode('shift-jis', errors='replace')
            st.download_button(
                label="日本株のCSVダウンロード",
                data=japan_csv,
                file_name=f"japan_stock_evaluation_{selected_date.strftime('%Y%m%d')}.csv",
                mime='text/csv',
            )
        
        # 米国株の結果を表示
        if us_results:
            st.subheader("米国株")
            st.session_state.us_df = pd.DataFrame(us_results)
            st.session_state.us_df = st.session_state.us_df.rename(columns={'損益額': '損益額($)'})
            
            # デフォルトのインデックスを追加
            for index in default_indices:
                if index['銘柄コード'] == 'NDX':
                    start_date = (selected_date + timedelta(days=1)).strftime("%Y-%m-%d")
                    end_date_str = end_date.strftime("%Y-%m-%d")
                    start_price, end_price = get_stock_price(index['銘柄コード'], start_date, end_date_str)
                    if start_price is not None and end_price is not None:
                        profit_rate = ((end_price - start_price) / start_price) * 100
                        profit_amount = end_price - start_price
                        index_data = {
                            '銘柄コード': index['銘柄コード'],
                            '銘柄名': index['銘柄名'],
                            '投票数': index['投票数'],
                            '始値': start_price,
                            '終値': end_price,
                            '損益率(%)': round(profit_rate, 2),
                            '損益額($)': round(profit_amount, 2)
                        }
                        st.session_state.us_df = pd.concat([st.session_state.us_df, pd.DataFrame([index_data])], ignore_index=True)
            
            # 投票数で降順ソート
            st.session_state.us_df = st.session_state.us_df.sort_values('投票数', ascending=False)
            
            # No.列を追加
            st.session_state.us_df.insert(0, 'No.', range(1, len(st.session_state.us_df) + 1))
            
            # 小数点の桁数を設定
            format_dict = {
                '始値': '{:.1f}',
                '終値': '{:.1f}',
                '損益率(%)': '{:.1f}',
                '損益額($)': '{:.1f}'
            }
            
            # 米国株のデータフレーム表示
            st.dataframe(style_df(st.session_state.us_df), hide_index=True)
            
            # 米国株のヒートマップ表示
            st.subheader("米国株 損益率ヒートマップ")
            value_type = st.radio(
                "サイズの基準",
                ["投票数", "損益率"],
                key="us_value_type",
                horizontal=True
            )
            fig = create_treemap(st.session_state.us_df, "米国株", "$", value_type)
            st.plotly_chart(fig, use_container_width=True)
            
            # 米国株の散布図表示
            st.subheader("米国株 投票数と損益率の関係")
            fig = create_scatter(st.session_state.us_df, "米国株", "$")
            st.plotly_chart(fig, use_container_width=True)
            
            # 米国株のCSVダウンロードボタン
            us_csv = st.session_state.us_df.to_csv(index=False).encode('shift-jis', errors='replace')
            st.download_button(
                label="米国株のCSVダウンロード",
                data=us_csv,
                file_name=f"us_stock_evaluation_{selected_date.strftime('%Y%m%d')}.csv",
                mime='text/csv',
            )
        
        if not japan_results and not us_results:
            st.warning("株価データを取得できませんでした。")
    else:
        # 株価取得ボタンを押していない場合でも、セッション状態にデータがあれば表示
        if st.session_state.japan_df is not None:
            st.subheader("日本株")
            
            # 小数点の桁数を設定
            format_dict = {
                '始値': '{:.1f}',
                '終値': '{:.1f}',
                '損益率(%)': '{:.1f}',
                '損益額(円)': '{:.1f}'
            }
            
            # 損益率と損益額のスタイリング
            def style_df(df):
                # インデックス用のスタイル
                def color_row(row):
                    color = '#FF0000' if row['損益率(%)'] < 0 else 'royalblue'  # マイナスは濃い赤、プラスはロイヤルブルー
                    is_index = row['銘柄コード'] in ['^N225', 'NDX']
                    if is_index:
                        return [f'color: {color}; background-color: rgba(211, 211, 211, 0.2)'] * len(row)
                    return [f'color: {color}'] * len(row)

                styled = df.style.format(format_dict).apply(color_row, axis=1).hide(axis='index')
                return styled

            # 日本株のデータフレーム表示
            st.dataframe(style_df(st.session_state.japan_df), hide_index=True)
            
            # 日本株のヒートマップ表示
            st.subheader("日本株 損益率ヒートマップ")
            value_type = st.radio(
                "サイズの基準",
                ["投票数", "損益率"],
                key="japan_value_type",
                horizontal=True
            )
            fig = create_treemap(st.session_state.japan_df, "日本株", "円", value_type)
            st.plotly_chart(fig, use_container_width=True)
            
            # 日本株の散布図表示
            st.subheader("日本株 投票数と損益率の関係")
            fig = create_scatter(st.session_state.japan_df, "日本株", "円")
            st.plotly_chart(fig, use_container_width=True)
            
            japan_csv = st.session_state.japan_df.to_csv(index=False).encode('shift-jis', errors='replace')
            st.download_button(
                label="日本株のCSVダウンロード",
                data=japan_csv,
                file_name=f"japan_stock_evaluation_{selected_date.strftime('%Y%m%d')}.csv",
                mime='text/csv',
            )
        
        if st.session_state.us_df is not None:
            st.subheader("米国株")
            
            # 小数点の桁数を設定
            format_dict = {
                '始値': '{:.1f}',
                '終値': '{:.1f}',
                '損益率(%)': '{:.1f}',
                '損益額($)': '{:.1f}'
            }
            
            # 米国株のデータフレーム表示
            st.dataframe(style_df(st.session_state.us_df), hide_index=True)
            
            # 米国株のヒートマップ表示
            st.subheader("米国株 損益率ヒートマップ")
            value_type = st.radio(
                "サイズの基準",
                ["投票数", "損益率"],
                key="us_value_type",
                horizontal=True
            )
            fig = create_treemap(st.session_state.us_df, "米国株", "$", value_type)
            st.plotly_chart(fig, use_container_width=True)
            
            # 米国株の散布図表示
            st.subheader("米国株 投票数と損益率の関係")
            fig = create_scatter(st.session_state.us_df, "米国株", "$")
            st.plotly_chart(fig, use_container_width=True)
            
            us_csv = st.session_state.us_df.to_csv(index=False).encode('shift-jis', errors='replace')
            st.download_button(
                label="米国株のCSVダウンロード",
                data=us_csv,
                file_name=f"us_stock_evaluation_{selected_date.strftime('%Y%m%d')}.csv",
                mime='text/csv',
            )
    
    conn.close()
