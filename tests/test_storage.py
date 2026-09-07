# ==========================================
# 存储模块测试：按用户隔离的会话与预设 CRUD 和持久化
# ==========================================
import json

from app import storage

# 测试用的用户名
TEST_USER = "testuser"


# ==========================================
# 测试创建会话返回完整字段与默认值
# ==========================================
def test_create_session_defaults():
    session = storage.create_session(TEST_USER, "你是一个测试助手", "audio_text")
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
    s1 = storage.create_session(TEST_USER, "", "audio_text")
    s2 = storage.create_session(TEST_USER, "", "audio_text")
    storage.update_session(TEST_USER, s1["id"], title="改过的标题")
    sessions = storage.list_sessions(TEST_USER)
    assert sessions[0]["id"] == s1["id"]
    assert sessions[1]["id"] == s2["id"]


# ==========================================
# 测试更新会话字段；未知 id 返回 None
# ==========================================
def test_update_session():
    session = storage.create_session(TEST_USER, "旧 prompt", "audio_text")
    updated = storage.update_session(
        TEST_USER, session["id"], title="新标题", system_prompt="新 prompt", output_mode="text"
    )
    assert updated["title"] == "新标题"
    assert updated["system_prompt"] == "新 prompt"
    assert updated["output_mode"] == "text"
    assert storage.update_session(TEST_USER, "不存在", title="x") is None


# ==========================================
# 测试更新时拒绝非法字段
# ==========================================
def test_update_session_rejects_unknown_field():
    session = storage.create_session(TEST_USER, "", "audio_text")
    updated = storage.update_session(TEST_USER, session["id"], transcript=[{"role": "user"}])
    assert updated["transcript"] == []


# ==========================================
# 测试删除会话
# ==========================================
def test_delete_session():
    session = storage.create_session(TEST_USER, "", "audio_text")
    assert storage.delete_session(TEST_USER, session["id"]) is True
    assert storage.get_session(TEST_USER, session["id"]) is None
    assert storage.delete_session(TEST_USER, session["id"]) is False


# ==========================================
# 测试追加对话记录并更新时间戳
# ==========================================
def test_append_transcript():
    session = storage.create_session(TEST_USER, "", "audio_text")
    storage.append_transcript(TEST_USER, session["id"], "user", "你好")
    storage.append_transcript(TEST_USER, session["id"], "assistant", "Bonjour !")
    loaded = storage.get_session(TEST_USER, session["id"])
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
    session = storage.create_session(TEST_USER, "落盘测试", "audio_text")
    from app.config import get_user_data_dir
    raw = json.loads((get_user_data_dir(TEST_USER) / "sessions.json").read_text(encoding="utf-8"))
    assert raw["sessions"][0]["id"] == session["id"]


# ==========================================
# 测试用户隔离：不同用户的会话互不可见
# ==========================================
def test_user_isolation():
    storage.create_session("alice", "Alice 的会话", "audio_text")
    storage.create_session("bob", "Bob 的会话", "audio_text")
    alice_sessions = storage.list_sessions("alice")
    bob_sessions = storage.list_sessions("bob")
    assert len(alice_sessions) == 1
    assert len(bob_sessions) == 1
    assert alice_sessions[0]["system_prompt"] == "Alice 的会话"
    assert bob_sessions[0]["system_prompt"] == "Bob 的会话"


# ==========================================
# 测试预设的创建、列表、删除
# ==========================================
def test_presets_crud():
    preset = storage.create_preset(TEST_USER, "法语老师", "你是一位耐心的法语老师")
    assert preset["name"] == "法语老师"
    assert preset["prompt"] == "你是一位耐心的法语老师"
    assert len(storage.list_presets(TEST_USER)) == 1
    assert storage.delete_preset(TEST_USER, preset["id"]) is True
    assert storage.list_presets(TEST_USER) == []
    assert storage.delete_preset(TEST_USER, preset["id"]) is False


# ==========================================
# 测试同名预设重复保存时覆盖而非追加
# ==========================================
def test_create_preset_same_name_overwrites():
    first = storage.create_preset(TEST_USER, "心理咨询师", "旧版内容")
    second = storage.create_preset(TEST_USER, "心理咨询师", "新版内容")
    presets = storage.list_presets(TEST_USER)
    assert len(presets) == 1
    assert second["id"] == first["id"]
    assert presets[0]["prompt"] == "新版内容"
