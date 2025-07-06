import streamlit as st
import pandas as pd
from utils.db import get_connection
from datetime import datetime
import csv
from io import StringIO
import re  # 正規表現を使用するために追加
from utils.common import STOCKS_PER_PAGE

def show(selected_date):
    st.title("銘柄マスタ管理")
    
    # タブを作成
    tab1, tab2, tab3 = st.tabs(["一覧・編集", "新規登録", "一括登録"])
    
    with tab1:
        show_stock_list()
    
    with tab2:
        show_add_form()
    
    with tab3:
        show_bulk_import()

def show_stock_list():
    st.subheader("銘柄一覧")
    
    # DBから銘柄マスタを取得
    conn = get_connection()
    total_df = pd.read_sql("SELECT COUNT(*) as count FROM stock_master", conn)
    total_records = total_df.iloc[0]['count']
    
    # ページネーション用のセッション状態を初期化
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 0
    
    total_pages = (total_records + STOCKS_PER_PAGE - 1) // STOCKS_PER_PAGE
    
    # ページ選択のUIを表示
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("前へ") and st.session_state.current_page > 0:
            st.session_state.current_page -= 1
            st.rerun()
    
    with col2:
        st.write(f"全{total_records}件中 {st.session_state.current_page * STOCKS_PER_PAGE + 1}～{min((st.session_state.current_page + 1) * STOCKS_PER_PAGE, total_records)}件を表示")
    
    with col3:
        if st.button("次へ") and st.session_state.current_page < total_pages - 1:
            st.session_state.current_page += 1
            st.rerun()
    
    # 現在のページのデータを取得
    offset = st.session_state.current_page * STOCKS_PER_PAGE
    df = pd.read_sql(
        f"SELECT stock_code, stock_name FROM stock_master ORDER BY stock_code LIMIT {STOCKS_PER_PAGE} OFFSET {offset}",
        conn
    )
    conn.close()
    
    # 編集モード用のセッション状態を初期化
    if 'editing_stock' not in st.session_state:
        st.session_state.editing_stock = None
    
    # 一覧表示と編集機能
    for index, row in df.iterrows():
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col1:
            st.write(row['stock_code'])
        
        with col2:
            if st.session_state.editing_stock == row['stock_code']:
                new_name = st.text_input(
                    "銘柄名を編集",
                    value=row['stock_name'],
                    key=f"edit_{row['stock_code']}"
                )
                if st.button("保存", key=f"save_{row['stock_code']}"):
                    update_stock_name(row['stock_code'], new_name)
                    st.session_state.editing_stock = None
                    st.rerun()
            else:
                st.write(row['stock_name'])
        
        with col3:
            if st.session_state.editing_stock == row['stock_code']:
                if st.button("キャンセル", key=f"cancel_{row['stock_code']}"):
                    st.session_state.editing_stock = None
                    st.rerun()
            else:
                if st.button("編集", key=f"edit_{row['stock_code']}"):
                    st.session_state.editing_stock = row['stock_code']
                    st.rerun()
    
    # ページネーションUIを下部にも表示
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("前へ", key="prev_bottom") and st.session_state.current_page > 0:
            st.session_state.current_page -= 1
            st.rerun()
    
    with col2:
        st.write(f"ページ {st.session_state.current_page + 1} / {total_pages}")
    
    with col3:
        if st.button("次へ", key="next_bottom") and st.session_state.current_page < total_pages - 1:
            st.session_state.current_page += 1
            st.rerun()

def show_add_form():
    st.subheader("新規登録")
    
    with st.form("add_stock_form"):
        stock_code = st.text_input("銘柄コード（半角英数字・大文字）")
        stock_name = st.text_input("銘柄名")
        submitted = st.form_submit_button("登録")
        
        if submitted:
            if not stock_code or not stock_name:
                st.error("銘柄コードと銘柄名を入力してください。")
            elif not re.match(r'^[A-Z0-9]+$', stock_code):  # surveyページと同じ正規表現チェック
                st.error("入力が不正です。半角英数字・大文字のみを使用してください。")
            else:
                save_new_stock(stock_code, stock_name)

def show_bulk_import():
    st.subheader("CSVファイルから一括登録")
    
    st.write("CSVファイルの形式: 「銘柄コード」「銘柄名」の2列")
    st.write("※ 銘柄コードは半角英数字・大文字のみ使用可能です。")
    uploaded_file = st.file_uploader("CSVファイルを選択", type=['csv'])
    
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            if set(['銘柄コード', '銘柄名']) != set(df.columns):
                st.error("CSVファイルには「銘柄コード」「銘柄名」の2列が必要です。")
                return
            
            # 銘柄コードの形式チェック
            invalid_codes = []
            for code in df['銘柄コード']:
                if not re.match(r'^[A-Z0-9]+$', str(code)):
                    invalid_codes.append(code)
            
            if invalid_codes:
                st.error(f"以下の銘柄コードが不正です（半角英数字・大文字のみ使用可能）: {', '.join(map(str, invalid_codes))}")
                return
            
            if st.button("一括登録実行"):
                save_bulk_stocks(df)
        except Exception as e:
            st.error(f"CSVファイルの読み込みに失敗しました: {str(e)}")

def update_stock_name(stock_code, new_name):
    conn = get_connection()
    c = conn.cursor(buffered=True)
    c.execute("START TRANSACTION;")
    c.execute(
        "UPDATE stock_master SET stock_name = %s WHERE stock_code = %s",
        (new_name, stock_code)
    )
    conn.commit()
    conn.close()
    st.success("銘柄名を更新しました。")

def save_new_stock(stock_code, stock_name):
    conn = get_connection()
    c = conn.cursor(buffered=True)
    try:
        c.execute("START TRANSACTION;")
        c.execute(
            """
            INSERT INTO stock_master (stock_code, stock_name)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE stock_name = VALUES(stock_name)
            """,
            (stock_code, stock_name)
        )

        conn.commit()
        st.success(f"銘柄コード {stock_code} を登録/更新しました。")
    except Exception as e:
        st.error(f"銘柄の登録/更新に失敗しました: {str(e)}")
    finally:
        conn.close()

def save_bulk_stocks(df):
    conn = get_connection()
    c = conn.cursor(buffered=True)
    c.execute("START TRANSACTION;")

    success_count = 0
    update_count = 0
    error_count = 0
 
    for _, row in df.iterrows():
        try:
            # 既存のレコードをチェック
            c.execute("SELECT stock_code FROM stock_master WHERE stock_code = %s", (row['銘柄コード'],))
            exists = c.fetchone() is not None
            c.execute(
                """
                INSERT INTO stock_master (stock_code, stock_name)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE stock_name = VALUES(stock_name)
                """,
                (row['銘柄コード'], row['銘柄名'])
            )

            if exists:
                update_count += 1
            else:
                success_count += 1

        except Exception as e:
            error_count += 1
            st.error(f"銘柄コード {row['銘柄コード']} の登録に失敗しました: {str(e)}")

    # 統計情報の更新
    c.execute("ANALYZE TABLE stock_master;")

    conn.commit()
    conn.close()
    
    # 結果の表示
    if success_count > 0:
        st.success(f"{success_count}件の新規登録が完了しました。")
    if update_count > 0:
        st.info(f"{update_count}件の更新が完了しました。")
    if error_count > 0:
        st.warning(f"{error_count}件の処理に失敗しました。") 