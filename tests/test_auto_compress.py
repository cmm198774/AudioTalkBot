# ==========================================
# 自动压缩测试：bridge 自取消防御 + 后台会话内压缩全链路
# （超限 → compressing 通知 → 后台摘要（对话不中断）→
#   会话内注入摘要+删除旧条目 → auto_compressed；
#   会话内压缩不可用时回退到断线重连方案）
# ==========================================
import asyncio

from fastapi.testclient import TestClient

from app import main, storage
from app.bridge import RealtimeBridge
from app.context import SUMMARY_PREFIX

from test_bridge import FakeWebSocket


# ==========================================
# 测试在接收循环任务内部调用 close 不会自我取消递归
# （回归测试：修复前该场景触发 RecursionError）
# ==========================================
async def test_close_inside_recv_task_no_recursion():
    received = []
    holder = {}

    async def on_final(role, text):
        # 模拟 main.py 旧 bug 路径：回调运行在 recv 任务内，直接 close
        await holder["bridge"].close()

    fake_ws = FakeWebSocket([
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "你好"},
    ])

    async def ws_factory(url, headers):
        return fake_ws

    async def send_to_client(msg):
        received.append(msg)

    bridge = RealtimeBridge(
        send_to_client=send_to_client,
        on_final_transcript=on_final,
        api_key="sk-test",
        ws_factory=ws_factory,
    )
    holder["bridge"] = bridge
    await bridge.connect("", "audio_text")
    recv_task = bridge._recv_task
    # 修复前：RecursionError 被 _recv_loop 捕获并推送 error 消息
    await asyncio.wait_for(recv_task, timeout=2)
    assert fake_ws.closed is True
    assert not any(m["type"] == "error" for m in received)


# ==========================================
# 记录型假桥接：connect 后在独立任务中触发 live_turns 轮用户长发言，
# 模拟对话持续推进把上下文顶过阈值。
# 忠实还原真实 bridge 的任务拓扑：转写回调发生在独立任务中；
# finalized_count 与真实 bridge 一致，在回调前自增。
# ==========================================
class FakeBridge:
    def __init__(self, send_to_client, on_final_transcript=None, api_key="",
                 base_url="", ws_factory=None, live_turns=0, turn_chars=2000,
                 compress_result=True):
        self.send_to_client = send_to_client
        self.on_final_transcript = on_final_transcript
        self.connected = None
        self.closed = False
        self.final_task = None
        self.live_turns = live_turns
        self.turn_chars = turn_chars
        self.compress_result = compress_result
        self.compress_calls = []
        self._finalized = 0

    @property
    def finalized_count(self):
        return self._finalized

    async def connect(self, instructions, output_mode, history=None):
        self.connected = (instructions, output_mode, history)
        if self.on_final_transcript is not None and self.live_turns:
            self.final_task = asyncio.create_task(self._fire_turns())

    async def _fire_turns(self):
        for i in range(self.live_turns):
            self._finalized += 1
            await self.on_final_transcript("user", f"第{i}轮发言" + "长" * self.turn_chars)

    async def send_audio(self, b64_audio):
        pass

    async def update_session(self, instructions, output_mode):
        pass

    async def compress_in_session(self, summary_text, cutoff_marker,
                                  tail_transcript=None):
        self.compress_calls.append((summary_text, cutoff_marker, tail_transcript))
        return self.compress_result

    async def close(self):
        self.closed = True


# ==========================================
# 测试环境搭建：注册用户 + 凭证 + 会话 + 4 条短历史
# ==========================================
def setup_client(username: str) -> tuple:
    """
    创建测试客户端、注册登录、配好凭证并建一个带 4 条短历史的会话。
    Args:
        username: 测试用户名 (str)
    Returns:
        tuple: (TestClient, session_id)
    """
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"username": username, "password": "pass123"})
    client.put("/api/credentials", json={"api_key": "sk-test", "base_url": ""})
    sid = client.post("/api/sessions", json={}).json()["id"]
    for i in range(4):
        storage.append_transcript(username, sid, "user", f"旧历史{i}" + "短" * 100)
    return client, sid


# ==========================================
# 收集 WebSocket 消息直到压缩完成或出错
# 断开连接前快照各 bridge 的 closed 状态（stop/断连会关闭 bridge，
# 事后再看 closed 全是 True，无法区分压缩路径的行为）
# ==========================================
def run_until_compressed(client, sid: str, bridges: list = None) -> tuple:
    """
    启动对话并收消息，直到 auto_compressed / error / 超限。
    Args:
        client: TestClient (TestClient)
        sid: 会话 id (str)
        bridges: 需要快照 closed 状态的 bridge 列表 (list)
    Returns:
        tuple: (消息列表, closed 状态快照列表)
    """
    msgs = []
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        for _ in range(25):
            msg = ws.receive_json()
            msgs.append(msg)
            if msg["type"] in ("auto_compressed", "error"):
                break
        closed_snapshot = [b.closed for b in (bridges or [])]
        ws.send_json({"type": "stop"})
    return msgs, closed_snapshot


