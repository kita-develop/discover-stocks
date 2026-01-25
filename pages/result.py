import streamlit as st
from utils.common import format_vote_data_with_thresh
from utils.db import get_connection
from utils import chatwork
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
    c = conn.cursor()
    
    # 投票数の合計を取得
    c.execute(
        """
        SELECT COUNT(*) as total_votes
        FROM vote
        WHERE vote_date = ?
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
        WHERE vote_date = ?
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
            # ChatWork投稿用にファイルデータを保存
            st.session_state["cw_txt_file"] = (filename, sorted_results_with_thresh.encode("utf-8"), "text/plain")
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
            
            # ワードクラウド画像のダウンロードボタン
            buf = BytesIO()
            fig.savefig(buf, format="png", bbox_inches='tight', pad_inches=0.1)
            wordcloud_filename = f"銘柄投票{selected_date.strftime('%Y%m%d')}.png"
            wordcloud_data = buf.getvalue()
            # ChatWork投稿用にファイルデータを保存
            st.session_state["cw_wordcloud_file"] = (wordcloud_filename, wordcloud_data, "image/png")
            st.download_button(
                label="銘柄コードワードクラウド画像保存",
                data=wordcloud_data,
                file_name=wordcloud_filename,
                mime="image/png",
            )
            
            # 銘柄名のワードクラウド
            st.subheader("銘柄名のワードクラウド")
            stock_name_data_str = str(stock_name_dict)
            fig = generate_wordcloud(stock_name_data_str, selected_date_str, True)
            st.pyplot(fig)

            st.markdown("---")
            
            # ランキング画像の生成・保存
            def generate_ranking_image(data, date_str, vote_sessions):
                font_path = get_font_path()
                font_prop = None
                if font_path:
                    from matplotlib import font_manager
                    font_prop = font_manager.FontProperties(fname=font_path)
                
                # 上位20位を取得
                top_20 = data[:20]
                
                # 表データの作成
                table_data = []
                # ヘッダー
                columns = ["順位", "銘柄コード", "銘柄名", "投票数", "割合"]
                
                for i, row in enumerate(top_20, 1):
                    stock_code = row[0]
                    vote_count = row[1]
                    stock_name = row[2] or stock_code
                    percentage = (vote_count / vote_sessions * 100) if vote_sessions > 0 else 0
                    table_data.append([
                        str(i),
                        stock_code,
                        stock_name,
                        str(vote_count),
                        f"{percentage:.1f}%"
                    ])
                
                # 図の作成
                fig_table = plt.figure(figsize=(10, len(top_20) * 0.5 + 2))
                ax = fig_table.add_subplot(111)
                ax.axis('off')
                ax.set_title(f"銘柄投票ランキング ({date_str})", fontproperties=font_prop if font_path else None, fontsize=16, pad=20)
                
                # 表の描画
                table = ax.table(
                    cellText=table_data,
                    colLabels=columns,
                    loc='center',
                    cellLoc='center',
                    colWidths=[0.1, 0.15, 0.4, 0.15, 0.15]
                )
                
                table.auto_set_font_size(False)
                table.set_fontsize(12)
                table.scale(1, 1.5)
                
                # フォント設定
                if font_path:
                    for cell in table.get_celld().values():
                        cell.set_text_props(fontproperties=font_prop)
                        
                    # ヘッダーのスタイル調整
                    for (row, col), cell in table.get_celld().items():
                        if row == 0:
                            cell.set_text_props(weight='bold', fontproperties=font_prop)
                            cell.set_facecolor('#f0f0f0')

                return fig_table

            ranking_fig = generate_ranking_image(results, selected_date_str, vote_sessions)
            
            ranking_buf = BytesIO()
            ranking_fig.savefig(ranking_buf, format="png", bbox_inches='tight', pad_inches=0.1)
            ranking_filename = f"銘柄投票ランキング{selected_date.strftime('%Y%m%d')}.png"
            ranking_data = ranking_buf.getvalue()
            # ChatWork投稿用にファイルデータを保存
            st.session_state["cw_ranking_file"] = (ranking_filename, ranking_data, "image/png")
            
            st.download_button(
                label="投票結果上位20位保存",
                data=ranking_data,
                file_name=ranking_filename,
                mime="image/png",
            )
            
        except ImportError:
            st.error("wordcloudおよびmatplotlibライブラリが必要です。'pip install wordcloud matplotlib'でインストールしてください。")
        
        # ====== ChatWork投稿セクション ======
        st.markdown("---")
        st.subheader("ChatWorkに投稿")
        
        # 注意: OAuthコールバック処理はapp.pyで実行済み
        
        if not chatwork.is_logged_in():
            # ログインボタンに現在のページと日付を渡す
            chatwork.show_login_button(return_page="result", return_date=selected_date.strftime("%Y%m%d"))
        else:
            try:
                if not chatwork.is_room_member():
                    st.warning("このルームのメンバーではないため、投稿できません。先にChatWorkでルームに参加してください。")
                    chatwork.show_logout_button()
                else:
                    # ログインユーザー情報を取得
                    profile = chatwork.get_my_profile()
                    user_name = profile.get("name", "不明") if profile else "不明"
                    
                    col_status, col_logout = st.columns([3, 1])
                    with col_status:
                        st.success(f"ログインOK（{user_name}）& ルームメンバー確認OK ✅")
                    with col_logout:
                        chatwork.show_logout_button()
                    
                    # 投稿するファイルの確認
                    files_to_post = []
                    if "cw_txt_file" in st.session_state:
                        files_to_post.append(st.session_state["cw_txt_file"])
                    if "cw_wordcloud_file" in st.session_state:
                        files_to_post.append(st.session_state["cw_wordcloud_file"])
                    if "cw_ranking_file" in st.session_state:
                        files_to_post.append(st.session_state["cw_ranking_file"])
                    
                    if files_to_post:
                        st.write(f"投稿予定ファイル: {len(files_to_post)}件")
                        for fname, _, _ in files_to_post:
                            st.write(f"  - {fname}")
                        
                        if st.button("ChatWorkに投稿", type="primary"):
                            try:
                                message = f"投票結果 ({selected_date_str})"
                                chatwork.post_files_to_room(files_to_post, message)
                                st.success("ChatWorkに投稿しました！")
                            except Exception as e:
                                st.error(f"投稿エラー: {e}")
                    else:
                        st.info("投稿するファイルがありません。先に各Exportボタンを押してファイルを生成してください。")
            except Exception as e:
                st.error(f"ChatWork API エラー: {e}")
        
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
            
            percentage = (vote_count / vote_sessions * 100) if vote_sessions > 0 else 0
            cols[3].write(f"{vote_count} ({percentage:.1f}%)")
    else:
        st.write("対象日の投票結果はまだありません。") 