from datetime import datetime, date

MAX_SETS = 7            # 銘柄発掘アンケートの入力セット数
MAX_VOTE_SELECTION = 10 # 集計ページでのチェックボックスの最大選択数
STOCKS_PER_PAGE = 100   # 銘柄マスタ一覧の1ページあたりの表示件数

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