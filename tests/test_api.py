# ==========================================
# HTTP API 测试：认证、会话、预设接口、上下文管理
# ==========================================
import pytest
from fastapi.testclient import TestClient

from app import auth, main, storage

# 测试用的用户名
TEST_USER = "testuser"
TEST_PASSWORD = "testpass123"


# ==========================================
# 已认证的测试客户端 fixture
# ==========================================
@pytest.fixture
def auth_client(tmp_path):
    """
    返回已登录的 TestClient。
    Returns:
        TestClient: 已登录的客户端
    """
    # 注册用户
    auth.register(TEST_USER, TEST_PASSWORD)
    client = TestClient(main.app)
    # 登录获取 cookie
    resp = client.post(
        "/api/auth/login",
        json={"username": TEST_USER, "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200
    return client


# ==========================================
# 测试首页返回 HTML
# ==========================================
def test_index_serves_html():
    client = TestClient(main.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


# ==========================================
# 测试未认证请求返回 401
# ==========================================
def test_unauthenticated_returns_401():
    client = TestClient(main.app)
    resp = client.get("/api/config")
    assert resp.status_code == 401
    resp = client.get("/api/sessions")
    assert resp.status_code == 401


# ==========================================
# 测试注册
# ==========================================
def test_register():
    client = TestClient(main.app)
    resp = client.post(
        "/api/auth/register",
        json={"username": "newuser", "password": "newpass"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "newuser"
    assert "session_id" in resp.cookies


# ==========================================
# 测试重复注册返回 409
# ==========================================
def test_register_duplicate():
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"username": "alice", "password": "pass"})
    resp = client.post("/api/auth/register", json={"username": "alice", "password": "pass2"})
    assert resp.status_code == 409


# ==========================================
# 测试登录
# ==========================================
def test_login():
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"username": "bob", "password": "pass"})
    resp = client.post("/api/auth/login", json={"username": "bob", "password": "pass"})
    assert resp.status_code == 200
    assert "session_id" in resp.cookies


# ==========================================
# 测试登录错误密码返回 401
# ==========================================
def test_login_wrong_password():
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"username": "charlie", "password": "pass"})
    resp = client.post("/api/auth/login", json={"username": "charlie", "password": "wrong"})
    assert resp.status_code == 401


# ==========================================
# 测试获取当前用户
# ==========================================
def test_get_me(auth_client):
    resp = auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == TEST_USER


# ==========================================
# 测试登出
# ==========================================
def test_logout(auth_client):
    resp = auth_client.post("/api/auth/logout")
    assert resp.status_code == 200
    # 登出后再访问需认证接口应返回 401
    resp = auth_client.get("/api/auth/me")
    assert resp.status_code == 401


# ==========================================
# 测试配置接口字段（已认证）
# ==========================================
def test_get_config(auth_client):
    data = auth_client.get("/api/config").json()
    assert data["input_sample_rate"] == 16000
    assert data["output_sample_rate"] == 24000
    assert "model" in data


# ==========================================
# 测试凭证的保存与读取
# ==========================================
def test_credentials_crud(auth_client):
    # 保存凭证
    resp = auth_client.put(
        "/api/credentials",
        json={"api_key": "sk-test-key", "base_url": "https://api.test.com"},
    )
    assert resp.status_code == 200
    # 读取凭证
    creds = auth_client.get("/api/credentials").json()
    assert creds["api_key"] == "sk-test-key"
    assert creds["base_url"] == "https://api.test.com"


# ==========================================
# 测试会话的创建、列表、更新、删除
# ==========================================
def test_sessions_crud(auth_client):
    created = auth_client.post(
        "/api/sessions",
        json={"system_prompt": "测试提示词", "output_mode": "audio_text"},
    )
    assert created.status_code == 201
    sid = created.json()["id"]

    sessions = auth_client.get("/api/sessions").json()
    assert any(s["id"] == sid for s in sessions)

    fetched = auth_client.get(f"/api/sessions/{sid}").json()
    assert fetched["system_prompt"] == "测试提示词"

    updated = auth_client.put(f"/api/sessions/{sid}", json={"title": "改名"}).json()
    assert updated["title"] == "改名"

    assert auth_client.delete(f"/api/sessions/{sid}").status_code == 204
    assert auth_client.get(f"/api/sessions/{sid}").status_code == 404
    assert auth_client.delete(f"/api/sessions/{sid}").status_code == 404


