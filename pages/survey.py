import streamlit as st
import re
from datetime import datetime
from utils.db import get_connection
from utils.common import MAX_SETS, get_stock_name

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")
    
    st.title("銘柄コード登録")
    st.write(f"【対象日】{selected_date_str}")
    
    # 入力方法の説明を追加
    st.info("""
    【銘柄コード入力方法】
    1. 銘柄コードを入力（半角英数字・大文字とピリオドのみ）
    2. 「確定」ボタンをクリックして入力内容を確認
    3. 銘柄名のリンクをクリックすると、TradingViewでチャートを確認できます
    4. 全ての入力が完了したら下部の「送信」ボタンを押してください
    """)
    st.markdown("---")
    
    st.write("以下の入力欄に、半角英数字・大文字とピリオドのみの銘柄コードを入力してください。")
    
    # 各入力セットを1行として作成
    for i in range(MAX_SETS):
        row = st.columns([3, 3])
        with row[0]:
            inner_cols = st.columns([3, 1])
            code_input = inner_cols[0].text_input(f"銘柄コード {i+1}", key=f"code_{i}")
            if inner_cols[1].button("確定", key=f"confirm_button_{i}"):
                if re.match(r'^[A-Z0-9.]+$', code_input):
                    st.session_state[f"confirmed_{i}"] = code_input
                    # 銘柄名を取得
                    stock_name = get_stock_name(code_input)
                    st.session_state[f"stock_name_{i}"] = stock_name
                    st.success(f"銘柄コード {code_input} を確定しました。")
                    # 銘柄名が銘柄コードと同じ場合は警告を表示
                    if stock_name == code_input:
                        st.warning("銘柄名が取得できませんでした。銘柄コードが正しいか確認してください。")
                else:
                    st.error("入力が不正です。半角英数字・大文字とピリオドのみを使用してください。")
        
        with row[1]:
            if f"confirmed_{i}" in st.session_state:
                confirmed_code = st.session_state[f"confirmed_{i}"]
                stock_name = st.session_state.get(f"stock_name_{i}", confirmed_code)
                url = f"https://jp.tradingview.com/chart/?symbol={confirmed_code}"
                st.markdown(
                    f'<a href="{url}" target="_blank" rel="noopener noreferrer">{stock_name}のチャートを表示する</a>',
                    unsafe_allow_html=True
                )
            else:
                st.write("")
    
    st.markdown("---")
    if st.button("送信"):
        save_survey_data(selected_date_str)
        st.success("入力した銘柄コードを登録しました。")

def save_survey_data(selected_date_str):
    conn = get_connection()
    c = conn.cursor(buffered=True)
    c.execute("START TRANSACTION;")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for i in range(MAX_SETS):
        if f"confirmed_{i}" in st.session_state:
            code = st.session_state[f"confirmed_{i}"]
            c.execute(
                "INSERT INTO survey (survey_date, stock_code, created_at) VALUES (%s, %s, %s)",
                (selected_date_str, code, now)
            )

    conn.commit()
    conn.close() 
