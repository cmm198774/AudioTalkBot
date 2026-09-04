# ==========================================
# 配置模块测试：常量正确性与环境变量读取
# ==========================================
import ssl

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
# 测试由 base_url 推导 realtime 地址：共用域名、换 /api-ws 路径
# ==========================================
def test_build_ws_url():
    url = config.build_ws_url(
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "qwen-audio-3.0-realtime-plus",
    )
    assert url == (
        "wss://token-plan.cn-beijing.maas.aliyuncs.com"
        "/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus"
    )


# ==========================================
# 测试默认 WebSocket 地址包含模型名与正确路径
# ==========================================
def test_ws_url_contains_model():
    assert config.DASHSCOPE_WS_URL.startswith("wss://")
    assert "/api-ws/v1/realtime" in config.DASHSCOPE_WS_URL
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


# ==========================================
# 测试板书固定指令与工具定义均指向 write_to_board 工具
# ==========================================
def test_board_prompt_tool_based():
    assert "write_to_board" in config.BOARD_PROMPT
    assert config.BOARD_TOOL["type"] == "function"
    assert config.BOARD_TOOL["function"]["name"] == "write_to_board"
    params = config.BOARD_TOOL["function"]["parameters"]
    assert "content" in params["properties"]
    assert params["required"] == ["content"]


# ==========================================
# 测试摘要模型默认取工作空间内实际提供的 qwen3.6-flash
# ==========================================
def test_summary_model_default():
    assert config.SUMMARY_MODEL == "qwen3.6-flash"


# ==========================================
# 测试 SSL 上下文已加载证书且开启校验
# ==========================================
def test_build_ssl_context():
    ctx = config.build_ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
