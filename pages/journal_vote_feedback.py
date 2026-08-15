import base64
import pandas as pd
import streamlit as st

from datetime import datetime, timedelta
from utils.db import get_connection
from utils.common import TEACHER_LOGIN_TIME_MINUTES, decrypt_string


def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")

    st.title("ジャーナリング Mr.Kフィードバック参照")
    st.write(f"【対象日】{selected_date_str}")

    ## 暗号化キー確認
    if not "JOURNAL_ENCRYPTION_KEY" in st.secrets:
        st.error("暗号化キーが設定されていません。")
        return False
    JOURNAL_ENCRYPTION_KEY = base64.b64decode(st.secrets["JOURNAL_ENCRYPTION_KEY"])

    ## 簡易ログインフォーム
    ## https://www.chatwork.com/#!rid379516146-2138915098071539712
    if not st.session_state.get("teacher_authenticated", False):
        ## ログイン実施
        login_flag = _teacher_login()
        if not login_flag:
            st.session_state.pop("teacher_authenticated", None)
            st.session_state.pop("teacher_login_time", None)
            return

        ## ログイン成功
        st.session_state["teacher_authenticated"] = True
        st.session_state["teacher_login_time"] = datetime.now()
        st.info("ログイン成功")
        st.rerun()

    ## ログイン成功後、フィードバック一覧を表示させる
    feedback_detail_df = _get_feedback_detail(selected_date_str, JOURNAL_ENCRYPTION_KEY)
    if feedback_detail_df.empty:
        st.write("対象日のデータはありません。")
        if st.button("ログアウト"):
            st.session_state.pop("teacher_authenticated", None)
            st.session_state.pop("teacher_login_time", None)
            st.rerun()
        return

    col1, col2 = st.columns(2)
    with col1:
        ## 先生向け閲覧用CSV。自由記述の文字化け防止のためUTF-8 BOM付きで出力
        csv = feedback_detail_df.to_csv(index=False, header=["回答番号", "投票日", "フィードバック内容"], encoding="utf-8-sig")
        st.download_button(label="CSVダウンロード", data=csv, file_name=f"journal_feedback_{selected_date_str}.csv", mime="text/csv")

    with col2:
        if st.button("ログアウト"):
            st.session_state.pop("teacher_authenticated", None)
            st.session_state.pop("teacher_login_time", None)
            st.rerun()


    st.subheader("フィードバック一覧")
    st.dataframe(
        feedback_detail_df,
        use_container_width=True,
        hide_index=True,
        column_config={"vote_journal_id": "回答番号", "vote_date": "投票日", "teacher_feedback": "フィードバック内容"}
    )

def _get_feedback_detail(selected_date_str, JOURNAL_ENCRYPTION_KEY):
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
			    vote_journal_id,
                vote_date,
                teacher_feedback
              FROM journal_vote_feedback
              WHERE vote_date = ?
                AND teacher_feedback IS NOT NULL
                AND teacher_feedback != ''
              ORDER BY vote_journal_id ASC
            """,
            conn,
            params=(selected_date_str,),
        )

        ## フィードバック復号化
        df["teacher_feedback"] = df["teacher_feedback"].apply(lambda x: decrypt_string(x, JOURNAL_ENCRYPTION_KEY))

        return df
    finally:
        conn.close()


def _teacher_login():
    ## 初期設定（環境変数）があるか確認
    if not "JORUNAL_TEACHER_PASSWORD" in st.secrets:
        st.error("講師用パスワードが設定されていません。")
        return False
    JORUNAL_TEACHER_PASSWORD = st.secrets["JORUNAL_TEACHER_PASSWORD"]

    ## ログイン期限
    if st.session_state.get("teacher_login_time"):
        last_login_time = st.session_state["teacher_login_time"]
        if datetime.now() - last_login_time > timedelta(minutes=TEACHER_LOGIN_TIME_MINUTES):
            st.warning("ログイン有効期限が切れました。再度ログインしてください。")
            return False

    with st.form("teacher_login_form"):
        password = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("ログイン")
        if submitted:
            if password == JORUNAL_TEACHER_PASSWORD:
                return True
            st.error(
                "ログインに失敗しました。"
                "パスワードを確認してください。"
            )

    return False