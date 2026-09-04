# ==========================================
# DashScope Realtime 事件构造：纯函数，无 IO，便于单元测试
# ==========================================
from app.config import TRANSCRIPTION_MODEL


# ==========================================
# 构造 session.update 事件
# ==========================================
def build_session_update(instructions: str, modalities: list, voice: str = "",
                         tools: list = None) -> dict:
    """
    构造会话配置事件（system prompt、输出模态、服务端 VAD、输入转写、工具）。
    Args:
        instructions: system prompt 内容 (str)
        modalities: 输出模态列表，如 ["text", "audio"] (list)
        voice: 发音人名称，空串表示使用默认 (str)
        tools: 工具定义列表，缺省不启用工具调用 (list)
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
    if tools:
        session["tools"] = tools
    return {"type": "session.update", "session": session}


# ==========================================
# 构造工具结果回传事件
# ==========================================
def build_tool_output(call_id: str, output: str) -> dict:
    """
    构造 function_call_output 注入事件，把工具执行结果交还给模型。
    Args:
        call_id: 工具调用 ID，来自 function_call_arguments.done (str)
        output: 工具结果字符串 (str)
    Returns:
        dict: conversation.item.create 事件 JSON
    """
    return {
        "type": "conversation.item.create",
        "item": {"type": "function_call_output", "call_id": call_id, "output": output},
    }


# ==========================================
# 构造触发模型继续回复的事件
# ==========================================
def build_response_create() -> dict:
    """
    工具结果回传后触发模型继续生成（口头总结/下一段/再次调用工具）。
    Returns:
        dict: response.create 事件 JSON
    """
    return {"type": "response.create"}


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
