from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import base64
import os
import streamlit as st
import uuid
import yfinance as yf
from utils.db import get_connection

DUMMY_STOCK_CODE = "0000"  # 銘柄発掘、投票時の「該当なし」のダミーコード
MAX_SETS = 7               # 銘柄発掘アンケートの入力セット数
MAX_VOTE_SELECTION = 10    # 集計ページでのチェックボックスの最大選択数
STOCKS_PER_PAGE = 100      # 銘柄マスタ一覧の1ページあたりの表示件数
JOURNAL_CANDIDATE_COUNT = 5 # ジャーナリング投票の銘柄候補数

## ジャーナリング投票のアンケートの選択肢とスコアの範囲
QUESTIONNAIRE_VERSION = 1 ## 回答バージョン
JOURNAL_SCORE_OPTIONS = { 1: "ランダム", 2: "ランダム", 3: "ややランダム", 4: "ややランダム", 5: "中間", 6: "中間", 7: "やや規律的", 8: "やや規律的", 9: "規律正しい", 10: "規律正しい" } ## 規律可能性のスコアラベル
WAVE_POSITION_OPTIONS = { "bottom": "初動", "middle": "中盤", "top": "終盤", "unknown": "不明" } ## 大きな波の中の位置の選択肢
BASELINE_DIRECTION_OPTIONS = { "down": "下落", "unknown":"方向性不明確", "up": "上昇" } ## ベースラインの方向性の選択肢
VOLATILITY_SCORE_OPTIONS = { 1: "非常に小さい", 2: "小さい", 3: "中間", 4: "大きい", 5: "非常に大きい" } ## ボラティリティのスコアラベル
EXCEPTION_OPTIONS = { 0: "不要", 1: "必要" } ## 例外的な判断の選択肢
LEADER_EXISTS_OPTIONS = { 0: "ない", 1: "ある"} ## 先導株の選択肢
MARKET_STATE_SCORE_OPTIONS = { 1: "簡単", 2: "やや簡単", 3: "中間", 4: "やや難しい", 5: "難しい" } ## 相場のスコアラベル
CONFIDENCE_SCORE_OPTIONS = { 1: "自信がない", 2: "やや自信がない", 3: "中間", 4: "やや自信がある", 5: "全能感がある" } ## 自信度スコアラベル
FEELING_SCORE_OPTIONS = { 1: "不安", 2: "やや不安", 3: "中間", 4: "やや安心", 5: "安心している" } ## 自信度スコアラベル
POSITION_RATIO_MIN = 0     ## ポジション量のスコアの最小値
POSITION_RATIO_MAX = 150   ## ポジション量のスコアの最大値
POSITION_RATIO_GROUP = 30  ## ポジション量の表示区切り
TEACHER_LOGIN_TIME_MINUTES = 60   ## 講師フィードバックのログイン有効時間（分）
JOURNAL_COOKIE_EXPIRE_DAYS = 730  ## ジャーナリング投票結果参照のためのCookie期限 (日)

def get_secret(key: str) -> str:
    value = os.getenv(key)
    if value:
        return value

    try:
        return st.secrets[key]
    except Exception:
        return ""


def get_ticker(stock_code):
    """
    銘柄コードからyfinance用のtickerを生成する関数

    Parameters:
    stock_code (str): 銘柄コード

    Returns:
    str: yfinance用のticker
    """
    # 先頭文字が数値の場合は日本株として扱う
    if stock_code[0].isdigit():
        return f"{stock_code}.T"
    else:
        # それ以外は米国株として扱う
        return stock_code

def get_date_from_params(query_params):
    if 'date' in query_params:
        date_param = query_params['date'].strip()
        try:
            return datetime.strptime(date_param, "%Y%m%d").date()
        except ValueError:
            return datetime.now(ZoneInfo("Asia/Tokyo")).date()
    return datetime.now(ZoneInfo("Asia/Tokyo")).date()


