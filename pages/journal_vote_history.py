import base64
import pandas as pd
import streamlit as st

from utils.db import get_connection
from utils.common import safe_decrypt, get_secret, get_journal_vote_uuid, JOURNAL_SCORE_OPTIONS, WAVE_POSITION_OPTIONS, BASELINE_DIRECTION_OPTIONS, VOLATILITY_SCORE_OPTIONS, EXCEPTION_OPTIONS, LEADER_EXISTS_OPTIONS, MARKET_STATE_SCORE_OPTIONS, CONFIDENCE_SCORE_OPTIONS, FEELING_SCORE_OPTIONS

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")

    st.title("ジャーナリング 回答参照")
    st.write(f"【対象日】{selected_date_str}")

    ## 暗号化キー確認
    encryption_key = get_secret("JOURNAL_ENCRYPTION_KEY")
    if not encryption_key:
        st.error("暗号化キーが設定されていません。")
        return False
    JOURNAL_ENCRYPTION_KEY = base64.b64decode(encryption_key)

    uuid = get_journal_vote_uuid()
    if uuid is None:
        st.error("Cookieが無効、またはプライベートブラウズの場合は表示できません。")
        return

    journals = _get_journals(uuid, selected_date_str)
    if journals.empty:
        st.write("対象日の回答が見つかりませんでした。")
        return

    st.info("対象日の回答は以下の通りです。")
    for _, journal in journals.iterrows():
        votes = _get_votes(journal["id"], selected_date_str)
        st.write("### 銘柄回答")
        for _, vote in votes.iterrows():
            st.write(f"#### {vote['stock_code']} {vote['stock_name']}")

            col1, col2 = st.columns(2)
            with col1:
                st.write(f"直近10本の規律可能性: {JOURNAL_SCORE_OPTIONS.get(vote['score'], vote['score'])}")
                st.write(f"波の位置: {WAVE_POSITION_OPTIONS.get(vote['wave_position'], vote['wave_position'])}")
                st.write(f"ベースラインの方向性: {BASELINE_DIRECTION_OPTIONS.get(vote['baseline_direction'], vote['baseline_direction'])}")

            with col2:
                st.write(f"ボラティリティ: {VOLATILITY_SCORE_OPTIONS.get(vote['volatility'], vote['volatility'])}")
                st.write(f"例外判断: {EXCEPTION_OPTIONS.get(vote['exception_needed'], vote['exception_needed'])}")
            if vote["exception_reason"]:
                st.write(f"例外理由: {vote['exception_reason']}")
            st.divider()

        st.write("### 自分の状態")
        st.write(f"回答番号: {journal['id']}")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"相場状態: {MARKET_STATE_SCORE_OPTIONS.get(journal['market_state'], journal['market_state'])}")
            st.write(f"自信度: {CONFIDENCE_SCORE_OPTIONS.get(journal['confidence'], journal['confidence'])}")
            st.write(f"気持ち: {FEELING_SCORE_OPTIONS.get(journal['feeling'], journal['feeling'])}")
            teacher_feedback = _get_teacher_feedback(journal['id'], selected_date_str, JOURNAL_ENCRYPTION_KEY)
            if not teacher_feedback.empty:
                st.write(f"Mr.Kへの突っ込み: {teacher_feedback.iloc[0]['teacher_feedback']}")

        with col2:
            st.write(f"ポジション量: {journal['position_ratio']}%")
            st.write(f"先導株の有無: {LEADER_EXISTS_OPTIONS.get(journal['leader_exists'], journal['leader_exists'])}")
            if journal["leader_exists"] == 1:
                st.write(f"先導株の銘柄コードまたは名称: {journal['leader_name_or_code']}")


def _get_journals(uuid, selected_date_str):
    conn = get_connection()

    try:
        return pd.read_sql_query(
            """
            SELECT
                id,
                vote_date,
                market_state,
                confidence,
                feeling,
                position_ratio,
                leader_exists,
                leader_name_or_code
            FROM journal_vote_base
            WHERE uuid = ? AND vote_date = ?
            ORDER BY id ASC
            """,
            conn,
            params=(uuid, selected_date_str)
        )

    finally:
        conn.close()


def _get_votes(journal_id, selected_date_str):
    conn = get_connection()
    try:
        return pd.read_sql_query(
            """
            SELECT
                v.id,
                v.stock_code,
                COALESCE(m.stock_name, v.stock_code) AS stock_name,
                v.score,
                v.wave_position,
                v.baseline_direction,
                v.volatility,
                v.exception_needed,
                v.exception_reason
            FROM journal_vote v
            LEFT JOIN stock_master m
                ON v.stock_code = m.stock_code
            WHERE v.vote_journal_id = ? AND v.vote_date = ?
            ORDER BY v.id
            """,
            conn,
            params=(journal_id, selected_date_str)
        )

    finally:
        conn.close()


def _get_teacher_feedback(journal_id, selected_date_str, JOURNAL_ENCRYPTION_KEY):
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
                teacher_feedback
            FROM journal_vote_feedback
            WHERE vote_journal_id = ? AND vote_date = ?
            """,
            conn,
            params=(journal_id, selected_date_str)
        )
        ## フィードバック復号化
        df["teacher_feedback"] = df["teacher_feedback"].apply(lambda x: safe_decrypt(x, JOURNAL_ENCRYPTION_KEY))
        return df

    finally:
        conn.close()
