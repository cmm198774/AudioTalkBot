# ==========================================
# DashScope Realtime WebSocket 桥接：管理一个实时对话连接
# 上行：浏览器音频 → input_audio_buffer.append
# 下行：服务端事件分流 → 音频/字幕/打断/状态/错误
# ==========================================
import asyncio
import json
import logging
import ssl

import certifi
from websockets.asyncio.client import connect as ws_connect

from app.config import DASHSCOPE_WS_URL, OUTPUT_MODE_MODALITIES, get_api_key
from app.protocol import build_audio_append, build_history_events, build_session_update

logger = logging.getLogger(__name__)

# 板书回合标记：模型以该前缀开头的回复视为板书，内容上黑板、语音掐断
_BOARD_MARKER = "[text]:"

# 已知但无需处理的服务端事件类型
_IGNORED_EVENTS = (
    "session.created",
    "session.updated",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.committed",
    "response.output_item.added",
    "response.output_item.done",
    "response.content_part.added",
    "response.content_part.done",
    "response.audio.done",
    "response.audio_transcript.done",
    "response.text.done",
)


# ==========================================
# 构造使用 certifi 证书的 SSL 上下文
# ==========================================
def _build_ssl_context() -> ssl.SSLContext:
    """
    本环境的默认证书上下文加载会失败，需显式用 certifi 证书构造。
    Returns:
        ssl.SSLContext: 已加载 CA 证书的客户端上下文
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(certifi.where())
    return ctx


# ==========================================
# 实时对话桥接器
# ==========================================
class RealtimeBridge:
    """
    管理一条 DashScope Realtime 连接，把服务端事件翻译成前端消息。
    前端消息格式见设计文档 6.3 节：
        audio / interrupt / transcript / state / error
    """

    def __init__(self, send_to_client, on_final_transcript=None, api_key: str = "", ws_factory=None):
        """
        初始化桥接器。
        Args:
            send_to_client: 异步回调，把 dict 消息发给浏览器 (callable)
            on_final_transcript: 异步回调 (role, text)，最终转写落盘用 (callable)
            api_key: DashScope API key，缺省读环境变量 (str)
            ws_factory: 可注入的 WS 连接工厂，测试用 (callable)
        """
        self._send_to_client = send_to_client
        self._on_final_transcript = on_final_transcript
        self._api_key = api_key or get_api_key()
        self._ws_factory = ws_factory or self._default_ws_factory
        self._ws = None
        self._recv_task = None
        self._assistant_text = ""
        self._speaking = False
        # 板书回合检测状态（按回合复位）
        self._board_mode = False
        self._board_decided = False
        self._pending_deltas = []

    # ==========================================
    # 默认 WebSocket 工厂（生产路径）
    # ==========================================
    async def _default_ws_factory(self, url: str, headers: dict):
        """
        建立真实的 DashScope WebSocket 连接。
        Args:
            url: WebSocket 地址 (str)
            headers: 握手头，含 Authorization (dict)
        Returns:
            WebSocket 连接对象
        """
        return await ws_connect(url, additional_headers=headers, ssl=_build_ssl_context())

    # ==========================================
    # 建立连接并配置会话
    # ==========================================
    async def connect(self, instructions: str, output_mode: str, history=None) -> None:
        """
        连接 DashScope，发送 session.update，可选注入历史，然后启动接收循环。
        Args:
            instructions: system prompt (str)
            output_mode: audio / text / audio_text (str)
            history: 历史对话记录列表，用于恢复上下文 (list)
        """
        modalities = OUTPUT_MODE_MODALITIES.get(output_mode, ["text", "audio"])
        headers = {"Authorization": f"Bearer {self._api_key}"}
        self._ws = await self._ws_factory(DASHSCOPE_WS_URL, headers)
        await self._send_event(build_session_update(instructions, modalities))
        if history:
            for event in build_history_events(history):
                await self._send_event(event)
        self._recv_task = asyncio.create_task(self._recv_loop())

    # ==========================================
    # 上行：发送音频块
    # ==========================================
    async def send_audio(self, b64_audio: str) -> None:
        """
        转发一个音频块到 DashScope。
        Args:
            b64_audio: base64 编码的 PCM (str)
        """
        if self._ws is not None:
            await self._send_event(build_audio_append(b64_audio))

    # ==========================================
    # 热更新：重发 session.update（修改 prompt / 输出模式）
    # ==========================================
    async def update_session(self, instructions: str, output_mode: str) -> None:
        """
        不重连的情况下更新会话配置。
        Args:
            instructions: 新的 system prompt (str)
            output_mode: 新的输出模式 (str)
        """
        if self._ws is None:
            return
        modalities = OUTPUT_MODE_MODALITIES.get(output_mode, ["text", "audio"])
        await self._send_event(build_session_update(instructions, modalities))

    # ==========================================
    # 关闭连接与接收任务
    # ==========================================
    async def close(self) -> None:
        """
        取消接收任务并关闭 WebSocket。
        """
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    # ==========================================
    # 测试辅助：等待接收循环处理完脚本事件
    # ==========================================
    async def wait_recv_done(self) -> None:
        """
        等待接收任务自然结束（仅 FakeWebSocket 场景有意义）。
        """
        if self._recv_task is not None:
            await self._recv_task
            self._recv_task = None

    # ==========================================
    # 内部：发送事件
    # ==========================================
    async def _send_event(self, event: dict) -> None:
        """
        序列化事件并通过 WebSocket 发送。
        Args:
            event: 事件字典 (dict)
        """
        await self._ws.send(json.dumps(event, ensure_ascii=False))

    # ==========================================
    # 内部：向前端发消息
    # ==========================================
    async def _emit(self, msg: dict) -> None:
        """
        向前端发送一条消息。
        Args:
            msg: 前端消息字典 (dict)
        """
        await self._send_to_client(msg)

    # ==========================================
    # 内部：接收循环
    # ==========================================
    async def _recv_loop(self) -> None:
        """
        持续读取服务端事件并分流处理；连接异常时通知前端。
        """
        try:
            async for raw in self._ws:
                event = json.loads(raw)
                await self._handle_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("DashScope 连接异常: %s", exc)
            await self._emit({"type": "error", "message": f"连接已断开：{exc}"})

    # ==========================================
    # 内部：事件分流
    # ==========================================
    async def _handle_event(self, event: dict) -> None:
        """
        按事件类型分发处理。
        Args:
            event: 服务端事件字典 (dict)
        """
        etype = event.get("type", "")
        if etype == "response.audio.delta":
            await self._handle_audio_delta(event)
        elif etype in ("response.audio_transcript.delta", "response.text.delta"):
            await self._handle_transcript_delta(event)
        elif etype == "input_audio_buffer.speech_started":
            self._speaking = False
            await self._emit({"type": "interrupt"})
            await self._emit({"type": "state", "value": "listening"})
        elif etype == "response.created":
            self._board_mode = False
            self._board_decided = False
            self._pending_deltas = []
            await self._emit({"type": "state", "value": "thinking"})
        elif etype == "response.done":
            await self._handle_response_done()
        elif etype == "conversation.item.input_audio_transcription.completed":
            await self._handle_user_transcript(event)
        elif etype == "error":
            err = event.get("error", {})
            await self._emit({"type": "error", "message": err.get("message", str(err))})
        elif etype in _IGNORED_EVENTS:
            pass
        else:
            logger.debug("未处理的事件类型: %s", etype)

    # ==========================================
    # 内部：回复音频增量
    # ==========================================
    async def _handle_audio_delta(self, event: dict) -> None:
        """
        转发音频增量，首次到达时切换 speaking 状态；板书回合直接丢弃。
        Args:
            event: response.audio.delta 事件 (dict)
        """
        if self._board_mode:
            return
        delta = event.get("delta", "")
        if not delta:
            return
        if not self._speaking:
            self._speaking = True
            await self._emit({"type": "state", "value": "speaking"})
        await self._emit({"type": "audio", "data": delta})

    # ==========================================
    # 内部：回复文本增量（字幕）
    # ==========================================
    async def _handle_transcript_delta(self, event: dict) -> None:
        """
        转发字幕增量并累积到当前回合缓冲；同时判定是否为板书回合。
        未判定前增量先暂存，避免字幕漏出 [tex… 碎片。
        Args:
            event: 字幕/文本增量事件 (dict)
        """
        delta = event.get("delta", "")
        if not delta:
            return
        self._assistant_text += delta

        # 已判定为板书回合：增量全部路由到黑板
        if self._board_mode:
            await self._emit({"type": "board", "delta": delta})
            return

        # 已判定为普通回合：正常转发字幕
        if self._board_decided:
            await self._emit({"type": "transcript", "role": "assistant", "delta": delta, "final": False})
            return

        # 未判定：暂存增量，用累积文本（忽略前导空白）比对板书标记
        self._pending_deltas.append(delta)
        acc = self._assistant_text.lstrip()
        if acc.startswith(_BOARD_MARKER):
            await self._enter_board_mode()
            return
        if not _BOARD_MARKER.startswith(acc):
            await self._decide_normal_turn()

    # ==========================================
    # 内部：确认进入板书回合
    # ==========================================
    async def _enter_board_mode(self) -> None:
        """
        掐断本回合语音并把暂存增量（去掉标记）送上黑板。
        """
        self._board_mode = True
        self._board_decided = True
        # 清空前端可能已排队的音频（双保险）
        await self._emit({"type": "interrupt"})
        full = "".join(self._pending_deltas)
        self._pending_deltas = []
        stripped = full.lstrip()[len(_BOARD_MARKER):]
        if stripped:
            await self._emit({"type": "board", "delta": stripped})

    # ==========================================
    # 内部：确认为普通回合并补发暂存增量
    # ==========================================
    async def _decide_normal_turn(self) -> None:
        """
        把判定期暂存的增量按序补发为字幕。
        """
        self._board_decided = True
        for held in self._pending_deltas:
            await self._emit({"type": "transcript", "role": "assistant", "delta": held, "final": False})
        self._pending_deltas = []

    # ==========================================
    # 内部：回合结束
    # ==========================================
    async def _handle_response_done(self) -> None:
        """
        回合结束：补发未判定的暂存增量，持久化累积的助手回复（板书回合含
        [text]: 原文），复位回合状态。
        """
        self._speaking = False
        if not self._board_decided and self._pending_deltas:
            for held in self._pending_deltas:
                await self._emit({"type": "transcript", "role": "assistant", "delta": held, "final": False})
        self._pending_deltas = []
        self._board_decided = False
        self._board_mode = False
        if self._assistant_text and self._on_final_transcript is not None:
            await self._on_final_transcript("assistant", self._assistant_text)
        self._assistant_text = ""
        await self._emit({"type": "state", "value": "listening"})

    # ==========================================
    # 内部：用户语音转写完成
    # ==========================================
    async def _handle_user_transcript(self, event: dict) -> None:
        """
        转发用户最终转写并持久化。
        Args:
            event: input_audio_transcription.completed 事件 (dict)
        """
        text = event.get("transcript", "")
        if not text:
            return
        await self._emit({"type": "transcript", "role": "user", "delta": text, "final": True})
        if self._on_final_transcript is not None:
            await self._on_final_transcript("user", text)