THRESHOLDS=[100, 50, 30, 20, 10, 5]
def format_vote_data_with_thresh(vote_data):
    """
    投票データを閾値に基づいて区切り（###）を入れて銘柄コードをリストにする
    範囲表示形式（例：100～、50～99）で区切りを表示

    Parameters:
    vote_data (list): [銘柄コード(row[0]), 投票数(row[1])] の形式のリスト

    Returns:
    str: 区切り（###）と銘柄コードを改行コードでつないだ文字列
    """
    thresholds = sorted(THRESHOLDS, reverse=True) # 念のため区切りを降順にする
    sorted_data = sorted(vote_data, key=lambda row: row[1], reverse=True) # 念のためデータを票数の降順にする

    result = []
    # 各閾値ごとにデータを処理
    for i, threshold in enumerate(thresholds):
        # 範囲表示のラベルを作成
        if i == 0:
            # 最大閾値の場合は「100～」のような表示
            range_label = f"###{threshold}～"
        else:
            # その他の閾値の場合は「50～99」のような表示
            upper_limit = thresholds[i-1] - 1
            range_label = f"###{threshold}～{upper_limit}"

        result.append(range_label)

        # この閾値以上の投票数を持つキーを追加
        next_threshold = thresholds[i-1] if i > 0 else float('inf')

        keys_in_range = [row[0] for row in sorted_data
                         if row[1] >= threshold and row[1] < next_threshold]
        result.extend(keys_in_range)

    # 最小閾値以下のデータを処理
    min_threshold = thresholds[-1]
    result.append(f"###～{min_threshold-1}")

    keys_below_min = [row[0] for row in sorted_data if row[1] < min_threshold]
    result.extend(keys_below_min)

    return '\n'.join(result)

def get_stock_name(stock_code):
    """
    銘柄コードから銘柄名を取得する関数
    1. まずstock_masterテーブルから取得を試みる
    2. 見つからない場合はyfinanceから取得する
    3. yfinanceから取得できた場合はstock_masterテーブルに登録する
    4. それでも見つからない場合は銘柄コードを返す

    Parameters:
    stock_code (str): 銘柄コード

    Returns:
    str: 銘柄名
    """
    # データベースから銘柄名を取得
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT stock_name FROM stock_master WHERE stock_code = ?", (stock_code,))
    result = cursor.fetchone()
    
    if result:
        conn.close()
        return result[0]

    # yfinanceから銘柄名を取得
    try:
        ticker = yf.Ticker(get_ticker(stock_code))
        info = ticker.info
        if 'shortName' in info:
            stock_name = info['shortName']
            # stock_masterテーブルに登録
            cursor.execute(
                "INSERT INTO stock_master (stock_code, stock_name) VALUES (?, ?)",
                (stock_code, stock_name)
            )
            conn.commit()
            conn.close()
            return stock_name
    except Exception:
        pass
    
    conn.close()
    # どちらも見つからない場合は銘柄コードを返す
    return stock_code


## 文字列の暗号化
def encrypt_string(plaintext, JOURNAL_ENCRYPTION_KEY):
    aesgcm = AESGCM(JOURNAL_ENCRYPTION_KEY)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


## 文字列の復号化
def decrypt_string(encrypted_text, JOURNAL_ENCRYPTION_KEY):
    aesgcm = AESGCM(JOURNAL_ENCRYPTION_KEY)
    raw = base64.b64decode(encrypted_text)

    nonce = raw[:12]
    ciphertext = raw[12:]

    return aesgcm.decrypt(nonce, ciphertext, None).decode()


def safe_decrypt(encrypted_text, JOURNAL_ENCRYPTION_KEY):
    if not encrypted_text:
        return "復号に失敗しました。"

    try:
        return decrypt_string(encrypted_text, JOURNAL_ENCRYPTION_KEY)
    except Exception:
        return "復号に失敗しました。"


## ジャーナリング時のuuid取得
def get_journal_vote_uuid():
    ## 投票画面アクセス毎にUUIDを取得する
    ## 久しぶりのアクセスで期限切れにならないように都度更新する。
    ## CookieManagerでアクセスする st.rerun() によってパフォーマンス劣化するため、JavaScriptでCookie更新する.
    user_id = st.context.cookies.get("journal_vote_uuid")
    if user_id is None:
        user_id = str(uuid.uuid4())

    ## 新規登録 + 現行UUIDの期限更新
    max_age = JOURNAL_COOKIE_EXPIRE_DAYS * 24 * 60 * 60
    st.components.v1.html(
        f"""
        <script>
        document.cookie = "journal_vote_uuid={user_id}; Max-Age={max_age}; Path=/; SameSite=Lax; Secure";
        </script>
        """,
        height=0,
    )
    return user_id