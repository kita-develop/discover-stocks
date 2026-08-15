import base64
import pandas as pd
import streamlit as st

from datetime import datetime
from utils.db import get_connection
from utils.common import encrypt_string, get_journal_vote_uuid, QUESTIONNAIRE_VERSION, JOURNAL_SCORE_OPTIONS, WAVE_POSITION_OPTIONS, BASELINE_DIRECTION_OPTIONS, VOLATILITY_SCORE_OPTIONS, EXCEPTION_OPTIONS, LEADER_EXISTS_OPTIONS, MARKET_STATE_SCORE_OPTIONS, CONFIDENCE_SCORE_OPTIONS, FEELING_SCORE_OPTIONS, POSITION_RATIO_MIN, POSITION_RATIO_MAX

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")

    st.title("ジャーナリング アンケート")
    st.write(f"【対象日】{selected_date_str}")

    results = _get_candidates(selected_date_str)
    if results.empty:
        st.write("銘柄が登録されていません。")
        return

    if not "JOURNAL_ENCRYPTION_KEY" in st.secrets:
        st.error("暗号化キーが設定されていません。")
        return False
    JOURNAL_ENCRYPTION_KEY = base64.b64decode(st.secrets["JOURNAL_ENCRYPTION_KEY"])

    st.info("銘柄毎のアンケート、下部の共通アンケートを入力後、投票ボタンを押してください。")
    if 'journal_submitted' not in st.session_state:
        st.session_state.journal_submitted = False
    submitted = False

    uuid = get_journal_vote_uuid()
    _initialize_widget_state(results)

    with st.form("journal_vote_form"):
        st.subheader("ジャーナリング銘柄の投票")
        st.text("チャートだけを見て答えてください。")
        for _, row in results.iterrows():
            stock_code = row["stock_code"]
            stock_name = row["stock_name"]

            with st.expander(f"{stock_code} - {stock_name}", expanded=True):
                url = f"https://jp.tradingview.com/chart/?symbol={stock_code}"
                st.markdown(
                    f'<a href="{url}" target="_blank" rel="noopener noreferrer">チャートを表示する</a>',
                    unsafe_allow_html=True
                )
                st.radio(
                    f"直近10本の規律可能性は？　{next(iter(JOURNAL_SCORE_OPTIONS))} 完全にランダム  -  {next(reversed(JOURNAL_SCORE_OPTIONS))} 完全に規律正しい",
                    list(JOURNAL_SCORE_OPTIONS.keys()),
                    horizontal=True,
                    key=_score_key(stock_code)
                )
                st.radio(
                    "大きな波の中でどの位置にいると思うか",
                    list(WAVE_POSITION_OPTIONS.keys()),
                    format_func=lambda key: WAVE_POSITION_OPTIONS[key],
                    horizontal=True,
                    key=_wave_position_key(stock_code),
                )
                st.radio(
                    "ベースラインの方向性について",
                    list(BASELINE_DIRECTION_OPTIONS.keys()),
                    format_func=lambda key: BASELINE_DIRECTION_OPTIONS[key],
                    horizontal=True,
                    key=_baseline_direction_key(stock_code),
                )
                st.radio(
                    "ボラティリティについて",
                    list(VOLATILITY_SCORE_OPTIONS.keys()),
                    format_func=lambda key: VOLATILITY_SCORE_OPTIONS[key],
                    horizontal=True,
                    key=_volatility_key(stock_code)
                )
                st.radio(
                    "例外的な判断が必要／不要",
                    list(EXCEPTION_OPTIONS.keys()),
                    format_func=lambda key: EXCEPTION_OPTIONS[key],
                    horizontal=True,
                    key=_exception_needed_key(stock_code),
                )
                st.text_input(
                    "「必要」と答えた場合のみ -- 理由",
                    key=_exception_reason_key(stock_code),
                    placeholder="理由を一行で入力してください",
                )

            st.markdown("---")

        st.subheader("自分の状態")
        st.text("チャートの話ではなく、あなた自身の話です。良い悪いはありません。")
        st.radio(
            "今の相場は",
            list(MARKET_STATE_SCORE_OPTIONS.keys()),
            format_func=lambda key: MARKET_STATE_SCORE_OPTIONS[key],
            horizontal=True,
            key="journal_market_state"
        )
        st.radio(
            "自分の状態は",
            list(CONFIDENCE_SCORE_OPTIONS.keys()),
            format_func=lambda key: CONFIDENCE_SCORE_OPTIONS[key],
            horizontal=True,
            key="journal_confidence"
        )
        st.radio(
            "気持ちは",
            list(FEELING_SCORE_OPTIONS.keys()),
            format_func=lambda key: FEELING_SCORE_OPTIONS[key],
            horizontal=True,
            key="journal_feeling"
        )
        st.selectbox(
            "今のポジション量は（資金に対する割合）",
            options=list(range(POSITION_RATIO_MIN, POSITION_RATIO_MAX + 1, 10)),
            key="journal_position_ratio",
        )
        st.radio(
            "先導株（または先導指数）はあると思いますか？",
            list(LEADER_EXISTS_OPTIONS.keys()),
            format_func=lambda key: LEADER_EXISTS_OPTIONS[key],
            horizontal=True,
            key="journal_leader_exists",
        )
        st.text_input(
            "「ある」と答えた方のみ──それは何だと思いますか？（銘柄名・コード）",
            key="journal_leader_name_or_code"
        )
        st.markdown("---")
        st.text_input(
            "Mr.Kへの突っ込み（任意）",
            key="journal_teacher_feedback"
        )
        submitted = st.form_submit_button("投票")

    if submitted and not st.session_state.journal_submitted:
        validation_message = _validate_inputs(results)
        if validation_message:
            st.error(validation_message)
            return

        with st.spinner("投票を保存中..."):
            ok, msg = _save_submission(
                selected_date_str=selected_date_str,
                candidates=results.to_dict(orient="records"),
                uuid=uuid,
                JOURNAL_ENCRYPTION_KEY=JOURNAL_ENCRYPTION_KEY
            )

        if ok:
            st.session_state.journal_submitted = True
            st.balloons()
            st.success(msg)
        else:
            st.error(msg)

    elif st.session_state.journal_submitted:
        st.info("投票は完了しています。")


