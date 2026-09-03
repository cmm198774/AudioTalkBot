# ==========================================
# pytest 公共 fixture：存储路径隔离
# ==========================================
import pytest

from app import storage


# ==========================================
# 所有测试自动使用临时数据目录，避免污染真实数据
# ==========================================
@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    """
    把 storage 模块的文件路径指向 pytest 临时目录。
    Args:
        tmp_path: pytest 内置临时目录 (Path)
        monkeypatch: pytest monkeypatch fixture
    """
    monkeypatch.setattr(storage, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(storage, "PRESETS_FILE", tmp_path / "presets.json")
