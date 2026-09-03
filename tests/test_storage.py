# ==========================================
# 存储模块测试：会话与预设的 CRUD 和持久化
# ==========================================
import json

from app import storage


# ==========================================
# 测试创建会话返回完整字段与默认值
# ==========================================
def test_create_session_defaults():
    session = storage.create_session("你是一个测试助手", "audio_text")
    assert session["title"] == "新对话"
    assert session["system_prompt"] == "你是一个测试助手"
    assert session["output_mode"] == "audio_text"
    assert session["transcript"] == []
    assert session["id"]
    assert session["created_at"]


# ==========================================
# 测试列表按更新时间倒序
# ==========================================
def test_list_sessions_sorted_by_updated_at():
    s1 = storage.create_session("", "audio_text")
    s2 = storage.create_session("", "audio_text")
    storage.update_session(s1["id"], title="改过的标题")
    sessions = storage.list_sessions()
    assert sessions[0]["id"] == s1["id"]
    assert sessions[1]["id"] == s2["id"]


# ==========================================
# 测试更新会话字段；未知 id 返回 None
# ==========================================
def test_update_session():
    session = storage.create_session("旧 prompt", "audio_text")
    updated = storage.update_session(
        session["id"], title="新标题", system_prompt="新 prompt", output_mode="text"
    )
    assert updated["title"] == "新标题"
    assert updated["system_prompt"] == "新 prompt"
    assert updated["output_mode"] == "text"
    assert storage.update_session("不存在", title="x") is None


# ==========================================
# 测试更新时拒绝非法字段
# ==========================================
def test_update_session_rejects_unknown_field():
    session = storage.create_session("", "audio_text")
    updated = storage.update_session(session["id"], transcript=[{"role": "user"}])
    assert updated["transcript"] == []


# ==========================================
# 测试删除会话
# ==========================================
def test_delete_session():
    session = storage.create_session("", "audio_text")
    assert storage.delete_session(session["id"]) is True
    assert storage.get_session(session["id"]) is None
    assert storage.delete_session(session["id"]) is False


# ==========================================
# 测试追加对话记录并更新时间戳
# ==========================================
def test_append_transcript():
    session = storage.create_session("", "audio_text")
    storage.append_transcript(session["id"], "user", "你好")
    storage.append_transcript(session["id"], "assistant", "Bonjour !")
    loaded = storage.get_session(session["id"])
    assert loaded["transcript"][0] == {
        "role": "user",
        "text": "你好",
        "ts": loaded["transcript"][0]["ts"],
    }
    assert loaded["transcript"][1]["text"] == "Bonjour !"
    assert len(loaded["transcript"]) == 2


# ==========================================
# 测试数据真实落盘
# ==========================================
def test_sessions_persist_to_disk(tmp_path):
    session = storage.create_session("落盘测试", "audio_text")
    raw = json.loads((tmp_path / "sessions.json").read_text(encoding="utf-8"))
    assert raw["sessions"][0]["id"] == session["id"]


# ==========================================
# 测试预设的创建、列表、删除
# ==========================================
def test_presets_crud():
    preset = storage.create_preset("法语老师", "你是一位耐心的法语老师")
    assert preset["name"] == "法语老师"
    assert preset["prompt"] == "你是一位耐心的法语老师"
    assert len(storage.list_presets()) == 1
    assert storage.delete_preset(preset["id"]) is True
    assert storage.list_presets() == []
    assert storage.delete_preset(preset["id"]) is False
