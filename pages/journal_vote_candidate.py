import re
import pandas as pd
import streamlit as st

from utils.db import get_connection, get_vote_results_top_n
from utils.common import JOURNAL_CANDIDATE_COUNT, get_stock_name

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")

    st.title("ジャーナリング 銘柄登録")
    st.write(f"【対象日】{selected_date_str}")

    results = get_vote_results_top_n(selected_date_str, top_n=JOURNAL_CANDIDATE_COUNT)
    if results:
        st.info(f"""投票に使う銘柄を{JOURNAL_CANDIDATE_COUNT}件登録します。  
        「銘柄コードを登録」から登録してください。初期値は上位{JOURNAL_CANDIDATE_COUNT}銘柄です。""")
        st.subheader("投票候補")

        existing_df = _get_existing_candidates(selected_date_str)
        if existing_df.empty:
            st.text("未登録")
            ## 初回は投票結果の上位N件をsession_stateにセットする
            for i, row in enumerate(results):
                key = f"journal_candidate_code_{i + 1}"
                if key not in st.session_state:
                    st.session_state[key] = row[0]
        else:
            st.dataframe(existing_df[["stock_code", "stock_name", "created_at"]], hide_index=True, use_container_width=True)
            for i, row in enumerate(existing_df.itertuples(index=False), start=1):
                key = f"journal_candidate_code_{i}"
                if key not in st.session_state:
                    st.session_state[key] = row.stock_code

        st.markdown("---")

        message = st.empty()
        with st.form("journal_candidate_form"):
            for i in range(JOURNAL_CANDIDATE_COUNT):
                code_key = f"journal_candidate_code_{i + 1}"
                code = st.text_input(f"銘柄コード {i + 1}", key=code_key)
                if code.strip():
                    stock_name = get_stock_name(code.strip())
                    st.caption(f"銘柄名: {stock_name}")

            col1, col2 = st.columns(2)
            with col1:
                submitted = st.form_submit_button("銘柄コードを登録")
            with col2:
                reset = st.form_submit_button("初期値に戻す")
        
        ## フォーム送信時の処理
        if submitted:
            codes = [st.session_state[f"journal_candidate_code_{i + 1}"] for i in range(JOURNAL_CANDIDATE_COUNT)]
            ok, msg = _save_candidates(selected_date_str, codes)
            if not ok:
                message.error(msg)
                return False
            st.rerun()

        if reset:
            for key in list(st.session_state):
                if key.startswith("journal_candidate_code_"):
                    del st.session_state[key]
            ok, msg = _clear_candidates(selected_date_str)
            if not ok:
                message.error(msg)
                return False
            st.rerun()

    else:
        st.write("対象日のデータはまだありません。")


def _get_existing_candidates(selected_date_str):
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
                c.stock_code,
                COALESCE(m.stock_name, c.stock_code) AS stock_name,
                c.created_at
            FROM journal_vote_candidate c
            LEFT JOIN stock_master m ON c.stock_code = m.stock_code
            WHERE c.vote_date = ?
            ORDER BY c.id
            """,
            conn,
            params=(selected_date_str,),
        )
        return df
    finally:
        conn.close()


def _clear_candidates(selected_date_str):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "DELETE FROM journal_vote_candidate WHERE vote_date = ?",
            (selected_date_str,),
        )
        conn.commit()
        return True, "銘柄コードを初期値に戻しました。"

    except Exception as e:
        return False, f"初期値に戻す際にエラーが発生しました: {str(e)}"

    finally:
        conn.close()


def _save_candidates(selected_date_str, codes):
    normalized_codes = [code.strip() for code in codes if code and code.strip()]
    message = ""

    if len(normalized_codes) == 0:
        return False, "銘柄コードを1件以上入力してください。"

    if len(normalized_codes) > JOURNAL_CANDIDATE_COUNT:
        return False, f"銘柄コードは最大{JOURNAL_CANDIDATE_COUNT}件です。"

    duplicate_codes = list(dict.fromkeys(
        code for code in normalized_codes
        if normalized_codes.count(code) > 1
    ))
    if duplicate_codes:
        return False, f"同じ銘柄コードを重複して登録できません: {', '.join(duplicate_codes)}"

    invalid_codes = [code for code in normalized_codes if not re.match(r'^[A-Z0-9.]+$', code)]
    if invalid_codes:
        message = f"以下の銘柄コードが不正です: {', '.join(invalid_codes)}"
        return False, message

    conn = get_connection()
    try:
        c = conn.cursor()
        now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

        c.execute(
            "DELETE FROM journal_vote_candidate WHERE vote_date = ?",
            (selected_date_str,),
        )

        for code in normalized_codes:
            c.execute(
                """
                INSERT INTO journal_vote_candidate (
                    vote_date, stock_code, created_at
                ) VALUES (?, ?, ?)
                """,
                (selected_date_str, code, now),
            )

        conn.commit()
        return True, "銘柄コードを登録しました。"

    finally:
        conn.close()