# ==========================================
# 测试用户隔离：不同用户的会话互不可见
# ==========================================
def test_user_isolation():
    # 用户 A 创建会话
    client_a = TestClient(main.app)
    client_a.post("/api/auth/register", json={"username": "user_a", "password": "pass"})
    client_a.post("/api/auth/login", json={"username": "user_a", "password": "pass"})
    resp = client_a.post(
        "/api/sessions",
        json={"system_prompt": "A 的会话", "output_mode": "audio_text"},
    )
    sid_a = resp.json()["id"]

    # 用户 B 创建会话
    client_b = TestClient(main.app)
    client_b.post("/api/auth/register", json={"username": "user_b", "password": "pass"})
    client_b.post("/api/auth/login", json={"username": "user_b", "password": "pass"})
    resp = client_b.post(
        "/api/sessions",
        json={"system_prompt": "B 的会话", "output_mode": "audio_text"},
    )
    sid_b = resp.json()["id"]

    # A 看不到 B 的会话
    sessions_a = client_a.get("/api/sessions").json()
    assert len(sessions_a) == 1
    assert sessions_a[0]["id"] == sid_a
    assert client_a.get(f"/api/sessions/{sid_b}").status_code == 404

    # B 看不到 A 的会话
    sessions_b = client_b.get("/api/sessions").json()
    assert len(sessions_b) == 1
    assert sessions_b[0]["id"] == sid_b


# ==========================================
# 测试预设的创建、列表、删除
# ==========================================
def test_presets_crud(auth_client):
    created = auth_client.post(
        "/api/presets", json={"name": "法语老师", "prompt": "你是法语老师"}
    )
    assert created.status_code == 201
    pid = created.json()["id"]
    assert len(auth_client.get("/api/presets").json()) == 1
    assert auth_client.delete(f"/api/presets/{pid}").status_code == 204
    assert auth_client.delete(f"/api/presets/{pid}").status_code == 404


# ==========================================
# 测试同名预设重复保存时覆盖而非追加
# ==========================================
def test_presets_same_name_overwrites(auth_client):
    first = auth_client.post(
        "/api/presets", json={"name": "心理咨询师", "prompt": "旧版内容"}
    )
    second = auth_client.post(
        "/api/presets", json={"name": "心理咨询师", "prompt": "新版内容"}
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    presets = auth_client.get("/api/presets").json()
    assert len(presets) == 1
    assert presets[0]["prompt"] == "新版内容"


# ==========================================
# 假桥接类：记录调用，模拟连接行为
# ==========================================
class FakeBridge:
    def __init__(
        self, send_to_client, on_final_transcript=None, api_key="",
        base_url="", ws_factory=None
    ):
        self.send_to_client = send_to_client
        self.on_final_transcript = on_final_transcript
        self.api_key = api_key
        self.base_url = base_url
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
def test_ws_chat_flow(monkeypatch, auth_client):
    holder = {}

    def fake_bridge_factory(**kwargs):
        bridge = FakeBridge(**kwargs)
        holder["bridge"] = bridge
        return bridge

    monkeypatch.setattr(main, "BRIDGE_CLASS", fake_bridge_factory)
    # 先保存凭证，否则连接会失败
    auth_client.put(
        "/api/credentials",
        json={"api_key": "sk-test", "base_url": ""},
    )

    sid = auth_client.post(
        "/api/sessions",
        json={"system_prompt": "原有提示词", "output_mode": "audio_text"},
    ).json()["id"]

    # WebSocket 连接需要手动传递 cookie
    with auth_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        # FakeBridge.connect 内触发用户转写 → 先推上下文用量，再推自动命名
        usage_msg = ws.receive_json()
        assert usage_msg["type"] == "context_usage"
        assert usage_msg["chars"] == len("你好，这是自动命名测试")
        assert usage_msg["count"] == 1
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
    # instructions = 人设 + 固定板书指令
    assert bridge.connected[0].startswith("原有提示词")
    assert "write_to_board" in bridge.connected[0]
    assert bridge.connected[1] == "audio_text"
    assert bridge.audio == ["QUJD"]
    assert bridge.updated[0].startswith("新提示词")
    assert "write_to_board" in bridge.updated[0]
    assert bridge.updated[1] == "text"
    assert bridge.closed is True

    session = auth_client.get(f"/api/sessions/{sid}").json()
    assert session["title"] == "你好，这是自动命名测试"
    assert session["transcript"][0]["text"] == "你好，这是自动命名测试"
    assert session["system_prompt"] == "新提示词"
    assert session["output_mode"] == "text"


# ==========================================
# 测试只改输出模式时不清空人设（回读会话存储）
# ==========================================
def test_ws_chat_update_settings_keeps_persona(monkeypatch, auth_client):
    holder = {}

    def fake_bridge_factory(**kwargs):
        bridge = FakeBridge(**kwargs)
        holder["bridge"] = bridge
        return bridge

    monkeypatch.setattr(main, "BRIDGE_CLASS", fake_bridge_factory)
    auth_client.put("/api/credentials", json={"api_key": "sk-test", "base_url": ""})
    sid = auth_client.post(
        "/api/sessions",
        json={"system_prompt": "原有人设", "output_mode": "audio_text"},
    ).json()["id"]

    with auth_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        # 只改输出模式，不带 system_prompt
        ws.send_json({"type": "update_settings", "output_mode": "text"})
        ws.send_json({"type": "stop"})

    bridge = holder["bridge"]
    assert bridge.updated[0].startswith("原有人设")
    assert "write_to_board" in bridge.updated[0]
    assert bridge.updated[1] == "text"


# ==========================================
# 测试 start 未知会话返回 error 消息
# ==========================================
def test_ws_chat_start_unknown_session(monkeypatch, auth_client):
    monkeypatch.setattr(main, "BRIDGE_CLASS", FakeBridge)
    auth_client.put("/api/credentials", json={"api_key": "sk-test", "base_url": ""})
    with auth_client.websocket_connect("/ws/chat") as ws:
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
def test_ws_chat_connect_failure(monkeypatch, auth_client):
    monkeypatch.setattr(main, "BRIDGE_CLASS", FailingBridge)
    auth_client.put("/api/credentials", json={"api_key": "sk-test", "base_url": ""})
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    with auth_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "401" in msg["message"]


# ==========================================
# 测试未配置 API key 时 start 返回错误
# ==========================================
def test_ws_chat_no_credentials(monkeypatch, auth_client):
    monkeypatch.setattr(main, "BRIDGE_CLASS", FakeBridge)
    # 不保存凭证
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    with auth_client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "start", "session_id": sid})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "API key" in msg["message"]


