import sqlite3
import os
from datetime import datetime
from zoneinfo import ZoneInfo
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


    # ジャーナリング投票の候補銘柄を保存するテーブル
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_vote_candidate (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vote_date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(vote_date, stock_code)
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_journal_vote_candidate_date ON journal_vote_candidate (vote_date);")


    # ジャーナリング投票の共通アンケート記録を保存するテーブル
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_vote_base (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vote_date TEXT NOT NULL,
            uuid TEXT NOT NULL,
            questionnaire_version INTEGER NOT NULL DEFAULT 1,
            market_state INTEGER NOT NULL,
            confidence INTEGER NOT NULL,
            feeling INTEGER NOT NULL,
            position_ratio INTEGER NOT NULL,
            leader_exists INTEGER NOT NULL,
            leader_name_or_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_journal_vote_base_date ON journal_vote_base (vote_date);")


    # ジャーナリング投票の入力を保存するテーブル
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_vote (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vote_date TEXT NOT NULL,
            vote_journal_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            score INTEGER NOT NULL,
            wave_position TEXT NOT NULL,
            baseline_direction TEXT NOT NULL,
            volatility INTEGER NOT NULL,
            exception_needed INTEGER NOT NULL,
            exception_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(vote_date, vote_journal_id, stock_code)
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_journal_vote_date ON journal_vote (vote_date);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_journal_vote_date_code ON journal_vote (vote_date, stock_code);")


    # ジャーナリング 講師へのフィードバック
    # カラム暗号化を行うため別テーブルへ切り出し。
    # 復号化キーをロストして復号化出来なくなった際に、ジャーナリングアンケートの投票結果へ影響を与えない様にする。
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS journal_vote_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vote_date TEXT NOT NULL,
            vote_journal_id INTEGER NOT NULL,
            teacher_feedback TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(vote_date, vote_journal_id)
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_journal_vote_feedback_date ON journal_vote_feedback (vote_date);")

    conn.commit()
    conn.close()

    # キャッシュの有効期限を確認するために実行時刻をログ出力
    st.write(f"DBキャッシュ: {datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M:%S JST')}")

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