def _get_candidates(selected_date_str):
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
                c.stock_code,
                COALESCE(m.stock_name, c.stock_code) AS stock_name
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


def _initialize_widget_state(results):
    for _, row in results.iterrows():
        code = row["stock_code"]
        if _score_key(code) not in st.session_state:
            st.session_state[_score_key(code)] = 1
        if _wave_position_key(code) not in st.session_state:
            st.session_state[_wave_position_key(code)] = "unknown"
        if _baseline_direction_key(code) not in st.session_state:
            st.session_state[_baseline_direction_key(code)] = "unknown"
        if _volatility_key(code) not in st.session_state:
            st.session_state[_volatility_key(code)] = 1
        if _exception_needed_key(code) not in st.session_state:
            st.session_state[_exception_needed_key(code)] = 0
        if _exception_reason_key(code) not in st.session_state:
            st.session_state[_exception_reason_key(code)] = None

    if "journal_market_state" not in st.session_state:
        st.session_state.journal_market_state = 1
    if "journal_confidence" not in st.session_state:
        st.session_state.journal_confidence = 1
    if "journal_feeling" not in st.session_state:
        st.session_state.journal_feeling = 1
    if "journal_position_ratio" not in st.session_state:
        st.session_state.journal_position_ratio = 0
    if "journal_leader_exists" not in st.session_state:
        st.session_state.journal_leader_exists = 0
    if "journal_leader_name_or_code" not in st.session_state:
        st.session_state.journal_leader_name_or_code = None
    if "journal_teacher_feedback" not in st.session_state:
        st.session_state.journal_teacher_feedback = None


