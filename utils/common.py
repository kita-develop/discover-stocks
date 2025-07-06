from datetime import datetime, date
import yfinance as yf
from utils.db import get_connection

MAX_SETS = 7            # 銘柄発掘アンケートの入力セット数
MAX_VOTE_SELECTION = 10 # 集計ページでのチェックボックスの最大選択数
STOCKS_PER_PAGE = 100   # 銘柄マスタ一覧の1ページあたりの表示件数

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
            return date.today()
    return date.today()


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
    cursor = conn.cursor(buffered=True)
    cursor.execute("SELECT stock_name FROM stock_master WHERE stock_code = %s", (stock_code,))
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
            conn.execute("START TRANSACTION;")
            cursor.execute(
                "INSERT INTO stock_master (stock_code, stock_name) VALUES (%s, %s)",
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