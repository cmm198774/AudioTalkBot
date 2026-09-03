# ==========================================
# 配置模块测试：常量正确性与环境变量读取
# ==========================================
from app import config


# ==========================================
# 测试音频参数与输出模式映射
# ==========================================
def test_audio_constants():
    assert config.INPUT_SAMPLE_RATE == 16000
    assert config.OUTPUT_SAMPLE_RATE == 24000
    assert config.AUDIO_CHUNK_MS == 100
    assert config.OUTPUT_MODE_MODALITIES["audio"] == ["audio"]
    assert config.OUTPUT_MODE_MODALITIES["text"] == ["text"]
    assert config.OUTPUT_MODE_MODALITIES["audio_text"] == ["text", "audio"]


# ==========================================
# 测试 WebSocket 地址包含模型名
# ==========================================
def test_ws_url_contains_model():
    assert config.DASHSCOPE_WS_URL.startswith("wss://dashscope.aliyuncs.com/api-ws/v1/realtime")
    assert config.MODEL_NAME in config.DASHSCOPE_WS_URL


# ==========================================
# 测试未设置环境变量时返回空串
# ==========================================
def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    assert config.get_api_key() == ""


# ==========================================
# 测试环境变量存在时正常读取
# ==========================================
def test_get_api_key_present(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-123")
    assert config.get_api_key() == "sk-test-123"
