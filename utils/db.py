import mysql.connector
import os
import streamlit as st
from datetime import datetime
from dotenv import load_dotenv

class DBConfig:
    # 環境変数読み込み
    load_dotenv()
    DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
    DB_USER = os.environ.get("DB_USER", "mysqluser")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "password")
    DB_NAME = os.environ.get("DB_NAME", "survey")

def get_connection():
    conn = mysql.connector.connect(
        host=DBConfig.DB_HOST,
        user=DBConfig.DB_USER,
        password=DBConfig.DB_PASSWORD,
        database=DBConfig.DB_NAME,
        connect_timeout=30
    )
    return conn

@st.cache_resource(ttl=24*3600)  # 24時間（1日）でキャッシュを無効化
def init_db():
    """
    DBの初期化を行う関数。
    @st.cache_resourceデコレータにより、1日1回のみ実行される。
    """
    conn = get_connection()
    # Unread result found → 「前のクエリの結果をちゃんと読んでないよ」という警告 をなくすため自動読込みの有効化
    c = conn.cursor(buffered=True)

    # 銘柄発掘アンケートの回答保存テーブル
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS survey (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            survey_date TEXT NOT NULL,
            stock_code VARCHAR(10) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    c.execute(
        """
        SELECT COUNT(*) FROM information_schema.statistics
         WHERE table_schema = %s AND table_name = 'survey' AND index_name = 'idx_survey_date_stock_code'
        """, (DBConfig.DB_NAME,))
    if c.fetchone()[0] == 0:
        c.execute("CREATE INDEX idx_survey_date_stock_code ON survey (survey_date(10), stock_code(10));")

    # 投票結果を保存するテーブル
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS vote (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            vote_date TEXT NOT NULL,
            stock_code VARCHAR(10) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    c.execute(
        """
        SELECT COUNT(*) FROM information_schema.statistics
         WHERE table_schema = %s AND table_name = 'vote' AND index_name = 'idx_vote_date_stock_code'
        """, (DBConfig.DB_NAME,))
    if c.fetchone()[0] == 0:
        c.execute("CREATE INDEX idx_vote_date_stock_code ON vote (vote_date(10), stock_code(10));")

    # 銘柄マスタテーブルを追加
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_master (
            stock_code VARCHAR(10) PRIMARY KEY,
            stock_name TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()
    
    # キャッシュの有効期限を確認するために実行時刻をログ出力
    st.write(f"DBキャッシュ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}") 
