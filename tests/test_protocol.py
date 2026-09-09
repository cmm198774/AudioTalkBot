# ==========================================
# 协议模块测试：DashScope 事件 JSON 构造
# ==========================================
from app.protocol import (
    build_audio_append,
    build_history_events,
    build_response_create,
    build_session_update,
    build_tool_output,
)


# ==========================================
# 测试 session.update 包含全部必要字段
# ==========================================
def test_build_session_update_full():
    event = build_session_update("你是法语老师", ["text", "audio"], voice="Cherry")
    assert event["type"] == "session.update"
    session = event["session"]
    assert session["instructions"] == "你是法语老师"
    assert session["modalities"] == ["text", "audio"]
    assert session["voice"] == "Cherry"
    assert session["input_audio_format"] == "pcm"
    assert session["output_audio_format"] == "pcm"
    assert session["turn_detection"] == {"type": "server_vad"}
    assert "model" in session["input_audio_transcription"]


# ==========================================
# 测试 voice 为空时省略该字段
# ==========================================
def test_build_session_update_no_voice():
    event = build_session_update("提示词", ["audio"], voice="")
    assert "voice" not in event["session"]


# ==========================================
# 测试传入工具定义时 session.update 携带 tools
# ==========================================
def test_build_session_update_with_tools():
    tools = [{"type": "function", "function": {"name": "write_to_board"}}]
    event = build_session_update("提示词", ["text", "audio"], tools=tools)
    assert event["session"]["tools"] == tools


# ==========================================
# 测试未传工具时省略 tools 字段
# ==========================================
def test_build_session_update_without_tools():
    event = build_session_update("提示词", ["text", "audio"])
    assert "tools" not in event["session"]


# ==========================================
# 测试工具结果回传事件
# ==========================================
def test_build_tool_output():
    event = build_tool_output("call-1", '{"status": "ok"}')
    assert event == {
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": '{"status": "ok"}',
        },
    }


# ==========================================
# 测试触发模型继续回复的事件
# ==========================================
def test_build_response_create():
    assert build_response_create() == {"type": "response.create"}


# ==========================================
# 测试音频追加事件
# ==========================================
def test_build_audio_append():
    event = build_audio_append("QUJD")
    assert event == {"type": "input_audio_buffer.append", "audio": "QUJD"}


# ==========================================
# 测试历史注入事件序列：打包为单条 user 笔记
# （DashScope 的 assistant output_text 条目不进模型上下文，
#   只有 user input_text 真正被记住，见 probe_history_variants）
# ==========================================
def test_build_history_events():
    transcript = [
        {"role": "user", "text": "你好"},
        {"role": "assistant", "text": "Bonjour"},
    ]
    events = build_history_events(transcript)
    assert len(events) == 1
    item = events[0]["item"]
    assert events[0]["type"] == "conversation.item.create"
    assert item["type"] == "message"
    assert item["role"] == "user"
    assert item["content"][0]["type"] == "input_text"
    note = item["content"][0]["text"]
    # 笔记包含恢复说明与带角色前缀的完整对话
    assert "[系统提示]" in note
    assert "user: 你好" in note
    assert "assistant: Bonjour" in note


# ==========================================
# 测试空历史返回空列表
# ==========================================
def test_build_history_events_empty():
    assert build_history_events([]) == []
