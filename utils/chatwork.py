"""
ChatWork OAuth & API連携ユーティリティ

機能:
- セッションに依存しないOAuth実装（stateにPKCE verifier埋め込み）
- HMAC署名でstate改竄防止
- クッキーによるトークン永続化（Fernet暗号化）

修正履歴:
- CookieManager に一意の key を指定
- secure / same_site 設定を環境に応じて制御
- クッキー読み取りタイミングの問題を修正
- extra_streamlit_components を廃止し、純粋なJavaScriptでクッキー操作
- st.context.cookies を使用してクッキーを読み取り（Streamlit 1.37+）
"""
import base64
import os
import hashlib
import hmac
import secrets
import time
import json
from datetime import datetime, timedelta
from urllib.parse import urlencode, quote

import requests
import streamlit as st
from cryptography.fernet import Fernet, InvalidToken


# ====== 設定 ======
def get_secret(key: str) -> str:
    v = os.getenv(key)
    if v:
        return v
    try:
        return st.secrets[key]
    except Exception:
        return ""

CLIENT_ID = get_secret("CHATWORK_CLIENT_ID")
CLIENT_SECRET = get_secret("CHATWORK_CLIENT_SECRET")
TARGET_ROOM_ID = int(get_secret("CHATWORK_ROOM_ID") or "0")
REDIRECT_URI = get_secret("CHATWORK_REDIRECT_URI")
TOKEN_ENCRYPT_KEY = get_secret("CHATWORK_TOKEN_ENCRYPT_KEY")

if not CLIENT_ID or not CLIENT_SECRET or not TARGET_ROOM_ID or not REDIRECT_URI or not TOKEN_ENCRYPT_KEY:
    st.error("Chatworkの設定が不足しています。Azureの環境変数（App settings）または secrets.toml を確認してください。")
    st.stop()

AUTH_URL = "https://www.chatwork.com/packages/oauth2/login.php"
TOKEN_URL = "https://oauth.chatwork.com/token"
API_BASE = "https://api.chatwork.com/v2"

SCOPES = "rooms.all:read_write users.profile.me:read"

# クッキー設定
COOKIE_NAME = "cw_tokens"
COOKIE_MAX_AGE_DAYS = 14  # Refresh Tokenの有効期限に合わせる

# HMAC署名シークレット（CLIENT_SECRETを使用）
_HMAC_SECRET = CLIENT_SECRET.encode("utf-8")

# Fernet暗号化用
_fernet = Fernet(TOKEN_ENCRYPT_KEY.encode("utf-8"))


def _b64(s: str) -> str:
    """Base64エンコード"""
    return base64.b64encode(s.encode("utf-8")).decode("utf-8")


def _b64url_encode(data: bytes) -> str:
    """URL-safe Base64エンコード（パディングなし）"""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    """URL-safe Base64デコード（パディング補完）"""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _pkce_verifier() -> str:
    """PKCE verifier生成"""
    return secrets.token_urlsafe(64)


