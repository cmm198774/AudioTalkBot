# ==========================================
# FastAPI 入口：静态页面托管、会话/预设 REST 接口
# WebSocket 对话端点在后续任务中加入
# ==========================================
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import storage
from app.config import INPUT_SAMPLE_RATE, MODEL_NAME, OUTPUT_SAMPLE_RATE, get_api_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="语音对话机器人")

# 静态资源目录与挂载
_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# ==========================================
# 请求体模型
# ==========================================
class SessionCreate(BaseModel):
    system_prompt: str = ""
    output_mode: str = "audio_text"


class SessionUpdate(BaseModel):
    title: str | None = None
    system_prompt: str | None = None
    output_mode: str | None = None


class PresetCreate(BaseModel):
    name: str
    prompt: str


# ==========================================
# 首页
# ==========================================
@app.get("/")
async def index():
    """
    返回前端单页面。
    Returns:
        FileResponse: index.html
    """
    return FileResponse(_STATIC_DIR / "index.html")


# ==========================================
# 前端启动配置
# ==========================================
@app.get("/api/config")
async def get_config():
    """
    返回模型名、采样率、API key 是否已配置。
    Returns:
        dict: 前端初始化所需配置
    """
    return {
        "model": MODEL_NAME,
        "has_api_key": bool(get_api_key()),
        "input_sample_rate": INPUT_SAMPLE_RATE,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
    }


# ==========================================
# 会话：列表
# ==========================================
@app.get("/api/sessions")
async def list_sessions():
    """
    返回会话列表（按更新时间倒序）。
    Returns:
        list: 会话列表
    """
    return storage.list_sessions()


# ==========================================
# 会话：创建
# ==========================================
@app.post("/api/sessions", status_code=201)
async def create_session(body: SessionCreate):
    """
    创建新会话。
    Args:
        body: system_prompt 与 output_mode (SessionCreate)
    Returns:
        dict: 新会话
    """
    return storage.create_session(body.system_prompt, body.output_mode)


# ==========================================
# 会话：读取单个
# ==========================================
@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """
    读取单个会话。
    Args:
        session_id: 会话 id (str)
    Returns:
        dict: 会话
    """
    session = storage.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


# ==========================================
# 会话：更新
# ==========================================
@app.put("/api/sessions/{session_id}")
async def update_session(session_id: str, body: SessionUpdate):
    """
    更新会话标题、prompt 或输出模式。
    Args:
        session_id: 会话 id (str)
        body: 待更新字段 (SessionUpdate)
    Returns:
        dict: 更新后的会话
    """
    fields = body.model_dump(exclude_none=True)
    session = storage.update_session(session_id, **fields)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


# ==========================================
# 会话：删除
# ==========================================
@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    """
    删除会话。
    Args:
        session_id: 会话 id (str)
    """
    if not storage.delete_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")


# ==========================================
# 预设：列表
# ==========================================
@app.get("/api/presets")
async def list_presets():
    """
    返回预设列表。
    Returns:
        list: 预设列表
    """
    return storage.list_presets()


# ==========================================
# 预设：创建
# ==========================================
@app.post("/api/presets", status_code=201)
async def create_preset(body: PresetCreate):
    """
    创建人设预设。
    Args:
        body: name 与 prompt (PresetCreate)
    Returns:
        dict: 新预设
    """
    return storage.create_preset(body.name, body.prompt)


# ==========================================
# 预设：删除
# ==========================================
@app.delete("/api/presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: str):
    """
    删除预设。
    Args:
        preset_id: 预设 id (str)
    """
    if not storage.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="预设不存在")
