import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

class StockScorer:
    def __init__(self, stock_data_dict):
        """
        stock_data_dict: { '7203': df, '9984': df, ... } 
        dfは各銘柄の120日分の株価データ（Date Index）
        """
        self.stock_data = stock_data_dict
        self.results = []

    def calculate_metrics(self, df):
        """1銘柄分の生の特徴量を計算"""
        # データが極端に少ない場合はスキップ (60日未満など)
        if len(df) < 60:
            return None
        
        close = df['Close']
        volume = df['Volume']
        
        # 1. Trend: 対数線形回帰による傾き (Slope) と決定係数 (R2)
        # 株価を対数変換することで、株価の絶対値に依存しない上昇率を算出
        # log(Price) = a * t + b  => Price = exp(b) * exp(a)^t
        y = np.log(close.values)
        X = np.arange(len(y)).reshape(-1, 1)
        
        reg = LinearRegression().fit(X, y)
        slope = reg.coef_[0] * 100  # %換算 (例: 0.001 -> 0.1%)
        r2 = reg.score(X, y)
        
        # 2. Stability: ボラティリティと最大ドローダウン
        # 対数収益率の標準偏差
        returns = close.pct_change().dropna()
        volatility = returns.std()
        
        # 最大ドローダウン (MDD)
        cumulative_max = close.cummax()
        drawdown = (close - cumulative_max) / cumulative_max
        max_drawdown = drawdown.min() # 負の値 (例: -0.15)
        
        # 3. Liquidity: 売買代金（概算）
        # 直近20日の平均
        avg_volume = volume.tail(20).mean()
        avg_price = close.tail(20).mean()
        trading_value = avg_volume * avg_price
        
        # 4. Penalty: RSI (過熱感)
        # 直近のRSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        # lossが0の場合の対策
        rs = rs.fillna(0) # loss=0ならRS無限大だが、便宜上計算できるように
        
        if len(rs) > 0:
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
        else:
            rsi = 50 # データ不足時

        # 出来高変化率 (直近5日 / 過去60日)
        vol_recent = volume.tail(5).mean()
        vol_past = volume.iloc[-65:-5].mean() if len(volume) > 65 else volume.mean()
        volume_ratio = vol_recent / vol_past if vol_past > 0 else 1.0

        return {
            'slope': slope,
            'r2': r2,
            'volatility': volatility,
            'mdd': max_drawdown,
            'trading_value': trading_value,
            'rsi': rsi,
            'volume_ratio': volume_ratio
        }

    def compute_scores(self):
        """全銘柄の特徴量を計算し、相対評価でスコア化する"""
        raw_data = []
        codes = []
        
        # 1. まず全銘柄の特徴量を計算
        for code, df in self.stock_data.items():
            metrics = self.calculate_metrics(df)
            if metrics:
                metrics['code'] = code
                raw_data.append(metrics)
                codes.append(code)
        
        if not raw_data:
            return []

        df_metrics = pd.DataFrame(raw_data)
        
        # 2. 相対評価 (Percentile Rank) で 0-100点に正規化
        # ascending=True: 値が大きいほど高順位（高得点）
        # ascending=False: 値が小さいほど高順位（高得点）
        
        def to_score(series, ascending=True):
            """順位を0-100点に変換"""
            return series.rank(pct=True, ascending=ascending) * 100

        # --- スコア計算ロジック ---
        
        # Trend Score (40点満点換算)
        # 傾きが急(Slope大) で かつ 直線に近い(R2大) ほど良い
        s_slope = to_score(df_metrics['slope'], ascending=True)
        s_r2 = to_score(df_metrics['r2'], ascending=True)
        
        # 傾きがマイナスの場合はR2が高くても意味がない（むしろ綺麗に下がっている）ので減点したいが
        # ここでは単純に重み付け。Slopeが低ければ点数低いのでOK。
        df_metrics['score_trend'] = (s_slope * 0.6 + s_r2 * 0.4)
        
        # Stability Score (30点満点換算)
        # ボラティリティが低い(std小)、MDDが小さい(0に近い=大きい) ほど良い
        s_vol = to_score(df_metrics['volatility'], ascending=False)
        s_mdd = to_score(df_metrics['mdd'], ascending=True)
        df_metrics['score_stability'] = (s_vol * 0.5 + s_mdd * 0.5)
        
        # Liquidity Score (20点満点換算)
        # 売買代金が大きいほど良い
        df_metrics['score_liquidity'] = to_score(df_metrics['trading_value'], ascending=True)
        
        # Risk Penalty (マイナス点, 絶対評価)
        # RSI 80以上: -20, 75以上: -10
        df_metrics['score_penalty'] = df_metrics['rsi'].apply(
            lambda x: 20 if x > 80 else (10 if x > 75 else 0)
        )
        # 追加: ボラティリティが極端に高い場合や出来高急減などもペナルティ候補だがまずはシンプルに

        # 総合スコア算出
        # Trend(40) + Stability(30) + Liquidity(20) + Base(10) - Penalty
        # 元の提案では合計100になるように調整。
        # ここではTrend, Stability, Liqudityがそれぞれ100点満点なので、係数を掛けて足す。
        
        raw_total = (
            df_metrics['score_trend'] * 0.4 +
            df_metrics['score_stability'] * 0.3 +
            df_metrics['score_liquidity'] * 0.2 +
            10 # ベース加点（全員10点からスタート的な）または調整
        ) - df_metrics['score_penalty']
        
        # 100点満点キャップ、0点下限
        df_metrics['total_score'] = raw_total.clip(0, 100)
        
        # ランク付け (スコアが高い順)
        df_metrics['rank'] = df_metrics['total_score'].rank(ascending=False, method='min')
        
        # カラム名のリネーム（保存用）
        # raw_slopeなどはそのまま
        
        # DataFrameを辞書リストに変換して返す
        # 小数点丸めなどはこれを使って呼び出す側でやるか、ここでやるか
        return df_metrics.to_dict('records')
