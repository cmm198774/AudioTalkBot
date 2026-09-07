# ==========================================
# 认证模块测试：密码哈希、用户表、session 管理、凭证加密
# ==========================================
import pytest

from app import auth


# ==========================================
# 测试密码哈希与验证
# ==========================================
def test_password_hash_and_verify():
    password = "my_secret_123"
    hashed = auth.hash_password(password)
    assert ":" in hashed
    assert auth.verify_password(password, hashed)
    assert not auth.verify_password("wrong_password", hashed)


# ==========================================
# 测试注册：正常创建
# ==========================================
def test_register_creates_user(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    user = auth.register("alice", "password123")
    assert user is not None
    assert user["username"] == "alice"
    assert ":" in user["password_hash"]


# ==========================================
# 测试注册：重复用户名返回 None
# ==========================================
def test_register_duplicate_username_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    auth.register("alice", "password123")
    duplicate = auth.register("alice", "another_password")
    assert duplicate is None


# ==========================================
# 测试注册：空用户名或密码返回 None
# ==========================================
def test_register_empty_credentials_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    assert auth.register("", "password") is None
    assert auth.register("alice", "") is None


# ==========================================
# 测试登录：成功返回 session_id
# ==========================================
def test_login_success(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "_SESSIONS", {})
    auth.register("alice", "password123")
    session_id = auth.login("alice", "password123")
    assert session_id is not None
    assert auth.get_user_by_session(session_id) == "alice"


# ==========================================
# 测试登录：错误密码返回 None
# ==========================================
def test_login_wrong_password_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "_SESSIONS", {})
    auth.register("alice", "password123")
    assert auth.login("alice", "wrong_password") is None


# ==========================================
# 测试登录：不存在的用户返回 None
# ==========================================
def test_login_nonexistent_user_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "_SESSIONS", {})
    assert auth.login("bob", "password") is None


# ==========================================
# 测试登出：session 被销毁
# ==========================================
def test_logout_invalidates_session(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "_SESSIONS", {})
    auth.register("alice", "password123")
    session_id = auth.login("alice", "password123")
    assert auth.get_user_by_session(session_id) == "alice"
    auth.logout(session_id)
    assert auth.get_user_by_session(session_id) is None


# ==========================================
# 测试凭证加密与解密
# ==========================================
def test_credential_encrypt_decrypt(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "get_user_data_dir", lambda u: tmp_path / u)
    auth.save_user_credentials("alice", "sk-test-123", "https://api.example.com")
    creds = auth.decrypt_user_credentials("alice")
    assert creds["api_key"] == "sk-test-123"
    assert creds["base_url"] == "https://api.example.com"


# ==========================================
# 测试凭证：空值处理
# ==========================================
def test_credential_empty_values(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "get_user_data_dir", lambda u: tmp_path / u)
    auth.save_user_credentials("alice", "", "")
    creds = auth.decrypt_user_credentials("alice")
    assert creds["api_key"] == ""
    assert creds["base_url"] == ""


# ==========================================
# 测试凭证：文件不存在时返回空
# ==========================================
def test_credential_file_not_exists(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "get_user_data_dir", lambda u: tmp_path / u)
    creds = auth.decrypt_user_credentials("nonexistent")
    assert creds["api_key"] == ""
    assert creds["base_url"] == ""
