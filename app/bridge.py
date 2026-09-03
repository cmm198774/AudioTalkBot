# ==========================================
# DashScope Realtime WebSocket 桥接：管理一个实时对话连接
# 上行：浏览器音频 → input_audio_buffer.append
# 下行：服务端事件分流 → 音频/字幕/黑板/打断/状态/错误
#
# 板书段解析：模型回复中 [start]...[end] 包裹的内容只写黑板不朗读。
# 文本流按标记切成字幕/黑板两路；音频流按"文本领先音频"的时间差把
# 黑板窗口对应的音频丢弃（模型被要求在窗口前后停顿，容忍切割误差）。
# ==========================================
import asyncio
import json
import logging
import ssl
import time

import certifi
from websockets.asyncio.client import connect as ws_connect

from app.config import DASHSCOPE_WS_URL, OUTPUT_MODE_MODALITIES, get_api_key
from app.protocol import build_audio_append, build_history_events, build_session_update

logger = logging.getLogger(__name__)

# 板书段标记：模型用 [start]/[end] 包裹黑板内容，该段只写不读
_START_MARKER = "[start]"
_END_MARKER = "[end]"
_MARKERS = (_START_MARKER, _END_MARKER)

# 无法测量文本领先量时的缺省值（实测约 0.65~1.1 秒）
_DEFAULT_LEAD = 0.8

# 窗口边界容差（秒）：音频块有百毫秒量级时长，且浮点换算有误差，
# 窗口两侧各放宽一点，模型又被要求在窗口前后停顿，容差不会误伤语音
_WINDOW_PAD = 0.05

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
# 计算可暂留的标记前缀尾巴长度
# ==========================================
def _holdable_suffix_len(text: str) -> int:
    """
    返回 text 末尾"可能是某个标记前缀"的最长尾巴长度。
    标记可能跨多个增量切分（如先收到 [st 后收到 art]），
    把可疑尾巴暂留缓冲，避免碎片泄漏到字幕或黑板。
    Args:
        text: 当前待发布的累积文本 (str)
    Returns:
        int: 应暂留的尾巴长度；0 表示没有碎片嫌疑
    """
    best = 0
    for marker in _MARKERS:
        upper = min(len(text), len(marker) - 1)
        for k in range(upper, 0, -1):
            if text.endswith(marker[:k]):
                if k > best:
                    best = k
                break
    return best