def _pkce_challenge(verifier: str) -> str:
    """PKCE challenge生成 (S256)"""
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _sign_state(data: dict) -> str:
    """
    stateデータに署名してエンコード
    フォーマット: base64(json).signature
    """
    json_data = json.dumps(data, separators=(',', ':'))
    encoded_data = _b64url_encode(json_data.encode("utf-8"))
    signature = hmac.new(_HMAC_SECRET, encoded_data.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"{encoded_data}.{signature}"


def _verify_and_decode_state(state: str) -> dict | None:
    """
    署名を検証してstateデータをデコード
    Returns: 検証成功時はdict、失敗時はNone
    """
    try:
        parts = state.split(".")
        if len(parts) != 2:
            return None
        encoded_data, signature = parts
        
        # 署名検証
        expected_sig = hmac.new(_HMAC_SECRET, encoded_data.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(signature, expected_sig):
            return None
        
        # データデコード
        json_data = _b64url_decode(encoded_data).decode("utf-8")
        return json.loads(json_data)
    except Exception:
        return None


# ====== クッキー関連 ======

def _encrypt_tokens(access_token: str, refresh_token: str, expires_at: float) -> str:
    """トークン情報を暗号化"""
    data = json.dumps({
        "a": access_token,
        "r": refresh_token,
        "e": expires_at
    })
    return _fernet.encrypt(data.encode("utf-8")).decode("utf-8")


def _decrypt_tokens(encrypted: str) -> dict | None:
    """暗号化されたトークンを復号"""
    try:
        decrypted = _fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
        return json.loads(decrypted)
    except (InvalidToken, json.JSONDecodeError):
        return None


def save_tokens_to_cookie():
    """
    現在のトークンをクッキーに保存
    
    JavaScriptを使用してブラウザのクッキーを設定
    st.components.v1.html の iframe は same-origin なので parent.document.cookie でアクセス可能
    """
    if "cw_access_token" not in st.session_state:
        return
    
    # 既に保存済みの場合はスキップ
    if st.session_state.get("cw_cookie_saved"):
        return
    
    # トークンを暗号化
    encrypted = _encrypt_tokens(
        st.session_state["cw_access_token"],
        st.session_state.get("cw_refresh_token", ""),
        st.session_state.get("cw_expires_at", 0)
    )
    
    # 有効期限を明示的に設定（14日後）
    expires = datetime.now() + timedelta(days=COOKIE_MAX_AGE_DAYS)
    expires_str = expires.strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    # URLエンコード（特殊文字対策）
    encoded_value = quote(encrypted, safe='')
    
    # JavaScriptでクッキーを設定（parent.document を使用）
    cookie_script = f"""
    <script>
        try {{
            // 親ウィンドウのクッキーに設定
            parent.document.cookie = "{COOKIE_NAME}={encoded_value}; expires={expires_str}; path=/; SameSite=Lax; Secure";
            console.log("Cookie saved successfully");
        }} catch (e) {{
            console.error("Failed to save cookie:", e.name, e.message);
            // フォールバック: 現在のドキュメントに設定
            try {{
                document.cookie = "{COOKIE_NAME}={encoded_value}; expires={expires_str}; path=/; SameSite=Lax; Secure";
                console.log("Fallback cookie saved");
            }} catch (e2) {{
                console.error("Fallback also failed:", e2.name, e2.message);
            }}
        }}
    </script>
    """
    st.components.v1.html(cookie_script, height=0, width=0)
    st.session_state["cw_cookie_saved"] = True


def load_tokens_from_cookie() -> bool:
    """
    クッキーからトークンを復元してsession_stateにセット
    
    st.context.cookies を使用してブラウザのクッキーを読み取る（Streamlit 1.37+）
    Returns: 復元成功したかどうか
    """
    # 既にセッションにある場合はスキップ
    if "cw_access_token" in st.session_state:
        return True
    
    # st.context.cookies からクッキーを読み取る（Streamlit 1.37+）
    try:
        from urllib.parse import unquote
        
        cookies = st.context.cookies
        encrypted = cookies.get(COOKIE_NAME)
        
        if encrypted:
            # URLデコードしてから復号（保存時にquote()でエンコードしているため）
            decoded_encrypted = unquote(encrypted)
            tokens = _decrypt_tokens(decoded_encrypted)
            if tokens:
                st.session_state["cw_access_token"] = tokens["a"]
                st.session_state["cw_refresh_token"] = tokens.get("r", "")
                st.session_state["cw_expires_at"] = tokens.get("e", 0)
                return True
    except Exception as e:
        # st.context.cookies が利用できない場合（古いバージョンなど）
        st.warning(f"クッキー読み取りエラー: {e}")
    
    return False


def clear_tokens():
    """トークンをセッションとクッキーから削除（ログアウト）"""
    for key in ["cw_access_token", "cw_refresh_token", "cw_expires_at", 
                "cw_cookie_load_attempted", "cw_cookie_saved", "cw_encrypted_token"]:
        if key in st.session_state:
            del st.session_state[key]
    
    # JavaScriptでクッキーを削除（parent.document を使用）
    delete_script = f"""
    <script>
        try {{
            parent.document.cookie = "{COOKIE_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax; Secure";
            console.log("Cookie deleted successfully");
        }} catch (e) {{
            console.error("Failed to delete cookie:", e);
            document.cookie = "{COOKIE_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax; Secure";
        }}
    </script>
    """
    st.components.v1.html(delete_script, height=0, width=0)


# ====== API関連 ======

def _authz_header() -> dict:
    """Bearer認証ヘッダー"""
    return {"authorization": f"Bearer {st.session_state['cw_access_token']}"}


def _refresh_if_needed():
    """トークンの自動更新（期限60秒前に更新）"""
    if "cw_expires_at" not in st.session_state:
        return
    if time.time() < st.session_state["cw_expires_at"] - 60:
        return
    if "cw_refresh_token" not in st.session_state:
        return

    basic = _b64(f"{CLIENT_ID}:{CLIENT_SECRET}")
    r = requests.post(
        TOKEN_URL,
        headers={"authorization": f"Basic {basic}"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": st.session_state["cw_refresh_token"],
            "scope": SCOPES,
        },
        timeout=30,
    )
    r.raise_for_status()
    tok = r.json()
    st.session_state["cw_access_token"] = tok["access_token"]
    st.session_state["cw_expires_at"] = time.time() + int(tok.get("expires_in", 1800))
    
    # 更新後クッキーにも保存
    save_tokens_to_cookie()


def is_logged_in() -> bool:
    """
    ChatWorkにログイン済みかどうか
    クッキーからの自動復元も試みる
    """
    # まずクッキーから復元を試みる
    load_tokens_from_cookie()
    return "cw_access_token" in st.session_state


def show_login_button(return_page: str = None, return_date: str = None):
    """
    ChatWorkログインボタンを表示
    
    Args:
        return_page: 認証後に戻るページ名
        return_date: 認証後に戻る日付パラメータ
    """
    verifier = _pkce_verifier()
    challenge = _pkce_challenge(verifier)

    # stateに全情報を含める（セッションに依存しない）
    state_data = {
        "v": verifier,  # PKCE verifier
        "p": return_page or "",  # page
        "d": return_date or "",  # date
        "t": int(time.time())  # timestamp（オプション：期限チェック用）
    }
    state = _sign_state(state_data)

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    login_url = f"{AUTH_URL}?{urlencode(params)}"
    
    # 同じタブで遷移するためにHTMLリンクを使用
    # st.link_button はデフォルトで新しいタブを開くため
    button_html = f"""
        <style>
        .cw-login-btn {{
            display: inline-block;
            padding: 0.5rem 1rem;
            background-color: #ff4b4b;
            color: white !important;
            text-decoration: none;
            border-radius: 0.5rem;
            font-weight: 600;
            text-align: center;
        }}
        .cw-login-btn:hover {{
            background-color: #ff3333;
            color: white !important;
        }}
        </style>
        <a href="{login_url}" target="_self" class="cw-login-btn">ChatWorkでログイン</a>
    """
    st.markdown(button_html, unsafe_allow_html=True)


def handle_oauth_callback() -> dict | None:
    """
    OAuthコールバック処理（app.pyレベルで呼び出し）
    
    セッションに依存せず、stateパラメータから全情報を取得
    
    Returns: 
        成功時: {"page": "result", "date": "20260120"} のような辞書
        処理なし/エラー: None
    """
    qp = st.query_params
    code = qp.get("code")
    state = qp.get("state")
    error = qp.get("error")

    if error:
        st.error(f"OAuth error: {error}")
        return None

    if not code:
        return None
    
    if "cw_access_token" in st.session_state:
        # 既にログイン済み、stateからページ情報を取り出してリダイレクト
        if state:
            state_data = _verify_and_decode_state(state)
            if state_data:
                return {"page": state_data.get("p", ""), "date": state_data.get("d", "")}
        return {"page": "", "date": ""}

    # stateの検証とデータ取り出し
    if not state:
        st.error("stateパラメータがありません。最初からやり直してください。")
        return None
    
    state_data = _verify_and_decode_state(state)
    if state_data is None:
        st.error("stateの署名検証に失敗しました。最初からやり直してください。")
        return None
    
    # 期限チェック（10分以内）
    created_at = state_data.get("t", 0)
    if time.time() - created_at > 600:
        st.error("認証の有効期限が切れました（10分）。最初からやり直してください。")
        return None
    
    verifier = state_data.get("v", "")
    return_info = {"page": state_data.get("p", ""), "date": state_data.get("d", "")}

    # トークン交換
    basic = _b64(f"{CLIENT_ID}:{CLIENT_SECRET}")
    try:
        r = requests.post(
            TOKEN_URL,
            headers={"authorization": f"Basic {basic}"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            },
            timeout=30,
        )
        r.raise_for_status()
        tok = r.json()
        st.session_state["cw_access_token"] = tok["access_token"]
        st.session_state["cw_refresh_token"] = tok.get("refresh_token")
        st.session_state["cw_expires_at"] = time.time() + int(tok.get("expires_in", 1800))
        
        # クッキーに保存
        save_tokens_to_cookie()
        
        return return_info
    except requests.exceptions.HTTPError as e:
        st.error(f"トークン取得エラー: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        st.error(f"トークン取得エラー: {e}")
        return None


def is_room_member() -> bool:
    """指定ルームのメンバーかどうか確認"""
    _refresh_if_needed()
    rooms = requests.get(f"{API_BASE}/rooms", headers=_authz_header(), timeout=30)
    rooms.raise_for_status()
    rooms_json = rooms.json()
    return any(int(r.get("room_id")) == TARGET_ROOM_ID for r in rooms_json)


def get_my_profile() -> dict | None:
    """
    ログインユーザーのプロフィール情報を取得
    
    Returns:
        成功時: {"account_id": 123, "name": "表示名", ...}
        失敗時: None
    """
    _refresh_if_needed()
    try:
        r = requests.get(f"{API_BASE}/me", headers=_authz_header(), timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def post_files_to_room(files_data: list[tuple[str, bytes, str]], message: str = "") -> bool:
    """
    複数ファイルをChatWorkルームに投稿
    
    Args:
        files_data: [(ファイル名, データ, MIMEタイプ), ...]のリスト
        message: 最初のファイルに付けるメッセージ
    
    Returns:
        bool: 成功したかどうか
    """
    _refresh_if_needed()
    
    for i, (filename, data, mime) in enumerate(files_data):
        if len(data) > 5 * 1024 * 1024:
            st.error(f"{filename}: 5MBを超えています。")
            return False
        
        files = {"file": (filename, data, mime)}
        form = {"message": message if i == 0 and message else " "}
        
        r = requests.post(
            f"{API_BASE}/rooms/{TARGET_ROOM_ID}/files",
            headers=_authz_header(),
            files=files,
            data=form,
            timeout=60,
        )
        r.raise_for_status()
    
    return True


def show_logout_button():
    """
    ログアウトボタンを表示（デバッグ・管理用）
    """
    if st.button("ChatWorkからログアウト"):
        clear_tokens()
        st.success("ログアウトしました。")
        st.rerun()



