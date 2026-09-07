# ==========================================
# 用户认证：密码哈希、用户表、session 管理
# ==========================================
import hashlib
import json
import secrets
import threading
from pathlib import Path

from app.config import USERS_FILE

# 全局写锁，防止并发写入用户表
_LOCK = threading.Lock()

# 内存 session 表：session_id → username
# 服务端重启后 session 丢失，用户需重新登录（安全考虑）
_SESSIONS: dict[str, str] = {}

# cookie 名
SESSION_COOKIE_NAME = "session_id"


# ==========================================
# 密码哈希：随机 salt + SHA-256
# ==========================================
def hash_password(password: str) -> str:
    """
    用随机 salt 哈希密码，返回 salt:hash 格式。
    Args:
        password: 明文密码 (str)
    Returns:
        str: salt:hash 格式字符串
    """
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{h}"


# ==========================================
# 验证密码
# ==========================================
def verify_password(password: str, stored: str) -> bool:
    """
    验证密码是否匹配。
    Args:
        password: 明文密码 (str)
        stored: 存储的 salt:hash 字符串 (str)
    Returns:
        bool: 是否匹配
    """
    if ":" not in stored:
        return False
    salt, expected = stored.split(":", 1)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return h == expected


# ==========================================
# 用户表：读取
# ==========================================
def _load_users() -> list:
    """
    读取用户表。
    Returns:
        list: 用户记录列表
    """
    if not USERS_FILE.exists():
        return []
    data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return data.get("users", [])


# ==========================================
# 用户表：写入
# ==========================================
def _save_users(users: list) -> None:
    """
    写入用户表。
    Args:
        users: 用户记录列表 (list)
    """
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = USERS_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"users": users}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(USERS_FILE)


# ==========================================
# 注册：创建新用户
# ==========================================
def register(username: str, password: str) -> dict | None:
    """
    注册新用户。
    Args:
        username: 用户名 (str)
        password: 明文密码 (str)
    Returns:
        dict | None: 新建的用户记录，用户名已存在返回 None
    """
    if not username or not password:
        return None
    with _LOCK:
        users = _load_users()
        for u in users:
            if u["username"] == username:
                return None
        user = {
            "username": username,
            "password_hash": hash_password(password),
            "created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        }
        users.append(user)
        _save_users(users)
    return user


# ==========================================
# 登录：验证密码，创建 session
# ==========================================
def login(username: str, password: str) -> str | None:
    """
    登录验证，成功返回 session_id。
    Args:
        username: 用户名 (str)
        password: 明文密码 (str)
    Returns:
        str | None: session_id，失败返回 None
    """
    users = _load_users()
    for u in users:
        if u["username"] == username and verify_password(password, u["password_hash"]):
            session_id = secrets.token_urlsafe(32)
            _SESSIONS[session_id] = username
            return session_id
    return None


# ==========================================
# 登出：销毁 session
# ==========================================
def logout(session_id: str) -> None:
    """
    登出，销毁 session。
    Args:
        session_id: session_id (str)
    """
    _SESSIONS.pop(session_id, None)


# ==========================================
# 验证 session，返回 username
# ==========================================
def get_user_by_session(session_id: str) -> str | None:
    """
    根据 session_id 返回 username。
    Args:
        session_id: session_id (str)
    Returns:
        str | None: username，无效 session 返回 None
    """
    return _SESSIONS.get(session_id)


# ==========================================
# 获取用户凭证（api_key, base_url）
# ==========================================
def get_user_credentials(username: str) -> dict:
    """
    读取用户凭证。
    Args:
        username: 用户名 (str)
    Returns:
        dict: {"api_key": str, "base_url": str}，缺失字段返回空串
    """
    from app.config import get_user_data_dir
    cred_file = get_user_data_dir(username) / "credentials.json"
    if not cred_file.exists():
        return {"api_key": "", "base_url": ""}
    data = json.loads(cred_file.read_text(encoding="utf-8"))
    return {
        "api_key": data.get("api_key", ""),
        "base_url": data.get("base_url", ""),
    }


# ==========================================
# 保存用户凭证
# ==========================================
def save_user_credentials(username: str, api_key: str, base_url: str) -> None:
    """
    保存用户凭证（简单加密）。
    Args:
        username: 用户名 (str)
        api_key: API key (str)
        base_url: base URL (str)
    """
    from app.config import get_user_data_dir
    cred_file = get_user_data_dir(username) / "credentials.json"
    cred_file.parent.mkdir(parents=True, exist_ok=True)
    # 简单加密：用用户名做 key 的 XOR + base64
    # 生产环境建议用 Fernet 或类似方案
    encrypted_key = _simple_encrypt(api_key, username) if api_key else ""
    encrypted_url = _simple_encrypt(base_url, username) if base_url else ""
    cred_file.write_text(
        json.dumps({"api_key": encrypted_key, "base_url": encrypted_url}, ensure_ascii=False),
        encoding="utf-8",
    )


# ==========================================
# 解密用户凭证
# ==========================================
def decrypt_user_credentials(username: str) -> dict:
    """
    解密并返回用户凭证。
    Args:
        username: 用户名 (str)
    Returns:
        dict: {"api_key": str, "base_url": str}
    """
    creds = get_user_credentials(username)
    return {
        "api_key": _simple_decrypt(creds["api_key"], username) if creds["api_key"] else "",
        "base_url": _simple_decrypt(creds["base_url"], username) if creds["base_url"] else "",
    }


# ==========================================
# 简单加密：XOR + base64
# ==========================================
def _simple_encrypt(text: str, key: str) -> str:
    """
    XOR 加密 + base64。
    Args:
        text: 明文 (str)
        key: 密钥（用户名）(str)
    Returns:
        str: base64 编码的密文
    """
    import base64
    key_bytes = key.encode()
    text_bytes = text.encode()
    encrypted = bytes(
        text_bytes[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(text_bytes))
    )
    return base64.b64encode(encrypted).decode()


# ==========================================
# 简单解密：base64 + XOR
# ==========================================
def _simple_decrypt(cipher: str, key: str) -> str:
    """
    base64 解码 + XOR 解密。
    Args:
        cipher: base64 密文 (str)
        key: 密钥（用户名）(str)
    Returns:
        str: 明文
    """
    import base64
    key_bytes = key.encode()
    cipher_bytes = base64.b64decode(cipher)
    decrypted = bytes(
        cipher_bytes[i] ^ key_bytes[i % len(key_bytes)] for i in range(len(cipher_bytes))
    )
    return decrypted.decode()