# ==========================================
# 实时对话桥接器
# ==========================================
class RealtimeBridge:
    """
    管理一条 DashScope Realtime 连接，把服务端事件翻译成前端消息。
    前端消息格式：
        audio / interrupt / transcript / board / state / error
    """

    def __init__(self, send_to_client, on_final_transcript=None, api_key: str = "",
                 ws_factory=None, clock=None):
        """
        初始化桥接器。
        Args:
            send_to_client: 异步回调，把 dict 消息发给浏览器 (callable)
            on_final_transcript: 异步回调 (role, text)，最终转写落盘用 (callable)
            api_key: DashScope API key，缺省读环境变量 (str)
            ws_factory: 可注入的 WS 连接工厂，测试用 (callable)
            clock: 返回当前秒数的可调用对象，缺省 time.monotonic，测试可注入假时钟 (callable)
        """
        self._send_to_client = send_to_client
        self._on_final_transcript = on_final_transcript
        self._api_key = api_key or get_api_key()
        self._ws_factory = ws_factory or self._default_ws_factory
        self._clock = clock or time.monotonic
        self._ws = None
        self._recv_task = None
        self._speaking = False
        self._reset_turn()

    # ==========================================
    # 回合级段解析状态复位
    # ==========================================
    def _reset_turn(self) -> None:
        """
        复位一个回合内的所有段解析状态（响应开始/结束时调用）。
        """
        self._assistant_text = ""   # 原始累积文本（含标记），用于持久化
        self._seg = "text"          # 当前所处段：text 字幕 / board 黑板
        self._buf = ""              # 已累积但尚未发布的文本尾巴
        self._seg_emitted = False   # 当前黑板段是否已发出过内容（首块带 new_segment）
        self._windows = []          # 黑板时间窗口列表 [[start, end|None], ...]
        self._t_first_text = None   # 本回合首个文本增量时刻
        self._t_first_audio = None  # 本回合首个音频增量时刻

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
            self._reset_turn()
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
    # 内部：回复音频增量（黑板窗口内丢弃）
    # ==========================================
    async def _handle_audio_delta(self, event: dict) -> None:
        """
        转发音频增量；落在黑板时间窗口内的音频直接丢弃，
        形成"老师写黑板时自然停顿"的效果。
        Args:
            event: response.audio.delta 事件 (dict)
        """
        delta = event.get("delta", "")
        if not delta:
            return
        now = self._clock()
        if self._t_first_audio is None:
            self._t_first_audio = now
        if self._in_board_window(now):
            return
        if not self._speaking:
            self._speaking = True
            await self._emit({"type": "state", "value": "speaking"})
        await self._emit({"type": "audio", "data": delta})

    # ==========================================
    # 内部：判断音频时刻是否落在黑板窗口
    # ==========================================
    def _in_board_window(self, audio_time: float) -> bool:
        """
        音频时间减去"文本领先量"换算成文本时间，
        落在任一 [start, end] 窗口内即视为黑板内容对应的语音。
        Args:
            audio_time: 音频增量到达时刻（秒）(float)
        Returns:
            bool: True 表示该音频应被丢弃
        """
        if not self._windows:
            return False
        if self._t_first_text is None or self._t_first_audio is None:
            lead = _DEFAULT_LEAD
        else:
            lead = max(0.0, self._t_first_audio - self._t_first_text)
        text_time = audio_time - lead
        for start, end in self._windows:
            if end is None:
                if text_time >= start - _WINDOW_PAD:
                    return True
            elif start - _WINDOW_PAD <= text_time <= end + _WINDOW_PAD:
                return True
        return False

    # ==========================================
    # 内部：回复文本增量（段解析入口）
    # ==========================================
    async def _handle_transcript_delta(self, event: dict) -> None:
        """
        累积文本增量并驱动段解析：标记前内容按当前段发布，
        遇到标记切换段并记录黑板时间窗口。
        Args:
            event: 字幕/文本增量事件 (dict)
        """
        delta = event.get("delta", "")
        if not delta:
            return
        now = self._clock()
        if self._t_first_text is None:
            self._t_first_text = now
        self._assistant_text += delta
        self._buf += delta
        await self._drain_buf()

    # ==========================================
    # 内部：按标记排空缓冲区
    # ==========================================
    async def _drain_buf(self) -> None:
        """
        循环处理缓冲区：找到当前段对应的标记时，发布标记前内容并切段；
        找不到完整标记时，只发布不可能属于标记前缀的部分，
        尾巴留给下一个增量继续拼。
        """
        while True:
            marker = _START_MARKER if self._seg == "text" else _END_MARKER
            idx = self._buf.find(marker)
            if idx >= 0:
                pre = self._buf[:idx]
                if pre:
                    await self._emit_seg(pre)
                self._buf = self._buf[idx + len(marker):]
                self._flip_segment()
                continue
            hold_len = _holdable_suffix_len(self._buf)
            emit_len = len(self._buf) - hold_len
            if emit_len > 0:
                chunk = self._buf[:emit_len]
                self._buf = self._buf[emit_len:]
                await self._emit_seg(chunk)
            break

    # ==========================================
    # 内部：在标记处切换段状态
    # ==========================================
    def _flip_segment(self) -> None:
        """
        字幕段遇 [start] 切到黑板段并开窗；黑板段遇 [end] 切回并关窗。
        """
        now = self._clock()
        if self._seg == "text":
            self._seg = "board"
            self._seg_emitted = False
            self._windows.append([now, None])
        else:
            self._seg = "text"
            if self._windows and self._windows[-1][1] is None:
                self._windows[-1][1] = now

    # ==========================================
    # 内部：按当前段发布一段文本
    # ==========================================
    async def _emit_seg(self, chunk: str) -> None:
        """
        黑板段发到黑板（该段首块带 new_segment 标记），字幕段发到字幕。
        Args:
            chunk: 要发布的文本片段 (str)
        """
        if self._seg == "board":
            msg = {"type": "board", "delta": chunk}
            if not self._seg_emitted:
                msg["new_segment"] = True
                self._seg_emitted = True
            await self._emit(msg)
        else:
            await self._emit({"type": "transcript", "role": "assistant", "delta": chunk, "final": False})

    # ==========================================
    # 内部：回合结束
    # ==========================================
    async def _handle_response_done(self) -> None:
        """
        回合结束：把未决的标记碎片按当前段补发，持久化原始累积文本
        （含 [start]/[end] 标记，历史渲染时再拆分），复位回合状态。
        """
        self._speaking = False
        if self._buf:
            chunk = self._buf
            self._buf = ""
            await self._emit_seg(chunk)
        if self._assistant_text and self._on_final_transcript is not None:
            await self._on_final_transcript("assistant", self._assistant_text)
        self._reset_turn()
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