# ==========================================
# 测试清空历史端点
# ==========================================
def test_clear_history(auth_client):
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    storage.append_transcript(TEST_USER, sid, "user", "你好")
    storage.append_transcript(TEST_USER, sid, "assistant", "Bonjour")
    resp = auth_client.post(f"/api/sessions/{sid}/clear_history")
    assert resp.status_code == 200
    assert resp.json()["transcript"] == []
    assert auth_client.post("/api/sessions/不存在/clear_history").status_code == 404


# ==========================================
# 假摘要器：不发网络请求，返回固定摘要
# ==========================================
async def fake_summarizer(old_transcript):
    return f"共总结了{len(old_transcript)}条"


# ==========================================
# 测试压缩上下文：旧对话被摘要，最近 6 条原样保留
# ==========================================
def test_compress_history(monkeypatch, auth_client):
    monkeypatch.setattr(main, "SUMMARIZER", fake_summarizer)
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    for i in range(10):
        role = "user" if i % 2 == 0 else "assistant"
        storage.append_transcript(TEST_USER, sid, role, f"第{i}条")
    resp = auth_client.post(f"/api/sessions/{sid}/compress")
    assert resp.status_code == 200
    transcript = resp.json()["transcript"]
    assert len(transcript) == 7
    assert transcript[0]["role"] == "assistant"
    assert "共总结了4条" in transcript[0]["text"]
    assert transcript[1]["text"] == "第4条"
    assert transcript[-1]["text"] == "第9条"


# ==========================================
# 测试历史过短压缩返回 400
# ==========================================
def test_compress_history_too_short(monkeypatch, auth_client):
    monkeypatch.setattr(main, "SUMMARIZER", fake_summarizer)
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    storage.append_transcript(TEST_USER, sid, "user", "你好")
    assert auth_client.post(f"/api/sessions/{sid}/compress").status_code == 400


# ==========================================
# 测试压缩时摘要服务失败返回 502
# ==========================================
def test_compress_history_summarizer_error(monkeypatch, auth_client):
    async def broken_summarizer(old_transcript):
        raise OSError("连接超时")

    monkeypatch.setattr(main, "SUMMARIZER", broken_summarizer)
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    for i in range(10):
        storage.append_transcript(TEST_USER, sid, "user", f"第{i}条")
    resp = auth_client.post(f"/api/sessions/{sid}/compress")
    assert resp.status_code == 502
    # 压缩失败不改动历史
    assert len(auth_client.get(f"/api/sessions/{sid}").json()["transcript"]) == 10


# ==========================================
# 测试静态 JS/CSS 资源可访问
# ==========================================
def test_static_assets_served():
    client = TestClient(main.app)
    for path in ("/static/style.css", "/static/audio.js", "/static/app.js", "/static/capture-processor.worklet.js"):
        assert client.get(path).status_code == 200, path
