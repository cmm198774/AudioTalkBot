# ==========================================
# 协议模块测试：DashScope 事件 JSON 构造
# ==========================================
from app.protocol import (
    build_audio_append,
    build_history_events,
    build_session_update,
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
# 测试音频追加事件
# ==========================================
def test_build_audio_append():
    event = build_audio_append("QUJD")
    assert event == {"type": "input_audio_buffer.append", "audio": "QUJD"}


# ==========================================
# 测试历史注入事件序列
# ==========================================
def test_build_history_events():
    transcript = [
        {"role": "user", "text": "你好"},
        {"role": "assistant", "text": "Bonjour"},
    ]
    events = build_history_events(transcript)
    assert len(events) == 2
    first = events[0]
    assert first["type"] == "conversation.item.create"
    assert first["item"]["type"] == "message"
    assert first["item"]["role"] == "user"
    assert first["item"]["content"] == [{"type": "input_text", "text": "你好"}]
    assert events[1]["item"]["role"] == "assistant"


# ==========================================
# 测试空历史返回空列表
# ==========================================
def test_build_history_events_empty():
    assert build_history_events([]) == []
