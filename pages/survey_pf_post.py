import streamlit as st
import re
import socket
import urllib.request
from datetime import datetime
from utils.db import get_connection
from utils.common import PEAK_FINDER_REPORT_URLS

def show(selected_date):
    selected_date_str = selected_date.strftime("%Y-%m-%d")
    
    st.title("銘柄コード登録 PEAK FINDER レポート")
    st.write(f"【対象日】{selected_date_str}")
    
    # 入力方法の説明を追加
    st.info(f"""
    「規律可能性銘柄一覧」から銘柄コードを登録します。  
  
    【登録方法】
    1. パスワードを入力します。
    2. 「登録」を押します。
  
    【注意事項】  
    登録は1日1回でお願いします。  
    複数回登録しても、同じ銘柄が重複して投票対象になることはありません。
    """)
    st.markdown("---")
    
    st.write("PEAK FINDER レポートのパスワードを入力し、登録ボタンを押してください。")
    
    with st.form("pf_report_login_form"):
        password = st.text_input("パスワード", type="password")
        submitted = st.form_submit_button("登録")
        if submitted:
            if not password:
                st.warning("パスワードを入力してください。")
                return False

            if not re.compile(r"^[A-Za-z0-9]+$").fullmatch(password):
                st.warning("正しいパスワードを入力してください。")
                return False

            stock_codes = _get_stock_codes_from_report(password)
            if not stock_codes:
                st.error("銘柄コードを取得出来ませんでした。")
                return False
            st.info("銘柄コードを取得しました。")

            regist = _save_survey_data(selected_date_str, stock_codes)
            if not regist:
                st.error("銘柄コードの登録に失敗しました。")
                return False
            st.success("銘柄コードを登録しました。")
            st.write("登録した銘柄コード:")
            st.write(f"{', '.join(stock_codes)}")


def _get_stock_codes_from_report(password):
    """指定した市場の銘柄コード一覧を取得する。"""
    TABLE_PATTERN = re.compile(
        r'<table class=att-tbl>.*?</table>',
        re.IGNORECASE | re.DOTALL,
    )

    ## att-tblの2列目が銘柄コード
    COLUMN_PATTERN = re.compile(
        r"<tr\b[^>]*>(?:\s*<td\b[^>]*>.*?</td>){1}\s*<td\b[^>]*>(.*?)</td>",
        re.IGNORECASE | re.DOTALL,
    )

    PATTERNS = {
        "jp": re.compile(r"\b[0-9A-Z]{4}\b"),
        "us": re.compile(r"\b[A-Z]{1,5}(?:[.-][A-Z])?\b"),
    }

    stock_codes = []
    for market in PEAK_FINDER_REPORT_URLS:
        request = urllib.request.Request(
            PEAK_FINDER_REPORT_URLS[market],
            headers={
                "Cookie": "pfrpw=" + password,
                "User-Agent": "Mozilla/5.0",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                html = response.read().decode("utf-8")

        except urllib.error.HTTPError as e:
            st.error(f"HTTP Response Error: {e.code}")
            return False

        except (TimeoutError, socket.timeout) as e:
            st.error(f"接続がタイムアウトしました: {e}")
            return False

        except urllib.error.URLError as e:
            st.error(f"接続に失敗しました: {e.reason}")
            return False

        table = TABLE_PATTERN.search(html)  ## att-tblの1つ目が対象
        if table is None:
            st.error(
                f"銘柄一覧のテーブルを取得できませんでした: "
                f"{PEAK_FINDER_REPORT_URLS[market]}"
            )
            return False

        column = COLUMN_PATTERN.findall(table.group())  ## 2列目の銘柄コードを取得
        if not column:
            st.error(
                f"銘柄一覧のカラムを取得できませんでした: "
                f"{PEAK_FINDER_REPORT_URLS[market]}"
            )
            return False

        ## 銘柄コードの形式に一致するものだけ採用
        codes = []
        for code in column:
            code = code.strip()
            if PATTERNS[market].fullmatch(code):
                codes.append(code)

        if not codes:
            st.error("銘柄コードが見つかりませんでした。")
            return False

        stock_codes.extend(sorted(set(codes)))

    return stock_codes


def _save_survey_data(selected_date_str, stock_codes):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = []
    for code in stock_codes:
        values.append((selected_date_str, code, now))

    conn = get_connection()
    c = conn.cursor()
    try:
        conn.execute("BEGIN TRANSACTION")

        ## 一括登録
        conn.executemany(
            """
            INSERT INTO survey (survey_date, stock_code, created_at)
            VALUES (?, ?, ?)
            """,
            values,
        )

        conn.commit()

    except Exception as e:
        conn.rollback()
        st.warning(f"登録エラー: {e}")
        return False

    finally:
        conn.close()

    return True