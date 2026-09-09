# ==========================================
# 自动压缩测试：bridge 自取消防御 + WebSocket 全链路
# （超限 → compressing 通知 → 摘要压缩 → 独立任务重连 → auto_compressed）
# ==========================================
import asyncio
import json

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
# 记录型假桥接：connect 后在独立任务中触发一次用户转写。
# 忠实还原真实 bridge 的任务拓扑：转写回调发生在
# 接收循环任务内（而非 connect 调用方协程内），
# 这正是旧代码 close 自我取消 bug 的触发条件。
# ==========================================
class FakeBridge:
    def __init__(self, send_to_client, on_final_transcript=None, api_key="",
                 base_url="", ws_factory=None):
        self.send_to_client = send_to_client
        self.on_final_transcript = on_final_transcript
        self.connected = None
        self.closed = False
        self.final_task = None

    async def connect(self, instructions, output_mode, history=None):
        self.connected = (instructions, output_mode, history)
        if self.on_final_transcript is not None:
            self.final_task = asyncio.create_task(
                self.on_final_transcript("user", "触发压缩的发言")
            )

    async def send_audio(self, b64_audio):
        pass

    async def update_session(self, instructions, output_mode):
        pass

    async def close(self):
        self.closed = True


# ==========================================
# 测试 WebSocket 全链路：超限自动压缩 + 独立任务重连 + 前端通知
# ==========================================
def test_ws_auto_compress_and_reconnect(monkeypatch):
    languages = []

    async def fake_summarizer(old_transcript, language=None):
        languages.append(language)
        return f"summary of {len(old_transcript)} items"

    bridges = []

    def fake_bridge_factory(**kwargs):
        bridge = FakeBridge(**kwargs)
        bridges.append(bridge)
        return bridge

    monkeypatch.setattr(main, "SUMMARIZER", fake_summarizer)
    monkeypatch.setattr(main, "BRIDGE_CLASS", fake_bridge_factory)

    client = TestClient(main.app)
    client.post("/api/auth/register", json={"username": "compuser", "password": "pass123"})
    client.put("/api/credentials", json={"api_key": "sk-test", "base_url": ""})
    sid = client.post("/api/sessions", json={}).json()["id"]

    # 预填 30 条中文长消息（约 18000 字符 > 阈值 12800）
    for i in range(30):
        role = "user" if i % 2 == 0 else "assistant"
        storage.append_transcript("compuser", sid, role, f"第{i}条" + "长" * 600)

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        msgs = []
        for _ in range(10):
            msg = ws.receive_json()
            msgs.append(msg)
            if msg["type"] in ("auto_compressed", "error"):
                break
        ws.send_json({"type": "stop"})

    types = [m["type"] for m in msgs]
    # 收到压缩开始与完成通知，且顺序正确、无错误
    assert types[-1] == "auto_compressed", f"消息序列异常: {types}"
    assert "compressing" in types
    assert types.index("compressing") < types.index("auto_compressed")
    assert "error" not in types

    # 摘要语言与对话语言一致（中文对话 → zh）
    assert languages == ["zh"]

    # 旧 bridge 被关闭，新 bridge 用压缩后的历史重连
    assert len(bridges) == 2
    assert bridges[0].closed is True
    assert bridges[1].connected is not None
    history = bridges[1].connected[2]
    assert len(history) == 7  # 1 条摘要 + 6 条最近保留
    assert history[0]["text"].startswith(SUMMARY_PREFIX)
    # 30 条预填 + 1 条触发发言 = 31 条，保留最近 6 条，摘要 25 条
    assert "summary of 25 items" in history[0]["text"]

    # 重连成功后推送了压缩后的上下文用量（7 条）
    # 注：bridge#2 的转写任务与重连任务并发，消息顺序不定，用 any 断言
    assert any(
        m["type"] == "context_usage"
        and m["count"] == 7
        and m["chars"] < main.AUTO_COMPRESS_THRESHOLD
        for m in msgs
    )

    # 存储已被压缩替换
    session = client.get(f"/api/sessions/{sid}").json()
    assert session["transcript"][0]["text"].startswith(SUMMARY_PREFIX)


# ==========================================
# 测试压缩失败时推送 error 且不关闭 bridge（对话可继续）
# ==========================================
def test_ws_auto_compress_failure_keeps_bridge(monkeypatch):
    async def broken_summarizer(old_transcript, language=None):
        raise OSError("摘要服务超时")

    bridges = []

    def fake_bridge_factory(**kwargs):
        bridge = FakeBridge(**kwargs)
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

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        msgs = []
        for _ in range(10):
            msg = ws.receive_json()
            msgs.append(msg)
            if msg["type"] == "error":
                break
        ws.send_json({"type": "stop"})

    types = [m["type"] for m in msgs]
    assert "compressing" in types
    assert types[-1] == "error"
    assert "摘要服务超时" in msgs[-1]["message"]
    # 压缩失败不触发重连，只有一个 bridge
    assert len(bridges) == 1
    # 历史未被压缩改动（30 条预填 + 1 条 FakeBridge 触发发言）
    session = client.get(f"/api/sessions/{sid}").json()
    assert len(session["transcript"]) == 31
    assert not session["transcript"][0]["text"].startswith(SUMMARY_PREFIX)
