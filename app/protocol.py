# ==========================================
# DashScope Realtime 事件构造：纯函数，无 IO，便于单元测试
# ==========================================
from app.config import TRANSCRIPTION_MODEL


# ==========================================
# 构造 session.update 事件
# ==========================================
def build_session_update(instructions: str, modalities: list, voice: str = "") -> dict:
    """
    构造会话配置事件（system prompt、输出模态、服务端 VAD、输入转写）。
    Args:
        instructions: system prompt 内容 (str)
        modalities: 输出模态列表，如 ["text", "audio"] (list)
        voice: 发音人名称，空串表示使用默认 (str)
    Returns:
        dict: session.update 事件 JSON
    """
    session = {
        "modalities": modalities,
        "instructions": instructions,
        "input_audio_format": "pcm",
        "output_audio_format": "pcm",
        "input_audio_transcription": {"model": TRANSCRIPTION_MODEL},
        "turn_detection": {"type": "server_vad"},
    }
    if voice:
        session["voice"] = voice
    return {"type": "session.update", "session": session}


# ==========================================
# 构造音频追加事件
# ==========================================
def build_audio_append(b64_audio: str) -> dict:
    """
    构造上行音频块事件。
    Args:
        b64_audio: base64 编码的 PCM 音频 (str)
    Returns:
        dict: input_audio_buffer.append 事件 JSON
    """
    return {"type": "input_audio_buffer.append", "audio": b64_audio}


# ==========================================
# 构造单条历史消息注入事件
# ==========================================
def build_history_item(role: str, text: str) -> dict:
    """
    构造一条历史消息的注入事件（用于恢复会话上下文）。
    Args:
        role: user 或 assistant (str)
        text: 消息文本 (str)
    Returns:
        dict: conversation.item.create 事件 JSON
    """
    # 协议要求：助手消息内容类型为 output_text，用户消息为 input_text
    content_type = "output_text" if role == "assistant" else "input_text"
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": role,
            "content": [{"type": content_type, "text": text}],
        },
    }


# ==========================================
# 构造完整历史注入事件序列
# ==========================================
def build_history_events(transcript: list) -> list:
    """
    将存档的对话记录转换为注入事件序列。
    Args:
        transcript: 对话记录列表，每项含 role 与 text (list)
    Returns:
        list: conversation.item.create 事件列表
    """
    return [build_history_item(item["role"], item["text"]) for item in transcript]
