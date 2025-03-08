import streamlit as st
from datetime import datetime
from utils.db import get_connection
from utils.common import MAX_VOTE_SELECTION, format_vote_data_with_thresh
import csv
from io import StringIO
import pandas as pd
from io import BytesIO

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")
    
    st.title("銘柄投票")
    st.write(f"【対象日】{selected_date_str}")
    
    # surveyテーブルから対象日の各銘柄のアンケート票数を集計
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT s.stock_code, COUNT(*) as survey_count, m.stock_name
        FROM survey s
        LEFT JOIN stock_master m ON s.stock_code = m.stock_code
        WHERE s.survey_date = ?
        GROUP BY s.stock_code
        """,
        (selected_date_str,)
    )
    results = c.fetchall()
    conn.close()
    
    if results:
        # 動的な並び替え方法の選択
        sort_option = st.selectbox("並び替え方法を選択", ["銘柄コード 昇順", "アンケート票数 降順"])
        if sort_option == "銘柄コード 昇順":
            sorted_results = sorted(results, key=lambda x: x[0])
            sort_suffix = "_コード順"
            sorted_results_with_thresh = None
        else:
            sorted_results = sorted(results, key=lambda x: x[1], reverse=True)
            sort_suffix = "_票数順"
            sorted_results_with_thresh = format_vote_data_with_thresh(results)
        
        row1_col1, row1_col2 = st.columns(2)
        # テキストファイルExportボタン
        codes = [row[0] for row in sorted_results]
        file_content = "\n".join(codes)
        filename = f"銘柄発掘{selected_date.strftime('%Y%m%d')}{sort_suffix}.txt"
        with row1_col1:
            st.download_button("銘柄コードExport", data=file_content, file_name=filename, mime="text/plain")

        if sorted_results_with_thresh:
            with row1_col2:
                filename = f"銘柄発掘{selected_date.strftime('%Y%m%d')}{sort_suffix}_票数付.txt"
                st.download_button("銘柄コードExport(票数付)", data=sorted_results_with_thresh, file_name=filename, mime="text/plain")
        
        row2_col1, row2_col2 = st.columns(2)
        # CSVファイルExportボタン
        csv_buffer = StringIO()
        csv_writer = csv.writer(csv_buffer)
        # ヘッダー行をSJISで書き込み
        headers = ['銘柄コード', 'アンケート票数', '銘柄名', 'TradingView URL']
        csv_data = [(row[0], row[1], row[2] or row[0], f'https://www.tradingview.com/chart/?symbol={row[0]}') for row in sorted_results]
        
        # SJISでエンコードしたバイトデータを作成
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(csv_data)
        csv_str = output.getvalue()
        csv_bytes = csv_str.encode('shift-jis', errors='replace')
        
        csv_filename = f"銘柄発掘{selected_date.strftime('%Y%m%d')}{sort_suffix}.csv"
        with row2_col1:
            st.download_button(
                "集計結果CSV Export",
                data=csv_bytes,
                file_name=csv_filename,
                mime="text/csv"
            )
        
        # Excelファイルのエクスポート
        excel_filename = f"銘柄発掘{selected_date.strftime('%Y%m%d')}{sort_suffix}.xlsx"
        
        # DataFrameを作成（URLなし）
        excel_data = [(row[0], row[1], row[2] or row[0]) for row in sorted_results]
        df = pd.DataFrame(excel_data, columns=['銘柄コード', 'アンケート票数', '銘柄名'])
        
        # Excelファイルを作成
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='集計結果')
            
            # ワークシートの取得
            worksheet = writer.sheets['集計結果']
            
            # 列幅の自動調整
            for idx, col in enumerate(df.columns):
                max_length = max(
                    df[col].astype(str).apply(len).max(),
                    len(str(col))
                )
                worksheet.column_dimensions[chr(65 + idx)].width = max_length + 2
            
            # 銘柄名列にハイパーリンクを設定
            for row_idx, row in enumerate(sorted_results, start=2):  # start=2 はヘッダー行の後から
                stock_code = row[0]
                url = f'https://www.tradingview.com/chart/?symbol={stock_code}'
                cell = worksheet.cell(row=row_idx, column=3)  # 3列目（銘柄名）
                cell.hyperlink = url
                cell.style = 'Hyperlink'
        
        excel_data = excel_buffer.getvalue()
        with row2_col2:
            st.download_button(
                "集計結果Excel Export",
                data=excel_data,
                file_name=excel_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
        header_cols = st.columns([0.5, 1, 1, 1])
        header_cols[0].write("No.")
        header_cols[1].write("銘柄コード投票")
        header_cols[2].write("銘柄名")
        header_cols[3].write("アンケート票数")
        
        for index, row in enumerate(sorted_results, 1):
            stock_code, survey_count, stock_name = row
            display_name = stock_name or stock_code  # stock_nameがNoneの場合はstock_codeを使用
            url = f"https://www.tradingview.com/chart/?symbol={stock_code}"
            stock_name_link = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{display_name}</a>'
            
            cols = st.columns([0.5, 1, 1, 1])
            cols[0].write(f"{index}")
            cols[1].checkbox(stock_code, key=f"checkbox_{stock_code}")
            cols[2].markdown(stock_name_link, unsafe_allow_html=True)
            cols[3].write(survey_count)
        
        st.markdown("---")
        # 投票ボタンの状態管理
        if 'vote_submitted' not in st.session_state:
            st.session_state.vote_submitted = False
        
        if not st.session_state.vote_submitted:
            if st.button("投票"):
                st.session_state.vote_submitted = True  # ボタンがクリックされたことを記録
                with st.spinner("投票を保存中..."):
                    save_vote_data(selected_date_str, sorted_results)
        else:
            st.info("投票は完了しています。")
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
        st.session_state.vote_submitted = False  # エラー時は再投票可能に
    elif len(selected_codes) == 0:
        st.warning("1件以上選択してください。")
        st.session_state.vote_submitted = False  # エラー時は再投票可能に
    else:
        # 進捗バーを表示
        progress_text = "投票データを保存中..."
        progress_bar = st.progress(0)
        
        conn = get_connection()
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for i, code in enumerate(selected_codes):
            c.execute(
                "INSERT INTO vote (vote_date, stock_code, created_at) VALUES (?, ?, ?)",
                (selected_date_str, code, now)
            )
            # 進捗バーを更新
            progress = (i + 1) / len(selected_codes)
            progress_bar.progress(progress)
        
        conn.commit()
        conn.close()
        
        # 進捗バーを完了状態に
        progress_bar.progress(1.0)
        st.success("投票が保存されました。")
        st.balloons()