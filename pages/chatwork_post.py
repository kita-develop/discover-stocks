"""
ChatWork投稿専用ページ

投票結果のファイルをChatWorkに投稿する機能を提供する。
resultページからChatWork処理を分離し、パフォーマンスを改善する。
"""
import streamlit as st
from utils.common import format_vote_data_with_thresh
from utils.db import get_connection
from utils import chatwork
from io import BytesIO
import platform
import os


def get_font_path():
    """
    環境に応じて日本語フォントのパスを返す関数
    """
    app_font_path = os.path.join(os.path.dirname(__file__), "..", "fonts", "NotoSansJP-Regular.otf")
    if os.path.exists(app_font_path):
        return app_font_path
    
    system = platform.system()
    if system == "Windows":
        return "C:/Windows/Fonts/msgothic.ttc"
    elif system == "Darwin":
        possible_paths = [
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴ Pro W3.otf",
            "/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
    else:
        system_font_paths = [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.otf",
            "/usr/share/fonts/truetype/ipa/ipag.ttf",
        ]
        for path in system_font_paths:
            if os.path.exists(path):
                return path
    return None


def _get_vote_data(selected_date_str):
    """対象日の投票結果データと投票セッション数を取得"""
    conn = get_connection()
    c = conn.cursor()
    
    # 投票ボタンが押された回数
    c.execute(
        "SELECT COUNT(DISTINCT created_at) as vote_sessions FROM vote WHERE vote_date = ?",
        (selected_date_str,)
    )
    vote_sessions_result = c.fetchone()
    vote_sessions = vote_sessions_result[0] if vote_sessions_result is not None else 0
    
    # 各銘柄の投票数を集計
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
    
    return results, vote_sessions


def _generate_files(results, vote_sessions, selected_date, selected_date_str):
    """投稿用ファイル（テキスト、ワードクラウド、ランキング）を生成"""
    files_to_post = []
    
    # 1. テキストファイル（票数付）
    sorted_results_with_thresh = format_vote_data_with_thresh(results)
    if sorted_results_with_thresh:
        filename = f"投票結果{selected_date.strftime('%Y%m%d')}_票数付.txt"
        files_to_post.append((filename, sorted_results_with_thresh.encode("utf-8"), "text/plain"))
    
    # 2. ワードクラウド画像 & 3. ランキング画像
    try:
        from wordcloud import WordCloud
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        
        font_path = get_font_path()
        
        # ワードクラウド
        vote_dict = {row[0]: row[1] for row in results}
        wc = WordCloud(
            width=800, height=400,
            background_color='white',
            font_path=font_path
        ).generate_from_frequencies(vote_dict)
        
        fig_wc = plt.figure(figsize=(10, 5))
        plt.imshow(wc, interpolation='bilinear')
        plt.axis("off")
        
        buf_wc = BytesIO()
        fig_wc.savefig(buf_wc, format="png", bbox_inches='tight', pad_inches=0.1)
        plt.close(fig_wc)
        wordcloud_filename = f"銘柄投票{selected_date.strftime('%Y%m%d')}.png"
        files_to_post.append((wordcloud_filename, buf_wc.getvalue(), "image/png"))
        
        # ランキング画像
        font_prop = None
        if font_path:
            from matplotlib import font_manager
            font_prop = font_manager.FontProperties(fname=font_path)
        
        top_20 = results[:20]
        columns = ["順位", "銘柄コード", "銘柄名", "投票数", "割合"]
        table_data = []
        for i, row in enumerate(top_20, 1):
            stock_code = row[0]
            vote_count = row[1]
            stock_name = row[2] or stock_code
            percentage = (vote_count / vote_sessions * 100) if vote_sessions > 0 else 0
            table_data.append([str(i), stock_code, stock_name, str(vote_count), f"{percentage:.1f}%"])
        
        fig_table = plt.figure(figsize=(10, len(top_20) * 0.5 + 2))
        ax = fig_table.add_subplot(111)
        ax.axis('off')
        ax.set_title(
            f"銘柄投票ランキング ({selected_date_str})",
            fontproperties=font_prop if font_path else None,
            fontsize=16, pad=20
        )
        table = ax.table(
            cellText=table_data, colLabels=columns,
            loc='center', cellLoc='center',
            colWidths=[0.1, 0.15, 0.4, 0.15, 0.15]
        )
        table.auto_set_font_size(False)
        table.set_fontsize(12)
        table.scale(1, 1.5)
        
        if font_path:
            for cell in table.get_celld().values():
                cell.set_text_props(fontproperties=font_prop)
            for (row, col), cell in table.get_celld().items():
                if row == 0:
                    cell.set_text_props(weight='bold', fontproperties=font_prop)
                    cell.set_facecolor('#f0f0f0')
        
        buf_rank = BytesIO()
        fig_table.savefig(buf_rank, format="png", bbox_inches='tight', pad_inches=0.1)
        plt.close(fig_table)
        ranking_filename = f"銘柄投票ランキング{selected_date.strftime('%Y%m%d')}.png"
        files_to_post.append((ranking_filename, buf_rank.getvalue(), "image/png"))
        
    except ImportError:
        st.warning("wordcloud/matplotlibが未インストールのため、画像ファイルは生成されません。")
    
    return files_to_post


def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")
    date_str = selected_date.strftime("%Y%m%d")
    
    st.title("ChatWork投稿")
    st.write(f"【対象日】{selected_date_str}")
    
    # 投票結果データ取得
    results, vote_sessions = _get_vote_data(selected_date_str)
    
    if not results:
        st.warning("対象日の投票結果がありません。投票結果がある日付を選択してください。")
        st.markdown(
            f'<a href="./?page=result&date={date_str}" target="_self">← 投票結果確認ページに戻る</a>',
            unsafe_allow_html=True
        )
        return
    
    # 投稿ファイルの生成
    with st.spinner("投稿ファイルを生成中..."):
        files_to_post = _generate_files(results, vote_sessions, selected_date, selected_date_str)
    
    # ファイルプレビュー
    st.subheader("投稿予定ファイル")
    if files_to_post:
        for fname, data, mime in files_to_post:
            size_kb = len(data) / 1024
            st.write(f"📄 **{fname}** ({size_kb:.1f} KB)")
    else:
        st.warning("投稿するファイルがありません。")
        return
    
    st.markdown("---")
    
    # ====== ChatWork認証・投稿セクション ======
    st.subheader("ChatWork認証")
    
    if not chatwork.is_logged_in():
        st.info("ChatWorkにログインして投稿してください。")
        chatwork.show_login_button(return_page="chatwork_post", return_date=date_str)
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
                
                # 投稿ボタン
                if st.button("ChatWorkに投稿", type="primary"):
                    try:
                        message = f"投票結果 ({selected_date_str})"
                        chatwork.post_files_to_room(files_to_post, message)
                        st.success("ChatWorkに投稿しました！ 🎉")
                    except Exception as e:
                        st.error(f"投稿エラー: {e}")
        except Exception as e:
            st.error(f"ChatWork API エラー: {e}")
            st.info("トークンが無効な場合は、ログアウトしてから再度ログインしてください。")
            chatwork.show_logout_button()
    
    st.markdown("---")
    st.markdown(
        f'<a href="./?page=result&date={date_str}" target="_self">← 投票結果確認ページに戻る</a>',
        unsafe_allow_html=True
    )
