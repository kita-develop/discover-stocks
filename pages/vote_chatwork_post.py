"""
ChatWork投稿専用ページ

銘柄コード登録のファイルをChatWorkに投稿する機能を提供する。
voteページからChatWork処理を分離し、パフォーマンスを改善する。
"""
import streamlit as st
from utils.common import format_vote_data_with_thresh
from utils.db import get_connection
from utils import chatwork


def _get_survey_data(selected_date_str):
    """対象日の投票結果データと投票セッション数を取得"""
    conn = get_connection()
    try:
        c = conn.cursor()

        # surveyテーブルから対象日の各銘柄のアンケート票数を集計
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
        return results
    finally:
        conn.close()


def _generate_files(results, selected_date, selected_date_str):
    """投稿用ファイル（テキスト）を生成"""
    files_to_post = []

    # 1. テキストファイル（票数付）
    sorted_results_with_thresh = format_vote_data_with_thresh(results)
    if sorted_results_with_thresh:
        filename = f"銘柄発掘{selected_date.strftime('%Y%m%d')}_票数順_票数付.txt"
        files_to_post.append((filename, sorted_results_with_thresh.encode("utf-8"), "text/plain"))

    return files_to_post


def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")
    date_str = selected_date.strftime("%Y%m%d")

    st.title("銘柄投票 ChatWork投稿")
    st.write(f"【対象日】{selected_date_str}")

    # 銘柄コード登録結果を取得
    results = _get_survey_data(selected_date_str)

    if not results:
        st.warning("対象日の銘柄コード登録がありません。銘柄コード登録がある日付を選択してください。")
        st.markdown(
            f'<a href="./?page=vote&date={date_str}" target="_self">← 銘柄投票ページに戻る</a>',
            unsafe_allow_html=True
        )
        return

    # 投稿ファイルの生成
    with st.spinner("投稿ファイルを生成中..."):
        files_to_post = _generate_files(results, selected_date, selected_date_str)

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
        chatwork.show_login_button(return_page="vote_chatwork_post", return_date=date_str)
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
                        message = f"銘柄コード登録結果 ({selected_date_str})"
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
        f'<a href="./?page=vote&date={date_str}" target="_self">← 銘柄投票ページに戻る</a>',
        unsafe_allow_html=True
    )
