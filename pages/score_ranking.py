import streamlit as st
import pandas as pd
import yfinance as yf
from utils.db import get_connection
import plotly.graph_objects as go
from utils.common import get_ticker, get_stock_name

def get_analysis_dates():
    """分析実行日の一覧を取得"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT analysis_date FROM analysis_results ORDER BY analysis_date DESC")
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

def get_analysis_results(analysis_date):
    """指定日の分析結果を取得"""
    conn = get_connection()
    try:
        # 結果をデータフレームとして取得
        df = pd.read_sql_query(
            "SELECT * FROM analysis_results WHERE analysis_date = ? ORDER BY rank ASC",
            conn,
            params=(analysis_date,)
        )
        return df
    finally:
        conn.close()

from datetime import datetime
from utils.analysis_runner import run_batch_analysis

def get_vote_dates_in_range(start_date, end_date):
    """指定期間内の投票日を取得"""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT DISTINCT vote_date FROM vote WHERE vote_date BETWEEN ? AND ? ORDER BY vote_date",
            (start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        )
        return [row[0] for row in c.fetchall()]
    finally:
        conn.close()

def show_ranking_table(df):
    """ランキング表を表示"""
    st.write(f"### ランキング ({len(df)}銘柄)")
    
    # 表示用の列を選択・リネーム
    display_cols = {
        'rank': '順位',
        'stock_code': 'コード',
        'total_score': '総合スコア',
        'score_trend': 'トレンド(40)',
        'score_stability': '安定性(30)',
        'score_liquidity': '流動性(20)',
        'score_penalty': 'ペナルティ',
        'raw_slope': '傾き(%)',
        'raw_r2': 'R2(綺麗さ)'
    }
    
    # 銘柄名を追加
    df['銘柄名'] = df['stock_code'].apply(get_stock_name)
    
    # 表示用DF作成
    df_show = df.copy()
    
    # カラムの並び順
    cols_order = ['rank', 'stock_code', '銘柄名', 'total_score', 'score_trend', 'score_stability', 'score_liquidity', 'score_penalty', 'raw_slope', 'raw_r2']
    
    # return_20dがある場合は追加
    if 'return_20d' in df.columns:
        display_cols['return_20d'] = '20日リターン(%)'
        cols_order.append('return_20d')

    df_show = df_show[cols_order].rename(columns=display_cols)
    
    # 数値のフォーマット
    column_config = {
        "総合スコア": st.column_config.NumberColumn(format="%.1f"),
        "トレンド(40)": st.column_config.NumberColumn(format="%.1f"),
        "安定性(30)": st.column_config.NumberColumn(format="%.1f"),
        "流動性(20)": st.column_config.NumberColumn(format="%.1f"),
        "ペナルティ": st.column_config.NumberColumn(format="%.0f"),
        "傾き(%)": st.column_config.NumberColumn(format="%.3f"),
        "R2(綺麗さ)": st.column_config.NumberColumn(format="%.3f"),
    }
    
    if 'return_20d' in df.columns:
        column_config["20日リターン(%)"] = st.column_config.NumberColumn(format="%.1f%%")

    st.dataframe(
        df_show,
        column_config=column_config,
        height=600,
        hide_index=True
    )

def show_detail_view(df):
    """詳細分析ビュー"""
    st.write("### 詳細分析")
    
    # 銘柄選択
    stock_options = [f"{row['rank']}位: {row['stock_code']} {get_stock_name(row['stock_code'])}" for _, row in df.iterrows()]
    selected_stock_str = st.selectbox("銘柄を選択", stock_options)
    
    if selected_stock_str:
        # 選択された銘柄のデータを取得
        rank = int(selected_stock_str.split("位")[0])
        row = df[df['rank'] == rank].iloc[0]
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("総合スコア", f"{row['total_score']:.1f} / 100")
        with col2:
            st.metric("ランキング", f"{row['rank']}位")
        with col3:
            st.metric("銘柄", f"{row['stock_code']}")
            
        st.divider()
        
        # スコア内訳（レーダーチャート風あるいはプログレスバー）
        st.write("#### スコア内訳")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.write(f"Trend (Max 40): **{row['score_trend']:.1f}**")
            st.progress(min(row['score_trend'] / 40, 1.0))
        with c2:
            st.write(f"Stability (Max 30): **{row['score_stability']:.1f}**")
            st.progress(min(row['score_stability'] / 30, 1.0))
        with c3:
            st.write(f"Liquidity (Max 20): **{row['score_liquidity']:.1f}**")
            st.progress(min(row['score_liquidity'] / 20, 1.0))
        with c4:
            st.write(f"Penalty: **-{row['score_penalty']:.0f}**")
            
        st.write("#### 生データ（特徴量）")
        st.json({
            "トレンド傾き (Slope)": f"{row['raw_slope']:.4f}% / day",
            "トレンド綺麗さ (R2)": f"{row['raw_r2']:.4f}",
            "ボラティリティ (Std)": f"{row['raw_volatility']:.4f}",
            "最大ドローダウン (MDD)": f"{row['raw_mdd']:.4f}",
            "出来高変化率": f"{row['raw_volume_ratio']:.2f}倍"
        })

def show():
    st.title("安定上昇銘柄ランキング ")

    # --- 分析実行セクション（サイドバー） ---
    with st.sidebar.expander("📊 分析の実行 (手動)", expanded=False):
        st.write("指定期間の投票データを分析します。")
        exec_start_date = st.date_input("開始日", value=datetime.now().date() - pd.Timedelta(days=30))
        exec_end_date = st.date_input("終了日", value=datetime.now().date())
        top_n = st.number_input("分析対象数 (上位N件)", min_value=5, max_value=100, value=20, step=5)
        
        if st.button("分析を実行する"):
            # 対象の投票日を取得
            vote_dates = get_vote_dates_in_range(exec_start_date, exec_end_date)
            
            if not vote_dates:
                st.warning("指定期間内に投票データがありませんでした。")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total_dates = len(vote_dates)
                for i, date_str in enumerate(vote_dates):
                    status_text.text(f"分析中: {date_str} ({i+1}/{total_dates})")
                    try:
                        # バッチ実行
                        run_batch_analysis(date_str, top_n=top_n)
                    except Exception as e:
                        st.error(f"{date_str} の分析中にエラーが発生: {e}")
                    
                    progress_bar.progress((i + 1) / total_dates)
                
                status_text.text("分析完了！")
                st.success(f"{total_dates}日分の分析が完了しました。ページをリロードしてください。")
                st.rerun()

    # --- 結果表示セクション ---
    dates = get_analysis_dates()
    if not dates:
        st.warning("まだ分析データがありません。サイドバーから分析を実行してください。")
        return

    # 日付選択
    selected_date = st.sidebar.selectbox("分析結果の日付", dates, index=0)
    
    # データ取得
    df = get_analysis_results(selected_date)
    
    if df.empty:
        st.warning("データが見つかりませんでした。")
        return

    # モード選択
    view_mode = st.sidebar.radio("表示モード", ["ランキング表", "詳細分析"], horizontal=True)
    
    # 将来リターンの計算（簡易的）
    if view_mode == "ランキング表":
        if st.sidebar.checkbox("20営業日後のリターンを表示 (時間がかかります)"):
            with st.spinner("リターン計算中..."):
                # analysis_date から 20営業日後の日付
                target_date_dt = pd.Timestamp(selected_date)
                future_date_dt = target_date_dt + pd.Timedelta(days=30) # カレンダー日で約1ヶ月後
                
                returns = []
                for code in df['stock_code']:
                    # yfinanceでデータ取得（キャッシュ推奨だが簡易実装）
                    # analysis_dateの翌日から30日後くらいまで取得
                    try:
                        ticker = get_ticker(code)
                        # 少し広めに取得
                        start_str = target_date_dt.strftime("%Y-%m-%d")
                        end_str = (future_date_dt + pd.Timedelta(days=10)).strftime("%Y-%m-%d")
                        
                        # キャッシュがないので都度取得になる点に注意
                        # 本格運用ではDBに価格を保存すべき
                        hist = st.cache_data(lambda t, s, e: yf.download(t, start=s, end=e, progress=False, auto_adjust=True))(ticker, start_str, end_str)

                        if not hist.empty:
                            # マルチインデックスの場合はレベル0を選択
                            if isinstance(hist.columns, pd.MultiIndex):
                                hist.columns = hist.columns.get_level_values(0)
                            # 基準日（分析日の翌営業日とする）の始値
                            # histはDate index
                            # analysis_dateの次の日を探す
                            
                            # 基準価格: 分析日の終値 or 翌日始値? -> 「明日以降上昇」なので翌日始値でエントリー想定
                            # analysis_dateが含まれていればその終値、なければ直後の始値
                            base_price = None
                            future_price = None
                            
                            # locで日付検索は厳密すぎるので、位置で
                            if len(hist) > 0:
                                base_price = hist['Open'].iloc[0] # 取得開始日(analysis_date)のOpen? start_strはanalysis_date当日
                                
                                # analysis_dateが土日の場合、月曜のデータが先頭に来るはず
                                # entry: 翌日の寄付き
                                
                                # 20営業日後 (約1ヶ月)
                                if len(hist) > 20:
                                    future_price = hist['Close'].iloc[20]
                                else:
                                    future_price = hist['Close'].iloc[-1] # あるだけ最新
                                
                                if base_price and future_price:
                                    ret = (future_price - base_price) / base_price * 100
                                    returns.append(ret)
                                else:
                                    returns.append(None)
                            else:
                                returns.append(None)
                        else:
                            returns.append(None)
                    except Exception as e:
                        returns.append(None)
                
                df['return_20d'] = returns
                
        show_ranking_table(df)

        if 'return_20d' in df.columns:
            st.write("※リターンは分析日翌日の始値でエントリーし、20営業日後に手仕舞いした場合の概算値です。")
    else:
        show_detail_view(df)

if __name__ == "__main__":
    show()
