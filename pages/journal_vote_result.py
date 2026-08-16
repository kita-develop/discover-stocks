import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from collections import defaultdict
from utils.db import get_connection
from utils.common import JOURNAL_SCORE_OPTIONS, WAVE_POSITION_OPTIONS, BASELINE_DIRECTION_OPTIONS, VOLATILITY_SCORE_OPTIONS, EXCEPTION_OPTIONS, LEADER_EXISTS_OPTIONS, MARKET_STATE_SCORE_OPTIONS, CONFIDENCE_SCORE_OPTIONS, FEELING_SCORE_OPTIONS, POSITION_RATIO_MIN, POSITION_RATIO_MAX, POSITION_RATIO_GROUP

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")

    st.title("ジャーナリング アンケート結果")
    st.write(f"【対象日】{selected_date_str}")

    journal_vote_base_df = _get_journal_base(selected_date_str)
    if journal_vote_base_df.empty:
        st.write("対象日のデータはまだありません。")
        return
    journal_vote_df = _get_journal_vote(selected_date_str)
    journal_vote_base_summary_df = _get_journal_vote_base_summary(selected_date_str)
    journal_vote_summary_df = _get_journal_vote_summary(selected_date_str)

    st.subheader("集計結果")
    st.metric("アンケート回答数", len(journal_vote_base_df))

    st.markdown("---")
    for _, row in journal_vote_summary_df.iterrows():
        stock_code = row["stock_code"]
        stock_name = row["stock_name"]
        avg_stock_score = row["avg_stock_score"]
        avg_stock_volatility = row["avg_stock_volatility"]
        st.subheader(f"{stock_code} {stock_name}")

        ## 投票内容
        stock_votes = journal_vote_df[journal_vote_df["stock_code"] == stock_code].copy()

        ## ① 直近10本の規律可能性
        st.text("① 直近10本の規律可能性")
        st.caption(f"平均: {avg_stock_score:.1f}/{next(reversed(JOURNAL_SCORE_OPTIONS))}")
        _show_ratio_bar(stock_votes["score"], JOURNAL_SCORE_OPTIONS, f"{stock_code}_score")
        groups = defaultdict(list)
        for score, label in JOURNAL_SCORE_OPTIONS.items():
            groups[label].append(score)
            text = " / ".join(
                f"{min(scores)}-{max(scores)}: {label}"
                for label, scores in groups.items()
            )
        st.caption(text)

        ## ② 大きな波の中の位置
        st.text("② 大きな波の中の位置")
        _show_ratio_bar(stock_votes["wave_position"], WAVE_POSITION_OPTIONS, f"{stock_code}_wave_position")

        ## ③ ベースラインの方向性
        st.text("③ ベースラインの方向性")
        _show_ratio_bar(stock_votes["baseline_direction"], BASELINE_DIRECTION_OPTIONS, f"{stock_code}_baseline_direction")

        ## ④ ボラティリティ
        st.text("④ ボラティリティ")
        st.caption(f"平均: {avg_stock_volatility:.1f}/{next(reversed(VOLATILITY_SCORE_OPTIONS))}")
        _show_ratio_bar(stock_votes["volatility"], VOLATILITY_SCORE_OPTIONS, f"{stock_code}_volatility")
        st.caption(" / ".join(f"{k}: {v}" for k, v in VOLATILITY_SCORE_OPTIONS.items()))

        ## ⑤ 例外的な判断が必要／不要
        st.text("⑤ 例外的な判断が必要／不要")
        _show_ratio_bar(stock_votes["exception_needed"], EXCEPTION_OPTIONS, f"{stock_code}_exception_needed")

        ## ⑥ 例外的な判断が必要な場合の理由
        st.text("⑥ 例外的な判断が必要な場合の理由")
        exception_votes = stock_votes[stock_votes["exception_needed"] == 1]
        if exception_votes.empty:
            st.write("例外的な判断が必要と回答した方はいません。")
        else:
            df = exception_votes[["exception_reason"]].copy()
            df.index = range(1, len(df) + 1) ## コメント番号で、何番のコメントと一意にする
            st.dataframe(df, column_config={"exception_reason": "理由"}, use_container_width=True)

    ## 先導株の認識
    st.markdown("---")
    st.subheader("先導株の認識")
    st.caption("先導株（または先導指数）はあるか")
    _show_ratio_bar(journal_vote_base_df["leader_exists"], LEADER_EXISTS_OPTIONS, f"{stock_code}_leader_exists")

    ## 先導株の銘柄コード／名称
    journal_with_leader = journal_vote_base_df[journal_vote_base_df["leader_exists"] == 1]
    if journal_with_leader.empty:
        st.write("先導株（または先導指数）があると回答した方はいません。")
    else:
        st.text("先導株（または先導指数）の銘柄コード／名称")
        counts = (
            journal_with_leader["leader_name_or_code"].value_counts().rename_axis("銘柄コード／名称").reset_index(name="件数")
        )
        # 列順を変更
        counts = counts[["件数", "銘柄コード／名称"]]
        st.dataframe(counts, hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("みんなの状態")
    if journal_vote_base_df.empty:
        st.info("みんなの状態 アンケートの記録がありません。")
    else:
        avg_market_state   = journal_vote_base_summary_df["avg_market_state"].iloc[0]
        avg_confidence     = journal_vote_base_summary_df["avg_confidence"].iloc[0]
        avg_feeling        = journal_vote_base_summary_df["avg_feeling"].iloc[0]
        avg_position_ratio = journal_vote_base_summary_df["avg_position_ratio"].iloc[0]
        display_journal_vote_base_df = journal_vote_base_df.copy()

        ## 今の相場は
        st.text("今の相場は")
        st.caption(f"平均: {avg_market_state:.1f}/{next(reversed(MARKET_STATE_SCORE_OPTIONS))}")
        _show_ratio_bar(display_journal_vote_base_df["market_state"], MARKET_STATE_SCORE_OPTIONS, f"market_state")
        st.caption(" / ".join(f"{k}: {v}" for k, v in MARKET_STATE_SCORE_OPTIONS.items()))

        ## 自分の状態は
        st.text("自分の状態は")
        st.caption(f"平均: {avg_confidence:.1f}/{next(reversed(CONFIDENCE_SCORE_OPTIONS))}")
        _show_ratio_bar(display_journal_vote_base_df["confidence"], CONFIDENCE_SCORE_OPTIONS, f"confidence")
        st.caption(" / ".join(f"{k}: {v}" for k, v in CONFIDENCE_SCORE_OPTIONS.items()))

        ## 気持ちは
        st.text("気持ちは")
        st.caption(f"平均: {avg_feeling:.1f}/{next(reversed(FEELING_SCORE_OPTIONS))}")
        _show_ratio_bar(display_journal_vote_base_df["feeling"], FEELING_SCORE_OPTIONS, f"feeling")
        st.caption(" / ".join(f"{k}: {v}" for k, v in FEELING_SCORE_OPTIONS.items()))

        ## 今のポジション量
        st.text("今のポジション量")
        st.caption(f"平均: {avg_position_ratio:.1f}%")

        grouped_position_ratio = (
            (display_journal_vote_base_df["position_ratio"] // POSITION_RATIO_GROUP) * POSITION_RATIO_GROUP
        )
        position_ratio_options = {
            start: f"{start}～{min(start + POSITION_RATIO_GROUP - 10, POSITION_RATIO_MAX)}%"
            for start in range(POSITION_RATIO_MIN, POSITION_RATIO_MAX + 1, POSITION_RATIO_GROUP,)
        }
        _show_ratio_bar(grouped_position_ratio, position_ratio_options, f"position_ratio")


def _get_journal_vote_base_summary(selected_date_str):
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
                AVG(j.market_state) AS avg_market_state,
                AVG(j.confidence) AS avg_confidence,
                AVG(j.feeling) AS avg_feeling,
                AVG(j.position_ratio) AS avg_position_ratio
            FROM journal_vote_base j
            WHERE j.vote_date = ?
            ORDER BY j.id ASC
            """,
            conn,
            params=(selected_date_str,),
        )
        return df
    finally:
        conn.close()


def _get_journal_base(selected_date_str):
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
                j.id AS journal_id,
                j.vote_date,
                j.questionnaire_version,
                j.market_state,
                j.confidence,
                j.feeling,
                j.position_ratio,
                j.leader_exists,
                j.leader_name_or_code,
                j.created_at
            FROM journal_vote_base j
            WHERE j.vote_date = ?
            ORDER BY j.id ASC
            """,
            conn,
            params=(selected_date_str,),
        )
        return df
    finally:
        conn.close()


def _get_journal_vote_summary(selected_date_str):
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
                r.stock_code,
                COALESCE(m.stock_name, r.stock_code) AS stock_name,
                AVG(r.score) AS avg_stock_score,
                AVG(r.volatility) AS avg_stock_volatility
            FROM journal_vote r
            LEFT JOIN stock_master m ON r.stock_code = m.stock_code
            WHERE r.vote_date = ?
            GROUP BY r.stock_code
            ORDER BY r.id ASC
            """,
            conn,
            params=(selected_date_str,),
        )
        return df
    finally:
        conn.close()


def _get_journal_vote(selected_date_str):
    conn = get_connection()
    try:
        df = pd.read_sql_query(
            """
            SELECT
                r.stock_code,
                COALESCE(m.stock_name, r.stock_code) AS stock_name,
                r.score,
                r.wave_position,
                r.baseline_direction,
                r.volatility,
                r.exception_needed,
                r.exception_reason
            FROM journal_vote r
            LEFT JOIN stock_master m ON r.stock_code = m.stock_code
            WHERE r.vote_date = ?
            ORDER BY r.stock_code ASC
            """,
            conn,
            params=(selected_date_str,),
        )
        return df
    finally:
        conn.close()


def _show_ratio_bar(series, options, key=None):
    count = series.value_counts().sort_index()
    labels = [options.get(x, x) for x in count.index]
    percent = count / count.sum() * 100

    fig = go.Figure()

    for x, label, p, c in zip(count.index, labels, percent, count):
        fig.add_bar(
            x=[p],
            y=[""],
            orientation="h",
            name=label,
            text=f"{label}<br>({p:.1f}%)",
            textposition="inside",
            insidetextanchor="middle",
            textfont_size=16,
            hovertemplate=(f"{x}: {label}<br>{c}票 ({p:.1f}%)<extra></extra>"
    ),
        )

    fig.update_layout(
        barmode="stack",
        xaxis=dict(range=[0, 100], visible=False),
        yaxis=dict(showticklabels=False),
        height=120,
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False
    )
    st.plotly_chart(fig, use_container_width=True, key=key)
