import streamlit as st
from utils.common import format_vote_data_with_thresh
from utils.db import get_connection
import csv
from io import StringIO
import pandas as pd
from io import BytesIO
import platform
import os

def get_font_path():
    """
    環境に応じて日本語フォントのパスを返す関数
    
    Returns:
    str: 日本語フォントのパス
    """
    # アプリケーション内のフォントファイルのパスを取得
    app_font_path = os.path.join(os.path.dirname(__file__), "..", "fonts", "NotoSansJP-Regular.otf")
    if os.path.exists(app_font_path):
        return app_font_path
    
    # バックアップとしてシステムフォントをチェック
    system = platform.system()
    if system == "Windows":
        return "C:/Windows/Fonts/msgothic.ttc"
    elif system == "Darwin":  # macOS
        # macOS環境で一般的な日本語フォントのパス
        possible_paths = [
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴ Pro W3.otf",
            "/System/Library/Fonts/ヒラギノ明朝 ProN W3.otf",
            "/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            "/Library/Fonts/ヒラギノ角ゴ Pro W3.otf",
            "/Library/Fonts/ヒラギノ明朝 ProN W3.otf"
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
    else:  # Linux
        system_font_paths = [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.otf",
            "/usr/share/fonts/truetype/ipa/ipag.ttf",
            "/usr/share/fonts/truetype/ipa/ipagp.ttf"
        ]
        for path in system_font_paths:
            if os.path.exists(path):
                return path
    return None

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")
    
    st.title("投票結果確認")
    st.write(f"【対象日】{selected_date_str}")
    
    # 投票数の合計と投票ボタンが押された回数を取得
    conn = get_connection()
    c = conn.cursor(buffered=True)
    
    # 投票数の合計を取得
    c.execute(
        """
        SELECT COUNT(*) as total_votes
        FROM vote
        WHERE vote_date = %s
        """,
        (selected_date_str,)
    )
    result = c.fetchone()
    total_votes = result[0] if result is not None else 0
    
    # 投票ボタンが押された回数を取得（created_atが同じものを1回としてカウント）
    c.execute(
        """
        SELECT COUNT(DISTINCT created_at) as vote_sessions
        FROM vote
        WHERE vote_date = %s
        """,
        (selected_date_str,)
    )
    vote_sessions_result = c.fetchone()
    vote_sessions = vote_sessions_result[0] if vote_sessions_result is not None else 0
    
    # 投票情報を表示
    col1, col2 = st.columns(2)
    with col1:
        st.metric("投票数の合計", total_votes)
    with col2:
        st.metric("投票ボタンが押された回数", vote_sessions)
    
    # voteテーブルから、対象日の各銘柄の投票数を集計（多い順）
    c.execute(
        """
        SELECT v.stock_code, COUNT(*) as vote_count, m.stock_name
        FROM vote v
        LEFT JOIN stock_master m ON v.stock_code = m.stock_code
        WHERE v.vote_date = %s
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
        csv_data = [(row[0], row[1], row[2] or row[0], f'https://jp.tradingview.com/chart/?symbol={row[0]}') for row in results]
        
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
                url = f'https://jp.tradingview.com/chart/?symbol={stock_code}'
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
        stock_name_dict = {row[2] or row[0]: row[1] for row in results}  # 銘柄名がNoneの場合は銘柄コードを使用
        try:
            from wordcloud import WordCloud
            import matplotlib.pyplot as plt
            
            # 投票結果をキャッシュキーとして使用
            @st.cache_data(ttl=None)  # TTLなし（投票結果が変わるまでキャッシュ有効）
            def generate_wordcloud(vote_data_str, date_str, use_stock_name=False):
                vote_dict = eval(vote_data_str)  # 文字列から辞書に戻す
                # 日本語フォントのパスを取得
                font_path = get_font_path()
                if font_path is None:
                    st.warning("日本語フォントが見つかりません。日本語が正しく表示されない可能性があります。")
                
                wc = WordCloud(
                    width=800,
                    height=400,
                    background_color='white',
                    font_path=font_path
                ).generate_from_frequencies(vote_dict)
                fig = plt.figure(figsize=(10, 5))
                plt.imshow(wc, interpolation='bilinear')
                plt.axis("off")
                return fig
            
            # 銘柄コードのワードクラウド
            st.subheader("銘柄コードのワードクラウド")
            vote_data_str = str(vote_dict)
            fig = generate_wordcloud(vote_data_str, selected_date_str, False)
            st.pyplot(fig)
            
            # 銘柄名のワードクラウド
            st.subheader("銘柄名のワードクラウド")
            stock_name_data_str = str(stock_name_dict)
            fig = generate_wordcloud(stock_name_data_str, selected_date_str, True)
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
            url = f"https://jp.tradingview.com/chart/?symbol={stock_code}"
            stock_name_link = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{display_name}</a>'
            
            cols = st.columns([0.5, 1, 2, 1])
            cols[0].write(f"{index}")
            cols[1].write(stock_code)
            cols[2].markdown(stock_name_link, unsafe_allow_html=True)
            cols[3].write(vote_count)
    else:
        st.write("対象日の投票結果はまだありません。") 