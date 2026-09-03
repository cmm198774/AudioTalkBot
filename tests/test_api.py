# ==========================================
# HTTP API 测试：配置、会话、预设接口
# ==========================================
from fastapi.testclient import TestClient

from app import main


# ==========================================
# 测试首页返回 HTML
# ==========================================
def test_index_serves_html():
    client = TestClient(main.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ==========================================
# 测试配置接口字段
# ==========================================
def test_get_config():
    client = TestClient(main.app)
    data = client.get("/api/config").json()
    assert data["input_sample_rate"] == 16000
    assert data["output_sample_rate"] == 24000
    assert "has_api_key" in data
    assert "model" in data


# ==========================================
# 测试会话的创建、列表、更新、删除
# ==========================================
def test_sessions_crud():
    client = TestClient(main.app)
    created = client.post(
        "/api/sessions",
        json={"system_prompt": "测试提示词", "output_mode": "audio_text"},
    )
    assert created.status_code == 201
    sid = created.json()["id"]

    sessions = client.get("/api/sessions").json()
    assert any(s["id"] == sid for s in sessions)

    fetched = client.get(f"/api/sessions/{sid}").json()
    assert fetched["system_prompt"] == "测试提示词"

    updated = client.put(f"/api/sessions/{sid}", json={"title": "改名"}).json()
    assert updated["title"] == "改名"

    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert client.delete(f"/api/sessions/{sid}").status_code == 404


# ==========================================
# 测试预设的创建、列表、删除
# ==========================================
def test_presets_crud():
    client = TestClient(main.app)
    created = client.post("/api/presets", json={"name": "法语老师", "prompt": "你是法语老师"})
    assert created.status_code == 201
    pid = created.json()["id"]
    assert len(client.get("/api/presets").json()) == 1
    assert client.delete(f"/api/presets/{pid}").status_code == 204
    assert client.delete(f"/api/presets/{pid}").status_code == 404


# ==========================================
# 假桥接类：记录调用，模拟连接行为
# ==========================================
class FakeBridge:
    def __init__(self, send_to_client, on_final_transcript=None, api_key="", ws_factory=None):
        self.send_to_client = send_to_client
        self.on_final_transcript = on_final_transcript
        self.connected = None
        self.updated = None
        self.audio = []
        self.closed = False

    async def connect(self, instructions, output_mode, history=None):
        self.connected = (instructions, output_mode, history)
        # 触发一次用户最终转写，验证持久化回调与自动命名
        if self.on_final_transcript is not None:
            await self.on_final_transcript("user", "你好，这是自动命名测试")

    async def send_audio(self, b64_audio):
        self.audio.append(b64_audio)

    async def update_session(self, instructions, output_mode):
        self.updated = (instructions, output_mode)

    async def close(self):
        self.closed = True


# ==========================================
# 测试完整对话流程：start → 自动命名 → audio → update_settings → stop
# ==========================================
def test_ws_chat_flow(monkeypatch):
    holder = {}

    def fake_bridge_factory(**kwargs):
        bridge = FakeBridge(**kwargs)
        holder["bridge"] = bridge
        return bridge

    monkeypatch.setattr(main, "BRIDGE_CLASS", fake_bridge_factory)
    client = TestClient(main.app)

    sid = client.post(
        "/api/sessions",
        json={"system_prompt": "原有提示词", "output_mode": "audio_text"},
    ).json()["id"]

    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        # FakeBridge.connect 内触发用户转写 → 自动命名 → 后端推送 title
        title_msg = ws.receive_json()
        assert title_msg["type"] == "title"
        assert title_msg["value"] == "你好，这是自动命名测试"

        ws.send_json({"type": "audio", "data": "QUJD"})
        ws.send_json({
            "type": "update_settings",
            "system_prompt": "新提示词",
            "output_mode": "text",
        })
        ws.send_json({"type": "stop"})

    bridge = holder["bridge"]
    assert bridge.connected[0] == "原有提示词"
    assert bridge.connected[1] == "audio_text"
    assert bridge.audio == ["QUJD"]
    assert bridge.updated == ("新提示词", "text")
    assert bridge.closed is True

    session = client.get(f"/api/sessions/{sid}").json()
    assert session["title"] == "你好，这是自动命名测试"
    assert session["transcript"][0]["text"] == "你好，这是自动命名测试"
    assert session["system_prompt"] == "新提示词"
    assert session["output_mode"] == "text"


# ==========================================
# 测试 start 未知会话返回 error 消息
# ==========================================
def test_ws_chat_start_unknown_session(monkeypatch):
    monkeypatch.setattr(main, "BRIDGE_CLASS", FakeBridge)
    client = TestClient(main.app)
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": "不存在"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "会话不存在" in msg["message"]


# ==========================================
# 连接失败的桥接类：模拟 API key 错误等握手失败
# ==========================================
class FailingBridge(FakeBridge):
    async def connect(self, instructions, output_mode, history=None):
        raise OSError("401 Unauthorized")


# ==========================================
# 测试连接 DashScope 失败时推送 error 消息而非直接断开
# ==========================================
def test_ws_chat_connect_failure(monkeypatch):
    monkeypatch.setattr(main, "BRIDGE_CLASS", FailingBridge)
    client = TestClient(main.app)
    sid = client.post("/api/sessions", json={}).json()["id"]
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "401" in msg["message"]


# ==========================================
# 测试静态 JS/CSS 资源可访问
# ==========================================
def test_static_assets_served():
    client = TestClient(main.app)
    for path in ("/static/style.css", "/static/audio.js", "/static/app.js", "/static/capture-processor.worklet.js"):
        assert client.get(path).status_code == 200, path
