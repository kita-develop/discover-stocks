import streamlit as st
from utils.db import init_db
from utils.common import get_date_from_params
from pages import top, survey, vote, result, stock_master

# DB初期化
init_db()

# URLパラメータから対象ページとdateを取得
query_params = st.query_params
page = query_params.get('page', 'top')
selected_date = get_date_from_params(query_params)
date_str = selected_date.strftime("%Y%m%d")

# サイドバーに日付選択を追加
st.sidebar.title("日付選択")
selected_date = st.sidebar.date_input("対象日", value=selected_date)
date_str = selected_date.strftime("%Y%m%d")

# サイドバーにページリンクを追加
st.sidebar.title("ページ選択")
st.sidebar.markdown(f'<a href="./?page=top&date={date_str}" target="_self">トップページ</a>', unsafe_allow_html=True)
st.sidebar.markdown(f'<a href="./?page=stock_master&date={date_str}" target="_self">銘柄マスタ管理</a>', unsafe_allow_html=True)
st.sidebar.markdown(f'<a href="./?page=survey&date={date_str}" target="_self">① 銘柄コード登録</a>', unsafe_allow_html=True)
st.sidebar.markdown(f'<a href="./?page=vote&date={date_str}" target="_self">② 銘柄投票</a>', unsafe_allow_html=True)
st.sidebar.markdown(f'<a href="./?page=result&date={date_str}" target="_self">③ 投票結果確認</a>', unsafe_allow_html=True)

# ページの表示
if page == 'stock_master':
    stock_master.show(selected_date)
elif page == 'survey':
    survey.show(selected_date)
elif page == 'vote':
    vote.show(selected_date)
elif page == 'result':
    result.show(selected_date)
else:
    top.show(selected_date)