def _validate_inputs(results):
    for _, row in results.iterrows():
        code = row["stock_code"]
        if st.session_state.get(_exception_needed_key(code)) == 1 and not st.session_state.get(_exception_reason_key(code)):
            return f"{code} は「必要」を選んだため、その理由を一行で入力してください。"

    if st.session_state.journal_leader_exists == 1 and not st.session_state.get("journal_leader_name_or_code"):
        return "「ある」を選んだ場合は、先導株または先導指数を入力してください。"

    return None


def _save_submission(selected_date_str, candidates, uuid, JOURNAL_ENCRYPTION_KEY):
    conn = get_connection()
    try:
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # トランザクション開始 (複数トランザクションのため)
        c.execute("BEGIN TRANSACTION")

        ## 共通アンケートを保存
        journal_cursor = c.execute(
            """
            INSERT INTO journal_vote_base (
                vote_date,
                uuid,
                questionnaire_version,
                market_state,
                confidence,
                feeling,
                position_ratio,
                leader_exists,
                leader_name_or_code,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                selected_date_str,
                uuid,
                QUESTIONNAIRE_VERSION,
                st.session_state.journal_market_state,
                st.session_state.journal_confidence,
                st.session_state.journal_feeling,
                st.session_state.journal_position_ratio,
                st.session_state.journal_leader_exists,
                st.session_state.journal_leader_name_or_code.strip() if st.session_state.journal_leader_exists else None,
                now
            ),
        )
        journal_id = journal_cursor.lastrowid

        ## 銘柄毎のアンケートを保存
        for candidate in candidates:
            code = candidate["stock_code"]
            c.execute(
                """
                INSERT INTO journal_vote (
                    vote_date,
                    vote_journal_id,
                    stock_code,
                    score,
                    wave_position,
                    baseline_direction,
                    volatility,
                    exception_needed,
                    exception_reason,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_date_str,
                    journal_id,
                    code,
                    st.session_state.get(_score_key(code)),
                    st.session_state.get(_wave_position_key(code)),
                    st.session_state.get(_baseline_direction_key(code)),
                    st.session_state.get(_volatility_key(code)),
                    st.session_state.get(_exception_needed_key(code)),
                    st.session_state.get(_exception_reason_key(code)).strip() if st.session_state.get(_exception_needed_key(code)) else None,
                    now
                ),
            )

        ## 講師へのフィードバックを保存
        if st.session_state.journal_teacher_feedback:
            ## フィードバック文字列暗号化
            enc_teacher_feedback = encrypt_string(st.session_state.journal_teacher_feedback.strip(), JOURNAL_ENCRYPTION_KEY)
            c.execute(
                """
                INSERT INTO journal_vote_feedback (
                    vote_date,
                    vote_journal_id,
                    teacher_feedback,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    selected_date_str,
                    journal_id,
                    enc_teacher_feedback,
                    now
                ),
            )

        # 統計情報の更新 (適宜)
        c.execute("PRAGMA optimize;")

        conn.commit()
        return True, "投票が保存されました。"

    except Exception as e:
        conn.rollback()
        return False, f"投票の保存中にエラーが発生しました: {str(e)}"

    finally:
        conn.close()


def _score_key(stock_code):
    return f"journal_score_{stock_code}"


def _wave_position_key(stock_code):
    return f"journal_wave_position_{stock_code}"


def _baseline_direction_key(stock_code):
    return f"journal_baseline_direction_{stock_code}"


def _volatility_key(stock_code):
    return f"journal_volatility_{stock_code}"


def _exception_needed_key(stock_code):
    return f"journal_exception_needed_{stock_code}"


def _exception_reason_key(stock_code):
    return f"journal_exception_reason_{stock_code}"
