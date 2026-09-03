# ==========================================
# 全局配置：环境变量加载、模型常量、音频参数、路径
# ==========================================
import os
from pathlib import Path
from urllib.parse import urlparse

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

# ---- 输出模式 → API modalities 映射 ----
OUTPUT_MODE_MODALITIES = {
    "audio": ["audio"],
    "text": ["text"],
    "audio_text": ["text", "audio"],
}

# ---- 板书功能固定指令（拼接在用户人设之后，用户不可见不可改）----
# 模型需要呈现板书时，单独输出以 [text]: 开头的一段内容，
# 前端据此把内容送上小黑板并掐断该回合语音。
BOARD_PROMPT = (
    "\n\n【板书功能】当你需要呈现板书内容时，"
    "单独输出一段以 [text]: 开头的内容，"
    "例如 [text]:勾股定理：a² + b² = c²。"
    "板书内容应提炼为简洁、结构化的要点，可用换行分条；"
    "普通对话回复不要包含 [text]: 标记。"
)

# ---- 数据持久化路径 ----
DATA_DIR = BASE_DIR / "data"
SESSIONS_FILE = DATA_DIR / "sessions.json"
PRESETS_FILE = DATA_DIR / "presets.json"


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
