import streamlit as st
from utils.common import format_vote_data_with_thresh
from utils.db import get_connection
import csv
from io import StringIO
import pandas as pd
from io import BytesIO

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")
    
    st.title("投票結果確認")
    st.write(f"【対象日】{selected_date_str}")
    
    # voteテーブルから、対象日の各銘柄の投票数を集計（多い順）
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT v.stock_code, COUNT(*) as vote_count, m.stock_name
        FROM vote v
        LEFT JOIN stock_master m ON v.stock_code = m.stock_code
        WHERE v.vote_date = ?
        GROUP BY v.stock_code
        ORDER BY vote_count DESC
        """,
        (selected_date_str,)
    )
    results = c.fetchall()
    conn.close()
    
    if results:
        row1_col1, row1_col2 = st.columns(2)
        # テキストファイルExportボタン
        codes = [row[0] for row in results]
        file_content = "\n".join(codes)
        filename = f"投票結果{selected_date.strftime('%Y%m%d')}.txt"
        with row1_col1:
            st.download_button("銘柄コードExport", data=file_content, file_name=filename, mime="text/plain")

        sorted_results_with_thresh = format_vote_data_with_thresh(results)
        if sorted_results_with_thresh:
            filename = f"投票結果{selected_date.strftime('%Y%m%d')}_票数付.txt"
            with row1_col2:
                st.download_button("銘柄コードExport(票数付)", data=sorted_results_with_thresh, file_name=filename, mime="text/plain")
        
        row2_col1, row2_col2 = st.columns(2)
        # CSVファイルExportボタン
        csv_buffer = StringIO()
        csv_writer = csv.writer(csv_buffer)
        # ヘッダー行をSJISで書き込み
        headers = ['銘柄コード', '投票数', '銘柄名', 'TradingView URL']
        csv_data = [(row[0], row[1], row[2] or row[0], f'https://www.tradingview.com/chart/?symbol={row[0]}') for row in results]
        
        # SJISでエンコードしたバイトデータを作成
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(csv_data)
        csv_str = output.getvalue()
        csv_bytes = csv_str.encode('shift-jis', errors='replace')
        
        csv_filename = f"投票結果{selected_date.strftime('%Y%m%d')}.csv"
        with row2_col1:
            st.download_button(
                "投票結果CSV Export",
                data=csv_bytes,
                file_name=csv_filename,
                mime="text/csv"
            )
        
        # Excelファイルのエクスポート
        excel_filename = f"投票結果{selected_date.strftime('%Y%m%d')}.xlsx"
        
        # DataFrameを作成（URLなし）
        excel_data = [(row[0], row[1], row[2] or row[0]) for row in results]
        df = pd.DataFrame(excel_data, columns=['銘柄コード', '投票数', '銘柄名'])
        
        # Excelファイルを作成
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='投票結果')
            
            # ワークシートの取得
            worksheet = writer.sheets['投票結果']
            
            # 列幅の自動調整
            for idx, col in enumerate(df.columns):
                max_length = max(
                    df[col].astype(str).apply(len).max(),
                    len(str(col))
                )
                worksheet.column_dimensions[chr(65 + idx)].width = max_length + 2
            
            # 銘柄名列にハイパーリンクを設定
            for row_idx, row in enumerate(results, start=2):  # start=2 はヘッダー行の後から
                stock_code = row[0]
                url = f'https://www.tradingview.com/chart/?symbol={stock_code}'
                cell = worksheet.cell(row=row_idx, column=3)  # 3列目（銘柄名）
                cell.hyperlink = url
                cell.style = 'Hyperlink'
        
        excel_data = excel_buffer.getvalue()
        with row2_col2:
            st.download_button(
                "投票結果Excel Export",
                data=excel_data,
                file_name=excel_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        
        st.markdown("---")

        # ワードクラウドの表示
        vote_dict = {row[0]: row[1] for row in results}
        try:
            from wordcloud import WordCloud
            import matplotlib.pyplot as plt
            
            # 投票結果をキャッシュキーとして使用
            @st.cache_data(ttl=None)  # TTLなし（投票結果が変わるまでキャッシュ有効）
            def generate_wordcloud(vote_data_str, date_str):
                vote_dict = eval(vote_data_str)  # 文字列から辞書に戻す
                wc = WordCloud(width=800, height=400, background_color='white').generate_from_frequencies(vote_dict)
                fig = plt.figure(figsize=(10, 5))
                plt.imshow(wc, interpolation='bilinear')
                plt.axis("off")
                return fig
            
            # 投票データを文字列化してキャッシュキーとして使用
            vote_data_str = str(vote_dict)
            fig = generate_wordcloud(vote_data_str, selected_date_str)
            st.pyplot(fig)
            
        except ImportError:
            st.error("wordcloudおよびmatplotlibライブラリが必要です。'pip install wordcloud matplotlib'でインストールしてください。")
        
        st.markdown("---")
        st.write("投票結果")
        header_cols = st.columns([0.5, 1, 2, 1])
        header_cols[0].write("No.")
        header_cols[1].write("銘柄コード")
        header_cols[2].write("銘柄名")
        header_cols[3].write("投票数")
        
        for index, row in enumerate(results, 1):
            stock_code, vote_count, stock_name = row
            display_name = stock_name or stock_code  # stock_nameがNoneの場合はstock_codeを使用
            url = f"https://www.tradingview.com/chart/?symbol={stock_code}"
            stock_name_link = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{display_name}</a>'
            
            cols = st.columns([0.5, 1, 2, 1])
            cols[0].write(f"{index}")
            cols[1].write(stock_code)
            cols[2].markdown(stock_name_link, unsafe_allow_html=True)
            cols[3].write(vote_count)
    else:
        st.write("対象日の投票結果はまだありません。") 