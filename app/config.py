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

# ---- 上下文压缩用的文本摘要模型（可用 .env 的 SUMMARY_MODEL 覆盖）----
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "qwen-plus")

# ---- 输出模式 → API modalities 映射 ----
OUTPUT_MODE_MODALITIES = {
    "audio": ["audio"],
    "text": ["text"],
    "audio_text": ["text", "audio"],
}

# ---- 板书功能固定指令（拼接在用户人设之后，用户不可见不可改）----
# 模型把黑板内容用 [start]/[end] 包裹，后端按标记分流：
# 标记内容上黑板，对应时间窗口的音频被丢弃（只写不读）。
BOARD_PROMPT = (
    "\n\n【板书功能】你身后有一块黑板。"
    "当用户说'写到黑板上''板书'或类似要求时，把要上黑板的内容用 [start] 和 [end] 包裹，"
    "这部分只写不读；同一条回复可以先口头讲解，再写黑板，再继续口头总结。"
    "朗读节奏要求：说到 [start] 前，先把前面的话说完并停顿约两秒；"
    "[end] 之后也要先停顿约两秒再继续说，给黑板留出书写时间。"
    "板书内容要提炼为简洁、结构化的要点，可换行分条，不要用口语复述或 Markdown 代替。"
    "示例——用户：把勾股定理写到黑板上。"
    "回复：好的，我们来看勾股定理。[start]勾股定理：直角边 a、b，斜边 c，"
    "满足 a² + b² = c²[end] 大家记得多练习。"
    "普通对话回复不要包含 [start]/[end] 标记。"
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