# ==========================================
# 测试后台会话内压缩：不断线、不重连、存储正确合并
# 数字账本：4 条历史（connect_len=4）+ 7 轮 live 发言（每轮约 2005 字符）
#   第 7 轮时总字符 ≈ 14447 > 阈值 12800 → 触发
#   快照 11 条，保留最近 6 条 → 摘要覆盖前 5 条
#   存储合并后 = 1 条摘要 + 6 条尾部 = 7 条
# ==========================================
def test_ws_background_compress_in_session(monkeypatch):
    languages = []

    async def fake_summarizer(old_transcript, language=None):
        languages.append(language)
        return f"summary of {len(old_transcript)} items"

    bridges = []
    turns_left = [7]  # 第一个 bridge 触发 7 轮，后续 bridge（回退场景）不触发

    def fake_bridge_factory(**kwargs):
        turns = turns_left[0]
        turns_left[0] = 0
        bridge = FakeBridge(live_turns=turns, **kwargs)
        bridges.append(bridge)
        return bridge

    monkeypatch.setattr(main, "SUMMARIZER", fake_summarizer)
    monkeypatch.setattr(main, "BRIDGE_CLASS", fake_bridge_factory)

    client, sid = setup_client("sessuser")
    msgs, closed_snapshot = run_until_compressed(client, sid, bridges)

    types = [m["type"] for m in msgs]
    assert types[-1] == "auto_compressed", f"消息序列异常: {types}"
    assert "compressing" in types
    assert types.index("compressing") < types.index("auto_compressed")
    assert "error" not in types

    # 摘要语言与对话语言一致（中文对话 → zh）
    assert languages == ["zh"]

    # 会话内压缩：连接不中断、无重连（只有一个 bridge 且压缩完成时未被关闭）
    assert len(bridges) == 1
    assert closed_snapshot == [False]
    assert len(bridges[0].compress_calls) == 1
    summary_text, cutoff, note_tail = bridges[0].compress_calls[0]
    assert summary_text == "summary of 5 items"
    # cutoff = finalized(7) - KEEP_RECENT(6) - 1（保守缓冲）= 0
    assert cutoff == 0
    # 快照 11 - 保留 6 = 边界 5 > connect_len(4) → 笔记全被摘要覆盖，无尾巴
    assert note_tail == []

    # 存储合并：摘要 + 快照尾部 6 条 = 7 条
    session = client.get(f"/api/sessions/{sid}").json()
    transcript = session["transcript"]
    assert len(transcript) == 7
    assert transcript[0]["text"].startswith(SUMMARY_PREFIX)
    assert "summary of 5 items" in transcript[0]["text"]

    # 压缩后的上下文用量已推送（7 条）
    assert any(m["type"] == "context_usage" and m["count"] == 7 for m in msgs)


# ==========================================
# 测试刚恢复的会话首轮触发压缩也走零中断路径
# 场景：30 条长历史（connect_len=30，全部在历史笔记里），
# 用户开口 1 轮即超阈值。此时 live 条目只有 1 条，笔记里
# 有一段（边界 25 到 30 共 5 条）未被摘要覆盖、也没有 live
# 条目对应 → 必须作为尾巴重注入，不能回退重连。
# ==========================================
def test_ws_resume_session_first_compress_in_session(monkeypatch):
    async def fake_summarizer(old_transcript, language=None):
        return f"summary of {len(old_transcript)} items"

    bridges = []

    def fake_bridge_factory(**kwargs):
        bridge = FakeBridge(live_turns=1, **kwargs)
        bridges.append(bridge)
        return bridge

    monkeypatch.setattr(main, "SUMMARIZER", fake_summarizer)
    monkeypatch.setattr(main, "BRIDGE_CLASS", fake_bridge_factory)

    client = TestClient(main.app)
    client.post("/api/auth/register", json={"username": "resumeuser", "password": "pass123"})
    client.put("/api/credentials", json={"api_key": "sk-test", "base_url": ""})
    sid = client.post("/api/sessions", json={}).json()["id"]
    for i in range(30):
        role = "user" if i % 2 == 0 else "assistant"
        storage.append_transcript("resumeuser", sid, role, f"第{i}条" + "长" * 600)

    msgs, closed_snapshot = run_until_compressed(client, sid, bridges)

    types = [m["type"] for m in msgs]
    assert types[-1] == "auto_compressed", f"消息序列异常: {types}"
    assert "error" not in types

    # 零中断：只有一个 bridge 且未被关闭（未走重连回退）
    assert len(bridges) == 1
    assert closed_snapshot == [False]
    summary_text, cutoff, note_tail = bridges[0].compress_calls[0]
    # 快照 31 条（30 历史 + 1 live），摘要覆盖前 25 条
    assert summary_text == "summary of 25 items"
    # cutoff = finalized(1) - 6 - 1 = -6 → 不删任何 live 条目
    assert cutoff == -6
    # 笔记尾巴 = transcript[25:30] 共 5 条，需重注入
    assert len(note_tail) == 5
    assert note_tail[0]["text"].startswith("第25条")

    # 存储合并：摘要 + 尾部 6 条 = 7 条
    session = client.get(f"/api/sessions/{sid}").json()
    transcript = session["transcript"]
    assert len(transcript) == 7
    assert transcript[0]["text"].startswith(SUMMARY_PREFIX)
    assert "summary of 25 items" in transcript[0]["text"]
    assert transcript[1]["text"].startswith("第25条")


