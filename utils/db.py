import sqlite3
import os
from datetime import datetime
import streamlit as st

def get_db_path():
    """データベースファイルのパスを取得"""
    # Azure App Serviceの永続的なストレージパス
    if os.environ.get('WEBSITE_INSTANCE_ID'):
        # Azureの場合は/home配下を使用
        db_dir = '/home/data'
        os.makedirs(db_dir, exist_ok=True)
        return os.path.join(db_dir, 'survey.db')
    else:
        # ローカル開発環境
        return 'survey.db'

def get_connection():
    # SQLite の DB ファイル (survey.db) に接続（マルチスレッド対応のため check_same_thread=False）
    db_path = get_db_path()
    return sqlite3.connect(db_path, check_same_thread=False)

@st.cache_resource(ttl=24*3600)  # 24時間（1日）でキャッシュを無効化
def init_db():
    """
    DBの初期化を行う関数。
    @st.cache_resourceデコレータにより、1日1回のみ実行される。
    """
    conn = get_connection()
    c = conn.cursor()

    # DB高速化
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")

    # 銘柄発掘アンケートの回答保存テーブル
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS survey (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_survey_date_stock_code ON survey (survey_date, stock_code);")

    # 投票結果を保存するテーブル
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS vote (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vote_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_vote_date_stock_code ON vote (vote_date, stock_code);")

    # 銘柄マスタテーブルを追加
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_master (
            stock_code TEXT PRIMARY KEY,
            stock_name TEXT NOT NULL
        )
        """
    )

    # 分析結果（スコア詳細）を保存するテーブル
    c.execute("""
        CREATE TABLE IF NOT EXISTS analysis_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            
            -- 総合スコア
            total_score REAL,
            rank INTEGER,
            
            -- 内訳スコア (0-100)
            score_trend REAL,
            score_stability REAL,
            score_liquidity REAL,
            score_penalty REAL,
            
            -- 生データ・特徴量（検証用）
            raw_slope REAL,       -- トレンドの傾き
            raw_r2 REAL,          -- 決定係数（綺麗さ）
            raw_volatility REAL,  -- ボラティリティ
            raw_mdd REAL,         -- 最大ドローダウン
            raw_volume_ratio REAL, -- 出来高変化率
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_analysis_date_code ON analysis_results (analysis_date, stock_code);")

    conn.commit()
    conn.close()

    # キャッシュの有効期限を確認するために実行時刻をログ出力
    st.write(f"DBキャッシュ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def init_price_cache_table():
    """株価キャッシュテーブルを初期化"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_cache (
                stock_code TEXT NOT NULL,
                date TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (stock_code, date)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_cache_updated_at ON price_cache (updated_at);")
        conn.commit()
    finally:
        conn.close()

def get_vote_results_top_n(vote_date, top_n=20):
    """指定日の投票結果上位N件を取得"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT stock_code, COUNT(*) as vote_count
            FROM vote
            WHERE vote_date = ?
            GROUP BY stock_code
            ORDER BY vote_count DESC
            LIMIT ?
        """, (vote_date, top_n))
        return cursor.fetchall()  # [(銘柄コード, 投票数), ...]
    finally:
        conn.close()