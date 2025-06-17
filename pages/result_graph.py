#coding: utf_8
import streamlit as st
import datetime
import re
from utils.db import get_connection

# 取得・表示の最大日数 (DB負荷考慮)
MAX_DAYS=365
DEFAULT_DAYS=90

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")

    st.title("投票結果の推移")
    st.write(f"【投票日】{selected_date_str}")

    # REGEXPを使うための関数を定義
    def regexp(pattern, string):
        return bool(re.match(pattern, string))

    sql_template = """
        SELECT a.vote_date, a.stock_code || ' ' || COALESCE(b.stock_name, ''), count(a.stock_code) AS vote_count
         FROM vote AS a LEFT OUTER JOIN stock_master AS b ON a.stock_code = b.stock_code WHERE a.vote_date BETWEEN ? AND ? 
         AND a.stock_code REGEXP ?
         GROUP BY a.vote_date, a.stock_code;
    """

    # voteテーブルから、各投票回の投票数を取得する
    conn = get_connection()

    # REGEXP関数をSQLiteに登録
    conn.create_function('REGEXP', 2, regexp)

    # 日本株 (数字始まり)
    c = conn.cursor()
    c.execute(
        sql_template,
        ((selected_date - datetime.timedelta(days=MAX_DAYS)).strftime("%Y-%m-%d"),
         selected_date_str,
         "^[0-9]+"
        )
    )
    results_jp = c.fetchall()

    # 米国株 (英字始まり)
    c = conn.cursor()
    c.execute(
        sql_template,
        ((selected_date - datetime.timedelta(days=MAX_DAYS)).strftime("%Y-%m-%d"),
         selected_date_str,
         "^[A-Z]+"
        )
    )
    results_us = c.fetchall()

    # 投票数の合計と投票ボタンが押された回数を取得 (#13の追従)
    sql_template = """
        SELECT a.vote_date, COUNT(a.id) as total_votes, COUNT(DISTINCT a.created_at) as vote_sessions
         FROM vote AS a
         WHERE a.vote_date BETWEEN ? AND ?
         GROUP BY a.vote_date ORDER BY a.vote_date ASC;
    """
    c = conn.cursor()
    c.execute(
        sql_template,
        ((selected_date - datetime.timedelta(days=MAX_DAYS)).strftime("%Y-%m-%d"),
         selected_date_str
        )
    )
    results_vote_count = c.fetchall()
    conn.close()

    if results_jp or results_us:
        # グラフ表示
        try:
            import matplotlib
            import pandas as pd

            # 投票結果をキャッシュキーとして使用
            @st.cache_data(ttl=None)  # TTLなし（投票結果が変わるまでキャッシュ有効）

            # DataFrameに変換
            def convert_to_df(vote_results):
                df = pd.DataFrame(vote_results, columns=["日付", "銘柄コード", "投票数"])
                df["日付"] = pd.to_datetime(df["日付"])  # 日付をDatetime型に変換
                return df

            # スライダーで日付範囲を選択
            dates = pd.date_range(start = (selected_date - datetime.timedelta(days=MAX_DAYS)).strftime("%Y-%m-%d"), end = selected_date_str, freq = "D")
            default_start_date = max(dates.min(), pd.Timestamp(selected_date) - pd.Timedelta(days=DEFAULT_DAYS))

            # スライダー用意
            start_date, end_date = st.slider(
                "表示期間を選択してください:", 
                min_value=dates.min().to_pydatetime(),
                max_value=dates.max().to_pydatetime(),
                value=(default_start_date.to_pydatetime(), dates.max().to_pydatetime()),
                format="YYYY-MM-DD"
            )

            result_list = [
                {"result_key": "日本株", "result_value": results_jp},
                {"result_key": "米国株", "result_value": results_us}
            ]

            df = None
            for result in result_list:
                st.subheader(result["result_key"])
                df = convert_to_df(result["result_value"])
                filtered_df = df[(df["日付"] >= pd.to_datetime(start_date)) & (df["日付"] <= pd.to_datetime(end_date))]
                filtered_df["日付"] = filtered_df["日付"].dt.strftime("%m月%d日") # 日付の表示形式変換

                options = st.multiselect("銘柄コードを選択してください:", sorted(df["銘柄コード"].unique().tolist()), default=[])
                if options:
                     # 銘柄コードがない日付に NaN（欠損値）を入れる対応
                     df_pivot = filtered_df.pivot(index="日付", columns="銘柄コード", values="投票数")
                     df_selected = df_pivot.reindex(columns=options)  # 存在しない場合は NaN になる
                     st.line_chart(df_selected, use_container_width=True)

                else:
                    st.line_chart(filtered_df, x="日付", y="投票数", color="銘柄コード", use_container_width=True)

            # 投票数の合計と投票ボタンが押された回数の表示 (#13の追従)
            # SQLの結果をDataFrameに変換
            df_vote = pd.DataFrame(results_vote_count, columns=["日付", "投票数の合計", "投票ボタンが押された回数"])
            df_vote["日付"] = pd.to_datetime(df_vote["日付"])  # 日付をDatetime型に変換

            # スライダーに従って日付フィルタ
            filtered_df_vote = df_vote[(df_vote["日付"] >= pd.to_datetime(start_date)) & (df_vote["日付"] <= pd.to_datetime(end_date))]
            filtered_df_vote["日付"] = filtered_df_vote["日付"].dt.strftime("%m月%d日")

            # 投票数のグラフ
            st.subheader("投票数の合計の推移")
            st.line_chart(filtered_df_vote.set_index("日付")[["投票数の合計"]], use_container_width=True)

            # 投票セッション数のグラフ
            st.subheader("投票ボタンが押された回数の推移")
            st.line_chart(filtered_df_vote.set_index("日付")[["投票ボタンが押された回数"]], use_container_width=True)

        except ImportError:
            st.error("matplotlib, pandas ライブラリが必要です。'pip3 install matplotlib, pandas'でインストールしてください。")

    else:
        st.write("対象日の投票結果はまだありません。")