# ==========================================
# 桥接模块测试：连接握手、事件分流、打断、转写持久化、
# write_to_board 工具调用的黑板上屏与"说话→工具→续说"编排
# ==========================================
import json

from app.bridge import RealtimeBridge


# ==========================================
# 假 WebSocket：脚本化返回事件、记录发送内容
# ==========================================
class FakeWebSocket:
    def __init__(self, events: list):
        self._events = [dict(e) for e in events]
        self.sent = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self._events:
            raise StopAsyncIteration
        return json.dumps(self._events.pop(0), ensure_ascii=False)

    async def close(self) -> None:
        self.closed = True


# ==========================================
# 创建桥接实例的测试工厂
# ==========================================
def make_bridge(fake_ws, url_holder, header_holder, received, finals):
    async def ws_factory(url, headers):
        url_holder.append(url)
        header_holder.append(headers)
        return fake_ws

    async def send_to_client(msg):
        received.append(msg)

    async def on_final_transcript(role, text):
        finals.append((role, text))

    return RealtimeBridge(
        send_to_client=send_to_client,
        on_final_transcript=on_final_transcript,
        api_key="sk-test",
        ws_factory=ws_factory,
    )


# ==========================================
# 构造一个板书工具调用完成事件
# ==========================================
def board_call(call_id: str, content: str) -> dict:
    """
    构造 response.function_call_arguments.done 事件。
    Args:
        call_id: 工具调用 ID (str)
        content: 黑板内容 (str)
    Returns:
        dict: 事件字典
    """
    return {
        "type": "response.function_call_arguments.done",
        "call_id": call_id,
        "name": "write_to_board",
        "arguments": json.dumps({"content": content}, ensure_ascii=False),
    }


# ==========================================
# 测试连接时首先发送 session.update 且鉴权头正确
# ==========================================
async def test_connect_sends_session_update():
    fake_ws = FakeWebSocket([{"type": "session.created"}])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("你是法语老师", "audio_text", history=None)
    assert "Bearer sk-test" in headers[0]["Authorization"]
    assert "qwen-audio-3.0-realtime" in urls[0]
    first_sent = fake_ws.sent[0]
    assert first_sent["type"] == "session.update"
    assert first_sent["session"]["instructions"] == "你是法语老师"
    assert first_sent["session"]["modalities"] == ["text", "audio"]
    await bridge.close()


# ==========================================
# 测试 session.update 携带板书工具定义
# ==========================================
async def test_connect_includes_board_tool():
    fake_ws = FakeWebSocket([{"type": "session.created"}])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    tools = fake_ws.sent[0]["session"]["tools"]
    assert tools[0]["function"]["name"] == "write_to_board"
    await bridge.close()


# ==========================================
# 测试带历史连接时注入 conversation.item.create
# ==========================================
async def test_connect_injects_history():
    fake_ws = FakeWebSocket([{"type": "session.created"}])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    history = [{"role": "user", "text": "你好"}, {"role": "assistant", "text": "Bonjour"}]
    await bridge.connect("", "audio_text", history=history)
    types = [e["type"] for e in fake_ws.sent]
    assert types.count("conversation.item.create") == 2
    await bridge.close()