# ==========================================
# 测试会话内压缩不可用时回退到断线重连方案
# ==========================================
def test_ws_compress_falls_back_to_reconnect(monkeypatch):
    async def fake_summarizer(old_transcript, language=None):
        return f"summary of {len(old_transcript)} items"

    bridges = []
    turns_left = [7]

    def fake_bridge_factory(**kwargs):
        turns = turns_left[0]
        turns_left[0] = 0
        bridge = FakeBridge(live_turns=turns, compress_result=False, **kwargs)
        bridges.append(bridge)
        return bridge

    monkeypatch.setattr(main, "SUMMARIZER", fake_summarizer)
    monkeypatch.setattr(main, "BRIDGE_CLASS", fake_bridge_factory)

    client, sid = setup_client("falluser")
    msgs, closed_snapshot = run_until_compressed(client, sid, bridges)

    types = [m["type"] for m in msgs]
    assert types[-1] == "auto_compressed", f"消息序列异常: {types}"
    assert "error" not in types

    # 回退路径：旧 bridge 被关闭，新 bridge 用压缩后历史重连
    assert len(bridges) == 2
    assert closed_snapshot == [True, False]
    assert len(bridges[0].compress_calls) == 1
    history = bridges[1].connected[2]
    assert len(history) == 7  # 1 条摘要 + 6 条最近保留
    assert history[0]["text"].startswith(SUMMARY_PREFIX)
    assert "summary of 5 items" in history[0]["text"]

    # 存储已被压缩替换
    session = client.get(f"/api/sessions/{sid}").json()
    assert len(session["transcript"]) == 7
    assert session["transcript"][0]["text"].startswith(SUMMARY_PREFIX)


# ==========================================
# 测试摘要失败时推送 error 且不关闭 bridge（对话可继续）
# ==========================================
def test_ws_auto_compress_failure_keeps_bridge(monkeypatch):
    async def broken_summarizer(old_transcript, language=None):
        raise OSError("摘要服务超时")

    bridges = []

    def fake_bridge_factory(**kwargs):
        bridge = FakeBridge(live_turns=1, **kwargs)
        bridges.append(bridge)
        return bridge

    monkeypatch.setattr(main, "SUMMARIZER", broken_summarizer)
    monkeypatch.setattr(main, "BRIDGE_CLASS", fake_bridge_factory)

    client = TestClient(main.app)
    client.post("/api/auth/register", json={"username": "compuser2", "password": "pass123"})
    client.put("/api/credentials", json={"api_key": "sk-test", "base_url": ""})
    sid = client.post("/api/sessions", json={}).json()["id"]
    for i in range(30):
        storage.append_transcript("compuser2", sid, "user", f"第{i}条" + "长" * 600)

    msgs, closed_snapshot = run_until_compressed(client, sid, bridges)

    types = [m["type"] for m in msgs]
    assert "compressing" in types
    assert types[-1] == "error"
    assert "摘要服务超时" in msgs[-1]["message"]
    # 压缩失败不触发会话内压缩也不重连，bridge 保持存活
    assert len(bridges) == 1
    assert closed_snapshot == [False]
    assert bridges[0].compress_calls == []
    # 历史未被压缩改动（30 条预填 + 1 条 FakeBridge 触发发言）
    session = client.get(f"/api/sessions/{sid}").json()
    assert len(session["transcript"]) == 31
    assert not session["transcript"][0]["text"].startswith(SUMMARY_PREFIX)
