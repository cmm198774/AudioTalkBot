# ==========================================
# FastAPI 入口：用户认证、会话/预设 REST 接口、WebSocket 对话
# 所有数据按用户隔离，每个用户自带 API key 和 base_url
# ==========================================
import asyncio
import logging
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import auth, context, storage
from app.bridge import RealtimeBridge
from app.config import (
    BOARD_PROMPT,
    INPUT_SAMPLE_RATE,
    MODEL_NAME,
    OUTPUT_SAMPLE_RATE,
    build_ws_url,
)
from app.context import CONTEXT_INPUT_LIMIT

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
class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class CredentialsUpdate(BaseModel):
    api_key: str = ""
    base_url: str = ""


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
# 当前用户依赖：从 cookie 提取 session_id，验证后返回 username
# ==========================================
def get_current_user(
    auth_session_id: str = Cookie(None, alias=auth.SESSION_COOKIE_NAME),
) -> str:
    """
    FastAPI 依赖：从 cookie 验证 session，返回 username。
    Args:
        auth_session_id: cookie 中的 session_id (str)
    Returns:
        str: 当前用户名
    Raises:
        HTTPException: 401 未登录
    """
    if not auth_session_id:
        raise HTTPException(status_code=401, detail="未登录")
    username = auth.get_user_by_session(auth_session_id)
    if not username:
        raise HTTPException(status_code=401, detail="登录已过期")
    return username


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
# 注册
# ==========================================
@app.post("/api/auth/register")
async def register(body: RegisterRequest):
    """
    注册新用户，成功后自动登录。
    Args:
        body: username 与 password (RegisterRequest)
    Returns:
        dict: {"username": str}
    """
    user = auth.register(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=409, detail="用户名已存在")
    session_id = auth.login(body.username, body.password)
    response = JSONResponse({"username": body.username})
    response.set_cookie(
        key=auth.SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return response


# ==========================================
# 登录
# ==========================================
@app.post("/api/auth/login")
async def login(body: LoginRequest):
    """
    登录。
    Args:
        body: username 与 password (LoginRequest)
    Returns:
        dict: {"username": str}
    """
    session_id = auth.login(body.username, body.password)
    if not session_id:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    response = JSONResponse({"username": body.username})
    response.set_cookie(
        key=auth.SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return response


# ==========================================
# 登出
# ==========================================
@app.post("/api/auth/logout")
async def logout(auth_session_id: str = Cookie(None, alias=auth.SESSION_COOKIE_NAME)):
    """
    登出，销毁 session。
    Args:
        auth_session_id: cookie 中的 session_id (str)
    Returns:
        dict: {"ok": True}
    """
    if auth_session_id:
        auth.logout(auth_session_id)
    response = JSONResponse({"ok": True})
    response.delete_cookie(key=auth.SESSION_COOKIE_NAME)
    return response


# ==========================================
# 获取当前用户信息
# ==========================================
@app.get("/api/auth/me")
async def get_me(username: str = Depends(get_current_user)):
    """
    返回当前登录用户信息。
    Args:
        username: 当前用户名 (str)
    Returns:
        dict: {"username": str}
    """
    return {"username": username}


# ==========================================
# 前端启动配置（不再包含 has_api_key，改为按需读取用户凭证）
# ==========================================
@app.get("/api/config")
async def get_config(username: str = Depends(get_current_user)):
    """
    返回模型名、采样率。
    Args:
        username: 当前用户名 (str)
    Returns:
        dict: 前端初始化所需配置
    """
    return {
        "model": MODEL_NAME,
        "input_sample_rate": INPUT_SAMPLE_RATE,
        "output_sample_rate": OUTPUT_SAMPLE_RATE,
    }


# ==========================================
# 用户凭证：读取
# ==========================================
@app.get("/api/credentials")
async def get_credentials(username: str = Depends(get_current_user)):
    """
    读取当前用户的 API 凭证（解密后）。
    Args:
        username: 当前用户名 (str)
    Returns:
        dict: {"api_key": str, "base_url": str}
    """
    return auth.decrypt_user_credentials(username)


# ==========================================
# 用户凭证：更新
# ==========================================
@app.put("/api/credentials")
async def update_credentials(
    body: CredentialsUpdate, username: str = Depends(get_current_user)
):
    """
    更新当前用户的 API 凭证。
    Args:
        body: api_key 与 base_url (CredentialsUpdate)
        username: 当前用户名 (str)
    Returns:
        dict: {"ok": True}
    """
    auth.save_user_credentials(username, body.api_key, body.base_url)
    return {"ok": True}


# ==========================================
# 会话：列表
# ==========================================
@app.get("/api/sessions")
async def list_sessions(username: str = Depends(get_current_user)):
    """
    返回当前用户的会话列表（按更新时间倒序）。
    Args:
        username: 当前用户名 (str)
    Returns:
        list: 会话列表
    """
    return storage.list_sessions(username)


# ==========================================
# 会话：创建
# ==========================================
@app.post("/api/sessions", status_code=201)
async def create_session(body: SessionCreate, username: str = Depends(get_current_user)):
    """
    创建新会话。
    Args:
        body: system_prompt 与 output_mode (SessionCreate)
        username: 当前用户名 (str)
    Returns:
        dict: 新会话
    """
    return storage.create_session(username, body.system_prompt, body.output_mode)


# ==========================================
# 会话：读取单个
# ==========================================
@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, username: str = Depends(get_current_user)):
    """
    读取单个会话。
    Args:
        session_id: 会话 id (str)
        username: 当前用户名 (str)
    Returns:
        dict: 会话
    """
    session = storage.get_session(username, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


# ==========================================
# 会话：更新
# ==========================================
@app.put("/api/sessions/{session_id}")
async def update_session(
    session_id: str, body: SessionUpdate, username: str = Depends(get_current_user)
):
    """
    更新会话标题、prompt 或输出模式。
    Args:
        session_id: 会话 id (str)
        body: 待更新字段 (SessionUpdate)
        username: 当前用户名 (str)
    Returns:
        dict: 更新后的会话
    """
    fields = body.model_dump(exclude_none=True)
    session = storage.update_session(username, session_id, **fields)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


# ==========================================
# 会话：删除
# ==========================================
@app.delete("/api/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, username: str = Depends(get_current_user)):
    """
    删除会话。
    Args:
        session_id: 会话 id (str)
        username: 当前用户名 (str)
    """
    if not storage.delete_session(username, session_id):
        raise HTTPException(status_code=404, detail="会话不存在")


# ==========================================
# 会话：清空历史
# ==========================================
@app.post("/api/sessions/{session_id}/clear_history")
async def clear_history(session_id: str, username: str = Depends(get_current_user)):
    """
    清空会话的全部对话历史。
    Args:
        session_id: 会话 id (str)
        username: 当前用户名 (str)
    Returns:
        dict: 更新后的会话
    """
    session = storage.replace_transcript(username, session_id, [])
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


# ==========================================
# 会话：压缩上下文（LLM 摘要旧对话）
# ==========================================
@app.post("/api/sessions/{session_id}/compress")
async def compress_history(session_id: str, username: str = Depends(get_current_user)):
    """
    把旧对话交给文本模型总结成一条摘要，最近几条原样保留，
    降低上下文占用。正在进行的对话不受影响，下次开始对话生效。
    Args:
        session_id: 会话 id (str)
        username: 当前用户名 (str)
    Returns:
        dict: 更新后的会话
    """
    session = storage.get_session(username, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    old, recent = context.split_old_recent(session["transcript"])
    if not old:
        raise HTTPException(status_code=400, detail="对话历史太少，无需压缩")
    old_text = "\n".join(item.get("text", "") for item in old)
    lang = context.detect_language(old_text)
    try:
        summary = await SUMMARIZER(old, language=lang)
    except Exception as exc:
        logger.warning("上下文压缩失败: %s", exc)
        raise HTTPException(status_code=502, detail=f"摘要失败：{exc}")
    new_transcript = context.merge_compressed(summary, recent)
    return storage.replace_transcript(username, session_id, new_transcript)


# ==========================================
# 预设：列表
# ==========================================
@app.get("/api/presets")
async def list_presets(username: str = Depends(get_current_user)):
    """
    返回当前用户的预设列表。
    Args:
        username: 当前用户名 (str)
    Returns:
        list: 预设列表
    """
    return storage.list_presets(username)


# ==========================================
# 预设：创建
# ==========================================
@app.post("/api/presets", status_code=201)
async def create_preset(body: PresetCreate, username: str = Depends(get_current_user)):
    """
    创建人设预设。
    Args:
        body: name 与 prompt (PresetCreate)
        username: 当前用户名 (str)
    Returns:
        dict: 新预设
    """
    return storage.create_preset(username, body.name, body.prompt)


# ==========================================
# 预设：删除
# ==========================================
@app.delete("/api/presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: str, username: str = Depends(get_current_user)):
    """
    删除预设。
    Args:
        preset_id: 预设 id (str)
        username: 当前用户名 (str)
    """
    if not storage.delete_preset(username, preset_id):
        raise HTTPException(status_code=404, detail="预设不存在")


# ==========================================
# 桥接类注入点（测试用假实现替换）
# ==========================================
BRIDGE_CLASS = RealtimeBridge

# 摘要器注入点（测试用假实现替换，避免发真实请求）
SUMMARIZER = context.summarize_old_turns

# 自动压缩阈值：上下文用量达到此值时自动触发压缩（约为上限的 80%）
AUTO_COMPRESS_THRESHOLD = int(CONTEXT_INPUT_LIMIT * 0.8)


# ==========================================
# 拼接下发给模型的完整指令：用户人设 + 固定板书指令
# ==========================================
def compose_instructions(persona: str) -> str:
    """
    板书指令固定在用户人设之后，人设编辑不受影响。
    Args:
        persona: 用户设置的 system prompt (str)
    Returns:
        str: 完整 instructions
    """
    return (persona or "") + BOARD_PROMPT


# ==========================================
# 自动压缩：检测语言 + 生成摘要 + 替换存储
# ==========================================
async def auto_compress_session(username: str, session: dict) -> list:
    """
    检测旧对话的主要语言，用同语言生成摘要，压缩后替换存储。
    Args:
        username: 当前用户名 (str)
        session: 当前会话记录 (dict)
    Returns:
        list: 压缩后的新对话历史
    Raises:
        Exception: 摘要生成失败
    """
    old, recent = context.split_old_recent(session["transcript"])
    if not old:
        return session["transcript"]
    old_text = "\n".join(item.get("text", "") for item in old)
    lang = context.detect_language(old_text)
    logger.info(
        "上下文超限（%d 字符），自动压缩（语言=%s）",
        sum(len(item.get("text", "")) for item in session["transcript"]),
        lang,
    )
    summary = await SUMMARIZER(old, language=lang)
    new_transcript = context.merge_compressed(summary, recent)
    storage.replace_transcript(username, session["id"], new_transcript)
    return new_transcript


# ==========================================
# 对话 WebSocket 端点
# ==========================================
@app.websocket("/ws/chat")
async def ws_chat(
    ws: WebSocket, auth_session_id: str = Cookie(None, alias=auth.SESSION_COOKIE_NAME)
):
    """
    对话主通道：一个浏览器连接对应一个活动会话。
    握手时从 cookie 验证用户身份，未登录则拒绝连接。
    前端消息：start / audio / update_settings / stop
    Args:
        ws: FastAPI WebSocket 连接
        auth_session_id: cookie 中的 session_id (str)
    """
    username = auth.get_user_by_session(auth_session_id) if auth_session_id else None
    if not username:
        await ws.close(code=4001, reason="未登录")
        return
    await ws.accept()
    bridge = None
    state = {"session_id": None, "compressing": False}

    async def send_to_client(msg: dict) -> None:
        """
        把消息推送给浏览器。
        Args:
            msg: 前端消息字典 (dict)
        """
        await ws.send_json(msg)

    # ==========================================
    # 辅助：创建并连接 bridge（start 和自动重连共用）
    # ==========================================
    async def _create_bridge(session: dict, history: list = None) -> None:
        """
        创建新的 RealtimeBridge 并连接 DashScope。
        使用闭包变量 bridge / state / username 等。
        Args:
            session: 当前会话记录 (dict)
            history: 注入的历史记录，缺省用 session["transcript"] (list)
        """
        nonlocal bridge
        creds = auth.decrypt_user_credentials(username)
        api_key = creds["api_key"]
        base_url = creds["base_url"]
        if not api_key:
            raise ValueError("未配置 API Key")
        instructions = compose_instructions(session["system_prompt"])
        output_mode = session["output_mode"]
        hist = history if history is not None else session["transcript"]
        logger.info(
            "创建新 bridge: api_key=%d chars, base_url=%s, history=%d items, output=%s",
            len(api_key), base_url[:50], len(hist), output_mode,
        )
        bridge = BRIDGE_CLASS(
            send_to_client=send_to_client,
            on_final_transcript=on_final_transcript,
            api_key=api_key,
            base_url=base_url,
        )
        logger.info("调用 bridge.connect()...")
        await bridge.connect(
            instructions=instructions,
            output_mode=output_mode,
            history=hist,
        )
        logger.info("bridge.connect() 完成")

    # ==========================================
    # 辅助：压缩后关闭旧 bridge 并重连（独立任务中执行）
    # ==========================================
    async def _reconnect_bridge(sid: str, new_transcript: list) -> None:
        """
        关闭旧 bridge 并用压缩后的历史重新连接，最多重试 3 次。
        必须以独立 asyncio 任务运行：on_final_transcript 回调发生在
        bridge 自己的接收循环任务内，若在回调里直接 close 会
        自我取消导致 RecursionError。
        Args:
            sid: 会话 id (str)
            new_transcript: 压缩后的对话历史 (list)
        """
        nonlocal bridge
        try:
            if bridge is not None:
                old = bridge
                bridge = None
                await old.close()
                logger.info("旧 bridge 已关闭")
            session = storage.get_session(username, sid)
            if session is None:
                logger.warning("压缩后 session 不存在: %s", sid)
                await send_to_client({
                    "type": "error",
                    "message": "压缩后会话丢失，请重新选择会话",
                })
                return
            for attempt in range(1, 4):
                try:
                    logger.info("重连尝试 %d/3...", attempt)
                    await _create_bridge(session, new_transcript)
                    logger.info("新 bridge 已连接")
                    chars = sum(len(i.get("text", "")) for i in new_transcript)
                    await send_to_client({
                        "type": "context_usage",
                        "chars": chars,
                        "count": len(new_transcript),
                    })
                    await send_to_client({"type": "auto_compressed"})
                    break
                except Exception as reconn_exc:
                    logger.warning("重连尝试 %d 失败: %s", attempt, reconn_exc)
                    if attempt < 3:
                        await asyncio.sleep(1 * attempt)
                    else:
                        await send_to_client({
                            "type": "error",
                            "message": f"上下文已压缩，但重新连接失败，请手动重新开始对话：{reconn_exc}",
                        })
        finally:
            state["compressing"] = False

    async def on_final_transcript(role: str, text: str) -> None:
        """
        最终转写落盘；推送最新上下文用量；首句用户发言自动命名会话。
        上下文超限时自动压缩并重连 bridge。
        Args:
            role: user 或 assistant (str)
            text: 转写文本 (str)
        """
        sid = state["session_id"]
        if not sid:
            return
        storage.append_transcript(username, sid, role, text)
        session = storage.get_session(username, sid)
        if session is None:
            return
        transcript = session["transcript"]
        chars = sum(len(item.get("text", "")) for item in transcript)
        await send_to_client({
            "type": "context_usage",
            "chars": chars,
            "count": len(transcript),
        })
        if role == "user" and session["title"] == "新对话":
            title = text.strip()[:20] or "新对话"
            storage.update_session(username, sid, title=title)
            await send_to_client({"type": "title", "value": title})
        # 上下文超限 → 自动压缩（compressing 标记防止重入）
        if chars > AUTO_COMPRESS_THRESHOLD and not state["compressing"]:
            state["compressing"] = True
            try:
                await send_to_client({"type": "compressing"})
                logger.info("开始自动压缩，session=%s, chars=%d", sid, chars)
                new_transcript = await auto_compress_session(username, session)
                logger.info(
                    "压缩完成: %d 条 → %d 条 (%d 字符)",
                    len(session["transcript"]),
                    len(new_transcript),
                    sum(len(i.get("text", "")) for i in new_transcript),
                )
            except Exception as exc:
                state["compressing"] = False
                logger.warning("自动压缩失败: %s", exc)
                await send_to_client({
                    "type": "error",
                    "message": f"自动压缩失败：{exc}",
                })
                return
            # 重连必须放到独立任务：本回调运行在 bridge 自己的
            # 接收循环任务里，直接 close 会自我取消（RecursionError）
            asyncio.create_task(_reconnect_bridge(sid, new_transcript))

    try:
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "start":
                if bridge is not None:
                    await bridge.close()
                sid = msg.get("session_id")
                session = storage.get_session(username, sid) if sid else None
                if session is None:
                    await send_to_client({"type": "error", "message": "会话不存在"})
                    continue
                state["session_id"] = sid
                creds = auth.decrypt_user_credentials(username)
                if not creds["api_key"]:
                    await send_to_client({
                        "type": "error",
                        "message": "未配置 API key，请先在设置中填写",
                    })
                    continue
                try:
                    await _create_bridge(session)
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
                sid = state["session_id"]
                system_prompt = msg.get("system_prompt")
                output_mode = msg.get("output_mode")
                session = storage.get_session(username, sid) if sid else None
                if session is not None:
                    fields = {}
                    if system_prompt is not None:
                        fields["system_prompt"] = system_prompt
                    if output_mode is not None:
                        fields["output_mode"] = output_mode
                    if fields:
                        session = storage.update_session(username, sid, **fields)
                # 回读存储的会话，缺省字段不会被清空（修复只改输出模式
                # 时清空人设的问题）；板书指令固定拼接在人设之后
                if bridge is not None and session is not None:
                    await bridge.update_session(
                        compose_instructions(session["system_prompt"]),
                        session["output_mode"],
                    )
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
