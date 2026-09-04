# ==========================================
# 全局配置：环境变量加载、模型常量、音频参数、路径
# ==========================================
import os
import ssl
from pathlib import Path
from urllib.parse import urlparse

import certifi
from dotenv import load_dotenv

# 项目根目录（app/ 的上一层）
BASE_DIR = Path(__file__).resolve().parent.parent

# 加载项目根 .env（内含 DASHSCOPE_API_KEY）
load_dotenv(BASE_DIR / ".env")

# ---- 模型与连接 ----
MODEL_NAME = "qwen-audio-3.0-realtime-plus"

# OpenAI 兼容模式的 base_url（可在 .env 用 DASHSCOPE_BASE_URL 覆盖）。
# realtime 与它共用同一域名，但走 /api-ws/v1/realtime 路径。
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
)


# ==========================================
# 由 base_url 推导 realtime WebSocket 地址
# ==========================================
def build_ws_url(base_url: str, model: str) -> str:
    """
    取 base_url 的域名（工作空间端点），拼接 realtime WebSocket 路径。
    Args:
        base_url: OpenAI 兼容 base_url，如 https://xxx.maas.aliyuncs.com/compatible-mode/v1 (str)
        model: 模型名 (str)
    Returns:
        str: wss://<域名>/api-ws/v1/realtime?model=<model>
    """
    host = urlparse(base_url).netloc
    return f"wss://{host}/api-ws/v1/realtime?model={model}"


DASHSCOPE_WS_URL = build_ws_url(DASHSCOPE_BASE_URL, MODEL_NAME)

# ---- 音频参数（官方协议：输入 16kHz、输出 24kHz、16bit 单声道 PCM）----
INPUT_SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
AUDIO_CHUNK_MS = 100

# ---- 输入转写模型（若服务端报错，按官方文档调整此常量）----
TRANSCRIPTION_MODEL = "qwen3-asr-flash"

# ---- 上下文压缩用的文本摘要模型（可用 .env 的 SUMMARY_MODEL 覆盖）----
# 必须是工作空间端点实际提供的模型（/compatible-mode/v1/models 可查）
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "qwen3.6-flash")

# ---- 输出模式 → API modalities 映射 ----
OUTPUT_MODE_MODALITIES = {
    "audio": ["audio"],
    "text": ["text"],
    "audio_text": ["text", "audio"],
}

# ---- 板书功能固定指令（拼接在用户人设之后，用户不可见不可改）----
# 板书通过 write_to_board 工具调用实现：工具参数是结构化文本，
# 不会被 TTS 朗读（只写不读），模型可在工具调用前后继续口头讲解。
BOARD_PROMPT = (
    "\n\n【板书功能】你身后有一块黑板，通过 write_to_board 工具写入。"
    "当用户说'写到黑板上''板书'或类似要求时，调用 write_to_board 工具，"
    "把要上黑板的内容放进 content 参数；"
    "你可以先口头讲解，再调用工具，工具返回后继续口头总结，也可多次调用。"
    "板书内容要提炼为简洁、结构化的要点，可换行分条，不要用口语复述。"
    "工具内容不会被朗读，需要用户听到的话必须口头说出来。"
    "普通对话不要调用工具。"
)

# ---- 板书工具定义（随 session.update 下发，模型据此发起工具调用）----
BOARD_TOOL = {
    "type": "function",
    "function": {
        "name": "write_to_board",
        "description": "把内容写到身后的黑板上。内容只展示不朗读。用户要求写黑板/板书时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "黑板内容，简洁结构化要点，可换行分条",
                },
            },
            "required": ["content"],
        },
    },
}

# ---- 数据持久化路径 ----
DATA_DIR = BASE_DIR / "data"
SESSIONS_FILE = DATA_DIR / "sessions.json"
PRESETS_FILE = DATA_DIR / "presets.json"


# ==========================================
# 构造使用 certifi 证书的 SSL 上下文
# ==========================================
def build_ssl_context() -> ssl.SSLContext:
    """
    本环境的默认证书上下文加载会失败，需显式用 certifi 证书构造，
    所有对外 HTTPS/WSS 连接都应使用它。
    Returns:
        ssl.SSLContext: 已加载 CA 证书的客户端上下文
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(certifi.where())
    return ctx


# ==========================================
# 读取 DashScope API Key
# ==========================================
def get_api_key() -> str:
    """
    从环境变量读取 API key。
    Returns:
        str: API key；未配置时返回空字符串
    """
    return os.getenv("DASHSCOPE_API_KEY", "")
