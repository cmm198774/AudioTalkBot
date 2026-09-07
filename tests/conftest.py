# ==========================================
# pytest 公共 fixture：存储路径隔离
# ==========================================
import pytest

from app import auth, config


# ==========================================
# 所有测试自动使用临时数据目录，避免污染真实数据
# ==========================================
@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    """
    把数据目录指向 pytest 临时目录。
    Args:
        tmp_path: pytest 内置临时目录 (Path)
        monkeypatch: pytest monkeypatch fixture
    """
    users_file = tmp_path / "users.json"
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "USERS_FILE", users_file)
    monkeypatch.setattr(auth, "USERS_FILE", users_file)
    monkeypatch.setattr(
        config, "get_user_data_dir", lambda username: tmp_path / "sessions" / username
    )
    # 清空内存 session 表
    auth._SESSIONS.clear()
