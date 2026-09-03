# ==========================================
# 桥接模块测试：连接握手、事件分流、打断、转写持久化
# ==========================================
import json

from app.bridge import RealtimeBridge


# ==========================================
# 假 WebSocket：脚本化返回事件、记录发送内容
# ==========================================
class FakeWebSocket:
    def __init__(self, events: list, clock=None):
        self._events = [dict(e) for e in events]
        self._clock = clock
        self.sent = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self._events:
            raise StopAsyncIteration
        event = self._events.pop(0)
        # _at 为测试用时间戳：弹出前把假时钟拨到该时刻
        if self._clock is not None and "_at" in event:
            self._clock.now = event.pop("_at")
        return json.dumps(event, ensure_ascii=False)

    async def close(self) -> None:
        self.closed = True


# ==========================================
# 可手动推进的假时钟：窗口掐音测试用
# ==========================================
class FakeClock:
    def __init__(self):
        self.now = 0.0

    def advance(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


# ==========================================
# 创建桥接实例的测试工厂
# ==========================================
def make_bridge(fake_ws, url_holder, header_holder, received, finals, clock=None):
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
        clock=clock,
    )


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
# 测试混合回合：段外字幕、段内黑板、黑板窗口音频被丢弃
# 时间线：文本 0.1/0.2，音频 1.0/1.5（lead=0.9）
# 黑板窗口文本时间 [0.1, 0.2] → 音频时间 [1.0, 1.1] 被掐
# ==========================================
async def test_mixed_turn_segments_and_audio_window():
    clock = FakeClock()
    fake_ws = FakeWebSocket([
        {"type": "response.created", "_at": 0.0},
        {"type": "response.audio_transcript.delta", "delta": "好，大家看黑板。[start]勾股定理", "_at": 0.1},
        {"type": "response.audio_transcript.delta", "delta": "[end]大家多练习。", "_at": 0.2},
        {"type": "response.audio.delta", "delta": "QUJD", "_at": 1.0},
        {"type": "response.audio.delta", "delta": "QUJE", "_at": 1.5},
        {"type": "response.done", "_at": 3.0},
    ], clock=clock)
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals, clock=clock)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()

    deltas = [m["delta"] for m in received if m["type"] == "transcript" and m["role"] == "assistant"]
    assert "".join(deltas) == "好，大家看黑板。大家多练习。"
    boards = [m for m in received if m["type"] == "board"]
    assert "".join(b["delta"] for b in boards) == "勾股定理"
    assert boards[0].get("new_segment") is True
    # 窗口内音频 QUJD 丢弃，窗口外 QUJE 转发
    audios = [m["data"] for m in received if m["type"] == "audio"]
    assert audios == ["QUJE"]
    assert finals == [("assistant", "好，大家看黑板。[start]勾股定理[end]大家多练习。")]
    await bridge.close()


# ==========================================
# 测试标记跨 delta 切分不泄漏碎片到字幕
# ==========================================
async def test_marker_split_across_deltas():
    clock = FakeClock()
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "看黑板。[st", "_at": 0.1},
        {"type": "response.audio_transcript.delta", "delta": "art]公式", "_at": 0.2},
        {"type": "response.audio_transcript.delta", "delta": "[e", "_at": 0.3},
        {"type": "response.audio_transcript.delta", "delta": "nd]继续。", "_at": 0.4},
        {"type": "response.done", "_at": 1.0},
    ], clock=clock)
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals, clock=clock)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    deltas = [m["delta"] for m in received if m["type"] == "transcript" and m["role"] == "assistant"]
    assert "".join(deltas) == "看黑板。继续。"
    assert not any("[st" in d or "art]" in d for d in deltas)
    board = "".join(m["delta"] for m in received if m["type"] == "board")
    assert board == "公式"
    await bridge.close()


# ==========================================
# 测试多个黑板段各自带 new_segment 标记
# ==========================================
async def test_multiple_board_segments_flags():
    clock = FakeClock()
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "[start]一[end]讲。[start]二[end]", "_at": 0.1},
        {"type": "response.done", "_at": 1.0},
    ], clock=clock)
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals, clock=clock)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    boards = [m for m in received if m["type"] == "board"]
    assert [b["delta"] for b in boards] == ["一", "二"]
    assert all(b.get("new_segment") is True for b in boards)
    await bridge.close()


# ==========================================
# 测试未闭合 [end]：后续音频全部丢弃（黑板读到完）
# ==========================================
async def test_unclosed_end_discards_tail_audio():
    clock = FakeClock()
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "讲。[start]公式", "_at": 0.1},
        {"type": "response.audio.delta", "delta": "QUJD", "_at": 1.0},
        {"type": "response.audio.delta", "delta": "QUJE", "_at": 2.0},
        {"type": "response.done", "_at": 3.0},
    ], clock=clock)
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals, clock=clock)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    assert not any(m["type"] == "audio" for m in received)
    board = "".join(m["delta"] for m in received if m["type"] == "board")
    assert board == "公式"
    await bridge.close()


# ==========================================
# 测试回合结束时未决的标记碎片按字幕补发
# ==========================================
async def test_trailing_fragment_flushed_on_done():
    clock = FakeClock()
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "你好[st", "_at": 0.1},
        {"type": "response.done", "_at": 1.0},
    ], clock=clock)
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals, clock=clock)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    deltas = [m["delta"] for m in received if m["type"] == "transcript" and m["role"] == "assistant"]
    assert "".join(deltas) == "你好[st"
    await bridge.close()


# ==========================================
# 测试普通回合（无标记）行为不变：字幕与音频全转发
# ==========================================
async def test_normal_turn_unchanged():
    clock = FakeClock()
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "Bonjour", "_at": 0.1},
        {"type": "response.audio.delta", "delta": "QUJD", "_at": 1.0},
        {"type": "response.done", "_at": 2.0},
    ], clock=clock)
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals, clock=clock)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    deltas = [m["delta"] for m in received if m["type"] == "transcript" and m["role"] == "assistant"]
    assert deltas == ["Bonjour"]
    assert [m["data"] for m in received if m["type"] == "audio"] == ["QUJD"]
    assert not any(m["type"] == "board" for m in received)
    await bridge.close()


# ==========================================
# 测试段状态在下一回合复位
# ==========================================
async def test_segment_state_resets_next_turn():
    clock = FakeClock()
    fake_ws = FakeWebSocket([
        {"type": "response.created", "_at": 0.0},
        {"type": "response.audio_transcript.delta", "delta": "[start]公式[end]", "_at": 0.1},
        {"type": "response.done", "_at": 1.0},
        {"type": "response.created", "_at": 2.0},
        {"type": "response.audio_transcript.delta", "delta": "你好", "_at": 2.1},
        {"type": "response.audio.delta", "delta": "QUJD", "_at": 3.0},
        {"type": "response.done", "_at": 4.0},
    ], clock=clock)
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals, clock=clock)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    board = "".join(m["delta"] for m in received if m["type"] == "board")
    assert board == "公式"
    assert any(m["type"] == "transcript" and m["delta"] == "你好" for m in received)
    assert [m["data"] for m in received if m["type"] == "audio"] == ["QUJD"]
    await bridge.close()