# ==========================================
# 测试回复音频转发并进入 speaking 状态
# ==========================================
async def test_audio_delta_forwarded():
    fake_ws = FakeWebSocket([
        {"type": "response.created"},
        {"type": "response.audio.delta", "delta": "QUJD"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    assert {"type": "state", "value": "thinking"} in received
    assert {"type": "state", "value": "speaking"} in received
    assert {"type": "audio", "data": "QUJD"} in received
    await bridge.close()


# ==========================================
# 测试字幕增量累积，response.done 时产出最终转写
# ==========================================
async def test_transcript_accumulates_and_finalizes():
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "Bon"},
        {"type": "response.audio_transcript.delta", "delta": "jour"},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    deltas = [m for m in received if m["type"] == "transcript" and m["role"] == "assistant"]
    assert [d["delta"] for d in deltas] == ["Bon", "jour"]
    assert finals == [("assistant", "Bonjour")]
    await bridge.close()


# ==========================================
# 测试用户开口打断：发出 interrupt 并切换 listening 状态
# ==========================================
async def test_speech_started_emits_interrupt():
    fake_ws = FakeWebSocket([
        {"type": "input_audio_buffer.speech_started"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    assert {"type": "interrupt"} in received
    assert {"type": "state", "value": "listening"} in received
    await bridge.close()


# ==========================================
# 测试用户语音转写完成事件
# ==========================================
async def test_user_transcription_completed():
    fake_ws = FakeWebSocket([
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "你好"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    user_msgs = [m for m in received if m["type"] == "transcript" and m["role"] == "user"]
    assert user_msgs[0]["delta"] == "你好"
    assert user_msgs[0]["final"] is True
    assert finals == [("user", "你好")]
    await bridge.close()


# ==========================================
# 测试错误事件转发为 error 消息
# ==========================================
async def test_error_event_forwarded():
    fake_ws = FakeWebSocket([
        {"type": "error", "error": {"message": "rate limited"}},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    errors = [m for m in received if m["type"] == "error"]
    assert errors[0]["message"] == "rate limited"
    await bridge.close()


# ==========================================
# 测试音频发送
# ==========================================
async def test_send_audio():
    fake_ws = FakeWebSocket([{"type": "session.created"}])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.send_audio("QUJD")
    assert {"type": "input_audio_buffer.append", "audio": "QUJD"} in fake_ws.sent
    await bridge.close()


# ==========================================
# 测试普通回合（无工具调用）：字幕与音频全转发，回合结束切 listening
# ==========================================
async def test_normal_turn_unchanged():
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "Bonjour"},
        {"type": "response.audio.delta", "delta": "QUJD"},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    deltas = [m["delta"] for m in received if m["type"] == "transcript" and m["role"] == "assistant"]
    assert deltas == ["Bonjour"]
    assert [m["data"] for m in received if m["type"] == "audio"] == ["QUJD"]
    assert not any(m["type"] == "board" for m in received)
    assert {"type": "state", "value": "listening"} in received
    assert finals == [("assistant", "Bonjour")]
    await bridge.close()


# ==========================================
# 测试工具调用：内容上黑板，回传结果并触发续说，
# 口头文本跨续说累积，最终回合结束才持久化
# ==========================================
async def test_tool_call_board_and_continuation():
    fake_ws = FakeWebSocket([
        # 第一轮：口头讲解 + 工具调用
        {"type": "response.created"},
        {"type": "response.audio_transcript.delta", "delta": "我写一下。"},
        board_call("call-1", "勾股定理"),
        {"type": "response.done"},
        # 第二轮：工具结果回传后的续说
        {"type": "response.created"},
        {"type": "response.audio_transcript.delta", "delta": "写好了。"},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()

    # 黑板收到工具内容，且标记为新段
    boards = [m for m in received if m["type"] == "board"]
    assert boards == [{"type": "board", "delta": "勾股定理", "new_segment": True}]

    # 工具结果回传 + 触发续说
    outputs = [e for e in fake_ws.sent
               if e["type"] == "conversation.item.create"
               and e["item"]["type"] == "function_call_output"]
    assert len(outputs) == 1
    assert outputs[0]["item"]["call_id"] == "call-1"
    assert any(e["type"] == "response.create" for e in fake_ws.sent)

    # 续说不创建新字幕气泡（new_response 仅一次）
    assert sum(1 for m in received if m["type"] == "new_response") == 1

    # 口头文本跨续说累积，回合结束才持久化
    assert finals == [("assistant", "我写一下。写好了。")]
    # 第一轮结束不切 listening，续说结束才切
    listening = [i for i, m in enumerate(received)
                 if m == {"type": "state", "value": "listening"}]
    assert len(listening) == 1
    await bridge.close()


# ==========================================
# 测试一个 response 内多次工具调用：各自上黑板、各自回传、只续说一次
# ==========================================
async def test_multiple_tool_calls_one_response():
    fake_ws = FakeWebSocket([
        {"type": "response.created"},
        board_call("call-1", "一"),
        board_call("call-2", "二"),
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()

    boards = [m for m in received if m["type"] == "board"]
    assert [b["delta"] for b in boards] == ["一", "二"]
    assert all(b.get("new_segment") is True for b in boards)

    outputs = [e for e in fake_ws.sent
               if e["type"] == "conversation.item.create"
               and e["item"]["type"] == "function_call_output"]
    assert [o["item"]["call_id"] for o in outputs] == ["call-1", "call-2"]
    # 只触发一次续说，且回合继续不切 listening
    assert sum(1 for e in fake_ws.sent if e["type"] == "response.create") == 1
    assert not any(m == {"type": "state", "value": "listening"} for m in received)
    await bridge.close()


# ==========================================
# 测试工具处理中被用户打断：只回传结果不续说，回合收尾
# ==========================================
async def test_interrupted_turn_sends_outputs_without_continuation():
    fake_ws = FakeWebSocket([
        {"type": "response.created"},
        board_call("call-1", "公式"),
        {"type": "input_audio_buffer.speech_started"},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()

    # 工具结果仍要回传，但不触发续说
    outputs = [e for e in fake_ws.sent
               if e["type"] == "conversation.item.create"
               and e["item"]["type"] == "function_call_output"]
    assert len(outputs) == 1
    assert not any(e["type"] == "response.create" for e in fake_ws.sent)
    # 回合收尾：切 listening（无口头文本则不持久化）
    assert {"type": "state", "value": "listening"} in received
    assert finals == []
    await bridge.close()


# ==========================================
# 测试未知工具调用：不上黑板但结果仍回传
# ==========================================
async def test_unknown_tool_call_no_board():
    fake_ws = FakeWebSocket([
        {"type": "response.created"},
        {
            "type": "response.function_call_arguments.done",
            "call_id": "call-x",
            "name": "some_other_tool",
            "arguments": "{}",
        },
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    assert not any(m["type"] == "board" for m in received)
    outputs = [e for e in fake_ws.sent
               if e["type"] == "conversation.item.create"
               and e["item"]["type"] == "function_call_output"]
    assert [o["item"]["call_id"] for o in outputs] == ["call-x"]
    await bridge.close()


# ==========================================
# 测试工具参数非法 JSON：不上黑板、不崩溃，流程照常续说
# ==========================================
async def test_malformed_arguments_no_board():
    fake_ws = FakeWebSocket([
        {"type": "response.created"},
        {
            "type": "response.function_call_arguments.done",
            "call_id": "call-1",
            "name": "write_to_board",
            "arguments": "not-json",
        },
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    assert not any(m["type"] == "board" for m in received)
    assert any(e["type"] == "response.create" for e in fake_ws.sent)
    await bridge.close()
