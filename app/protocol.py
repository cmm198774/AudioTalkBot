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


# 历史注入笔记的开头说明：告诉模型这是恢复的对话记录
_HISTORY_NOTE_HEADER = (
    "[系统提示] 你正在恢复一段此前被中断的对话。"
    "下面是之前的对话记录（user=用户说的话，assistant=你说过的话，"
    "以[对话摘要]开头的是更早对话的总结）。"
    "请记住这些内容，并基于它们自然地继续对话：\n"
)


# ==========================================
# 构造完整历史注入事件序列
# ==========================================
def build_history_events(transcript: list) -> list:
    """
    将存档的对话记录打包为单条 user 角色笔记注入。
    DashScope 实测行为：assistant 角色条目仅接受 output_text 类型，
    且该类型条目虽被 API 接受却不会进入模型上下文（模型完全看不到）；
    只有 user 角色的 input_text 条目真正被模型记住。
    因此把整段历史（含摘要）格式化成一条 user 笔记，确保恢复可见。
    Args:
        transcript: 对话记录列表，每项含 role 与 text (list)
    Returns:
        list: conversation.item.create 事件列表（至多一条）
    """
    if not transcript:
        return []
    lines = [
        f"{item.get('role', 'user')}: {item.get('text', '')}"
        for item in transcript
    ]
    note = _HISTORY_NOTE_HEADER + "\n".join(lines)
    return [{
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": note}],
        },
    }]
