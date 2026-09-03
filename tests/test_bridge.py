# ==========================================
# 桥接模块测试：连接握手、事件分流、打断、转写持久化、
# [start]/[end] 段解析与黑板字符区间掐音
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
# 构造指定时长的假音频块（24kHz 16bit 单声道，内容全零）
# ==========================================
def pcm_b64(seconds: float, fill: str = "A") -> str:
    """
    生成给定秒数的 base64 假音频串，fill 用于区分不同块。
    Args:
        seconds: 音频时长（秒）(float)
        fill: base64 填充字符 (str)
    Returns:
        str: base64 字符串（长度为 4 的倍数）
    """
    return fill * int(seconds * 48000 * 4 / 3)


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
# 测试混合回合：段外字幕、段内黑板、黑板区间音频被丢弃
# 口头 8 字 + 板书 4 字，字符区间 [8, 12]；按 4 字/秒换算成
# 秒区间 [1.625, 3.375]（含 1.5 字容差）。
# 音频块：A[0,1) 转发，B[1,2.5) 丢弃，C[2.5,3.5) 丢弃，D[3.5,4.5) 转发
# ==========================================
async def test_mixed_turn_segments_and_audio_cut():
    chunk_a = pcm_b64(1.0, "A")
    chunk_b = pcm_b64(1.5, "B")
    chunk_c = pcm_b64(1.0, "C")
    chunk_d = pcm_b64(1.0, "D")
    fake_ws = FakeWebSocket([
        {"type": "response.created"},
        {"type": "response.audio_transcript.delta", "delta": "好，大家看黑板。[start]勾股定理"},
        {"type": "response.audio_transcript.delta", "delta": "[end]大家多练习。"},
        {"type": "response.audio.delta", "delta": chunk_a},
        {"type": "response.audio.delta", "delta": chunk_b},
        {"type": "response.audio.delta", "delta": chunk_c},
        {"type": "response.audio.delta", "delta": chunk_d},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()

    deltas = [m["delta"] for m in received if m["type"] == "transcript" and m["role"] == "assistant"]
    assert "".join(deltas) == "好，大家看黑板。大家多练习。"
    boards = [m for m in received if m["type"] == "board"]
    assert "".join(b["delta"] for b in boards) == "勾股定理"
    assert boards[0].get("new_segment") is True
    # 区间内音频 B、C 丢弃，区间外 A、D 转发
    audios = [m["data"] for m in received if m["type"] == "audio"]
    assert audios == [chunk_a, chunk_d]
    assert finals == [("assistant", "好，大家看黑板。[start]勾股定理[end]大家多练习。")]
    await bridge.close()


# ==========================================
# 测试标记跨 delta 切分不泄漏碎片到字幕
# ==========================================
async def test_marker_split_across_deltas():
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "看黑板。[st"},
        {"type": "response.audio_transcript.delta", "delta": "art]公式"},
        {"type": "response.audio_transcript.delta", "delta": "[e"},
        {"type": "response.audio_transcript.delta", "delta": "nd]继续。"},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
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
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "[start]一[end]讲。[start]二[end]"},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    boards = [m for m in received if m["type"] == "board"]
    assert [b["delta"] for b in boards] == ["一", "二"]
    assert all(b.get("new_segment") is True for b in boards)
    await bridge.close()


# ==========================================
# 测试未闭合 [end]：开场白之后的音频全部丢弃（黑板读到完）
# 开场白 6 字，区间起点 (6-1.5)/4 = 1.125 秒：
# A[0,1) 在开场白内转发，B[1,2)、C[2,3) 丢弃
# ==========================================
async def test_unclosed_end_discards_tail_audio():
    chunk_a = pcm_b64(1.0, "A")
    chunk_b = pcm_b64(1.0, "B")
    chunk_c = pcm_b64(1.0, "C")
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "大家看这里。[start]公式"},
        {"type": "response.audio.delta", "delta": chunk_a},
        {"type": "response.audio.delta", "delta": chunk_b},
        {"type": "response.audio.delta", "delta": chunk_c},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    audios = [m["data"] for m in received if m["type"] == "audio"]
    assert audios == [chunk_a]
    board = "".join(m["delta"] for m in received if m["type"] == "board")
    assert board == "公式"
    await bridge.close()


# ==========================================
# 测试回合结束时未决的标记碎片按字幕补发
# ==========================================
async def test_trailing_fragment_flushed_on_done():
    fake_ws = FakeWebSocket([
        {"type": "response.audio_transcript.delta", "delta": "你好[st"},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    deltas = [m["delta"] for m in received if m["type"] == "transcript" and m["role"] == "assistant"]
    assert "".join(deltas) == "你好[st"
    await bridge.close()


# ==========================================
# 测试普通回合（无标记）行为不变：字幕与音频全转发
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
    await bridge.close()


# ==========================================
# 测试段状态在下一回合复位：上一回合的黑板区间不影响新回合音频
# ==========================================
async def test_segment_state_resets_next_turn():
    chunk_a = pcm_b64(2.0, "A")
    fake_ws = FakeWebSocket([
        {"type": "response.created"},
        {"type": "response.audio_transcript.delta", "delta": "[start]公式[end]"},
        {"type": "response.done"},
        {"type": "response.created"},
        {"type": "response.audio_transcript.delta", "delta": "你好"},
        {"type": "response.audio.delta", "delta": chunk_a},
        {"type": "response.done"},
    ])
    urls, headers, received, finals = [], [], [], []
    bridge = make_bridge(fake_ws, urls, headers, received, finals)
    await bridge.connect("", "audio_text")
    await bridge.wait_recv_done()
    board = "".join(m["delta"] for m in received if m["type"] == "board")
    assert board == "公式"
    assert any(m["type"] == "transcript" and m["delta"] == "你好" for m in received)
    assert [m["data"] for m in received if m["type"] == "audio"] == [chunk_a]
    await bridge.close()
