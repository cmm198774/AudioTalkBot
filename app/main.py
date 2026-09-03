# ==========================================
# FastAPI 入口：静态页面托管、会话/预设 REST 接口
# WebSocket 对话端点在后续任务中加入
# ==========================================
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import storage
from app.bridge import RealtimeBridge
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


# ==========================================
# 桥接类注入点（测试用假实现替换）
# ==========================================
BRIDGE_CLASS = RealtimeBridge


# ==========================================
# 对话 WebSocket 端点
# ==========================================
@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    """
    对话主通道：一个浏览器连接对应一个活动会话。
    前端消息：start / audio / update_settings / stop
    Args:
        ws: FastAPI WebSocket 连接
    """
    await ws.accept()
    bridge = None
    state = {"session_id": None}

    async def send_to_client(msg: dict) -> None:
        """
        把消息推送给浏览器。
        Args:
            msg: 前端消息字典 (dict)
        """
        await ws.send_json(msg)

    async def on_final_transcript(role: str, text: str) -> None:
        """
        最终转写落盘；首句用户发言自动命名会话。
        Args:
            role: user 或 assistant (str)
            text: 转写文本 (str)
        """
        session_id = state["session_id"]
        if not session_id:
            return
        storage.append_transcript(session_id, role, text)
        if role == "user":
            session = storage.get_session(session_id)
            if session is not None and session["title"] == "新对话":
                title = text.strip()[:20] or "新对话"
                storage.update_session(session_id, title=title)
                await send_to_client({"type": "title", "value": title})

    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "start":
                if bridge is not None:
                    await bridge.close()
                session_id = msg.get("session_id")
                session = storage.get_session(session_id) if session_id else None
                if session is None:
                    await send_to_client({"type": "error", "message": "会话不存在"})
                    continue
                state["session_id"] = session_id
                bridge = BRIDGE_CLASS(
                    send_to_client=send_to_client,
                    on_final_transcript=on_final_transcript,
                )
                try:
                    await bridge.connect(
                        instructions=session["system_prompt"],
                        output_mode=session["output_mode"],
                        history=session["transcript"],
                    )
                except Exception as exc:
                    logger.warning("连接 DashScope 失败: %s", exc)
                    await bridge.close()
                    bridge = None
                    state["session_id"] = None
                    await send_to_client({"type": "error", "message": f"连接失败：{exc}"})
            elif mtype == "audio":
                if bridge is not None:
                    await bridge.send_audio(msg.get("data", ""))
            elif mtype == "update_settings":
                session_id = state["session_id"]
                system_prompt = msg.get("system_prompt")
                output_mode = msg.get("output_mode")
                if session_id:
                    fields = {}
                    if system_prompt is not None:
                        fields["system_prompt"] = system_prompt
                    if output_mode is not None:
                        fields["output_mode"] = output_mode
                    if fields:
                        storage.update_session(session_id, **fields)
                if bridge is not None:
                    await bridge.update_session(system_prompt or "", output_mode or "audio_text")
            elif mtype == "stop":
                if bridge is not None:
                    await bridge.close()
                    bridge = None
                state["session_id"] = None
    except WebSocketDisconnect:
        logger.info("前端 WebSocket 断开")
    finally:
        if bridge is not None:
            await bridge.close()
