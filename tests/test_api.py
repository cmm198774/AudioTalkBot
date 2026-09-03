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
