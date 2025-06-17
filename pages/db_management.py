import streamlit as st
import json
from datetime import datetime
from io import BytesIO
import pandas as pd
from utils.db import get_connection

def show(selected_date):
    st.title("データベース管理")
    
    tab1, tab2, tab3 = st.tabs(["エクスポート", "インポート", "データベース整理"])
    
    with tab1:
        show_export()
    
    with tab2:
        show_import()

    with tab3:
        show_maintenance_db()

def show_export():
    st.subheader("データベースエクスポート")
    
    # データベースの内容を取得
    conn = get_connection()
    
    # 各テーブルのデータを取得
    tables = {
        'stock_master': pd.read_sql_query("SELECT * FROM stock_master ORDER BY stock_code ASC", conn),
        'survey': pd.read_sql_query("SELECT * FROM survey ORDER BY id ASC", conn),
        'vote': pd.read_sql_query("SELECT * FROM vote ORDER BY id ASC", conn)
    }

    conn.close()

    # Timestamp型がjson.dumps()時にエラーになるためisoformatでstr変換している
    for df in tables.values():
        for col in df.select_dtypes(include=['datetime64[ns]']).columns:
            df[col] = df[col].apply(lambda x: x.isoformat() if pd.notnull(x) else None)

    # エクスポートファイル名
    export_filename = f"db_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    # JSONデータの作成
    export_data = {
        'export_date': datetime.now().isoformat(),
        'tables': {
            table_name: df.to_dict(orient='records')
            for table_name, df in tables.items()
        }
    }
    
    # JSONファイルのダウンロードボタン
    json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
    st.download_button(
        "データベースをエクスポート",
        data=json_str.encode('utf-8'),
        file_name=export_filename,
        mime="application/json"
    )
    
    # テーブルの内容を表示
    st.markdown("---")
    st.write("現在のデータベース内容")
    
    for table_name, df in tables.items():
        st.write(f"### {table_name}")
        st.write(f"レコード数: {len(df)}")
        if not df.empty:
            st.dataframe(df)

def show_import():
    st.subheader("データベースインポート")
    
    st.warning("""
    ⚠️ 注意
    - インポートを実行すると、既存のデータは上書きされます
    - バックアップを取ってから実行することをお勧めします
    """)
    
    uploaded_file = st.file_uploader("バックアップファイルを選択", type=['json'])
    
    if uploaded_file is not None:
        try:
            import_data = json.load(uploaded_file)
            
            # データの検証
            if 'tables' not in import_data:
                st.error("無効なバックアップファイルです。")
                return

            if st.button("インポートを実行"):
                with st.spinner("データをインポート中..."):
                    conn = get_connection()
                    c = conn.cursor(buffered=True)

                    # トランザクション開始
                    c.execute("START TRANSACTION;")
                    try:
                        # 各テーブルのデータをインポート
                        for table_name, records in import_data['tables'].items():
                            # テーブルを空にする
                            c.execute(f"DELETE FROM {table_name};")

                            if records:  # レコードが存在する場合
                                # カラム名を取得
                                columns = records[0].keys()
                                placeholders = ','.join(['%s' for _ in columns])
                                columns_str = ','.join(columns)

                                # データを挿入
                                for record in records:
                                    values = [record[col] for col in columns]
                                    c.execute(
                                        f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders});",
                                        values
                                    )

                        # 統計情報の更新
                        c.execute("ANALYZE TABLE stock_master;")
                        c.execute("ANALYZE TABLE survey;")
                        c.execute("ANALYZE TABLE vote;")

                        # コミット
                        conn.commit()
                        st.success("データのインポートが完了しました。")

                    except Exception as e:
                        # エラー時はロールバック
                        conn.rollback()
                        st.error(f"インポート中にエラーが発生しました: {str(e)}")
                    
                    finally:
                        conn.close()
                        
        except Exception as e:
            st.error(f"ファイルの読み込みに失敗しました: {str(e)}") 

def show_maintenance_db():
    st.subheader("データベース整理")

    # データベース整理の実行
    def run_maintenance_db():
        conn = get_connection()
        c = conn.cursor(buffered=True)

        try:
            # 統計情報の更新
            c.execute("ANALYZE TABLE stock_master;")
            c.execute("ANALYZE TABLE survey;")
            c.execute("ANALYZE TABLE vote;")

        except Exception as e:
            st.error(f"データベース整理に失敗しました: {str(e)}") 

        finally:
            conn.close()

    if st.button("データベース整理実行"):
        run_maintenance_db()
        st.success("データベース整理を実行しました")
