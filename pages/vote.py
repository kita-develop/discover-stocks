import streamlit as st
from datetime import datetime
from utils.db import get_connection
from utils.common import MAX_VOTE_SELECTION
import csv
from io import StringIO

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")
    
    st.title("銘柄投票")
    st.write(f"【対象日】{selected_date_str}")
    
    # surveyテーブルから対象日の各銘柄のアンケート票数を集計
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT stock_code, COUNT(*) as survey_count FROM survey WHERE survey_date = ? GROUP BY stock_code",
        (selected_date_str,)
    )
    results = c.fetchall()
    conn.close()
    
    if results:
        # 動的な並び替え方法の選択
        sort_option = st.selectbox("並び替え方法を選択", ["銘柄コード 昇順", "アンケート票数 降順"])
        if sort_option == "銘柄コード 昇順":
            sorted_results = sorted(results, key=lambda x: x[0])
        else:
            sorted_results = sorted(results, key=lambda x: x[1], reverse=True)
        
        # テキストファイルExportボタン
        codes = [row[0] for row in sorted_results]
        file_content = "\n".join(codes)
        filename = selected_date.strftime("%Y%m%d") + "銘柄発掘.txt"
        st.download_button("銘柄コードExport", data=file_content, file_name=filename, mime="text/plain")
        
        # CSVファイルExportボタン
        csv_buffer = StringIO()
        csv_writer = csv.writer(csv_buffer)
        csv_writer.writerow(['code', 'Number of survey votes', 'TradingView URL'])  # ヘッダー行
        # データ行にTradingView URLを追加
        csv_data = [(row[0], row[1], f'https://www.tradingview.com/chart/?symbol={row[0]}') for row in sorted_results]
        csv_writer.writerows(csv_data)
        
        csv_filename = selected_date.strftime("%Y%m%d") + "集計結果.csv"
        st.download_button(
            "集計結果CSV Export",
            data=csv_buffer.getvalue(),
            file_name=csv_filename,
            mime="text/csv"
        )
        
        # 投票方法の説明
        st.info("""
        【投票方法】
        1. 注目したい銘柄のチェックボックスを選択（最大10銘柄まで）
        2. 銘柄名のリンクをクリックすると、TradingViewでチャートを確認できます
        3. 選択が完了したら下部の「投票」ボタンを押してください
        """)
        st.markdown("---")
        
        st.write("最新の集計結果（投票前のアンケート集計）")
        
        # 表形式で表示
        header_cols = st.columns([0.5, 1, 1, 1])  # カラム幅を調整
        header_cols[0].write("No.")
        header_cols[1].write("銘柄コード投票")
        header_cols[2].write("銘柄名")
        header_cols[3].write("アンケート票数")
        
        for index, row in enumerate(sorted_results, 1):  # enumerate関数で順番を付与
            stock_code, survey_count = row
            url = f"https://www.tradingview.com/chart/?symbol={stock_code}"
            stock_name_link = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{stock_code}</a>'
            cols = st.columns([0.5, 1, 1, 1])  # カラム幅を調整
            cols[0].write(f"{index}")  # 順位を表示
            cols[1].checkbox(stock_code, key=f"checkbox_{stock_code}")
            cols[2].markdown(stock_name_link, unsafe_allow_html=True)
            cols[3].write(survey_count)
        
        st.markdown("---")
        if st.button("投票"):
            save_vote_data(selected_date_str, sorted_results)
    else:
        st.write("対象日のデータはまだありません。")

def save_vote_data(selected_date_str, results):
    selected_codes = []
    for row in results:
        stock_code = row[0]
        if st.session_state.get(f"checkbox_{stock_code}"):
            selected_codes.append(stock_code)
    
    if len(selected_codes) > MAX_VOTE_SELECTION:
        st.error(f"投票は最大{MAX_VOTE_SELECTION}件まで選択可能です。現在 {len(selected_codes)} 件選択されています。")
    elif len(selected_codes) == 0:
        st.warning("1件以上選択してください。")
    else:
        conn = get_connection()
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for code in selected_codes:
            c.execute(
                "INSERT INTO vote (vote_date, stock_code, created_at) VALUES (?, ?, ?)",
                (selected_date_str, code, now)
            )
        conn.commit()
        conn.close()
        st.success("投票が保存されました。") 